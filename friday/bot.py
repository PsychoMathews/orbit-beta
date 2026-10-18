import asyncio
import logging
import time
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from . import alexa, brain, claude_agent, config, desktop, gamemode, hub, memory, orbit, winsys, proactive, tools, voice
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


async def _respond(update, context, text, reply_with_voice, heard=None, heavy=False):
    chat_id = update.effective_chat.id
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


async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not _allowed(update):
        await query.answer("Acesso negado.")
        return
    await query.answer()
    decision, action_id = query.data.split(":", 1)
    summary = tools.pending.get(action_id, {}).get("summary", "")
    if decision == "no":
        tools.cancel_pending(action_id)
        await query.edit_message_text(f"{summary}\n\n❌ Cancelado.")
        return
    try:
        result = await asyncio.to_thread(tools.execute_pending, action_id)
    except Exception as e:
        log.exception("Erro ao executar ação")
        result = f"Falhou: {e}"
    await query.edit_message_text(f"{summary}\n\n✅ {result}")


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
    asyncio.get_running_loop().create_task(brain.warm_up())
    if True:  # antes só com Telegram; agora os avisos também vivem só na ilha e na voz do PC
        asyncio.get_running_loop().create_task(proactive.run(notify, ask_brain))
        await hub.run(notify)
        await winsys.run(notify)
        claude_agent.set_notifier(asyncio.get_running_loop(), notify)  # avisa quando o Claude terminar
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
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(_on_startup).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("pesado", heavy))
    app.add_handler(CallbackQueryHandler(handle_confirmation))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    log.info(assistente.NOME + " no ar (modelo %s, voz %s, ouvido %s)", config.OLLAMA_MODEL, config.VOICE_ENGINE, config.STT_ENGINE)
    app.run_polling()


if __name__ == "__main__":
    main()
