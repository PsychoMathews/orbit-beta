"""Status line do Claude Code: mostra a cota embaixo do terminal e grava os números para a assistente e o Orbit.

O Claude Code chama este script a cada atualização, mandando um JSON no stdin. O campo rate_limits traz a janela
de 5 horas e a semanal (porcentagem usada e quando reinicia). Grava em memoria/claude_limits.json.
Sem dependências do resto do pacote: precisa ser rápido.
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "memoria" / "claude_limits.json"


def _epoch(value) -> float | None:
    """resets_at chega como segundos Unix ou como texto ISO, dependendo da versão."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None


def _window(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    pct = raw.get("used_percentage", raw.get("utilization"))
    return {"used_pct": float(pct) if pct is not None else None, "resets_at": _epoch(raw.get("resets_at"))}


def main() -> None:
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "ignore") or "{}")
    except ValueError:
        data = {}
    limits = data.get("rate_limits") or {}
    five, week = _window(limits.get("five_hour")), _window(limits.get("seven_day"))
    if five or week:
        try:
            OUT.parent.mkdir(exist_ok=True)
            tmp = OUT.with_suffix(".tmp")
            tmp.write_text(json.dumps({"updated": time.time(), "five_hour": five, "seven_day": week}), encoding="utf-8")
            tmp.replace(OUT)
        except OSError:
            pass
    parts = [str((data.get("model") or {}).get("display_name") or "Claude")]
    for label, w in (("5h", five), ("semana", week)):
        if w and w["used_pct"] is not None:
            reset = f" · volta {datetime.fromtimestamp(w['resets_at']):%H:%M}" if label == "5h" and w["resets_at"] else ""
            parts.append(f"{label} {w['used_pct']:.0f}%{reset}")
    print(" | ".join(parts))


if __name__ == "__main__":
    main()
