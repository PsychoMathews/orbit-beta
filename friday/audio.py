"""Volume por programa (mixer do Windows) e volume geral, via Core Audio (pycaw).

Cada programa pode ter várias "sessões" de áudio (o Chrome abre uma por aba); aqui elas viram uma linha só por programa.
"""
import re
import threading
import time
import unicodedata

import comtypes
from pycaw.pycaw import AudioUtilities, IAudioMeterInformation

from .tools_common import fn
from .paths import APP_DIR
from . import assistente

NAMES = {"spotify": "Spotify", "chrome": "Chrome", "msedge": "Edge", "opera": "Opera GX", "discord": "Discord",
         "resolve": "DaVinci Resolve", "obs64": "OBS", "electron": "Orbit", "pythonw": assistente.NOME, "python": assistente.NOME,
         "claude": "Claude", "steam": "Steam", "steamwebhelper": "Steam", "vlc": "VLC", "teams": "Teams", "ms-teams": "Teams",
         "whatsapp": "WhatsApp", "riotclientux": "Riot", "valorant-win64-shipping": "Valorant", "leagueclientux": "League of Legends"}


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _com(fn_):
    """Core Audio é COM: cada thread precisa inicializar."""
    def wrapper(*a, **k):
        comtypes.CoInitialize()
        try:
            return fn_(*a, **k)
        finally:
            comtypes.CoUninitialize()
    wrapper.__name__ = fn_.__name__
    return wrapper


def _groups() -> dict[str, dict]:
    groups: dict[str, dict] = {}
    for s in AudioUtilities.GetAllSessions():
        if s.Process:
            exe = s.Process.name().removesuffix(".exe").removesuffix(".EXE")
            key, name = exe.lower(), NAMES.get(exe.lower(), exe[:1].upper() + exe[1:])
        else:
            key, name = "sistema", "Sons do sistema"
        g = groups.setdefault(key, {"id": key, "name": name, "sessions": [], "active": False})
        g["sessions"].append(s)
        g["active"] = g["active"] or s.State == 1  # 1 = tocando agora
    return groups


@_com
def sessions() -> dict:
    out = []
    for g in _groups().values():
        v = g["sessions"][0].SimpleAudioVolume
        out.append({"id": g["id"], "name": g["name"], "volume": round(v.GetMasterVolume() * 100),
                    "muted": bool(v.GetMute()), "active": g["active"]})
    out.sort(key=lambda x: (not x["active"], x["id"] == "sistema", x["name"].lower()))
    speakers = AudioUtilities.GetSpeakers()
    ev = speakers.EndpointVolume
    return {"apps": out, "master": round(ev.GetMasterVolumeLevelScalar() * 100), "masterMuted": bool(ev.GetMute()),
            "device": speakers.FriendlyName}


def _match(groups: dict, app: str) -> dict | None:
    key = _norm(app).replace(" ", "")
    if key in groups:
        return groups[key]
    for g in groups.values():
        if key in _norm(g["name"]).replace(" ", "") or key in g["id"]:
            return g
    return None


@_com
def set_app(app: str, volume: float | None = None, mute: bool | None = None) -> str:
    groups = _groups()
    g = _match(groups, app)
    if not g:
        names = ", ".join(x["name"] for x in groups.values())
        return f"Não achei '{app}' tocando som agora. Programas com áudio: {names}."
    for s in g["sessions"]:
        v = s.SimpleAudioVolume
        if volume is not None:
            v.SetMasterVolume(max(0.0, min(1.0, float(volume) / 100)), None)
        if mute is not None:
            v.SetMute(1 if mute else 0, None)
    parts = []
    if volume is not None:
        parts.append(f"volume {int(max(0, min(100, volume)))}%")
    if mute is not None:
        parts.append("mudo" if mute else "som ligado")
    return f"{g['name']}: {', '.join(parts) or 'nada mudou'}."


@_com
def set_master(volume: float | None = None, mute: bool | None = None) -> str:
    ev = AudioUtilities.GetSpeakers().EndpointVolume
    if volume is not None:
        ev.SetMasterVolumeLevelScalar(max(0.0, min(1.0, float(volume) / 100)), None)
    if mute is not None:
        ev.SetMute(1 if mute else 0, None)
    return f"Volume geral: {round(ev.GetMasterVolumeLevelScalar() * 100)}%" + (" (mudo)" if ev.GetMute() else "") + "."


def app_volume(app: str = "", volume: float | None = None, mute: bool | None = None) -> str:
    """Para a IA: app vazio = volume geral; sem volume/mute = só listar."""
    if isinstance(volume, str):
        m = re.search(r"\d+", volume)
        volume = float(m.group()) if m else None
    if not app or _norm(app) in ("geral", "tudo", "pc", "computador", "master", "sistema geral"):
        if volume is None and mute is None:
            s = sessions()
            return f"Volume geral {s['master']}% ({s['device']}). " + "; ".join(
                f"{a['name']} {a['volume']}%" + (" mudo" if a["muted"] else "") for a in s["apps"])
        return set_master(volume, mute)
    if volume is None and mute is None:
        s = sessions()
        a = next((x for x in s["apps"] if _norm(app) in _norm(x["name"])), None)
        return f"{a['name']}: {a['volume']}%" + (" (mudo)" if a["muted"] else "") if a else f"'{app}' não está tocando som agora."
    return set_app(app, volume, mute)


def _audio_output(device: str = "", app: str = "") -> str:
    from . import audio_route
    return audio_route.audio_output(device, app)


def _mic_mute(mute: bool | None = None) -> str:
    from . import audio_route
    return audio_route.mic_mute(mute)


TOOLS = {"app_volume": app_volume, "audio_output": _audio_output, "mic_mute": _mic_mute}
SCHEMAS = [
    fn("app_volume", "Volume POR PROGRAMA (mixer do Windows): ex. Spotify a 30%, mutar o Discord, Chrome mais baixo. "
       "app vazio = volume geral do PC. Sem volume nem mute = só mostra os volumes.", {
           "app": {"type": "string", "description": "Nome do programa: Spotify, Chrome, Discord, DaVinci, jogo..."},
           "volume": {"type": "number", "description": "0 a 100"},
           "mute": {"type": "boolean"},
       }),
    fn("audio_output", "Saída de som: troca para fone/headset ou caixa (alto-falantes), de tudo ou SÓ de um programa "
       "(ex. música na caixa e Discord no fone). Sem device = lista as saídas. device='padrão' com app = o programa volta ao normal.", {
           "device": {"type": "string", "description": "Parte do nome: fone, headset, caixa, alto-falantes, monitor..."},
           "app": {"type": "string", "description": "Opcional: só esse programa (Spotify, Discord, Chrome...)"},
       }),
    fn("mic_mute", "Muta ou liga TODOS os microfones do PC. Sem mute = alterna.", {"mute": {"type": "boolean"}}),
]


# ---------- Batida da música e nível do DaVinci (medidor em processo à parte: friday/meter.py) ----------
# Ler o medidor do Windows dentro do bot derrubava o processo (access violation). O bot só lê o que o
# processo do medidor imprime. A ilha renova o pedido a cada ~2 s; sem renovação por 5 s o medidor é morto.
_beat = {"app": "", "until": 0.0, "proc": None}
_beat_lock = threading.Lock()


def _meter_cmd(*args):
    import subprocess
    import sys
    from pathlib import Path
    exe = sys.executable.replace("pythonw.exe", "python.exe")
    return dict(args=[exe, "-m", "friday.meter", *args], cwd=str(APP_DIR),
                creationflags=0x08000000, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)


def beat_watch(app: str, publish) -> None:
    import subprocess
    with _beat_lock:
        _beat["until"] = time.monotonic() + 5
        p = _beat["proc"]
        if p and p.poll() is None and _beat["app"] == app:
            return
        if p and p.poll() is None:
            p.kill()
        _beat["app"] = app
        p = _beat["proc"] = subprocess.Popen(**_meter_cmd("stream", app))
    threading.Thread(target=_beat_reader, args=(p, publish), daemon=True, name="orbit-beat").start()


def _beat_reader(p, publish) -> None:
    try:
        for line in p.stdout:
            if time.monotonic() > _beat["until"] or _beat["proc"] is not p:
                break
            try:
                publish("beat", value=float(line))
            except ValueError:
                pass
    finally:
        if p.poll() is None:
            p.kill()


def app_peak(app: str) -> float:
    """Maior nível de saída do programa em ~0,2 s (0 = mudo/parado). Usado para saber se o DaVinci está tocando."""
    import subprocess
    try:
        out = subprocess.run(**{**_meter_cmd("once", app), "timeout": 5})
        return float(out.stdout.strip() or 0)
    except Exception:
        return 0.0
