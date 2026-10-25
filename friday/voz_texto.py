"""Preparo do texto e limpeza do áudio da voz própria (Qwen3-TTS). Roda só no processo da voz (friday/tts_worker.py).

- Títulos em inglês ganham aspas: com aspas o modelo pronuncia certo ("Shape of You"; sem aspas saía "Chop of You").
  Nome de banda depois de "do/da" fica sem aspas: com aspas piorava ("Mumford and Sons").
- Algumas palavras vão com outra grafia só para a voz (nome com "th" lido em inglês, por exemplo): lista em
  pronuncia.txt, na pasta da referência da voz (models/voz-propria), "palavra = grafia" por linha (fica só no PC).
- Respiros (trechos de ar entre as palavras) são abaixados depois de gerar.
"""
import re
from pathlib import Path

import numpy as np

# Grafia só para a fala (o texto mostrado na tela não muda). Preenchida por carregar_pronuncia().
PRONUNCIA: list[tuple[str, str]] = []


def carregar_pronuncia(arquivo: Path) -> None:
    """Lê "palavra = grafia" (uma por linha, # comenta) do pronuncia.txt ao lado da referência da voz."""
    PRONUNCIA.clear()
    if arquivo.exists():
        for line in arquivo.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                a, b = (s.strip() for s in line.split("=", 1))
                PRONUNCIA.append((rf"\b{re.escape(a)}\b", b))

# Palavras inglesas que no Brasil se falam do jeito português ("time" de futebol = "tchími").
_PT_FIXO = {"time"}
_TOKEN = re.compile(r"[A-Za-zÀ-ÿ]+(?:['’][A-Za-z]+)?|&|[^\sA-Za-zÀ-ÿ&]+|\s+")


def _z(w: str, lang: str) -> float:
    from wordfreq import zipf_frequency
    return zipf_frequency(w, lang)


def _ingles(w: str) -> bool:
    w = w.lower().replace("’", "'")
    if w in _PT_FIXO:
        return False
    en, pt = _z(w, "en"), _z(w, "pt")
    return (en >= 2.5 and pt < 1.5) or (en >= 3 and en - pt >= 0.8)


def _nome_ingles(w: str) -> bool:
    """Nome próprio que não é palavra comum em português (Sheeran, Mumford, Chrome)."""
    en, pt = _z(w.lower(), "en"), _z(w.lower(), "pt")
    return w[0].isupper() and (pt < 3.5 or en >= pt) and w.lower() not in _PT_FIXO


def trechos(text: str) -> list[tuple[str, str]]:
    """Divide o texto em [(idioma, trecho)]: nomes e termos em inglês viram 'en', o resto 'pt'."""
    toks = _TOKEN.findall(text)
    lang = ["pt"] * len(toks)
    words = [i for i, t in enumerate(toks) if t[0].isalpha() or t == "&"]
    i = 0
    while i < len(words):
        # sequência de palavras só separadas por espaço
        j = i
        while j + 1 < len(words) and all(toks[k].isspace() for k in range(words[j] + 1, words[j + 1])):
            j += 1
        run = words[i:j + 1]
        for k in run:
            if toks[k] == "&" or _ingles(toks[k]):
                lang[k] = "en"
        # dois ou mais nomes próprios estrangeiros seguidos (Ed Sheeran)
        for a in range(len(run) - 1):
            if _nome_ingles(toks[run[a]]) and _nome_ingles(toks[run[a + 1]]):
                lang[run[a]] = lang[run[a + 1]] = "en"
        # nome próprio colado a uma palavra inglesa vira inglês também (Mumford, Sons, Rhapsody)
        changed = True
        while changed:
            changed = False
            for a, k in enumerate(run):
                if lang[k] == "pt" and _nome_ingles(toks[k]) and (
                        (a > 0 and lang[run[a - 1]] == "en") or (a + 1 < len(run) and lang[run[a + 1]] == "en")):
                    lang[k] = "en"
                    changed = True
        i = j + 1
    out: list[list[str]] = []
    for k, t in enumerate(toks):
        lg = lang[k] if (t[0].isalpha() or t == "&") else (out[-1][0] if out else "pt")  # espaço e pontuação: trecho anterior
        if out and out[-1][0] == lg:
            out[-1][1] += t
        else:
            out.append([lg, t])
    return [(lg, s) for lg, s in out]


def preparar(text: str) -> str:
    """Texto como a voz deve ler: aspas nos títulos em inglês e grafias de pronúncia."""
    out = ""
    for lg, s in trechos(text):
        depois_de = re.search(r"\b(d[oae]s?|feat\.?|com)\s*$", out, re.I)
        if lg == "en" and (len(s.split()) >= 2 or s.strip()[0].isupper()) and "“" not in s and not depois_de:
            m = re.match(r"(\s*)(.*?\w)(\W*)$", s, re.S)
            out += f"{m[1]}“{m[2]}”{m[3]}"
        else:
            out += s
    for pat, rep in PRONUNCIA:
        out = re.sub(pat, rep, out)
    return out


def max_passos(text: str) -> int:
    """Trava de duração: o modelo às vezes não para de falar (uma vez gerou 147 s).
    ~15 letras por segundo, folga de 2x + 2 s, 12 passos por segundo de áudio."""
    return int(12 * (len(text) / 15 * 2 + 2))


# ---------- respiros ----------

def _tem_tom(x: np.ndarray, sr: int) -> bool:
    # cordas vocais vibrando: pico forte de autocorrelação entre 70 e 400 Hz
    x = x - x.mean()
    c = np.correlate(x, x, "full")[len(x) - 1:]
    if c[0] <= 0:
        return False
    lo, hi = int(sr / 400), min(int(sr / 70), len(c) - 1)
    return c[lo:hi].max() > 0.45 * c[0]


def respiros(a: np.ndarray, sr: int) -> list[tuple[int, int]]:
    """Trechos de 0,1 a 0,7 s sem tom, bem mais fracos que a fala e mais graves que "s"/"ch" (essas ficam acima de 4 kHz)."""
    n = int(sr * 0.02)
    fs = [a[i:i + n] for i in range(0, len(a) - n, n)]
    if not fs:
        return []
    db = np.array([10 * np.log10((f ** 2).mean() + 1e-12) for f in fs])
    pico = np.percentile(db, 95)
    freq = np.fft.rfftfreq(n, 1 / sr)
    janela = np.hanning(n)

    def centro(f):
        X = np.abs(np.fft.rfft(f * janela)) ** 2
        return (X * freq).sum() / (X.sum() + 1e-12)

    cand = [(not _tem_tom(f, sr)) and pico - 50 < d < pico - 20 and centro(f) < 3500 for f, d in zip(fs, db)]
    out, i = [], 0
    while i < len(cand):
        if not cand[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(cand) and cand[j + 1]:
            j += 1
        if 0.1 <= (j - i + 1) * n / sr <= 0.7:
            out.append((i * n, (j + 1) * n))
        i = j + 1
    return out


def tirar_respiros(a: np.ndarray, sr: int, ganho_db: float = -35) -> np.ndarray:
    """Abaixa os respiros em 35 dB, com rampa curta nas bordas para não estalar."""
    a = np.array(a, dtype=np.float32, copy=True)
    g, r = 10 ** (ganho_db / 20), int(0.01 * sr)
    for s, e in respiros(a, sr):
        env = np.full(e - s, g, np.float32)
        k = min(r, (e - s) // 2)
        env[:k] = np.linspace(1, g, k)
        env[-k:] = np.linspace(g, 1, k)
        a[s:e] *= env
    return a
