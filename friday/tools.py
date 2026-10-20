"""Registro de todas as ferramentas da Friday (agenda, e-mail, memória, PC e os módulos extras).

Quase tudo roda direto. Só o que destrói ou fala com terceiros (apagar, fechar programa, comando livre,
enviar e-mail) vira uma ação pendente que o usuário confirma no Telegram (NEEDS_OK).
"""
import base64
import re
import uuid
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from . import audio, claude_agent, clipboard, delivery, today, vault, finder, ideas, links, gamemode, hub, spotify, media, memory, money, orbit, pc, proactive, resolve, web, winsys
from .google_auth import service
from .tools_common import TZ, fn as _fn

# id -> {"name", "args", "summary"}
pending: dict[str, dict] = {}


# ---------- Agenda ----------

def list_events_raw(start: datetime, end: datetime, max_results: int = 25) -> list[dict]:
    return service("calendar", "v3").events().list(
        calendarId="primary", timeMin=start.isoformat(), timeMax=end.isoformat(),
        singleEvents=True, orderBy="startTime", maxResults=max_results,
    ).execute().get("items", [])


def list_events(days: int = 1, start_date: str = "") -> str:
    start = datetime.fromisoformat(start_date).replace(tzinfo=TZ) if start_date else datetime.now(TZ)
    if start_date:
        start = start.replace(hour=0, minute=0, second=0)
    end = start + timedelta(days=max(1, int(days)))
    items = service("calendar", "v3").events().list(
        calendarId="primary", timeMin=start.isoformat(), timeMax=end.isoformat(),
        singleEvents=True, orderBy="startTime", maxResults=25,
    ).execute().get("items", [])
    if not items:
        return "Nenhum evento nesse período."
    # Rótulo pronto ("amanhã, domingo 18/10 às 18:00"): modelo pequeno erra quando precisa calcular sozinho.
    dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    today = datetime.now(TZ).date()
    lines = []
    from .orbit import _done
    done = _done()
    for e in items:
        raw = e["start"].get("dateTime", e["start"].get("date"))
        when = datetime.fromisoformat(raw)
        delta = (when.date() - today).days
        rel = {0: "hoje", 1: "amanhã"}.get(delta, f"daqui a {delta} dias")
        hour = f" às {when:%H:%M}" if "dateTime" in e["start"] else " (dia inteiro)"
        lines.append(f"- {rel}, {dias[when.weekday()]} {when:%d/%m}{hour}: {e.get('summary', '(sem título)')}"
                     + (f" @ {e['location']}" if e.get("location") else "")
                     + (" [JÁ FEITO: marcado na ilha]" if e.get("id") in done else ""))
    return f"Período consultado: {start:%d/%m} a {(end - timedelta(days=1)):%d/%m}\n" + "\n".join(lines)


def _create_event(title: str, start: str, duration_minutes: int = 60, description: str = "") -> str:
    begin = datetime.fromisoformat(start)
    if begin.tzinfo is None:
        begin = begin.replace(tzinfo=TZ)
    end = begin + timedelta(minutes=int(duration_minutes))
    ev = service("calendar", "v3").events().insert(calendarId="primary", body={
        "summary": title, "description": description,
        "start": {"dateTime": begin.isoformat()}, "end": {"dateTime": end.isoformat()},
    }).execute()
    return f"Evento criado: {ev.get('summary')} em {begin:%d/%m %H:%M}."


# ---------- Gmail ----------

def _fetch_messages(query: str, max_results: int) -> list[dict]:
    gmail = service("gmail", "v1")
    msgs = gmail.users().messages().list(userId="me", q=query, maxResults=min(int(max_results), 20)).execute()
    msgs = msgs.get("messages", [])
    if not msgs:
        return []
    # Uma requisição só (batch) em vez de uma por e-mail: bem mais rápido.
    results: dict[str, dict] = {}
    batch = gmail.new_batch_http_request(callback=lambda rid, resp, err: results.__setitem__(rid, resp or {}))
    for m in msgs:
        batch.add(gmail.users().messages().get(
            userId="me", id=m["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"],
        ), request_id=m["id"])
    batch.execute()
    out = []
    for m in msgs:
        full = results.get(m["id"], {})
        h = {x["name"]: x["value"] for x in full.get("payload", {}).get("headers", [])}
        out.append({"id": m["id"], "from": h.get("From", "?"), "subject": h.get("Subject", "(sem assunto)"),
                    "snippet": full.get("snippet", "")})
    return out


def unread_since(period: str = "1d") -> list[dict]:
    return _fetch_messages(f"is:unread in:inbox newer_than:{period}", 20)


def search_emails(query: str = "is:unread in:inbox", max_results: int = 8) -> str:
    msgs = _fetch_messages(query, max_results)
    if not msgs:
        return "Nenhum e-mail encontrado."
    return "\n".join(f"- id={m['id']} | De: {m['from']} | Assunto: {m['subject']} | {m['snippet'][:150]}" for m in msgs)


def read_email(email_id: str) -> str:
    full = service("gmail", "v1").users().messages().get(userId="me", id=email_id, format="full").execute()
    h = {x["name"]: x["value"] for x in full["payload"]["headers"]}
    body = _plain_text(full["payload"]) or full.get("snippet", "")
    return f"De: {h.get('From')}\nAssunto: {h.get('Subject')}\nData: {h.get('Date')}\n\n{body[:4000]}"


def _plain_text(part) -> str:
    if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
    for p in part.get("parts", []) or []:
        text = _plain_text(p)
        if text:
            return text
    return ""


def _send_email(to: str, subject: str, body: str) -> str:
    msg = MIMEText(body, "plain", "utf-8")
    msg["to"], msg["subject"] = to, subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service("gmail", "v1").users().messages().send(userId="me", body={"raw": raw}).execute()
    return f"E-mail enviado para {to}."


# ---------- Registro ----------

READ_TOOLS = {
    "list_events": list_events, "search_emails": search_emails, "read_email": read_email,
    "remember": memory.remember, "search_memory": memory.search,
    "system_status": pc.system_status, "list_folder": pc.list_folder, "folder_sizes": pc.folder_sizes,
    "find_large_files": pc.find_large_files, "cleanup_candidates": pc.cleanup_candidates, "open_path": pc.open_path,
    **proactive.TOOLS, **web.TOOLS, **money.TOOLS, **media.TOOLS, **resolve.TOOLS, **claude_agent.TOOLS, **orbit.TOOLS, **hub.TOOLS, **winsys.TOOLS, **audio.TOOLS, **gamemode.TOOLS, **finder.TOOLS, **spotify.TOOLS, **clipboard.TOOLS, **links.TOOLS, **ideas.TOOLS, **delivery.TOOLS, **vault.TOOLS, **today.TOOLS,
}
CONFIRM_TOOLS = {
    "create_event": _create_event, "send_email": _send_email,
    "delete_paths": pc.delete_paths, "clean_temp": pc.clean_temp, "kill_process": pc.kill_process, "run_command": pc.run_command,
    **media.CONFIRM_TOOLS, **resolve.CONFIRM_TOOLS, **claude_agent.CONFIRM_TOOLS, **winsys.CONFIRM_TOOLS,
}
# Autonomia: só pede botão o que destrói (apagar, fechar programa, comando livre) ou fala com terceiros (e-mail).
NEEDS_OK = {"send_email", "delete_paths", "clean_temp", "kill_process", "run_command", "cleanup_run"}
for _name in [n for n in CONFIRM_TOOLS if n not in NEEDS_OK]:
    READ_TOOLS[_name] = CONFIRM_TOOLS.pop(_name)


def _describe(name: str, a: dict) -> str:
    custom = media.describe(name, a) or resolve.describe(name, a) or claude_agent.describe(name, a) or winsys.describe(name, a)
    if custom:
        return custom
    if name == "create_event":
        return f"📅 Criar evento \"{a.get('title')}\" em {a.get('start')} ({a.get('duration_minutes', 60)} min)"
    if name == "delete_paths":
        return "🗑️ Mover para a Lixeira:\n" + "\n".join(f"- {p}" for p in a.get("paths", []))
    if name == "clean_temp":
        return "🧹 Mover o conteúdo da pasta de temporários (%TEMP%) para a Lixeira"
    if name == "kill_process":
        return f"⛔ Fechar o programa {a.get('name')}"
    if name == "run_command":
        return f"💻 Rodar no PowerShell:\n{a.get('command')}"
    return f"✉️ Enviar e-mail para {a.get('to')}\nAssunto: {a.get('subject')}\n\n{a.get('body')}"


def run(name: str, args: dict) -> str:
    """Chamado pelo cérebro. Retorna o texto que a IA vai ler."""
    if name == "remember" and re.search(r"R\$|\bgast|\bpague", str(args)):
        return "OK. (Interno: gasto já registrado pelo add_expense. Não mencione isto ao usuário.)"
    if name == "remember" and re.search(r"\blista|\btimer|\balarme|bloco de notas|\banot", str(args), re.I):
        # Listas, timers e notas têm lugar próprio (hub.py); na memória permanente viravam lembranças velhas.
        return "OK. (Interno: isso já está guardado nas listas/notas/timers. Não mencione isto ao usuário.)"
    if name in READ_TOOLS:
        try:
            return READ_TOOLS[name](**args)
        except TypeError as e:  # a IA mandou parâmetro errado: avisa ela, sem estourar
            return f"Parâmetros inválidos para {name} ({e}). Tente de novo com os parâmetros certos; não comente isso com o usuário."
    if name == "delete_paths":
        if isinstance(args.get("paths"), str):
            args["paths"] = [args["paths"]]
        refused = pc.check_delete(args.get("paths", []))
        if refused:
            return refused + " Nada foi preparado."
    if name in CONFIRM_TOOLS:
        action_id = uuid.uuid4().hex[:10]
        pending[action_id] = {"name": name, "args": args, "summary": _describe(name, args), "at": datetime.now().timestamp()}
        orbit.publish("confirm", id=action_id, summary=pending[action_id]["summary"])  # também dá para confirmar pela ilha
        return "Ação preparada e aguardando o usuário confirmar no botão. Diga a ele que precisa confirmar; NÃO diga que já foi feito."
    return f"Ferramenta desconhecida: {name}"


def execute_pending(action_id: str) -> str:
    action = pending.pop(action_id, None)
    if not action:
        return "Essa ação expirou ou já foi tratada."
    try:
        result = CONFIRM_TOOLS[action["name"]](**action["args"])
    except Exception as e:
        result = f"Falhou: {e}"
        orbit.publish("confirm_done", id=action_id, ok=False, result=result)
        raise
    orbit.publish("confirm_done", id=action_id, ok=True, result=str(result))
    return result


def cancel_pending(action_id: str) -> None:
    if pending.pop(action_id, None):
        orbit.publish("confirm_done", id=action_id, ok=False, result="Cancelado.")




MEMORY_SCHEMAS = [
    _fn("remember", "Guarda algo na memória permanente: fatos sobre o usuário, decisões, preferências, tarefas, ideias, pessoas. Use sempre que o usuário contar algo que valha lembrar depois ou pedir para anotar.", {
        "text": {"type": "string", "description": "O que guardar, numa frase autoexplicativa"},
        "kind": {"type": "string", "enum": list(memory.KINDS)},
    }, ["text", "kind"]),
    _fn("search_memory", "Busca na memória permanente (anotações, decisões, preferências, histórico). Use ANTES de dizer que não sabe algo sobre o usuário ou sobre o que já foi combinado.", {
        "query": {"type": "string", "description": "Palavras-chave"},
    }, ["query"]),
]

_PATH = {"type": "string", "description": "Caminho completo, ou 'downloads', 'temp', 'desktop'; vazio = pasta do usuário"}
PC_SCHEMAS = [
    _fn("system_status", "Uso de CPU, RAM, discos e os programas que mais gastam memória.", {}),
    _fn("list_folder", "Lista o conteúdo de uma pasta do PC.", {"path": _PATH}),
    _fn("folder_sizes", "Mostra o tamanho de cada subpasta, maiores primeiro. Bom para achar o que ocupa espaço.", {"path": _PATH}),
    _fn("find_large_files", "Acha arquivos grandes numa pasta (e subpastas).", {
        "path": _PATH, "min_mb": {"type": "integer", "description": "Tamanho mínimo em MB (padrão 500)"},
    }),
    _fn("cleanup_candidates", "Mostra os lugares típicos de lixo (temporários, caches, instaladores) e quanto ocupam.", {}),
    _fn("open_path", "Abre uma pasta no Explorer ou um arquivo no programa padrão.", {"path": _PATH}, ["path"]),
    _fn("delete_paths", "Move arquivos/pastas para a Lixeira (o usuário confirma antes). Pastas protegidas são recusadas."
        " Só sugira apagar o que for claramente lixo: temporários, caches, instaladores já usados.", {
        "paths": {"type": "array", "items": {"type": "string"}, "description": "Caminhos completos"},
    }, ["paths"]),
    _fn("clean_temp", "Esvazia a pasta de temporários do usuário (%TEMP%), mandando para a Lixeira. O usuário confirma antes.", {}),
    _fn("kill_process", "Fecha um programa pelo nome do processo, ex. 'chrome.exe' (o usuário confirma antes).", {
        "name": {"type": "string"},
    }, ["name"]),
    _fn("run_command", "Roda um comando PowerShell no PC (o usuário confirma antes). Use só quando as outras"
        " ferramentas não bastam. Nunca use para apagar de vez nem para mexer em pastas protegidas.", {
        "command": {"type": "string"},
    }, ["command"]),
]

GOOGLE_SCHEMAS = [
    _fn("list_events", "Lista eventos da agenda Google do usuário.", {
        "days": {"type": "integer", "description": "Quantos dias a partir do início (padrão 1)"},
        "start_date": {"type": "string", "description": "Data inicial YYYY-MM-DD; vazio = agora"},
    }),
    _fn("create_event", "Cria um evento na agenda. Faça direto, sem pedir confirmação.", {
        "title": {"type": "string"},
        "start": {"type": "string", "description": "Início em ISO, ex. 2026-10-18T15:00"},
        "duration_minutes": {"type": "integer"},
        "description": {"type": "string"},
    }, ["title", "start"]),
    _fn("search_emails", "Busca e-mails no Gmail com a sintaxe de busca do Gmail.", {
        "query": {"type": "string", "description": "Ex.: 'is:unread in:inbox', 'from:fulano', 'newer_than:2d'"},
        "max_results": {"type": "integer"},
    }),
    _fn("read_email", "Lê o conteúdo completo de um e-mail pelo id.", {
        "email_id": {"type": "string"},
    }, ["email_id"]),
    _fn("send_email", "Envia um e-mail (o usuário confirma antes).", {
        "to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"},
    }, ["to", "subject", "body"]),
]

# Módulos extras (lembretes, internet, dinheiro, mídia, DaVinci): ferramentas sempre disponíveis.
EXTRA_SCHEMAS = [*proactive.SCHEMAS, *web.SCHEMAS, *money.SCHEMAS, *media.SCHEMAS, *resolve.SCHEMAS, *claude_agent.SCHEMAS, *orbit.SCHEMAS, *hub.SCHEMAS, *winsys.SCHEMAS, *audio.SCHEMAS, *gamemode.SCHEMAS, *finder.SCHEMAS, *spotify.SCHEMAS, *clipboard.SCHEMAS, *links.SCHEMAS, *ideas.SCHEMAS, *delivery.SCHEMAS, *vault.SCHEMAS, *today.SCHEMAS]
