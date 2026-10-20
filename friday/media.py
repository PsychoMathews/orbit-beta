"""Mídia e programas: tocar/pausar/pular (Spotify, YouTube, qualquer player), volume, abrir programas, modo trabalho.

As teclas de mídia funcionam com qualquer player aberto, sem conta nem API.
Abrir programa: procura o atalho no Menu Iniciar (só abre o que está instalado; não roda comando arbitrário).
Modo trabalho: abre os programas de WORK_APPS e fecha os de WORK_CLOSE (no .env).
"""
import os
import unicodedata
from pathlib import Path

import keyboard
import psutil

from . import config
from .tools_common import fn

START_MENUS = [
    Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    Path.home() / "Desktop",
]

KEYS = {
    "play_pause": "play/pause media", "next": "next track", "previous": "previous track",
    "volume_up": "volume up", "volume_down": "volume down", "mute": "volume mute",
}


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def media_control(action: str, steps: int = 5) -> str:
    if action not in KEYS:
        return f"Ação inválida. Use: {', '.join(KEYS)}"
    times = max(1, min(int(steps), 25)) if action.startswith("volume_") and action != "volume_mute" else 1
    for _ in range(times):
        keyboard.send(KEYS[action])
    labels = {"play_pause": "Play/pause", "next": "Próxima faixa", "previous": "Faixa anterior",
              "volume_up": f"Volume +{times * 2}%", "volume_down": f"Volume -{times * 2}%", "mute": "Mudo alternado"}
    return labels[action] + "."


def _shortcuts() -> list[Path]:
    found = []
    for root in START_MENUS:
        if root.exists():
            found += [p for p in root.rglob("*.lnk") if "uninstall" not in p.name.lower() and "desinstal" not in p.name.lower()]
    return found


def open_app(name: str) -> str:
    q = _norm(name)
    candidates = [p for p in _shortcuts() if q in _norm(p.stem)]
    if not candidates:  # tenta palavra por palavra ("davinci" acha "DaVinci Resolve")
        words = [w for w in q.split() if len(w) > 2]
        candidates = [p for p in _shortcuts() if words and all(w in _norm(p.stem) for w in words)]
    if not candidates:
        return f"Não achei um programa chamado '{name}' no Menu Iniciar."
    best = min(candidates, key=lambda p: len(p.stem))
    os.startfile(best)
    return f"Abrindo {best.stem}."


def list_apps(filter: str = "") -> str:
    names = sorted({p.stem for p in _shortcuts() if _norm(filter) in _norm(p.stem)})
    return ", ".join(names[:80]) or "Nenhum."


def _work_mode() -> str:
    opened = [open_app(a) for a in config.WORK_APPS.split(";") if a.strip()]
    closing = {c.strip().lower() for c in config.WORK_CLOSE.split(";") if c.strip()}
    closed = set()
    for p in psutil.process_iter(["name"]):
        n = (p.info["name"] or "").lower()
        if n in closing:
            try:
                p.terminate()
                closed.add(n)
            except psutil.Error:
                pass
    return " ".join(opened) + (f" Fechei: {', '.join(sorted(closed))}." if closed else " Nada para fechar.")


TOOLS = {"media_control": media_control, "open_app": open_app, "list_apps": list_apps}
CONFIRM_TOOLS = {"work_mode": _work_mode}


def describe(name: str, args: dict) -> str | None:
    if name == "work_mode":
        return (f"💼 Modo trabalho\nAbrir: {config.WORK_APPS.replace(';', ', ')}\n"
                f"Fechar se estiverem abertos: {config.WORK_CLOSE.replace(';', ', ')}")
    return None


SCHEMAS = [
    fn("media_control", "Controla a música/vídeo tocando no PC (Spotify, YouTube...) e o volume.", {
        "action": {"type": "string", "enum": list(KEYS)},
        "steps": {"type": "integer", "description": "Para volume: quantos passos de 2% (padrão 5 = 10%)"},
    }, ["action"]),
    fn("open_app", "Abre um programa instalado pelo nome (ex.: 'DaVinci', 'Chrome', 'Spotify', 'OBS').", {
        "name": {"type": "string"},
    }, ["name"]),
    fn("list_apps", "Lista programas instalados (filtro opcional).", {"filter": {"type": "string"}}),
    fn("work_mode", "Modo trabalho: abre os programas de trabalho e fecha jogos/distrações", {}),
]
