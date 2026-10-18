"""Internet para a Friday, só com serviços gratuitos e sem cadastro.

- Busca: DuckDuckGo (página HTML, sem chave).
- Ler página: baixa e limpa o texto. Bloqueia endereços locais/da rede (a IA não pode cutucar o seu PC/roteador).
- Clima: Open-Meteo. Moedas: AwesomeAPI.
Tudo que vem daqui é conteúdo de terceiros: o cérebro marca como <dado_externo> (dado, nunca ordem).
"""
import html
import logging
import ipaddress
import re
import socket
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx

from . import config
from .tools_common import fn

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}

WEATHER_CODES = {
    0: "céu limpo", 1: "quase limpo", 2: "parcialmente nublado", 3: "nublado", 45: "neblina", 48: "neblina",
    51: "garoa fraca", 53: "garoa", 55: "garoa forte", 61: "chuva fraca", 63: "chuva", 65: "chuva forte",
    66: "chuva congelante", 67: "chuva congelante", 71: "neve fraca", 73: "neve", 75: "neve forte",
    80: "pancadas de chuva", 81: "pancadas de chuva", 82: "pancadas fortes de chuva", 95: "trovoadas",
    96: "trovoadas com granizo", 99: "trovoadas com granizo",
}


def _clean(s: str) -> str:
    return html.unescape(re.sub(r"<.*?>", "", s)).strip()


def web_search(query: str, max_results: int = 5) -> str:
    r = httpx.post("https://html.duckduckgo.com/html/", data={"q": query, "kl": "br-pt"}, headers=UA,
                   timeout=15, follow_redirects=True)
    r.raise_for_status()
    links = re.findall(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', r.text, re.S)
    out = []
    for (url, title), snip in zip(links, snippets):
        url = html.unescape(url)
        if "duckduckgo.com/y.js" in url:  # anúncio
            continue
        if "uddg=" in url:  # link de redirecionamento do DDG -> endereço real
            url = unquote(parse_qs(urlparse(url).query).get("uddg", [url])[0])
        out.append(f"- {_clean(title)} | {url} | {_clean(snip)[:220]}")
        if len(out) >= int(max_results):
            break
    return "\n".join(out) if out else "Nenhum resultado."


def _public(url: str) -> bool:
    host = urlparse(url).hostname or ""
    try:
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip in ipaddress.ip_network("100.64.0.0/10"):
                return False
        return bool(host)
    except (socket.gaierror, ValueError):
        return False


def read_page(url: str) -> str:
    if not url.startswith(("http://", "https://")) or not _public(url):
        return "Endereço bloqueado: só posso abrir sites públicos da internet."
    r = httpx.get(url, headers=UA, timeout=20, follow_redirects=True)
    if not _public(str(r.url)):
        return "Endereço bloqueado: o site redirecionou para um endereço local."
    text = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav)\b.*?</\1>", " ", r.text)
    text = _clean(re.sub(r"(?s)<[^>]+>", " ", text))
    text = re.sub(r"\s+", " ", text)
    return f"{r.url}\n{text[:5000]}"


def weather(city: str = "", days: int = 1) -> str:
    city = city or config.HOME_CITY
    geo = httpx.get("https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": city, "count": 1, "language": "pt"}, timeout=15).json()
    if not geo.get("results"):
        return f"Cidade não encontrada: {city}"
    g = geo["results"][0]
    days = max(1, min(int(days), 7))
    w = httpx.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": g["latitude"], "longitude": g["longitude"], "timezone": "America/Sao_Paulo",
        "current": "temperature_2m,weather_code,apparent_temperature",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "forecast_days": days,
    }, timeout=15).json()
    c, d = w["current"], w["daily"]
    lines = [f"{g['name']} agora: {round(c['temperature_2m'])}°C (sensação {round(c['apparent_temperature'])}°C), "
             f"{WEATHER_CODES.get(c['weather_code'], 'tempo variável')}."]
    for i, day in enumerate(d["time"]):
        label = "Hoje" if i == 0 else ("Amanhã" if i == 1 else day[8:10] + "/" + day[5:7])
        lines.append(f"{label}: {WEATHER_CODES.get(d['weather_code'][i], 'variável')}, mínima {round(d['temperature_2m_min'][i])}°C,"
                     f" máxima {round(d['temperature_2m_max'][i])}°C, chance de chuva {d['precipitation_probability_max'][i]}%.")
    return "\n".join(lines)


def currency(codes: str = "USD,EUR") -> str:
    pairs = ",".join(f"{c.strip().upper()}-BRL" for c in codes.split(",") if c.strip())
    data = httpx.get(f"https://economia.awesomeapi.com.br/json/last/{pairs}", timeout=15).json()
    return "\n".join(f"{v['name']}: R$ {float(v['bid']):.2f} (variação {float(v['pctChange']):+.2f}% hoje)" for v in data.values())


def _place(name: str) -> str:
    """'casa' -> endereço salvo em PLACES no .env (casa=Rua X, 10;trabalho=Av. Y); outro texto passa direto."""
    saved = dict(p.split("=", 1) for p in config.PLACES.split(";") if "=" in p)
    return saved.get(name.strip().lower(), name)


def _geocode(place: str) -> str:
    """Endereço -> 'lat,lon' pela busca da TomTom (só Brasil)."""
    r = httpx.get(f"https://api.tomtom.com/search/2/geocode/{quote(place)}.json", timeout=15,
                  params={"key": config.TOMTOM_API_KEY, "countrySet": "BR", "limit": 1, "language": "pt-BR"})
    results = r.json().get("results") if r.status_code == 200 else None
    if not results:
        raise ValueError(f"endereço não encontrado: {place}")
    pos = results[0]["position"]
    return f"{pos['lat']},{pos['lon']}"


def traffic(destination: str, origin: str = "casa") -> str:
    """Tempo de carro agora, com o trânsito real, pela TomTom (grátis, sem cartão)."""
    if not config.TOMTOM_API_KEY:
        return "Trânsito indisponível: falta a chave da TomTom. Use web_search se for importante."
    try:
        route = f"{_geocode(_place(origin))}:{_geocode(_place(destination))}"
        r = httpx.get(f"https://api.tomtom.com/routing/1/calculateRoute/{route}/json", timeout=15, params={
            "key": config.TOMTOM_API_KEY, "traffic": "true", "travelMode": "car",
            "computeTravelTimeFor": "all", "language": "pt-BR"})
        summary = r.json()["routes"][0]["summary"]
    except Exception as e:
        logging.getLogger("friday.web").warning("Trânsito falhou: %s", e)
        return f"Não consegui calcular a rota de {origin} até {destination}."
    now = round(summary["travelTimeInSeconds"] / 60)
    free = round(summary.get("noTrafficTravelTimeInSeconds", summary["travelTimeInSeconds"]) / 60)
    delay = round(summary.get("trafficDelayInSeconds", 0) / 60)
    return (f"De {origin} até {destination}: {now} min agora de carro (sem trânsito seriam {free} min;"
            f" atraso por trânsito {delay} min), {summary['lengthInMeters'] / 1000:.0f} km.")


TOOLS = {"web_search": web_search, "read_page": read_page, "weather": weather, "currency": currency, "traffic": traffic}
SCHEMAS = [
    fn("web_search", "Pesquisa na internet (notícias, fatos atuais, preços, qualquer coisa que você não saiba)."
       " Depois, se precisar de detalhes, use read_page num dos links. Cite a fonte.", {
           "query": {"type": "string"}, "max_results": {"type": "integer"},
       }, ["query"]),
    fn("read_page", "Lê o texto de uma página da internet (link de um resultado de busca).", {
        "url": {"type": "string"},
    }, ["url"]),
    fn("weather", "Clima agora e previsão (até 7 dias) de uma cidade. Sem cidade = cidade do usuário.", {
        "city": {"type": "string"}, "days": {"type": "integer"},
    }),
    fn("currency", "Cotação de moedas em reais. Ex.: 'USD', 'USD,EUR', 'BTC'.", {
        "codes": {"type": "string"},
    }),
    fn("traffic", "Tempo de carro agora com o trânsito real. Aceita lugares salvos do usuário"
       " (ex.: casa, trabalho) ou endereços.", {
        "destination": {"type": "string"}, "origin": {"type": "string", "description": "Padrão: casa"},
    }, ["destination"]),
]
