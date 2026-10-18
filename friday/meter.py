"""Medidor de nível de som por programa, num processo à parte.

Ler o medidor do Windows (COM, IAudioMeterInformation) dentro do bot derrubava o processo inteiro
(access violation ao carregar o whisper). Aqui fica isolado: no pior caso só este processo morre.

  python -m friday.meter stream <app>   -> imprime o pico ~15x/s, até ser morto
  python -m friday.meter once <app>     -> imprime o maior pico em ~0,2 s e sai
"""
import sys
import time

import comtypes
from pycaw.pycaw import IAudioMeterInformation

from .audio import _groups, _match


def _meters(app: str):
    g = _match(_groups(), app.split()[0] if app else "")
    return [s._ctl.QueryInterface(IAudioMeterInformation) for s in (g["sessions"] if g else [])]


def _peak(meters) -> float:
    p = 0.0
    for m in meters:
        try:
            p = max(p, m.GetPeakValue())
        except Exception:
            pass
    return p


def main() -> None:
    mode, app = sys.argv[1], " ".join(sys.argv[2:])
    comtypes.CoInitialize()
    meters = _meters(app)
    if mode == "once":
        p = 0.0
        for _ in range(4):
            p = max(p, _peak(meters))
            time.sleep(0.05)
        print(round(p, 4), flush=True)
        return
    refresh = time.monotonic() + 3
    while True:
        if time.monotonic() > refresh:  # sessões mudam (abas novas)
            meters, refresh = _meters(app), time.monotonic() + 3
        print(round(min(1.0, _peak(meters)), 3), flush=True)
        time.sleep(1 / 15)


if __name__ == "__main__":
    main()
