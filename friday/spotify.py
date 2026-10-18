"""Spotify conectado à conta do usuário (Web API, login PKCE: sem senha e sem segredo guardado aqui).

Cada pessoa conecta a própria conta pelas Configurações do Orbit → Contas. O app do Spotify (Client ID) é criado uma
vez em developer.spotify.com, com o endereço de retorno REDIRECT abaixo. Dá a fila de reprodução e "põe na fila".
"""
import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path

from .tools_common import fn
from .paths import MEMORIA

log = logging.getLogger("friday.spotify")

TOKEN_FILE = MEMORIA / "spotify_token.json"
CONF_FILE = MEMORIA / "spotify.json"
REDIRECT = f"http://127.0.0.1:{os.getenv('ORBIT_PORT', '8788')}/orbit/spotify/callback"
SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"

_pending: dict[str, dict] = {}  # state -> {"verifier", "t"}


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def client_id() -> str:
    return os.getenv("SPOTIFY_CLIENT_ID", "") or _read(CONF_FILE).get("client_id", "")


def set_client_id(cid: str) -> None:
    CONF_FILE.write_text(json.dumps({"client_id": cid.strip()}), encoding="utf-8")


def connected() -> bool:
    return bool(_read(TOKEN_FILE).get("refresh_token"))


def status() -> dict:
    t = _read(TOKEN_FILE)
    return {"client_id": bool(client_id()), "connected": bool(t.get("refresh_token")), "user": t.get("user", ""),
            "redirect": REDIRECT}


def auth_url() -> str:
    cid = client_id()
    if not cid:
        raise RuntimeError("Falta o Client ID do app do Spotify.")
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    _pending[state] = {"verifier": verifier, "t": time.time()}
    return "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": cid, "response_type": "code", "redirect_uri": REDIRECT, "scope": SCOPES,
        "code_challenge_method": "S256", "code_challenge": challenge, "state": state})


def _token_request(data: dict) -> dict:
    req = urllib.request.Request("https://accounts.spotify.com/api/token", data=urllib.parse.urlencode(data).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _save(tok: dict) -> None:
    old = _read(TOKEN_FILE)
    tok["refresh_token"] = tok.get("refresh_token") or old.get("refresh_token")
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    tok["user"] = tok.get("user") or old.get("user", "")
    TOKEN_FILE.write_text(json.dumps(tok), encoding="utf-8")


def finish(code: str, state: str) -> str:
    p = _pending.pop(state, None)
    if not p or time.time() - p["t"] > 600:
        raise RuntimeError("Pedido de login expirado. Tente conectar de novo.")
    tok = _token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
                          "client_id": client_id(), "code_verifier": p["verifier"]})
    _save(tok)
    try:
        me = _api("GET", "/me")
        t = _read(TOKEN_FILE)
        t["user"] = me.get("display_name") or me.get("id", "")
        TOKEN_FILE.write_text(json.dumps(t), encoding="utf-8")
        return t["user"]
    except Exception:
        return ""


def disconnect() -> None:
    TOKEN_FILE.unlink(missing_ok=True)


def _access() -> str:
    t = _read(TOKEN_FILE)
    if not t.get("refresh_token"):
        raise RuntimeError("Spotify não conectado.")
    if time.time() >= t.get("expires_at", 0):
        _save(_token_request({"grant_type": "refresh_token", "refresh_token": t["refresh_token"], "client_id": client_id()}))
        t = _read(TOKEN_FILE)
    return t["access_token"]


def _api(method: str, path: str, params: dict | None = None):
    url = "https://api.spotify.com/v1" + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, method=method, headers={"Authorization": "Bearer " + _access()},
                                 data=b"" if method in ("POST", "PUT") else None)
    with urllib.request.urlopen(req, timeout=10) as r:
        body = r.read()
        return json.loads(body) if body else {}


def _track(t: dict | None) -> dict | None:
    if not t:
        return None
    imgs = (t.get("album") or {}).get("images") or (t.get("images") or [])
    return {"name": t.get("name", ""), "artist": ", ".join(a["name"] for a in t.get("artists", [])) or (t.get("show") or {}).get("name", ""),
            "art": imgs[-1]["url"] if imgs else "", "uri": t.get("uri", ""), "duration": (t.get("duration_ms") or 0) / 1000}


def now() -> dict:
    """Posição exata do que toca agora (a do Windows atrasa e pula; a letra sincronizada precisa desta)."""
    r = _api("GET", "/me/player/currently-playing") or {}
    item = r.get("item") or {}
    return {"progress": (r.get("progress_ms") or 0) / 1000, "playing": bool(r.get("is_playing")), "name": item.get("name", ""),
            "duration": (item.get("duration_ms") or 0) / 1000, "at": time.time()}


def queue() -> dict:
    q = _api("GET", "/me/player/queue")
    try:  # de onde vem o que toca (playlist/álbum): com isso, escolher na fila é um pedido só
        ctx = ((_api("GET", "/me/player/currently-playing") or {}).get("context") or {}).get("uri", "")
    except Exception:
        ctx = ""
    return {"now": _track(q.get("currently_playing")), "context": ctx,
            "queue": [x for x in map(_track, q.get("queue", [])[:20]) if x]}


def add_to_queue(query: str) -> str:
    """Procura a música e põe na fila do Spotify."""
    try:
        r = _api("GET", "/search", {"q": query, "type": "track", "limit": 1, "market": "from_token"})
        items = r.get("tracks", {}).get("items", [])
        if not items:
            return f"Não achei '{query}' no Spotify."
        t = _track(items[0])
        _api("POST", "/me/player/queue", {"uri": t["uri"]})
        return f"Na fila: {t['name']} — {t['artist']}."
    except RuntimeError as e:
        return str(e)
    except urllib.error.HTTPError as e:
        return "O Spotify precisa estar tocando em algum aparelho para usar a fila." if e.code == 404 else f"O Spotify recusou ({e.code})."


def _api_json(method: str, path: str, body: dict):
    req = urllib.request.Request("https://api.spotify.com/v1" + path, method=method, data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + _access(), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()


def play_from_queue(uri: str, context: str = "") -> str:
    """Toca a música escolhida na fila.

    Se o que toca vem de uma playlist ou álbum, toca dentro dele a partir dessa música (a fila continua igual).
    Senão, avança música por música, conferindo a cada passo, até chegar nela (pular "N vezes" errava a música)."""
    ctx = context
    cur = {} if ctx else (_api("GET", "/me/player/currently-playing") or {})
    ctx = ctx or (cur.get("context") or {}).get("uri", "")
    if ctx and ctx.split(":")[1] in ("playlist", "album"):
        try:
            _api_json("PUT", "/me/player/play", {"context_uri": ctx, "offset": {"uri": uri}})
            return "Tocando."
        except urllib.error.HTTPError:
            cur = cur or (_api("GET", "/me/player/currently-playing") or {})  # não está nesse contexto (fila manual): avança
    for _ in range(25):
        _api("POST", "/me/player/next")
        for _ in range(8):  # espera o Spotify trocar de faixa
            time.sleep(0.25)
            now = (_api("GET", "/me/player/currently-playing") or {}).get("item") or {}
            if now.get("uri") and now.get("uri") != (cur.get("item") or {}).get("uri"):
                break
        if now.get("uri") == uri:
            return "Tocando."
        cur = {"item": now}
    return "Não achei essa música na fila."


def spotify_queue(query: str = "") -> str:
    """Para a IA: sem query = diz o que vem na fila; com query = põe na fila."""
    if query:
        return add_to_queue(query)
    try:
        q = queue()
    except Exception as e:
        return f"Não consegui ler a fila do Spotify: {e}"
    if not q["queue"]:
        return "A fila do Spotify está vazia."
    return "Próximas no Spotify: " + "; ".join(f"{t['name']} ({t['artist']})" for t in q["queue"][:5]) + "."


TOOLS = {"spotify_queue": spotify_queue}
SCHEMAS = [
    fn("spotify_queue", "Fila do Spotify: sem query diz as próximas músicas; com query procura e põe a música na fila "
       "('coloca Bohemian Rhapsody na fila').", {"query": {"type": "string", "description": "Música e/ou artista"}}),
]
