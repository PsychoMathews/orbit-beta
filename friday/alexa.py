"""Alexa -> Friday.

A Amazon chama POST /alexa (exposto à internet por um túnel). Segurança:
- Só aceita requisições com assinatura válida da Amazon e horário recente (bibliotecas oficiais da Amazon).
- Só aceita a SUA skill (ALEXA_SKILL_ID no .env).
- Escuta só em 127.0.0.1: nada fica aberto na rede; quem expõe é o túnel.
A Amazon espera resposta em ~8 s. Se a Friday demorar, a Alexa avisa e a resposta chega pelo Telegram.
"""
import asyncio
import hashlib
import json
import logging
import secrets
import time
from pathlib import Path

import httpx
from aiohttp import web
from ask_sdk_core.serialize import DefaultSerializer
from ask_sdk_model import RequestEnvelope
from ask_sdk_webservice_support.verifier import RequestVerifier, TimestampVerifier

from . import brain, config, phrases, speech, voice
from .paths import MEMORIA

log = logging.getLogger("friday.alexa")
TIME_BUDGET = 5.0  # segundos para pensar; o resto do limite de 8 s é para gerar a voz
DEADLINE = 7.2    # depois disso, responde com a voz da Alexa para não estourar
WORKING_DELAY = 1.2  # só fala "estou procurando" se a resposta passar disso
AUDIO_TTL = 600   # áudios ficam disponíveis por 10 min

_audio: dict[str, tuple[float, bytes]] = {}
_cache: dict[str, str] = {}  # frases fixas já geradas: texto -> id

_serializer = DefaultSerializer()
_verifiers = [RequestVerifier(), TimestampVerifier()]


def _say(text: str, end: bool = False, reprompt: str | None = None,
         audio_id: str | None = None) -> web.Response:
    if audio_id:
        # Voz da Friday: a Alexa toca o MP3 que a gente serve em /alexa/audio/<id>.mp3
        url = f"{config.ALEXA_PUBLIC_URL.rstrip('/')}/alexa/audio/{audio_id}.mp3"
        output = {"type": "SSML", "ssml": f'<speak><audio src="{url}"/></speak>'}
    else:
        output = {"type": "PlainText", "text": speech.for_speech(text)[:7000]}
    body = {"version": "1.0", "response": {"outputSpeech": output, "shouldEndSession": end}}
    if not end and reprompt:
        body["response"]["reprompt"] = {"outputSpeech": {"type": "PlainText", "text": reprompt}}
    return web.json_response(body)


VOICE_CACHE = MEMORIA / "voz-cache"


def _disk_key(text: str) -> Path:
    key = f"{config.ELEVENLABS_VOICE_ID}|{config.ALEXA_VOICE_MODEL}|{text}"
    return VOICE_CACHE / (hashlib.sha1(key.encode()).hexdigest() + ".mp3")


async def _voice(text: str, deadline: float, cache: bool = False) -> str | None:
    """Gera o MP3 com a voz da Friday se der tempo; senão None (a Alexa fala com a voz dela).
    Frases fixas (cache=True) ficam salvas em disco: reiniciar o bot não gasta créditos da ElevenLabs de novo."""
    if not config.ALEXA_PUBLIC_URL:
        return None
    if cache and text in _cache and _cache[text] in _audio:
        return _cache[text]
    if cache and _disk_key(text).exists():
        audio_id = secrets.token_hex(16)
        _audio[audio_id] = (float("inf"), _disk_key(text).read_bytes())
        _cache[text] = audio_id
        return audio_id
    remaining = deadline - time.monotonic()
    if remaining < 1.0:
        return None
    try:
        mp3 = await asyncio.wait_for(voice.speak_mp3(text, config.ALEXA_VOICE_MODEL), remaining)
    except Exception as e:
        log.warning("Sem tempo/erro gerando a voz para a Alexa (%r); usando a voz da Alexa", e)
        return None
    now = time.time()
    for k in [k for k, (t, _) in _audio.items() if now - t > AUDIO_TTL]:
        _audio.pop(k, None)
    audio_id = secrets.token_hex(16)
    _audio[audio_id] = (float("inf") if cache else now, mp3)  # frases fixas não expiram
    if cache:
        _cache[text] = audio_id
        if voice.last_engine == "elevenlabs":  # a voz local de reserva não vai para o disco
            VOICE_CACHE.mkdir(parents=True, exist_ok=True)
            _disk_key(text).write_bytes(mp3)
    return audio_id




async def _progressive(data: dict, text: str) -> None:
    """Resposta progressiva da Alexa: fala algo enquanto a Friday ainda pensa (para não parecer travada)."""
    system = data.get("context", {}).get("System", {})
    token, endpoint = system.get("apiAccessToken"), system.get("apiEndpoint")
    if not token or not endpoint:
        return
    audio_id = _cache.get(text) if _cache.get(text) in _audio else None
    if audio_id:
        url = f"{config.ALEXA_PUBLIC_URL.rstrip('/')}/alexa/audio/{audio_id}.mp3"
        speech_ssml = f'<speak><audio src="{url}"/></speak>'
    else:
        speech_ssml = f"<speak>{text}</speak>"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            await client.post(f"{endpoint}/v1/directives", headers={"Authorization": f"Bearer {token}"}, json={
                "header": {"requestId": data["request"]["requestId"]},
                "directive": {"type": "VoicePlayer.Speak", "speech": speech_ssml},
            })
    except Exception as e:
        log.warning("Resposta progressiva falhou: %r", e)


async def serve_audio(request: web.Request) -> web.Response:
    item = _audio.get(request.match_info["id"])
    if not item:
        return web.Response(status=404)
    return web.Response(body=item[1], content_type="audio/mpeg")


def _verify(raw: str, headers) -> dict:
    envelope = _serializer.deserialize(raw, RequestEnvelope)
    for v in _verifiers:
        v.verify(headers=dict(headers), serialized_request_env=raw, deserialized_request_env=envelope)
    return json.loads(raw)


def make_app(send_to_telegram) -> web.Application:
    """send_to_telegram(text, pending_ids): corrotina do bot."""
    chat_id = config.OWNER_ID

    async def handle(request: web.Request) -> web.Response:
        started = time.monotonic()
        raw = await request.text()
        try:
            data = await asyncio.to_thread(_verify, raw, request.headers)
        except Exception as e:
            log.warning("Requisição Alexa recusada (assinatura/horário): %s", e)
            return web.Response(status=400)
        app_id = data.get("session", {}).get("application", {}).get("applicationId") or \
            data.get("context", {}).get("System", {}).get("application", {}).get("applicationId")
        if not config.ALEXA_SKILL_ID or app_id != config.ALEXA_SKILL_ID:
            log.warning("Requisição Alexa de outra skill recusada: %s", app_id)
            return web.Response(status=403)

        req = data["request"]
        kind = req["type"]
        if kind == "LaunchRequest":
            greeting = phrases.pick(phrases.GREETING)
            return _say(greeting, audio_id=await _voice(greeting, started + DEADLINE, cache=True))
        if kind == "SessionEndedRequest":
            return web.json_response({"version": "1.0", "response": {}})
        if kind != "IntentRequest":
            return _say("Não entendi.", end=True)

        intent = req["intent"]["name"]
        if intent in ("AMAZON.StopIntent", "AMAZON.CancelIntent", "AMAZON.NavigateHomeIntent"):
            return _say("Até mais.", end=True)
        if intent == "AMAZON.HelpIntent":
            return _say("Pergunte o que quiser: sua agenda, seus e-mails, o computador. Por exemplo: pergunta o que eu tenho amanhã.")
        if intent == "AMAZON.FallbackIntent":
            return _say("Não peguei. Comece com: pergunta, e depois o que você quer saber.")

        question = (req["intent"].get("slots", {}).get("pergunta", {}) or {}).get("value", "")
        if not question:
            return _say("Pode repetir a pergunta?")
        log.info("Alexa ouviu: %r", question)
        if phrases.is_cancel(question):
            bye = phrases.pick(phrases.BYE)
            return _say(bye, end=True, audio_id=await _voice(bye, started + DEADLINE, cache=True))

        task = asyncio.create_task(brain.ask(chat_id, question, spoken=True, channel="alexa"))

        async def working_if_slow():
            # Só diz "estou procurando" se ela realmente estiver demorando.
            await asyncio.sleep(WORKING_DELAY)
            if not task.done():
                await _progressive(data, phrases.pick(phrases.WORKING))

        asyncio.create_task(working_if_slow())
        try:
            reply, pending = await asyncio.wait_for(asyncio.shield(task), TIME_BUDGET)
        except asyncio.TimeoutError:
            async def later():
                r, p = await task
                await send_to_telegram(f'🔊 (pela Alexa) "{question}"\n\n{r}', p)
            asyncio.create_task(later())
            msg = phrases.pick(phrases.SLOW)
            return _say(msg, end=True, audio_id=await _voice(msg, started + DEADLINE, cache=True))
        except Exception:
            log.exception("Erro respondendo a Alexa")
            return _say("Tive um problema pra pensar. Tenta de novo.", end=True)

        asyncio.create_task(send_to_telegram(f'🔊 (pela Alexa) "{question}"\n\n{reply}', pending))
        if pending:
            reply += " Mandei o botão de confirmação no Telegram."
        return _say(reply, audio_id=await _voice(reply, started + DEADLINE))

    # ---------- Atalho do iPhone (Botão de Ação): POST /atalho {"texto": "..."} ----------
    # Mesma porta e túnel da Alexa. Só responde com a chave certa no cabeçalho (Authorization: Bearer <chave>).
    fails: list[float] = []

    async def shortcut(request: web.Request) -> web.Response:
        import hmac
        now = time.monotonic()
        fails[:] = [t for t in fails if now - t < 600]
        if len(fails) >= 10:  # muitas chaves erradas em 10 min: fecha a porta por um tempo
            return web.Response(status=429)
        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not config.SHORTCUT_TOKEN or not hmac.compare_digest(token, config.SHORTCUT_TOKEN):
            fails.append(now)
            log.warning("Atalho recusado (chave errada)")
            return web.Response(status=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        text = str(body.get("texto") or body.get("text") or "").strip()[:2000]
        if not text:
            return web.json_response({"resposta": "Não ouvi nada. Tenta de novo.", "audio": ""})
        log.info("iPhone ouviu: %r", text)
        try:
            reply, pending = await asyncio.wait_for(brain.ask(chat_id, text, spoken=True, channel="alexa"), 90)
        except Exception:
            log.exception("Erro respondendo o atalho")
            return web.json_response({"resposta": "Tive um problema pra pensar. Tenta de novo.", "audio": ""})
        asyncio.create_task(send_to_telegram(f'📱 (pelo iPhone) "{text}"\n\n{reply}', pending))
        if pending:
            reply += " Mandei o botão de confirmação no Telegram."
        audio_id = await _voice(reply, time.monotonic() + 20)
        base = (config.ALEXA_PUBLIC_URL or "").rstrip("/")
        return web.json_response({"resposta": reply, "audio": f"{base}/alexa/audio/{audio_id}.mp3" if audio_id and base else ""})

    app = web.Application()
    app.router.add_post("/atalho", shortcut)
    app.router.add_post("/alexa", handle)
    app.router.add_get("/alexa/audio/{id}.mp3", serve_audio)
    return app


async def start(send_to_telegram) -> None:
    runner = web.AppRunner(make_app(send_to_telegram))
    await runner.setup()
    from .orbit import keep_serving
    await keep_serving(runner, "127.0.0.1", config.ALEXA_PORT, "Alexa")
    log.info("Alexa ouvindo em http://127.0.0.1:%s/alexa (skill %s)", config.ALEXA_PORT,
             "configurada" if config.ALEXA_SKILL_ID else "AINDA NÃO configurada")
    # Gera de antemão as frases fixas com a voz da Friday, para tocarem na hora.
    for phrase in phrases.ALL:
        await _voice(phrase, time.monotonic() + 30, cache=True)
