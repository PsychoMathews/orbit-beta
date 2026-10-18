"""Teste de voz do guia de instalação: python -m friday.voz_teste <voz da Microsoft> "<frase>"."""
import asyncio
import os
import sys

if len(sys.argv) > 1:
    os.environ["EDGE_VOICE"] = sys.argv[1]
    os.environ["VOICE_ENGINE"] = "local"  # testa só a voz da Microsoft escolhida

from . import desktop, voice  # noqa: E402

desktop._play(asyncio.run(voice.speak(sys.argv[2] if len(sys.argv) > 2 else "Oi! Esta é a minha voz.")))
