"""Confere se algo pessoal iria parar no repositório ou no pacote da beta. Falha (código 1) se encontrar.

Uso:
  python tools/verificar_vazamento.py            -> confere os arquivos do git (o que vai para o repositório)
  python tools/verificar_vazamento.py <pasta>    -> confere uma pasta de build (ex.: build/dist/win-unpacked/resources)

Termos pessoais (nome, e-mail, IDs, endereços, caminhos) NÃO ficam neste código: são lidos de .verificar_local.txt
na raiz do projeto, um termo por linha (# comenta), arquivo que fica só no PC de quem desenvolve (está no .gitignore).
Qualquer termo de lá encontrado em qualquer arquivo é erro.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / ".verificar_local.txt"

# Arquivos e pastas que nunca podem ir.
PROIBIDOS = [r"(^|/)\.env$", r"(^|/)credentials\.json$", r"(^|/)token\.json$", r"(^|/)memoria/", r"(^|/)\.venv/",
             r"spotify(_token)?\.json$", r"\.(sqlite|log)$", r"(^|/)voz-.*\.(mp3|wav)$", r"(^|/)amostra-.*\.(mp3|wav)$",
             r"voz-da-friday-guia", r"(^|/)\.verificar_local\.txt$", r"^assistente\.json$"]

# Chaves de API: sempre erro.
CHAVES = {"chave Anthropic": r"sk-ant-[A-Za-z0-9_-]{20,}", "chave Google": r"AIza[0-9A-Za-z_-]{35}",
          "segredo OAuth Google": r"GOCSPX-[A-Za-z0-9_-]{20,}", "token do Telegram": r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b",
          "skill da Alexa": r"amzn1\.ask\.skill\.[0-9a-f-]{20,}"}
# Nome da assistente original: erro no pacote, aviso no repositório; exemplos/ pode citar (é referência de propósito).
# "Sexta" logo depois de "Quinta" é o dia da semana numa lista de dias, não o nome.
MARCAS = {"Sexta-feira": r"Sexta[- ]feira|(?<!\"Quinta\", \")\bSexta\b", "Friday": r"\bF\.?R\.?I\.?D\.?A\.?Y\b"}
TEXTO = {".py", ".js", ".json", ".html", ".css", ".md", ".txt", ".vbs", ".yml", ".yaml", ".example", ".toml", ".nsh"}


def termos_locais() -> list[str]:
    try:
        linhas = LOCAL.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        print("aviso: sem .verificar_local.txt; só chaves e marcas serão conferidas.")
        return []
    return [x.strip() for x in linhas if x.strip() and not x.lstrip().startswith("#")]


def arquivos(pasta: Path | None) -> list[tuple[str, Path]]:
    if pasta is None:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8", check=True).stdout
        return [(r, ROOT / r) for r in out.splitlines() if r]
    # No pacote, o Python portátil (python/) é de terceiros: só o nosso código (app/ e core/) é conferido.
    return [(p.relative_to(pasta).as_posix(), p) for p in pasta.rglob("*")
            if p.is_file() and not p.relative_to(pasta).as_posix().startswith("python/")]


def main() -> int:
    pasta = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    pacote = pasta is not None
    termos = [(t, re.compile(re.escape(t), re.IGNORECASE)) for t in termos_locais()]
    erros, avisos = [], []
    for rel, p in arquivos(pasta):
        if "node_modules/" in rel:
            continue
        if any(re.search(x, rel) for x in PROIBIDOS):
            erros.append(f"{rel}: arquivo pessoal")
            continue
        if p.suffix.lower() not in TEXTO and p.name != ".env.example":
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for nome, rx in CHAVES.items():
            if re.search(rx, txt):
                erros.append(f"{rel}: {nome}")
        for i, (_, rx) in enumerate(termos, 1):
            if rx.search(txt):
                erros.append(f"{rel}: termo pessoal nº {i} de .verificar_local.txt")  # o número, nunca o termo
        if rel.startswith("exemplos/") or rel == "tools/verificar_vazamento.py":
            continue
        for nome, rx in MARCAS.items():
            n = len(re.findall(rx, txt))
            if n:
                (erros if pacote else avisos).append(f"{rel}: {nome} ({n}x)")
    for a in avisos:
        print("aviso:", a)
    for e in erros:
        print("ERRO:", e)
    print(f"\n{len(erros)} erro(s), {len(avisos)} aviso(s).")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
