# Orbit Beta: como instalar e testar

O Orbit é uma assistente de IA que mora numa ilha preta no topo da tela do Windows. Você cria a sua: nome, jeito de falar e voz. Ela usa as **suas** contas e roda no **seu** PC.

## Do que você precisa

- Windows 10 ou 11 (64 bits), microfone e caixas de som (ou fone).
- **Um cérebro, pelo menos um dos dois:**
  - **Chave da API do Claude** (recomendado). Paga por uso, na sua conta: uns US$ 5 dão para testar bastante. O guia mostra o passo a passo.
  - **Ollama** (grátis, roda no PC). Precisa de placa de vídeo NVIDIA com 8 GB ou mais.
- Internet (para a voz e para o reconhecimento de voz, que é baixado na primeira vez que você fala, uns 500 MB).

## Instalar

1. Rode o `Orbit Beta Setup 0.1.0.exe`.
2. O Windows deve mostrar **"O Windows protegeu o computador"**. É porque o programa ainda não tem assinatura digital paga. Clique em **Mais informações → Executar assim mesmo**.
3. Abre a tela **Primeira configuração**. Siga as etapas; cada conta tem um botão **Testar**:
   - **Sua assistente:** nome, seu nome, personalidade.
   - **Cérebro:** chave do Claude ou Ollama.
   - **Voz:** voz grátis da Microsoft (botão **Ouvir**) ou ElevenLabs.
   - **Detalhes:** atalho para falar, cidade e, se quiser, Agenda/Gmail do Google.
4. Clique em **Concluir**. A ilha aparece no topo da tela.

## Usar

- Passe o mouse na ilha para abrir as abas: assistente, Música, Som, Agenda, Lembretes, Timer, Sistema, Windows, Notas e mais.
- **Falar:** aperte o atalho escolhido (padrão **Ctrl + Alt + Espaço**), espere o bipe e fale. Ou digite na aba dela.
- Ideias de teste: "que horas são?", "timer de 1 minuto", "anota leite na lista de compras", "vai chover amanhã?", "abaixa o volume do Spotify para 30%", "liga o modo jogo", "quanto está o dólar?".
- **Ícone do anel na bandeja** (perto do relógio): clique para as Configurações; botão direito para o menu e **Refazer configuração**.
- O Orbit abre sozinho quando o Windows liga. Para fechar: botão direito no ícone → **Sair do Orbit**.

## Se algo der errado

- O registro de erros fica em `%APPDATA%\Orbit Beta\dados\memoria\bot.log`. Mande esse arquivo para quem te passou o Orbit. Ele não tem as suas chaves, mas pode ter trechos das suas conversas.
- Seus dados, chaves e memórias ficam em `%APPDATA%\Orbit Beta`.
- **Desinstalar:** Configurações do Windows → Aplicativos → **Orbit Beta** → Desinstalar. Apaga o programa e os seus dados.

## O que ainda não tem nesta beta

Alexa, Telegram, palavra de ativação falada ("Ei, Luna") e atualização automática. As ações perigosas (apagar arquivos, fechar programas, mandar e-mail, criar evento) sempre pedem confirmação na própria ilha.
