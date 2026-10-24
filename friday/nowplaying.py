"""O que está tocando no Windows (Spotify, YouTube no navegador, qualquer player) e os controles dele.

Usa o controle de mídia do Windows (GlobalSystemMediaTransportControls). As chamadas WinRT travam se forem
esperadas dentro do loop do bot, então tudo roda numa thread própria com o seu próprio loop e tempo limite.
"""
import asyncio
import base64
import logging
from datetime import timedelta

log = logging.getLogger("friday.nowplaying")

_art_cache: dict[str, str | None] = {}


def _run(coro_fn, *args):
    """Roda uma corrotina WinRT num loop novo (chamado de dentro de asyncio.to_thread)."""
    return asyncio.run(coro_fn(*args))


async def _sessions() -> list:
    """Todas as sessões de mídia (YouTube, Spotify...): quem está tocando primeiro, depois a "atual" do Windows."""
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
    manager = await Manager.request_async()
    sessions = list(manager.get_sessions())
    current = manager.get_current_session()
    cur_id = current.source_app_user_model_id if current else None
    sessions.sort(key=lambda s: (int(s.get_playback_info().playback_status) != 4, s.source_app_user_model_id != cur_id))
    return sessions


async def _session(sid: str | None = None):
    sessions = await _sessions()
    if sid:
        for s in sessions:
            if s.source_app_user_model_id == sid:
                return s
    return sessions[0] if sessions else None


def _app_name(aumid: str) -> str:
    a = aumid.lower()
    for key, name in (("spotify", "Spotify"), ("opera", "Opera GX"), ("chrome", "Chrome"), ("msedge", "Edge"),
                      ("firefox", "Firefox"), ("vlc", "VLC"), ("zunemusic", "Media Player"), ("music", "Música")):
        if key in a:
            return name
    base = aumid.split("!")[0].split("\\")[-1].removesuffix(".exe")
    # Identificador em formato de domínio ("com.maestri.windows"): o nome do app é o segundo pedaço.
    parts = base.split(".")
    if len(parts) >= 3 and parts[0].lower() in ("com", "org", "net", "io", "app", "br"):
        return parts[1].capitalize()
    return base


async def _art(props, key: str) -> str | None:
    if key in _art_cache:
        return _art_cache[key]
    art = None
    if props.thumbnail:
        try:
            from winrt.windows.storage.streams import Buffer, InputStreamOptions
            stream = await props.thumbnail.open_read_async()
            buf = Buffer(stream.size)
            await stream.read_async(buf, stream.size, InputStreamOptions.READ_AHEAD)
            data = bytes(memoryview(buf)[:buf.length])
            mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
            art = f"data:{mime};base64," + base64.b64encode(data).decode()
        except Exception:
            log.debug("Sem capa", exc_info=True)
    if len(_art_cache) > 8:  # guarda só as capas recentes
        _art_cache.clear()
    _art_cache[key] = art
    return art


async def _now() -> dict:
    """A sessão principal nos campos de cima (pílula e compatibilidade) e todas em "sessions"."""
    items = [await _describe(s) for s in await _sessions()]
    if not items:
        return {"title": None, "playing": False, "sessions": []}
    return {**items[0], "sessions": items}


async def _describe(s) -> dict:
    props = await s.try_get_media_properties_async()
    info = s.get_playback_info()
    caps = info.controls
    tl = s.get_timeline_properties()
    status = int(info.playback_status)
    end = tl.end_time.total_seconds() if tl.end_time else 0
    key = f"{s.source_app_user_model_id}|{props.title}|{props.artist}"
    return {
        "id": s.source_app_user_model_id,
        "title": props.title or None, "artist": props.artist, "album": props.album_title,
        "app": _app_name(s.source_app_user_model_id), "playing": status == 4, "status": status,
        "position": tl.position.total_seconds() if tl.position else 0, "duration": end,
        "updated": tl.last_updated_time.timestamp() if tl.last_updated_time else None,
        "can": {"next": caps.is_next_enabled, "previous": caps.is_previous_enabled, "pause": caps.is_play_pause_toggle_enabled,
                "seek": bool(caps.is_playback_position_enabled and end)},
        "art": await _art(props, key),
    }


async def _control(action: str, seconds: float = 10, sid: str | None = None) -> bool:
    s = await _session(sid)
    if not s:
        return False
    if action == "play_pause":
        return await s.try_toggle_play_pause_async()
    if action == "next":
        return await s.try_skip_next_async()
    if action == "previous":
        return await s.try_skip_previous_async()
    if action in ("seek_forward", "seek_back", "seek_to"):
        tl = s.get_timeline_properties()
        if action == "seek_to":  # clique na barra: seconds é a posição exata
            pos = seconds
        else:
            pos = tl.position.total_seconds() + (seconds if action == "seek_forward" else -seconds)
        pos = max(0.0, min(pos, tl.end_time.total_seconds() if tl.end_time else pos))
        # O WinRT recebe a posição em "ticks" de 100 ns.
        return await s.try_change_playback_position_async(int(timedelta(seconds=pos).total_seconds() * 10_000_000))
    return False


def now_playing() -> dict:
    try:
        return _run(_now)
    except Exception:
        log.debug("Mídia indisponível", exc_info=True)
        return {"title": None, "playing": False}


def control(action: str, seconds: float = 10, sid: str | None = None) -> bool:
    """sid: qual sessão controlar (id do app); vazio = a principal."""
    try:
        return bool(_run(_control, action, seconds, sid))
    except Exception:
        log.debug("Controle de mídia falhou", exc_info=True)
        return False
