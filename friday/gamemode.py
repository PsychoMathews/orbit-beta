"""Modo jogo: não perturbe de verdade.

Ligado:
- A assistente não escuta nem fala pelo PC: Ctrl+Alt+F e o microfone/pergunta da ilha ficam desativados.
- Avisos passam só se forem dos tipos liberados (padrão: lembretes, reuniões, timers e aviso de desligar o PC).
  Os outros (e-mails, renders, alertas do sistema, cota do Claude...) ficam guardados e chegam num resumo quando o modo desliga.
- As notificações do Windows (balões dos programas) são silenciadas, e voltam como estavam ao desligar.
- A ilha some da tela, exceto para mostrar os avisos liberados.
Telegram e Alexa continuam respondendo (são pedidos explícitos, não ativam sem querer).
"""
import json
import logging
import time
import winreg
from datetime import datetime
from pathlib import Path

from .tools_common import TZ, fn
from .paths import MEMORIA

log = logging.getLogger("friday.gamemode")

STATE_FILE = MEMORIA / "modo-jogo.json"
TOAST_KEY = r"Software\Microsoft\Windows\CurrentVersion\PushNotifications"

KINDS = {"reminder": "Lembretes", "meeting": "Reuniões", "timer": "Timers", "shutdown": "Aviso de desligar o PC",
         "email": "E-mails importantes", "render": "Renders do DaVinci", "alert": "Alertas do sistema",
         "claude": "Cota do Claude", "brief": "Resumo da manhã", "windows": "Energia (modo acordado)"}
DEFAULT = {"on": False, "since": None, "allow": ["reminder", "meeting", "timer", "shutdown"], "speak": True,
           "held": [], "toasts_before": None}


def _load() -> dict:
    try:
        return {**DEFAULT, **json.loads(STATE_FILE.read_text(encoding="utf-8"))}
    except Exception:
        return dict(DEFAULT)


def _save(s: dict) -> None:
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    from . import orbit
    orbit.publish("gamemode", **public(s))


def public(s: dict | None = None) -> dict:
    s = s or _load()
    return {"on": s["on"], "since": s["since"], "allow": s["allow"], "speak": s["speak"], "held": len(s["held"]),
            "kinds": KINDS}


def is_on() -> bool:
    return _load()["on"]


def allows(kind: str) -> bool:
    s = _load()
    return not s["on"] or kind in s["allow"]


def speak_allowed() -> bool:
    s = _load()
    return not s["on"] or s["speak"]


def hold(text: str, kind: str) -> None:
    s = _load()
    s["held"].append({"text": text, "kind": kind, "t": time.time()})
    s["held"] = s["held"][-50:]
    _save(s)


def _toasts(enabled: bool | None) -> int | None:
    """Liga/desliga os balões de notificação do Windows. Retorna o valor anterior (None = não existia)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, TOAST_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            try:
                before = winreg.QueryValueEx(k, "ToastEnabled")[0]
            except FileNotFoundError:
                before = None
            if enabled is None:
                winreg.DeleteValue(k, "ToastEnabled")
            else:
                winreg.SetValueEx(k, "ToastEnabled", 0, winreg.REG_DWORD, 1 if enabled else 0)
            return before
    except FileNotFoundError:
        return None
    except Exception:
        log.exception("Não consegui mexer nas notificações do Windows")
        return None


def _free_gpu() -> None:
    """Tira o modelo da IA da placa de vídeo (o jogo fica com ela toda)."""
    try:
        import httpx
        from . import config
        httpx.post(f"{config.OLLAMA_URL}/api/generate", json={"model": config.OLLAMA_MODEL, "keep_alive": 0}, timeout=20)
        from . import voice
        voice.unload_whisper()
    except Exception:
        log.warning("Não consegui descarregar o modelo da placa", exc_info=True)


def set_mode(on: bool) -> tuple[str, list[dict]]:
    """Retorna (mensagem, avisos guardados para entregar)."""
    s = _load()
    if bool(on) == s["on"]:
        return ("O modo jogo já está " + ("ligado." if on else "desligado."), [])
    held = []
    if on:
        s.update(on=True, since=time.time(), held=[])
        s["toasts_before"] = _toasts(False)
        _free_gpu()
        msg = ("🎮 Modo jogo ligado: não escuto nem falo pelo PC e as notificações do Windows estão silenciadas. "
               "Só passam: " + ", ".join(KINDS[k].lower() for k in s["allow"]) + ".")
    else:
        held = s["held"]
        before = s.get("toasts_before")
        _toasts(None if before is None else bool(before))
        mins = int((time.time() - (s["since"] or time.time())) / 60)
        s.update(on=False, since=None, held=[], toasts_before=None)
        msg = f"🎮 Modo jogo desligado ({mins} min). " + (f"Guardei {len(held)} aviso(s) para você." if held else "Nenhum aviso ficou guardado.")
    _save(s)
    return msg, held


def configure(allow: list[str] | None = None, speak: bool | None = None) -> dict:
    s = _load()
    if allow is not None:
        s["allow"] = [k for k in allow if k in KINDS]
    if speak is not None:
        s["speak"] = bool(speak)
    _save(s)
    return public(s)


def summary(held: list[dict]) -> str:
    lines = [f"• {datetime.fromtimestamp(h['t'], TZ):%H:%M} {h['text']}" for h in held]
    return "🎮 Enquanto você jogava:\n" + "\n".join(lines)


_deliver = None  # definido pelo bot.py: entrega os avisos guardados (Telegram + ilha)


def game_mode(on: bool = True) -> str:
    msg, held = set_mode(on)
    if held and _deliver:
        _deliver(held)
    return msg


TOOLS = {"game_mode": game_mode}
SCHEMAS = [
    fn("game_mode", "Liga ou desliga o MODO JOGO (não perturbe): a assistente para de ouvir/falar no PC, notificações do Windows "
       "silenciadas, só lembretes/reuniões/timers passam. Desligar entrega o resumo do que chegou.", {
           "on": {"type": "boolean"},
       }, ["on"]),
]
