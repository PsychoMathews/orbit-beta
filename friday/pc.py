"""Acesso da Friday ao PC.

Regras de segurança (no código, não só no prompt):
- Olhar (listar, medir, ver processos) e abrir pastas: livre.
- Apagar, fechar programa e rodar comando: SEMPRE viram ação pendente com botão de confirmação.
- Apagar manda para a LIXEIRA (dá para recuperar), nunca apaga de vez.
- Pastas protegidas (PROTECTED_PATHS no .env) não podem ser apagadas nem por pedido.
"""
import os
import subprocess
import time
from pathlib import Path

import psutil
from send2trash import send2trash

from . import config

HOME = Path.home()


def _protected() -> list[Path]:
    paths = [Path(os.path.expandvars(p.strip())).expanduser() for p in config.PROTECTED_PATHS.split(";") if p.strip()]
    system = [Path(os.environ.get("SystemRoot", r"C:\Windows")), Path(r"C:\Program Files"), Path(r"C:\Program Files (x86)")]
    return [p.resolve() for p in paths + system]


def is_protected(path: str | Path) -> bool:
    p = Path(path).expanduser().resolve()
    if p == HOME or p.parent == p:  # a pasta do usuário inteira ou a raiz de um disco
        return True
    return any(p == prot or prot in p.parents for prot in _protected())


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _resolve(path: str) -> Path:
    path = os.path.expandvars(path or str(HOME))
    aliases = {"downloads": HOME / "Downloads", "temp": Path(os.environ.get("TEMP", "")), "desktop": HOME / "Desktop"}
    return aliases.get(path.lower().strip(), Path(path).expanduser())


def _size(path: Path, deadline: float) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        if time.time() > deadline:
            break
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


# ---------- Ferramentas de leitura ----------

def system_status() -> str:
    mem = psutil.virtual_memory()
    lines = [f"CPU: {psutil.cpu_percent(interval=0.5):.0f}%",
             f"RAM: {_human(mem.used)} usados de {_human(mem.total)} ({mem.percent:.0f}%)"]
    for part in psutil.disk_partitions():
        try:
            u = psutil.disk_usage(part.mountpoint)
            lines.append(f"Disco {part.mountpoint} {_human(u.free)} livres de {_human(u.total)} ({u.percent:.0f}% usado)")
        except OSError:
            pass
    procs = {}
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            procs[p.info["name"]] = procs.get(p.info["name"], 0) + p.info["memory_info"].rss
        except (psutil.Error, TypeError, AttributeError):
            pass
    top = sorted(procs.items(), key=lambda x: -x[1])[:10]
    lines.append("Programas que mais usam RAM: " + ", ".join(f"{n} {_human(s)}" for n, s in top))
    return "\n".join(lines)


def list_folder(path: str = "") -> str:
    p = _resolve(path)
    if not p.is_dir():
        return f"Pasta não encontrada: {p}"
    items = []
    for e in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:60]:
        try:
            info = "pasta" if e.is_dir() else _human(e.stat().st_size)
        except OSError:
            info = "?"
        items.append(f"- {e.name} ({info})")
    return f"{p} {'[PROTEGIDA]' if is_protected(p) else ''}\n" + "\n".join(items)


def folder_sizes(path: str = "") -> str:
    """Tamanho de cada subpasta, maiores primeiro (com limite de tempo)."""
    p = _resolve(path)
    if not p.is_dir():
        return f"Pasta não encontrada: {p}"
    deadline = time.time() + 40
    sizes = []
    for e in p.iterdir():
        try:
            s = _size(e, deadline) if e.is_dir() else e.stat().st_size
        except OSError:
            continue
        sizes.append((s, e))
    sizes.sort(key=lambda x: -x[0])
    note = " (parcial: pasta grande demais, tempo esgotado)" if time.time() > deadline else ""
    return f"{p}{note}\n" + "\n".join(
        f"- {e.name}: {_human(s)}{' [PROTEGIDA]' if is_protected(e) else ''}" for s, e in sizes[:20]
    )


def find_large_files(path: str = "", min_mb: int = 500) -> str:
    p = _resolve(path)
    deadline, found = time.time() + 40, []
    for root, _dirs, files in os.walk(p, onerror=lambda e: None):
        if time.time() > deadline:
            break
        for f in files:
            fp = os.path.join(root, f)
            try:
                s = os.lstat(fp).st_size
            except OSError:
                continue
            if s >= int(min_mb) * 1024 * 1024:
                found.append((s, fp))
    found.sort(key=lambda x: -x[0])
    if not found:
        return f"Nenhum arquivo acima de {min_mb} MB em {p}."
    return "\n".join(f"- {fp} ({_human(s)}){' [PROTEGIDO]' if is_protected(fp) else ''}" for s, fp in found[:25])


def cleanup_candidates() -> str:
    """Lugares típicos de lixo e quanto ocupam."""
    deadline = time.time() + 40
    spots = {
        "Temporários do usuário (%TEMP%)": Path(os.environ.get("TEMP", "")),
        "Temporários do Windows": Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Temp",
        "Downloads": HOME / "Downloads",
        "Cache de modelos HuggingFace": HOME / ".cache" / "huggingface",
        "Cache do pip": HOME / "AppData" / "Local" / "pip" / "cache",
        "Cache do Chrome": HOME / "AppData" / "Local" / "Google" / "Chrome" / "User Data" / "Default" / "Cache",
    }
    lines = [f"- {name}: {_human(_size(p, deadline))} ({p})" for name, p in spots.items() if p.exists()]
    installers = [f for f in (HOME / "Downloads").glob("*") if f.suffix.lower() in (".exe", ".msi", ".zip")]
    installers += [f for f in HOME.glob("*") if f.is_file() and f.suffix.lower() in (".exe", ".msi")]
    if installers:
        total = sum(f.stat().st_size for f in installers)
        lines.append(f"- Instaladores e .zip soltos (Downloads e pasta do usuário): {len(installers)} arquivos, {_human(total)}")
    lines.append("Obs.: esvaziar a Lixeira o usuário faz sozinho; a Friday só move coisas para lá.")
    return "\n".join(lines)


def open_path(path: str) -> str:
    p = _resolve(path)
    if not p.exists():
        return f"Não existe: {p}"
    os.startfile(p)  # abre no Explorer (pasta) ou no programa padrão (arquivo)
    return f"Aberto: {p}"


# ---------- Ações que precisam de confirmação ----------

def check_delete(paths: list[str]) -> str | None:
    """Recusa antes mesmo de pedir confirmação se algo for protegido ou não existir."""
    for raw in paths:
        p = _resolve(raw)
        if is_protected(p):
            return f"Recusado: {p} está numa pasta protegida."
        if not p.exists():
            return f"Não existe: {p}"
    return None


def delete_paths(paths: list[str]) -> str:
    done, failed = [], []
    for raw in paths:
        p = _resolve(raw)
        if is_protected(p):  # confere de novo na hora de executar
            failed.append(f"{p} (protegido)")
            continue
        try:
            send2trash(str(p))
            done.append(str(p))
        except Exception as e:
            failed.append(f"{p} ({e})")
    msg = f"{len(done)} item(ns) movido(s) para a Lixeira."
    return msg + (" Falharam: " + "; ".join(failed) if failed else "")


def clean_temp() -> str:
    """Move o conteúdo de %TEMP% para a Lixeira (arquivos em uso são pulados)."""
    temp = Path(os.environ.get("TEMP", ""))
    moved = skipped = 0
    for e in temp.iterdir():
        try:
            send2trash(str(e))
            moved += 1
        except Exception:
            skipped += 1
    return f"{moved} item(ns) dos temporários foram para a Lixeira; {skipped} estavam em uso e ficaram. Esvazie a Lixeira para liberar o espaço."


def kill_process(name: str) -> str:
    killed = 0
    for p in psutil.process_iter(["name"]):
        if (p.info["name"] or "").lower() == name.lower():
            try:
                p.terminate()
                killed += 1
            except psutil.Error:
                pass
    return f"{killed} processo(s) {name} encerrado(s)." if killed else f"Nenhum processo {name} encontrado."


def run_command(command: str) -> str:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True, text=True, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    out = (r.stdout + r.stderr).strip()
    return f"Código de saída {r.returncode}.\n{out[-3000:]}" if out else f"Código de saída {r.returncode}, sem saída."
