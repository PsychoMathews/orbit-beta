"""DaVinci Resolve: status e fila de render, aviso quando o render termina, pastas de projeto e backup.

Para status/render, o Resolve precisa estar aberto e com o scripting externo ligado:
Preferências > Sistema > Geral > "External scripting using" = Local.
Pastas e backup não dependem do Resolve.
"""
import os
import subprocess
import sys
from pathlib import Path

from . import config
from .tools_common import fn
from .paths import APP_DIR

API = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Blackmagic Design/DaVinci Resolve/Support/Developer/Scripting"
LIB = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Blackmagic Design/DaVinci Resolve/fusionscript.dll"

NOT_RUNNING = ("Não consegui falar com o DaVinci Resolve. Ele precisa estar aberto e com o scripting ligado"
               " (Preferências > Sistema > Geral > External scripting using: Local).")


def _resolve():
    os.environ.setdefault("RESOLVE_SCRIPT_API", str(API))
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", str(LIB))
    modules = str(API / "Modules")
    if modules not in sys.path:
        sys.path.append(modules)
    try:
        import DaVinciResolveScript as dvr
        return dvr.scriptapp("Resolve")
    except Exception:
        return None


def _project():
    r = _resolve()
    return r.GetProjectManager().GetCurrentProject() if r else None


_SNAP = ("import json; from friday import resolve as r; p = r._project(); t = p and p.GetCurrentTimeline(); "
         "print(json.dumps({'running': True, 'project': p.GetName(), 'timeline': t.GetName() if t else '', "
         "'rendering': bool(p.IsRenderingInProgress()), 'jobs': r.render_jobs(), "
         "'cache': p.GetSetting('perfCacheClipsLocation') or ''} if p else {'running': False, 'jobs': []}))")


def snapshot(timeout: float = 15) -> dict:
    """Estado do Resolve lido num processo à parte.

    Com a timeline tocando, a biblioteca do Resolve trava segurando o GIL e congelava o bot inteiro
    (ponte do Orbit, mixer, Telegram). Num processo separado, o pior caso é esse processo ser morto.
    Levanta exceção se não responder a tempo.
    """
    import json
    exe = sys.executable.replace("pythonw.exe", "python.exe")
    out = subprocess.run([exe, "-c", _SNAP], capture_output=True, text=True, timeout=timeout,
                         cwd=str(APP_DIR), creationflags=0x08000000)
    return json.loads(out.stdout.strip().splitlines()[-1])


def render_jobs() -> list[dict]:
    """Usado também pelo relógio para avisar quando um render termina."""
    project = _project()
    if not project:
        return []
    jobs = []
    for job in project.GetRenderJobList() or []:
        status = project.GetRenderJobStatus(job["JobId"]) or {}
        jobs.append({"id": job["JobId"], "name": job.get("OutputFilename") or job.get("TimelineName", "?"),
                     "status": status.get("JobStatus", "?"), "progress": status.get("CompletionPercentage", 0),
                     "project": project.GetName()})
    return jobs


def resolve_status() -> str:
    project = _project()
    if not project:
        return NOT_RUNNING
    timeline = project.GetCurrentTimeline()
    lines = [f"Projeto aberto: {project.GetName()}" + (f", timeline {timeline.GetName()}" if timeline else "")]
    lines.append("Renderizando agora." if project.IsRenderingInProgress() else "Nenhum render em andamento.")
    jobs = render_jobs()
    lines += [f"- {j['name']}: {j['status']} ({j['progress']}%)" for j in jobs] or ["Fila de render vazia."]
    return "\n".join(lines)


def _start_render() -> str:
    project = _project()
    if not project:
        return NOT_RUNNING
    if not project.GetRenderJobList():
        return "A fila de render está vazia; adicione os jobs no Resolve primeiro."
    return "Render iniciado." if project.StartRendering() else "O Resolve recusou iniciar o render."


_just_created: set[str] = set()


def create_project_folders(name: str, base: str = "") -> str:
    base_dir = Path(base or config.VIDEO_PROJECTS_DIR)
    if not base_dir.exists():
        return f"A pasta base não existe: {base_dir}"
    safe = "".join(c for c in name if c not in '<>:"/\\|?*').strip()
    if not safe:
        return "Nome de projeto inválido."
    project = base_dir / safe
    if str(project) in _just_created:  # a IA às vezes chama duas vezes seguidas
        return f"Projeto criado em {project}."
    if project.exists():
        return f"Já existe um projeto com esse nome: {project}"
    _just_created.add(str(project))
    for sub in config.PROJECT_TEMPLATE.split(";"):
        if sub.strip():
            (project / sub.strip()).mkdir(parents=True, exist_ok=True)
    os.startfile(project)
    return f"Projeto criado em {project}, com as pastas: {config.PROJECT_TEMPLATE.replace(';', ', ')}."


def _backup(source: str, dest: str = "") -> str:
    src = Path(source)
    if not src.is_dir():
        return f"Pasta de origem não existe: {src}"
    target = Path(dest or config.BACKUP_DIR) / src.name
    # /E copia subpastas; /XO pula o que já está igual. NÃO usa /MIR: nunca apaga nada no destino.
    r = subprocess.run(["robocopy", str(src), str(target), "/E", "/XO", "/R:1", "/W:2", "/NP", "/NFL", "/NDL", "/NJH"],
                       capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode >= 8:
        return f"Backup com erro (código {r.returncode}): {r.stdout[-500:]}"
    copied = 0
    for line in r.stdout.splitlines():
        parts = line.split(":", 1)
        if parts[0].strip() in ("Arquivos", "Files") and len(parts) > 1 and len(parts[1].split()) > 1:
            copied = int(parts[1].split()[1])  # colunas: Total, Copiados, Ignorados...
    return f"Backup feito em {target}: {copied} arquivo(s) copiado(s); o que já estava igual foi pulado."


TOOLS = {"resolve_status": resolve_status, "create_project_folders": create_project_folders}
CONFIRM_TOOLS = {"resolve_start_render": _start_render, "backup_folder": _backup}


def describe(name: str, a: dict) -> str | None:
    if name == "resolve_start_render":
        return "🎬 Iniciar o render da fila do DaVinci Resolve"
    if name == "backup_folder":
        return f"💾 Backup (só copia, nunca apaga)\nDe: {a.get('source')}\nPara: {Path(a.get('dest') or config.BACKUP_DIR) / Path(a.get('source', '')).name}"
    return None


SCHEMAS = [
    fn("resolve_status", "DaVinci Resolve: projeto aberto, se está renderizando e a fila de render com progresso.", {}),
    fn("resolve_start_render", "Inicia o render da fila do DaVinci Resolve.", {}),
    fn("create_project_folders", "Cria a estrutura de pastas de um projeto de vídeo novo no padrão do usuário.", {
        "name": {"type": "string", "description": "Nome do projeto, ex.: 'CLIENTE X 20.10.2026'"},
        "base": {"type": "string", "description": "Pasta base; vazio = padrão"},
    }, ["name"]),
    fn("backup_folder", "Faz backup de uma pasta (ex.: o material de um projeto) para o disco de backup. Só copia,"
       " nunca apaga.", {
           "source": {"type": "string", "description": "Caminho completo da pasta"},
           "dest": {"type": "string", "description": "Destino; vazio = pasta de backup padrão"},
       }, ["source"]),
]
