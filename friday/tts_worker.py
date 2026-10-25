"""Voz própria (Qwen3-TTS na placa de vídeo) num processo à parte, com Python próprio (.venv da voz, com PyTorch).

Fica separado pelo mesmo motivo do Whisper (friday/stt_worker.py): se algo nativo cair, só este processo morre.
E o PyTorch (~3 GB) não entra no .venv principal da Friday.

Protocolo: o bot manda uma linha JSON {"text": "..."}; o worker responde uma linha JSON {"sr": 24000, "n": bytes}
seguida de n bytes de amostras float32 mono (ou {"error": "..."}). Ao subir, imprime {"ready": true}.
Argumentos: <áudio de referência> <texto da referência> <modelo>.
"""
import json
import sys

import numpy as np


def main() -> None:
    ref_audio, ref_text_file, modelo = sys.argv[1:4]
    from faster_qwen3_tts import FasterQwen3TTS
    from pathlib import Path
    from .voz_texto import carregar_pronuncia, max_passos, preparar, tirar_respiros
    carregar_pronuncia(Path(ref_audio).parent / "pronuncia.txt")
    ref_text = open(ref_text_file, encoding="utf-8").read().strip()
    model = FasterQwen3TTS.from_pretrained(modelo)
    kw = dict(language="Portuguese", ref_audio=ref_audio, ref_text=ref_text)
    # Aquece pelo caminho inteiro (a lista de palavras do wordfreq carrega do disco na primeira consulta):
    # sem isso a primeira fala de verdade levava o dobro.
    aquece = preparar("Pronto! Já conferi a sua agenda: a reunião começa às três. Quer abrir o Google Chrome?")
    wavs, sr = model.generate_voice_clone(text=aquece, max_new_tokens=max_passos(aquece), **kw)
    tirar_respiros(np.asarray(wavs[0], np.float32).squeeze(), sr)
    out = sys.stdout.buffer
    out.write(b'{"ready": true}\n'); out.flush()
    for line in sys.stdin.buffer:
        try:
            text = preparar(json.loads(line)["text"])
            wavs, sr = model.generate_voice_clone(text=text, max_new_tokens=max_passos(text), **kw)
            data = tirar_respiros(np.asarray(wavs[0], np.float32).squeeze(), sr).tobytes()
            out.write(json.dumps({"sr": sr, "n": len(data)}).encode() + b"\n" + data)
        except Exception as e:
            out.write(json.dumps({"error": str(e)}).encode() + b"\n")
        out.flush()


if __name__ == "__main__":
    main()
