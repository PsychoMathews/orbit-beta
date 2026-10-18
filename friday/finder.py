"""Barra de comandos dentro da assistente: achar arquivos pelo nome e fazer contas/conversões sem chutar.

O modelo local erra conta; aqui a conta é feita de verdade (expressão segura, sem eval de código).
"""
import ast
import math
import operator
import os
import re
import time
import unicodedata
from pathlib import Path

from .tools_common import fn

HOME = Path.home()
ROOTS = [HOME / "Desktop", HOME / "Documents", HOME / "Downloads", HOME / "Videos", HOME / "Pictures", HOME / "Music",
         HOME / "OneDrive"]
SKIP = {"node_modules", ".git", ".venv", "__pycache__", "AppData", "$recycle.bin", "cacheclip", ".cache"}


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


# Nomes falados de pasta -> pasta de verdade ("procura nos downloads" chega como folder="downloads").
ALIASES = {"downloads": "Downloads", "download": "Downloads", "baixados": "Downloads", "documentos": "Documents",
           "documents": "Documents", "desktop": "Desktop", "area de trabalho": "Desktop", "videos": "Videos",
           "imagens": "Pictures", "fotos": "Pictures", "pictures": "Pictures", "musicas": "Music", "musica": "Music",
           "onedrive": "OneDrive"}


def _folder(folder: str) -> list[Path]:
    key = _norm(folder).strip(" /\\")
    for pre in ("pasta ", "meus ", "minhas ", "de ", "da ", "do "):
        key = key.removeprefix(pre)
    if key in ALIASES:
        return [HOME / ALIASES[key]]
    p = Path(os.path.expandvars(os.path.expanduser(folder)))
    if p.is_absolute() and p.exists():
        return [p]
    near = [r / folder for r in [HOME, *ROOTS] if (r / folder).is_dir()]
    return near[:1] or [r for r in ROOTS if r.exists()]  # pasta desconhecida: procura em todas


def find_files(query: str, folder: str = "", kind: str = "") -> str:
    """Procura arquivos e pastas cujo nome tem todas as palavras da busca (sem acento, sem maiúscula)."""
    words = [w for w in _norm(query).split() if w]
    if not words:
        return "Diga parte do nome do arquivo."
    exts = {"video": (".mp4", ".mov", ".mkv", ".avi", ".mxf", ".braw"), "imagem": (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".psd", ".heic", ".rw2", ".cr2", ".arw"),
            "audio": (".mp3", ".wav", ".flac", ".m4a"), "documento": (".pdf", ".docx", ".doc", ".txt", ".xlsx", ".pptx", ".md"),
            "projeto": (".drp", ".prproj", ".aep", ".blend")}.get(_norm(kind))
    roots = _folder(folder) if folder else [r for r in ROOTS if r.exists()]
    deadline, hits = time.time() + 8, []
    for root in roots:
        for dirpath, dirs, files in os.walk(root, onerror=lambda e: None):
            dirs[:] = [d for d in dirs if d.lower() not in SKIP and not d.startswith(".")]
            for name in (files + dirs) if not exts else files:
                n = _norm(name)
                if all(w in n for w in words) and (not exts or n.endswith(exts)):
                    p = Path(dirpath) / name
                    stem, want = _norm(Path(name).stem), " ".join(words)
                    # nome igual ao pedido vem primeiro ("arquivo chamado 1" -> 1.webp antes de "Berlim 1.mp4")
                    rank = 0 if stem == want or n == want else 1 if stem.startswith(want) else 2
                    try:
                        hits.append((rank, -p.stat().st_mtime, p))
                    except OSError:
                        pass
            if time.time() > deadline or len(hits) > 2000:
                break
    if not hits:
        return f"Não achei nada com '{query}' em " + ", ".join(r.name for r in roots) + "."
    hits.sort(key=lambda h: (h[0], h[1]))
    if hits[0][0] == 0:  # achou o nome exato: ele e só mais uns poucos parecidos (lista grande confunde)
        hits = [h for h in hits if h[0] == 0] + [h for h in hits if h[0] != 0][:3]
    lines = [f"- {p} ({time.strftime('%d/%m/%Y', time.localtime(-t))})" + (" <- nome exato" if r == 0 else "") for r, t, p in hits[:10]]
    more = f"\n(+{len(hits) - 10} outros)" if len(hits) > 10 else ""
    return "Achei (nome exato primeiro, depois os mais recentes; para abrir use open_path com o caminho completo):\n" + "\n".join(lines) + more


# ---------- Contas ----------

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {"sqrt": math.sqrt, "raiz": math.sqrt, "log": math.log10, "ln": math.log, "sin": math.sin, "cos": math.cos,
          "tan": math.tan, "abs": abs, "round": round, "arredonda": round}
_CONST = {"pi": math.pi, "e": math.e}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        a, b = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(b) > 100:
            raise ValueError("expoente grande demais")
        return _OPS[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    if isinstance(node, ast.Name) and node.id in _CONST:
        return _CONST[node.id]
    raise ValueError("conta inválida")


# fator para a unidade base de cada grupo
_UNITS = {
    "comprimento": {"mm": 0.001, "cm": 0.01, "m": 1, "km": 1000, "pol": 0.0254, "in": 0.0254, "pe": 0.3048, "ft": 0.3048, "mi": 1609.344, "milha": 1609.344},
    "massa": {"mg": 1e-6, "g": 0.001, "kg": 1, "t": 1000, "lb": 0.45359237, "libra": 0.45359237, "oz": 0.028349523},
    "volume": {"ml": 0.001, "l": 1, "litro": 1, "gal": 3.785411784},
    "dados": {"b": 1, "kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3, "tb": 1024 ** 4},
    "tempo": {"ms": 0.001, "s": 1, "seg": 1, "min": 60, "h": 3600, "hora": 3600, "dia": 86400, "semana": 604800},
    "velocidade": {"km/h": 1 / 3.6, "m/s": 1, "mph": 0.44704},
}


def _convert(value: float, src: str, dst: str) -> str | None:
    def unit(u: str) -> str:  # "horas" -> "hora", "litros" -> "litro"; "ms", "m/s" e "kb/s" ficam
        u = u.lower()
        return u[:-1] if len(u) > 3 and u.endswith("s") and "/" not in u else u
    src, dst = unit(src), unit(dst)
    temps = {"c", "°c", "celsius", "f", "°f", "fahrenheit", "k", "kelvin"}
    if src in temps and dst in temps:
        c = value if src.endswith("c") or src == "celsius" else (value - 32) * 5 / 9 if "f" in src else value - 273.15
        out = c if dst.endswith("c") or dst == "celsius" else c * 9 / 5 + 32 if "f" in dst else c + 273.15
        return f"{value:g} {src} = {out:.2f} {dst}"
    for units in _UNITS.values():
        if src in units and dst in units:
            return f"{value:g} {src} = {value * units[src] / units[dst]:.6g} {dst}"
    return None


def calculate(expression: str) -> str:
    """Conta (2+2*3, 15% de 340, raiz(2)) ou conversão (10 km em mi, 30 c em f, 4 gb em mb)."""
    text = expression.strip().lower().replace("×", "*").replace("÷", "/").replace("^", "**")
    m = re.fullmatch(r"([\d.,]+)\s*([a-z°/]+)\s+(?:em|para|to|in|=)\s+([a-z°/]+)", text)
    if m:
        out = _convert(float(m.group(1).replace(",", ".")), m.group(2), m.group(3))
        if out:
            return out
    m = re.fullmatch(r"([\d.,]+)\s*%\s*(?:de|of)\s*([\d.,]+)", text)
    if m:
        a, b = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
        return f"{a:g}% de {b:g} = {a * b / 100:.6g}"
    text = re.sub(r"(\d),(\d)", r"\1.\2", text)  # vírgula decimal brasileira
    try:
        v = _eval(ast.parse(text, mode="eval"))
    except Exception:
        return f"Não entendi a conta '{expression}'."
    return f"{expression.strip()} = {v:.10g}"


TOOLS = {"find_files": find_files, "calculate": calculate}
SCHEMAS = [
    fn("find_files", "Procura arquivos ou pastas pelo nome no PC (Área de Trabalho, Documentos, Downloads, Vídeos, Imagens, Música, OneDrive). "
       "Use antes de open_path quando ele pede para abrir/achar um arquivo e não diz o caminho.", {
           "query": {"type": "string", "description": "Parte do nome (palavras soltas valem)"},
           "folder": {"type": "string", "description": "Opcional: só dentro desta pasta"},
           "kind": {"type": "string", "enum": ["video", "imagem", "audio", "documento", "projeto"], "description": "Opcional"},
       }, ["query"]),
    fn("calculate", "Faz contas e conversões de unidade com precisão (nunca calcule de cabeça): '2+2*3', '15% de 340', 'raiz(2)', "
       "'10 km em mi', '30 c em f', '4 gb em mb'.", {"expression": {"type": "string"}}, ["expression"]),
]
