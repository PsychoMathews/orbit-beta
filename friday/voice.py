"""Voz da Friday: falar (TTS) e ouvir (STT).

Padrão: tudo local (Kokoro para falar, Whisper na GPU para ouvir), sem custo.
ElevenLabs continua disponível: VOICE_ENGINE=elevenlabs / STT_ENGINE=elevenlabs no .env.
"""
import asyncio
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import httpx
import numpy as np

from . import config, speech
from .paths import APP_DIR, MODELS as PATHS_MODELS
from . import assistente

log = logging.getLogger("friday.voice")

API = "https://api.elevenlabs.io/v1"
MODELS = PATHS_MODELS

_lock = threading.Lock()
_kokoro = None
_whisper = None


def enabled() -> bool:
    return bool(config.ELEVENLABS_API_KEY) or (MODELS / "kokoro-v1.0.onnx").exists()


def can_listen() -> bool:
    return config.STT_ENGINE == "local" or bool(config.ELEVENLABS_API_KEY)


# ---------- Falar ----------

last_engine = ""  # "elevenlabs", "edge" ou "local": qual voz gerou o último áudio
_eleven_paused_until = 0.0  # sem créditos: não insiste na ElevenLabs por um tempo


async def speak(text: str, model: str | None = None) -> bytes:
    """Texto -> áudio OGG/Opus (formato de mensagem de voz do Telegram).
    Ordem: ElevenLabs (voz da Friday) -> voz neural da Microsoft -> Kokoro (local, sem internet)."""
    global last_engine, _eleven_paused_until
    text = speech.for_speech(text)
    vlog = logging.getLogger("friday.voice")
    if config.VOICE_ENGINE == "elevenlabs" and config.ELEVENLABS_API_KEY and time.time() >= _eleven_paused_until:
        try:
            out = await _ffmpeg(await _elevenlabs_tts(text, model), ["-i", "pipe:0"])
            last_engine = "elevenlabs"
            return out
        except Exception as e:
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (401, 402, 429):
                _eleven_paused_until = time.time() + 3600  # sem créditos/chave: tenta de novo em 1 h
                vlog.warning("ElevenLabs recusou (%s); usando a voz de reserva por 1 h", e.response.status_code)
            else:
                vlog.warning("ElevenLabs falhou (%s); usando a voz de reserva", e)
    try:
        out = await _ffmpeg(await _edge_tts(text), ["-i", "pipe:0"])
        last_engine = "edge"
        return out
    except Exception as e:
        if not (MODELS / "kokoro-v1.0.onnx").exists():
            raise
        vlog.warning("Voz da Microsoft falhou (%s); usando a voz local", e)
    last_engine = "local"
    samples, rate = await asyncio.to_thread(_kokoro_tts, text)
    raw = samples.astype(np.float32).tobytes()
    return await _ffmpeg(raw, ["-f", "f32le", "-ar", str(rate), "-ac", "1", "-i", "pipe:0"])


async def _edge_tts(text: str) -> bytes:
    import edge_tts
    chunks = []
    async for part in edge_tts.Communicate(text, config.EDGE_VOICE, rate=config.EDGE_RATE).stream():
        if part["type"] == "audio":
            chunks.append(part["data"])
    if not chunks:
        raise RuntimeError("voz da Microsoft não devolveu áudio")
    return b"".join(chunks)


def _kokoro_tts(text: str):
    global _kokoro
    with _lock:
        if _kokoro is None:
            from kokoro_onnx import Kokoro
            _kokoro = Kokoro(str(MODELS / "kokoro-v1.0.onnx"), str(MODELS / "voices-v1.0.bin"))
        return _kokoro.create(text, voice=config.KOKORO_VOICE, speed=config.KOKORO_SPEED, lang="pt-br")


async def _elevenlabs_tts(text: str, model: str | None = None) -> bytes:
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{API}/text-to-speech/{config.ELEVENLABS_VOICE_ID}",
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": config.ELEVENLABS_API_KEY},
            json={
                "text": text,
                "model_id": model or config.ELEVENLABS_MODEL,
                # Estabilidade mais alta = entonação consistente em textos longos (menos "travada").
                "voice_settings": {
                    "speed": config.ELEVENLABS_SPEED,
                    "stability": config.ELEVENLABS_STABILITY,
                    "similarity_boost": 0.8,
                    "style": 0.0,
                    "use_speaker_boost": True,
                },
            },
        )
        r.raise_for_status()
        return r.content


async def speak_mp3(text: str, model: str | None = None) -> bytes:
    """Texto -> MP3 no formato que a Alexa aceita em <audio> (48 kbps, 24 kHz)."""
    ogg = await speak(text, model)
    return await _ffmpeg(ogg, ["-i", "pipe:0"], ["-ac", "1", "-ar", "24000", "-codec:a", "libmp3lame", "-b:a", "48k", "-f", "mp3"])


# ---------- Ouvir ----------

async def transcribe(audio: bytes, filename: str = "voice.ogg") -> str:
    """Áudio -> texto."""
    if config.STT_ENGINE == "elevenlabs":
        return await _elevenlabs_stt(audio, filename)
    pcm = await _ffmpeg(audio, ["-i", "pipe:0"], ["-ac", "1", "-ar", "16000", "-f", "s16le"])
    samples = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
    return await asyncio.to_thread(_whisper_stt, samples)


_whisper_used = 0.0
_stt_lock = threading.Lock()
WHISPER_IDLE = 600  # na placa de vídeo: descarrega depois de 10 min sem uso


def preload_whisper() -> None:
    """Sobe o processo do reconhecimento de voz antes de precisar (o atalho chama isso enquanto você ainda fala).

    O Whisper roda em friday/stt_worker.py, num processo à parte: carregá-lo dentro do bot derrubava tudo.
    """
    global _whisper, _whisper_used
    with _lock:
        _whisper_used = time.time()
        if _whisper is None or _whisper.poll() is not None:
            import subprocess, sys
            from pathlib import Path
            exe = sys.executable.replace("pythonw.exe", "python.exe")
            _whisper = subprocess.Popen([exe, "-m", "friday.stt_worker"], cwd=str(APP_DIR),
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        creationflags=0x08000000)
            _whisper.ready = False
            if config.WHISPER_DEVICE == "cuda":
                threading.Thread(target=_unload_when_idle, daemon=True, name="whisper-ocioso").start()


def unload_whisper() -> None:
    """Tira o reconhecimento de voz da memória (libera a placa de vídeo)."""
    global _whisper
    with _lock:
        p, _whisper = _whisper, None
    if p and p.poll() is None:
        p.kill()


def _unload_when_idle() -> None:
    while True:
        time.sleep(60)
        if _whisper is None:
            return
        if time.time() - _whisper_used > WHISPER_IDLE:
            unload_whisper()
            logging.getLogger("friday.voice").info("Reconhecimento de voz saiu da placa (10 min sem uso)")
            return


class _Seg:
    def __init__(self, d):
        self.text, self.no_speech_prob, self.avg_logprob = d["text"], d["no_speech_prob"], d["avg_logprob"]


def _worker_transcribe(samples) -> list:
    import json, struct
    for attempt in (1, 2):  # se o processo morreu, sobe de novo uma vez
        preload_whisper()
        p = _whisper
        try:
            while not p.ready:
                line = p.stdout.readline()
                if not line:
                    raise RuntimeError("worker do whisper saiu ao carregar")
                p.ready = b"ready" in line
            data = np.asarray(samples, np.float32).tobytes()
            p.stdin.write(struct.pack("<I", len(data)) + data); p.stdin.flush()
            line = p.stdout.readline()
            if not line:
                raise RuntimeError("worker do whisper saiu ao transcrever")
            res = json.loads(line)
            if isinstance(res, dict):
                raise RuntimeError(res.get("error"))
            return [_Seg(d) for d in res]
        except Exception:
            log.exception("Reconhecimento de voz falhou (tentativa %d)", attempt)
            unload_whisper()
    return []


# Vocabulário que o Whisper erra sem dica (ouvia "Freddy", "se está feira", "Cloud").
_PROMPT = (", ".join([assistente.NOME, *assistente.APELIDOS, *([assistente.USUARIO] if assistente.USUARIO else [])])
           + ". Claude, DaVinci Resolve, Spotify, Telegram, Alexa, timer, alarme, "
           "lembrete, agenda, lista de compras, bloco de notas, trânsito, previsão do tempo.")
_FIXES = [
    *assistente.CORRECOES,  # erros no nome dela, escolhidos por quem usa
    (r"\bcl?[oó]ud\b", "Claude"),
    (r"\b(claudio|cl[oó]udio)(?= (resetar|voltar|liberar))", "Claude"),
    (r"\bda ?vinte\b", "DaVinci"),
]


def _whisper_stt(samples) -> str:
    global _whisper_used
    _whisper_used = time.time()
    with _stt_lock:  # um pedido por vez no processo do whisper
        segments = _worker_transcribe(samples)
    # Trecho que o próprio Whisper acha que é ruído ou chute: melhor "não ouvi" do que agir em cima disso.
    kept = [s for s in segments if not (s.no_speech_prob > 0.6 and s.avg_logprob < -0.8) and s.avg_logprob > -1.2]
    if len(kept) < len(segments):
        log.info("Whisper descartou %d trecho(s) incerto(s): %r", len(segments) - len(kept),
                 [s.text for s in segments if s not in kept])
    text = "".join(s.text for s in kept).strip()
    if text.strip(" .").lower() == _PROMPT.strip(" .").lower()[:len(text)]:  # alucinação: repetiu a dica
        return ""
    for pat, rep in _FIXES:
        text = re.sub(pat, rep, text, flags=re.I)
    return text



def _vram_free_mb() -> int:
    try:
        import subprocess
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5, creationflags=0x08000000)
        return int(out.stdout.split()[0])
    except Exception:
        return 99999  # sem como medir: segue o caminho normal

def _load_whisper():
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    if config.WHISPER_DEVICE != "cuda":  # padrão: processador, para não prender memória da placa de vídeo
        from faster_whisper import WhisperModel
        return WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
    if _vram_free_mb() < 1800:  # placa cheia (DaVinci/Ollama): carregar na GPU derrubava o bot inteiro (crash nativo)
        log.warning("Pouca memória de vídeo livre; whisper vai no processador desta vez")
        from faster_whisper import WhisperModel
        return WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
    try:
        # As DLLs da CUDA vêm dos pacotes pip nvidia-*; o Windows precisa saber onde estão.
        import nvidia.cublas
        import nvidia.cudnn
        for pkg in (nvidia.cublas, nvidia.cudnn):
            bin_dir = os.path.join(list(pkg.__path__)[0], "bin")
            os.add_dll_directory(bin_dir)
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]
        from faster_whisper import WhisperModel
        return WhisperModel(config.WHISPER_MODEL, device="cuda", compute_type="int8_float16")
    except Exception:
        from faster_whisper import WhisperModel
        return WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")


async def _elevenlabs_stt(audio: bytes, filename: str) -> str:
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{API}/speech-to-text",
            headers={"xi-api-key": config.ELEVENLABS_API_KEY},
            data={"model_id": "scribe_v1", "language_code": "por"},
            files={"file": (filename, audio)},
        )
        r.raise_for_status()
        return r.json().get("text", "").strip()


# ---------- ffmpeg ----------

async def _ffmpeg(data: bytes, input_args: list[str], output_args: list[str] | None = None) -> bytes:
    """Converte áudio. Sem output_args, gera OGG/Opus para o Telegram."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg não encontrado no PATH")
    output_args = output_args or ["-c:a", "libopus", "-b:a", "48k", "-f", "ogg"]
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-loglevel", "error", *input_args, *output_args, "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,  # sem janela piscando quando roda em segundo plano
    )
    out, err = await proc.communicate(data)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg falhou: " + err.decode(errors="ignore"))
    return out
