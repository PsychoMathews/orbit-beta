"""Voz da Friday: falar (TTS) e ouvir (STT).

Padrão: tudo local (Kokoro para falar, Whisper na GPU para ouvir), sem custo.
VOICE_ENGINE=propria: voz própria da Friday (Qwen3-TTS na placa, friday/tts_worker.py), com a Microsoft de reserva.
ElevenLabs continua disponível: VOICE_ENGINE=elevenlabs / STT_ENGINE=elevenlabs no .env.
"""
import asyncio
import json
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

last_engine = ""  # "propria", "elevenlabs", "edge" ou "local": qual voz gerou o último áudio
_eleven_paused_until = 0.0  # sem créditos: não insiste na ElevenLabs por um tempo


async def speak(text: str, model: str | None = None) -> bytes:
    """Texto -> áudio OGG/Opus (formato de mensagem de voz do Telegram).
    Ordem: voz própria ou ElevenLabs (conforme VOICE_ENGINE) -> voz neural da Microsoft -> Kokoro (local, sem internet)."""
    global last_engine, _eleven_paused_until
    text = speech.for_speech(text)
    vlog = logging.getLogger("friday.voice")
    if config.VOICE_ENGINE == "propria":
        try:
            # ~15 letras por segundo de fala, gerada ~2x mais rápido que o tempo real; folga para a primeira frase
            samples, rate = await asyncio.wait_for(asyncio.to_thread(_propria_tts, text), 10 + len(text) / 15)
            out = await _ffmpeg(samples.tobytes(), ["-f", "f32le", "-ar", str(rate), "-ac", "1", "-i", "pipe:0"])
            last_engine = "propria"
            return out
        except Exception as e:
            if isinstance(e, asyncio.TimeoutError):
                unload_propria()  # travou: derruba o processo (destrava a leitura) e sobe de novo na próxima
                e = "demorou demais"
            vlog.info("Voz própria indisponível (%s); usando a da Microsoft", e)
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


# ---------- Voz própria (Qwen3-TTS num processo à parte, com o Python da voz) ----------

PROPRIA_DIR = MODELS / "voz-propria"  # referencia.wav + referencia.txt: a voz que o modelo copia
PROPRIA_VRAM = 3200  # MB livres na placa para subir (ela usa ~2,7 GB)
_propria = None
_propria_pronta = threading.Event()
_propria_start = threading.Lock()
_propria_fala = threading.Lock()  # um pedido por vez no processo da voz
_propria_usada = 0.0
_propria_tentou = 0.0


def _propria_instalada() -> bool:
    return (config.VOICE_ENGINE == "propria" and Path(config.VOZ_PROPRIA_PYTHON).exists()
            and (PROPRIA_DIR / "referencia.wav").exists())


def preload_propria() -> None:
    """Sobe o processo da voz própria (leva ~20 s). Não sobe no modo jogo nem com a placa cheia."""
    global _propria, _propria_tentou
    if not _propria_instalada():
        return
    from . import gamemode
    if gamemode.is_on():
        return
    with _propria_start:
        if _propria is not None and _propria.poll() is None:
            return
        if time.time() - _propria_tentou < 60:  # placa cheia ou falhou agora há pouco: não insiste
            return
        _propria_tentou = time.time()
        livre = _vram_free_mb()
        if livre < PROPRIA_VRAM:
            # O cérebro local (Ollama) ocupa ~5 GB. Carregado antes, não deixa a voz subir; depois dela, os dois cabem
            # e rodam na mesma velocidade (medido em 25/10). Então ele sai, a voz sobe, e ele volta na próxima pergunta.
            _tirar_ollama()
            livre = _vram_free_mb()
        if livre < PROPRIA_VRAM:
            log.info("Voz própria não subiu: só %d MB livres na placa de vídeo", livre)
            return
        _propria_pronta.clear()
        _propria = p = subprocess.Popen(
            [config.VOZ_PROPRIA_PYTHON, "-m", "friday.tts_worker", str(PROPRIA_DIR / "referencia.wav"),
             str(PROPRIA_DIR / "referencia.txt"), config.VOZ_PROPRIA_MODELO],
            cwd=str(APP_DIR), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
    threading.Thread(target=_propria_carregando, args=(p,), daemon=True, name="voz-propria").start()


def _tirar_ollama() -> None:
    try:
        httpx.post(f"{config.OLLAMA_URL}/api/generate", json={"model": config.OLLAMA_MODEL, "keep_alive": 0}, timeout=20)
        time.sleep(2)  # a placa demora um instante para liberar
        log.info("Cérebro local saiu da placa para a voz própria subir primeiro")
    except Exception:
        log.warning("Não consegui tirar o cérebro local da placa", exc_info=True)


def _propria_carregando(p) -> None:
    global _propria_usada
    t = time.time()
    while b"ready" not in (line := p.stdout.readline()):
        if not line:
            log.warning("Voz própria saiu ao carregar")
            return
    _propria_usada = time.time()
    _propria_pronta.set()
    log.info("Voz própria pronta (%.0f s para carregar)", time.time() - t)
    if config.VOZ_PROPRIA_OCIOSA:
        while _propria is p and p.poll() is None:
            time.sleep(60)
            if time.time() - _propria_usada > config.VOZ_PROPRIA_OCIOSA * 60:
                unload_propria()
                log.info("Voz própria saiu da placa (%d min sem uso)", config.VOZ_PROPRIA_OCIOSA)


def esperar_voz(timeout: float = 90) -> None:
    """Espera a voz própria carregar (para não gravar frases prontas com a voz de reserva)."""
    preload_propria()
    if _propria is not None and _propria.poll() is None:
        _propria_pronta.wait(timeout)


def unload_propria() -> None:
    """Tira a voz própria da placa de vídeo (modo jogo, ou quando travou)."""
    global _propria
    with _propria_start:
        p, _propria = _propria, None
        _propria_pronta.clear()
    if p and p.poll() is None:
        p.kill()


def _propria_tts(text: str):
    global _propria_usada
    from . import gamemode
    p = _propria
    if gamemode.is_on():
        unload_propria()
        raise RuntimeError("modo jogo")
    if p is None or p.poll() is not None or not _propria_pronta.is_set():
        threading.Thread(target=preload_propria, daemon=True).start()
        raise RuntimeError("ainda carregando" if p is not None and p.poll() is None else "fora da placa")
    with _propria_fala:
        _propria_usada = time.time()
        p.stdin.write(json.dumps({"text": text}).encode() + b"\n")
        p.stdin.flush()
        line = p.stdout.readline()
        if not line:
            _propria_pronta.clear()
            raise RuntimeError("o processo da voz saiu")
        head = json.loads(line)
        if "error" in head:
            raise RuntimeError(head["error"])
        data = p.stdout.read(head["n"])
    return np.frombuffer(data, np.float32), head["sr"]


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
    preload_propria()  # a voz também (volta depois do modo jogo)


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
