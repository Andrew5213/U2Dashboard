/* Chat AI Widget — U2 Broadcast Dashboard
 * Namespace isolado: ChatWidget / ChatCharts
 * Não interfere com app.js, charts.js nem Charts.disposeAll()
 */
const ChatWidget = (() => {
  const STORAGE_KEY = 'u2chat_history';
  const MAX_HISTORY = 40;

  let _panel = null;
  let _msgList = null;
  let _input = null;
  let _sendBtn = null;
  let _open = false;
  let _msgIndex = 0;

  // Instâncias ECharts gerenciadas pelo chat (separadas do Charts global)
  const ChatCharts = { _instances: {} };
  ChatCharts.init = (el, id) => {
    ChatCharts.dispose(id);
    const inst = echarts.init(el);
    ChatCharts._instances[id] = inst;
    return inst;
  };
  ChatCharts.dispose = (id) => {
    if (ChatCharts._instances[id]) {
      try { ChatCharts._instances[id].dispose(); } catch (_) {}
      delete ChatCharts._instances[id];
    }
  };
  ChatCharts.disposeAll = () => {
    Object.keys(ChatCharts._instances).forEach(ChatCharts.dispose);
  };

  function _loadHistory() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); } catch (_) { return []; }
  }
  function _saveHistory(msgs) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(msgs.slice(-MAX_HISTORY))); } catch (_) {}
  }

  function _escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function _renderChart(container, chart, chartId) {
    if (!chart || !chart.type) return;
    container.style.marginTop = '10px';

    if (chart.type === 'kpi') {
      const grid = document.createElement('div');
      grid.style.cssText = 'display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:8px;';
      (chart.data || []).forEach(item => {
        const card = document.createElement('div');
        card.style.cssText = 'background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;text-align:center;';
        card.innerHTML = `<div style="font-size:18px;font-weight:700;color:#1e40af;">${_escapeHtml(String(item.value))}</div><div style="font-size:10px;color:#64748b;margin-top:2px;">${_escapeHtml(item.label)}</div>`;
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
      wrap.style.cssText = 'overflow-x:auto;margin-top:8px;max-height:260px;overflow-y:auto;';
      let html = `<p style="font-size:11px;font-weight:600;color:#374151;margin-bottom:4px;">${_escapeHtml(chart.title || '')}</p>`;
      html += '<table style="width:100%;border-collapse:collapse;font-size:11px;">';
      html += '<thead><tr>' + headers.map(h => `<th style="background:#f1f5f9;padding:4px 8px;text-align:left;border-bottom:1px solid #e2e8f0;white-space:nowrap;">${_escapeHtml(h)}</th>`).join('') + '</tr></thead>';
      html += '<tbody>' + rows.map((row, i) =>
        `<tr style="background:${i % 2 === 0 ? '#fff' : '#f8fafc'};">${row.map(cell => `<td style="padding:4px 8px;border-bottom:1px solid #f1f5f9;white-space:nowrap;">${_escapeHtml(String(cell ?? ''))}</td>`).join('')}</tr>`
      ).join('') + '</tbody></table>';
      wrap.innerHTML = html;
      container.appendChild(wrap);
      return;
    }

    // ECharts: bar / pie / line
    const chartEl = document.createElement('div');
    chartEl.style.cssText = 'width:100%;height:220px;margin-top:8px;';
    container.appendChild(chartEl);
    const inst = ChatCharts.init(chartEl, chartId);

    let option = { title: { text: chart.title || '', textStyle: { fontSize: 11, fontWeight: 600 } }, tooltip: {}, animation: false };

    if (chart.type === 'pie') {
      option.series = [{ type: 'pie', radius: '60%', data: chart.data || [], label: { fontSize: 10 } }];
      option.legend = { orient: 'vertical', right: 0, top: 'center', textStyle: { fontSize: 10 } };
    }

    if (chart.type === 'bar') {
      const d = chart.data || {};
      const cats = d.categories || [];
      const series = (d.series || []).map(s => ({
        name: s.name,
        type: 'bar',
        data: s.data,
        stack: d.stacked ? 'total' : undefined,
        label: !d.stacked ? { show: cats.length <= 8, position: 'right', formatter: v => `${v}%`, fontSize: 10 } : undefined,
      }));
      const isHorizontal = cats.length > 4 || cats.some(c => c.length > 10);
      if (isHorizontal) {
        option.xAxis = { type: 'value', axisLabel: { fontSize: 9 } };
        option.yAxis = { type: 'category', data: cats, axisLabel: { fontSize: 9, width: 100, overflow: 'truncate' } };
        option.grid = { left: 110, right: 20, top: 36, bottom: 10 };
        series.forEach(s => { if (s.label) s.label.position = 'right'; });
      } else {
        option.xAxis = { type: 'category', data: cats, axisLabel: { fontSize: 9 } };
        option.yAxis = { type: 'value', axisLabel: { fontSize: 9, formatter: v => `${v}%` } };
        option.grid = { left: 40, right: 10, top: 36, bottom: 30 };
      }
      option.series = series;
      if (d.stacked) option.legend = { bottom: 0, textStyle: { fontSize: 9 } };
    }

    if (chart.type === 'line') {
      const seriesData = (chart.data?.series || []);
      const allDates = [...new Set(seriesData.flatMap(s => s.points?.map(p => p.date) || []))].sort();
      option.xAxis = { type: 'category', data: allDates, axisLabel: { fontSize: 9, rotate: 30 } };
      option.yAxis = { type: 'value', min: 0, max: 100, axisLabel: { fontSize: 9, formatter: v => `${v}%` } };
      option.grid = { left: 40, right: 10, top: 36, bottom: 50 };
      option.legend = { bottom: 0, textStyle: { fontSize: 9 } };
      option.series = seriesData.map(s => {
        const map = Object.fromEntries((s.points || []).map(p => [p.date, p.value]));
        return { name: s.name, type: 'line', smooth: true, data: allDates.map(d => map[d] ?? null), connectNulls: false };
      });
    }

    inst.setOption(option);
  }

  function _appendMessage(role, text, chart, save = true) {
    const id = ++_msgIndex;
    const isUser = role === 'user';

    const wrap = document.createElement('div');
    wrap.style.cssText = `display:flex;flex-direction:column;align-items:${isUser ? 'flex-end' : 'flex-start'};margin-bottom:12px;`;

    const bubble = document.createElement('div');
    bubble.style.cssText = `max-width:88%;padding:9px 12px;border-radius:12px;font-size:12.5px;line-height:1.5;word-break:break-word;` +
      (isUser ? 'background:#1e40af;color:#fff;border-bottom-right-radius:3px;' : 'background:#f1f5f9;color:#1e293b;border-bottom-left-radius:3px;');

    // Text — convert newlines to <br>
    const textDiv = document.createElement('div');
    textDiv.innerHTML = _escapeHtml(text).replace(/\n/g, '<br>');
    bubble.appendChild(textDiv);

    // Chart
    if (!isUser && chart) {
      _renderChart(bubble, chart, `chat-chart-${id}`);
    }

    wrap.appendChild(bubble);
    _msgList.appendChild(wrap);
    _msgList.scrollTop = _msgList.scrollHeight;

    if (save) {
      const history = _loadHistory();
      history.push({ role, text, chart: chart || null });
      _saveHistory(history);
    }
  }

  function _appendThinking() {
    const el = document.createElement('div');
    el.id = 'chat-thinking';
    el.style.cssText = 'display:flex;align-items:flex-start;margin-bottom:12px;';
    el.innerHTML = `<div style="background:#f1f5f9;padding:8px 12px;border-radius:12px;border-bottom-left-radius:3px;font-size:12px;color:#64748b;">
      <span style="display:inline-flex;gap:3px;align-items:center;">
        <span style="animation:bounce 1s infinite 0s" class="dot">●</span>
        <span style="animation:bounce 1s infinite .2s" class="dot">●</span>
        <span style="animation:bounce 1s infinite .4s" class="dot">●</span>
      </span>
    </div>`;
    _msgList.appendChild(el);
    _msgList.scrollTop = _msgList.scrollHeight;
  }

  function _removeThinking() {
    const el = document.getElementById('chat-thinking');
    if (el) el.remove();
  }

  async function _send() {
    const msg = _input.value.trim();
    if (!msg) return;
    _input.value = '';
    _input.style.height = 'auto';
    _sendBtn.disabled = true;

    _appendMessage('user', msg);
    _appendThinking();

    try {
      const res = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg }),
      });
      const json = await res.json();
      _removeThinking();
      _appendMessage('bot', json.text || 'Sem resposta.', json.chart || null);
    } catch (err) {
      _removeThinking();
      _appendMessage('bot', 'Erro de comunicação com o assistente. Verifique a conexão.');
    } finally {
      _sendBtn.disabled = false;
      _input.focus();
    }
  }

  function _clearHistory() {
    localStorage.removeItem(STORAGE_KEY);
    _msgList.innerHTML = '';
    _msgIndex = 0;
    ChatCharts.disposeAll();
    _appendMessage('bot', 'Histórico limpo. Como posso ajudar?', null, false);
  }

  function _buildPanel() {
    // Inject bounce animation
    if (!document.getElementById('chat-style')) {
      const style = document.createElement('style');
      style.id = 'chat-style';
      style.textContent = `
        @keyframes bounce { 0%,80%,100%{transform:translateY(0)} 40%{transform:translateY(-5px)} }
        #chat-panel { transition: transform .25s ease, opacity .25s ease; }
        #chat-panel.hidden-panel { transform: translateX(100%); opacity: 0; pointer-events: none; }
      `;
      document.head.appendChild(style);
    }

    _panel = document.createElement('div');
    _panel.id = 'chat-panel';
    _panel.className = 'hidden-panel';
    _panel.style.cssText = 'position:fixed;top:0;right:0;width:380px;max-width:95vw;height:100vh;background:#fff;box-shadow:-4px 0 24px rgba(0,0,0,.12);z-index:9999;display:flex;flex-direction:column;';

    // Header
    const header = document.createElement('div');
    header.style.cssText = 'padding:14px 16px;border-bottom:1px solid #e2e8f0;display:flex;align-items:center;justify-content:space-between;background:#1e40af;';
    header.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;">
        <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="white" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z"/>
        </svg>
        <span style="color:#fff;font-size:13.5px;font-weight:600;">Assistente U2</span>
      </div>
      <div style="display:flex;gap:6px;align-items:center;">
        <button id="chat-clear-btn" title="Limpar histórico" style="background:rgba(255,255,255,.15);border:none;border-radius:6px;padding:4px 8px;cursor:pointer;color:#fff;font-size:11px;">Limpar</button>
        <button id="chat-close-btn" title="Fechar" style="background:rgba(255,255,255,.15);border:none;border-radius:6px;padding:4px 8px;cursor:pointer;color:#fff;font-size:11px;">✕</button>
      </div>
    `;
    _panel.appendChild(header);

    // Message list
    _msgList = document.createElement('div');
    _msgList.id = 'chat-messages';
    _msgList.style.cssText = 'flex:1;overflow-y:auto;padding:14px 12px;display:flex;flex-direction:column;';
    _panel.appendChild(_msgList);

    // Input area
    const inputWrap = document.createElement('div');
    inputWrap.style.cssText = 'padding:10px 12px;border-top:1px solid #e2e8f0;display:flex;gap:8px;align-items:flex-end;background:#fafafa;';

    _input = document.createElement('textarea');
    _input.id = 'chat-input';
    _input.placeholder = 'Pergunte sobre o progresso... (/ para focar)';
    _input.rows = 1;
    _input.style.cssText = 'flex:1;resize:none;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;font-size:12.5px;outline:none;max-height:100px;overflow-y:auto;font-family:inherit;background:#fff;';
    _input.addEventListener('input', () => {
      _input.style.height = 'auto';
      _input.style.height = Math.min(_input.scrollHeight, 100) + 'px';
    });
    _input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); _send(); }
    });

    _sendBtn = document.createElement('button');
    _sendBtn.style.cssText = 'background:#1e40af;color:#fff;border:none;border-radius:8px;padding:8px 14px;font-size:12px;cursor:pointer;white-space:nowrap;font-weight:600;flex-shrink:0;';
    _sendBtn.textContent = 'Enviar';
    _sendBtn.addEventListener('click', _send);

    inputWrap.appendChild(_input);
    inputWrap.appendChild(_sendBtn);
    _panel.appendChild(inputWrap);

    document.body.appendChild(_panel);

    // Overlay (clique fora fecha)
    const overlay = document.createElement('div');
    overlay.id = 'chat-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.15);z-index:9998;display:none;';
    overlay.addEventListener('click', close);
    document.body.appendChild(overlay);

    // Botões do header do painel
    document.getElementById('chat-close-btn').addEventListener('click', close);
    document.getElementById('chat-clear-btn').addEventListener('click', _clearHistory);

    // Atalho /
    document.addEventListener('keydown', e => {
      if (e.key === '/' && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
        e.preventDefault();
        open();
        setTimeout(() => _input.focus(), 50);
      }
      if (e.key === 'Escape' && _open) close();
    });
  }

  function _restoreHistory() {
    const history = _loadHistory();
    history.forEach(m => _appendMessage(m.role, m.text, m.chart || null, false));
    if (history.length === 0) {
      _appendMessage('bot', 'Olá! Posso responder perguntas sobre o progresso das províncias, tarefas e equipes. Experimente: "Qual o progresso da província Kuito?"', null, false);
    }
  }

  function open() {
    if (!_panel) {
      _buildPanel();
      _restoreHistory();
    }
    _panel.classList.remove('hidden-panel');
    document.getElementById('chat-overlay').style.display = 'block';
    _open = true;
    setTimeout(() => _input && _input.focus(), 100);
  }

  function close() {
    if (_panel) _panel.classList.add('hidden-panel');
    const ov = document.getElementById('chat-overlay');
    if (ov) ov.style.display = 'none';
    _open = false;
  }

  function toggle() {
    _open ? close() : open();
  }

  return { open, close, toggle };
})();
