"""A Friday vir até você: lembretes, resumo da manhã, aviso de reunião e de e-mail urgente.

Um "relógio" roda a cada 30 s dentro do bot. Tudo que ele avisa vai para o Telegram (texto + voz)
e, se PC_SPEAK=1 no .env, também é falado nas caixas de som do PC.
Estado (lembretes, o que já foi avisado) fica em memoria/lembretes.json e memoria/.avisos.json.
"""
import asyncio
import os
import json
import logging
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from . import respostas
from . import config, google_auth
from .tools_common import TZ, fn
from .paths import MEMORIA

log = logging.getLogger("friday.proactive")

ROOT = MEMORIA
REMINDERS = ROOT / "lembretes.json"
STATE = ROOT / ".avisos.json"


# ---------- Armazenamento ----------

def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path: Path, data) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _parse_when(when: str) -> datetime:
    dt = datetime.fromisoformat(when.strip().replace("Z", ""))
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


# ---------- Repetição (como no Google Agenda) ----------
# repeat: "" (uma vez), "diario", "dias_uteis", "semanal", "mensal" ou dias da semana "seg,qua,sex".
_WD = {"seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sab": 5, "sáb": 5, "dom": 6}
_WD_NOMES = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def _repeat_norm(repeat: str) -> str | None:
    """Padroniza; None = inválido."""
    raw = _norm(repeat or "").strip()
    r = raw.replace(" ", "").replace("-", "_")
    if r in ("", "nao", "nunca", "umavez"):
        return ""
    if r in ("diario", "tododia", "todososdias"):
        return "diario"
    if r in ("dias_uteis", "diasuteis", "seg_sex", "segasex"):
        return "dias_uteis"
    if r in ("semanal", "todasemana", "toda_semana"):
        return "semanal"
    if r in ("mensal", "todomes"):
        return "mensal"
    if r in ("anual", "todoano", "aniversario"):
        return "anual"
    days = [d.strip()[:3] for d in re.split(r"\s*(?:,|;|/|\be\b)\s*", raw) if d.strip()]
    return ",".join(dict.fromkeys(days)) if days and all(d in _WD for d in days) else None


def _next(dt: datetime, repeat: str) -> datetime:
    if repeat == "diario":
        return dt + timedelta(days=1)
    if repeat == "semanal":
        return dt + timedelta(weeks=1)
    if repeat == "anual":
        try:
            return dt.replace(year=dt.year + 1)
        except ValueError:  # 29/02
            return dt.replace(year=dt.year + 1, day=28)
    if repeat == "mensal":
        month = dt.month % 12 + 1
        year = dt.year + (dt.month == 12)
        for day in (dt.day, 30, 29, 28):  # dia 31 vira o último dia do mês
            try:
                return dt.replace(year=year, month=month, day=day)
            except ValueError:
                continue
    days = {0, 1, 2, 3, 4} if repeat == "dias_uteis" else {_WD[d] for d in repeat.split(",")}
    nxt = dt + timedelta(days=1)
    while nxt.weekday() not in days:
        nxt += timedelta(days=1)
    return nxt


def _repeat_label(repeat: str) -> str:
    return {"": "", "diario": "todo dia", "dias_uteis": "de segunda a sexta", "semanal": "toda semana",
            "mensal": "todo mês", "anual": "todo ano"}.get(repeat, "toda " + ", ".join(repeat.split(",")))


# ---------- Ferramentas (a IA usa) ----------

def add_reminder(text: str, when: str = "", in_minutes: int = 0, repeat: str = "") -> str:
    try:
        dt = datetime.now(TZ) + timedelta(minutes=int(in_minutes)) if in_minutes else _parse_when(when)
    except (ValueError, TypeError):
        return f"Data/hora inválida: {when}. Use o formato 2026-10-18T18:00, ou in_minutes."
    if dt.year < datetime.now(TZ).year:  # modelo pequeno às vezes escreve um ano antigo
        dt = dt.replace(year=datetime.now(TZ).year)
    if dt < datetime.now(TZ) - timedelta(minutes=1):
        return "Esse horário já passou. Peça outro horário ao usuário."
    rep_ = _repeat_norm(repeat)
    if rep_ is None:
        return f"Repetição inválida: {repeat}. Use diario, dias_uteis, semanal, mensal, anual ou dias como 'seg,qua,sex'."
    if rep_ and rep_ not in ("diario", "semanal", "mensal", "anual", "dias_uteis") and dt.weekday() not in {_WD[d] for d in rep_.split(",")}:
        dt = _next(dt - timedelta(days=1), rep_)  # primeiro dia que bate com os dias pedidos
    items = _load(REMINDERS, [])
    rid = uuid.uuid4().hex[:6]
    items.append({"id": rid, "text": text, "when": dt.isoformat(), "done": False, "repeat": rep_})
    _save(REMINDERS, items)
    if rep_:
        return f"Lembrete criado para {dt:%d/%m às %H:%M}, repetindo {_repeat_label(rep_)}: {text}. (id={rid})"
    return (f"Lembrete criado para {dt:%d/%m às %H:%M}: {text}. (id={rid}) Se for algo que costuma se repetir"
            " (treino, reunião, aula, conta, remédio), pergunte se ele quer que repita e, se sim, use reminder_repeat.")


def reminder_repeat(reminder: str, repeat: str) -> str:
    """Muda a repetição de um lembrete que já existe (id ou palavra do texto). repeat vazio = só uma vez."""
    rep_ = _repeat_norm(repeat)
    if rep_ is None:
        return f"Repetição inválida: {repeat}. Use diario, dias_uteis, semanal, mensal, anual ou dias como 'seg,qua,sex'."
    items = _load(REMINDERS, [])
    q = _norm(reminder)
    words = [w for w in re.findall(r"\w+", q) if len(w) > 2 and w != "lembrete"]
    hits = [r for r in items if not r["done"] and (r["id"] == reminder or (words and all(w in _norm(r["text"]) for w in words)))]
    if not hits:
        return "Nenhum lembrete pendente com isso. Use list_reminders para ver os que existem."
    for r in hits:
        r["repeat"] = rep_
    _save(REMINDERS, items)
    how = f"repetindo {_repeat_label(rep_)}" if rep_ else "só uma vez"
    return "Pronto, " + how + ": " + "; ".join(r["text"] for r in hits)


def list_reminders() -> str:
    items = [r for r in _load(REMINDERS, []) if not r["done"]]
    if not items:
        return "Nenhum lembrete pendente."
    items.sort(key=lambda r: r["when"])
    return "\n".join(f"- id={r['id']} | {_parse_when(r['when']):%d/%m %H:%M} | {r['text']}"
                     + (f" | repete {_repeat_label(r['repeat'])}" if r.get("repeat") else "") for r in items)


def _norm(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def cancel_reminder(reminder: str) -> str:
    """Aceita o id ou um pedaço do texto ("Rafael")."""
    items = _load(REMINDERS, [])
    q = _norm(reminder)
    words = [w for w in re.findall(r"\w+", q) if len(w) > 2 and w not in ("lembrete", "cancela", "cancelar")]
    hits = [r for r in items if not r["done"] and (r["id"] == reminder or (words and all(w in _norm(r["text"]) for w in words)))]
    if not hits:
        return "Nenhum lembrete pendente com isso. Use list_reminders para ver os que existem."
    for r in hits:
        r["done"] = True
    _save(REMINDERS, items)
    return "Cancelado: " + "; ".join(f"{r['text']} ({_parse_when(r['when']):%d/%m %H:%M})" for r in hits)


TOOLS = {"add_reminder": add_reminder, "list_reminders": list_reminders, "cancel_reminder": cancel_reminder,
         "reminder_repeat": reminder_repeat}
SCHEMAS = [
    fn("add_reminder", "Cria um lembrete: no horário, a Friday avisa o usuário por voz e no Telegram."
       " Use para 'me lembra de...', 'me avisa às...'.", {
           "text": {"type": "string", "description": "O que lembrar, do jeito que será dito ao usuário"},
           "when": {"type": "string", "description": "Data e hora ISO, ex. 2026-10-18T18:00"},
           "in_minutes": {"type": "integer", "description": "Para 'daqui a X': minutos a partir de agora (2 horas = 120)"},
           "repeat": {"type": "string", "description": "Repetição: vazio (uma vez), diario, dias_uteis, semanal,"
                      " mensal, anual (aniversários e datas), ou dias da semana 'seg,qua,sex'. Só use se ele disse que repete."},
       }, ["text"]),
    fn("reminder_repeat", "Faz um lembrete existente se repetir (ou parar de repetir). Use depois que ele confirmar"
       " que o lembrete se repete.", {
           "reminder": {"type": "string", "description": "id ou palavra-chave do lembrete"},
           "repeat": {"type": "string", "description": "diario, dias_uteis, semanal, mensal, 'seg,qua,sex' ou vazio"},
       }, ["reminder", "repeat"]),
    fn("list_reminders", "Lista os lembretes pendentes.", {}),
    fn("cancel_reminder", "Cancela lembrete(s) pelo id ou por uma palavra do texto, ex. 'Rafael'.", {
        "reminder": {"type": "string", "description": "id ou palavra-chave do lembrete"},
    }, ["reminder"]),
]


# ---------- Relógio ----------

def _quiet(now: datetime) -> bool:
    """Horário de silêncio para avisos automáticos (lembretes que você marcou sempre tocam)."""
    start, end = config.QUIET_START, config.QUIET_END
    return (now.hour >= start or now.hour < end) if start > end else start <= now.hour < end


# ---------- Desacelerar (ele se cobra demais) ----------
SLOW_PER_WEEK = int(os.getenv("SLOW_DOWN_PER_WEEK", "2"))


def _next_slow(after: datetime) -> datetime:
    """Próximo momento aleatório: dia útil, entre 14h e 18h, uns dias depois (cerca de SLOW_PER_WEEK por semana)."""
    import random
    day = after + timedelta(days=random.randint(2, 4) if SLOW_PER_WEEK <= 2 else random.randint(1, 2))
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.replace(hour=random.randint(14, 17), minute=random.randint(0, 59), second=0, microsecond=0)


async def _slow_down(now: datetime, state: dict, notify, ask_brain) -> None:
    if SLOW_PER_WEEK <= 0:
        return
    when = state.get("slow_next")
    if not when:
        state["slow_next"] = _next_slow(now).isoformat()
        return
    if now < _parse_when(when):
        return
    state["slow_next"] = _next_slow(now).isoformat()
    text = await ask_brain(
        "Escreva UMA mensagem curta (1 a 2 frases) para o usuário dar uma desacelerada agora: ele se cobra demais"
        " com trabalho. Pode sugerir respirar, levantar, beber água, olhar algo bom que ele fez. Varie, use o que sabe"
        " dele (Eu.md), sem clichê de coach, sem exagero, com o seu jeito. Responda só a mensagem.", tools=False)
    if text:
        await notify(f"🌿 {text}", text, kind="proactive")


async def run(notify, ask_brain) -> None:
    """notify(text, speak_text): corrotina que avisa o usuário. ask_brain(prompt): resposta falada da Friday."""
    state = _load(STATE, {})
    tick = 0
    while True:
        try:
            now = datetime.now(TZ)
            await _due_reminders(now, notify)
            if tick % 2 == 0:  # a cada 1 min
                await _morning_brief(now, state, notify, ask_brain)
            if tick % 2 == 0:  # a cada 1 min
                await _render_watch(state, notify)
            if google_auth.connected() and tick % 4 == 0:  # a cada 2 min
                await _meeting_alerts(now, state, notify)
            if google_auth.connected() and tick % 4 == 0 and not _quiet(now):  # a cada 2 min
                await _urgent_emails(state, notify, ask_brain)
            if tick % 2 == 0:
                await _slow_down(now, state, notify, ask_brain)
            _save(STATE, state)
        except Exception:
            log.exception("Erro no relógio da Friday")
        tick += 1
        await asyncio.sleep(30)


async def _render_watch(state: dict, notify) -> None:
    from . import resolve
    try:  # processo à parte: com a timeline tocando o Resolve trava e levava o bot junto
        jobs = (await asyncio.to_thread(resolve.snapshot, 10)).get("jobs", [])
    except Exception:
        return
    previous = state.get("renders", {})
    current = {j["id"]: j["status"] for j in jobs}
    for j in jobs:
        before = previous.get(j["id"])
        if before and before != j["status"] and j["status"] in ("Complete", "Failed", "Cancelled"):
            if j["status"] == "Complete":
                await notify(f"🎬 Render pronto: {j['name']}", f"Chefe, o render {j['name']} terminou.", kind="render")
            else:
                await notify(f"⚠️ Render {j['status']}: {j['name']}", f"Chefe, o render {j['name']} falhou.", kind="render")
    state["renders"] = current


async def _due_reminders(now: datetime, notify) -> None:
    items = _load(REMINDERS, [])
    fired = False
    for r in items:
        if not r["done"] and _parse_when(r["when"]) <= now:
            if r.get("repeat"):  # repete: agenda a próxima (pula as que passaram com o PC desligado)
                nxt = _parse_when(r["when"])
                while nxt <= now:
                    nxt = _next(nxt, r["repeat"])
                r["when"] = nxt.isoformat()
            else:
                r["done"] = True
            fired = True
            oque = respostas.assunto(r["text"])
            await notify(f"⏰ Lembrete: {r['text']}", respostas.fala("lembrete_fim", oque=oque) if oque
                         else respostas.fala("lembrete_fim_sem_assunto"), kind="reminder")
    if fired:
        _save(REMINDERS, items)


async def _morning_brief(now: datetime, state: dict, notify, ask_brain) -> None:
    if not config.MORNING_TIME:
        return
    hh, mm = (int(x) for x in config.MORNING_TIME.split(":"))
    today = now.strftime("%Y-%m-%d")
    if state.get("morning") == today or (now.hour, now.minute) < (hh, mm) or now.hour >= hh + 3:
        return
    state["morning"] = today
    text = await ask_brain(await _morning_prompt(now), tools=False)
    await notify(f"☀️ Resumo da manhã\n\n{text}", text, kind="brief")


async def _morning_prompt(now: datetime) -> str:
    """O código busca os dados de verdade; a IA só escreve (assim ela não inventa compromisso nem clima)."""
    from . import tools, web

    async def get(func, *args):
        try:
            return await asyncio.to_thread(func, *args)
        except Exception as e:
            return f"(indisponível: {e})"

    events = await get(tools.list_events, 1, now.strftime("%Y-%m-%d")) if google_auth.connected() else "(agenda não conectada)"
    emails = await get(tools.search_emails, "is:unread in:inbox newer_than:1d -category:promotions -category:social", 8) \
        if google_auth.connected() else "(e-mail não conectado)"
    today_reminders = [r for r in _load(REMINDERS, []) if not r["done"] and _parse_when(r["when"]).date() == now.date()]
    reminders = "\n".join(f"- {_parse_when(r['when']):%H:%M} {r['text']}" for r in today_reminders) or "Nenhum."
    forecast = await get(web.weather, "", 1)
    return (
        "[resumo da manhã] Escreva o resumo da manhã para o usuário, falado, curto (até 5 frases), sem listas,"
        " como uma assistente no começo do dia. Use SOMENTE os dados abaixo; se uma parte estiver vazia, diga"
        " que está livre/sem novidades. Nos e-mails, cite só os que importam (ignore propaganda).\n\n"
        f"<dado_externo>\nAGENDA DE HOJE:\n{events}\n\nE-MAILS NÃO LIDOS (24h):\n{emails}\n\n"
        f"LEMBRETES DE HOJE:\n{reminders}\n\nCLIMA:\n{forecast}\n</dado_externo>"
    )


async def _meeting_alerts(now: datetime, state: dict, notify) -> None:
    from .tools import list_events_raw  # import tardio: evita ciclo
    alerted = state.setdefault("meetings", {})
    for ev in await asyncio.to_thread(list_events_raw, now, now + timedelta(minutes=config.MEETING_ALERT_MIN + 1)):
        start = ev["start"].get("dateTime")
        if not start:
            continue  # evento de dia inteiro não tem "começa em 10 min"
        key = f"{ev['id']}|{start}"
        minutes = round((_parse_when(start) - now).total_seconds() / 60)
        if key in alerted or minutes < 0:
            continue
        alerted[key] = now.isoformat()
        title = ev.get("summary", "um compromisso")
        when = "agora" if minutes <= 1 else f"em {minutes} minutos"
        offer = " Quer que eu grave? Diga 'grava a reunião'." if minutes >= 2 else ""
        await notify(f"📅 {title} começa {when}.{offer}", f"Chefe, {title} começa {when}.{offer}", kind="meeting")
    # limpa avisos antigos
    for k in [k for k, v in alerted.items() if _parse_when(v) < now - timedelta(days=2)]:
        alerted.pop(k)


def _people_names() -> list[str]:
    """Nomes da nota Pessoas do cofre (gente importante para a triagem de e-mail)."""
    from . import vault
    try:
        return re.findall(r"^\s*-\s*\*\*(.+?)\*\*", (vault.VAULT / "Pessoas.md").read_text(encoding="utf-8"), re.M)[:30]
    except Exception:
        return []


async def _urgent_emails(state: dict, notify, ask_brain) -> None:
    from .tools import unread_since
    seen = set(state.get("emails_seen", []))
    new = [m for m in await asyncio.to_thread(unread_since, "1d") if m["id"] not in seen]
    if not new:
        return
    state["emails_seen"] = list(seen | {m["id"] for m in new})[-500:]
    if not state.get("emails_initialized"):
        state["emails_initialized"] = True  # primeira vez: só marca como visto, não avisa o histórico todo
        return
    listing = "\n".join(f"{i}. De: {m['from']} | Assunto: {m['subject']} | {m['snippet'][:120]}" for i, m in enumerate(new))
    prompt = (
        "[triagem de e-mail] Destes e-mails novos, quais são URGENTES ou importantes de verdade para o usuário"
        " (cliente, trabalho, banco, cobrança, prazo, segurança da conta)? Propaganda, newsletter e notificação"
        " automática comum NÃO são." + (f" Gente próxima dele (sempre importante): {', '.join(_people_names())}." if _people_names() else "")
        + " Responda só com os números separados por vírgula, ou NENHUM.\n\n"
        f"<dado_externo>\n{listing}\n</dado_externo>"
    )
    answer = await ask_brain(prompt, tools=False)
    picks = [int(n) for n in re.findall(r"\d+", answer) if int(n) < len(new)]
    for i in dict.fromkeys(picks):
        m = new[i]
        sender = re.sub(r"\s*<.*?>", "", m["from"]).strip('" ')
        await notify(f"📧 E-mail importante de {sender}: {m['subject']}", f"Chefe, chegou um e-mail importante de {sender}: {m['subject']}", kind="email")
