# Exemplo: Sexta-feira

Uma assistente já testada no uso diário, para servir de referência a quem quiser criar a própria (com o guia de instalação ou pedindo ajuda ao Claude). Não é carregada por padrão: o Orbit só lê o `assistente.json` da pasta de dados de quem usa.

O que tem aqui:
- `assistente.json`: nome, apelido ("Friday"), tratamento ("chefe"), personalidade escrita do zero (fria, elegante, humor seco) e correções do reconhecimento de voz para o nome dela ("se está feira" → "Sexta-feira").

Para usar como ponto de partida, copie o arquivo para a pasta de dados (`%APPDATA%\Orbit Beta\dados\assistente.json` no programa instalado), preencha `usuario` e `sobre_usuario` e reinicie o Orbit. Melhor ainda: troque o nome e a personalidade e crie a sua.

As frases prontas (timer, alarme, lembretes) que combinam com esse estilo ficam em `friday/respostas.py` e `friday/phrases.py`.
