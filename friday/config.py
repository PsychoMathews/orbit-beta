import os
from pathlib import Path

from dotenv import load_dotenv
from .paths import ENV_FILE
from . import assistente

load_dotenv(ENV_FILE)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_IDS = {
    int(x) for x in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x
}

# Telegram é opcional: sem token (ou sem ID permitido) tudo funciona pela ilha e pela voz do PC.
TELEGRAM_ON = bool(TELEGRAM_BOT_TOKEN and ALLOWED_USER_IDS)
# Conversa principal (memória recente): o ID do Telegram de quem usa, ou 0 sem Telegram.
OWNER_ID = next(iter(ALLOWED_USER_IDS), 0)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
# Modelo grande, usado com /pesado (mais lento, melhor para código, análise e pesquisa).
OLLAMA_MODEL_HEAVY = os.getenv("OLLAMA_MODEL_HEAVY", "")

# Voz: "local" (Kokoro, grátis) ou "elevenlabs". Ouvir: "local" (Whisper na GPU) ou "elevenlabs".
VOICE_ENGINE = os.getenv("VOICE_ENGINE", "local")
STT_ENGINE = os.getenv("STT_ENGINE", "local")
# Voz de reserva quando a ElevenLabs falha (sem créditos/fora do ar): voz neural da Microsoft, grátis e sem chave.
EDGE_VOICE = os.getenv("EDGE_VOICE", "pt-BR-FranciscaNeural")  # a Thalita (multilíngue) puxava sotaque espanhol
EDGE_RATE = os.getenv("EDGE_RATE", "+8%")
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "pf_dora")
KOKORO_SPEED = float(os.getenv("KOKORO_SPEED", "1.1"))
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
# "cpu" (padrão) deixa a placa de vídeo livre para jogos e DaVinci; "cuda" usa a placa (um pouco mais rápido).
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
# Quanto tempo o modelo fica carregado na placa depois da última pergunta (ex.: 10m, 1h, 0 = descarrega na hora).
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "10m")
# Memória de contexto do modelo local. O Ollama 0.40 recusa (erro 400) pedido maior que o padrão dele (4096 tokens),
# e o prompt da assistente com histórico e ferramentas passa de 9 mil.
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

# Cérebro na nuvem (API do Claude) para perguntas, pesquisa e conversa. Sem ANTHROPIC_API_KEY = tudo no qwen local.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLOUD_MODEL = os.getenv("CLOUD_MODEL", "claude-opus-5-5")
# Profundidade do raciocínio: low (mais rápido) a high. Pesquisa sempre pode buscar na internet.
CLOUD_EFFORT = os.getenv("CLOUD_EFFORT", "low")
# Onde a nuvem responde: "pc" (só a voz do PC) ou "pc,telegram,alexa".
# Quem é o cérebro na nuvem: "plano" (Claude Code na conta do usuário, sem custo extra) ou "api" (cobrada à parte).
CLOUD_BACKEND = os.getenv("CLOUD_BACKEND", "plano")
CLOUD_CHANNELS = {c.strip() for c in os.getenv("CLOUD_CHANNELS", "pc").split(",") if c.strip()}
# Trânsito: chave da TomTom (developer.tomtom.com, grátis) e lugares salvos (casa=Rua X, 10;trabalho=Av. Y, 200).
TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "")
PLACES = os.getenv("PLACES", "")

# Pastas que a Friday NUNCA apaga (separadas por ;). Windows e Arquivos de Programas já são protegidos sempre.
PROTECTED_PATHS = os.getenv("PROTECTED_PATHS", ";".join(rf"%USERPROFILE%\{d}" for d in (
    "Pictures", "Videos", "Documents", "Music", "Desktop", "OneDrive", "DaVinci Resolve Media")))

# Atalho global para falar com a Friday pelo microfone do PC.
HOTKEY = os.getenv("HOTKEY", "ctrl+alt+f")
# Microfone do atalho (parte do nome, ex. "Realtek"); vazio = padrão do Windows.
MIC_DEVICE = os.getenv("MIC_DEVICE", "")

# Alexa: ID da sua skill (amzn1.ask.skill...). Vazio = recusa tudo.
ALEXA_SKILL_ID = os.getenv("ALEXA_SKILL_ID", "")
ALEXA_PORT = int(os.getenv("ALEXA_PORT", "8787"))
# Endereço público (túnel) para a Alexa buscar o áudio com a voz da Friday. Vazio = voz da Alexa.
ALEXA_PUBLIC_URL = os.getenv("ALEXA_PUBLIC_URL", "")
# Atalho do iPhone (Botão de Ação): chave secreta que o atalho manda no cabeçalho. Vazio = rota desligada.
SHORTCUT_TOKEN = os.getenv("SHORTCUT_TOKEN", "")
# Modelo da ElevenLabs na Alexa: o Flash gera em metade do tempo (a Amazon corta em 8 s).
ALEXA_VOICE_MODEL = os.getenv("ALEXA_VOICE_MODEL", "eleven_flash_v2_5")

# Proatividade: resumo da manhã (HH:MM; vazio desliga), aviso de reunião, silêncio para avisos automáticos.
MORNING_TIME = os.getenv("MORNING_TIME", "08:00")
MEETING_ALERT_MIN = int(os.getenv("MEETING_ALERT_MIN", "10"))
QUIET_START = int(os.getenv("QUIET_START", "23"))
QUIET_END = int(os.getenv("QUIET_END", "7"))
# Falar os avisos também nas caixas de som do PC (1 = sim).
PC_SPEAK = os.getenv("PC_SPEAK", "1") == "1"
# Cidade padrão para o clima.
HOME_CITY = os.getenv("HOME_CITY", "São Paulo")
# Modo trabalho: programas para abrir e processos para fechar (separados por ;).
WORK_APPS = os.getenv("WORK_APPS", "DaVinci Resolve")
# DaVinci / projetos de vídeo: onde criar projetos, estrutura de pastas e destino de backup.
VIDEO_PROJECTS_DIR = os.getenv("VIDEO_PROJECTS_DIR", "G:\\")
PROJECT_TEMPLATE = os.getenv("PROJECT_TEMPLATE", "1.BRUTOS/CARD 01;1.BRUTOS/MOBILE;2.AUDIO/LOC;2.AUDIO/TRILHAS;"
                             "2.AUDIO/SFX;3.ASSETS;4.PROJETO;5.RENDER")
BACKUP_DIR = os.getenv("BACKUP_DIR", "C:\\BACKUP PROJETOS")
WORK_CLOSE = os.getenv("WORK_CLOSE", "steam.exe;EpicGamesLauncher.exe;RiotClientServices.exe;uTorrent.exe")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
# Velocidade da fala: 0.7 (lenta) a 1.2 (rápida); 1.0 é o normal.
ELEVENLABS_SPEED = float(os.getenv("ELEVENLABS_SPEED", "1.0"))
# 0.3 = expressiva e variável; 0.7 = estável e consistente.
ELEVENLABS_STABILITY = float(os.getenv("ELEVENLABS_STABILITY", "0.6"))

# Identidade e personalidade vêm de assistente.json (friday/assistente.py).
PERSONA = assistente.persona()
