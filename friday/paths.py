"""Onde ficam as coisas: o programa (APP_DIR) e os dados de quem usa (DATA_DIR).

- APP_DIR: a pasta do código (o projeto, ou a pasta do programa instalado).
- DATA_DIR: configurações, memórias, logins e modelos da pessoa.
  Ordem: variável ORBIT_DATA_DIR -> a própria pasta do projeto, se já tiver .env ou memoria/ (modo de desenvolvimento)
  -> %APPDATA%\\Orbit (programa instalado).
"""
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    env = os.getenv("ORBIT_DATA_DIR", "").strip()
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    if (APP_DIR / ".env").exists() or (APP_DIR / "memoria").is_dir():
        return APP_DIR
    return Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming")) / "Orbit"


DATA_DIR = _data_dir()
MEMORIA = DATA_DIR / "memoria"
MODELS = DATA_DIR / "models"
ENV_FILE = DATA_DIR / ".env"
GOOGLE_CREDENTIALS = DATA_DIR / "credentials.json"  # baixado do Google Cloud Console de quem usa
GOOGLE_TOKEN = DATA_DIR / "token.json"  # criado depois do login; fica só no PC

MEMORIA.mkdir(parents=True, exist_ok=True)
