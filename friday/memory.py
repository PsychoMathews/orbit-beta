"""Memória permanente da Friday.

A verdade mora em arquivos .md que você pode abrir e editar (pasta memoria/).
O SQLite/FTS5 é só um índice de busca: se estragar, apague memoria/indice.sqlite que ele se reconstrói.
Regra do log: nunca apagar; erro se corrige com uma entrada nova.
"""
import json
import re
import sqlite3
import threading
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from .paths import MEMORIA
from . import assistente

TZ = ZoneInfo("America/Sao_Paulo")
ROOT = MEMORIA
SOBRE_MIM = ROOT / "SOBRE_MIM.md"
INBOX = ROOT / "INBOX.md"
LOG_DIR = ROOT / "log"
INDEX = ROOT / "indice.sqlite"
CONVERSA = ROOT / ".conversa.json"

KINDS = ("fato", "decisao", "preferencia", "tarefa", "ideia", "pessoa")
_lock = threading.Lock()

SOBRE_MIM_TEMPLATE = """# Sobre mim

> {nome} lê este arquivo em toda conversa. Edite à vontade: curto e direto funciona melhor.

## Quem sou
- Nome: {usuario}
- Trabalho:
- Cidade:

## Como quero ser tratado
- Respostas curtas e diretas. Sem bajulação.

## O que odeio em resposta de IA
-

## Aprendido por {nome}
"""


def setup() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not SOBRE_MIM.exists():
        SOBRE_MIM.write_text(SOBRE_MIM_TEMPLATE.format(nome=assistente.com_artigo(True), usuario=assistente.USUARIO), encoding="utf-8")
    if not INBOX.exists():
        INBOX.write_text("# Inbox\n\n> Ideias e coisas soltas para triar depois.\n\n", encoding="utf-8")
    rebuild_index()


def profile() -> str:
    return SOBRE_MIM.read_text(encoding="utf-8") if SOBRE_MIM.exists() else ""


def recent_log(n: int = 15) -> str:
    lines = []
    for f in sorted(LOG_DIR.glob("*.md"), reverse=True)[:2]:
        lines = [l for l in f.read_text(encoding="utf-8").splitlines() if l.startswith("- ")] + lines
    return "\n".join(lines[-n:])


# ---------- Escrever ----------

def remember(text: str, kind: str = "fato") -> str:
    kind = kind if kind in KINDS else "fato"
    text = " ".join(text.split())
    now = datetime.now(TZ)
    with _lock:
        if kind == "preferencia":
            _append(SOBRE_MIM, f"- {text} ({now:%d/%m/%Y})\n")
        elif kind == "ideia":
            _append(INBOX, f"- {now:%Y-%m-%d} {text}\n")
        log = LOG_DIR / f"{now:%Y-%m}.md"
        if not log.exists():
            log.write_text(f"# Log {now:%m/%Y}\n\n> Nunca apagar. Para corrigir, adicione uma entrada nova.\n\n", encoding="utf-8")
        _append(log, f"- {now:%Y-%m-%d %H:%M} [{kind}] {text}\n")
        _index_line(f"log/{log.name}", f"{now:%Y-%m-%d %H:%M}", f"[{kind}] {text}")
    return f"Registrado em memória ({kind})."


def _append(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


# ---------- Buscar ----------

def _norm(s: str) -> str:
    """Minúsculo e sem acento, para achar 'reuniao' quando foi escrito 'Reunião'."""
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(INDEX)
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS mem USING fts5(arquivo UNINDEXED, data UNINDEXED, texto UNINDEXED, busca)")
    return con


def _index_line(arquivo: str, data: str, texto: str, con: sqlite3.Connection | None = None) -> None:
    own = con is None
    con = con or _db()
    con.execute("INSERT INTO mem VALUES (?,?,?,?)", (arquivo, data, texto, _norm(texto)))
    if own:
        con.commit()
        con.close()


def rebuild_index() -> None:
    with _lock:
        INDEX.unlink(missing_ok=True)
        con = _db()
        for f in [SOBRE_MIM, INBOX, *sorted(LOG_DIR.glob("*.md"))]:
            if not f.exists():
                continue
            rel = f.relative_to(ROOT).as_posix()
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith(("#", ">")):
                    continue
                m = re.match(r"- (\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?) (.*)", line)
                data, texto = (m.group(1), m.group(2)) if m else ("", line.lstrip("- "))
                _index_line(rel, data, texto, con)
        con.commit()
        con.close()


def search(query: str, limit: int = 8) -> str:
    words = re.findall(r"\w+", _norm(query))
    if not words:
        return "Busca vazia."
    # OR entre palavras + prefixo, para tolerar plural e palavra incompleta; o BM25 ordena por relevância.
    fts = " OR ".join(f'"{w}"*' for w in words if len(w) > 2) or " OR ".join(f'"{w}"*' for w in words)
    with _lock:
        con = _db()
        rows = con.execute(
            "SELECT arquivo, data, texto FROM mem WHERE mem MATCH ? ORDER BY bm25(mem) LIMIT ?", (f"busca : ({fts})", limit)
        ).fetchall()
        con.close()
    if not rows:
        return "Nada encontrado na memória sobre isso."
    return "\n".join(f"- {data} {texto} ({arquivo})".replace("-  ", "- ") for arquivo, data, texto in rows)


# ---------- Conversa recente (sobrevive a reinícios) ----------

def load_conversation() -> dict[int, list]:
    try:
        return {int(k): v for k, v in json.loads(CONVERSA.read_text(encoding="utf-8")).items()}
    except Exception:
        return {}


def save_conversation(history: dict) -> None:
    data = {str(k): list(v) for k, v in history.items()}
    CONVERSA.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
