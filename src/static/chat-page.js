/* chat-page.js — Lógica da página /assistente */
(() => {
  const STORAGE_KEY = 'u2chat_page_history';
  const MAX_HISTORY = 60;

  let _msgIndex = 0;
  const _chartInstances = {};

  // ── Helpers ──────────────────────────────────────────────────────────────

  function esc(str) {
    return String(str ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function mdToHtml(text) {
    const safe = String(text ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

    function inline(s) {
      return s
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code style="background:#f1f5f9;padding:1px 5px;border-radius:3px;font-size:11.5px;font-family:monospace">$1</code>');
    }

    const lines = safe.split('\n');
    const out = [];
    let listItems = [];

    function flushList() {
      if (!listItems.length) return;
      out.push('<ul style="margin:5px 0 5px 18px;list-style:disc">' +
        listItems.map(li => `<li style="margin:3px 0">${li}</li>`).join('') + '</ul>');
      listItems = [];
    }

    for (const line of lines) {
      if (/^### /.test(line)) {
        flushList();
        out.push(`<div style="font-weight:700;font-size:12.5px;margin:10px 0 3px;color:#1e293b">${inline(line.slice(4))}</div>`);
      } else if (/^## /.test(line)) {
        flushList();
        out.push(`<div style="font-weight:700;font-size:13px;margin:12px 0 4px;color:#0f172a;border-bottom:1px solid #e2e8f0;padding-bottom:3px">${inline(line.slice(3))}</div>`);
      } else if (/^# /.test(line)) {
        flushList();
        out.push(`<div style="font-weight:700;font-size:14px;margin:12px 0 4px;color:#0f172a">${inline(line.slice(2))}</div>`);
      } else if (/^[-*] /.test(line)) {
        listItems.push(inline(line.slice(2)));
      } else if (line.trim() === '') {
        flushList();
        out.push('<div style="height:5px"></div>');
      } else {
        flushList();
        out.push(`<div style="margin:2px 0">${inline(line)}</div>`);
      }
    }
    flushList();
    return out.join('');
  }

  function loadHistory() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); } catch { return []; }
  }

  function saveHistory(msgs) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(msgs.slice(-MAX_HISTORY))); } catch {}
  }

  function disposeChart(id) {
    if (_chartInstances[id]) {
      try { _chartInstances[id].dispose(); } catch {}
      delete _chartInstances[id];
    }
  }

  // ── Chart rendering ───────────────────────────────────────────────────────

  function renderChart(container, chart, chartId) {
    if (!chart?.type) return;
    container.style.marginTop = '12px';

    if (chart.type === 'kpi') {
      const grid = document.createElement('div');
      grid.className = 'kpi-grid';
      (chart.data || []).forEach(item => {
        const card = document.createElement('div');
        card.className = 'kpi-card';
        card.innerHTML = `<div class="kpi-value">${esc(String(item.value))}</div><div class="kpi-label">${esc(item.label)}</div>`;
        grid.appendChild(card);
      });
      container.appendChild(grid);
      return;
    }

    if (chart.type === 'table') {
      const d = chart.data || {};
      const headers = d.headers || [];
      const rows = d.rows || [];
      const wrap = document.createElement('div');
      wrap.className = 'chat-table-wrap';
      let html = `<table class="chat-table">`;
      html += '<thead><tr>' + headers.map(h => `<th>${esc(h)}</th>`).join('') + '</tr></thead>';
      html += '<tbody>' + rows.map((row, i) =>
        `<tr class="${i % 2 === 0 ? 'even' : 'odd'}">${row.map(c => `<td>${esc(String(c ?? ''))}</td>`).join('')}</tr>`
      ).join('') + '</tbody></table>';
      wrap.innerHTML = html;
      container.appendChild(wrap);
      return;
    }

    // ECharts: bar / pie / line
    const el = document.createElement('div');
    el.className = 'chart-canvas';
    container.appendChild(el);
    disposeChart(chartId);
    const inst = echarts.init(el);
    _chartInstances[chartId] = inst;

    let opt = {
      title: { text: chart.title || '', textStyle: { fontSize: 13, fontWeight: 600, color: '#1e293b' } },
      tooltip: { trigger: chart.type === 'pie' ? 'item' : 'axis' },
      animation: true,
    };

    if (chart.type === 'pie') {
      opt.series = [{ type: 'pie', radius: ['35%', '65%'], data: chart.data || [], label: { fontSize: 11 } }];
      opt.legend = { orient: 'vertical', right: '5%', top: 'center', textStyle: { fontSize: 11 } };
    }

    if (chart.type === 'bar') {
      const d = chart.data || {};
      const cats = d.categories || [];
      const isHoriz = cats.length > 5 || cats.some(c => c.length > 12);
      const series = (d.series || []).map(s => ({
        name: s.name,
        type: 'bar',
        data: s.data,
        stack: d.stacked ? 'total' : undefined,
        barMaxWidth: 40,
        label: !d.stacked && cats.length <= 10 ? {
          show: true,
          position: isHoriz ? 'right' : 'top',
          formatter: v => `${v}%`,
          fontSize: 10,
        } : undefined,
      }));

      if (isHoriz) {
        opt.xAxis = { type: 'value', axisLabel: { fontSize: 10 } };
        opt.yAxis = { type: 'category', data: cats, axisLabel: { fontSize: 10, width: 130, overflow: 'truncate' } };
        opt.grid = { left: 145, right: 60, top: 50, bottom: 16 };
      } else {
        opt.xAxis = { type: 'category', data: cats, axisLabel: { fontSize: 10 } };
        opt.yAxis = { type: 'value', axisLabel: { fontSize: 10, formatter: v => `${v}%` } };
        opt.grid = { left: 50, right: 20, top: 50, bottom: 36 };
      }
      opt.series = series;
      if (d.stacked) opt.legend = { bottom: 4, textStyle: { fontSize: 10 } };
    }

    if (chart.type === 'line') {
      const seriesData = chart.data?.series || [];
      const allDates = [...new Set(seriesData.flatMap(s => (s.points || []).map(p => p.date)))].sort();
      opt.xAxis = { type: 'category', data: allDates, axisLabel: { fontSize: 10, rotate: 30 } };
      opt.yAxis = { type: 'value', min: 0, max: 100, axisLabel: { fontSize: 10, formatter: v => `${v}%` } };
      opt.grid = { left: 50, right: 20, top: 50, bottom: 60 };
      opt.legend = { bottom: 4, textStyle: { fontSize: 10 } };
      opt.series = seriesData.map(s => {
        const map = Object.fromEntries((s.points || []).map(p => [p.date, p.value]));
        return { name: s.name, type: 'line', smooth: true, symbol: 'none', data: allDates.map(d => map[d] ?? null), connectNulls: false };
      });
    }

    inst.setOption(opt);
    window.addEventListener('resize', () => inst.resize());
  }

  // ── Message rendering ─────────────────────────────────────────────────────

  function appendMessage(role, text, chart, save = true) {
    const id = ++_msgIndex;
    const isUser = role === 'user';
    const msgs = document.getElementById('chat-messages');
    const welcome = document.getElementById('chat-welcome');
    if (welcome) welcome.classList.add('hidden');
    msgs.classList.remove('hidden');

    const wrap = document.createElement('div');
    wrap.className = `msg-wrap ${isUser ? 'msg-user' : 'msg-bot'}`;

    if (!isUser) {
      const avatar = document.createElement('div');
      avatar.className = 'msg-avatar';
      avatar.innerHTML = `<svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="white" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z"/></svg>`;
      wrap.appendChild(avatar);
    }

    const bubble = document.createElement('div');
    bubble.className = `msg-bubble ${isUser ? 'bubble-user' : 'bubble-bot'}`;

    const textDiv = document.createElement('div');
    textDiv.innerHTML = isUser ? esc(text).replace(/\n/g, '<br>') : mdToHtml(text);
    bubble.appendChild(textDiv);

    wrap.appendChild(bubble);
    msgs.appendChild(wrap);
    msgs.scrollTop = msgs.scrollHeight;

    if (!isUser && chart) renderChart(bubble, chart, `pc-${id}`);

    if (save) {
      const history = loadHistory();
      history.push({ role, text, chart: chart || null });
      saveHistory(history);
    }
  }

  function showTyping() {
    const el = document.createElement('div');
    el.id = 'chat-typing';
    el.className = 'msg-wrap msg-bot';
    el.innerHTML = `<div class="msg-avatar"><svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="white" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z"/></svg></div>
    <div class="msg-bubble bubble-bot typing-bubble"><span></span><span></span><span></span></div>`;
    document.getElementById('chat-messages').appendChild(el);
    document.getElementById('chat-messages').scrollTop = 99999;
  }

  function removeTyping() {
    document.getElementById('chat-typing')?.remove();
  }

  // ── Send ──────────────────────────────────────────────────────────────────

  async function send(msg) {
    if (!msg) return;
    const input = document.getElementById('chat-input');
    const btn = document.getElementById('chat-send');
    input.value = '';
    input.style.height = 'auto';
    btn.disabled = true;

    appendMessage('user', msg);
    showTyping();

    try {
      const res = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg }),
      });
      const json = await res.json();
      removeTyping();
      appendMessage('bot', json.text || 'Sem resposta.', json.chart || null);
    } catch {
      removeTyping();
      appendMessage('bot', 'Erro de comunicação. Verifique a conexão e tente novamente.');
    } finally {
      btn.disabled = false;
      input.focus();
    }
  }

  // ── Init ──────────────────────────────────────────────────────────────────

  function clearHistory() {
    if (!confirm('Limpar todo o histórico de conversa?')) return;
    localStorage.removeItem(STORAGE_KEY);
    const msgs = document.getElementById('chat-messages');
    msgs.innerHTML = '';
    msgs.classList.add('hidden');
    Object.keys(_chartInstances).forEach(disposeChart);
    document.getElementById('chat-welcome')?.classList.remove('hidden');
    _msgIndex = 0;
  }

  function restoreHistory() {
    const history = loadHistory();
    if (history.length === 0) return;
    history.forEach(m => appendMessage(m.role, m.text, m.chart || null, false));
  }

  document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('chat-input');
    const btn = document.getElementById('chat-send');
    const clearBtn = document.getElementById('chat-clear');

    btn.addEventListener('click', () => send(input.value.trim()));
    clearBtn.addEventListener('click', clearHistory);

    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input.value.trim()); }
    });
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });

    // Sugestões
    document.querySelectorAll('[data-query]').forEach(el => {
      el.addEventListener('click', () => send(el.dataset.query));
    });

    restoreHistory();
    input.focus();
  });
})();
