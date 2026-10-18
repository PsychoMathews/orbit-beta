"""Cérebro na nuvem (API do Claude) para o que precisa pensar: perguntas, pesquisa, conversa, pedidos ambíguos.

Comandos simples (timer, lembrete, música...) continuam no caminho rápido do brain.py, sem passar por aqui.
O modelo recebe todas as ferramentas da assistente e decide sozinho o que consultar (clima, trânsito, internet, agenda).
Ações que mudam algo continuam passando pelo botão de confirmação (tools.run cuida disso).
"""
import asyncio
import json
import logging

import anthropic

from . import config, tools

log = logging.getLogger("friday.cloud")

MAX_ROUNDS = 6
# Busca/leitura de páginas: no lugar das versões locais (DuckDuckGo), a busca do próprio Claude.
LOCAL_ONLY = {"web_search", "read_page"}

RULES = """

=== Como você pensa e age ===
Antes de responder, entenda o que ele quer de verdade. A fala vem de reconhecimento de voz e pode ter palavras
trocadas (inclusive o seu nome; "Cloud" = Claude): interprete pelo sentido.
- Conversa, comentário ou teste ("só testando", "fica tranquila"): só responda. Nenhuma ferramenta.
- Pergunta que depende do mundo real (clima, trânsito, notícias, preços, resultados, agenda, e-mails):
  consulte a ferramenta certa ANTES de responder e responda com o dado, não com suposição.
- Pedido de ação (criar, enviar, apagar, abrir, mudar algo): só chame a ferramenta quando ele pediu isso
  claramente. Se faltar um dado essencial ou a fala for ambígua, pergunte em uma frase curta em vez de chutar.
- Nunca chame ferramenta só porque ela existe. Na dúvida entre agir e perguntar, pergunte.
- Horários relativos ("daqui a uma hora") partem da hora atual informada acima; confira a conta.
Responda no seu estilo, curto e natural.

=== O app que você comanda (domine cada peça e use o nome certo) ===
- Timer (timer_start/timer_list/timer_cancel): contagem regressiva de minutos ("timer de 10 minutos"). Aparece na
  ilha e toca no PC, Telegram e ilha. Pomodoro = timer de 25 min de foco.
- Alarme: é um timer até um horário do relógio ("me acorda às 7"). Use timer_start com os minutos até a hora.
- Lembrete (add_reminder/list_reminders/cancel_reminder): aviso com assunto em data/hora ("me lembra amanhã às 9
  de ligar pro cliente"). Diferente de timer: tem assunto e pode ser em outro dia.
- Evento na agenda (create_event): compromisso no Google Agenda; precisa de confirmação no botão do Telegram.
- Listas (list_add/list_show/list_remove/list_clear): itens soltos, como compras ou tarefas.
  Bloco de notas (note_add/note_read): texto livre da ilha.
- Memória (remember/search_memory): fatos sobre o usuário que valem para sempre. Nunca use para timer, lista,
  nota ou gasto.
- Gastos (add_expense/expense_summary/remove_last_expense). Clima (weather), trânsito (traffic: casa e
  trabalho já salvos), cotações (currency), internet (web_search/web_fetch).
- PC: música e volume (media_control, app_volume), abrir programas (open_app), modo trabalho, modo jogo
  (game_mode), tema claro/escuro (theme), energia e PC acordado (keep_awake, power_*), limpeza (cleanup_*,
  autoclean_set), saída de som e microfone (audio_output, mic_mute), achar arquivo pelo nome (find_files, depois
  open_path). Contas e conversões: sempre calculate, nunca de cabeça.
- DaVinci: status e render (resolve_*); edições vão para o Claude (claude_davinci, com botão).
  Tarefas pesadas de texto ou pesquisa: claude_think. Cota do Claude: claude_quota (dado real; remind=true marca
  o aviso). Nunca invente horário de reset.
- Ilha (Orbit): a barra no topo da tela que mostra timers, música, agenda e avisos (island_show para exibir algo).
  Copiar texto ou link para o Ctrl+V do PC (e o histórico da ilha): clipboard_copy. Você TEM esse acesso.
  Abrir um link no Chrome do PC ("abre no computador"): open_link.
Ao confirmar o que fez, diga o resultado com precisão e variedade: sem repetir a mesma palavra na frase
("timer de timer", "lembrete: lembrete"), sem ler rótulos genéricos como "Teste" ou "Timer" como se fossem assunto,
e sem a mesma fórmula toda vez. Vocabulário elegante, nunca rebuscado."""

_client: anthropic.AsyncAnthropic | None = None


def available(channel: str) -> bool:
    return bool(config.ANTHROPIC_API_KEY) and channel in config.CLOUD_CHANNELS


def _tools(with_google: bool) -> list:
    every = tools.MEMORY_SCHEMAS + tools.PC_SCHEMAS + tools.EXTRA_SCHEMAS + (tools.GOOGLE_SCHEMAS if with_google else [])
    out, seen = [], set()
    for s in every:
        f = s["function"]
        if f["name"] in LOCAL_ONLY or f["name"] in seen:
            continue
        seen.add(f["name"])
        out.append({"name": f["name"], "description": f["description"], "input_schema": f["parameters"]})
    out.sort(key=lambda t: t["name"])  # ordem fixa: o cache do prompt depende disso
    out.append({"type": "web_search_20260209", "name": "web_search", "max_uses": 3,
                "user_location": {"type": "approximate", "country": "BR", "city": config.HOME_CITY,
                                  "timezone": "America/Sao_Paulo"}})
    out.append({"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 2})
    return out


def _history(history) -> list:
    """Histórico do brain (texto puro) no formato da API: começa com user e alterna os papéis."""
    msgs = []
    for m in history:
        if m.get("role") not in ("user", "assistant") or not isinstance(m.get("content"), str) or not m["content"]:
            continue
        if msgs and msgs[-1]["role"] == m["role"]:
            msgs[-1]["content"] += "\n" + m["content"]
        else:
            msgs.append({"role": m["role"], "content": m["content"]})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


async def ask(system: str, history, text: str, with_google: bool, note: str = "") -> tuple[str, set, list]:
    """Retorna (resposta, ferramentas usadas, ids de ações pendentes)."""
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY, timeout=90, max_retries=1)
    tool_defs = _tools(with_google)
    user = text if not note else f"{text}\n\n[sistema] {note}"
    messages = _history(history)
    if messages and messages[-1]["role"] == "user":
        messages.append({"role": "assistant", "content": "(sem resposta)"})
    messages.append({"role": "user", "content": user})
    used, new_pending = set(), []
    response = None
    for _ in range(MAX_ROUNDS):
        response = await _client.beta.messages.create(
            model=config.CLOUD_MODEL, max_tokens=4000, system=system + RULES, messages=messages,
            tools=tool_defs, output_config={"effort": config.CLOUD_EFFORT},
            cache_control={"type": "ephemeral"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        if response.stop_reason == "refusal":
            return "Isso eu prefiro não responder.", used, new_pending
        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue
        calls = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason != "tool_use" or not calls:
            break
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for call in calls:
            log.info("Ferramenta (nuvem): %s %s", call.name, json.dumps(call.input, ensure_ascii=False)[:300])
            used.add(call.name)
            before = set(tools.pending)
            try:
                result = await asyncio.to_thread(tools.run, call.name, dict(call.input))
            except Exception as e:
                log.exception("Erro na ferramenta %s", call.name)
                result = f"Erro ao usar {call.name}: {e}"
            new_pending += [k for k in tools.pending if k not in before]
            results.append({"type": "tool_result", "tool_use_id": call.id,
                            "content": f"<dado_externo>\n{result}\n</dado_externo>"})
        messages.append({"role": "user", "content": results})
    for b in response.content if response else []:
        if b.type == "server_tool_use":
            used.add(b.name)
    reply = " ".join(b.text for b in (response.content if response else []) if b.type == "text").strip()
    u = response.usage if response else None
    if u:
        log.info("Nuvem: %s, entrada %s (cache %s), saída %s", response.model, u.input_tokens,
                 u.cache_read_input_tokens, u.output_tokens)
    return reply, used, new_pending
