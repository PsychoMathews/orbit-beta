"""Área de transferência do Windows: a assistente copia um texto ou link para você colar no PC.

Serve para qualquer canal (Telegram, Alexa, voz): o texto vai para o Ctrl+V do PC e, com o Orbit aberto,
aparece também no histórico da aba Área de transferência.
"""
import ctypes
import time
from ctypes import wintypes

from .tools_common import fn

_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
_u32, _k32 = ctypes.windll.user32, ctypes.windll.kernel32
_k32.GlobalAlloc.restype = wintypes.HGLOBAL
_k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_k32.GlobalLock.restype = wintypes.LPVOID
_k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
_k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
_u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
_u32.SetClipboardData.restype = wintypes.HANDLE


def _set(text: str) -> None:
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    for _ in range(10):  # outro programa pode estar segurando a área de transferência por um instante
        if _u32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise OSError("A área de transferência está ocupada por outro programa.")
    try:
        _u32.EmptyClipboard()
        h = _k32.GlobalAlloc(_GMEM_MOVEABLE, size)
        ptr = _k32.GlobalLock(h)
        ctypes.memmove(ptr, data, size)
        _k32.GlobalUnlock(h)
        if not _u32.SetClipboardData(_CF_UNICODETEXT, h):
            raise OSError("O Windows não aceitou o texto.")
    finally:
        _u32.CloseClipboard()


def clipboard_copy(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return "Não recebi nada para copiar."
    if len(text) > 20000:
        return "Texto grande demais para a área de transferência (máx. 20 mil caracteres)."
    try:
        _set(text)
    except OSError as e:
        return str(e)
    preview = text if len(text) <= 80 else text[:77] + "..."
    return f"Copiado para a área de transferência do PC (Ctrl+V cola): {preview}"


def open_link(url: str) -> str:
    """Abre o link no Chrome do PC (ou no navegador padrão, se não houver Chrome)."""
    import os
    import re
    import subprocess
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        return "Só abro links que começam com http:// ou https://."
    chrome = next((p for p in (os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                               os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
                               os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"))
                   if os.path.exists(p)), None)
    if chrome:
        subprocess.Popen([chrome, url], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return f"Abri no Chrome do PC: {url}"
    os.startfile(url)
    return f"Abri no navegador do PC: {url}"


TOOLS = {"clipboard_copy": clipboard_copy, "open_link": open_link}
SCHEMAS = [
    fn("clipboard_copy", "Copia um texto ou link para a área de transferência do PC (o Ctrl+V do usuário) e para o histórico "
       "da aba Área de transferência da ilha. Use quando ele pedir para copiar, colar, mandar para o clipboard ou deixar "
       "um link pronto no PC. Copie exatamente o texto/link que ele mandou.", {
           "text": {"type": "string", "description": "O texto ou link exato a copiar"},
       }, ["text"]),
    fn("open_link", "Abre um link (http/https) no Chrome do PC. Use quando ele mandar um link (Instagram, YouTube, site...) "
       "e pedir para abrir no computador.", {"url": {"type": "string", "description": "O link exato"}}, ["url"]),
]
