"""Transforma texto escrito em texto falável antes de virar áudio.

Ex.: "11 GB (70%)" -> "11 gigabytes, 70 por cento"; "C:\\Users\\ana\\Downloads" -> "a pasta Downloads".
"""
import re
import unicodedata

UNITS = {
    "TB": "terabytes", "GB": "gigabytes", "MB": "megabytes", "KB": "kilobytes",
    "GHz": "gigahertz", "MHz": "megahertz", "Mbps": "megabits por segundo", "MB/s": "megabytes por segundo",
    "ms": "milissegundos", "min": "minutos", "h": "horas", "s": "segundos",
}
WORDS = {
    "RAM": "memória RAM", "CPU": "processador", "GPU": "placa de vídeo", "PC": "computador", "SSD": "esse esse dê",
    "HD": "agá dê", "e-mail": "email", "etc.": "etcétera", "vs.": "contra", "Sr.": "senhor", "Sra.": "senhora",
}


def _unit(m: re.Match) -> str:
    number, unit = m.group(1), m.group(2)
    if unit == "GB" and "," not in number and "." not in number and number == "1":
        return "1 gigabyte"
    return f"{number} {UNITS[unit]}"


MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro"]


def _hour(h: str, m: str) -> str:
    h = int(h)
    word = "hora" if h == 1 else "horas"
    if m == "00":
        return "meio-dia" if h == 12 else ("meia-noite" if h == 0 else f"{h} {word}")
    return f"{h} e {int(m)}"


def _date(d: str, m: str) -> str:
    month = int(m)
    return f"{int(d)} de {MESES[month - 1]}" if 1 <= month <= 12 else f"{d}/{m}"


def for_speech(text: str) -> str:
    t = text
    # Emoji não se fala ("beber água 💧" virava "beber água, gota"): sai antes de tudo.
    t = "".join(ch for ch in t if unicodedata.category(ch) != "So" and ch not in "‍️︎"
                and not "\U0001f3fb" <= ch <= "\U0001f3ff")  # tons de pele
    # Markdown e símbolos que a voz lê errado
    t = re.sub(r"[*_`#>|]+", "", t)
    t = re.sub(r"https?://\S+", "o link", t)
    # Caminhos do Windows: fala só o último nome ("a pasta Downloads")
    t = re.sub(r"[A-Za-z]:\\(?:[^\s\\,;)]+\\)*([^\s\\,;)]+)", lambda m: f"{m.group(1)}", t)
    t = re.sub(r"(?i)(disco\s+)?\b([A-Z]):\\?(?=[\s,.;)]|$)", r"disco \2", t)
    # Dinheiro e milhar: "R$ 1.230,50" -> "1230,50 reais"
    t = re.sub(r"R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?)",
               lambda m: re.sub(r",00$", "", m.group(1).replace(".", "")) + " reais", t)
    t = re.sub(r"(?<![\w,])-(\d)", r"menos \1", t)  # "-0,69%" -> "menos 0,69 por cento"
    t = re.sub(r"\b(\d{1,3})\.(\d{3})\b(?![.,]\d)", r"\1\2", t)
    t = re.sub(r"(\w)\.(exe|msi|dll)\b", r"\1", t)  # "chrome.exe" -> "chrome"
    # Horários: "18:00" / "18h" -> "18 horas"; "18:30" / "18h30" -> "18 e 30"; "1h" -> "1 hora"
    t = re.sub(r"\b(\d{1,2})(?::|h)(\d{2})\b", lambda m: _hour(m.group(1), m.group(2)), t)
    t = re.sub(r"\b(\d{1,2})\s?h\b", lambda m: _hour(m.group(1), "00"), t)
    t = re.sub(r"\bàs meio-dia\b", "ao meio-dia", t)
    t = re.sub(r"\bàs meia-noite\b", "à meia-noite", t)
    t = re.sub(r"\bàs 1 hora\b", "à uma hora", t)
    t = re.sub(r"\bàs 1 e\b", "à uma e", t)
    # Datas: "18/10" -> "18 de outubro"
    t = re.sub(r"\b(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\b", lambda m: _date(m.group(1), m.group(2)), t)
    # Números com unidade: 1.5 GB / 11GB / 3200 MHz
    unit_alt = "|".join(sorted(map(re.escape, UNITS), key=len, reverse=True))
    t = re.sub(rf"(\d+(?:[.,]\d+)?)\s?({unit_alt})\b", _unit, t)
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s?%", r"\1 por cento", t)
    t = re.sub(r"(\d+)\s?°C", r"\1 graus", t)
    t = re.sub(r"(\d)\.(\d)", r"\1,\2", t)  # 1.5 -> 1,5 (como se fala no Brasil)
    t = t.replace("&", " e ").replace("+", " mais ").replace("/", " ou ")
    for k, v in WORDS.items():
        t = re.sub(rf"(?<!\w){re.escape(k)}(?!\w)", v, t)
    # Listas viram frases
    t = re.sub(r"^\s*[-•]\s*", "", t, flags=re.M)
    t = re.sub(r"\n+", ". ", t)
    t = re.sub(r"\(\s*([^)]*)\)", r", \1,", t)
    t = re.sub(r"\s+([,.])", r"\1", t)
    t = re.sub(r"([,.]){2,}", r"\1", t)
    return re.sub(r"\s{2,}", " ", t).strip()
