"""Gravar e transcrever reuniões.

Grava o som que sai do PC (os outros participantes: Meet, Zoom, Teams...) e o microfone dele, em dois arquivos ao
mesmo tempo (soundcard, WASAPI); ao parar, mistura os dois (ffmpeg), transcreve num processo à parte (Whisper, no PC)
e pede ao Claude resumo, decisões e próximos passos. Vira uma nota em Reuniões/ no cofre, com a transcrição inteira.

Para sozinho 5 min depois do fim do evento da agenda (quando a gravação é de um evento) ou em 3 h. Áudio e
transcrição ficam em memoria/reunioes/. Gravar exige avisar os participantes: o aviso de início lembra disso.
"""
import asyncio
import json
import logging
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import assistente, orbit, vault
from .paths import APP_DIR, MEMORIA
from .tools_common import TZ, fn

log = logging.getLogger("friday.meetings")

ROOT = MEMORIA / "reunioes"
NOTES = vault.VAULT / "Reuniões"
MAX_HOURS = 3
RATE = 16000

_rec: dict = {}                 # gravação em andamento
_notify = None                  # notify do bot (avisa quando a nota fica pronta)
_loop: asyncio.AbstractEventLoop | None = None


def set_notifier(loop, notify) -> None:
    global _loop, _notify
    _loop, _notify = loop, notify


def _record(source: str, path: Path, stop: threading.Event) -> None:
    """Grava uma fonte ("pc" = o que sai nos alto-falantes; "mic" = microfone) até stop."""
    import warnings
    import soundcard as sc
    import soundfile as sf
    warnings.filterwarnings("ignore")  # o soundcard avisa a cada pedaço sem som
    try:
        if source == "pc":
            dev = sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True)
        else:
            dev = sc.default_microphone()
        with dev.recorder(samplerate=RATE, channels=1) as r, sf.SoundFile(path, "w", RATE, 1, "PCM_16") as f:
            while not stop.is_set():
                f.write(r.record(numframes=RATE // 2))
    except Exception:
        log.exception("Reunião: falhou a gravação de %s", source)


def _event_now() -> dict | None:
    """O evento da agenda acontecendo agora (ou começando nos próximos 15 min)."""
    try:
        from . import google_auth
        from .tools import list_events_raw
        if not google_auth.connected():
            return None
        now = datetime.now(TZ)
        for ev in list_events_raw(now - timedelta(hours=3), now + timedelta(minutes=15)):
            start, end = ev["start"].get("dateTime"), ev["end"].get("dateTime")
            if start and end and datetime.fromisoformat(start) - timedelta(minutes=15) <= now <= datetime.fromisoformat(end):
                return {"title": ev.get("summary", "Reunião"), "end": datetime.fromisoformat(end).timestamp()}
    except Exception:
        log.debug("Reunião: agenda indisponível", exc_info=True)
    return None


def start(title: str = "") -> str:
    if _rec.get("on"):
        return f"Já estou gravando '{_rec['title']}'. Diga 'para de gravar' para encerrar."
    ev = _event_now() if not title else None
    title = (title or (ev or {}).get("title") or "Reunião").strip()[:80]
    stamp = datetime.now(TZ).strftime("%Y-%m-%d %H%M")
    folder = ROOT / f"{stamp} {''.join(c for c in title if c not in chr(92) + '/:*?\"<>|')}"
    folder.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    threads = [threading.Thread(target=_record, args=(src, folder / f"{src}.wav", stop), daemon=True) for src in ("pc", "mic")]
    for t in threads:
        t.start()
    limit = time.time() + MAX_HOURS * 3600
    until = min(ev["end"] + 300, limit) if ev else limit  # evento da agenda: para 5 min depois do fim
    _rec.update(on=True, title=title, folder=folder, stop=stop, threads=threads, started=time.time(), until=until)
    orbit.publish("notify", text=f"🔴 Gravando: {title}", kind="recording")
    log.info("Reunião: gravando '%s' em %s", title, folder)
    return (f"Gravando '{title}': o som do PC e o seu microfone. Lembre de avisar os participantes que está sendo gravado. "
            "Quando acabar, diga 'para de gravar'" + (" (ou eu paro sozinha no fim do horário da agenda)." if ev else "."))


def stop() -> str:
    if not _rec.get("on"):
        return "Não estou gravando nenhuma reunião."
    _rec["stop"].set()
    for t in _rec["threads"]:
        t.join(timeout=5)
    folder, title, minutes = _rec["folder"], _rec["title"], (time.time() - _rec["started"]) / 60
    _rec.clear()
    orbit.publish("notify", text=f"⏹️ Gravação encerrada: {title}", kind="recording")
    threading.Thread(target=_process, args=(folder, title), daemon=True).start()
    return (f"Parei de gravar '{title}' ({minutes:.0f} min). Vou transcrever e resumir; te aviso quando a nota estiver no cofre.")


def tick() -> None:
    """Chamado a cada minuto pelo relógio: encerra sozinho no fim do evento (+5 min) ou no limite de horas."""
    if _rec.get("on") and time.time() >= _rec["until"]:
        log.info("Reunião: parando sozinha (fim do horário)")
        msg = stop()
        _say(f"⏹️ {msg}")


def _say(text: str) -> None:
    if _loop and _notify:
        asyncio.run_coroutine_threadsafe(_notify(text, None, kind="meeting"), _loop)


# ---------- Gravação feita no celular (app Orbit ou Gravador do iPhone) ----------

def phone_folder(rec_id: str, title: str) -> Path:
    """Pasta da gravação do celular (o app manda pedaços com o mesmo id)."""
    rec_id = "".join(c for c in rec_id if c.isalnum())[:24] or str(int(time.time()))
    found = next(ROOT.glob(f"*__{rec_id}"), None) if ROOT.exists() else None
    if found:
        return found
    title = "".join(c for c in (title or "Reunião") if c not in chr(92) + '/:*?"<>|').strip()[:80] or "Reunião"
    folder = ROOT / f"{datetime.now(TZ):%Y-%m-%d %H%M} {title}__{rec_id}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def process_phone(folder: Path, title: str) -> None:
    """Áudio do celular (m4a/mp4/webm/caf...) vira mic.wav e segue o mesmo caminho da gravação do PC."""
    def run():
        src = next((p for p in folder.iterdir() if p.stem == "celular"), None)
        if not src:
            _say(f"⚠️ A gravação de '{title}' não chegou do celular.")
            return
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", str(RATE), str(folder / "mic.wav")],
                           check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            log.exception("Reunião: áudio do celular não converteu")
            _say(f"⚠️ Não consegui ler o áudio de '{title}' que veio do celular.")
            return
        _process(folder, title)
    threading.Thread(target=run, daemon=True).start()


def _process(folder: Path, title: str) -> None:
    """Mistura, transcreve e resume. Roda numa thread (pode levar vários minutos)."""
    try:
        mix = folder / "reuniao.wav"
        inputs = [p for p in (folder / "pc.wav", folder / "mic.wav") if p.exists() and p.stat().st_size > 2000]
        if not inputs:
            _say(f"⚠️ A gravação de '{title}' ficou vazia: não consegui capturar o áudio.")
            return
        args = ["ffmpeg", "-y", "-loglevel", "error"] + sum((["-i", str(p)] for p in inputs), [])
        args += (["-filter_complex", f"amix=inputs={len(inputs)}:duration=longest:normalize=0"] if len(inputs) > 1 else [])
        subprocess.run(args + ["-ac", "1", "-ar", str(RATE), str(mix)], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        exe = sys.executable.replace("pythonw.exe", "python.exe")
        out = subprocess.run([exe, "-m", "friday.meetings", "transcribe", str(mix)], capture_output=True, text=True,
                             encoding="utf-8", cwd=str(APP_DIR), timeout=4 * 3600, creationflags=subprocess.CREATE_NO_WINDOW)
        segs = json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() else []
        if not segs:
            _say(f"⚠️ Não consegui transcrever '{title}' (sem fala reconhecida). O áudio ficou em {mix}.")
            return
        transcript = "\n".join(f"[{int(s['start'] // 60):02d}:{int(s['start'] % 60):02d}] {s['text'].strip()}" for s in segs)
        (folder / "transcricao.txt").write_text(transcript, encoding="utf-8")
        summary = _summarize(title, transcript)
        NOTES.mkdir(parents=True, exist_ok=True)
        note = NOTES / f"{folder.name.split('__')[0]}.md"
        note.write_text(f"# {title}\n\n{datetime.now(TZ):%d/%m/%Y}\n\n{summary}\n\n## Transcrição\n\n{transcript}\n", encoding="utf-8")
        first = next((l.strip("-• ") for l in summary.splitlines() if l.strip() and not l.startswith("#")), "")
        _say(f"📝 Nota da reunião '{title}' pronta no cofre (Reuniões). {first[:160]}")
    except Exception:
        log.exception("Reunião: falhou o processamento de %s", folder)
        _say(f"⚠️ Falhei ao processar a gravação de '{title}'. O áudio ficou em {folder}.")


def _summarize(title: str, transcript: str) -> str:
    """Resumo pelo Claude do plano (sem custo de API). Sem ele, a nota fica só com a transcrição."""
    from . import claude_agent
    prompt = (f"Abaixo está a transcrição automática da reunião '{title}' (pode ter erros de reconhecimento). Escreva em "
              "português, em markdown curto, três seções: '## Resumo' (3 a 5 linhas), '## Decisões' (lista) e "
              "'## Próximos passos' (lista com responsável e prazo quando aparecerem). Não invente nada que não esteja "
              "na transcrição. Responda só o markdown.\n\n<transcricao>\n" + transcript[-120000:] + "\n</transcricao>")
    try:
        r = subprocess.run([claude_agent.CLAUDE, "-p", prompt, "--output-format", "json", "--model", claude_agent.MODEL,
                            "--tools", "", "--setting-sources", "", "--no-session-persistence"],
                           capture_output=True, text=True, encoding="utf-8", timeout=600, env=claude_agent.PLAN_ENV,
                           cwd=str(APP_DIR), creationflags=subprocess.CREATE_NO_WINDOW)
        res = json.loads(r.stdout or "{}")
        if res.get("result") and not res.get("is_error"):
            return res["result"].strip()
    except Exception:
        log.exception("Reunião: resumo falhou")
    return "## Resumo\n\n(Não consegui resumir agora; a transcrição está abaixo.)"


def _transcribe_main(path: str) -> None:
    """Processo à parte (o Whisper dentro do bot já derrubou o processo): imprime os trechos em JSON."""
    import soundfile as sf
    from .voice import _load_whisper
    model = _load_whisper()
    # Passa as amostras, não o caminho: o leitor de arquivos do faster-whisper quebra com a versão do PyAV instalada.
    samples, _ = sf.read(path, dtype="float32")
    segments, _ = model.transcribe(samples, language="pt", beam_size=5, vad_filter=True, condition_on_previous_text=False)
    print(json.dumps([{"start": s.start, "end": s.end, "text": s.text} for s in segments], ensure_ascii=False))


def meeting_record(acao: str = "iniciar", titulo: str = "") -> str:
    """Para a IA: 'iniciar' (grava) ou 'parar'."""
    return stop() if acao.strip().lower() in ("parar", "para", "stop", "encerrar") else start(titulo)


TOOLS = {"meeting_record": meeting_record}
SCHEMAS = [
    fn("meeting_record", "Grava a reunião no PC (som do PC + microfone) e, ao parar, transcreve e resume numa nota do cofre. "
       "'grava a reunião' = iniciar; 'para de gravar' = parar. Sem título usa o evento da agenda de agora.",
       {"acao": {"type": "string", "enum": ["iniciar", "parar"]}, "titulo": {"type": "string"}}, ["acao"]),
]


if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[1] == "transcribe":
    _transcribe_main(sys.argv[2])
