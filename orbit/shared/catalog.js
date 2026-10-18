// Catálogo dos módulos do Orbit e configuração padrão. Usado pela ilha, pelas Configurações e pelo processo principal.
(function (root) {
  const MODULES = [
    { id: 'sexta', name: '%nome%', icon: 'spark', desc: 'Fale ou digite para a IA. Mostra quando ela ouve, pensa e fala.' },
    { id: 'midia', name: 'Música', icon: 'music', desc: 'O que está tocando em qualquer player (Spotify, YouTube, navegador), com controles.' },
    { id: 'som', name: 'Som', icon: 'volUp', desc: 'Volume geral e por programa (Spotify baixo, chamada alta), com mudo por app.' },
    { id: 'agenda', name: 'Agenda', icon: 'calendar', desc: 'Próximos eventos e o mês inteiro da sua agenda Google.' },
    { id: 'lembretes', name: 'Lembretes', icon: 'bell', desc: 'Lembretes pendentes que você pediu para %a%.' },
    { id: 'timer', name: 'Timer', icon: 'timer', desc: 'Timers e pomodoro. %A% também cria timers por voz.' },
    { id: 'sistema', name: 'Sistema', icon: 'cpu', desc: 'CPU, GPU, memória, temperatura e disco com gráficos.' },
    { id: 'windows', name: 'Windows', icon: 'bolt', desc: 'Energia (manter acordado, quando dormir, desligar depois do render), faxina de espaço e alertas do sistema.' },
    { id: 'davinci', name: 'DaVinci', icon: 'film', desc: 'Projeto aberto e fila de render do DaVinci Resolve.' },
    { id: 'ia', name: 'Uso de IA', icon: 'gauge', desc: 'Cota do Claude em tempo real, aviso quando uma tarefa longa termina, tokens, valor em API e projetos.' },
    { id: 'arquivos', name: 'Arquivos', icon: 'folder', desc: 'Downloads em andamento e recentes, e a Prateleira: arraste arquivos para a ilha e solte em outro lugar depois.' },
    { id: 'clipboard', name: 'Área de transferência', icon: 'clip', desc: 'Histórico do que você copiou. Clique para copiar de novo.' },
    { id: 'notas', name: 'Notas', icon: 'note', desc: 'Bloco de notas rápido, salvo automaticamente.' },
    { id: 'avisos', name: 'Avisos', icon: 'inbox', desc: 'Histórico dos avisos e respostas %da%.' },
  ];

  const DEFAULTS = {
    modules: { order: MODULES.map((m) => m.id), enabled: Object.fromEntries(MODULES.map((m) => [m.id, true])) },
    island: {
      expandOnHover: true, hoverDelay: 180, collapseDelay: 450, idleOpacity: 0.9,
      panelWidth: 660, offsetY: 8, liveMusic: true, liveTimer: true, sounds: true, theme: 'escuro', lite: false, compactPanel: false,
      orbMode: 'grad', orbC1: '#2f7bff', orbC2: '#9b5cff', orbC3: '#ff6fb5',
    },
    friday: { speakTyped: false },
    clipboard: { max: 30 },
  };

  // Nome da assistente (vem do bot). Textos usam marcadores: %A% "A Luna", %a% "a Luna", %à% "à Luna", %da% "da Luna",
  // %nome% "Luna". Na ilha e nas Configurações um observador troca os marcadores em tudo que aparece na tela.
  const assist = { nome: 'Orbit', artigo: 'a' };
  const MARK = /%(A|a|à|da|nome)%/g;
  function names(s) {
    const o = assist.artigo === 'o', n = assist.nome;
    return s.replace(MARK, (_, k) => ({ A: (o ? 'O ' : 'A ') + n, a: (o ? 'o ' : 'a ') + n, 'à': (o ? 'ao ' : 'à ') + n, da: (o ? 'do ' : 'da ') + n, nome: n })[k]);
  }

  const api = { MODULES, DEFAULTS, names, assist };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else {
    root.ORBIT_CATALOG = api;
    // Guarda o texto original (com marcadores) em cada nó, para refazer quando o nome chegar ou mudar.
    const ATTRS = ['placeholder', 'title', 'aria-label'];
    const raw = new WeakMap();
    const fixText = (t) => {
      const src = raw.get(t) ?? t.data;
      if (!src.includes('%')) return;
      MARK.lastIndex = 0;
      if (!MARK.test(src)) return;
      raw.set(t, src);
      const v = names(src);
      if (t.data !== v) t.data = v;
    };
    const fixEl = (el) => {
      for (const a of ATTRS) {
        const k = 'data-raw-' + a, v = el.getAttribute(k) ?? el.getAttribute(a);
        if (v && v.includes('%')) { el.setAttribute(k, v); el.setAttribute(a, names(v)); }
      }
    };
    const walk = (node) => {
      if (node.nodeType === 3) return fixText(node);
      if (node.nodeType !== 1) return;
      fixEl(node);
      const w = document.createTreeWalker(node, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
      for (let n = w.nextNode(); n; n = w.nextNode()) n.nodeType === 3 ? fixText(n) : fixEl(n);
    };
    const start = () => {
      walk(document.body);
      new MutationObserver((ms) => { for (const m of ms) for (const n of m.addedNodes) walk(n); })
        .observe(document.body, { childList: true, subtree: true });
    };
    if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
    root.ORBIT_SET_ASSIST = (a) => {
      if (!a || (a.nome === assist.nome && a.artigo === assist.artigo)) return;
      Object.assign(assist, { nome: a.nome || 'Orbit', artigo: a.artigo === 'o' ? 'o' : 'a' });
      document.title = names(document.title);
      if (document.body) walk(document.body);
    };
  }
})(this);
