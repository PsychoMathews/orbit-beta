"""Orbit no celular: app web instalável (PWA) servido pela assistente, com push no iPhone.

Servidor em 127.0.0.1:MOBILE_PORT. Para o celular alcançar, o Tailscale publica só na rede dos seus aparelhos:
  tailscale serve --bg --https=8443 http://127.0.0.1:8790
Os arquivos do app ficam em orbit/mobile/ (e os ícones em orbit/shared/icons.js).

Segurança: cada aparelho é pareado uma vez com um código de 6 letras (gerado pela ferramenta phone_pair ou
mostrado no log quando ainda não há aparelho). Depois disso o app guarda um cookie; sem ele, a API recusa.
Pedidos que mudam algo (POST) também precisam vir do próprio app (cabeçalho Origin do mesmo endereço).

Avisos: tudo que a assistente avisa (orbit.publish "notify") entra no histórico do app e vira push no iPhone
quando você não está mexendo no PC há MOBILE_PUSH_IDLE segundos (ou sempre, se ligado no app).
"""
import asyncio
import base64
import ctypes
import hashlib
import json
import logging
import os
import re
import secrets
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from aiohttp import web

from . import assistente, orbit
from .paths import APP_DIR, MEMORIA
from .tools_common import fn

log = logging.getLogger("friday.mobile")

PORT = int(os.getenv("MOBILE_PORT", "8790"))
PUSH_IDLE = int(os.getenv("MOBILE_PUSH_IDLE", "120"))
PUSH_SUB = os.getenv("MOBILE_PUSH_SUB", "mailto:orbit@example.com")  # contato exigido pelo padrão de push
WEB = APP_DIR / "orbit" / "mobile"
SHARED = APP_DIR / "orbit" / "shared"
STATE = MEMORIA / "celular.json"
VAPID = MEMORIA / ".vapid.pem"
FEED = MEMORIA / "avisos_celular.json"
DOWNLOADS = Path.home() / "Downloads"
UPLOADS = DOWNLOADS / "Do celular"
SILENT_KINDS = {"mute", "error"}  # avisos que não vão para o celular
COOKIE = "orbit_dev"

_loop: asyncio.AbstractEventLoop | None = None


# ---------- Estado: aparelhos pareados, assinaturas de push, código de pareamento ----------

def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"devices": {}, "subs": [], "code": None, "always_push": False}


def _save(s: dict) -> None:
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_code() -> str:
    s = _load()
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
    s["code"], s["code_until"] = code, time.time() + 15 * 60
    _save(s)
    return code


# Ação para o celular executar depois de falar a resposta (o Atalho da Siri abre este link: Waze, Spotify...).
_action = {"url": ""}


def action(url: str) -> None:
    _action["url"] = url


def with_city(address: str) -> str:
    """Endereço sem cidade ganha a cidade dele (HOME_CITY): rua com nome repetido em outra cidade levava ao lugar errado."""
    from . import config
    city = config.HOME_CITY
    if not city or city.casefold() in address.casefold() or re.search(r",\s*[A-Za-zÀ-ÿ .]+\s*[-/]\s*[A-Z]{2}\b|\b(SP|RJ|MG|PR|SC|RS|BA)\b", address):
        return address
    return f"{address}, {city}"


def open_waze(destino: str) -> str:
    """Para a IA: rota no Waze do celular."""
    import urllib.parse
    action("https://waze.com/ul?" + urllib.parse.urlencode({"q": with_city(destino), "navigate": "yes"}))
    return f"Rota para {destino} pronta: o Waze abre no celular."


# Apps do iPhone que o Atalho consegue abrir (endereço próprio de cada app).
PHONE_APPS = {
    "spotify": "spotify://", "waze": "waze://", "whatsapp": "whatsapp://", "youtube": "youtube://",
    "instagram": "instagram://", "telegram": "tg://", "mapas": "maps://", "maps": "maps://", "google maps": "comgooglemaps://",
    "uber": "uber://", "99": "taxi99://", "ifood": "ifood://", "netflix": "nflx://", "gmail": "googlegmail://",
    "x": "twitter://", "twitter": "twitter://", "notas": "mobilenotes://", "calendário": "calshow://", "agenda": "calshow://",
    "música": "music://", "apple music": "music://", "podcasts": "podcasts://", "fotos": "photos-redirect://",
    "câmera": "camera://", "relógio": "clock-alarm://", "ajustes": "app-settings:", "orbit": "",
}


def open_phone_app(app: str) -> str:
    """Para a IA: abre um app no celular (quando ele fala pelo Atalho da Siri, longe do PC)."""
    key = app.strip().lower().removeprefix("o ").removeprefix("a ")
    url = PHONE_APPS.get(key) or next((v for k, v in PHONE_APPS.items() if k in key or key in k), None)
    if url is None:
        return f"Não sei abrir {app} no celular. Apps que eu abro: " + ", ".join(sorted({k for k in PHONE_APPS if k != 'orbit'})) + "."
    if url:
        action(url)
    return f"Abrindo {app} no celular."


# ---------- Atalho: comandos diretos respondidos na hora, sem o Claude pensar ----------


def _people() -> dict:
    """Números da nota Pessoas do cofre: linhas "- **Nome**: ... Tel: +55 11 91234-5678"."""
    from . import vault
    out = {}
    try:
        for line in (vault.VAULT / "Pessoas.md").read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*-\s*\*\*(.+?)\*\*", line)
            tel = re.search(r"(?:tel|telefone|celular|whats(?:app)?|n[uú]mero)\s*:?\s*(\+?[\d\s().-]{8,})", line, re.I)
            if m and tel:
                digits = re.sub(r"\D", "", tel.group(1))
                out[m.group(1).strip()] = digits if len(digits) > 11 else "55" + digits  # sem DDI: Brasil
    except Exception:
        log.debug("Pessoas sem números", exc_info=True)
    return out


def _person_address(name: str) -> str:
    """Endereço de alguém na nota Pessoas ("- **Nome**: ... Endereço: Rua X, 10, Bairro")."""
    from . import vault
    want = name.strip().casefold()
    try:
        for line in (vault.VAULT / "Pessoas.md").read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*-\s*\*\*(.+?)\*\*", line)
            addr = re.search(r"endere[cç]o\s*:\s*([^;|]+?)(?:\s+(?:tel|telefone|celular|anivers[aá]rio)\b|$)", line, re.I)
            if m and addr and (m.group(1).casefold() == want or m.group(1).casefold().startswith(want)):
                return addr.group(1).strip(" .")
    except Exception:
        log.debug("Pessoas sem endereço", exc_info=True)
    return ""


def _person(name: str) -> tuple[str, str] | None:
    want = name.strip().casefold()
    people = _people()
    hit = next((k for k in people if k.casefold() == want), None) or next((k for k in people if k.casefold().startswith(want) or want in k.casefold()), None)
    return (hit, people[hit]) if hit else None


_waiting_msg = {"who": "", "t": 0.0}  # "O que eu digo para X?": a resposta seguinte vira a mensagem (por 2 min)


def quick(text: str) -> tuple[str, str] | None:
    """(fala, abrir) para pedidos diretos; None = segue para o Claude."""
    import urllib.parse
    from . import spotify
    t = re.sub(r"^\s*(sexta[- ]feira|friday|fala friday|chama friday)[,!.\s]*", "", text.strip(), flags=re.I).rstrip(" .!?")
    low = t.casefold()
    # mensagem: "manda uma mensagem pra Vitória dizendo que eu tô indo" (também "abre o whatsapp e manda...")
    m = re.search(r"(?:manda|mande|envia|envie|mandar)\s+(?:uma\s+)?(?:mensagem|msg|zap|whats(?:app)?)\s+(?:no whats(?:app)?\s+)?(?:pra|para|pro|pros|pras)\s+(?:a\s+|o\s+)?"
                  r"(?P<who>[\wÀ-ÿ]+)(?P<rest>.*)$", t, re.I)
    if m:
        # Sobrenome só se a palavra seguinte começar com maiúscula e não for conector ("Vitória dizendo que...").
        who, rest = m.group("who"), m.group("rest")
        nxt = re.match(r"\s+([A-ZÀ-Ý][\wÀ-ÿ]+)", rest)
        if nxt and nxt.group(1).casefold() not in ("que", "dizendo", "falando", "e", "avisando", "diz", "fala"):
            who, rest = f"{who} {nxt.group(1)}", rest[nxt.end():]
        msg = re.sub(r"^[,\s]*(?:e\s+)?(?:(?:diz|dizendo|fala|falando|falar|dizer|avisa|avisando)\s+)?(?:que\s+)?", "", rest, flags=re.I).strip()
        p = _person(who)
        if not msg:
            _waiting_msg.update(who=who, t=time.time())  # a próxima fala dele é a mensagem
            return f"O que eu digo para {who}?", ""
        q = urllib.parse.quote(msg)
        if p:
            return f"Mensagem para {p[0]} pronta no WhatsApp. É só tocar em enviar.", f"whatsapp://send?phone={p[1]}&text={q}"
        return f"Não tenho o número de {who}. Abri o WhatsApp com a mensagem: escolha a conversa.", f"whatsapp://send?text={q}"
    # ligação
    m = re.search(r"(?:liga|ligar|ligue|faz uma liga[cç][aã]o)\s+(?:pra|para|pro|com)\s+(?:a\s+|o\s+)?(?P<who>.+)$", t, re.I)
    if m:
        p = _person(m.group("who"))
        if p:
            return f"Ligando para {p[0]}.", f"tel:+{p[1]}"
        return f"Não tenho o número de {m.group('who')}. Adicione na nota Pessoas do cofre, ou peça direto à Siri.", ""
    # rota
    m = re.search(r"(?:me\s+leva|me\s+levar|leva(?:-me)?|rota|navega(?:r)?|vamos|bora)\s+(?:pra|para|at[eé]|ao|à|pro|no|na|a)\s+(?:o\s+|a\s+)?(?P<d>.+)$", t, re.I)
    # Casa, trabalho e casa de alguém: só endereços guardados por ele (lugares salvos ou nota Pessoas).
    # Nunca pesquisa pessoa na internet ("casa da Vitória" já virou uma loja chamada Vitória).
    if m:
        d = m.group("d").strip()
        who = re.match(r"^(?:minha\s+)?casa(?:\s+d[aoe]s?\s+(?P<who>.+))?$|^(?:meu\s+)?trabalho$", d, re.I)
        if who:
            from . import web
            addr = web._place(d)
            if addr == d and who.group("who"):
                addr = _person_address(who.group("who")) or d
            if addr == d:
                return f"Não tenho o endereço {('de ' + who.group('who')) if who.group('who') else 'salvo'}. Coloque na nota Pessoas como Endereço.", ""
            return f"Rota para {d} no Waze.", "https://waze.com/ul?" + urllib.parse.urlencode({"q": addr, "navigate": "yes"})
    # Só endereço vai direto; lugar pelo nome ("restaurante tal em Pinheiros") segue para o Claude achar o endereço exato.
    if m and re.search(r"\d|\b(rua|r\.|avenida|av\.?|alameda|al\.|estrada|rodovia|pra[cç]a|travessa|largo)\b", m.group("d"), re.I):
        d = m.group("d")
        return f"Rota para {d} no Waze.", "https://waze.com/ul?" + urllib.parse.urlencode({"q": with_city(d), "navigate": "yes"})
    # música ("... no PC" toca no computador; o resto, no celular)
    where = "celular"
    pc = re.search(r"\s+(?:no|pelo)\s+(?:pc|computador)$", t, re.I)
    if pc:
        where, t = "pc", t[:pc.start()]
        low = t.casefold()
    try:
        m = re.search(r"(?:adiciona|adicione|coloca|coloque|p[oõ]e|bota)\s+(?P<q>.+?)\s+na\s+fila", t, re.I)
        if m:
            return spotify.add_to_queue(m.group("q")), ""
        if (re.search(r"(minhas?\s+m[uú]sicas?(\s+(padr[aã]o|de sempre|curtidas))?|playlist\s+padr[aã]o|m[uú]sicas?\s+(padr[aã]o|de sempre|curtidas))\b", low)
                and re.search(r"\b(toca|tocar|coloca|bota|p[oõ]e|abre)\b", low)):
            msg, uri = spotify.play("", where, "default")
            return msg, (uri if uri and msg.startswith("Abrindo") else "")
        m = re.search(r"(?:toca|tocar|toque|coloca|coloque|bota|p[oõ]e)\s+(?:a\s+)?(?:minha\s+)?playlist\s+(?:de\s+|do\s+|da\s+)?(?P<q>.+)$", t, re.I)
        if m:
            msg, uri = spotify.play(m.group("q"), where, "playlist")
            return msg, (uri if uri and msg.startswith("Abrindo") else "")
        m = re.search(r"^(?:abre\s+o\s+spotify\s+e\s+)?(?:toca|tocar|toque|bota\s+pra\s+tocar|coloca\s+pra\s+tocar)\s+(?P<q>.+)$", t, re.I)
        if m:
            msg, uri = spotify.play(m.group("q"), where)
            return msg, (uri if uri and msg.startswith("Abrindo") else "")
    except RuntimeError as e:  # Spotify não conectado
        return str(e), "spotify://"
    except Exception as e:
        # Só fala em Premium quando o Spotify diz isso; qualquer outra recusa vai para o log com o motivo.
        try:
            body = e.read().decode(errors="ignore") if hasattr(e, "read") else str(e)
        except Exception:
            body = str(e)
        log.warning("Atalho da Siri: Spotify recusou (%s): %s", getattr(e, "code", "?"), body[:200])
        if "premium" in body.lower():
            return "O Spotify disse que precisa de conta Premium para tocar por comando.", "spotify://"
        return "O Spotify recusou o comando agora. Abri o app para você.", "spotify://"
    # abrir app
    m = re.match(r"^(?:abre|abrir|abra|abri)\s+(?:o\s+|a\s+)?(?P<app>[\wÀ-ÿ ]+?)$", t, re.I)
    if m:
        name = m.group("app").strip()
        key = name.casefold()
        url = PHONE_APPS.get(key) or next((v for k, v in PHONE_APPS.items() if k == key.split()[0]), None)
        if url:
            return f"Abrindo {name}.", url
    return None


def siri_token(new: bool = False) -> str:
    """Senha do Atalho da Siri (fica só neste PC e no Atalho)."""
    s = _load()
    if new or not s.get("siri_token"):
        s["siri_token"] = secrets.token_urlsafe(24)
        _save(s)
    return s["siri_token"]


def phone_pair() -> str:
    """Ferramenta: código para parear o app do celular."""
    return (f"Código para parear o Orbit no celular: {new_code()} (vale 15 minutos). Abra o app instalado na tela "
            "inicial e digite o código.")


TOOLS = {"phone_pair": phone_pair, "open_waze": open_waze, "open_phone_app": open_phone_app}
SCHEMAS = [fn("phone_pair", "Gera o código para parear (conectar) o app Orbit do celular com a assistente.", {}, []),
           fn("open_waze", "Abre o Waze no CELULAR com a rota para um endereço ou lugar ('me leva pra casa da minha mãe', "
              "'abre o Waze na Av. Paulista 1000'). Use quando ele está fora do PC ou dirigindo.",
              {"destino": {"type": "string", "description": "endereço ou nome do lugar"}}, ["destino"]),
           fn("open_phone_app", "Abre um app no CELULAR (Spotify, WhatsApp, YouTube, Instagram, Maps, Uber, iFood...). "
              "Quando o pedido vem pelo atalho da Siri, 'abre X' é sempre no celular, nunca no PC.",
              {"app": {"type": "string", "description": "nome do app"}}, ["app"])]


# ---------- Cores da assistente (as mesmas do orbe da ilha, escolhidas nas Configurações do Orbit) ----------

def colors() -> dict:
    """Lê a configuração do Orbit no PC (a mais recente entre a versão de desenvolvimento e a instalada)."""
    found = []
    for name in ("orbit", "Orbit Beta"):
        p = Path(os.getenv("APPDATA", "")) / name / "config.json"
        try:
            found.append((p.stat().st_mtime, json.loads(p.read_text(encoding="utf-8")).get("island", {})))
        except Exception:
            continue
    c = max(found, key=lambda x: x[0])[1] if found else {}
    return {"mode": c.get("orbMode", "grad"), "c1": c.get("orbC1", "#2f7bff"), "c2": c.get("orbC2", "#9b5cff"),
            "c3": c.get("orbC3", "#ff6fb5")}


# Ícone do app com as cores dela: o iPhone guarda o ícone ao adicionar à Tela de Início, então ele nasce
# com as cores do momento (trocou a cor? remove e adiciona de novo). Mesmo desenho do ícone do Orbit.
_icons: dict = {}


def icon_png(size: int) -> bytes:
    import io
    import numpy as np
    from PIL import Image, ImageFilter
    c = colors()
    key = (size, c["mode"], c["c1"], c["c2"], c["c3"])
    if key in _icons:
        return _icons[key]
    hexrgb = lambda h: np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], float)
    stops = [hexrgb(c["c1"])] * 4 if c["mode"] == "solid" else [hexrgb(c["c1"]), hexrgb(c["c2"]), hexrgb(c["c3"]), hexrgb(c["c1"])]
    u = (np.arange(size) + 0.5) * 64 / size
    x, y = np.meshgrid(u - 32, u - 32)
    d, k = np.hypot(x, y), ((np.arctan2(y, x) + 0.6) % (2 * np.pi)) / (2 * np.pi)
    seg = np.minimum((k * 3).astype(int), 2)
    t = (k * 3 - seg)[..., None]
    col = np.choose(seg[..., None], stops[:3]) * (1 - t) + np.choose(seg[..., None], stops[1:]) * t
    ring = lambda w: np.clip(w / 2 - np.abs(d - 21) + 0.5 * 64 / size, 0, 1)
    glow = Image.fromarray((ring(9) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(size * 0.045))
    a_glow = np.asarray(glow, float)[..., None] / 255 * 0.55
    core = ring(4.2)[..., None]
    rgb = np.full((size, size, 3), 13.0)
    rgb = rgb + col * a_glow                                  # brilho em volta, como o "lighter" do canvas
    rgb = rgb * (1 - core) + (col * 0.65 + 255 * 0.35) * core  # o anel em si, puxado para o claro
    buf = io.BytesIO()
    Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).save(buf, "PNG")
    _icons[key] = buf.getvalue()
    return _icons[key]


HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


async def colors_post(request: web.Request) -> web.Response:
    """{"mode": "grad"|"solid", "c1", "c2", "c3"}: cores da assistente. O Orbit do PC recebe pelo canal de eventos
    e salva na configuração dele; aqui também gravamos no arquivo, para valer mesmo com a ilha fechada."""
    b = await request.json()
    cur = colors()
    new = {"orbMode": "solid" if b.get("mode") == "solid" else "grad"}
    for k in ("c1", "c2", "c3"):
        new["orbC" + k[1]] = b[k] if HEX.match(str(b.get(k, ""))) else cur[k]
    orbit.publish("orbit_config", config={"island": new})
    for name in ("orbit", "Orbit Beta"):
        p = Path(os.getenv("APPDATA", "")) / name / "config.json"
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
            cfg.setdefault("island", {}).update(new)
            p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except Exception:
            continue
    _icons.clear()
    return web.json_response({"ok": True, "cores": colors()})


# ---------- Presença no PC (para decidir se o aviso vai pro celular) ----------

class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_seconds() -> float:
    try:
        li = _LastInput(ctypes.sizeof(_LastInput), 0)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
        return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000
    except Exception:
        return 0.0


# ---------- Avisos: histórico e push ----------

def _feed() -> list:
    try:
        return json.loads(FEED.read_text(encoding="utf-8"))
    except Exception:
        return []


def _vapid():
    from py_vapid import Vapid
    if not VAPID.exists():
        v = Vapid()
        v.generate_keys()
        v.save_key(str(VAPID))
    return Vapid.from_file(str(VAPID))


def public_key() -> str:
    from cryptography.hazmat.primitives import serialization
    raw = _vapid().public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def push(title: str, body: str, tag: str = "") -> int:
    """Manda para todos os celulares pareados. Devolve quantos receberam."""
    from pywebpush import WebPushException, webpush
    s = _load()
    ok, keep = 0, []
    for sub in s["subs"]:
        try:
            webpush(sub, json.dumps({"title": title, "body": body, "tag": tag}, ensure_ascii=False),
                    vapid_private_key=str(VAPID), vapid_claims={"sub": PUSH_SUB}, ttl=3600, timeout=10)
            ok += 1
            keep.append(sub)
        except WebPushException as e:
            code = getattr(e.response, "status_code", 0)
            if code in (404, 410):
                log.info("Celular: assinatura de push expirada, removida")
                continue
            log.warning("Celular: push falhou (%s)", code or e)
            keep.append(sub)
        except Exception:
            log.exception("Celular: push falhou")
            keep.append(sub)
    if len(keep) != len(s["subs"]):
        s["subs"] = keep
        _save(s)
    return ok


def _on_event(ev: dict) -> None:
    """Ouvinte do orbit.publish: guarda o aviso e, se você não está no PC, manda para o celular."""
    if ev.get("type") != "notify" or ev.get("kind") in SILENT_KINDS:
        return
    text = str(ev.get("text") or "").strip()
    if not text:
        return
    item = {"id": secrets.token_hex(6), "text": text, "kind": ev.get("kind", ""), "t": ev.get("t", time.time())}
    feed = [item, *_feed()][:100]
    FEED.write_text(json.dumps(feed, ensure_ascii=False), encoding="utf-8")
    s = _load()
    if not s["subs"] or not (s.get("always_push") or idle_seconds() >= PUSH_IDLE):
        return
    if _loop:
        _loop.call_soon_threadsafe(lambda: _loop.run_in_executor(None, push, assistente.NOME, text, item["kind"]))


# ---------- Rotas ----------

@web.middleware
async def _guard(request: web.Request, handler):
    if not request.path.startswith("/api/") or request.path == "/api/pair":
        return await handler(request)
    if (request.path == "/api/siri" and request.method == "GET") or request.path.startswith("/api/siri-audio/"):
        return await handler(request)  # o áudio tem nome aleatório de uso único (vale 10 min): basta como senha
    if request.path == "/api/siri":  # Atalho da Siri: senha própria no cabeçalho, sem cookie
        if secrets.compare_digest(request.headers.get("X-Orbit-Token", ""), _load().get("siri_token") or "-"):
            return await handler(request)
        return web.json_response({"fala": "O atalho está com a senha errada. Pegue a senha nova nos Ajustes do Orbit."}, status=401)
    token = request.cookies.get(COOKIE, "")
    if not token or _hash(token) not in _load()["devices"]:
        return web.json_response({"ok": False, "erro": "não pareado",
                                  "fala": "Endereço errado no atalho. Ele precisa terminar em barra api barra siri."}, status=401)
    if request.method != "GET":
        origin = request.headers.get("Origin", "")
        if origin and origin.split("://", 1)[-1] != request.headers.get("X-Forwarded-Host", request.host):
            return web.Response(status=403)
    return await handler(request)


async def pair(request: web.Request) -> web.Response:
    b = await request.json()
    s = _load()
    code = str(b.get("code", "")).strip().upper()
    if not s.get("code") or time.time() > s.get("code_until", 0) or not secrets.compare_digest(code, s["code"]):
        await asyncio.sleep(1)  # freia tentativa às cegas
        return web.json_response({"ok": False, "erro": "Código inválido ou vencido."}, status=403)
    token = secrets.token_urlsafe(32)
    s["devices"][_hash(token)] = {"name": str(b.get("name", "Celular"))[:40], "at": time.time()}
    s["code"] = None
    _save(s)
    log.info("Celular: aparelho pareado")
    resp = web.json_response({"ok": True})
    resp.set_cookie(COOKIE, token, max_age=400 * 86400, secure=True, httponly=True, samesite="Strict")
    return resp


async def unpair(request: web.Request) -> web.Response:
    """Tira este aparelho da lista de pareados (e as assinaturas de push dele)."""
    s = _load()
    s["devices"].pop(_hash(request.cookies.get(COOKIE, "")), None)
    _save(s)
    resp = web.json_response({"ok": True})
    resp.del_cookie(COOKIE)
    return resp


async def me(request: web.Request) -> web.Response:
    from . import google_auth
    return web.json_response({"ok": True, "assistente": assistente.publico(), "cores": colors(), "push": bool(_load()["subs"]),
                              "google": google_auth.connected(),
                              "always_push": _load().get("always_push", False), "state": orbit._state})


async def ask(request: web.Request) -> web.Response:
    """Pergunta pelo celular: responde aqui mesmo (texto e, se pedido, voz em MP3). Nada toca no PC."""
    from . import brain, config, voice
    b = await request.json()
    text = str(b.get("text") or "").strip()[:2000]
    if not text:
        return web.json_response({"ok": False}, status=400)
    return web.json_response(await _answer(text, bool(b.get("voice")), brain, config, voice))


async def _answer(text: str, want_voice: bool, brain, config, voice) -> dict:
    reply, pending = await brain.ask(config.OWNER_ID, text, spoken=want_voice, channel="telegram")
    from . import tools
    out = {"ok": True, "heard": text, "reply": reply,
           "pending": [{"id": k, "summary": tools.pending[k]["summary"]} for k in pending if k in tools.pending]}
    if want_voice and reply:
        try:
            out["audio"] = base64.b64encode(await voice.speak_mp3(reply)).decode()
        except Exception:
            log.exception("Celular: resposta sem voz")
    return out


_later = {"text": "", "url": "", "t": 0.0}  # resposta que ficou pronta depois que a Siri desistiu de esperar
_last_reply = {"text": ""}                    # para o "repete"
SPOKEN_WORDS = 40                             # acima disso, fala o começo e manda o resto por notificação


def _spoken(reply: str) -> str:
    """Resposta longa: fala as primeiras frases (até ~40 palavras) e manda o texto inteiro por notificação."""
    if len(reply.split()) <= SPOKEN_WORDS:
        return reply
    sentences, out = re.split(r"(?<=[.!?])\s+", reply), []
    for s in sentences:
        if out and len(" ".join(out + [s]).split()) > SPOKEN_WORDS:
            break
        out.append(s)
    if _loop:
        _loop.run_in_executor(None, push, assistente.NOME, reply[:1500], "siri")
    return " ".join(out) + " Mandei os detalhes no celular."


def _asks(reply: str) -> dict:
    """Terminou em pergunta ("O que eu digo para a Vitória?"): o Atalho se chama de novo para ele responder."""
    return {"continuar": "sim"} if (reply or "").rstrip().endswith("?") else {}


def _clean_reply(reply: str) -> str:
    """Sem rodapé de fontes nem links da pesquisa na fala ("Sources: [BaresSP](...)")."""
    reply = re.split(r"\n?\s*(?:Sources|Fontes)\s*:", reply or "", maxsplit=1, flags=re.I)[0]
    return re.sub(r"\[([^\]]+)\]\([^)]*\)?", r"\1", reply).strip()


def _deliver_later(task: asyncio.Future) -> None:
    """Pesquisa que passou do tempo da Siri: guarda a resposta e manda por notificação no iPhone."""
    try:
        reply, _ = task.result()
    except Exception:
        log.exception("Atalho da Siri: pesquisa em segundo plano falhou")
        reply = "Não consegui terminar aquela pesquisa. Pode pedir de novo?"
    reply = _clean_reply(reply)
    _later.update(text=reply, url=_action["url"], t=time.time())
    _last_reply["text"] = reply
    _action["url"] = ""
    if _loop:
        _loop.run_in_executor(None, push, assistente.NOME, reply[:300], "siri")


async def siri(request: web.Request) -> web.Response:
    """Atalho "Chama Friday": recebe o que você ditou e devolve o que a Siri deve falar e, se houver, o link a abrir
    (Waze com a rota, Spotify). A voz sai do iPhone: o PC não fala nada."""
    from . import brain, config, speech
    try:
        b = await request.json()
    except Exception:
        b = {}
    text = str(b.get("texto") or b.get("text") or "").strip()[:1000]
    if not text:
        return web.json_response({"fala": "Não ouvi nada. Pode repetir?"})
    _action["url"] = ""
    # "E aí?" / "aí" / "qual o resultado?": entrega a resposta que ficou pronta depois (até 30 min).
    if _later["text"] and time.time() - _later["t"] < 1800 and re.fullmatch(
            r"\W*(e\s+)?(a[ií]|ent[aã]o|qual (foi )?o resultado|j[aá] (achou|terminou|tem)|terminou|a[ií],? (achou|encontrou).*|o que voc[eê] achou|resultado)\W*", text, re.I):
        out = {"fala": speech.for_speech(_later["text"])}
        if _later["url"]:
            out["abrir"] = _later["url"]
        _last_reply["text"], _later["text"] = _later["text"], ""
        return web.json_response(out)
    # "Repete" / "o que você disse?" / "sua resposta anterior": repete na hora, sem pensar de novo.
    if _last_reply["text"] and re.fullmatch(r"\W*(repete|repita|repete a[ií]|fala de novo|o que voc[eê] (disse|falou)|(sua|a) (resposta|[uú]ltima resposta)( anterior)?|n[aã]o (ouvi|entendi))\W*", text, re.I):
        return web.json_response({"fala": speech.for_speech(_last_reply["text"])})
    if _waiting_msg["who"] and time.time() - _waiting_msg["t"] < 120:
        who, _waiting_msg["who"] = _waiting_msg["who"], ""
        text = f"manda uma mensagem pra {who} {text}"  # resposta ao "O que eu digo para X?"
    hit = await asyncio.to_thread(quick, text)
    if hit:  # comando direto: responde na hora
        log.info("Atalho da Siri (rápido): %s -> %s", text[:80], hit[1][:60])
        # No histórico também, para ela saber depois o que abriu ("você me mandou pro endereço errado").
        from . import brain, config
        brain.record(config.OWNER_ID, text, hit[0] + (f" (abri no celular: {hit[1]})" if hit[1] else ""))
        out = {"fala": hit[0], **_asks(hit[0])}
        if hit[1]:
            out["abrir"] = hit[1]
        if b.get("voz"):
            audio = await _siri_voice(hit[0], request.headers.get("X-Forwarded-Host") or request.host)
            if audio:
                out["audio"] = audio
        return web.json_response(out)
    # Instruções do canal vão à parte (context), nunca no texto: senão viram "a pergunta" para o cérebro.
    context = ("Pedido por voz pelo atalho do celular: ele está longe do PC e pode estar dirigindo. "
           "'Abre X' é no celular (open_phone_app); rota é open_waze; música é spotify_play no celular. "
           "Rota para um lugar pelo nome (restaurante, loja, academia): pesquise na internet o endereço exato (o ditado "
           "pode ter escrito o nome errado, ex. 'Low Barbecue' = 'Low BBQ'), chame open_waze com rua, número, bairro e cidade, "
           "e diga o nome e a rua na resposta. Casa, trabalho e casa de alguém: só endereços salvos (ferramenta traffic "
           "ou nota Pessoas); NUNCA pesquise uma pessoa na internet: sem endereço salvo, diga que não tem e não abra nada. "
           "Não abra nada no PC. "
           "COMO RESPONDER (vai ser falado no carro): comece pela resposta, em no máximo 2 frases curtas (até 35 palavras). "
           "Sem 'pesquisei', sem repetir o nome dele, sem ressalvas ('isso não garante...'), sem fontes, sem listas. "
           "Números redondos ('uns 49 por cento'). Se houver detalhe que valha a pena, diga só o essencial: o resto vai por escrito.")
    # A Siri desiste de esperar a rede em ~10 s. Pesquisa leva 12 a 15 s: passou de 8 s, responde "tô pesquisando",
    # termina no PC e entrega por notificação no iPhone (e no próximo "e aí?" pelo atalho).
    task = asyncio.ensure_future(brain.ask(config.OWNER_ID, text, spoken=True, channel="telegram", context=context))
    try:
        # Pelo botão de Ação não há o limite de ~10 s da Siri; quem ainda usa a Siri manda "espera": 8.
        reply, _ = await asyncio.wait_for(asyncio.shield(task), float(b.get("espera") or 25))
    except asyncio.TimeoutError:
        task.add_done_callback(_deliver_later)
        return web.json_response({"fala": "Tô pesquisando. Te aviso no celular assim que tiver a resposta."})
    except Exception:
        log.exception("Atalho da Siri: erro ao responder")
        reply = "Tive um problema pra responder agora. Tenta de novo daqui a pouco."
    url, _action["url"] = _action["url"], ""
    reply = _clean_reply(reply)
    spoken = _spoken(reply or "Feito.")
    _last_reply["text"] = reply or ""
    out = {"fala": speech.for_speech(spoken), **_asks(spoken)}
    if b.get("voz"):  # só se o Atalho pedir ("voz": true): gerar o áudio leva 1 a 3 s
        audio = await _siri_voice(reply or "Feito.", request.headers.get("X-Forwarded-Host") or request.host)
        if audio:
            out["audio"] = audio
    if url:  # sem link, sem o campo: o Atalho entende "abrir" vazio como valor e tenta abrir um endereço em branco
        out["abrir"] = url
    return web.json_response(out)


# Áudio das respostas do Atalho (voz da assistente, em português): fica 10 min num endereço de nome aleatório.
_siri_audio: dict = {}  # id -> (instante, mp3)


async def _siri_voice(text: str, host: str) -> str:
    from . import voice
    try:
        mp3 = await asyncio.wait_for(voice.speak_mp3(text), 25)
    except Exception:
        log.exception("Atalho da Siri: resposta sem áudio")
        return ""
    now = time.time()
    for k in [k for k, (t, _) in _siri_audio.items() if now - t > 600]:
        _siri_audio.pop(k, None)
    aid = secrets.token_urlsafe(16)
    _siri_audio[aid] = (now, mp3)
    return f"https://{host}/api/siri-audio/{aid}.mp3"


async def siri_audio(request: web.Request) -> web.Response:
    item = _siri_audio.get(request.match_info["id"])
    if not item:
        return web.Response(status=404)
    return web.Response(body=item[1], content_type="audio/mpeg")


async def siri_get(request: web.Request) -> web.Response:
    """Atalho montado com o método errado: responde em dados (a Siri fala o problema) em vez da página do app."""
    return web.json_response({"fala": "O atalho está usando o método GET. Na ação Get Contents of URL, troque o Method para POST."})


async def siri_info(request: web.Request) -> web.Response:
    """Para os Ajustes do app: endereço e senha do Atalho (renova=1 troca a senha)."""
    host = request.headers.get("X-Forwarded-Host") or request.host
    return web.json_response({"url": f"https://{host}/api/siri", "token": siri_token(request.query.get("renova") == "1")})


async def voice_in(request: web.Request) -> web.Response:
    """Áudio gravado no celular (m4a/webm) -> texto -> resposta com voz."""
    from . import brain, config, voice
    data = await request.read()
    if not data or len(data) > 15 * 1024 * 1024:
        return web.json_response({"ok": False}, status=400)
    # O m4a do iPhone guarda o índice no fim do arquivo: o ffmpeg precisa ler de um arquivo, não de um pipe.
    src = Path(tempfile.gettempdir()) / f"orbit-voz-{secrets.token_hex(4)}"
    src.write_bytes(data)
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        wav, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(err.decode(errors="ignore"))
        text = (await voice.transcribe(wav, "voz.wav")).strip()
    except Exception:
        log.exception("Celular: não entendi o áudio")
        return web.json_response({"ok": False, "erro": "Não consegui entender o áudio."})
    finally:
        src.unlink(missing_ok=True)
    if not text:
        return web.json_response({"ok": False, "erro": "Não ouvi nada."})
    return web.json_response(await _answer(text, True, brain, config, voice))


# ---------- Música: o vídeo do YouTube por trás do que toca no PC ----------
# O Windows só conta título, canal e uma capa pequena. Achando o vídeo (busca pelo título, conferida pela duração),
# o celular ganha a capa em alta e o "Abrir no celular" no ponto em que estava.
_yt: dict = {}           # (título, canal) -> {"id", ...} ou None (não achou)
_yt_busy: dict = {}      # (título, canal) -> Future da busca em andamento
YT_CACHE = MEMORIA / ".youtube.json"  # o que já foi achado sobrevive aos reinícios


def _yt_load() -> None:
    try:
        for row in json.loads(YT_CACHE.read_text(encoding="utf-8")):
            _yt[(row["title"], row["artist"])] = row["video"]
    except Exception:
        pass


def _yt_save() -> None:
    rows = [{"title": k[0], "artist": k[1], "video": v} for k, v in _yt.items() if v][-300:]
    try:
        YT_CACHE.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    except Exception:
        log.debug("Celular: não salvei a lista do YouTube", exc_info=True)


def _yt_find(title: str, artist: str, duration: float) -> None:
    import sys
    key = (title, artist)
    try:
        out = subprocess.run([sys.executable, "-m", "yt_dlp", "--flat-playlist", "-j", f"ytsearch3:{title} {artist}"],
                             capture_output=True, text=True, encoding="utf-8", timeout=25,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout
        found = None
        for line in out.splitlines():
            v = json.loads(line)
            same = (v.get("title") or "").casefold() == title.casefold()
            if v.get("id") and (same or (duration and v.get("duration") and abs(v["duration"] - duration) <= 5)):
                found = {"id": v["id"], "title": v.get("title"), "channel": v.get("channel")}
                break
        _yt[key] = found
        if found:
            _yt_save()
    except Exception:
        log.debug("Celular: busca no YouTube falhou", exc_info=True)
        _yt[key] = None


async def media_get(request: web.Request) -> web.Response:
    from . import nowplaying
    try:
        m = await asyncio.wait_for(asyncio.to_thread(nowplaying.now_playing), 6)
    except asyncio.TimeoutError:
        return web.json_response({"title": None, "playing": False})
    m.pop("sessions", None)
    title, artist = m.get("title") or "", m.get("artist") or ""
    if title and "spotify" not in str(m.get("app", "")).lower():
        key = (title, artist)
        if not _yt:
            _yt_load()
        if key not in _yt:
            # Primeira vez com este vídeo: espera a busca (uns 2 s) para a tela já abrir com a capa em alta e o
            # "Abrir no celular", em vez de trocar depois. Pedidos que chegam juntos esperam a mesma busca.
            fut = _yt_busy.get(key)
            if fut is None:
                fut = _yt_busy[key] = asyncio.get_running_loop().run_in_executor(None, _yt_find, title, artist, float(m.get("duration") or 0))
                fut.add_done_callback(lambda _f, k=key: _yt_busy.pop(k, None))
            try:
                await asyncio.wait_for(asyncio.shield(fut), 4)
            except asyncio.TimeoutError:
                pass
        if _yt.get(key):
            vid = _yt[key]["id"]
            m["yt"] = {"id": vid, "thumb": f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg",
                       "thumb_hq": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"}
            m.pop("art", None)  # a capa pequena do Windows não precisa ir junto
    return web.json_response(m)


# ---------- Uso de IA: o mesmo cálculo da aba da ilha (main.js scanTokens), para o celular ----------
# Lê os registros do Claude Code (só o que foi acrescentado desde a última vez) e soma por dia: tokens, valor
# estimado em API, modelos e projetos dos últimos 31 dias.
CLAUDE_LOGS = Path.home() / ".claude" / "projects"
_PRICES = [("haiku", 1, 5), ("sonnet", 3, 15), ("opus", 5, 25), ("fable", 5, 25)]
_token_files: dict = {}  # arquivo -> {"offset", "rest", "entries": {id: registro}}


def _cost(model: str, u: dict) -> float:
    p = next((x for x in _PRICES if x[0] in model), _PRICES[1])
    return ((u.get("input_tokens") or 0) * p[1] + (u.get("cache_creation_input_tokens") or 0) * p[1] * 1.25
            + (u.get("cache_read_input_tokens") or 0) * p[1] * 0.1 + (u.get("output_tokens") or 0) * p[2]) / 1e6


def _read_appended(path: Path, size: int, mtime: float) -> None:
    known = _token_files.get(path)
    if not known or size < known["offset"]:
        known = _token_files[path] = {"offset": 0, "rest": "", "entries": {}}
    if size == known["offset"]:
        return
    with path.open("rb") as f:
        f.seek(known["offset"])
        chunk = f.read(size - known["offset"])
    known["offset"] = size
    lines = (known["rest"] + chunk.decode("utf-8", "ignore")).split("\n")
    known["rest"] = lines.pop()
    for line in lines:
        if '"usage"' not in line:
            continue
        try:
            j = json.loads(line)
            m = j.get("message") or {}
            u = m.get("usage")
            if not u or not m.get("id"):
                continue
            ts = j.get("timestamp")
            day = (datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone() if ts else datetime.fromtimestamp(mtime)).strftime("%Y-%m-%d")
            model = m.get("model") or "?"
            known["entries"][m["id"]] = {
                "day": day, "model": model, "cost": _cost(model, u), "project": Path(j["cwd"]).name if j.get("cwd") else "?",
                "input": (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0),
                "cached": u.get("cache_read_input_tokens") or 0, "output": u.get("output_tokens") or 0}
        except Exception:
            continue


def ai_usage() -> dict:
    since = time.time() - 31 * 86400
    try:
        for f in CLAUDE_LOGS.glob("*/*.jsonl"):
            st = f.stat()
            if st.st_mtime >= since:
                _read_appended(f, st.st_size, st.st_mtime)
    except OSError:
        pass
    days: dict = {}
    for known in _token_files.values():
        for e in known["entries"].values():
            d = days.setdefault(e["day"], {"input": 0, "cached": 0, "output": 0, "cost": 0.0, "messages": 0, "models": {}, "projects": {}})
            for k in ("input", "cached", "output", "cost"):
                d[k] += e[k]
            d["messages"] += 1
            t = e["input"] + e["output"] + e["cached"]
            for group, name in (("models", e["model"]), ("projects", e["project"])):
                g = d[group].setdefault(name, {"tokens": 0, "cost": 0.0})
                g["tokens"] += t
                g["cost"] += e["cost"]
    ollama = None
    try:
        import httpx
        ollama = httpx.get("http://127.0.0.1:11434/api/ps", timeout=2).json().get("models", [])
    except Exception:
        pass
    return {"claude": {"days": days}, "ollama": ollama}


async def ai_usage_get(request: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(ai_usage))


async def reminders_post(request: web.Request) -> web.Response:
    from . import proactive
    b = await request.json()
    action = request.match_info["action"]
    if action == "add":
        msg = await asyncio.to_thread(proactive.add_reminder, str(b.get("text", ""))[:300], str(b.get("when", "")),
                                      int(b.get("in_minutes") or 0), str(b.get("repeat", "")))
    elif action == "cancel":
        msg = await asyncio.to_thread(proactive.cancel_reminder, str(b.get("text", "")))
    else:
        return web.json_response({"ok": False}, status=400)
    return web.json_response({"ok": True, "msg": msg})


def _file_list() -> list:
    out = []
    for folder, where in ((UPLOADS, "celular"), (DOWNLOADS, "downloads")):
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() not in (".tmp", ".crdownload", ".part"):
                st = p.stat()
                out.append({"name": p.name, "where": where, "size": st.st_size, "t": st.st_mtime})
    out.sort(key=lambda f: -f["t"])
    return out[:40]


async def files_get(request: web.Request) -> web.Response:
    return web.json_response({"files": await asyncio.to_thread(_file_list)})


async def file_get(request: web.Request) -> web.Response:
    """Baixa um arquivo das Downloads (ou de Downloads\\Do celular) para o celular. Só o nome: nada de caminho."""
    name, where = request.query.get("name", ""), request.query.get("where", "downloads")
    folder = UPLOADS if where == "celular" else DOWNLOADS
    path = (folder / name).resolve()
    if path.parent != folder.resolve() or not path.is_file():
        return web.Response(status=404)
    return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{path.name}"'})


def save_upload(name: str, data: bytes) -> Path:
    """Guarda um arquivo vindo do celular (app ou Telegram) em Downloads\\Do celular, sem sobrescrever, e avisa na ilha."""
    UPLOADS.mkdir(parents=True, exist_ok=True)
    dest = UPLOADS / (Path(name).name.replace(":", "_") or "arquivo")
    stem, n = dest.stem, 1
    while dest.exists():
        dest, n = UPLOADS / f"{stem} ({n}){dest.suffix}", n + 1
    dest.write_bytes(data)
    orbit.publish("show", title="Do celular", text=dest.name + " em Downloads\\Do celular")
    return dest


async def upload(request: web.Request) -> web.Response:
    """Arquivos do app Arquivos do iPhone -> Downloads\\Do celular, e um aviso na ilha do PC."""
    UPLOADS.mkdir(parents=True, exist_ok=True)
    reader, saved = await request.multipart(), []
    while (part := await reader.next()) is not None:
        if not part.filename:
            continue
        name = Path(part.filename).name.replace(":", "_") or "arquivo"
        dest = UPLOADS / name
        stem, n = dest.stem, 1
        while dest.exists():
            dest, n = UPLOADS / f"{stem} ({n}){dest.suffix}", n + 1
        size = 0
        with dest.open("wb") as f:
            while chunk := await part.read_chunk(1 << 16):
                size += len(chunk)
                if size > 500 * 1024 * 1024:
                    break
                f.write(chunk)
        saved.append(dest.name)
    if saved:
        orbit.publish("show", title="Do celular", text=", ".join(saved) + " em Downloads\\Do celular")
    return web.json_response({"ok": True, "saved": saved})


async def push_key(request: web.Request) -> web.Response:
    return web.json_response({"key": await asyncio.to_thread(public_key)})


async def push_subscribe(request: web.Request) -> web.Response:
    sub = await request.json()
    if not isinstance(sub, dict) or not str(sub.get("endpoint", "")).startswith("https://"):
        return web.json_response({"ok": False}, status=400)
    s = _load()
    s["subs"] = [x for x in s["subs"] if x.get("endpoint") != sub["endpoint"]] + [sub]
    _save(s)
    return web.json_response({"ok": True})


async def push_test(request: web.Request) -> web.Response:
    n = await asyncio.to_thread(push, assistente.NOME, "Notificações ligadas. É assim que eu te chamo quando você não está no PC.", "test")
    return web.json_response({"ok": n > 0, "sent": n})


async def prefs_post(request: web.Request) -> web.Response:
    b = await request.json()
    s = _load()
    if "always_push" in b:
        s["always_push"] = bool(b["always_push"])
    _save(s)
    return web.json_response({"ok": True})


async def feed_get(request: web.Request) -> web.Response:
    return web.json_response({"feed": _feed()})


async def static(request: web.Request) -> web.StreamResponse:
    rel = request.match_info.get("path") or "index.html"
    if rel.startswith("api/"):  # rota da API que não existe: dados, não a página do app (o Atalho não lê página)
        return web.json_response({"fala": "Esse endereço não existe na Friday. Confira se o endereço do atalho termina em barra api barra siri."}, status=404)
    if rel in ("icon-180.png", "icon-192.png", "icon-512.png"):
        png = await asyncio.to_thread(icon_png, int(rel[5:8]))
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "no-cache"})
    base = SHARED if rel.startswith("shared/") else WEB
    path = (base / (rel[7:] if rel.startswith("shared/") else rel)).resolve()
    if not str(path).startswith(str(base.resolve())) or not path.is_file():
        path = WEB / "index.html"  # app de página única
    headers = {"Cache-Control": "no-cache"}
    if path.name == "sw.js":
        headers["Service-Worker-Allowed"] = "/"
    return web.FileResponse(path, headers=headers)


async def start() -> None:
    global _loop
    if not WEB.is_dir():
        log.info("Celular: sem orbit/mobile, app do celular desligado")
        return
    try:
        import pywebpush  # noqa: F401
    except ImportError:
        log.warning("Celular: falta o pacote pywebpush (pip install pywebpush); app sem push")
    _loop = asyncio.get_running_loop()
    orbit.listeners.append(_on_event)
    app = web.Application(middlewares=[_guard], client_max_size=600 * 1024 * 1024)
    r = app.router
    r.add_post("/api/pair", pair)
    r.add_get("/api/me", me)
    r.add_get("/api/events", orbit.events)
    r.add_post("/api/ask", ask)
    r.add_post("/api/siri", siri)
    r.add_get("/api/siri", siri_get)
    r.add_get("/api/siri-audio/{id}.mp3", siri_audio)
    r.add_get("/api/siri-info", siri_info)
    r.add_post("/api/voice", voice_in)
    r.add_get("/api/feed", feed_get)
    r.add_post("/api/prefs", prefs_post)
    r.add_post("/api/colors", colors_post)
    r.add_post("/api/unpair", unpair)
    r.add_get("/api/push/key", push_key)
    r.add_post("/api/push/subscribe", push_subscribe)
    r.add_post("/api/push/test", push_test)
    r.add_get("/api/media", media_get)
    r.add_post("/api/media/{action}", orbit.media_post)
    r.add_get("/api/agenda", orbit.agenda)
    r.add_post("/api/agenda/done", orbit.agenda_done)
    r.add_get("/api/reminders", orbit.reminders)
    r.add_post("/api/reminders/{action}", reminders_post)
    r.add_get("/api/timers", orbit.timers_get)
    r.add_post("/api/timers/{action}", orbit.timers_post)
    r.add_get("/api/notes", orbit.notes_get)
    r.add_post("/api/notes", orbit.notes_post)
    r.add_post("/api/notes/delete", orbit.notes_delete)
    r.add_post("/api/notes/archive", orbit.notes_archive)
    r.add_get("/api/claude", orbit.claude_get)
    r.add_get("/api/ai-usage", ai_usage_get)
    r.add_get("/api/pending", orbit.pending_get)
    r.add_post("/api/confirm", orbit.confirm_post)
    r.add_get("/api/files", files_get)
    r.add_get("/api/file", file_get)
    r.add_post("/api/upload", upload)
    r.add_get("/", static)
    r.add_get("/{path:.*}", static)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await orbit.keep_serving(runner, "127.0.0.1", PORT, "Celular")
    if not _load()["devices"]:
        log.info("Celular: nenhum aparelho pareado ainda. Código: %s (vale 15 min)", new_code())
    log.info("Celular: app em http://127.0.0.1:%s (publique com: tailscale serve --bg --https=8443 http://127.0.0.1:%s)", PORT, PORT)
