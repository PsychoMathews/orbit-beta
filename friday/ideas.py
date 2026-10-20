"""'Tive uma ideia': anota, lembra no horário pedido e já abre uma conversa no Claude Code sobre ela.

A conversa nasce numa pasta só de ideias (IDEAS_DIR no .env), cada ideia com seu arquivo .md. Se vier um link, o
conteúdo real dele (legenda e fala do vídeo) entra no arquivo antes de o Claude ler, para ele não imaginar nada.
idea_add completa a última ideia (link ou pedido que chegou numa segunda mensagem) e continua a mesma conversa.
"""
import os
import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from .tools_common import fn
from . import claude_agent, hub, links, proactive, vault

IDEAS_DIR = Path(os.getenv("IDEAS_DIR") or vault.VAULT / "Ideias")
_RULES = (" Use só o que está no arquivo; se faltar informação, diga o que falta em vez de inventar."
          " Atualize o arquivo com o resultado.")


def _link_section(link: str) -> str:
    try:
        info, speech = links.gather(link)
        return f"\n## Conteúdo do link\n\n{links.describe_content(link, info, speech)}\n"
    except Exception as e:
        claude_agent.log.warning("Link da ideia não abriu: %s", e)
        return f"\n## Link\n\n{link}\n(não consegui ler o conteúdo automaticamente: {str(e)[:150]})\n"


def _claude(prompt: str, resume: bool) -> None:
    cmd = [claude_agent.CLAUDE, "-p", prompt, "--model", claude_agent.MODEL, "--allowedTools", "Read,Edit,WebSearch,WebFetch",
           "--disallowedTools", "Bash,PowerShell"] + (["--continue"] if resume else [])
    try:
        r = subprocess.run(cmd, cwd=IDEAS_DIR, env=claude_agent.PLAN_ENV, capture_output=True, text=True, encoding="utf-8",
                           timeout=claude_agent.TIMEOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        done = (r.stdout or "").strip()
    except Exception as e:
        claude_agent.log.exception("Sessão da ideia falhou")
        done = f"falhou: {e}"
    links._notify(f"💡 Claude na ideia:\n\n{done[:1500]}")


def _work(path: Path, link: str, instructions: str, resume: bool) -> None:
    if link:
        with path.open("a", encoding="utf-8") as f:
            f.write(_link_section(link))
    if resume:
        prompt = f"Atualizei o arquivo da ideia {path.name}. Releia." + (f" Pedido: {instructions}." if instructions else "")
    else:
        prompt = (f"Esta conversa é sobre uma ideia que eu pedi para a minha assistente guardar, no arquivo {path.name}."
                  + (f" Pedido: {instructions}." if instructions else
                     " Faça uma primeira leitura curta: o que é, 3 perguntas para eu responder e um primeiro passo,"
                     " numa seção 'Primeira leitura do Claude'."))
    _claude(prompt + _RULES, resume)


def _latest() -> Path | None:
    files = sorted(IDEAS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def save_idea(idea: str, title: str = "", remind_at: str = "", link: str = "", instructions: str = "") -> str:
    idea = (idea or "").strip()
    if not idea and not link:
        return "Qual é a ideia?"
    title = (title or idea[:50] or "ideia").strip()
    IDEAS_DIR.mkdir(parents=True, exist_ok=True)
    path = IDEAS_DIR / f"{datetime.now():%Y-%m-%d} {re.sub(r'[^\w\s-]', '', title)[:60].strip()}.md"
    path.write_text(f"# {title}\n\n_{datetime.now():%d/%m/%Y %H:%M}_\n\n{idea}\n"
                    + (f"\nPedido: {instructions}\n" if instructions else ""), encoding="utf-8")
    hub.note_add(f"💡 {title}: {idea}" + (f" {link}" if link else ""))
    done = ["anotei no bloco de notas"]
    if remind_at:
        r = proactive.add_reminder(f"Ideia: {title}", when=remind_at)
        done.append(r.split(" (")[0] if r.startswith("Lembrete criado") else f"lembrete falhou ({r})")
    threading.Thread(target=_work, args=(path, link, instructions, False), daemon=True, name="ideia").start()
    done.append(f"passei pro Claude Code na pasta IDEIAS ({path.name}); ele avisa quando terminar")
    return "Ideia salva: " + "; ".join(done) + "."


def idea_add(text: str = "", link: str = "", instructions: str = "") -> str:
    path = _latest()
    if not path:
        return "Não tem ideia salva ainda; use save_idea."
    if text:
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n{text.strip()}\n")
    threading.Thread(target=_work, args=(path, link, instructions, True), daemon=True, name="ideia").start()
    return f"Acrescentei na ideia '{path.stem}' e o Claude está continuando a mesma conversa. Ele avisa quando terminar."


TOOLS = {"save_idea": save_idea, "idea_add": idea_add}
SCHEMAS = [
    fn("save_idea", "Guarda uma ideia NOVA: anota, cria lembrete (se ele pediu horário) e abre uma conversa no"
       " Claude Code sobre ela. Use quando ele disser 'tive uma ideia', 'salva no meu Claude' etc. Se ele mandou um"
       " link junto, passe em link (o conteúdo real é lido); o que ele pediu pro Claude fazer vai em instructions.", {
           "idea": {"type": "string", "description": "A ideia, com as palavras dele"},
           "title": {"type": "string", "description": "Título curto"},
           "remind_at": {"type": "string", "description": "Quando lembrar, ISO ex. 2026-10-19T10:00; vazio = sem lembrete"},
           "link": {"type": "string", "description": "Link que veio com a ideia"},
           "instructions": {"type": "string", "description": "O que pedir pro Claude, ex. 'transforma em pautas'"},
       }, ["idea"]),
    fn("idea_add", "Completa a ÚLTIMA ideia salva com um link, texto ou pedido que chegou depois (ex.: ele salvou a"
       " ideia e na mensagem seguinte mandou o link). Continua a mesma conversa do Claude.", {
           "text": {"type": "string"}, "link": {"type": "string"}, "instructions": {"type": "string"},
       }),
]
