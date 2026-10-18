"""Dados que a assistente e o Orbit compartilham: timers, listas, notas e a cota do Claude.

A assistente é a dona desses dados: a ilha, o Telegram, a voz e a Alexa leem e mudam tudo por aqui.
- Timers: tocam no PC (voz), no Telegram e na ilha, venha o pedido de onde vier.
- Listas: "lista de compras", "filmes pra ver"... (memoria/listas.json).
- Notas: o bloco de notas da ilha (memoria/notas.txt); a IA lê e escreve nele.
- Cota do Claude: lê os registros locais do Claude Code (~/.claude/projects) e avisa quando o limite acaba e quando volta.
"""
import asyncio
import json
import logging
import re
import time
import unicodedata
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from . import respostas
from .tools_common import TZ, fn
from .paths import MEMORIA

log = logging.getLogger("friday.hub")

TIMERS = MEMORIA / "timers.json"
LISTS = MEMORIA / "listas.json"
NOTES = MEMORIA / "notas.txt"
QUOTA_STATE = MEMORIA / ".cota-claude.json"
CLAUDE_DIR = Path.home() / ".claude" / "projects"


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path: Path, data) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s.lower().strip()) if unicodedata.category(c) != "Mn")
    return re.sub(r"^(a |o |as |os )?(lista (de |do |da |dos |das )?)?", "", s).strip()


def _publish(kind: str, **data) -> None:
    from . import orbit
    orbit.publish(kind, **data)


# ---------- Timers ----------

def timers() -> list[dict]:
    items = _load(TIMERS, [])
    now = time.time()
    for t in items:
        t["left"] = round(t["paused"] if t.get("paused") is not None else t["end"] - now)
    return items


def _save_timers(items: list[dict]) -> None:
    for t in items:
        t.pop("left", None)
    _save(TIMERS, items)
    _publish("timers", timers=timers())


def timer_start(minutes: float, label: str = "Timer") -> str:
    minutes = max(0.1, min(float(minutes), 24 * 60))
    items = _load(TIMERS, [])
    items.append({"id": uuid.uuid4().hex[:8], "label": (label or "Timer").strip()[:40], "total": int(minutes * 60),
                  "end": time.time() + minutes * 60, "paused": None})
    _save_timers(items)
    end = datetime.now(TZ) + timedelta(minutes=minutes)
    return f"Timer '{label}' de {minutes:g} min iniciado; toca às {end:%H:%M:%S} no PC, no Telegram e na ilha."


def timer_list() -> str:
    items = timers()
    if not items:
        return "Nenhum timer rodando."
    return "\n".join(f"- {t['label']}: faltam {t['left'] // 60} min {t['left'] % 60} s" + (" (pausado)" if t.get("paused") is not None else "")
                     for t in items)


def _find_timer(items, key: str):
    key = _norm(key)
    return next((t for t in items if t["id"] == key or key in _norm(t["label"])), None) if key else (items[-1] if items else None)


def timer_cancel(label: str = "") -> str:
    items = _load(TIMERS, [])
    t = _find_timer(items, label)
    if not t:
        return "Não achei esse timer."
    items.remove(t)
    _save_timers(items)
    return f"Timer '{t['label']}' cancelado."


def timer_pause(timer_id: str) -> None:
    items = _load(TIMERS, [])
    t = _find_timer(items, timer_id)
    if not t:
        return
    if t.get("paused") is not None:
        t["end"], t["paused"] = time.time() + t["paused"], None
    else:
        t["paused"] = max(0, t["end"] - time.time())
    _save_timers(items)


def _timer_message(t: dict) -> tuple[str, str]:
    """(texto, fala) do aviso de fim do timer, sem repetir "timer Timer"."""
    label, mins = t["label"].strip(), t["total"] / 60
    if mins < 1:
        dur = f"{round(mins * 60)} segundos"
    elif mins < 60:
        dur = f"{round(mins)} minuto{'s' if round(mins) != 1 else ''}"
    else:
        h, m = divmod(round(mins), 60)
        dur = f"{h} hora{'s' if h != 1 else ''}" + (f" e {m} minutos" if m else "")
    R = respostas
    if label.lower().startswith("alarme "):
        hora = label[7:]
        return f"⏰ Alarme das {hora}.", R.fala("alarme_fim", hora=hora)
    if label.lower() == "pomodoro":
        return "🍅 Pomodoro terminou: hora da pausa.", R.fala("pomodoro_fim")
    oque = R.assunto(label)
    if not oque:
        return f"⏱️ Seu timer de {dur} acabou.", R.fala("timer_fim", dur=dur)
    return f"⏱️ Deu a hora: {label} ({dur}).", R.fala("timer_fim_oque", oque=oque)


async def _timer_loop(notify) -> None:
    seen, items = None, []
    while True:
        try:
            # Só relê o arquivo quando ele muda (antes lia o disco a cada segundo).
            mtime = TIMERS.stat().st_mtime_ns if TIMERS.exists() else 0
            if mtime != seen:
                seen, items = mtime, _load(TIMERS, [])
            due = [t for t in items if t.get("paused") is None and t["end"] <= time.time()]
            if due:
                _save_timers([t for t in items if t not in due])
                for t in due:
                    await notify(*_timer_message(t), kind="timer")
        except Exception:
            log.exception("Erro nos timers")
        await asyncio.sleep(1)


# ---------- Listas ----------

def _lists() -> dict[str, list[str]]:
    return _load(LISTS, {})


def _save_lists(data: dict) -> None:
    _save(LISTS, data)
    _publish("lists", lists=data)


def _list_key(data: dict, name: str) -> str:
    n = _norm(name) or "geral"
    for k in data:
        if _norm(k) == n:
            return k
    close = [k for k in data if _norm(k).startswith(n) or n in _norm(k)]
    if len(close) == 1:  # "compras" acha "compras do mês"
        return close[0]
    # Nome novo: mantém acentos, tira só o "lista de" do começo.
    clean = re.sub(r"^(a |o |as |os )?(lista (de |do |da |dos |das )?)?", "", name.strip(), flags=re.I).strip().lower()
    return clean or "geral"


def list_add(list_name: str, items: list[str] | str) -> str:
    if isinstance(items, str):
        items = [i for i in re.split(r",|\be\b|\n", items) if i.strip()]
    data = _lists()
    key = _list_key(data, list_name)
    current = data.setdefault(key, [])
    added = [i.strip() for i in items if i.strip() and _norm(i) not in {_norm(x) for x in current}]
    current.extend(added)
    _save_lists(data)
    return f"Lista '{key}': adicionei {', '.join(added) or 'nada novo'}. Agora tem {len(current)} itens."


def list_show(list_name: str = "") -> str:
    data = _lists()
    if not list_name:
        return "\n".join(f"- {k} ({len(v)} itens)" for k, v in data.items()) or "Nenhuma lista ainda."
    key = _list_key(data, list_name)
    if key not in data:
        return f"Não existe a lista '{list_name}'. Listas: {', '.join(data) or 'nenhuma'}."
    return f"Lista '{key}':\n" + ("\n".join(f"- {i}" for i in data[key]) or "(vazia)")


def list_remove(list_name: str, items: list[str] | str) -> str:
    if isinstance(items, str):
        items = [items]
    data = _lists()
    key = _list_key(data, list_name)
    if key not in data:
        return f"Não existe a lista '{list_name}'."
    gone = {_norm(i) for i in items}
    before = len(data[key])
    data[key] = [x for x in data[key] if _norm(x) not in gone and not any(g and g in _norm(x) for g in gone)]
    removed = before - len(data[key])
    if not data[key]:  # lista que ficou vazia some (só existe lista que você criou e está usando)
        del data[key]
        _save_lists(data)
        return f"Tirei {removed} item(ns); a lista '{key}' ficou vazia e foi apagada."
    _save_lists(data)
    return f"Tirei {removed} item(ns) da lista '{key}'."


def list_clear(list_name: str) -> str:
    data = _lists()
    key = _list_key(data, list_name)
    if data.pop(key, None) is None:
        return f"Não existe a lista '{list_name}'."
    _save_lists(data)
    return f"Lista '{key}' apagada."


# ---------- Notas da ilha ----------

def notes_get() -> str:
    try:
        return NOTES.read_text(encoding="utf-8")
    except Exception:
        return ""


def notes_set(text: str, source: str = "ilha") -> None:
    NOTES.parent.mkdir(exist_ok=True)
    NOTES.write_text(text, encoding="utf-8")
    _publish("notes", text=text, source=source)


def note_read() -> str:
    text = notes_get().strip()
    return text[:4000] if text else "O bloco de notas da ilha está vazio."


def note_add(text: str) -> str:
    current = notes_get().rstrip()
    notes_set((current + "\n" if current else "") + text.strip(), source="ia")
    return "Anotado no bloco de notas da ilha."


# ---------- Cota do Claude ----------

_LIMIT = re.compile(r"(?:hit your|reached your|usage) (?:session |weekly |daily )?limit[^\"]*?resets? (?:at )?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.I)


def _last_limit() -> tuple[datetime, datetime] | None:
    """(quando bateu o limite, quando volta) da mensagem de limite mais recente do Claude Code."""
    since = time.time() - 8 * 3600
    best = None
    try:
        files = [f for f in CLAUDE_DIR.glob("*/*.jsonl") if f.stat().st_mtime >= since]
    except Exception:
        return None
    for f in files:
        try:
            with f.open("rb") as h:
                h.seek(max(0, f.stat().st_size - 400_000))
                tail = h.read().decode("utf-8", "ignore")
        except Exception:
            continue
        for line in tail.splitlines():
            if "limit" not in line or "reset" not in line:
                continue
            try:
                j = json.loads(line)
            except Exception:
                continue
            m = _LIMIT.search(json.dumps(j.get("message", {}).get("content", ""), ensure_ascii=False))
            if not m or not j.get("timestamp"):
                continue
            hit = datetime.fromisoformat(j["timestamp"].replace("Z", "+00:00")).astimezone(TZ)
            hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
            if ampm == "pm" and hour < 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0
            reset = hit.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
            if reset <= hit:
                reset += timedelta(days=1)
            if not best or hit > best[0]:
                best = (hit, reset)
    return best


def _tokens_today() -> int:
    today, total, seen = datetime.now(TZ).date(), 0, set()
    since = time.time() - 30 * 3600
    for f in CLAUDE_DIR.glob("*/*.jsonl"):
        try:
            if f.stat().st_mtime < since:
                continue
            for line in f.open(encoding="utf-8", errors="ignore"):
                if '"usage"' not in line:
                    continue
                j = json.loads(line)
                msg = j.get("message") or {}
                u, mid = msg.get("usage"), msg.get("id")
                if not u or mid in seen or not j.get("timestamp"):
                    continue
                if datetime.fromisoformat(j["timestamp"].replace("Z", "+00:00")).astimezone(TZ).date() != today:
                    continue
                seen.add(mid)
                total += sum(u.get(k, 0) or 0 for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        except Exception:
            continue
    return total


LIMITS = MEMORIA / "claude_limits.json"  # gravado pela status line do Claude Code (statusline.py)


PROBE_EVERY = 60  # igual ao Vorssaint: get_usage não gasta cota, então dá para ler a cada minuto


def _probe() -> None:
    """Lê a cota da conta pelo Claude Code (pedido de controle get_usage, o mesmo do Vorssaint).

    Não manda pergunta nenhuma ao modelo: não gasta cota. Dá o mesmo número do app do Claude."""
    import subprocess
    from .claude_agent import CLAUDE
    args = [CLAUDE, "--print", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--no-session-persistence", "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--setting-sources", "", "--settings", '{"disableAllHooks":true}']
    reqs = [("init", {"subtype": "initialize"}), ("usage", {"subtype": "get_usage", "skip_behaviors": True})]
    stdin = "".join(json.dumps({"type": "control_request", "request_id": i, "request": r}) + "\n" for i, r in reqs)
    try:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="ignore", cwd=str(Path.home()),
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        log.exception("Não consegui consultar a cota do Claude")
        return
    result = None
    try:
        proc.stdin.write(stdin)
        proc.stdin.flush()
        deadline = time.time() + 30
        for line in proc.stdout:
            if time.time() > deadline:
                break
            try:
                m = json.loads(line)
            except ValueError:
                continue
            r = m.get("response") or {}
            if m.get("type") == "control_response" and r.get("request_id") == "usage":
                result = r.get("response") if r.get("subtype") == "success" else None
                break
    except Exception:
        log.exception("Erro lendo a cota do Claude")
    finally:
        proc.kill()
    if not result or not result.get("rate_limits_available"):
        return
    limits = result.get("rate_limits") or {}
    data = {"updated": time.time(), "source": "get_usage"}
    for key in ("five_hour", "seven_day"):
        w = limits.get(key)
        if not w or w.get("utilization") is None:
            continue
        reset = w.get("resets_at")  # texto ISO; nulo = janela parada (ninguém usou ainda)
        if reset:
            reset = datetime.fromisoformat(reset.replace("Z", "+00:00")).timestamp()
        data[key] = {"used_pct": round(float(w["utilization"]), 1), "resets_at": reset}
    LIMITS.write_text(json.dumps(data), encoding="utf-8")
    _history_add(data)


HISTORY = MEMORIA / "claude_historico.jsonl"  # uma amostra a cada 10 min, para o gráfico da aba IA


def _history_add(data: dict) -> None:
    try:
        last = HISTORY.read_bytes()[-400:].decode("utf-8", "ignore").strip().splitlines()[-1]
        if data["updated"] - json.loads(last)["t"] < 600:
            return
    except Exception:
        pass
    row = {"t": int(data["updated"]), "fh": (data.get("five_hour") or {}).get("used_pct"),
           "sd": (data.get("seven_day") or {}).get("used_pct")}
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def quota_history(days: int = 7) -> list[dict]:
    since = time.time() - days * 86400
    try:
        rows = [json.loads(l) for l in HISTORY.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:
        return []
    return [r for r in rows if r["t"] >= since]


def live_limits(refresh: bool = False) -> dict | None:
    """Cota real do Claude (5 h e semana), lida da conta pelo Claude Code (get_usage) ou pela status line.

    refresh=True consulta de novo se o dado tiver mais de 1 min. None se não houver dado."""
    try:
        d = json.loads(LIMITS.read_text(encoding="utf-8"))
    except Exception:
        d = None
    if refresh and (not d or time.time() - (d.get("updated") or 0) > PROBE_EVERY):
        _probe()
        return live_limits()
    if not d:
        return None
    now = time.time()
    out = {"updated": d.get("updated")}
    for key in ("five_hour", "seven_day"):
        w = d.get(key) or {}
        reset = w.get("resets_at")
        if reset and reset <= now:  # a janela já virou: o que estava gravado não vale mais
            w = {"used_pct": 0.0, "resets_at": None, "rolled": True}
        out[key] = w or None
    five = out.get("five_hour") or {}
    if five.get("resets_at"):
        out["window_start"] = five["resets_at"] - 5 * 3600  # a janela de 5 h começa na primeira mensagem
    return out


def quota_status(refresh: bool = False) -> dict:
    live = live_limits(refresh)
    now = datetime.now(TZ)
    five = (live or {}).get("five_hour") or {}
    if five.get("resets_at") and (five.get("used_pct") or 0) >= 100:
        reset = datetime.fromtimestamp(five["resets_at"], TZ)
        # "hit" identifica o limite: o reset é estável (o horário de atualização mudaria a cada minuto e repetiria o aviso).
        return {"limited": True, "hit": reset.isoformat(), "reset": reset.isoformat(), "live": live}
    last = _last_limit()
    limited = bool(last and last[1] > now)
    from . import claude_watch
    return {"limited": limited, "hit": last[0].isoformat() if last else None,
            "reset": last[1].isoformat() if last else None, "live": live, "tasks": claude_watch.working()}


def _ago(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m // 60}h{m % 60:02d}" if m >= 60 else f"{m} min"


def claude_quota(remind: bool = False) -> str:
    """remind=True: cria um lembrete de verdade para a hora em que a janela de 5 h reinicia."""
    s = quota_status(refresh=True)
    live, now = s.get("live"), datetime.now(TZ)
    five = (live or {}).get("five_hour") or {}
    week = (live or {}).get("seven_day") or {}
    reset = datetime.fromisoformat(s["reset"]) if s["limited"] else (
        datetime.fromtimestamp(five["resets_at"], TZ) if five.get("resets_at") else None)
    lines = []
    if s["limited"]:
        lines.append(f"A cota do Claude está esgotada; volta às {reset:%H:%M} (daqui a {_ago((reset - now).total_seconds())}).")
    elif five.get("used_pct") is not None:
        txt = (f"A janela de 5 horas do Claude está em {five['used_pct']:.0f}% de uso" if five["used_pct"] >= 1
               else "A cota de 5 horas do Claude está praticamente cheia (quase nada usado)")
        if reset:
            txt += (f"; reinicia às {reset:%H:%M} (daqui a {_ago((reset - now).total_seconds())}),"
                    f" e começou há {_ago(now.timestamp() - live['window_start'])}")
        lines.append(txt + ".")
    else:
        lines.append("Ainda não sei quando a cota do Claude reinicia: esse horário aparece assim que o Claude Code"
                     " for usado de novo.")
    if week.get("used_pct") is not None:
        wr = f", reinicia {datetime.fromtimestamp(week['resets_at'], TZ):%d/%m às %H:%M}" if week.get("resets_at") else ""
        lines.append(f"Na semana: {week['used_pct']:.0f}% usado{wr}.")
    if live and live.get("updated"):
        lines.append(f"(Dado do Claude Code de {_ago(now.timestamp() - live['updated'])} atrás.)")
    if remind:
        if s["limited"]:
            lines.append("O aviso de quando volta já é automático (Telegram, PC e ilha); não precisa de lembrete.")
        elif reset and reset > now:
            from . import proactive
            proactive.add_reminder("A janela de 5 horas do Claude reiniciou: cota cheia de novo", when=reset.strftime("%Y-%m-%dT%H:%M"))
            lines.append(f"Marquei: te aviso às {reset:%H:%M}, quando a janela reiniciar.")
        else:
            lines.append("Por isso não marquei aviso; pergunte de novo depois de usar o Claude Code.")
    return " ".join(lines)


async def _quota_loop(notify) -> None:
    """Avisa quando o Claude Code bate o limite e de novo quando a cota volta (sempre, sem precisar pedir)."""
    while True:
        try:
            s = await asyncio.to_thread(quota_status, True)  # lê a conta a cada minuto: a ilha fica em tempo real
            st = _load(QUOTA_STATE, {})
            if s["reset"] and s["limited"] and st.get("hit") != s["hit"]:
                st = {"hit": s["hit"], "reset": s["reset"], "back": False}
                reset = datetime.fromisoformat(s["reset"])
                await notify(f"🪫 A cota do Claude acabou. Volta às {reset:%H:%M}; eu aviso.",
                             respostas.fala("cota_acabou", hora=f"{reset:%H:%M}"), kind="claude")
            elif st.get("reset") and not st.get("back") and datetime.fromisoformat(st["reset"]) <= datetime.now(TZ):
                st["back"] = True
                await notify("✅ A cota do Claude voltou! Pode usar de novo.", respostas.fala("cota_voltou"), kind="claude")
            _save(QUOTA_STATE, st)
            _publish("claude", **s)
        except Exception:
            log.exception("Erro vendo a cota do Claude")
        await asyncio.sleep(60)


async def run(notify) -> None:
    asyncio.create_task(_timer_loop(notify))
    asyncio.create_task(_quota_loop(notify))
    from . import claude_watch
    asyncio.create_task(claude_watch.run(notify))


TOOLS = {
    "timer_start": timer_start, "timer_list": timer_list, "timer_cancel": timer_cancel,
    "list_add": list_add, "list_show": list_show, "list_remove": list_remove, "list_clear": list_clear,
    "note_read": note_read, "note_add": note_add, "claude_quota": claude_quota,
}
_LIST = {"type": "string", "description": "Nome da lista, ex. 'compras do mês', 'filmes', 'tarefas'"}
_ITEMS = {"type": "array", "items": {"type": "string"}}
SCHEMAS = [
    fn("timer_start", "Inicia um timer/alarme/cronômetro regressivo (ex.: 'timer de 10 minutos', 'me avisa em 25 min pro pomodoro'). Toca no PC, no Telegram e na ilha.", {
        "minutes": {"type": "number"}, "label": {"type": "string", "description": "Nome curto, ex. 'Café', 'Pomodoro'"},
    }, ["minutes"]),
    fn("timer_list", "Lista os timers rodando e quanto falta.", {}),
    fn("timer_cancel", "Cancela um timer pelo nome (vazio = o último criado).", {"label": {"type": "string"}}),
    fn("list_add", "Adiciona itens numa lista (cria se não existir), ex. lista de compras.", {"list_name": _LIST, "items": _ITEMS}, ["list_name", "items"]),
    fn("list_show", "Mostra os itens de uma lista (vazio = todas as listas).", {"list_name": _LIST}),
    fn("list_remove", "Tira itens de uma lista (ex.: o que já foi comprado).", {"list_name": _LIST, "items": _ITEMS}, ["list_name", "items"]),
    fn("list_clear", "Apaga uma lista inteira.", {"list_name": _LIST}, ["list_name"]),
    fn("note_read", "Lê o bloco de notas da ilha do PC (o que o usuário anotou lá).", {}),
    fn("note_add", "Acrescenta um texto no bloco de notas da ilha do PC.", {"text": {"type": "string"}}, ["text"]),
    fn("claude_quota", "Cota real do Claude (Claude Code): % usado na janela de 5 h e na semana, quando reinicia e há quanto tempo começou. remind=true cria um aviso para a hora do reset (use quando ele pedir 'me avisa quando voltar').", {
        "remind": {"type": "boolean"},
    }),
]
