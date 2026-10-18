"""Saída de áudio: trocar o dispositivo padrão e escolher a saída de cada programa (música na caixa, chamada no fone).

A saída por programa usa a mesma interface interna do Windows que o EarTrumpet e o "Volume e dispositivos por
aplicativo" das Configurações (IAudioPolicyConfigFactory, Windows 10 21H2 ou mais novo). Microfone: mudo de todos.
"""
import ctypes
from ctypes import wintypes

import comtypes
from pycaw.pycaw import AudioUtilities

_combase = ctypes.windll.combase
_RENDER_IF = "{e6327cad-dcec-4949-ae8a-991e976a79d2}"  # interface de dispositivo de saída (MMDEVAPI)
_CAPTURE_IF = "{2eef81be-33fa-4800-9670-1cd474972c3f}"


class _GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]


def _guid(s: str) -> _GUID:
    g = _GUID()
    ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g))
    return g


def _hstring(s: str | None):
    h = ctypes.c_void_p()
    if s:
        _combase.WindowsCreateString(ctypes.c_wchar_p(s), len(s), ctypes.byref(h))
    return h


def _factory():
    """IAudioPolicyConfigFactory (IID muda entre versões do Windows; tenta a nova e a antiga)."""
    name = "Windows.Media.Internal.AudioPolicyConfig"
    hs = _hstring(name)
    try:
        for iid in ("{ab3d4648-e242-459f-b02f-541c70306324}", "{2a59116d-6c4f-45e0-a74f-707e3fef9258}"):
            p = ctypes.c_void_p()
            if _combase.RoGetActivationFactory(hs, ctypes.byref(_guid(iid)), ctypes.byref(p)) == 0 and p.value:
                return p
    finally:
        _combase.WindowsDeleteString(hs)
    raise OSError("Este Windows não deixa escolher a saída por programa.")


def _call(obj, index: int, *args, argtypes=()):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
    return proto(vtbl[index])(obj, *args)


_SET_APP, _GET_APP = 25, 26  # SetPersistedDefaultAudioEndpoint / GetPersistedDefaultAudioEndpoint


def _short(dev_id: str | None) -> str:
    """\\\\?\\SWD#MMDEVAPI#{0.0.0.00000000}.{guid}#{interface} -> {0.0.0.00000000}.{guid}"""
    if not dev_id:
        return ""
    if "MMDEVAPI#" in dev_id:
        return dev_id.split("MMDEVAPI#", 1)[1].split("#", 1)[0]
    return dev_id


def _com(fn_):
    def wrapper(*a, **k):
        comtypes.CoInitialize()
        try:
            return fn_(*a, **k)
        finally:
            comtypes.CoUninitialize()
    wrapper.__name__ = fn_.__name__
    return wrapper


def _devices(flow: int = 0) -> list[dict]:
    """flow 0 = saídas, 1 = entradas. Só os ativos."""
    out = []
    for d in AudioUtilities.GetAllDevices(data_flow=flow, device_state=1):
        out.append({"id": d.id, "name": d.FriendlyName or "?"})
    return out


@_com
def outputs() -> dict:
    default = AudioUtilities.GetSpeakers()
    raw = AudioUtilities.GetMicrophone()
    mic = AudioUtilities.CreateDevice(raw) if raw else None
    mic_muted = None
    try:
        mic_muted = bool(mic.EndpointVolume.GetMute()) if mic else None
    except Exception:
        pass
    return {"outputs": _devices(0), "default": default.id if default else "",
            "mic": mic.FriendlyName if mic else "", "micMuted": mic_muted}


@_com
def set_default(dev_id: str) -> str:
    devs = {d["id"]: d["name"] for d in _devices(0)}
    if dev_id not in devs:
        return "Não achei esse dispositivo de saída."
    AudioUtilities.SetDefaultDevice(dev_id)
    return f"Saída padrão: {devs[dev_id]}."


def _pids(app: str) -> list[int]:
    from . import audio
    g = audio._match(audio._groups(), app)
    return [s.ProcessId for s in g["sessions"] if s.ProcessId] if g else []


def _get_app(f, pid: int) -> str:
    h = ctypes.c_void_p()
    if _call(f, _GET_APP, pid, 0, 1, ctypes.byref(h),
             argtypes=(wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))) != 0 or not h.value:
        return ""
    try:
        _combase.WindowsGetStringRawBuffer.restype = ctypes.c_void_p
        return _short(ctypes.wstring_at(_combase.WindowsGetStringRawBuffer(h, None)))
    finally:
        _combase.WindowsDeleteString(h)


@_com
def app_outputs() -> dict[str, str]:
    """{id do programa no mixer: id do dispositivo escolhido} (só os que não seguem o padrão)."""
    from . import audio
    try:
        f = _factory()
    except OSError:
        return {}
    out = {}
    for key, g in audio._groups().items():
        pid = next((s.ProcessId for s in g["sessions"] if s.ProcessId), 0)
        dev = _get_app(f, pid) if pid else ""
        if dev:
            out[key] = dev
    return out


@_com
def set_app_output(app: str, dev_id: str = "") -> str:
    """dev_id vazio = o programa volta a seguir a saída padrão."""
    from . import audio
    g = audio._match(audio._groups(), app)
    if not g:
        return f"'{app}' não está com som aberto agora."
    pids = sorted({s.ProcessId for s in g["sessions"] if s.ProcessId})
    name = ""
    if dev_id:
        devs = {d["id"]: d["name"] for d in _devices(0)}
        if dev_id not in devs:
            return "Não achei esse dispositivo de saída."
        name = devs[dev_id]
    full = f"\\\\?\\SWD#MMDEVAPI#{dev_id}#{_RENDER_IF}" if dev_id else None
    f = _factory()
    for pid in pids:
        for role in (0, 1):  # console e multimídia
            h = _hstring(full)
            try:
                _call(f, _SET_APP, pid, 0, role, h, argtypes=(wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_void_p))
            finally:
                if h.value:
                    _combase.WindowsDeleteString(h)
    return f"{g['name']}: saindo em {name}." if dev_id else f"{g['name']}: segue a saída padrão."


@_com
def mic_mute(mute: bool | None = None) -> str:
    """Muta (ou tira do mudo) todos os microfones. mute=None alterna."""
    devs = AudioUtilities.GetAllDevices(data_flow=1, device_state=1)
    if not devs:
        return "Nenhum microfone ligado."
    if mute is None:
        first = AudioUtilities.GetMicrophone()
        mute = not bool(AudioUtilities.CreateDevice(first).EndpointVolume.GetMute()) if first else True
    for d in devs:
        try:
            d.EndpointVolume.SetMute(1 if mute else 0, None)
        except Exception:
            pass
    return "Microfone mudo." if mute else "Microfone ligado."


def _find_output(name: str) -> dict | None:
    from .audio import _norm
    key = _norm(name)
    for d in outputs()["outputs"]:
        if key in _norm(d["name"]):
            return d
    aliases = {"fone": ("fone", "headset", "headphone", "head"), "caixa": ("alto-falante", "speaker", "caixa", "realtek")}
    for k, words in aliases.items():
        if k in key:
            for d in outputs()["outputs"]:
                if any(w in _norm(d["name"]) for w in words):
                    return d
    return None


def audio_output(device: str = "", app: str = "") -> str:
    """Para a IA: sem nada = lista; device = troca a saída (de tudo, ou só do app)."""
    info = outputs()
    if not device:
        cur = next((d["name"] for d in info["outputs"] if d["id"] == info["default"]), "?")
        return f"Saída padrão: {cur}. Disponíveis: " + ", ".join(d["name"] for d in info["outputs"]) + "."
    if device.lower() in ("padrao", "padrão", "normal", "reset"):
        return set_app_output(app, "") if app else "Diga qual programa deve voltar para a saída padrão."
    d = _find_output(device)
    if not d:
        return f"Não achei a saída '{device}'. Disponíveis: " + ", ".join(x["name"] for x in info["outputs"]) + "."
    try:
        return set_app_output(app, d["id"]) if app else set_default(d["id"])
    except OSError as e:
        return str(e)
