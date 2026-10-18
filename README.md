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

## Créditos

A ideia do Orbit, uma ilha no topo da tela que junta música, sistema, agenda e uso de IA, veio do **[Vorssaint](https://github.com/vorssaint/vorssaint-utils)**, um app de barra de menus para macOS feito por vorssaint. O Orbit é um projeto independente, escrito do zero para Windows: nenhum código, ícone ou arquivo do Vorssaint foi copiado. Algumas telas seguem o mesmo espírito (por exemplo, a aba de uso de IA em cartões e a leitura da cota do Claude Code a cada minuto). O nome, o ícone e a identidade visual do Vorssaint pertencem ao autor dele; se você gosta da ideia no Mac, use o original.

Também usa: [Electron](https://www.electronjs.org/), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [edge-tts](https://github.com/rany2/edge-tts), [Ollama](https://ollama.com/), a API do [Claude](https://www.anthropic.com/) e o [FFmpeg](https://ffmpeg.org/) (incluído no instalador pelo pacote imageio-ffmpeg).

## Licença

[GPL-3.0](LICENSE), a mesma do Vorssaint. Você pode usar, estudar, modificar e redistribuir o Orbit. Se distribuir uma versão modificada, ela também precisa ser GPL-3.0, com o código aberto. Para uma versão sua, dê outro nome e outro ícone.
