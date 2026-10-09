/* Modo embutido — a app aberta dentro de um iframe (Nextcloud › External sites).

   Fora de um iframe este arquivo não muda nada: o layout com a barra lateral e os
   diálogos nativos continuam exatamente como sempre foram.

   Dentro de um iframe a moldura já é do Nextcloud (barra superior, marca, menu de
   apps), então:
     • a barra lateral vira um painel "Relatórios" que desliza pela direita;
     • a navegação entre páginas sobe para a barra do topo, em abas;
     • prompt()/confirm() dão lugar a um diálogo da própria página — dentro de um
       iframe de outra origem os nativos aparecem como "uma página incorporada
       diz…" e há navegadores que os bloqueiam.

   `?embed=1` força o modo (para testar sem iframe) e `?embed=0` desliga; a escolha
   vale até fechar a aba. */
(function () {
  'use strict';

  var KEY = 'u2-embed';

  function detect() {
    var forced = null;
    try {
      var param = new URLSearchParams(window.location.search).get('embed');
      if (param === '1' || param === '0') {
        forced = param;
        sessionStorage.setItem(KEY, param);
      } else {
        forced = sessionStorage.getItem(KEY);
      }
    } catch (_) { /* storage bloqueado: segue só com a detecção */ }
    if (forced === '1') return true;
    if (forced === '0') return false;
    try { return window.self !== window.top; } catch (_) { return true; }
  }

  var embedded = detect();
  if (embedded) document.documentElement.classList.add('embed');

  // ── Diálogos ───────────────────────────────────────────────────────────────

  function modal(message, options) {
    return new Promise(function (resolve) {
      var overlay = document.createElement('div');
      overlay.className = 'u2-dialog-overlay';
      overlay.innerHTML =
        '<div class="u2-dialog" role="dialog" aria-modal="true">' +
          '<p class="u2-dialog-message"></p>' +
          (options.input ? '<input class="u2-dialog-input" autocomplete="off" />' : '') +
          '<div class="u2-dialog-actions">' +
            '<button type="button" class="u2-dialog-btn" data-act="cancel">Cancelar</button>' +
            '<button type="button" class="u2-dialog-btn u2-dialog-btn-primary" data-act="ok">' +
              (options.okLabel || 'Confirmar') + '</button>' +
          '</div>' +
        '</div>';
      overlay.querySelector('.u2-dialog-message').textContent = message;
      var input = overlay.querySelector('.u2-dialog-input');
      if (input) input.type = options.password ? 'password' : 'text';

      function close(value) {
        document.removeEventListener('keydown', onKey, true);
        overlay.remove();
        resolve(value);
      }
      function accept() { close(input ? input.value : true); }
      function cancel() { close(input ? null : false); }
      function onKey(event) {
        if (event.key === 'Escape') { event.stopPropagation(); cancel(); }
        if (event.key === 'Enter') { event.stopPropagation(); accept(); }
      }
      overlay.addEventListener('click', function (event) {
        var act = event.target.getAttribute && event.target.getAttribute('data-act');
        if (act === 'ok') accept();
        else if (act === 'cancel' || event.target === overlay) cancel();
      });
      document.addEventListener('keydown', onKey, true);
      document.body.appendChild(overlay);
      (input || overlay.querySelector('[data-act="ok"]')).focus();
    });
  }

  // Mesmos contratos de prompt()/confirm(), só que assíncronos: prompt devolve o
  // texto ou null; confirm devolve true/false.
  window.U2Dialog = {
    prompt: function (message, options) {
      options = options || {};
      if (!embedded) return Promise.resolve(window.prompt(message));
      return modal(message, { input: true, password: !!options.password });
    },
    confirm: function (message, options) {
      options = options || {};
      if (!embedded) return Promise.resolve(window.confirm(message));
      return modal(message, { okLabel: options.okLabel });
    },
  };
  window.U2Embed = { active: embedded };

  if (!embedded) return;

  // ── Layout de desktop: abas no topo + painel de relatórios ────────────────

  var REPORTS_ICON =
    '<svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">' +
    '<path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m.75 12 3 3m0 0 3-3m-3 3v-6m-1.5-9H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"/></svg>';
  var EXTERNAL_ICON =
    '<svg width="11" height="11" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">' +
    '<path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25"/></svg>';

  function setPanel(open) {
    document.documentElement.classList.toggle('embed-panel-open', open);
    var button = document.getElementById('embed-reports-btn');
    if (button) button.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  function buildDesktop() {
    var aside = document.querySelector('body > aside');
    var header = document.querySelector('body > div > header');
    if (!aside || !header) return;   // página sem a barra lateral (mobile, RDO…)
    var nav = aside.querySelector('nav');
    if (!nav) return;

    // Tudo que vem antes do bloco "Relatórios" é navegação: sobe para as abas.
    var reportsHeading = null;
    var langButton = nav.querySelector('#lang-pt');
    Array.prototype.forEach.call(nav.children, function (child) {
      if (langButton && child.contains(langButton)) reportsHeading = child;
    });

    var tabs = document.createElement('nav');
    tabs.className = 'embed-tabs';
    tabs.setAttribute('aria-label', 'Páginas');
    var path = window.location.pathname.replace(/\/+$/, '') || '/';
    for (var i = 0; i < nav.children.length; i++) {
      var child = nav.children[i];
      if (child === reportsHeading) break;
      child.classList.add('embed-hidden');
      if (child.tagName !== 'A') continue;
      var tab = document.createElement('a');
      var href = child.getAttribute('href') || '#';
      var external = /^https?:/i.test(href);
      tab.href = href;
      tab.className = 'embed-tab';
      tab.textContent = child.textContent.trim();
      if (external) {
        tab.target = '_blank';
        tab.rel = 'noopener noreferrer';
        tab.insertAdjacentHTML('beforeend', EXTERNAL_ICON);
      } else if ((href.replace(/\/+$/, '') || '/') === path) {
        tab.classList.add('embed-tab-active');
        tab.setAttribute('aria-current', 'page');
      }
      tabs.appendChild(tab);
    }
    if (reportsHeading) reportsHeading.classList.add('embed-first');

    var button = document.createElement('button');
    button.type = 'button';
    button.id = 'embed-reports-btn';
    button.className = 'embed-reports-btn';
    button.setAttribute('aria-expanded', 'false');
    button.innerHTML = REPORTS_ICON + '<span>Relatórios</span>';
    button.addEventListener('click', function () {
      setPanel(!document.documentElement.classList.contains('embed-panel-open'));
    });

    header.classList.add('embed-header');
    header.insertBefore(tabs, header.firstChild);
    header.appendChild(button);

    var panelTitle = document.createElement('div');
    panelTitle.className = 'embed-panel-title';
    panelTitle.innerHTML = '<span>Relatórios</span>' +
      '<button type="button" class="embed-panel-close" aria-label="Fechar">&times;</button>';
    panelTitle.querySelector('button').addEventListener('click', function () { setPanel(false); });
    aside.insertBefore(panelTitle, aside.firstChild);
    aside.classList.add('embed-panel');

    var backdrop = document.createElement('div');
    backdrop.className = 'embed-backdrop';
    backdrop.addEventListener('click', function () { setPanel(false); });
    document.body.appendChild(backdrop);

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') setPanel(false);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', buildDesktop);
  } else {
    buildDesktop();
  }
})();
