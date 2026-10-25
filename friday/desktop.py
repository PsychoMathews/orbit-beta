"""Falar com a Friday pelo PC: atalho global (padrão Ctrl+Alt+F).

Aperta o atalho (registrado no Windows) -> bipe agudo -> fala. Para quando você fica 1,5 s em silêncio ou aperta o atalho de novo.
Bipe grave -> ela pensa e responde pelas caixas de som. A conversa também aparece no Telegram
(e é lá que chegam os botões de confirmação).
"""
import asyncio
import io
import logging
import subprocess
import re
import threading
import time
import wave
import winsound

import keyboard
import numpy as np
import sounddevice as sd

from . import brain, config, gamemode, orbit, phrases, voice
from . import assistente

log = logging.getLogger("friday.desktop")

RATE = 16000
MIN_RMS = 0.003
SILENCE_SECONDS = 1.5
MAX_SECONDS = 30

_busy = threading.Event()
_started = [0.0]  # quando a conversa atual começou
_stop = threading.Event()


def start(loop: asyncio.AbstractEventLoop, send_to_telegram) -> None:
    """send_to_telegram(text, pending_ids) é uma corrotina do bot."""

    def on_hotkey():
        if gamemode.is_on() and not _busy.is_set():
            log.info("Atalho ignorado: modo jogo ligado")
            return
        if orbit.muted() and not _busy.is_set():
            orbit.publish("notify", text=f"{assistente.NOME} no mudo", kind="mute")
            return
        if _busy.is_set():
            # Segunda apertada encerra a gravação, mas não no primeiro 1,2 s: segurar as teclas um pouco
            # faz o Windows repetir o atalho, e isso cortava a gravação antes de você falar.
            if time.time() - _started[0] > 1.2:
                _stop.set()
            return
        _busy.set()
        _started[0] = time.time()
        threading.Thread(target=_conversation, args=(loop, send_to_telegram), daemon=True).start()

    orbit._trigger = on_hotkey
    if config.WHISPER_DEVICE != "cuda":  # na placa ele carrega na hora do atalho (e sai depois de 10 min)
        threading.Thread(target=voice.preload_whisper, daemon=True, name="carrega-whisper").start()
    # Frases de espera prontas de antemão: gerar na hora atrasava a resposta.
    # Espera a voz própria carregar antes, senão as frases ficavam guardadas com a voz de reserva.
    threading.Thread(target=lambda: (voice.esperar_voz(), [_phrase(p, loop) for p in phrases.WORKING]),
                     daemon=True, name="frases").start()
    threading.Thread(target=_hotkey_thread, args=(config.HOTKEY, on_hotkey), daemon=True, name="atalho").start()


def _hotkey_thread(spec: str, callback) -> None:
    """Atalho registrado no próprio Windows (RegisterHotKey).

    A biblioteca keyboard escuta todas as teclas por um "gancho" que o Windows desliga sem avisar quando o
    processo demora a responder (PC pesado): o atalho morria. O registro do Windows não tem esse problema e,
    com MOD_NOREPEAT, segurar as teclas não dispara de novo.
    """
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    mods_map = {"ctrl": 0x2, "control": 0x2, "alt": 0x1, "shift": 0x4, "win": 0x8}
    mods, vk = 0x4000, None  # 0x4000 = MOD_NOREPEAT
    for part in spec.lower().replace(" ", "").split("+"):
        if part in mods_map:
            mods |= mods_map[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit():
            vk = 0x6F + int(part[1:])  # F1 = 0x70
        elif part == "space":
            vk = 0x20
    if vk is None or not user32.RegisterHotKey(None, 1, mods, vk):
        log.warning("Não consegui registrar %s no Windows (outro programa usa?); usando o modo antigo", spec)
        keyboard.add_hotkey(spec, callback, suppress=False)
        return
    log.info("Atalho %s ativo", spec)
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == 0x0312:  # WM_HOTKEY
            threading.Thread(target=callback, daemon=True).start()


# Oferta no fim da resposta também espera um "sim/não", mesmo sem "?" ("Se quiser, eu abro a imagem.").
_OFFER = re.compile(r"\b(se (voc[eê] )?quiser|quer que eu|posso\s+\w+|deseja|prefere|me (diz|fala|avisa) se|"
                    r"[eé] s[oó] (falar|pedir|confirmar)|confirma)\b", re.I)


def _expects_answer(reply: str) -> bool:
    text = reply.strip()
    if text.endswith("?"):
        return True
    last = re.split(r"(?<=[.!])\s+", text)[-1]  # só a última frase: oferta no meio não pede resposta
    return bool(_OFFER.search(last))


def _conversation(loop, send_to_telegram) -> None:
    try:
        follow = False
        for turn in range(3):  # 1ª fala + até 2 respostas quando ela fizer uma pergunta
            _stop.clear()
            orbit.state("listening")
            # Carrega o reconhecimento de voz enquanto você fala (na placa ele sai depois de 10 min parado).
            threading.Thread(target=voice.preload_whisper, daemon=True).start()
            winsound.Beep(880, 120)
            audio = _record()
            orbit.state("thinking")
            winsound.Beep(440, 120)
            if audio.size < RATE * 0.4:
                if not follow:  # na resposta a uma pergunta, silêncio só encerra
                    _didnt_hear("não detectei voz")
                return
            t0 = time.time()
            text = voice._whisper_stt(audio)
            t_stt = time.time() - t0
            log.info("Ouvi: %r", text)
            if not text:
                if not follow:
                    _didnt_hear("transcrição vazia")
                return
            if phrases.is_cancel(text):
                _play(_phrase(phrases.pick(phrases.BYE), loop))
                return
            chat_id = config.OWNER_ID
            future = asyncio.run_coroutine_threadsafe(brain.ask(chat_id, text, spoken=True, channel="pc"), loop)
            # Só diz "estou procurando" se ela realmente estiver demorando.
            answered = threading.Event()
            threading.Thread(target=_play_working, args=(loop, answered), daemon=True).start()
            orbit.publish("heard", text=text)
            reply, pending = future.result(timeout=600)
            answered.set()
            t_brain = time.time() - t0 - t_stt
            asyncio.run_coroutine_threadsafe(
                send_to_telegram(f'💻 (pelo PC) "{text}"\n\n{reply}', pending), loop
            )
            ogg = asyncio.run_coroutine_threadsafe(voice.speak(reply), loop).result(timeout=120)
            t_tts = time.time() - t0 - t_stt - t_brain
            log.info("Tempos: entender %.1fs, pensar %.1fs, gerar voz %.1fs (%s)", t_stt, t_brain, t_tts, voice.last_engine)
            orbit.publish("reply", text=reply)  # texto aparece junto com a voz, não antes
            _play(ogg)
            # Ela fez uma pergunta (e não há botão de confirmação esperando): já abre o microfone para a resposta.
            follow = _expects_answer(reply) and not pending
            if not follow:
                return
            log.info("Ela perguntou; ouvindo a resposta sem precisar do atalho")
    except Exception:
        log.exception("Erro na conversa pelo PC")
        orbit.publish("notify", text="Deu erro na conversa", kind="error")
        winsound.Beep(220, 400)
    finally:
        _busy.clear()
        orbit.state("idle")


def _mic_index() -> int | None:
    """Microfone escolhido no .env (MIC_DEVICE, parte do nome); vazio = padrão do Windows."""
    if not config.MIC_DEVICE:
        return None
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and config.MIC_DEVICE.lower() in d["name"].lower():
            return i
    log.warning("Microfone '%s' não encontrado; usando o padrão do Windows", config.MIC_DEVICE)
    return None


def _didnt_hear(reason: str) -> None:
    log.info("Nada para responder: %s", reason)
    for _ in range(2):  # dois bipes graves curtos = não ouvi
        winsound.Beep(330, 120)
        time.sleep(0.08)


def _open_mic() -> "sd.InputStream":
    """Abre o microfone. Se a lista de dispositivos mudou (Área de Trabalho Remota, fone desconectado), recarrega
    a lista e cai no microfone padrão do momento; sem microfone nenhum, avisa em vez de dar erro calado."""
    opts = dict(samplerate=RATE, channels=1, dtype="float32", blocksize=1600)
    try:
        return sd.InputStream(device=_mic_index(), **opts)
    except sd.PortAudioError:
        log.warning("Microfone configurado indisponível; recarregando a lista e usando o padrão")
        sd._terminate()
        sd._initialize()
        try:
            return sd.InputStream(device=None, **opts)
        except sd.PortAudioError as e:
            orbit.publish("notify", text="Sem microfone disponível. Na Área de Trabalho Remota, libere o microfone"
                                         " no Windows App.", kind="error")
            raise RuntimeError("sem microfone disponível") from e


def _record() -> np.ndarray:
    chunks, heard_voice, quiet_since, started = [], False, None, time.time()
    floor, peak = None, 0.0
    with _open_mic() as stream:
        while not _stop.is_set() and time.time() - started < MAX_SECONDS:
            block, _ = stream.read(1600)
            chunks.append(block[:, 0].copy())
            rms = float(np.sqrt(np.mean(block ** 2)))
            orbit.level(min(1.0, rms * 12))
            peak = max(peak, rms)
            # Microfones de headset captam baixo: o limite se ajusta ao ruído medido nos primeiros 0,3 s.
            if len(chunks) <= 3:
                floor = rms if floor is None else min(floor, rms)
                continue
            loud = rms > max(MIN_RMS, floor * 3)
            if loud:
                heard_voice, quiet_since = True, None
            elif heard_voice:
                quiet_since = quiet_since or time.time()
                if time.time() - quiet_since > SILENCE_SECONDS:
                    break
            elif time.time() - started > 6:  # ninguém falou
                break
    log.info("Gravação: %.1fs, ruído %.4f, pico %.4f, voz detectada=%s",
             time.time() - started, floor or 0, peak, heard_voice)
    return np.concatenate(chunks) if chunks and heard_voice else np.zeros(0, np.float32)


_phrase_audio: dict[str, bytes] = {}


WORKING_DELAY = 2.5  # o modelo novo responde em 1-2 s: só fala "estou procurando" se passar disso


def _phrase(text: str, loop) -> bytes:
    if text not in _phrase_audio:
        _phrase_audio[text] = asyncio.run_coroutine_threadsafe(voice.speak(text), loop).result(timeout=20)
    return _phrase_audio[text]


def _play_working(loop, answered: threading.Event) -> None:
    """Fala "estou procurando" só se a resposta passar de WORKING_DELAY (e nunca depois que ela chegou)."""
    try:
        if not answered.wait(WORKING_DELAY):
            _play(_phrase(phrases.pick(phrases.WORKING), loop))
    except Exception:
        log.exception("Não consegui tocar o 'estou procurando'")


_play_lock = threading.Lock()  # um áudio por vez: dois ao mesmo tempo se cortavam


def _play(ogg: bytes) -> None:
    """Toca pelo próprio Windows (PlaySound). Antes era por uma rotina em Python que travava o som
    por alguns segundos quando o bot estava ocupado com outra coisa."""
    pcm = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", "24000", "pipe:1"],
        input=ogg, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
    ).stdout
    # 0,3 s de silêncio antes: a placa de som (Realtek) "acorda" da economia de energia sem cortar o começo da fala.
    samples = np.concatenate([np.zeros(int(24000 * 0.3), np.int16), np.frombuffer(pcm, np.int16)])
    wav = io.BytesIO()
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(samples.tobytes())
    with _play_lock:
        previous = orbit._state["state"]
        orbit.state("speaking")
        done = threading.Event()
        threading.Thread(target=_wave_levels, args=(samples, done), daemon=True).start()
        try:
            winsound.PlaySound(wav.getvalue(), winsound.SND_MEMORY | winsound.SND_NODEFAULT)
        finally:
            done.set()
            orbit.state(previous if previous != "speaking" else "idle")


def _wave_levels(samples: np.ndarray, done: threading.Event) -> None:
    """Onda da ilha acompanhando a fala (só manda os níveis; o som é do Windows)."""
    step, started = 1200, time.time()
    for i in range(0, len(samples), step):
        if done.wait(max(0.0, started + i / 24000 - time.time())):
            return
        chunk = samples[i:i + step].astype(np.float32) / 32768
        orbit.level(min(1.0, float(np.sqrt(np.mean(chunk ** 2))) * 5))
