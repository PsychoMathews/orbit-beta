"""Cérebro pelo plano do Claude do usuário (Claude Code logado na conta dele), sem API paga.

Cada pergunta roda `claude -p` com o prompt da Friday no lugar do prompt do Claude Code (bem mais barato),
sem as ferramentas de programação, com busca na internet e com as ferramentas da Friday via MCP (mcp_server.py).
Gasta cota do plano, não dinheiro. PLAN_DAILY_LIMIT limita quantas perguntas por dia vão para o Claude.
"""
import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from . import claude_agent, orbit, tools
from .paths import DATA_DIR

log = logging.getLogger("friday.plan")

DAILY_LIMIT = int(os.getenv("PLAN_DAILY_LIMIT", "150"))
NOT_FOR_PLAN = {"claude_think", "claude_jobs", "web_search", "read_page"}  # ele mesmo pesquisa (WebSearch/WebFetch)
_count = {"day": None, "n": 0}


def _schemas(with_google: bool) -> Path:
    every = tools.MEMORY_SCHEMAS + tools.PC_SCHEMAS + tools.EXTRA_SCHEMAS + (tools.GOOGLE_SCHEMAS if with_google else [])
    out, seen = [], set()
    for s in every:
        f = s["function"]
        if f["name"] in NOT_FOR_PLAN or f["name"] in seen:
            continue
        seen.add(f["name"])
        out.append({"name": f["name"], "description": f["description"], "inputSchema": f["parameters"]})
    out.sort(key=lambda t: t["name"])  # ordem fixa ajuda o cache
    path = DATA_DIR / ".mcp-tools.json"
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return path


def available() -> bool:
    today = date.today()
    if _count["day"] != today:
        _count.update(day=today, n=0)
    return _count["n"] < DAILY_LIMIT


def _conversation(history, text: str, note: str) -> str:
    lines = []
    for m in list(history)[-16:]:
        who = "Ele" if m["role"] == "user" else "Você"
        lines.append(f"{who}: {m['content']}")
    past = ("Conversa até agora:\n" + "\n".join(lines) + "\n\n") if lines else ""
    return f"{past}Mensagem nova dele: {text}" + (f"\n\n[sistema] {note}" if note else "")


def _run(system: str, prompt: str, with_google: bool) -> dict:
    mcp = {"mcpServers": {"friday": {
        "command": str(Path(sys.executable).with_name("python.exe")), "args": ["-m", "friday.mcp_server"],
        "env": {"FRIDAY_TOOL_URL": f"http://127.0.0.1:{orbit.PORT}/orbit/tool", "FRIDAY_TOOL_TOKEN": orbit.TOOL_TOKEN,
                "FRIDAY_TOOLS_FILE": str(_schemas(with_google)), "PYTHONPATH": str(Path(__file__).parent.parent)},
    }}}
    cmd = [claude_agent.CLAUDE, "-p", prompt, "--output-format", "json", "--model", claude_agent.MODEL,
           "--system-prompt", system, "--tools", "WebSearch,WebFetch",
           "--mcp-config", json.dumps(mcp), "--strict-mcp-config",
           "--allowedTools", "mcp__friday,WebSearch,WebFetch",
           "--setting-sources", "", "--no-session-persistence"]
    r = subprocess.run(cmd, cwd=Path(__file__).parent.parent, env=claude_agent.PLAN_ENV, capture_output=True,
                       text=True, encoding="utf-8", timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        return json.loads(r.stdout or "{}")
    except ValueError:
        return {"is_error": True, "result": (r.stderr or r.stdout)[:500]}


async def ask(system: str, history, text: str, with_google: bool, note: str = "") -> tuple[str, set, list]:
    """Mesmo contrato do cloud.ask: (resposta, ferramentas usadas, ids de ações pendentes)."""
    _count["n"] += 1
    before = set(tools.pending)
    orbit.tool_calls.clear()
    data = await asyncio.to_thread(_run, system, _conversation(history, text, note), with_google)
    usage = data.get("usage") or {}
    log.info("Plano: %s, %.1fs, entrada %s, cache gravado %s, cache lido %s, saída %s, equivalente US$ %s (cota, não cobrado), %d/%d hoje",
             claude_agent.MODEL, (data.get("duration_ms") or 0) / 1000, usage.get("input_tokens"),
             usage.get("cache_creation_input_tokens"), usage.get("cache_read_input_tokens"), usage.get("output_tokens"),
             data.get("total_cost_usd"), _count["n"], DAILY_LIMIT)
    if data.get("is_error"):
        raise RuntimeError(f"Claude pelo plano falhou: {data.get('result')}")
    new_pending = [k for k in tools.pending if k not in before]
    return (data.get("result") or "").strip(), set(orbit.tool_calls), new_pending
