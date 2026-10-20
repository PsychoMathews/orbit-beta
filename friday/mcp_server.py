"""Servidor MCP (stdio) que entrega as ferramentas da Friday ao Claude Code.

O Claude Code (cérebro pelo plano do usuário) abre este processo; cada chamada vira um POST na ponte local do bot
(/orbit/tool), então as ferramentas rodam DENTRO do bot: botões de confirmação, Telegram e ilha funcionam igual.
Variáveis: FRIDAY_TOOL_URL, FRIDAY_TOOL_TOKEN (senha da ponte), FRIDAY_TOOLS_FILE (JSON com as ferramentas liberadas).
"""
import json
import os
import sys

import httpx

URL = os.environ["FRIDAY_TOOL_URL"]
TOKEN = os.environ["FRIDAY_TOOL_TOKEN"]
with open(os.environ["FRIDAY_TOOLS_FILE"], encoding="utf-8") as _f:
    SCHEMAS = json.load(_f)  # [{name, description, inputSchema}]


def _reply(msg_id, result=None, error=None) -> None:
    out = {"jsonrpc": "2.0", "id": msg_id}
    out["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _call(name: str, args: dict) -> str:
    r = httpx.post(URL, json={"name": name, "args": args}, timeout=300,
                   headers={"X-Orbit": "1", "X-Friday-Token": TOKEN})
    r.raise_for_status()
    return r.json()["result"]


def main() -> None:
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method, msg_id = msg.get("method"), msg.get("id")
        if msg_id is None:  # notificação (ex.: initialized): não tem resposta
            continue
        if method == "initialize":
            _reply(msg_id, {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                            "capabilities": {"tools": {}}, "serverInfo": {"name": "friday", "version": "1"}})
        elif method == "tools/list":
            _reply(msg_id, {"tools": SCHEMAS})
        elif method == "tools/call":
            p = msg.get("params", {})
            try:
                text, err = _call(p.get("name", ""), p.get("arguments") or {}), False
            except Exception as e:
                text, err = f"Falha ao chamar a Friday: {e}", True
            _reply(msg_id, {"content": [{"type": "text", "text": text}], "isError": err})
        elif method == "ping":
            _reply(msg_id, {})
        else:
            _reply(msg_id, error={"code": -32601, "message": f"método desconhecido: {method}"})


if __name__ == "__main__":
    main()
