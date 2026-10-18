"""Peças comuns a todos os módulos de ferramentas (evita import circular)."""
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")


def fn(name, description, props, required=()):
    """Descreve uma ferramenta no formato que o Ollama entende."""
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": props, "required": list(required)},
    }}
