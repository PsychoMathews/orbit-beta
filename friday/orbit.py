"""Ponte local entre a assistente e o Orbit (a "ilha" no topo da tela).

Servidor separado em 127.0.0.1:ORBIT_PORT (não passa pelo Tailscale Funnel da Alexa).
Todas as rotas exigem o cabeçalho X-Orbit: 1 e nenhum Origin, o que impede sites abertos no navegador de usá-las.
- GET  /orbit/events          SSE: estados (idle, listening, thinking, speaking), níveis de áudio, avisos, comandos da IA.
- POST /orbit/trigger         mesmo fluxo do Ctrl+Alt+F.
- POST /orbit/mute            liga/desliga o mudo (atalho e voz no PC).
- POST /orbit/ask             {"text", "speak"}: pergunta digitada na ilha.
- GET  /orbit/media           música tocando (qualquer player do Windows).
- POST /orbit/media/{action}  play_pause, next, previous, seek_forward, seek_back, seek_to ({"id", "position"}), volume_up, volume_down.
- GET  /orbit/agenda          próximos eventos da agenda Google.
- GET  /orbit/reminders       lembretes pendentes.
- GET  /orbit/resolve         projeto aberto e fila de render do DaVinci.
- GET/POST /orbit/windows, GET /orbit/cleanup: energia, limpeza e alertas (winsys.py).
- GET/POST /orbit/audio (volume por programa), /orbit/gamemode (modo jogo), /orbit/theme (claro/escuro).
- GET/POST /orbit/timers, /orbit/lists, /orbit/notes, GET /orbit/claude: dados do hub.py (a assistente é a dona deles).
A IA também fala com a ilha pela ferramenta island_show; timers, listas e notas ficam no hub.py.
publish() pode ser chamado de qualquer thread.
"""
import asyncio
from pathlib import Path
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta

from aiohttp import web

from .tools_common import TZ, fn
from .paths import MEMORIA
from . import assistente

log = logging.getLogger("friday.orbit")

PORT = int(os.getenv("ORBIT_PORT", "8788"))

_loop: asyncio.AbstractEventLoop | None = None
_clients: set[asyncio.Queue] = set()
_state = {"state": "idle", "muted": False}
_trigger = None  # função sem argumentos, definida pelo desktop.py
_send_to_telegram = None
_last_level = 0.0
listeners: list = []  # funções chamadas a cada evento publicado (qualquer thread)


def muted() -> bool:
    return _state["muted"]


def publish(event_type: str, **data) -> None:
    """event_type: state | level | notify | heard | reply | mute | show | timer."""
    if event_type == "state":
        _state["state"] = data["state"]
    event = {"type": event_type, "t": time.time(), **data}
    for fn_ in listeners:  # ex.: o app do celular (mobile.py) manda push dos avisos
        try:
            fn_(event)
        except Exception:
            log.exception("Ouvinte do Orbit falhou")
    if _loop is None or not _clients:
        return
    try:
        _loop.call_soon_threadsafe(_fanout, event)
    except RuntimeError:
        pass


def state(name: str) -> None:
    publish("state", state=name)


def level(value: float) -> None:
    """Nível de áudio 0..1, limitado a ~20 eventos por segundo."""
    global _last_level
    now = time.monotonic()
    if now - _last_level >= 0.05:
        _last_level = now
        publish("level", value=round(min(1.0, value), 3))


def _fanout(event: dict) -> None:
    for q in list(_clients):
        if q.qsize() < 200:
            q.put_nowait(event)


# ---------- Ferramentas da IA para a ilha ----------

def island_show(text: str, title: str = "") -> str:
    title = title or assistente.NOME
    publish("show", text=text, title=title)
    return "Mostrado na ilha do PC."


TOOLS = {"island_show": island_show}
SCHEMAS = [
    fn("island_show", "Mostra um texto curto na ilha do topo da tela do PC (lista, número, link, lembrete visual).", {
        "text": {"type": "string"}, "title": {"type": "string"},
    }, ["text"]),
]


# ---------- Rotas ----------

@web.middleware
async def _guard(request: web.Request, handler):
    # Volta do login do Spotify: vem do navegador (sem o cabeçalho); vale só com o "state" que o próprio bot gerou.
    if request.path == "/orbit/spotify/callback" and request.method == "GET":
        return await handler(request)
    if request.headers.get("X-Orbit") != "1" or request.headers.get("Origin"):
        return web.Response(status=403)
    return await handler(request)


# Ferramentas da Friday para o Claude Code (cérebro pelo plano): o servidor MCP (friday/mcp_server.py) chama esta
# rota. Senha nova a cada início, passada só para o processo do Claude; sem ela a rota recusa.
TOOL_TOKEN = secrets.token_hex(16)
tool_calls: list[str] = []  # nomes chamados na pergunta atual (o cérebro zera antes de cada uma)


async def tool(request: web.Request) -> web.Response:
    from . import tools
    if not secrets.compare_digest(request.headers.get("X-Friday-Token", ""), TOOL_TOKEN):
        return web.Response(status=403)
    body = await request.json()
    name, args = body.get("name", ""), body.get("args") or {}
    tool_calls.append(name)
    log.info("Ferramenta (plano): %s %s", name, json.dumps(args, ensure_ascii=False)[:300])
    try:
        result = await asyncio.to_thread(tools.run, name, dict(args))
    except Exception as e:
        log.exception("Erro na ferramenta %s", name)
        result = f"Erro ao usar {name}: {e}"
    return web.json_response({"result": f"<dado_externo>\n{result}\n</dado_externo>"})


async def events(request: web.Request) -> web.StreamResponse:
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
    await resp.prepare(request)
    q: asyncio.Queue = asyncio.Queue()
    _clients.add(q)
    try:
        hello = {"type": "hello", **_state, "assistente": assistente.publico()}
        await resp.write(f"data: {json.dumps(hello, ensure_ascii=False)}\n\n".encode())
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), 15)
                await resp.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode())
            except asyncio.TimeoutError:
                await resp.write(b": ping\n\n")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        _clients.discard(q)
    return resp


def _game_blocked() -> web.Response | None:
    from . import gamemode
    if gamemode.is_on():
        publish("notify", text=f"Modo jogo ligado: {assistente.com_artigo()} não escuta pelo PC agora.", kind="mute")
        return web.json_response({"ok": False, "erro": "modo jogo"}, status=423)
    return None


async def trigger(request: web.Request) -> web.Response:
    if (blocked := _game_blocked()) is not None:
        return blocked
    if _trigger is None:
        return web.json_response({"ok": False, "erro": "atalho do PC inativo"}, status=503)
    _trigger()
    return web.json_response({"ok": True})


async def mute(request: web.Request) -> web.Response:
    _state["muted"] = not _state["muted"]
    log.info("Orbit: mudo %s", "ligado" if _state["muted"] else "desligado")
    publish("mute", muted=_state["muted"])
    return web.json_response({"ok": True, "muted": _state["muted"]})


async def ask(request: web.Request) -> web.Response:
    from . import brain, config, desktop, voice
    body = await request.json()
    text = (body.get("text") or "").strip()[:2000]
    if (blocked := _game_blocked()) is not None:
        return blocked
    if not text:
        return web.json_response({"ok": False}, status=400)

    async def run():
        chat_id = config.OWNER_ID
        state("thinking")
        try:
            speak = bool(body.get("speak")) and not muted()
            reply, pending = await brain.ask(chat_id, text, spoken=speak, channel="pc")
            if _send_to_telegram:
                asyncio.create_task(_send_to_telegram(f'🏝️ (pela ilha) "{text}"\n\n{reply}', pending))
            if speak:
                ogg = await voice.speak(reply)
                publish("reply", text=reply)  # texto e voz juntos
                await asyncio.get_running_loop().run_in_executor(None, desktop._play, ogg)
            else:
                publish("reply", text=reply)
        except Exception:
            log.exception("Erro na pergunta pela ilha")
            publish("notify", text="Deu erro pra responder", kind="error")
        finally:
            state("idle")

    asyncio.create_task(run())
    return web.json_response({"ok": True})


async def media_get(request: web.Request) -> web.Response:
    from . import nowplaying
    try:  # WinRT roda numa thread própria (dentro do loop do bot ele trava)
        return web.json_response(await asyncio.wait_for(asyncio.to_thread(nowplaying.now_playing), 6))
    except asyncio.TimeoutError:
        return web.json_response({"title": None, "playing": False})


async def media_post(request: web.Request) -> web.Response:
    from . import media, nowplaying
    action = request.match_info["action"]
    if action in ("volume_up", "volume_down"):
        await asyncio.to_thread(media.media_control, action, 1)
        return web.json_response({"ok": True})
    if action not in ("play_pause", "next", "previous", "seek_forward", "seek_back", "seek_to"):
        return web.json_response({"ok": False}, status=400)
    body = await request.json() if request.can_read_body else {}
    sid = body.get("id")  # qual player (YouTube, Spotify...)
    seconds = float(body.get("position", 0)) if action == "seek_to" else 10
    try:
        ok = await asyncio.wait_for(asyncio.to_thread(nowplaying.control, action, seconds, sid), 6)
    except asyncio.TimeoutError:
        ok = False
    if not ok and not sid and action in ("play_pause", "next", "previous"):
        await asyncio.to_thread(media.media_control, action, 1)  # reserva: teclas de mídia
    return web.json_response({"ok": True, **(await asyncio.to_thread(nowplaying.now_playing))})


_agenda_cache: dict[str, tuple[float, list]] = {}


DONE_FILE = MEMORIA / "agenda_feito.json"  # tarefas da agenda marcadas como feitas


def _done() -> dict:
    try:
        return json.loads(DONE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _event(e: dict) -> dict:
    return {"id": e.get("id", ""), "title": e.get("summary", "(sem título)"),
            "start": e["start"].get("dateTime") or e["start"].get("date"),
            "end": e["end"].get("dateTime") or e["end"].get("date"),
            "link": e.get("hangoutLink", ""),
            "page": e.get("htmlLink", ""), "where": e.get("location", "")}


HOLIDAYS = "pt-br.brazilian#holiday@group.v.calendar.google.com"  # calendário público de feriados do Google


def _holidays(start: datetime, end: datetime) -> list[dict]:
    from .google_auth import service
    items = service("calendar", "v3").events().list(calendarId=HOLIDAYS, timeMin=start.isoformat(), timeMax=end.isoformat(),
                                                   singleEvents=True, orderBy="startTime").execute().get("items", [])
    return [{"title": e.get("summary", ""), "start": e["start"].get("date"), "end": e["end"].get("date"),
             "holiday": "feriado" if (e.get("description") or "").lower().startswith("feriado") else "data"} for e in items]


async def agenda(request: web.Request) -> web.Response:
    """Sem parâmetro: hoje e amanhã. ?month=AAAA-MM: o mês inteiro (para o calendário da aba)."""
    from . import google_auth, tools
    if not google_auth.connected():
        return web.json_response({"connected": False, "events": []})
    month = request.query.get("month", "")
    now = datetime.now(TZ)
    if month:
        try:
            start = datetime.strptime(month, "%Y-%m").replace(tzinfo=TZ)
        except ValueError:
            return web.json_response({"connected": True, "events": []}, status=400)
        end = (start + timedelta(days=32)).replace(day=1)
        key, limit = month, 250
    else:
        start, end = now, (now + timedelta(days=2)).replace(hour=0, minute=0, second=0)
        key, limit = "", 25
    cached = _agenda_cache.get(key)
    if not cached or time.time() - cached[0] > 120:
        try:
            raw = await asyncio.to_thread(tools.list_events_raw, start, end, limit)
            events = [_event(e) for e in raw]
            if month:
                try:
                    events += await asyncio.to_thread(_holidays, start, end)
                except Exception:
                    log.debug("Feriados indisponíveis", exc_info=True)
            cached = _agenda_cache[key] = (time.time(), events)
        except Exception:
            log.exception("Agenda indisponível para o Orbit")
            cached = cached or (0.0, [])
    done = _done()
    return web.json_response({"connected": True, "events": [{**e, "done": e.get("id") in done} for e in cached[1]]})


async def agenda_done(request: web.Request) -> web.Response:
    """Marca/desmarca uma tarefa da agenda (ex.: "Pagar o DAS") como feita. Fica só no PC; o Google não muda."""
    b = await request.json()
    done = _done()
    if b.get("done"):
        done[str(b["id"])] = {"title": b.get("title", ""), "at": time.time()}
    else:
        done.pop(str(b.get("id")), None)
    DONE_FILE.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
    return web.json_response({"ok": True})


async def reminders(request: web.Request) -> web.Response:
    from . import proactive
    items = [r for r in proactive._load(proactive.REMINDERS, []) if not r["done"]]
    items.sort(key=lambda r: r["when"])
    return web.json_response({"reminders": [{"text": r["text"], "when": r["when"]} for r in items]})


_resolve_cache: tuple[float, dict] = (0.0, {})
_resolve_busy = asyncio.Lock()
_resolve_task = None


async def resolve_info(request: web.Request) -> web.Response:
    """Projeto, timeline e fila de render do DaVinci para a aba do Orbit.

    Tocando a timeline, o script do Resolve fica sem responder por vários segundos. Então:
    - a leitura roda em segundo plano (uma por vez); a rota responde na hora com o último estado;
    - "tocando" vem do som que sai do Resolve (medidor do Windows), que funciona mesmo com o script travado.
    """
    global _resolve_cache, _resolve_task
    from . import audio

    def read():
        from . import resolve
        snap = resolve.snapshot()
        snap.pop("cache", None)
        return snap

    def alive():
        import psutil
        return any((p.info["name"] or "").lower() == "resolve.exe" for p in psutil.process_iter(["name"]))

    async def refresh():
        global _resolve_cache
        prev = _resolve_cache[1]
        try:
            data = await asyncio.to_thread(read)
        except Exception:
            log.debug("DaVinci indisponível", exc_info=True)
            data = {"running": False, "jobs": []}
        if not data.get("running") and prev.get("running") and await asyncio.to_thread(alive):
            data = {**prev}  # o script falhou mas o programa está aberto: não diz que fechou
        _resolve_cache = (time.time(), data)

    ttl = 4 if _resolve_cache[1].get("running") else 20  # fechado: perguntar de novo custa ~4 s, então espera mais
    stuck = _resolve_task is not None and not _resolve_task.done()
    if not stuck and time.time() - _resolve_cache[0] > ttl:
        _resolve_task = asyncio.create_task(refresh())
        try:  # leitura rápida: espera um pouco para já responder com dado novo
            await asyncio.wait_for(asyncio.shield(_resolve_task), 3)
        except asyncio.TimeoutError:
            stuck = True
    data = dict(_resolve_cache[1] or {"running": False, "jobs": []})
    if data.get("running"):
        try:
            data["playing"] = await asyncio.wait_for(asyncio.to_thread(audio.app_peak, "resolve"), 2) > 0.002
        except Exception:
            data["playing"] = False
        data["busy"] = stuck
    return web.json_response(data)


# ---------- Dados compartilhados (hub): timers, listas, notas, cota do Claude ----------

async def timers_get(request):
    from . import hub
    return web.json_response({"timers": hub.timers()})


async def claude_get(request):
    """Cota do Claude para a aba da ilha: % da janela de 5 h e da semana, reset e início da janela (segundos Unix)."""
    from . import hub
    s = await asyncio.to_thread(hub.quota_status)
    return web.json_response({**s, "now": time.time()})


async def timers_post(request):
    from . import hub
    body = await request.json()
    action = request.match_info.get("action", "start")
    if action == "start":
        msg = hub.timer_start(float(body.get("minutes", 0)), body.get("label") or "Timer")
    elif action == "cancel":
        msg = hub.timer_cancel(body.get("id", ""))
    elif action == "pause":
        hub.timer_pause(body.get("id", ""))
        msg = "ok"
    else:
        return web.json_response({"ok": False}, status=400)
    return web.json_response({"ok": True, "msg": msg, "timers": hub.timers()})


async def lists_get(request):
    from . import hub
    return web.json_response({"lists": hub._lists()})


async def lists_post(request):
    from . import hub
    body = await request.json()
    action = request.match_info["action"]
    name, items = body.get("list", ""), body.get("items", [])
    msg = {"add": lambda: hub.list_add(name, items), "remove": lambda: hub.list_remove(name, items),
           "clear": lambda: hub.list_clear(name)}.get(action)
    if not msg:
        return web.json_response({"ok": False}, status=400)
    return web.json_response({"ok": True, "msg": msg(), "lists": hub._lists()})


async def notes_get(request):
    from . import hub
    return web.json_response({"text": hub.notes_get()})


async def notes_post(request):
    from . import hub
    body = await request.json()
    hub.notes_set(str(body.get("text", ""))[:100000])
    return web.json_response({"ok": True})


async def claude_get(request):
    from . import hub
    out = await asyncio.to_thread(hub.quota_status)
    if request.query.get("history"):
        out["history"] = await asyncio.to_thread(hub.quota_history)
    return web.json_response(out)


# ---------- Windows: energia, limpeza, alertas (winsys.py). Cliques na ilha valem como confirmação do usuário. ----------

async def windows_get(request):
    from . import winsys
    return web.json_response(await asyncio.to_thread(winsys.power_status))


def _apply_energy(winsys, b: dict) -> str:
    """Botão "Aplicar" da seção Energia: tudo que mudou, de uma vez (mexer no Windows a cada clique pesava)."""
    msgs = []
    if "awake" in b:
        a = b["awake"]
        msgs.append(winsys.keep_awake(a.get("mode", "off"), a.get("minutes", 0), a.get("screen", False)))
    if "sleep" in b or "screen" in b:
        msgs.append(winsys.power_set(b.get("sleep"), b.get("screen")))
    if b.get("plan"):
        msgs.append(winsys.power_plan(b["plan"]))
    return " ".join(msgs) or "Nada para aplicar."


async def windows_post(request):
    from . import winsys
    b = await request.json() if request.can_read_body else {}
    action = request.match_info["action"]
    calls = {
        "awake": lambda: winsys.keep_awake(b.get("mode", "forever"), b.get("minutes", 0), b.get("screen", False)),
        "power": lambda: winsys.power_set(b.get("sleep"), b.get("screen")),
        "plan": lambda: winsys.power_plan(b.get("name", "")),
        "shutdown": lambda: winsys.schedule_shutdown(b.get("action", "shutdown"), b.get("minutes", 0), b.get("after_render", False)),
        "cancel": winsys.shutdown_cancel,
        "alerts": lambda: winsys.alerts_set(**{k: b[k] for k in ("cpu", "ram", "disk", "gpu") if k in b}),
        "clean": lambda: winsys.cleanup_run(b.get("targets", []), b.get("only")),
        "recycle": winsys.empty_recycle_bin,
        "autoclean": lambda: winsys.autoclean_set(b.get("every"), b.get("targets"), b.get("downloads_days")),
        "apply": lambda: _apply_energy(winsys, b),
        "server": lambda: winsys.server_mode(bool(b.get("on"))),
    }
    if action not in calls:
        return web.json_response({"ok": False}, status=400)
    msg = await asyncio.to_thread(calls[action])
    return web.json_response({"ok": True, "msg": msg, **(await asyncio.to_thread(winsys.power_status))})


_audio_cache: dict = {}


async def audio_get(request):
    # O mixer do Windows às vezes demora (ex.: DaVinci tocando segura o dispositivo): responde em até 4 s
    # com o último estado conhecido em vez de deixar a aba "Carregando".
    global _audio_cache
    from . import audio
    try:
        _audio_cache = await asyncio.wait_for(asyncio.to_thread(audio.sessions), 4)
    except Exception:
        log.debug("Mixer lento", exc_info=True)
        if not _audio_cache:
            return web.json_response({"apps": [], "master": 0, "masterMuted": False, "device": "Mixer do Windows não respondeu", "stale": True})
        return web.json_response({**_audio_cache, "stale": True})
    return web.json_response(_audio_cache)


async def confirm_post(request):
    """Confirmar/cancelar pela ilha uma ação pendente (a mesma do botão do Telegram; quem clicar primeiro vale)."""
    from . import tools
    b = await request.json()
    aid = str(b.get("id") or "")
    if aid not in tools.pending:
        return web.json_response({"ok": False, "msg": "Essa ação expirou ou já foi tratada."})
    if not b.get("ok"):
        tools.cancel_pending(aid)
        return web.json_response({"ok": True, "msg": "Cancelado."})
    try:
        msg = await asyncio.to_thread(tools.execute_pending, aid)
    except Exception as e:
        msg = f"Falhou: {e}"
    return web.json_response({"ok": True, "msg": str(msg)})


async def pending_get(request):
    from . import tools
    return web.json_response({"pending": [{"id": k, "summary": v["summary"]} for k, v in tools.pending.items()]})


async def beat_post(request):
    from . import audio
    b = await request.json()
    audio.beat_watch(str(b.get("app") or ""), publish)
    return web.json_response({"ok": True})


async def audio_post(request):
    from . import audio
    b = await request.json()
    async with _audio_lock:  # em fila: pedidos fora de ordem deixavam o volume "preso" num valor antigo
        if b.get("app") in (None, "", "master"):
            msg = await asyncio.to_thread(audio.set_master, b.get("volume"), b.get("mute"))
        else:
            msg = await asyncio.to_thread(audio.set_app, b["app"], b.get("volume"), b.get("mute"))
        state = await asyncio.to_thread(audio.sessions)
    return web.json_response({"ok": True, "msg": msg, **state})


_audio_lock = asyncio.Lock()


async def audio_outputs_get(request):
    from . import audio_route
    try:
        info = await asyncio.wait_for(asyncio.to_thread(audio_route.outputs), 4)
        info["apps"] = await asyncio.wait_for(asyncio.to_thread(audio_route.app_outputs), 4)
    except Exception:
        log.debug("Saídas de áudio indisponíveis", exc_info=True)
        return web.json_response({"outputs": [], "apps": {}, "default": ""})
    return web.json_response(info)


async def audio_output_post(request):
    """{"device": id} troca a saída padrão; {"device": id|"", "app": id} só daquele programa; {"mic": bool|null}."""
    from . import audio_route
    b = await request.json()
    async with _audio_lock:
        try:
            if "mic" in b:
                msg = await asyncio.to_thread(audio_route.mic_mute, b["mic"])
            elif b.get("app"):
                msg = await asyncio.to_thread(audio_route.set_app_output, b["app"], b.get("device", ""))
            else:
                msg = await asyncio.to_thread(audio_route.set_default, b.get("device", ""))
        except OSError as e:
            msg = str(e)
    publish("mic", muted=(await asyncio.to_thread(audio_route.outputs)).get("micMuted"))
    return web.json_response({"ok": True, "msg": msg})


async def spotify_get(request):
    from . import spotify
    out = spotify.status()
    if out["connected"] and request.query.get("now"):
        try:
            out["now"] = await asyncio.to_thread(spotify.now)
        except Exception as e:
            out["error"] = str(e)
        return web.json_response(out)
    if out["connected"] and request.query.get("queue"):
        try:
            out.update(await asyncio.to_thread(spotify.queue))
        except Exception as e:
            out["error"] = str(e)
    return web.json_response(out)


async def spotify_post(request):
    from . import spotify
    b = await request.json() if request.can_read_body else {}
    action = request.match_info["action"]
    try:
        if action == "client":
            await asyncio.to_thread(spotify.set_client_id, str(b.get("client_id", "")))
        elif action == "connect":
            return web.json_response({"ok": True, "url": spotify.auth_url()})
        elif action == "disconnect":
            spotify.disconnect()
        elif action == "add":
            return web.json_response({"ok": True, "msg": await asyncio.to_thread(spotify.add_to_queue, str(b.get("query", "")))})
        elif action == "play":
            return web.json_response({"ok": True, "msg": await asyncio.to_thread(spotify.play_from_queue, str(b.get("uri", "")), str(b.get("context", "")))})
        else:
            return web.json_response({"ok": False}, status=400)
    except Exception as e:
        return web.json_response({"ok": False, "msg": str(e)})
    return web.json_response({"ok": True, **spotify.status()})


async def spotify_callback(request):
    from . import spotify
    q = request.query
    page = lambda title, text: web.Response(content_type="text/html", text=(
        "<!doctype html><meta charset=utf-8><title>Orbit</title><body style='font:16px system-ui;background:#0d0d0f;color:#eee;"
        f"display:grid;place-items:center;height:100vh;margin:0'><div style='text-align:center'><h2>{title}</h2><p>{text}</p></div>"))
    if q.get("error") or not q.get("code"):
        return page("Spotify não conectado", "O login foi cancelado. Pode fechar esta aba.")
    try:
        user = await asyncio.to_thread(spotify.finish, q["code"], q.get("state", ""))
    except Exception as e:
        return page("Não deu certo", str(e))
    publish("spotify", connected=True, user=user)
    return page("Spotify conectado ✓", f"{user + ', a' if user else 'A'} fila já aparece na aba Música. Pode fechar esta aba.")


async def gamemode_get(request):
    from . import gamemode
    return web.json_response(gamemode.public())


async def gamemode_post(request):
    from . import gamemode
    b = await request.json()
    msg = ""
    if "on" in b:
        msg = gamemode.game_mode(bool(b["on"]))
    if "allow" in b or "speak" in b:
        gamemode.configure(b.get("allow"), b.get("speak"))
    return web.json_response({"ok": True, "msg": msg, **gamemode.public()})


async def theme_post(request):
    from . import winsys
    b = await request.json()
    msg = await asyncio.to_thread(winsys.theme, b.get("mode", "escuro"), b.get("target", "windows"))
    return web.json_response({"ok": True, "msg": msg, "windows": await asyncio.to_thread(winsys.windows_theme)})


async def theme_get(request):
    from . import winsys
    return web.json_response({"windows": await asyncio.to_thread(winsys.windows_theme)})


async def cleanup_get(request):
    from . import winsys
    if request.query.get("files"):
        return web.json_response({"files": await asyncio.to_thread(winsys.cleanup_files, request.query["files"])})
    return web.json_response(await asyncio.to_thread(winsys.scan))


async def keep_serving(runner: web.AppRunner, host: str, port: int, name: str) -> None:
    """No Windows, quando um cliente cai no meio da conexão (WinError 64), o asyncio para de aceitar
    conexões naquela porta e não volta mais. Aqui a porta é testada a cada 20 s e reaberta se morreu."""
    site = web.TCPSite(runner, host, port)
    await site.start()

    async def guard():
        nonlocal site
        while True:
            await asyncio.sleep(20)
            try:
                _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 3)
                writer.close()
                continue
            except Exception:
                log.warning("%s: a porta %s parou de aceitar conexões; reabrindo", name, port)
            try:
                await site.stop()
            except Exception:
                pass
            try:
                site = web.TCPSite(runner, host, port)
                await site.start()
                log.info("%s: porta %s reaberta", name, port)
            except Exception:
                log.exception("%s: não consegui reabrir a porta %s", name, port)

    asyncio.create_task(guard())


async def start(send_to_telegram=None) -> None:
    global _loop, _send_to_telegram
    _loop = asyncio.get_running_loop()
    _send_to_telegram = send_to_telegram
    app = web.Application(middlewares=[_guard])
    app.router.add_get("/orbit/events", events)
    app.router.add_post("/orbit/trigger", trigger)
    app.router.add_post("/orbit/mute", mute)
    app.router.add_post("/orbit/ask", ask)
    app.router.add_post("/orbit/tool", tool)
    app.router.add_get("/orbit/media", media_get)
    app.router.add_post("/orbit/media/{action}", media_post)
    app.router.add_get("/orbit/agenda", agenda)
    app.router.add_post("/orbit/agenda/done", agenda_done)
    app.router.add_get("/orbit/reminders", reminders)
    app.router.add_get("/orbit/resolve", resolve_info)
    app.router.add_get("/orbit/timers", timers_get)
    app.router.add_get("/orbit/claude", claude_get)
    app.router.add_post("/orbit/timers/{action}", timers_post)
    app.router.add_get("/orbit/lists", lists_get)
    app.router.add_post("/orbit/lists/{action}", lists_post)
    app.router.add_get("/orbit/notes", notes_get)
    app.router.add_post("/orbit/notes", notes_post)
    app.router.add_get("/orbit/claude", claude_get)
    app.router.add_get("/orbit/windows", windows_get)
    app.router.add_post("/orbit/windows/{action}", windows_post)
    app.router.add_get("/orbit/cleanup", cleanup_get)
    app.router.add_get("/orbit/audio", audio_get)
    app.router.add_post("/orbit/audio", audio_post)
    app.router.add_get("/orbit/audio/outputs", audio_outputs_get)
    app.router.add_post("/orbit/audio/output", audio_output_post)
    app.router.add_post("/orbit/beat", beat_post)
    app.router.add_post("/orbit/confirm", confirm_post)
    app.router.add_get("/orbit/pending", pending_get)
    app.router.add_get("/orbit/spotify", spotify_get)
    app.router.add_post("/orbit/spotify/{action}", spotify_post)
    app.router.add_get("/orbit/spotify/callback", spotify_callback)
    app.router.add_get("/orbit/gamemode", gamemode_get)
    app.router.add_post("/orbit/gamemode", gamemode_post)
    app.router.add_get("/orbit/theme", theme_get)
    app.router.add_post("/orbit/theme", theme_post)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await keep_serving(runner, "127.0.0.1", PORT, "Orbit")
    log.info("Orbit: ponte em http://127.0.0.1:%s/orbit", PORT)
