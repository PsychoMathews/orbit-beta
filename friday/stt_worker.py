"""Reconhecimento de voz (Whisper) num processo à parte.

Carregar o faster-whisper dentro do bot passou a derrubar o processo inteiro (access violation nativo,
2026-10-18). Aqui, no pior caso, só este processo morre e o bot segue no ar.

Protocolo (stdin/stdout binários): o bot manda 4 bytes (tamanho, little-endian) + amostras float32 16 kHz;
o worker responde uma linha JSON com os trechos [{text, no_speech_prob, avg_logprob}].
Ao subir, imprime {"ready": true} quando o modelo está carregado.
"""
import json
import struct
import sys

import numpy as np


def main() -> None:
    from .voice import _PROMPT, _load_whisper
    model = _load_whisper()
    out = sys.stdout.buffer
    out.write(b'{"ready": true}\n'); out.flush()
    inp = sys.stdin.buffer
    while True:
        head = inp.read(4)
        if len(head) < 4:
            return
        (n,) = struct.unpack("<I", head)
        samples = np.frombuffer(inp.read(n), np.float32)
        try:
            segments, _ = model.transcribe(samples, language="pt", beam_size=5, vad_filter=True,
                                           initial_prompt=_PROMPT, condition_on_previous_text=False)
            res = [{"text": s.text, "no_speech_prob": s.no_speech_prob, "avg_logprob": s.avg_logprob} for s in segments]
        except Exception as e:
            res = {"error": str(e)}
        out.write(json.dumps(res).encode() + b"\n"); out.flush()


if __name__ == "__main__":
    main()
