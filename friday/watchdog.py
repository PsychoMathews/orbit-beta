"""Vigia da Friday. Roda a cada 5 minutos pelo Agendador de Tarefas do Windows.

- Se o bot não está rodando, ou está "travado" (sem batimento há mais de 3 min), reinicia e avisa no Telegram.
- Com --restart, reinicia sempre (usado no reinício diário de madrugada, que zera sessões presas).
Logs do bot: memoria/bot.log. Logs do vigia: memoria/vigia.log.
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import psutil

from . import config
from .paths import APP_DIR, MEMORIA
from . import assistente

ROOT = APP_DIR
HEARTBEAT = MEMORIA / ".heartbeat"
BOT_LOG = MEMORIA / "bot.log"
WATCH_LOG = MEMORIA / "vigia.log"
# .venv no modo de desenvolvimento; no programa instalado, o Python embutido que roda este vigia.
PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
if not PYTHONW.exists():
    PYTHONW = Path(sys.executable).with_name("pythonw.exe")
STALE_SECONDS = 180


def _log(msg: str) -> None:
    WATCH_LOG.parent.mkdir(exist_ok=True)
    with WATCH_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def _bot_processes() -> list[psutil.Process]:
    found = []
    for p in psutil.process_iter(["name", "cmdline"]):
        cmd = " ".join(p.info["cmdline"] or [])
        if "friday.bot" in cmd and p.info["name"] and p.info["name"].lower().startswith("python"):
            found.append(p)
    return found


def _alive() -> bool:
    try:
        return time.time() - float(HEARTBEAT.read_text()) < STALE_SECONDS
    except Exception:
        return False


def _notify(text: str) -> None:
    if not config.TELEGRAM_ON:
        return
    for uid in config.ALLOWED_USER_IDS:
        try:
            httpx.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                       data={"chat_id": uid, "text": text}, timeout=15)
        except Exception as e:
            _log(f"falha ao avisar no Telegram: {e}")


def _restart() -> None:
    for p in _bot_processes():
        try:
            p.kill()
        except psutil.Error:
            pass
    time.sleep(3)
    log = BOT_LOG.open("a", encoding="utf-8")
    subprocess.Popen(
        [str(PYTHONW), "-m", "friday.bot"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
    )


def main() -> None:
    forced = "--restart" in sys.argv
    running = bool(_bot_processes())
    if forced:
        _log("reinício diário")
        _restart()
    elif not running:
        _log("bot não estava rodando; iniciando")
        _restart()
    elif not _alive():
        _log("bot travado (sem batimento); reiniciando")
        _restart()
        _notify(f"⚠️ {assistente.com_artigo(True)} tinha travado e foi reiniciada pelo vigia.")


if __name__ == "__main__":
    main()
