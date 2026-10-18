"""Frases curtas da Friday, sorteadas para ela não soar como script.

Edite à vontade: cada lista pode ter quantas frases quiser. Elas são geradas com a voz da Friday
quando ela liga (para tocar na hora), então frases novas só valem depois de reiniciar.
"""
import random
import re
from .assistente import personalizar

GREETING = [
    "{nome} aqui. Pode falar.",
    "Estou ouvindo.",
    "Pode mandar, chefe.",
    "Às ordens.",
    "Diga.",
    "Sim, chefe?",
    "Pronta. O que precisa?",
    "Aqui. Manda.",
]

WORKING = [
    "Estou procurando.",
    "Vou analisar.",
    "Buscando os dados.",
    "Conferindo.",
    "Um segundo.",
    "Deixa eu ver.",
    "Verificando.",
    "Só um instante.",
    "Já olho isso.",
    "Consultando.",
]

SLOW = [
    "Isso vai levar um pouco mais. Te mando a resposta no Telegram.",
    "Vou precisar de mais tempo. A resposta chega no Telegram.",
    "Essa é mais demorada. Te aviso pelo Telegram.",
]

BYE = [
    "Tudo bem.",
    "Beleza.",
    "Ok, deixa comigo se mudar de ideia.",
    "Certo.",
    "Sem problema.",
    "Combinado.",
]

ALL = [personalizar(x) for x in GREETING + WORKING + SLOW + BYE]

# "cancela", "não quero mais", "deixa pra lá"... -> encerra sem fingir que está trabalhando
CANCEL = re.compile(
    r"^\s*(cancela\w*|para|pare|chega|esquece|deixa (pra|para) l[aá]|deixa quieto|n[aã]o quero( mais)?|"
    r"nada|n[aã]o( precisa)?|tchau|valeu|obrigad[oa]|era s[oó] isso|s[oó] isso|tudo certo)\b",
    re.I,
)


def is_cancel(text: str) -> bool:
    """Só frases curtas de encerrar ("cancela", "deixa pra lá"); "cancela o lembrete X" é um pedido."""
    return bool(CANCEL.search(text)) and len(text.split()) <= 3

_decks: dict[int, list[str]] = {}
_last: dict[int, str] = {}


def pick(options: list[str]) -> str:
    """Como um baralho: passa por todas as frases em ordem aleatória antes de repetir alguma."""
    deck = _decks.get(id(options))
    if not deck:
        deck = options[:]
        random.shuffle(deck)
        if len(deck) > 1 and deck[-1] == _last.get(id(options)):
            deck[0], deck[-1] = deck[-1], deck[0]  # não emenda a mesma frase entre um baralho e outro
        _decks[id(options)] = deck
    choice = deck.pop()
    _last[id(options)] = choice
    return personalizar(choice)
