"""A assistente passa o trabalho pesado para o Claude (Claude Code em modo headless).

- claude_davinci: edição no DaVinci Resolve. O Claude só pode usar as ferramentas do DaVinci (MCP "DaVinci Resolve").
  Roda direto (autonomia); o Claude não apaga nada sem o pedido dizer.
- claude_think: tarefas pesadas de texto/raciocínio/pesquisa. Só pode ler a internet; nada no PC. Sem botão.
Roda em segundo plano: a assistente responde "passei pro Claude" na hora e avisa quando terminar.
Gasta a cota do plano do Claude do usuário (combinado com ele).
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .tools_common import fn
from .paths import DATA_DIR
from . import assistente

log = logging.getLogger("friday.claude")

ROOT = DATA_DIR
CLAUDE = shutil.which("claude") or str(Path.home() / ".local/bin/claude.exe")
TIMEOUT = 15 * 60

MODES = {
    "davinci": {
        "allowed": "mcp__DaVinci_Resolve__*",
        "intro": "Você está executando um pedido de edição no DaVinci Resolve aberto no PC dele, usando só as"
                 " ferramentas do DaVinci. Antes de mudar algo, confira o estado atual (projeto, timeline, bins)."
                 " Não apague mídia, timelines ou projetos inteiros a menos que o pedido diga isso claramente.",
    },
    "think": {
        "allowed": "WebSearch,WebFetch",
        "intro": "Você está fazendo uma tarefa pesada de texto, análise ou pesquisa. Você só pode ler a internet;"
                 " não tem acesso a arquivos nem ao PC.",
    },
}
DENIED = "Bash,Edit,Write,MultiEdit,NotebookEdit,PowerShell"
# Pesquisa, análise de link e ideias vão no Sonnet (gasta bem menos cota); mexer no DaVinci fica no Opus.
MODEL = os.getenv("CLAUDE_MODEL", "sonnet")
MODEL_DAVINCI = os.getenv("CLAUDE_DAVINCI_MODEL", "opus")
# Sem isto o Claude Code usa a ANTHROPIC_API_KEY do .env (cobrada à parte) em vez da conta/plano do usuário.
PLAN_ENV = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")}

_notify = None  # (loop, corrotina notify(text, speak_text)), configurado pelo bot
_running: dict[str, dict] = {}


def set_notifier(loop, notify) -> None:
    global _notify
    _notify = (loop, notify)


def _prompt(mode: str, task: str) -> str:
    return (
        f"Você é o Claude, chamado pel{assistente.ARTIGO} {assistente.NOME}, {assistente.ARTIGO} assistente de voz de {assistente.quem_usa()}"
        + (f" ({assistente.SOBRE_USUARIO}). " if assistente.SOBRE_USUARIO else ". ")
        + MODES[mode]["intro"]
        + "\n\nNo final, responda em português, em no máximo 4 frases curtas, faladas (sem markdown, sem listas),"
          " dizendo o que você fez ou encontrou. Se não conseguiu, diga o motivo.\n\nPEDIDO: " + task
    )


def _run(job_id: str, mode: str, task: str) -> None:
    started = time.time()
    try:
        r = subprocess.run(
            [CLAUDE, "-p", _prompt(mode, task), "--output-format", "json",
             "--model", MODEL_DAVINCI if mode == "davinci" else MODEL,
             "--allowedTools", MODES[mode]["allowed"], "--disallowedTools", DENIED],
            cwd=ROOT, env=PLAN_ENV, capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        data = json.loads(r.stdout or "{}")
        result = (data.get("result") or r.stderr or "O Claude não devolveu resposta.").strip()
        ok = not data.get("is_error") and r.returncode == 0
        log.info("Claude (%s) terminou em %.0fs, ok=%s, custo=%s", mode, time.time() - started, ok, data.get("total_cost_usd"))
    except subprocess.TimeoutExpired:
        result, ok = "O Claude passou de 15 minutos e eu interrompi.", False
    except Exception as e:
        log.exception("Erro chamando o Claude")
        result, ok = f"Não consegui chamar o Claude: {e}", False
    _running.pop(job_id, None)
    icon = "🤖" if ok else "⚠️"
    head = "Claude no DaVinci" if mode == "davinci" else "Claude"
    if _notify:
        loop, notify = _notify
        asyncio.run_coroutine_threadsafe(
            notify(f"{icon} {head}: {task[:120]}\n\n{result}", result), loop)


def _start(mode: str, task: str) -> str:
    if not Path(CLAUDE).exists() and not shutil.which("claude"):
        return "O Claude Code não está instalado neste PC."
    job_id = f"{mode}-{int(time.time() * 1000)}"
    _running[job_id] = {"mode": mode, "task": task, "since": time.time()}
    threading.Thread(target=_run, args=(job_id, mode, task), daemon=True).start()
    return "Passei pro Claude. Ele está trabalhando e eu te aviso quando terminar."


def claude_think(task: str) -> str:
    return _start("think", task)


def _claude_davinci(task: str) -> str:
    return _start("davinci", task)


def claude_jobs() -> str:
    if not _running:
        return "O Claude não está trabalhando em nada agora."
    return "\n".join(f"- {j['task'][:100]} (há {int(time.time() - j['since'])}s)" for j in _running.values())


TOOLS = {"claude_think": claude_think, "claude_jobs": claude_jobs}
CONFIRM_TOOLS = {"claude_davinci": _claude_davinci}


def describe(name: str, a: dict) -> str | None:
    if name == "claude_davinci":
        return f"🎬🤖 Passar pro Claude no DaVinci:\n{a.get('task')}"
    return None


SCHEMAS = [
    fn("claude_davinci", "Passa um pedido de EDIÇÃO no DaVinci Resolve para o Claude (criar/editar timelines, clipes,"
       " bins, marcadores, cortes, cor, legendas, configurar render, organizar mídia). Escreva o pedido completo e"
       " claro, com nomes e detalhes que o usuário deu.", {
           "task": {"type": "string", "description": "O pedido completo para o Claude, em português"},
       }, ["task"]),
    fn("claude_think", "Passa uma tarefa PESADA para o Claude: escrever textos longos, roteiros, propostas, e-mails"
       " elaborados, análises, explicações complexas, pesquisa aprofundada, código. Ele responde depois.", {
           "task": {"type": "string", "description": "A tarefa completa, com todo o contexto que o usuário deu"},
       }, ["task"]),
    fn("claude_jobs", "Mostra o que o Claude está fazendo agora.", {}),
]
