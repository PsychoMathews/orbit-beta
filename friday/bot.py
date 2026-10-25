import asyncio
import logging
from datetime import datetime
import re
import time
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from . import agent, alexa, brain, claude_agent, config, delivery, vault, desktop, gamemode, hub, memory, mobile, orbit, winsys, proactive, tools, voice
from .paths import MEMORIA
from . import assistente
from .assistente import personalizar

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("friday")

# O vigia (friday.watchdog) olha este arquivo para saber se o bot está vivo.
HEARTBEAT = MEMORIA / ".heartbeat"


def _allowed(update: Update) -> bool:
    user = update.effective_user
    if user and user.id in config.ALLOWED_USER_IDS:
        return True
    log.warning("Acesso negado para user_id=%s", user.id if user else "?")
    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        await update.message.reply_text(f"Acesso negado. Seu ID do Telegram é {update.effective_user.id}")
        return
    await update.message.reply_text(
        personalizar(f"{assistente.NOME} online. Pode falar, chefe.") + "\n"
        "/pesado <pergunta> usa o modelo grande\n"
        "/reset limpa a conversa recente (a memória permanente fica)"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    brain.reset(update.effective_chat.id)
    await update.message.reply_text("Conversa recente apagada. A memória permanente continua em memoria/.")


async def heavy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Use: /pesado sua pergunta")
        return
    if not config.OLLAMA_MODEL_HEAVY:
        await update.message.reply_text("Nenhum modelo grande configurado (OLLAMA_MODEL_HEAVY no .env).")
        return
    await update.message.reply_text("Usando o modelo grande. Pode levar alguns minutos.")
    await _respond(update, context, text, reply_with_voice=False, heavy=True)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    await _respond(update, context, update.message.text, reply_with_voice=False)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    if not voice.can_listen():
        await update.message.reply_text("Ainda não tenho ouvidos: confira STT_ENGINE no .env.")
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    tg_file = await (update.message.voice or update.message.audio).get_file()
    audio = bytes(await tg_file.download_as_bytearray())
    try:
        text = await voice.transcribe(audio)
    except Exception as e:
        log.exception("Erro na transcrição")
        await update.message.reply_text(f"Não consegui transcrever o áudio: {e}")
        return
    if not text:
        await update.message.reply_text("Não consegui entender o áudio.")
        return
    await _respond(update, context, text, reply_with_voice=True, heard=text)


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Foto, print ou arquivo mandado no Telegram: salva no PC (Downloads\\Do celular) e, com legenda, atende o pedido."""
    if not _allowed(update):
        return
    msg = update.message
    if msg.photo:
        tg, name = msg.photo[-1], f"Foto {datetime.now():%Y-%m-%d %H%M%S}.jpg"  # a maior resolução que o Telegram guarda
    else:
        tg = msg.document or msg.video
        name = getattr(tg, "file_name", None) or f"Arquivo {datetime.now():%Y-%m-%d %H%M%S}"
    if getattr(tg, "file_size", 0) and tg.file_size > 20 * 1024 * 1024:
        await msg.reply_text("O Telegram só deixa bots baixarem arquivos de até 20 MB. Mande pelo app Orbit, na aba Arquivos.")
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_DOCUMENT)
    try:
        data = bytes(await (await tg.get_file()).download_as_bytearray())
        dest = mobile.save_upload(name, data)
    except Exception as e:
        log.exception("Arquivo do Telegram não salvou")
        await msg.reply_text(f"Não consegui salvar o arquivo no PC: {e}")
        return
    if msg.caption:
        await _respond(update, context, f"{msg.caption}\n\n(Arquivo que ele mandou agora, já salvo no PC em: {dest})", reply_with_voice=False)
    else:
        await msg.reply_text(f"Salvei no PC: Downloads\\Do celular\\{dest.name}")


async def _respond(update, context, text, reply_with_voice, heard=None, heavy=False):
    chat_id = update.effective_chat.id
    if await _voice_decision(update, text):
        return
    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
    try:
        reply, pending_ids = await brain.ask(chat_id, text, heavy=heavy, spoken=reply_with_voice)
    except Exception as e:
        log.exception("Erro no cérebro")
        await update.message.reply_text(f"Tive um problema pra pensar (o Ollama está rodando?): {e}")
        return

    caption = f'🎙️ (transcrição automática, pode ter erro) "{heard}"\n\n{reply}' if heard else reply
    if reply_with_voice and voice.enabled():
        try:
            await context.bot.send_chat_action(chat_id, ChatAction.RECORD_VOICE)
            audio = await voice.speak(reply)
            await update.message.reply_voice(audio, caption=caption[:1024])
            await _ask_confirmations(context.bot, chat_id, pending_ids)
            return
        except Exception:
            log.exception("Erro na voz; respondendo em texto")
    await update.message.reply_text(caption or "Feito.")
    await _ask_confirmations(context.bot, chat_id, pending_ids)


async def _ask_confirmations(bot, chat_id, pending_ids):
    for action_id in pending_ids:
        action = tools.pending.get(action_id)
        if not action:
            continue
        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirmar", callback_data=f"ok:{action_id}"),
            InlineKeyboardButton("❌ Cancelar", callback_data=f"no:{action_id}"),
        ]])
        await bot.send_message(chat_id, action["summary"], reply_markup=buttons)


async def _decide(chat_id: int, action_id: str, ok: bool) -> str:
    """Executa ou cancela uma ação pendente e conta o resultado ao cérebro (senão ela não fica sabendo)."""
    summary = tools.pending.get(action_id, {}).get("summary", "")
    if not ok:
        tools.cancel_pending(action_id)
        brain.record(chat_id, "[cancelei no botão]", f"Cancelado: {summary[:300]}")
        return f"{summary}\n\n❌ Cancelado."
    try:
        result = await asyncio.to_thread(tools.execute_pending, action_id)
    except Exception as e:
        log.exception("Erro ao executar ação")
        result = f"Falhou: {e}"
    brain.record(chat_id, "[confirmei no botão]", f"Executei: {summary[:300]}\nResultado: {str(result)[:1500]}")
    return f"{summary}\n\n✅ {result}"


async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not _allowed(update):
        return
    try:  # clique atrasado ("query is too old") não pode impedir a ação: só a animação do botão se perde
        await query.answer()
    except Exception:
        log.warning("Clique no botão chegou atrasado; executando assim mesmo")
    decision, action_id = query.data.split(":", 1)
    if action_id not in tools.pending:
        await query.message.reply_text("Essa ação expirou ou já foi tratada. Peça de novo.")
        return
    text = await _decide(update.effective_chat.id, action_id, decision == "ok")
    try:
        await query.edit_message_text(text[:4000])
    except Exception:
        await query.message.reply_text(text[:4000])


# Plano B para o botão: responder "confirma"/"pode"/"cancela" (texto ou áudio) decide a última ação pendente.
# Só a mensagem do próprio usuário dispara isto; o modelo nunca consegue se autoconfirmar.
_YES = re.compile(r"^\W*(sim|confirm[oa]?|confirmado|pode( ir| fazer| rodar| mandar)?|ok|beleza|manda( ver)?|"
                  r"executa|faz( isso)?|autorizo|vai)\W*$", re.I)
_NO = re.compile(r"^\W*(n[aã]o|cancela|cancelar|cancelado|deixa( pra l[aá])?|esquece|para)\W*$", re.I)


async def _voice_decision(update, text: str) -> bool:
    recent = [k for k, a in tools.pending.items() if time.time() - a.get("at", 0) < 600]  # só ação dos últimos 10 min
    if not recent or not (_YES.match(text) or _NO.match(text)):
        return False
    action_id = recent[-1]
    result = await _decide(update.effective_chat.id, action_id, bool(_YES.match(text)))
    await update.message.reply_text(result[:4000])
    return True


async def _on_startup(app) -> None:
    async def beat():
        while True:
            HEARTBEAT.write_text(str(time.time()))
            await asyncio.sleep(30)

    async def send_to_telegram(text, pending_ids):
        if not app:  # sem Telegram: a resposta já apareceu na ilha e as confirmações ficam nela
            return
        chat_id = config.OWNER_ID
        # O Telegram aceita até 4096 caracteres por mensagem: texto maior vai em partes.
        for i in range(0, len(text), 4000):
            await app.bot.send_message(chat_id, text[i:i + 4000])
        await _ask_confirmations(app.bot, chat_id, pending_ids)

    async def notify(text, speak_text, kind="proactive"):
        """Aviso proativo: ilha do PC, Telegram (texto + voz) e, se PC_SPEAK, caixas de som do PC. speak_text=None: só texto."""
        chat_id = config.OWNER_ID
        text = personalizar(text)  # frases prontas dizem "chefe": troca pelo tratamento escolhido (ou tira)
        speak_text = personalizar(speak_text) if speak_text else speak_text
        if not gamemode.allows(kind):
            gamemode.hold(text, kind)  # modo jogo: guarda para o resumo
            return
        orbit.publish("notify", text=text, kind=kind)  # primeiro a ilha: não depende da internet
        if app:
            try:
                await app.bot.send_message(chat_id, text)
            except Exception:
                log.exception("Aviso não chegou no Telegram")
        if not speak_text:
            return
        try:
            ogg = await voice.speak(speak_text)
            if app:
                await app.bot.send_voice(chat_id, ogg)
            if config.PC_SPEAK and not orbit.muted() and gamemode.speak_allowed():
                asyncio.get_running_loop().run_in_executor(None, desktop._play, ogg)
        except Exception:
            log.exception("Aviso sem voz")

    loop = asyncio.get_running_loop()

    def deliver_held(held):
        """Resumo do que chegou durante o modo jogo: Telegram + ilha. Chamado de qualquer thread."""
        text = gamemode.summary(held)
        orbit.publish("show", text=text, title="Modo jogo")
        if app:
            asyncio.run_coroutine_threadsafe(app.bot.send_message(config.OWNER_ID, text), loop)

    gamemode._deliver = deliver_held

    async def ask_brain(prompt, tools=True):
        # Conversa separada (id -1) para não misturar o resumo/triagem com o seu histórico.
        reply, _ = await brain.ask(-1, prompt, spoken=tools, use_tools=tools)
        brain.reset(-1)
        return reply

    asyncio.get_running_loop().create_task(beat())
    try:
        await orbit.start(send_to_telegram)
    except Exception:
        log.exception("Feed do Orbit não pôde ser iniciado")
    try:
        await mobile.start()  # Orbit no celular (app web + push)
    except Exception:
        log.exception("App do celular não pôde ser iniciado")
    asyncio.get_running_loop().create_task(brain.warm_up())
    if config.CLOUD_BACKEND == "plano":  # Claude já aberto esperando a primeira pergunta (economiza ~2,5 s cada)
        from . import plan
        from .google_auth import connected as _google_on
        plan.warm_up(_google_on())
    if True:  # antes só com Telegram; agora os avisos também vivem só na ilha e na voz do PC
        asyncio.get_running_loop().create_task(proactive.run(notify, ask_brain))
        await hub.run(notify)
        await winsys.run(notify)
        claude_agent.set_notifier(asyncio.get_running_loop(), notify)  # avisa quando o Claude terminar
        asyncio.get_running_loop().create_task(vault.run(notify))  # revisão da noite: aprende com o dia
        asyncio.get_running_loop().create_task(agent.run(notify))  # modo agente: acompanha o dia e chama quando vale
        if app:
            delivery.set_sender(asyncio.get_running_loop(), app.bot, config.OWNER_ID)  # arquivos e prints no Telegram
    if True:
        try:
            desktop.start(asyncio.get_running_loop(), send_to_telegram)
        except Exception:
            log.exception("Atalho do PC não pôde ser ativado")
        if config.ALEXA_SKILL_ID:  # Alexa fica de fora da beta: só liga com a skill configurada
            try:
                await alexa.start(send_to_telegram)
            except Exception:
                log.exception("Servidor da Alexa não pôde ser iniciado")


async def _run_local() -> None:
    """Sem Telegram: liga só a ilha, a voz do PC e os avisos, e fica rodando."""
    await _on_startup(None)
    await asyncio.Event().wait()


_instance_lock = None


def _single_instance() -> bool:
    """Trava um arquivo enquanto o bot roda: uma segunda cópia (ex.: vigia e reinício ao mesmo tempo) desiste."""
    import msvcrt
    global _instance_lock
    path = HEARTBEAT.parent / ".bot.lock"
    path.parent.mkdir(exist_ok=True)
    _instance_lock = open(path, "a+")
    try:
        msvcrt.locking(_instance_lock.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def main() -> None:
    if not _single_instance():
        log.warning("Outra cópia do bot já está rodando; esta vai fechar.")
        return
    memory.setup()
    if not config.TELEGRAM_BOT_TOKEN:
        log.info(assistente.NOME + " no ar sem Telegram (modelo %s, voz %s, ouvido %s)", config.OLLAMA_MODEL,
                 config.VOICE_ENGINE, config.STT_ENGINE)
        asyncio.run(_run_local())
        return
    if not config.ALLOWED_USER_IDS:
        log.warning("TELEGRAM_ALLOWED_USER_IDS vazio: mande /start pro bot pra descobrir seu ID.")
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).concurrent_updates(True).post_init(_on_startup).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("pesado", heavy))
    app.add_handler(CallbackQueryHandler(handle_confirmation))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL | filters.VIDEO, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    log.info(assistente.NOME + " no ar (modelo %s, voz %s, ouvido %s)", config.OLLAMA_MODEL, config.VOICE_ENGINE, config.STT_ENGINE)
    app.run_polling()


if __name__ == "__main__":
    main()
