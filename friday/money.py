"""Controle de gastos por voz. Tudo fica em memoria/gastos/AAAA-MM.csv (abre no Excel).

"Gastei 80 no mercado" -> uma linha no CSV do mês. "Quanto gastei esse mês?" -> resumo por categoria.
"""
import csv
import unicodedata
from datetime import datetime
from pathlib import Path

from .tools_common import TZ, fn
from .paths import MEMORIA

DIR = MEMORIA / "gastos"
HEADER = ["data", "valor", "categoria", "descricao"]
CATEGORIES = ["mercado", "alimentação", "transporte", "casa", "contas", "saúde", "lazer", "trabalho",
              "assinaturas", "compras", "educação", "outros"]


def _file(month: str) -> Path:
    return DIR / f"{month}.csv"


def _read(month: str) -> list[dict]:
    f = _file(month)
    if not f.exists():
        return []
    with f.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def _money(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def add_expense(amount: float, description: str, category: str = "outros", date: str = "") -> str:
    try:
        value = float(str(amount).replace("R$", "").replace(".", "").replace(",", ".")) if isinstance(amount, str) else float(amount)
    except ValueError:
        return f"Valor inválido: {amount}"
    if value <= 0:
        return "O valor precisa ser maior que zero."
    category = category if category in CATEGORIES else "outros"
    day = datetime.fromisoformat(date).date() if date else datetime.now(TZ).date()
    f = _file(f"{day:%Y-%m}")
    DIR.mkdir(parents=True, exist_ok=True)
    new = not f.exists()
    with f.open("a", encoding="utf-8-sig", newline="") as fh:  # utf-8-sig: o Excel abre com acento certo
        w = csv.writer(fh, delimiter=";")
        if new:
            w.writerow(HEADER)
        w.writerow([day.isoformat(), f"{value:.2f}".replace(".", ","), category, description])
    total = sum(float(r["valor"].replace(",", ".")) for r in _read(f"{day:%Y-%m}"))
    return f"Gasto registrado: {_money(value)} em {category} ({description}). Total do mês: {_money(total)}."


def expense_summary(month: str = "") -> str:
    month = month or datetime.now(TZ).strftime("%Y-%m")
    rows = _read(month)
    if not rows:
        return f"Nenhum gasto registrado em {month}."
    by_cat: dict[str, float] = {}
    for r in rows:
        by_cat[r["categoria"]] = by_cat.get(r["categoria"], 0) + float(r["valor"].replace(",", "."))
    total = sum(by_cat.values())
    parts = ", ".join(f"{c} {_money(v)}" for c, v in sorted(by_cat.items(), key=lambda x: -x[1]))
    biggest = max(rows, key=lambda r: float(r["valor"].replace(",", ".")))
    return (f"{month}: total {_money(total)} em {len(rows)} gastos. Por categoria: {parts}. "
            f"Maior gasto: {_money(float(biggest['valor'].replace(',', '.')))} ({biggest['descricao']}, {biggest['data']}).")


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def remove_last_expense(description: str = "") -> str:
    """Desfaz o último lançamento (ou o último com essa descrição) do mês atual."""
    month = datetime.now(TZ).strftime("%Y-%m")
    rows = _read(month)
    # Compara pelo começo das palavras: "almocei" acha "Almoço fora".
    stems = [w[:4] for w in _norm(description).split() if len(w) >= 4]
    idx = next((i for i in range(len(rows) - 1, -1, -1)
                if not stems or any(st in _norm(rows[i]["descricao"] + " " + rows[i]["categoria"]) for st in stems)), None)
    if idx is None:
        return "Não achei esse gasto."
    removed = rows.pop(idx)
    with _file(month).open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=HEADER, delimiter=";")
        w.writeheader()
        w.writerows(rows)
    return f"Removido: {removed['valor']} reais, {removed['descricao']} ({removed['data']})."


TOOLS = {"add_expense": add_expense, "expense_summary": expense_summary, "remove_last_expense": remove_last_expense}
SCHEMAS = [
    fn("add_expense", "Registra um gasto do usuário ('gastei 80 no mercado', 'paguei 120 de luz').", {
        "amount": {"type": "number", "description": "Valor em reais. Falado '45 e 50' = 45.50 (reais e centavos)"},
        "description": {"type": "string"},
        "category": {"type": "string", "enum": CATEGORIES},
        "date": {"type": "string", "description": "YYYY-MM-DD; vazio = hoje"},
    }, ["amount", "description", "category"]),
    fn("expense_summary", "Resumo dos gastos do mês (total, por categoria, maior gasto).", {
        "month": {"type": "string", "description": "YYYY-MM; vazio = mês atual"},
    }),
    fn("remove_last_expense", "Desfaz o último gasto registrado (ou o último com essa descrição).", {
        "description": {"type": "string"},
    }),
]
