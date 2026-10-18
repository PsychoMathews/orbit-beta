"""Vigia do Claude Code: percebe quando ele está trabalhando e avisa quando uma tarefa longa termina.

Lê só o fim dos registros de conversa (~/.claude/projects/*/*.jsonl), sem gastar cota.
"Trabalhando" = o registro mudou nos últimos segundos. "Terminou" = parou de mudar e a última resposta
fechou o turno (stop_reason end_turn). Avisa (ilha, voz e Telegram) se o turno durou LONG_TASK ou mais.
"""
import asyncio
import json
import logging
import time
from pathlib import Path

log = logging.getLogger("friday.claude_watch")

PROJECTS = Path.home() / ".claude" / "projects"
ACTIVE = 25        # s sem mudar no registro = parou
LONG_TASK = 120    # s: só avisa tarefas de 2 min ou mais
TAIL = 96 * 1024

_runs: dict[str, dict] = {}  # arquivo -> {"start", "project"}


def _tail(path: Path) -> list[dict]:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - TAIL))
            lines = f.read().decode("utf-8", "ignore").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[1:] if size > TAIL else lines:  # a primeira linha pode estar cortada
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def _finished(entries: list[dict]) -> bool:
    for e in reversed(entries):
        if e.get("type") == "assistant":
            return (e.get("message") or {}).get("stop_reason") == "end_turn"
        if e.get("type") == "user":
            return False
    return False


def _project(entries: list[dict], path: Path) -> str:
    for e in reversed(entries):
        if e.get("cwd"):
            return Path(e["cwd"]).name
    return path.parent.name.split("-")[-1]


def working() -> list[dict]:
    """Tarefas do Claude Code rodando agora: [{"project", "start"}] (start em segundos Unix)."""
    return sorted(({"project": r["project"], "start": int(r["start"])} for r in _runs.values()), key=lambda t: t["start"])


def _scan() -> list[dict]:
    """Atualiza _runs e devolve as tarefas que acabaram de terminar."""
    now = time.time()
    done = []
    try:
        files = [p for p in PROJECTS.glob("*/*.jsonl") if now - p.stat().st_mtime < 3600]
    except OSError:
        return done
    for p in files:
        key, age = str(p), now - p.stat().st_mtime
        run = _runs.get(key)
        if age < ACTIVE:
            if not run:
                _runs[key] = {"start": p.stat().st_mtime, "project": _project(_tail(p), p)}
            continue
        if run:
            entries = _tail(p)
            if not _finished(entries):
                if age > 600:  # parado há 10 min sem fechar o turno (esperando você ou travou): esquece
                    _runs.pop(key, None)
                continue
            _runs.pop(key, None)
            dur = p.stat().st_mtime - run["start"]
            if dur >= LONG_TASK:
                done.append({"project": run["project"], "seconds": int(dur)})
    for key in [k for k in _runs if not Path(k).exists()]:
        _runs.pop(key, None)
    return done


def _mins(s: int) -> str:
    m = round(s / 60)
    return f"{m // 60}h{m % 60:02d}" if m >= 60 else f"{m} min"


async def run(notify) -> None:
    from . import orbit
    last = None
    while True:
        try:
            for t in await asyncio.to_thread(_scan):
                await notify(f"✅ O Claude terminou a tarefa em {t['project']} ({_mins(t['seconds'])}).",
                             f"Chefe, o Claude terminou a tarefa em {t['project']}.", kind="claude_done")
            now = working()
            if now != last:
                orbit.publish("claude_work", tasks=now)
                last = now
        except Exception:
            log.exception("Erro vigiando o Claude Code")
        await asyncio.sleep(5)
