/* Versão em inglês da dashboard.

   A interface é escrita em português, espalhada por templates e por HTML montado em
   JavaScript. Em vez de reescrever cada tela com chaves de tradução, este arquivo
   traduz o que chega ao DOM: cada nó de texto (e placeholder/title/aria-label) é
   procurado, nesta ordem, em
     1. FRASES   — textos fixos da interface (i18n-en.js);
     2. PADRÕES  — textos com números ou nomes no meio ("2 área(s) · 98 tarefa(s)");
     3. TERMOS   — nomes vindos do ClickUp (disciplinas, atividades, status), do
                   mesmo dicionário dos relatórios em inglês (/i18n/terms.js).
   Sem correspondência o texto fica como está — uma frase nova aparece em português
   até entrar no dicionário, nunca quebra a tela. `U2I18n.missing()` lista o que foi
   visto sem tradução.

   O que não passa pelo DOM (rótulos desenhados em canvas pelo ECharts, mensagens de
   prompt/confirm) usa `U2I18n.t(texto)` diretamente.

   Idioma: `?lang=en|pt` na URL (o Nextcloud pode passar `{language}`), senão a
   última escolha guardada no navegador, senão português. */
(function () {
  'use strict';

  var KEY = 'u2-lang';
  var SKIP_TAGS = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, CODE: 1, PRE: 1, NOSCRIPT: 1 };
  // onde o texto é do utilizador ou do assistente, não da interface
  var SKIP_SELECTOR = '[data-no-i18n], #chat-messages, #mob-chat-messages';
  var ATTRIBUTES = ['placeholder', 'title', 'aria-label'];

  function pick(value) {
    var code = String(value || '').toLowerCase().slice(0, 2);
    return code === 'en' ? 'en' : code === 'pt' ? 'pt' : null;
  }

  function detect() {
    var chosen = null;
    try {
      chosen = pick(new URLSearchParams(window.location.search).get('lang'));
      if (chosen) localStorage.setItem(KEY, chosen);
      else chosen = pick(localStorage.getItem(KEY));
    } catch (_) { /* storage bloqueado: vale só o parâmetro desta carga */ }
    return chosen || 'pt';
  }

  var lang = detect();
  var english = lang === 'en';
  document.documentElement.lang = english ? 'en' : 'pt-BR';
  if (english) document.documentElement.classList.add('i18n-pending');

  var phrases = {};
  var patterns = [];
  var terms = window.U2_TERMS || {};
  var missing = {};
  var produced = {};   // o que já saiu em inglês: não é texto "sem tradução" se reaparecer
  var done = typeof WeakMap === 'function' ? new WeakMap() : null;

  function squash(text) { return String(text).replace(/\s+/g, ' ').trim(); }

  // mesma normalização de translation.py::_norm — sem acento, minúsculas, só letras e números
  function termKey(text) {
    return String(text).normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
      .replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
  }

  function lookup(core) {
    if (Object.prototype.hasOwnProperty.call(phrases, core)) return phrases[core];
    for (var i = 0; i < patterns.length; i++) {
      var rule = patterns[i];
      if (rule[0].test(core)) {
        return typeof rule[1] === 'function'
          ? core.replace(rule[0], function () { return rule[1].apply(null, arguments); })
          : core.replace(rule[0], rule[1]);
      }
    }
    var key = termKey(core);
    if (key && Object.prototype.hasOwnProperty.call(terms, key)) return terms[key];
    return null;
  }

  // Um pedaço de texto: frase, padrão ou termo; "Rótulo:" e "Rótulo…" valem o mesmo
  // que "Rótulo".
  function piece(core) {
    var found = lookup(core);
    if (found !== null) return found;
    var tail = core.match(/^(.*?)(\s*[:…]|\.\.\.)$/);
    if (tail && tail[1]) {
      var head = lookup(tail[1]);
      if (head !== null) return head + tail[2];
    }
    return null;
  }

  var SEPARATOR = /(\s*[·—]\s*|\s+\/\s+)/;

  function translate(text) {
    if (!english || text === null || text === undefined) return text;
    var raw = String(text);
    var core = squash(raw);
    if (!core || !/[A-Za-zÀ-ÿ]/.test(core) || produced[core]) return raw;
    var found = piece(core);
    if (found === null && SEPARATOR.test(core)) {
      // "LUBANGO · Site FM · PROEF", "Grupo / Tarefa", "Área — Cronograma": cada
      // pedaço é traduzido por si, e o que não tiver tradução fica como está
      var changed = false;
      found = core.split(SEPARATOR).map(function (part, index) {
        if (index % 2 === 1 || !/[A-Za-zÀ-ÿ]/.test(part)) return part;
        var out = piece(part);
        if (out === null) { if (!produced[part]) missing[part] = 1; return part; }
        changed = true;
        return out;
      }).join('');
      if (!changed) return raw;
    } else if (found === null) {
      missing[core] = 1;
      return raw;
    }
    produced[squash(found)] = 1;
    // mantém os espaços que cercavam o texto original (separam elementos vizinhos)
    return raw.match(/^\s*/)[0] + found + raw.match(/\s*$/)[0];
  }

  function skipped(element) {
    return !element || SKIP_TAGS[element.tagName] || (element.closest && element.closest(SKIP_SELECTOR));
  }

  function translateText(node) {
    if (skipped(node.parentElement)) return;
    var value = node.nodeValue;
    if (!value || (done && done.get(node) === value)) return;
    var out = translate(value);
    if (out !== value) node.nodeValue = out;
    if (done) done.set(node, out);
  }

  function translateAttributes(element) {
    if (skipped(element)) return;
    for (var i = 0; i < ATTRIBUTES.length; i++) {
      var name = ATTRIBUTES[i];
      if (!element.hasAttribute(name)) continue;
      var value = element.getAttribute(name);
      var out = translate(value);
      if (out !== value) element.setAttribute(name, out);
    }
  }

  function translateTree(root) {
    if (!root) return;
    if (root.nodeType === 3) { translateText(root); return; }
    if (root.nodeType !== 1 || SKIP_TAGS[root.tagName]) return;
    translateAttributes(root);
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, null);
    var node;
    while ((node = walker.nextNode())) {
      if (node.nodeType === 3) translateText(node);
      else translateAttributes(node);
    }
  }

  function start() {
    document.title = translate(document.title);
    translateTree(document.body);
    new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        var record = records[i];
        if (record.type === 'characterData') translateText(record.target);
        else if (record.type === 'attributes') translateAttributes(record.target);
        else for (var j = 0; j < record.addedNodes.length; j++) translateTree(record.addedNodes[j]);
      }
    }).observe(document.body, {
      childList: true, subtree: true, characterData: true,
      attributes: true, attributeFilter: ATTRIBUTES,
    });
    document.documentElement.classList.remove('i18n-pending');
  }

  // ── Seletor de idioma (PT | EN) ────────────────────────────────────────────
  function setLang(next) {
    next = pick(next) || 'pt';
    try { localStorage.setItem(KEY, next); } catch (_) {}
    // recarrega: os gráficos são desenhados em canvas e só mudam de idioma ao redesenhar
    var url = new URL(window.location.href);
    url.searchParams.set('lang', next);
    window.location.assign(url.pathname + url.search + url.hash);
  }

  function buildSwitch() {
    var host = document.querySelector('body > div > header') || document.querySelector('.mob-header');
    if (!host || document.getElementById('u2-lang')) return;
    var box = document.createElement('div');
    box.id = 'u2-lang';
    box.className = 'u2-lang';
    box.setAttribute('data-no-i18n', '');
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', english ? 'Language' : 'Idioma');
    ['pt', 'en'].forEach(function (code) {
      var button = document.createElement('button');
      button.type = 'button';
      button.textContent = code.toUpperCase();
      button.className = 'u2-lang-btn' + (code === lang ? ' u2-lang-active' : '');
      button.setAttribute('aria-pressed', code === lang ? 'true' : 'false');
      button.addEventListener('click', function () { if (code !== lang) setLang(code); });
      box.appendChild(button);
    });
    var chip = host.querySelector('.mob-sse-chip');
    if (chip) host.insertBefore(box, chip); else host.appendChild(box);
  }

  window.U2I18n = {
    lang: lang,
    t: translate,
    setLang: setLang,
    // i18n-en.js entrega o dicionário por aqui
    register: function (table, rules) {
      Object.keys(table || {}).forEach(function (key) { phrases[squash(key)] = table[key]; });
      patterns = patterns.concat(rules || []);
    },
    // textos vistos sem tradução (só em inglês) — para completar o dicionário
    missing: function () { return Object.keys(missing).sort(); },
  };

  function ready() {
    buildSwitch();
    if (english) {
      start();
      // os relatórios saem no idioma da interface, salvo se o utilizador trocar
      if (typeof window.setReportLang === 'function') {
        try { window.setReportLang('en'); } catch (_) {}
      }
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready);
  else ready();
})();
