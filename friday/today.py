"""'O que eu tenho pra fazer hoje?' / 'Hoje é dia de quê?': junta tudo do dia num lugar só.

Agenda do Google, lembretes, timers, listas, bloco de notas, Inbox do cofre, pendências do último Diário e a rotina
fixa da semana (Rotina.md no cofre: treino, aulas, hábitos por dia da semana, que ele mesmo escreve).
"""
import re
from datetime import datetime

from .tools_common import TZ, fn
from . import hub, proactive, vault

DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
ROTINA = vault.VAULT / "Rotina.md"
ROTINA_TEMPLATE = """# Rotina

> A Friday lê isto quando você pergunta "o que eu tenho hoje?". Escreva o que se repete em cada dia
> (treino, aulas, hábitos, horários fixos). Linhas embaixo de "Todo dia" valem para todos os dias.

## Todo dia
-

## Segunda
-

## Terça
-

## Quarta
-

## Quinta
-

## Sexta
-

## Sábado
-

## Domingo
-
"""


def _section(text: str, title: str) -> str:
    m = re.search(rf"^## {title}\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    lines = [l for l in (m.group(1).splitlines() if m else []) if l.strip() not in ("", "-")]
    return "\n".join(lines)


def _rotina(day: int) -> str:
    if not ROTINA.exists():
        ROTINA.write_text(ROTINA_TEMPLATE, encoding="utf-8")
    text = ROTINA.read_text(encoding="utf-8")
    parts = [p for p in (_section(text, "Todo dia"), _section(text, DIAS[day])) if p]
    return "\n".join(parts)


def _pendencias() -> str:
    """Pendências do Diário mais recente (a revisão da noite escreve lá o que ficou pendente)."""
    days = sorted((vault.VAULT / "Diário").glob("*.md"))
    if not days:
        return ""
    text = days[-1].read_text(encoding="utf-8")
    m = re.search(r"pendente.*?\n(.*?)(?=^#|\Z)", text, re.I | re.S | re.M)
    return f"({days[-1].stem}) " + m.group(1).strip()[:1500] if m else ""


def my_day() -> str:
    from . import google_auth, tools
    now = datetime.now(TZ)
    out = [f"HOJE: {DIAS[now.weekday()]}-feira, {now:%d/%m/%Y}, agora {now:%H:%M}".replace("Sábado-feira", "Sábado")
           .replace("Domingo-feira", "Domingo")]

    def add(title, fn_):
        try:
            text = (fn_() or "").strip()
        except Exception as e:
            text = f"(não consegui ler: {e})"
        if text:
            out.append(f"\n== {title} ==\n{text}")

    if google_auth.connected():
        add("AGENDA DE HOJE", lambda: tools.list_events(1, f"{now:%Y-%m-%d}"))
    add("ROTINA FIXA DE HOJE (Rotina.md)", lambda: _rotina(now.weekday()) or "nada escrito para hoje")
    add("LEMBRETES", proactive.list_reminders)
    add("TIMERS", hub.timer_list)
    add("LISTAS", hub.list_show)
    add("BLOCO DE NOTAS", lambda: hub.note_read()[:1500])
    add("INBOX DO COFRE", lambda: "\n".join(l for l in vault.INBOX.read_text(encoding="utf-8").splitlines()
                                             if l.startswith("- "))[-1500:] if vault.INBOX.exists() else "")
    add("PENDÊNCIAS DO ÚLTIMO DIÁRIO", _pendencias)
    out.append("\n(Monte um resumo falado do dia, na ordem do horário. Diga o dia da semana e o que a rotina pede;"
               " não leia tudo cru, destaque o que é para hoje.)")
    return "\n".join(out)


TOOLS = {"my_day": my_day}
SCHEMAS = [
    fn("my_day", "Tudo do dia do usuário: agenda, rotina fixa (treino etc.), lembretes, timers, listas, notas e"
       " pendências. Use para 'o que eu tenho hoje', 'hoje é dia de quê', 'como está meu dia'.", {}),
]
