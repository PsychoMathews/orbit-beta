// Guia de primeira configuração: 6 telas, cada conta com botão de teste. Salvar grava assistente.json e .env
// na pasta de dados (beta.js) e liga o assistente.
const $ = (id) => document.getElementById(id);
const S = window.setup;
const sections = [...document.querySelectorAll('section')];
let step = 0, pers = 'direta';
const ok = { claude: false, ollama: false };

$('steps').innerHTML = sections.map(() => '<i></i>').join('');

function show(n) {
  step = Math.max(0, Math.min(sections.length - 1, n));
  sections.forEach((s, i) => s.classList.toggle('on', i === step));
  [...$('steps').children].forEach((b, i) => b.classList.toggle('on', i <= step));
  $('back').style.visibility = step ? 'visible' : 'hidden';
  $('next').textContent = step === 0 ? 'Começar' : step === sections.length - 1 ? 'Concluir e abrir o Orbit' : 'Continuar';
  if (step === sections.length - 1) summary();
  window.scrollTo(0, 0);
}

function res(id, r, wait) {
  const el = $(id);
  el.className = 'res ' + (wait ? 'wait' : r && r.ok ? 'ok' : 'bad');
  el.textContent = wait ? 'Testando…' : (r && r.msg) || '';
}

function check() { // o que impede de avançar em cada tela
  if (step === 1 && !$('nome').value.trim()) return 'Dê um nome para a sua assistente.';
  if (step === 1 && !$('usuario').value.trim()) return 'Diga o seu nome.';
  if (step === 1 && pers === 'propria' && !$('personalidade_texto').value.trim()) return 'Descreva a personalidade ou escolha um dos modelos.';
  if (step === 2 && !ok.claude && !ok.ollama) return 'Teste a chave do Claude ou o Ollama: pelo menos um precisa funcionar.';
  if (step === 3 && $('elevenKey').value.trim() && !$('elevenVoice').value) return 'Teste a chave da ElevenLabs e escolha uma voz, ou apague a chave.';
  return '';
}

function summary() {
  const a = $('artigo').value === 'o' ? 'o' : 'a', n = $('nome').value.trim();
  const brain = ok.claude ? 'Claude' : 'Ollama (no seu PC)';
  const voz = $('elevenKey').value.trim() ? 'ElevenLabs' : $('edgeVoice').selectedOptions[0].textContent;
  $('resumo').textContent = `${a === 'o' ? 'O' : 'A'} ${n} vai pensar com ${brain} e falar com a voz ${voz}.`;
  $('hk').textContent = $('hotkey').selectedOptions[0].textContent;
}

$('next').onclick = async () => {
  if (step < sections.length - 1) {
    const err = check();
    if (err) { alert(err); return; }
    return show(step + 1);
  }
  $('next').disabled = true; res('rSave', null, true); $('rSave').textContent = 'Salvando e ligando…';
  const r = await S.save({
    nome: $('nome').value, artigo: $('artigo').value, usuario: $('usuario').value, tratamento: $('tratamento').value,
    sobre_linha: $('sobre_linha').value, sobre: $('sobre').value, personalidade: pers, personalidade_texto: $('personalidade_texto').value,
    claudeKey: ok.claude ? $('claudeKey').value.trim() : '', claudeModel: $('claudeModel').value,
    ollamaModel: $('ollamaModel').value, edgeVoice: $('edgeVoice').value,
    elevenKey: $('elevenKey').value.trim(), elevenVoice: $('elevenVoice').value,
    hotkey: $('hotkey').value, cidade: $('cidade').value,
  });
  if (!r.ok) { res('rSave', r); $('next').disabled = false; }
};
$('back').onclick = () => show(step - 1);

for (const d of $('pers').children) d.onclick = () => {
  pers = d.dataset.p;
  for (const x of $('pers').children) x.classList.toggle('sel', x === d);
  $('personalidade_texto').style.display = pers === 'propria' ? 'block' : 'none';
};
$('pers').children[0].classList.add('sel');

for (const a of document.querySelectorAll('a[data-url]')) a.onclick = () => S.open(a.dataset.url);

$('tClaude').onclick = async () => {
  const key = $('claudeKey').value.trim();
  if (!key) return res('rClaude', { ok: false, msg: 'Cole a chave primeiro.' });
  res('rClaude', null, true);
  const r = await S.test('claude', { key, model: $('claudeModel').value });
  ok.claude = r.ok; res('rClaude', r);
};
$('claudeKey').oninput = () => { ok.claude = false; };
$('tOllama').onclick = async () => {
  res('rOllama', null, true);
  const r = await S.test('ollama');
  ok.ollama = r.ok; res('rOllama', r);
  if (r.models && r.models.length) $('ollamaModel').innerHTML = r.models.map((m) => `<option>${m.replace(/</g, '')}</option>`).join('');
};
$('tVoz').onclick = async () => { res('rVoz', null, true); res('rVoz', await S.test('voz', { voice: $('edgeVoice').value })); };
$('tEleven').onclick = async () => {
  const key = $('elevenKey').value.trim();
  if (!key) return res('rEleven', { ok: false, msg: 'Cole a chave primeiro.' });
  res('rEleven', null, true);
  const r = await S.test('elevenlabs', { key });
  res('rEleven', r);
  if (r.ok) {
    const opts = (r.voices || []).map((v) => `<option value="${v.id.replace(/"/g, '')}">${v.name.replace(/</g, '')}</option>`).join('');
    $('elevenVoice').innerHTML = opts || '<option value="">(nenhuma voz na conta)</option>';
  }
};
$('tGoogle').onclick = async () => { res('rGoogle', null, true); $('rGoogle').textContent = 'Siga o login no navegador…'; res('rGoogle', await S.google()); };

// Refazendo a configuração: preenche o que já existe (as chaves precisam ser testadas de novo).
S.load().then((d) => {
  if (!d || !d.nome) return;
  for (const k of ['nome', 'usuario', 'tratamento']) $(k).value = d[k] || '';
  $('artigo').value = d.artigo === 'o' ? 'o' : 'a';
  $('sobre_linha').value = d.sobre_usuario || '';
  const p = [...$('pers').children].find((x) => x.dataset.p === d.personalidade);
  if (p) p.click();
  $('personalidade_texto').value = d.personalidade_texto || '';
  if (d.env_CLOUD_MODEL) $('claudeModel').value = d.env_CLOUD_MODEL;
  if (d.env_EDGE_VOICE) $('edgeVoice').value = d.env_EDGE_VOICE;
  if (d.env_HOTKEY) $('hotkey').value = d.env_HOTKEY;
  $('cidade').value = d.env_HOME_CITY || '';
  if (d.env_ANTHROPIC_API_KEY) { $('claudeKey').value = d.env_ANTHROPIC_API_KEY; }
  if (d.env_ELEVENLABS_API_KEY) { $('elevenKey').value = d.env_ELEVENLABS_API_KEY; }
});

show(0);
