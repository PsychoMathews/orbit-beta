"""Ajustes do Windows: energia, limpeza e alertas. A assistente e a aba "Windows" do Orbit usam tudo daqui.

Energia
- Manter acordado (por X min, até o render do DaVinci acabar, ou até desligar), sem mexer nas configurações do Windows.
- Dormir/desligar a tela após X min (powercfg, na tomada) e plano de energia (Equilibrado, Alto desempenho...).
- Desligar/reiniciar agendado ou quando o render acabar (a IA agenda direto; dá para cancelar).
Limpeza
- Varredura de lixo regenerável (temporários, cache de render do DaVinci, caches de navegador) e instaladores velhos.
- Caches e temporários são apagados de vez (o programa recria); instaladores vão para a Lixeira.
- Esvaziar a Lixeira só pelo botão da ilha (clique do usuário); a IA nunca esvazia.
Alertas
- CPU no máximo por minutos, RAM quase cheia, disco quase cheio, GPU quente. Avisa na ilha e no Telegram, sem voz.
"""
import asyncio
import ctypes
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import psutil
from send2trash import send2trash

from .tools_common import TZ, fn
from .paths import MEMORIA
from . import assistente

log = logging.getLogger("friday.winsys")

STATE_FILE = MEMORIA / "windows.json"
HOME = Path.home()
NO_WINDOW = subprocess.CREATE_NO_WINDOW

DEFAULT_STATE = {
    "awake": {"mode": "off", "until": None, "screen": False, "since": None},
    "shutdown": {"action": None, "at": None, "after_render": False},
    "alerts": {"cpu": True, "ram": True, "disk": True, "gpu": True},
    # Faxina automática: "off", "daily" ou "weekly"; downloads_days > 0 manda para a Lixeira o que ficou em Downloads mais que isso.
    "autoclean": {"every": "off", "targets": ["temp", "browsers", "installers"], "downloads_days": 0, "last": 0},
    "davinci_cache": str(HOME / "Videos" / "CacheClip"),
}


def _load() -> dict:
    import json
    try:
        saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        saved = {}
    state = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_STATE.items()}
    for k, v in saved.items():
        if isinstance(v, dict) and isinstance(state.get(k), dict):
            state[k].update(v)
        else:
            state[k] = v
    return state


def _save(state: dict) -> None:
    import json
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    _publish()


def _publish() -> None:
    from . import orbit
    try:
        orbit.publish("windows", **status())
    except Exception:
        log.debug("Sem publicar estado do Windows", exc_info=True)


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


# ---------- Energia ----------

ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002
_awake_wakeup = threading.Event()


def _awake_thread() -> None:
    """SetThreadExecutionState vale para a thread que chamou; por isso uma thread só cuida disso."""
    applied = None
    while True:
        a = _load()["awake"]
        on = a["mode"] != "off"
        flags = ES_CONTINUOUS | ((ES_SYSTEM_REQUIRED | (ES_DISPLAY_REQUIRED if a.get("screen") else 0)) if on else 0)
        if flags != applied or on:
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
            applied = flags
        _awake_wakeup.wait(30)
        _awake_wakeup.clear()


def keep_awake(mode: str = "forever", minutes: float = 0, keep_screen: bool = False) -> str:
    """mode: off | minutes | until_render | forever."""
    state = _load()
    if mode not in ("off", "minutes", "until_render", "forever"):
        return "Modo inválido. Use off, minutes, until_render ou forever."
    if mode == "minutes" and not minutes:
        return "Diga por quantos minutos."
    until = (time.time() + float(minutes) * 60) if mode == "minutes" else None
    state["awake"] = {"mode": mode, "until": until, "screen": bool(keep_screen), "since": time.time(), "seen_render": False}
    _save(state)
    _awake_wakeup.set()
    if mode == "off":
        return "Pronto: o PC volta a dormir normalmente, conforme as configurações do Windows."
    what = "o PC e a tela ficam ligados" if keep_screen else "o PC não vai dormir (a tela pode apagar)"
    if mode == "minutes":
        return f"Pronto: {what} até as {datetime.fromtimestamp(until, TZ):%H:%M}."
    if mode == "until_render":
        return f"Pronto: {what} até o render do DaVinci terminar. Eu aviso quando acabar."
    return f"Pronto: {what} até você mandar desligar o modo acordado."


def _powercfg(*args: str) -> str:
    return subprocess.run(["powercfg", *args], capture_output=True, text=True, encoding="cp850", errors="ignore",
                          creationflags=NO_WINDOW, timeout=15).stdout


def _read_timeout(sub: str, setting: str) -> int | None:
    """Minutos na tomada (0 = nunca)."""
    vals = re.findall(r"0x([0-9a-fA-F]+)\s*$", _powercfg("/query", "SCHEME_CURRENT", sub, setting), re.M)
    return int(vals[-2], 16) // 60 if len(vals) >= 2 else None


def _plans() -> list[dict]:
    plans = []
    for guid, name, active in re.findall(r"([0-9a-f-]{36})\s+\((.+?)\)\s*(\*)?", _powercfg("/list")):
        plans.append({"guid": guid, "name": name, "active": bool(active)})
    return plans


def power_set(sleep_minutes: int | None = None, screen_minutes: int | None = None) -> str:
    """Muda quando o PC dorme e quando a tela apaga (na tomada). 0 = nunca."""
    done = []
    if sleep_minutes is not None:
        _powercfg("/change", "standby-timeout-ac", str(int(sleep_minutes)))
        done.append("dormir: " + ("nunca" if int(sleep_minutes) == 0 else f"após {int(sleep_minutes)} min sem uso"))
    if screen_minutes is not None:
        _powercfg("/change", "monitor-timeout-ac", str(int(screen_minutes)))
        done.append("tela: " + ("nunca apaga" if int(screen_minutes) == 0 else f"apaga após {int(screen_minutes)} min"))
    _publish()
    return ("Configurado — " + "; ".join(done) + ".") if done else "Nada mudou: diga os minutos para dormir e/ou para a tela."


def power_plan(name: str = "") -> str:
    plans = _plans()
    if not name:
        return "Planos: " + ", ".join(p["name"] + (" (ativo)" if p["active"] else "") for p in plans)
    key = name.lower()
    alias = {"desempenho": "alto", "maximo": "alto", "máximo": "alto", "economia": "economia", "normal": "equilibrado", "balanceado": "equilibrado"}
    for word, target in alias.items():
        if word in key:
            key = target
    plan = next((p for p in plans if key in p["name"].lower()), None)
    if not plan:
        return f"Não achei o plano '{name}'. Planos: {', '.join(p['name'] for p in plans)}."
    _powercfg("/setactive", plan["guid"])
    _publish()
    return f"Plano de energia agora: {plan['name']}."


def schedule_shutdown(action: str = "shutdown", minutes: float = 0, after_render: bool = False) -> str:
    """Executado depois da confirmação (ou pelo clique na ilha)."""
    if action not in ("shutdown", "restart"):
        return "Ação inválida (shutdown ou restart)."
    state = _load()
    state["awake"]["seen_render"] = False  # só conta o render que vier depois deste pedido
    state["awake"]["since"] = state["awake"].get("since") or time.time()
    state["shutdown"] = {"action": action, "after_render": bool(after_render),
                         "at": None if after_render else time.time() + max(1.0, float(minutes)) * 60}
    _save(state)
    verb = "desligar" if action == "shutdown" else "reiniciar"
    if after_render:
        return f"Combinado: vou {verb} o PC quando o render do DaVinci terminar (com 2 min de aviso para cancelar)."
    return f"Combinado: vou {verb} o PC às {datetime.fromtimestamp(state['shutdown']['at'], TZ):%H:%M} (com 1 min de aviso do Windows)."


def shutdown_cancel() -> str:
    state = _load()
    had = state["shutdown"]["action"]
    state["shutdown"] = {"action": None, "at": None, "after_render": False}
    _save(state)
    subprocess.run(["shutdown", "/a"], capture_output=True, creationflags=NO_WINDOW)
    return "Desligamento cancelado." if had else "Não havia desligamento agendado (cancelei qualquer aviso do Windows por garantia)."


def status() -> dict:
    s = _load()
    return {"awake": s["awake"], "shutdown": s["shutdown"], "alerts": s["alerts"], "autoclean": s["autoclean"],
            "server": {"on": bool((s.get("server") or {}).get("on")), "since": (s.get("server") or {}).get("since")}}


def power_status() -> dict:
    return {**status(), "sleep": _read_timeout("SUB_SLEEP", "STANDBYIDLE"), "screen": _read_timeout("SUB_VIDEO", "VIDEOIDLE"),
            "plans": _plans()}


def power_info() -> str:
    p = power_status()
    a, sd = p["awake"], p["shutdown"]
    awake = {"off": "desligado", "forever": "ligado até você desligar", "until_render": "ligado até o render acabar",
             "minutes": f"ligado até {datetime.fromtimestamp(a['until'], TZ):%H:%M}" if a.get("until") else "ligado"}[a["mode"]]
    lines = [f"Modo acordado: {awake}.",
             "PC dorme: " + ("nunca" if p["sleep"] == 0 else f"após {p['sleep']} min sem uso") + ".",
             "Tela apaga: " + ("nunca" if p["screen"] == 0 else f"após {p['screen']} min") + ".",
             "Plano: " + next((x["name"] for x in p["plans"] if x["active"]), "?") + "."]
    if sd["action"]:
        verb = "Desligar" if sd["action"] == "shutdown" else "Reiniciar"
        lines.append(f"{verb} agendado: " + ("quando o render acabar" if sd["after_render"] else datetime.fromtimestamp(sd["at"], TZ).strftime("%H:%M")) + ".")
    return " ".join(lines)


def _rendering() -> bool | None:
    try:
        from . import resolve
        return bool(resolve.snapshot(10).get("rendering"))
    except Exception:
        return None


async def _power_loop(notify) -> None:
    while True:
        try:
            s = _load()
            a, sd = s["awake"], s["shutdown"]
            changed = False
            needs_render = a["mode"] == "until_render" or (sd["action"] and sd["after_render"])
            rendering = await asyncio.to_thread(_rendering) if needs_render else None
            if a["mode"] == "minutes" and a.get("until") and time.time() >= a["until"]:
                s["awake"] = dict(DEFAULT_STATE["awake"]); changed = True
                await notify("☕ Modo acordado terminou; o PC volta a dormir normalmente.", None, kind="windows")
            if needs_render and rendering:
                a["seen_render"] = True; changed = True
            # O render "acabou": já foi visto renderizando e parou, ou nunca começou em 10 min.
            render_done = rendering is False and (a.get("seen_render") or time.time() - (a.get("since") or time.time()) > 600)
            if a["mode"] == "until_render" and render_done:
                s["awake"] = dict(DEFAULT_STATE["awake"]); changed = True
                await notify("🎬 Render terminou: modo acordado desligado.", None, kind="windows")
            if sd["action"] and sd["after_render"] and render_done:
                sd["after_render"], sd["at"] = False, time.time() + 120; changed = True
                verb = "desligar" if sd["action"] == "shutdown" else "reiniciar"
                await notify(f"⏻ Render terminou: vou {verb} o PC em 2 minutos. Para cancelar: 'cancela o desligamento' ou o botão na ilha.",
                             f"Chefe, o render terminou. Vou {verb} o PC em dois minutos.", kind="shutdown")
            if sd["action"] and sd.get("at") and time.time() >= sd["at"]:
                flag = "/s" if sd["action"] == "shutdown" else "/r"
                subprocess.run(["shutdown", flag, "/t", "60", "/c", f"{assistente.NOME}: o PC vai desligar em 1 minuto. (shutdown /a cancela)"],
                               creationflags=NO_WINDOW)
                s["shutdown"] = dict(DEFAULT_STATE["shutdown"]); changed = True
            if changed:
                _save(s)
                _awake_wakeup.set()
        except Exception:
            log.exception("Erro no controle de energia")
        await asyncio.sleep(15)


# ---------- Limpeza ----------

def _cache_targets() -> dict[str, dict]:
    s = _load()
    local = Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local"))
    return {
        "temp": {"name": "Temporários do usuário", "paths": [Path(os.environ.get("TEMP", ""))], "how": "delete",
                 "desc": "Arquivos com mais de 24 h que os programas deixam para trás."},
        "wintemp": {"name": "Temporários do Windows", "paths": [Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Temp"], "how": "delete",
                    "desc": "Só o que dá para apagar sem administrador."},
        "davinci": {"name": "Cache de render do DaVinci", "paths": [Path(s["davinci_cache"])], "how": "delete",
                    "desc": "O DaVinci recria quando precisar (feche o DaVinci antes)."},
        "browsers": {"name": "Cache dos navegadores", "paths": [
            local / "Google/Chrome/User Data/Default/Cache", local / "Google/Chrome/User Data/Default/Code Cache",
            local / "Microsoft/Edge/User Data/Default/Cache", local / "Microsoft/Edge/User Data/Default/Code Cache",
            Path(os.environ.get("APPDATA", "")) / "Opera Software/Opera GX Stable/Cache"], "how": "delete",
            "desc": "Imagens e páginas guardadas; os sites recarregam."},
        "installers": {"name": "Instaladores antigos em Downloads", "paths": [], "how": "trash",
                       "desc": ".exe, .msi e .zip de instalador com mais de 14 dias; vão para a Lixeira."},
        "old_downloads": {"name": "Downloads antigos", "paths": [], "how": "trash",
                          "desc": f"Tudo em Downloads com mais de {s['autoclean']['downloads_days'] or 30} dias; vai para a Lixeira."},
    }


def _old_downloads(days: int | None = None) -> list[Path]:
    days = days or _load()["autoclean"]["downloads_days"] or 30
    cutoff = time.time() - days * 86400
    try:
        return [f for f in (HOME / "Downloads").iterdir()
                if not f.name.startswith(".") and f.name.lower() != "desktop.ini" and f.stat().st_mtime < cutoff]
    except Exception:
        return []


def _installers() -> list[Path]:
    cutoff = time.time() - 14 * 86400
    try:
        # .zip só conta se o nome parece instalador; zip de projeto/asset é do usuário.
        installer_zip = re.compile(r"setup|install|windows|win64|x64|amd64|_win|-win", re.I)
        return [f for f in (HOME / "Downloads").iterdir()
                if f.is_file() and f.stat().st_mtime < cutoff
                and (f.suffix.lower() in (".exe", ".msi") or (f.suffix.lower() == ".zip" and installer_zip.search(f.stem)))]
    except Exception:
        return []


def _dir_size(path: Path, deadline: float) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
        if time.time() > deadline:
            break
    return total


def _recycle_size() -> int:
    class Info(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]
    info = Info(); info.cbSize = ctypes.sizeof(Info)
    ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    return info.i64Size


_scan_cache: tuple[float, dict] = (0.0, {})


def scan() -> dict:
    global _scan_cache
    if time.time() - _scan_cache[0] < 60:
        return _scan_cache[1]
    deadline = time.time() + 45
    out = {}
    for key, t in _cache_targets().items():
        if key in ("installers", "old_downloads"):
            files = _installers() if key == "installers" else _old_downloads()
            size = sum(f.stat().st_size if f.is_file() else _dir_size(f, deadline) for f in files)
            out[key] = {"name": t["name"], "desc": t["desc"], "size": size, "count": len(files)}
        else:
            size = sum(_dir_size(p, deadline) for p in t["paths"] if p.exists())
            out[key] = {"name": t["name"], "desc": t["desc"], "size": size}
    out["recycle"] = {"name": "Lixeira", "desc": "Esvaziar é só pelo botão na ilha.", "size": _recycle_size()}
    disks = []
    for part in psutil.disk_partitions(all=False):
        if "fixed" not in part.opts and "rw" not in part.opts:
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
            disks.append({"drive": part.mountpoint.rstrip("\\"), "free": u.free, "total": u.total})
        except Exception:
            pass
    result = {"targets": out, "disks": disks, "at": time.time()}
    _scan_cache = (time.time(), result)
    return result


def cleanup_scan() -> str:
    s = scan()
    lines = [f"- {v['name']}: {_human(v['size'])}" + (f" ({v['count']} arquivos)" if "count" in v else "")
             for v in s["targets"].values()]
    total = sum(v["size"] for k, v in s["targets"].items() if k != "recycle")
    disks = "; ".join(f"{d['drive']} {_human(d['free'])} livres de {_human(d['total'])}" for d in s["disks"])
    return (f"Dá para liberar uns {_human(total)}:\n" + "\n".join(lines) + f"\nDiscos: {disks}.\n"
            "Para limpar, use cleanup_run com as chaves: temp, wintemp, davinci, browsers, installers. A Lixeira só pelo botão da ilha.")


KEEP_IN_TEMP = {"claude"}  # pastas de trabalho de outros programas que não são lixo


def _wipe_dir(path: Path, min_age_hours: float = 0) -> tuple[int, int]:
    """Apaga o conteúdo (não a pasta). Arquivos em uso ficam; com min_age_hours, só o que é mais velho que isso."""
    freed = skipped = 0
    cutoff = time.time() - min_age_hours * 3600
    try:
        entries = list(path.iterdir())
    except OSError:  # sem permissão (ex.: C:\Windows\Temp sem administrador)
        return 0, 0
    for entry in entries:
        if entry.name.lower() in KEEP_IN_TEMP:
            continue
        try:
            if min_age_hours and entry.stat().st_mtime > cutoff:
                continue
            size = entry.stat().st_size if entry.is_file() else _dir_size(entry, time.time() + 20)
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
            freed += size
        except Exception:
            skipped += 1
    return freed, skipped


def cleanup_files(key: str) -> list[dict]:
    """O que vai para a Lixeira num item de "mandar para a Lixeira" (para conferir antes), maiores primeiro."""
    files = _installers() if key == "installers" else _old_downloads() if key == "old_downloads" else []
    deadline = time.time() + 15
    out = []
    for f in files:
        try:
            st = f.stat()
            out.append({"name": f.name, "path": str(f), "dir": f.is_dir(), "mtime": st.st_mtime,
                        "size": st.st_size if f.is_file() else _dir_size(f, deadline)})
        except OSError:
            pass
    return sorted(out, key=lambda x: -x["size"])


def cleanup_run(targets: list[str] | str, only: dict | None = None) -> str:
    """only = {"old_downloads": [caminhos]}: desses itens, só os caminhos marcados (sempre dentro da lista calculada)."""
    global _scan_cache
    if isinstance(targets, str):
        targets = [t.strip() for t in targets.split(",")]
    all_targets = _cache_targets()
    freed = skipped = 0
    done = []
    for key in targets:
        t = all_targets.get(key)
        if not t:
            continue
        if key == "davinci" and _rendering():
            done.append("cache do DaVinci pulado (está renderizando)")
            continue
        if t["how"] == "trash":
            allowed = _installers() if key == "installers" else _old_downloads()
            if only and key in only:
                keep = {os.path.normcase(p) for p in only[key]}
                allowed = [f for f in allowed if os.path.normcase(str(f)) in keep]
            for f in allowed:
                try:
                    size = f.stat().st_size if f.is_file() else _dir_size(f, time.time() + 10)
                    send2trash(str(f))
                    freed += size
                except Exception:
                    skipped += 1
        else:
            for p in t["paths"]:
                f, sk = _wipe_dir(p, 24 if key in ("temp", "wintemp") else 0)
                freed += f; skipped += sk
        done.append(t["name"].lower())
    _scan_cache = (0.0, {})
    _publish()
    if not done:
        return "Nada foi limpo (chaves válidas: temp, wintemp, davinci, browsers, installers, old_downloads)."
    return f"Limpei {', '.join(done)}: {_human(freed)} liberados." + (f" {skipped} itens em uso ficaram." if skipped else "")


def empty_recycle_bin() -> str:
    """Só pelo clique do usuário na ilha (nunca exposto para a IA)."""
    size = _recycle_size()
    ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)
    global _scan_cache
    _scan_cache = (0.0, {})
    return f"Lixeira esvaziada: {_human(size)} liberados."


def autoclean_set(every: str | None = None, targets: list[str] | None = None, downloads_days: int | None = None) -> str:
    s = _load()
    a = s["autoclean"]
    if every in ("off", "daily", "weekly"):
        a["every"] = every
        a["last"] = a["last"] or time.time()  # primeira faxina só depois do intervalo, não na hora
    if targets is not None:
        a["targets"] = [t for t in targets if t in _cache_targets() and t != "recycle"]
    if downloads_days is not None:
        a["downloads_days"] = max(0, int(downloads_days))
        if a["downloads_days"] and "old_downloads" not in a["targets"]:
            a["targets"].append("old_downloads")
        if not a["downloads_days"]:
            a["targets"] = [t for t in a["targets"] if t != "old_downloads"]
    _save(s)
    if a["every"] == "off":
        return "Faxina automática desligada."
    names = {k: v["name"].lower() for k, v in _cache_targets().items()}
    return (f"Faxina automática {'todo dia' if a['every'] == 'daily' else 'toda semana'}: "
            + ", ".join(names.get(t, t) for t in a["targets"]) + ".")


async def _autoclean_loop(notify) -> None:
    while True:
        await asyncio.sleep(1800)
        try:
            s = _load()
            a = s["autoclean"]
            gap = {"daily": 86400, "weekly": 7 * 86400}.get(a["every"])
            if not gap or time.time() - (a["last"] or 0) < gap or not a["targets"]:
                continue
            msg = await asyncio.to_thread(cleanup_run, list(a["targets"]))
            s = _load()
            s["autoclean"]["last"] = time.time()
            _save(s)
            await notify(f"🧹 Faxina automática: {msg}", None, kind="alert")
        except Exception:
            log.exception("Erro na faxina automática")


# ---------- Modo servidor (PC ligado a semana toda, gastando o mínimo) ----------

def server_mode(on: bool) -> str:
    """Liga: não dorme, tela apaga em 1 min, plano de economia, tira a IA local da placa de vídeo e põe a ilha no
    modo leve. Desliga: volta tudo como estava antes (guardado em windows.json)."""
    s = _load()
    cur = s.get("server") or {}
    if on and cur.get("on"):
        return "O modo servidor já está ligado."
    if not on and not cur.get("on"):
        return "O modo servidor já está desligado."
    from . import orbit
    if on:
        active = next((p["name"] for p in _plans() if p["active"]), "")
        prev = {"awake": s["awake"], "plan": active,
                "screen": _read_timeout("SUB_VIDEO", "VIDEOIDLE"), "sleep": _read_timeout("SUB_SLEEP", "STANDBYIDLE")}
        s["server"] = {"on": True, "since": time.time(), "prev": prev}
        _save(s)
        power_plan("economia")
        power_set(sleep_minutes=0, screen_minutes=1)  # o plano novo tem os próprios tempos: ajusta depois de trocar
        keep_awake("forever", keep_screen=False)
        from .gamemode import _free_gpu
        _free_gpu()
        orbit.publish("server", on=True)
        _publish()
        return ("Modo servidor ligado: o PC não dorme, a tela apaga em 1 minuto, plano Economia de energia e a IA "
                "local saiu da placa de vídeo. Continuo atendendo pelo Telegram, iPhone e Alexa. Deixe o Tailscale ligado.")
    prev = cur.get("prev") or {}
    if prev.get("plan"):
        power_plan(prev["plan"])
    power_set(sleep_minutes=prev.get("sleep") if prev.get("sleep") is not None else None,
              screen_minutes=prev.get("screen") if prev.get("screen") is not None else None)
    a = prev.get("awake") or {"mode": "off"}
    if a.get("mode") == "minutes" and a.get("until") and a["until"] > time.time():
        keep_awake("minutes", (a["until"] - time.time()) / 60, a.get("screen", False))
    elif a.get("mode") in ("forever", "until_render"):
        keep_awake(a["mode"], keep_screen=a.get("screen", False))
    else:
        keep_awake("off")
    s = _load()
    s["server"] = {"on": False}
    _save(s)
    orbit.publish("server", on=False)
    _publish()
    return "Modo servidor desligado: energia, tela e plano voltaram como estavam."


# ---------- Alertas ----------

ALERT_COOLDOWN = 30 * 60


def _gpu_temp() -> int | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5, creationflags=NO_WINDOW).stdout
        return int(out.strip().splitlines()[0])
    except Exception:
        return None


def _top_process(by: str) -> str:
    procs = []
    for p in psutil.process_iter(["name", "memory_info", "cpu_percent"]):
        try:
            procs.append((p.info["cpu_percent"] or 0, (p.info["memory_info"].rss if p.info["memory_info"] else 0), p.info["name"]))
        except Exception:
            pass
    if not procs:
        return ""
    top = max(procs, key=lambda x: x[0] if by == "cpu" else x[1])
    return f" O que mais pesa: {top[2]}" + (f" ({_human(top[1])})." if by == "ram" else ".")


async def _alerts_loop(notify) -> None:
    high_since: dict[str, float] = {}
    last_sent: dict[str, float] = {}
    psutil.cpu_percent(None)
    tick = 0
    while True:
        await asyncio.sleep(15)
        tick += 1
        try:
            enabled = _load()["alerts"]
            now = time.time()
            checks = {}
            if enabled.get("cpu"):
                checks["cpu"] = (psutil.cpu_percent(None) >= 90, 300)
            if enabled.get("ram"):
                checks["ram"] = (psutil.virtual_memory().percent >= 92, 120)
            if enabled.get("gpu"):
                t = await asyncio.to_thread(_gpu_temp)
                checks["gpu"] = (t is not None and t >= 85, 60)
            for key, (bad, sustain) in checks.items():
                if not bad:
                    high_since.pop(key, None)
                    continue
                high_since.setdefault(key, now)
                if now - high_since[key] >= sustain and now - last_sent.get(key, 0) >= ALERT_COOLDOWN:
                    last_sent[key] = now
                    msg = {"cpu": "🔥 CPU no máximo há mais de 5 minutos." + await asyncio.to_thread(_top_process, "cpu"),
                           "ram": f"🧠 Memória quase cheia ({psutil.virtual_memory().percent:.0f}%)." + await asyncio.to_thread(_top_process, "ram"),
                           "gpu": f"🌡️ GPU quente: {await asyncio.to_thread(_gpu_temp)} °C há mais de 1 minuto."}[key]
                    await notify(msg, None, kind="alert")
            if enabled.get("disk") and tick % 40 == 1:  # a cada ~10 min
                for part in psutil.disk_partitions(all=False):
                    try:
                        u = psutil.disk_usage(part.mountpoint)
                    except Exception:
                        continue
                    key = "disk:" + part.mountpoint
                    if (u.free < 20 * 1024**3 or u.percent >= 95) and now - last_sent.get(key, 0) >= 6 * 3600:
                        last_sent[key] = now
                        await notify(f"💾 Disco {part.mountpoint.rstrip(chr(92))} quase cheio: {_human(u.free)} livres. "
                                     "Peça 'libera espaço' para eu ver o que dá para limpar.", None, kind="alert")
        except Exception:
            log.exception("Erro nos alertas do sistema")


def alerts_set(cpu: bool | None = None, ram: bool | None = None, disk: bool | None = None, gpu: bool | None = None) -> str:
    s = _load()
    for k, v in (("cpu", cpu), ("ram", ram), ("disk", disk), ("gpu", gpu)):
        if v is not None:
            s["alerts"][k] = bool(v)
    _save(s)
    names = {"cpu": "CPU", "ram": "memória", "disk": "disco", "gpu": "GPU"}
    return "Alertas ligados: " + (", ".join(names[k] for k, v in s["alerts"].items() if v) or "nenhum") + "."


async def run(notify) -> None:
    threading.Thread(target=_awake_thread, daemon=True, name="manter-acordado").start()
    s = _load()
    try:  # guarda onde o DaVinci põe o cache, para limpar mesmo com ele fechado
        from . import resolve
        loc = (await asyncio.to_thread(resolve.snapshot, 10)).get("cache", "")
        if loc and loc != s["davinci_cache"]:
            s["davinci_cache"] = loc
            _save(s)
    except Exception:
        pass
    asyncio.create_task(_power_loop(notify))
    asyncio.create_task(_alerts_loop(notify))
    asyncio.create_task(_autoclean_loop(notify))


# ---------- Tema claro/escuro ----------

THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def windows_theme() -> str:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_KEY) as k:
        return "claro" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "escuro"


def set_windows_theme(mode: str) -> None:
    import winreg
    light = 1 if mode == "claro" else 0
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "AppsUseLightTheme", 0, winreg.REG_DWORD, light)
        winreg.SetValueEx(k, "SystemUsesLightTheme", 0, winreg.REG_DWORD, light)
    # Avisa as janelas abertas para trocarem na hora (WM_SETTINGCHANGE "ImmersiveColorSet").
    result = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "ImmersiveColorSet", 0x0002, 3000, ctypes.byref(result))


def theme(mode: str, target: str = "tudo") -> str:
    """mode: claro | escuro | sistema (só para o Orbit). target: windows | orbit | tudo."""
    from . import orbit
    mode = {"light": "claro", "dark": "escuro", "system": "sistema"}.get(mode, mode)
    if mode not in ("claro", "escuro", "sistema"):
        return "Use claro, escuro ou sistema."
    done = []
    if target in ("windows", "tudo") and mode != "sistema":
        set_windows_theme(mode)
        done.append(f"Windows no modo {mode}")
    if target in ("orbit", "tudo"):
        orbit.publish("theme", mode=mode)
        done.append("Orbit " + ("seguindo o Windows" if mode == "sistema" else f"no modo {mode}"))
    return "Pronto: " + " e ".join(done) + "." if done else "Nada mudou."


# ---------- Ferramentas da IA ----------

TOOLS = {
    "keep_awake": keep_awake, "power_info": power_info, "power_set": power_set, "power_plan": power_plan,
    "shutdown_cancel": shutdown_cancel, "cleanup_scan": cleanup_scan, "alerts_set": alerts_set, "theme": theme,
    "server_mode": server_mode,
}
CONFIRM_TOOLS = {"schedule_shutdown": schedule_shutdown, "cleanup_run": cleanup_run, "autoclean_set": autoclean_set}


def describe(name: str, args: dict) -> str | None:
    if name == "schedule_shutdown":
        verb = "Desligar" if args.get("action", "shutdown") == "shutdown" else "Reiniciar"
        when = "quando o render do DaVinci terminar" if args.get("after_render") else f"daqui a {args.get('minutes', 0)} min"
        return f"⏻ {verb} o PC {when}"
    if name == "cleanup_run":
        t = args.get("targets", [])
        t = t if isinstance(t, list) else [t]
        names = {k: v["name"] for k, v in _cache_targets().items()}
        return "🧹 Limpar (apaga de vez caches/temporários; instaladores vão para a Lixeira):\n" + "\n".join(f"- {names.get(k, k)}" for k in t)
    if name == "autoclean_set":
        every = {"off": "desligar", "daily": "todo dia", "weekly": "toda semana"}.get(args.get("every") or "", "")
        days = args.get("downloads_days")
        return "🧹 Faxina automática" + (f": {every}" if every else "") + (f"; Downloads com mais de {days} dias para a Lixeira" if days else "")
    return None


SCHEMAS = [
    fn("theme", "Muda o tema claro/escuro do Windows e/ou do Orbit (a ilha).", {
        "mode": {"type": "string", "enum": ["claro", "escuro", "sistema"]},
        "target": {"type": "string", "enum": ["tudo", "windows", "orbit"], "description": "Padrão: tudo"},
    }, ["mode"]),
    fn("keep_awake", "Impede o PC de dormir: por X minutos, até o render do DaVinci acabar, ou até mandar parar (mode=off desliga).", {
        "mode": {"type": "string", "enum": ["minutes", "until_render", "forever", "off"]},
        "minutes": {"type": "number"},
        "keep_screen": {"type": "boolean", "description": "true = tela também fica ligada"},
    }, ["mode"]),
    fn("power_info", "Mostra a situação de energia: modo acordado, quando o PC dorme, quando a tela apaga, plano de energia, desligamento agendado.", {}),
    fn("power_set", "Muda depois de quantos minutos sem uso o PC dorme e/ou a tela apaga (0 = nunca).", {
        "sleep_minutes": {"type": "integer"}, "screen_minutes": {"type": "integer"},
    }),
    fn("power_plan", "Lista ou troca o plano de energia do Windows (ex.: 'alto desempenho' para renderizar, 'equilibrado').", {
        "name": {"type": "string", "description": "Vazio = listar"},
    }),
    fn("schedule_shutdown", "Agenda desligar ou reiniciar o PC daqui a X minutos ou quando o render do DaVinci terminar.", {
        "action": {"type": "string", "enum": ["shutdown", "restart"]},
        "minutes": {"type": "number"}, "after_render": {"type": "boolean"},
    }, ["action"]),
    fn("shutdown_cancel", "Cancela o desligamento/reinício agendado.", {}),
    fn("server_mode", "Modo servidor: deixa o PC ligado dias seguidos gastando o mínimo (não dorme, tela apaga, plano de "
       "economia, tira a IA local da placa de vídeo, ilha leve) para ele falar com a assistente de longe. on=false desfaz tudo.", {
           "on": {"type": "boolean"},
       }, ["on"]),
    fn("cleanup_scan", "Varre o PC atrás de espaço para liberar (temporários, cache do DaVinci, navegadores, instaladores velhos, Lixeira) e mostra os discos.", {}),
    fn("cleanup_run", "Limpa os itens escolhidos depois da varredura (o usuário confirma).", {
        "targets": {"type": "array", "items": {"type": "string", "enum": ["temp", "wintemp", "davinci", "browsers", "installers", "old_downloads"]}},
    }, ["targets"]),
    fn("autoclean_set", "Liga/desliga a faxina automática (todo dia ou toda semana), escolhe o que limpar e quantos dias um arquivo pode ficar em Downloads antes de ir para a Lixeira (0 = nunca). O usuário confirma.", {
        "every": {"type": "string", "enum": ["off", "daily", "weekly"]},
        "targets": {"type": "array", "items": {"type": "string", "enum": ["temp", "wintemp", "davinci", "browsers", "installers", "old_downloads"]}},
        "downloads_days": {"type": "integer"},
    }),
    fn("alerts_set", "Liga/desliga os alertas automáticos de CPU, memória, disco e temperatura da GPU.", {
        "cpu": {"type": "boolean"}, "ram": {"type": "boolean"}, "disk": {"type": "boolean"}, "gpu": {"type": "boolean"},
    }),
]
