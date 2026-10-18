# Orbit (beta)

Uma assistente de IA pessoal para Windows, numa ilha preta no topo da tela. Você cria a sua (nome, personalidade e voz), ela usa as suas contas (Claude ou Ollama, Google, Spotify, ElevenLabs) e roda no seu PC.

- **Para instalar e testar:** baixe o instalador na página de [Releases](../../releases) e siga o [COMO-INSTALAR-BETA.md](COMO-INSTALAR-BETA.md).
- **Exemplo de assistente pronta:** [exemplos/sexta-feira](exemplos/sexta-feira).

## Como o projeto é organizado

| Pasta | O que é |
|---|---|
| `friday/` | O cérebro (Python): conversa, ferramentas (agenda, timers, PC, música…), voz e a ponte local com a ilha. |
| `orbit/` | A ilha (Electron): abas, configurações, guia de primeira configuração (`setup/`) e o modo instalado (`beta.js`). |
| `tools/` | `preparar_beta.js` (monta o pacote) e `verificar_vazamento.py` (barra chaves e dados pessoais). |
| `exemplos/` | Assistentes de referência. Não são carregadas por padrão. |

## Gerar o instalador

1. Uma vez: monte `build/python` com o Python 3.12.10 portátil (pacote `python` do NuGet) e rode `build\python\python.exe -m pip install -r requirements-lock.txt imageio-ffmpeg`.
2. `cd orbit`, `npm install` e `npm run dist`. Sai `build/dist/Orbit Beta Setup <versão>.exe`, e o pacote é conferido pelo verificador de vazamento.
3. Para testar sem instalar: `npm run beta` (usa o `.venv` do projeto e a pasta `%APPDATA%\Orbit Beta`).

Os dados de quem usa (configuração, chaves, memórias) ficam em `%APPDATA%\Orbit Beta\dados` e nunca entram no git nem no instalador.
