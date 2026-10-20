"""Entregar coisas do PC para o usuário no Telegram: arquivos e prints da tela.

O bot registra o envio (set_sender) ao subir; as ferramentas rodam numa thread e agendam o envio no loop do bot.
Só vai para o próprio usuário (OWNER_ID), nunca para terceiros: por isso não pede botão.
"""
import asyncio
import io
from pathlib import Path

from .tools_common import fn
from . import pc

TELEGRAM_LIMIT = 50 * 1024 * 1024  # bots só mandam arquivos de até 50 MB
_sender = None  # (loop, bot, chat_id)


def set_sender(loop, bot, chat_id) -> None:
    global _sender
    _sender = (loop, bot, chat_id)


def _send(coro_fn) -> None:
    loop, bot, chat_id = _sender
    asyncio.run_coroutine_threadsafe(coro_fn(bot, chat_id), loop).result(timeout=300)


def _resolve(path: str) -> Path:
    resolved = getattr(pc, "_resolve", None)
    return Path(resolved(path)) if resolved else Path(path).expanduser()


def send_file(path: str, caption: str = "") -> str:
    if not _sender:
        return "O Telegram não está ligado; não dá para mandar arquivo."
    p = _resolve(path)
    if not p.is_file():
        return f"Arquivo não encontrado: {p}. Use find_files ou list_folder para achar o caminho certo."
    size = p.stat().st_size
    if size > TELEGRAM_LIMIT:
        return (f"{p.name} tem {size / 1048576:.0f} MB e o Telegram só aceita até 50 MB por bot."
                " Ofereça mandar por e-mail (até 25 MB) ou abrir a pasta no PC.")
    video = p.suffix.lower() in (".mp4", ".mov", ".m4v")

    async def go(bot, chat_id):
        with p.open("rb") as f:
            if video:
                await bot.send_video(chat_id, f, caption=caption or p.name, supports_streaming=True, read_timeout=300, write_timeout=300)
            else:
                await bot.send_document(chat_id, f, caption=caption or p.name, read_timeout=300, write_timeout=300)
    _send(go)
    return f"Mandei {p.name} ({size / 1048576:.1f} MB) aqui no Telegram."


def screenshot(caption: str = "") -> str:
    if not _sender:
        return "O Telegram não está ligado; não dá para mandar print."
    from PIL import ImageGrab
    # Bloqueado ou com a sessão remota desconectada, o Windows não desenha a tela: o print sai preto ou falha.
    locked = ("O PC está bloqueado (ou a Área de Trabalho Remota foi desconectada), então não dá para tirar print."
              " Diga isso ao usuário; para destravar, ele entra pela Área de Trabalho Remota e sai pelo atalho"
              " 'Sair do remoto (desbloqueado)'. Arquivos continuam podendo ser enviados com send_file.")
    try:
        img = ImageGrab.grab(all_screens=True)
    except OSError:
        return locked
    if img.convert("L").getextrema()[1] < 8:  # imagem toda preta
        return locked
    img.thumbnail((2560, 2560))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)

    async def go(bot, chat_id):
        await bot.send_photo(chat_id, buf.getvalue(), caption=caption or "Print da tela")
    _send(go)
    return "Mandei o print da tela aqui no Telegram."


TOOLS = {"send_file": send_file, "screenshot": screenshot}
SCHEMAS = [
    fn("send_file", "Manda um arquivo do PC (vídeo, foto, documento) para o usuário aqui no Telegram. Até 50 MB."
       " Ache o caminho antes com find_files/list_folder. Faça direto, sem pedir confirmação.", {
           "path": {"type": "string", "description": "Caminho completo do arquivo"},
           "caption": {"type": "string"},
       }, ["path"]),
    fn("screenshot", "Tira um print da tela do PC e manda para o usuário no Telegram. Para mostrar uma pasta, abra"
       " antes com open_path e depois tire o print.", {
           "caption": {"type": "string"},
       }),
]
