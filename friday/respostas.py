"""Respostas prontas da assistente para as ferramentas do app (timer, alarme, lembrete, listas, notas, avisos).

Cada situação tem várias frases; phrases.pick sorteia como um baralho, então ela passa por todas antes de repetir.
Tom: elegante, contido, preciso. Frases curtas, porque quase sempre viram voz.
Campos entre chaves são preenchidos na hora: {dur} duração, {hora} horário, {oque} assunto, {quando} dia/hora,
{lista} nome da lista, {itens} itens, {n} quantidade.
Edite à vontade.
"""
from .phrases import pick

BANCO = {
    # ---------- Timer ----------
    "timer_ok": [
        "Cronômetro de {dur} correndo. Encerra às {hora}.",
        "Feito. {dur} no relógio, até as {hora}.",
        "Contagem iniciada: {dur}. Eu aviso às {hora}.",
        "Cronômetro de {dur} no ar. Termina às {hora}.",
        "Relógio armado. {dur}, fim às {hora}.",
        "Está contando. Às {hora} eu te chamo.",
        "Iniciado. Em {dur}, às {hora}, você ouve de mim.",
        "Combinado: {dur}. O aviso sai às {hora}.",
    ],
    "timer_ok_oque": [
        "{dur} para {oque}. Eu aviso às {hora}.",
        "Cronômetro rodando para {oque}: {dur}, até as {hora}.",
        "Feito. {Oque} em {dur}; te chamo às {hora}.",
        "Contagem para {oque} iniciada. Encerra às {hora}.",
        "{dur} reservados para {oque}. Às {hora}, aviso.",
        "Relógio ligado para {oque}. Termina às {hora}.",
    ],
    "timer_fim": [
        "Chefe, o tempo de {dur} terminou.",
        "Tempo esgotado, chefe.",
        "Cronômetro encerrado, chefe.",
        "Deu o tempo, chefe.",
        "Chefe, o relógio zerou.",
        "Fim da contagem de {dur}.",
    ],
    "timer_fim_oque": [
        "Chefe, hora de {oque}.",
        "Tempo cumprido: {oque}.",
        "O cronômetro zerou, chefe: {oque}.",
        "Deu a hora: {oque}.",
    ],
    "pomodoro_ok": [
        "Pomodoro iniciado: {dur} de foco. Pausa às {hora}.",
        "Foco ligado. {dur}, e às {hora} você respira.",
        "Bloco de concentração em andamento. Intervalo às {hora}.",
    ],
    "pomodoro_fim": [
        "Pomodoro concluído, chefe. Hora da pausa.",
        "Bloco de foco encerrado. Levante, estique as pernas.",
        "Fim do pomodoro. Cinco minutos de descanso, chefe.",
    ],
    # ---------- Alarme ----------
    "alarme_ok": [
        "Alarme para as {hora}. Considere-se acordado.",
        "Marcado: {hora} em ponto.",
        "Às {hora} eu toco. Pode contar com isso.",
        "Alarme armado para as {hora}.",
        "Feito. {hora} no despertador.",
        "Anotado no relógio: {hora}.",
        "Às {hora}, sem falta.",
    ],
    "alarme_ok_oque": [
        "Alarme das {hora} para {oque}.",
        "Às {hora} eu te chamo para {oque}.",
        "Marcado: {hora}, {oque}.",
        "Despertador das {hora} armado. Motivo: {oque}.",
    ],
    "alarme_fim": [
        "Chefe, são {hora}. Seu alarme.",
        "{hora}, chefe. Hora de levantar.",
        "Alarme das {hora}. Bom dia, ou boa tarde, conforme o caso.",
        "Chefe, deu {hora}.",
        "São {hora} em ponto, chefe.",
    ],
    # ---------- Lembrete ----------
    "lembrete_ok": [
        "Te lembro {quando} de {oque}.",
        "{Quando}, eu toco no assunto: {oque}.",
        "Registrado. {Quando}: {oque}.",
        "Fica comigo. {Quando} eu te lembro de {oque}.",
        "Deixa que eu me lembro por você: {oque}, {quando}.",
        "Anotado: {oque}, {quando}.",
        "Combinado. {Quando}, {oque}.",
        "Pode esquecer, que eu não esqueço: {oque}, {quando}.",
    ],
    "lembrete_ok_sem_assunto": [
        "Lembrete marcado, {quando}.",
        "{Quando}, eu te chamo.",
        "Marcado. {Quando} eu apareço.",
    ],
    "lembrete_fim": [
        "Chefe, lembrete: {oque}.",
        "Chefe, chegou a hora de {oque}.",
        "Como combinado: {oque}.",
        "Chefe, não esqueça: {oque}.",
        "Lembrando, como prometido: {oque}.",
        "Chefe, {oque}. Era agora.",
    ],
    "lembrete_fim_sem_assunto": [
        "Chefe, você pediu para eu te chamar agora.",
        "Chefe, deu a hora que você marcou.",
        "É agora, chefe. Foi o que você me pediu.",
    ],
    "lembretes_vazio": [
        "Nenhum lembrete pendente. Agenda mental limpa.",
        "Nada guardado para lembrar. Está tudo em dia.",
        "Zero lembretes na fila, chefe.",
        "Nenhuma pendência comigo.",
    ],
    "lembretes_lista": [
        "Na fila: {itens}.",
        "Seus lembretes: {itens}.",
        "Guardados comigo: {itens}.",
        "Pendentes comigo: {itens}.",
    ],
    # ---------- Notas e listas ----------
    "notas_vazio": [
        "O bloco de notas está em branco.",
        "Nada anotado no bloco por enquanto.",
        "Bloco de notas vazio, chefe.",
    ],
    "notas_ler": [
        "No bloco de notas: {texto}",
        "Você anotou: {texto}",
        "O bloco diz: {texto}",
    ],
    "listas_nomes": [
        "Suas listas: {itens}.",
        "Tenho estas listas: {itens}.",
        "Listas guardadas: {itens}.",
    ],
    "lista_vazia": [
        "A lista {lista} está vazia.",
        "Nada na lista {lista} por enquanto.",
        "{Lista}: nenhum item ainda.",
    ],
    "lista_itens": [
        "Na lista {lista}: {itens}.",
        "{Lista} tem {itens}.",
        "Para {lista}, você tem {itens}.",
        "{Lista}: {itens}.",
    ],
    # ---------- Avisos da cota do Claude ----------
    "cota_acabou": [
        "Chefe, a cota do Claude esgotou. Volta às {hora}; eu aviso.",
        "O Claude bateu o limite. Libera às {hora}, e eu te chamo.",
        "Cota do Claude no fim. Retorno previsto para as {hora}.",
    ],
    "cota_voltou": [
        "Chefe, a cota do Claude voltou. Pode usar.",
        "Claude liberado de novo, chefe.",
        "A janela do Claude reiniciou. Cota cheia.",
    ],
}


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def fala(chave: str, **campos) -> str:
    """Sorteia uma frase da situação e preenche os campos ({Campo} com inicial maiúscula também funciona)."""
    campos.update({_cap(k): _cap(str(v)) for k, v in list(campos.items())})
    return pick(BANCO[chave]).format(**campos)


# Rótulos genéricos que não devem virar "assunto" ("Chefe, lembrete: lembrete", "timer de teste: teste").
GENERICOS = {"", "timer", "lembrete", "alarme", "teste", "aviso", "pomodoro", "cronômetro", "cronometro"}


def assunto(texto: str) -> str:
    """'Beber Água' -> 'beber água'; rótulo genérico -> '' (a frase sem assunto entra no lugar)."""
    t = (texto or "").strip().rstrip(".!?")
    if t.lower() in GENERICOS or t.lower().startswith("alarme "):
        return ""
    return t[:1].lower() + t[1:] if not t[:2].isupper() else t  # mantém siglas ("DaVinci", "PC")


def lista_falada(itens: list[str]) -> str:
    itens = [i for i in itens if i]
    return ", ".join(itens[:-1]) + " e " + itens[-1] if len(itens) > 1 else (itens[0] if itens else "")
