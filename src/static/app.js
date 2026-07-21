/* Dashboard SPA — roteador hash-based */
(function () {
  /* ── Estado de navegação ─────────────────────────────────────────── */
  const nav = { folderId: null, folderName: null, listId: null, listName: null };

  /* ── Ícones SVG (Heroicons outline) ─────────────────────────────── */
  const ICONS = {
    tasks:    `<svg class="w-6 h-6 text-gray-400" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2M9 5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2M9 5a2 2 0 0 0 2-2h2a2 2 0 0 0 2 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"/></svg>`,
    check:    `<svg class="w-6 h-6 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/></svg>`,
    chartBar: `<svg class="w-6 h-6 text-red-600" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z"/></svg>`,
    clock:    `<svg class="w-6 h-6 text-red-400" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/></svg>`,
    calendar: `<svg class="w-6 h-6 text-gray-400" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5"/></svg>`,
    folder:   `<svg class="w-6 h-6 text-amber-400" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 0 1 4.5 9.75h15A2.25 2.25 0 0 1 21.75 12v.75m-8.69-6.44-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 1-1.06-.44Z"/></svg>`,
    sync:     `<svg class="w-6 h-6 text-blue-400" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99"/></svg>`,
  };
  const WARN_ICON = `<svg class="w-3.5 h-3.5 inline-block align-text-bottom shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"/></svg>`;

  /* ── Semáforo de saúde da província ─────────────────────────────── */
  function healthStatus(rate, overdue) {
    if (overdue > 0)
      return { border: 'border-l-red-400',   dot: 'bg-red-500',     badge: 'bg-red-50 text-red-600',     label: 'Em risco' };
    if (rate < 0.1)
      return { border: 'border-l-amber-300', dot: 'bg-amber-400',   badge: 'bg-amber-50 text-amber-700', label: 'Atenção' };
    return   { border: 'border-l-emerald-400', dot: 'bg-emerald-500', badge: 'bg-emerald-50 text-emerald-700', label: 'No prazo' };
  }

  /* ── Utilitários ─────────────────────────────────────────────────── */
  function esc(str) {
    return String(str || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function fmtDate(iso) {
    if (!iso) return '—';
    try {
      return new Date(iso).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' });
    } catch (_) { return iso; }
  }

  function fmtPct(rate) {
    return Math.round((rate || 0) * 100) + '%';
  }

  function progressBar(rate, colorClass) {
    const pct = Math.round((rate || 0) * 100);
    const cls = colorClass || (pct >= 80 ? 'bg-emerald-400' : pct >= 40 ? 'bg-amber-400' : 'bg-red-400');
    return `<div class="w-full bg-gray-100 rounded-full h-1.5 mt-1">
      <div class="progress-bar h-1.5 rounded-full ${cls}" style="width:${pct}%"></div>
    </div>`;
  }

  function statusBadge(status, statusType, color) {
    const bg = color ? color + '22' : '#e2e8f014';
    const fg = color || '#64748b';
    const dot = `<span style="background:${fg}" class="w-1.5 h-1.5 rounded-full inline-block"></span>`;
    return `<span class="status-badge" style="background:${bg};color:${fg}">${dot}${esc(status || 'sem status')}</span>`;
  }

  function showToast(msg, type) {
    const el = document.getElementById('toast');
    if (!el) return;
    const colors = { success: 'bg-emerald-50 text-emerald-800 border border-emerald-200',
                     error:   'bg-red-50 text-red-800 border border-red-200',
                     info:    'bg-blue-50 text-blue-800 border border-blue-200' };
    el.className = 'fixed bottom-5 right-5 z-50 toast ' + (colors[type] || colors.info);
    el.textContent = msg;
    el.classList.remove('hidden');
    setTimeout(function () { el.classList.add('hidden'); }, 3500);
  }

  function setView(html) {
    Charts.disposeAll();
    const view = document.getElementById('view');
    view.innerHTML = html;
  }

  function setBreadcrumb(parts) {
    const el = document.getElementById('breadcrumb');
    if (!el) return;
    el.innerHTML = parts.map(function (p, i) {
      const isLast = i === parts.length - 1;
      if (isLast) return `<span class="text-gray-800 font-medium">${esc(p.label)}</span>`;
      return `<a href="${esc(p.href)}" class="hover:text-red-600 transition-colors">${esc(p.label)}</a>
              <span class="mx-1.5 text-gray-300">/</span>`;
    }).join('');
  }

  function setLastRefresh(iso) {
    const el = document.getElementById('last-refresh');
    if (!el || !iso) return;
    el.textContent = 'Atualizado ' + fmtDate(iso);
  }

  /* ── Fetch helper ────────────────────────────────────────────────── */
  async function api(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const json = await res.json();
    if (!json.success) throw new Error(json.error || 'Erro desconhecido');
    return json.data;
  }

  /* ── Loading state ───────────────────────────────────────────────── */
  function loading() {
    setView(`<div class="flex items-center justify-center h-64">
      <svg class="animate-spin w-7 h-7 text-red-500" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"></path>
      </svg>
    </div>`);
  }

  /* ── KPI card ────────────────────────────────────────────────────── */
  function kpiCard(icon, label, value, sub, color) {
    return `<div class="bg-white rounded-xl border border-gray-200 p-4 flex items-start gap-3">
      <div class="shrink-0 mt-0.5">${icon}</div>
      <div>
        <p class="text-xs text-gray-500 font-medium uppercase tracking-wide">${esc(label)}</p>
        <p class="text-2xl font-bold ${color || 'text-gray-800'} leading-tight">${esc(String(value))}</p>
        ${sub ? `<p class="text-xs text-gray-400 mt-0.5">${esc(String(sub))}</p>` : ''}
      </div>
    </div>`;
  }

  /* ── VIEW: Overview ──────────────────────────────────────────────── */
  async function renderOverview() {
    loading();
    setBreadcrumb([{ label: 'Visão Geral', href: '#/' }]);

    let overview, folders, assignees, upcoming, evolution;
    try {
      [overview, folders, assignees, upcoming, evolution] = await Promise.all([
        api('/dashboard/overview'),
        api('/dashboard/folders'),
        api('/dashboard/assignees'),
        api('/dashboard/upcoming?days=30'),
        api('/dashboard/evolution'),
      ]);
    } catch (e) {
      setView(`<div class="text-red-500 text-center py-12">Erro ao carregar dados: ${esc(e.message)}</div>`);
      return;
    }

    setLastRefresh(overview.last_refresh_at);

    const pct = fmtPct(overview.completion_rate);
    const overdueColor = overview.overdue_tasks > 0 ? 'text-red-600' : 'text-gray-800';

    const foldersHTML = folders.map(function (f) {
      const h = healthStatus(f.completion_rate, f.overdue_tasks);
      return `<div class="bg-white rounded-xl border border-gray-200 border-l-4 ${h.border} p-4 card-hover cursor-pointer"
               onclick="location.hash='#/folder/${esc(f.folder_id)}'; window.__folderName='${esc(f.name)}'">
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full ${h.dot} shrink-0"></span>
            <p class="font-semibold text-gray-800 truncate">${esc(f.name)}</p>
          </div>
          <span class="text-xs font-medium px-2 py-0.5 rounded-full ${h.badge} shrink-0">${h.label}</span>
        </div>
        <p class="text-xs text-gray-400 mt-1.5 ml-4">${f.total_lists} área(s) · ${f.total_tasks} task(s) · ${fmtPct(f.completion_rate)} concluído</p>
        ${progressBar(f.completion_rate)}
        ${f.overdue_tasks > 0 ? `<p class="text-xs text-red-500 mt-2 flex items-center gap-1">${WARN_ICON} ${f.overdue_tasks} em atraso</p>` : ''}
      </div>`;
    }).join('');

    const upcomingIn7  = upcoming.filter(function (t) { return new Date(t.due_date) <= new Date(Date.now() + 7 * 86400000); });
    const upcomingRows = function (list) {
      if (!list.length) return `<p class="text-sm text-gray-400 py-4 text-center">Nenhuma tarefa vencendo neste período.</p>`;
      return list.map(function (t) {
        const days = Math.ceil((new Date(t.due_date) - Date.now()) / 86400000);
        const urgCls = days <= 2 ? 'text-red-600 font-semibold' : days <= 7 ? 'text-amber-600' : 'text-gray-500';
        const dot = days <= 2 ? 'bg-red-500' : days <= 7 ? 'bg-amber-400' : 'bg-slate-300';
        return `<div class="flex items-center justify-between py-2.5 border-b border-gray-100 last:border-0 gap-3">
          <div class="flex items-center gap-2 min-w-0">
            <span class="w-2 h-2 rounded-full ${dot} shrink-0"></span>
            <div class="min-w-0">
              <p class="text-sm text-gray-800 truncate font-medium">${esc(t.name)}</p>
              <p class="text-xs text-gray-400">${esc(t.folder_name)} · ${esc(t.list_name)}${t.assignees.length ? ' · ' + esc(t.assignees.join(', ')) : ''}</p>
            </div>
          </div>
          <span class="text-xs shrink-0 ${urgCls}">${days === 0 ? 'Hoje' : days === 1 ? 'Amanhã' : 'em ' + days + 'd'}</span>
        </div>`;
      }).join('');
    };

    setView(`
      <!-- KPIs -->
      <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-6">
        ${kpiCard(ICONS.tasks,    'Total de Tasks', overview.total_tasks, null, '')}
        ${kpiCard(ICONS.check,    'Concluídas', overview.completed_tasks, pct + ' do total', 'text-emerald-600')}
        ${kpiCard(ICONS.chartBar, 'Progresso Geral', pct, overview.completed_tasks + ' de ' + overview.total_tasks, 'text-red-600')}
        ${kpiCard(ICONS.clock,    'Em Atraso', overview.overdue_tasks, 'tasks vencidas', overdueColor)}
        ${kpiCard(ICONS.calendar, 'Sem Data', overview.tasks_without_due_date, 'sem due date', 'text-gray-500')}
      </div>

      <!-- Charts row -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6 items-start">
        <div class="lg:col-span-2 bg-white rounded-xl border border-gray-200 p-4">
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-sm font-semibold text-gray-700">Progresso por Província</h2>
            <a href="#/gantt/overview"
               class="text-xs bg-slate-50 text-slate-600 px-3 py-1.5 rounded-lg hover:bg-slate-100 active:scale-95 transition-all font-medium flex items-center gap-1.5">
              <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
              </svg>
              Cronograma Geral
            </a>
          </div>
          <div style="max-height:460px;overflow-y:auto;overflow-x:hidden;">
            <div id="chart-folders" class="echo-chart" style="height:${Math.max(200, folders.length * 38)}px"></div>
          </div>
        </div>
        <div class="bg-white rounded-xl border border-gray-200 p-4">
          <h2 class="text-sm font-semibold text-gray-700 mb-3">Distribuição por Status</h2>
          <div id="chart-donut" class="echo-chart" style="height:380px"></div>
        </div>
      </div>

      <!-- Produtividade + Próximos Vencimentos -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6 items-start">
        <div class="bg-white rounded-xl border border-gray-200 p-4">
          <h2 class="text-sm font-semibold text-gray-700 mb-3">Produtividade por Responsável</h2>
          <div id="chart-assignees" class="echo-chart" style="height:300px"></div>
        </div>
        <div class="bg-white rounded-xl border border-gray-200 p-4">
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-sm font-semibold text-gray-700">Próximos Vencimentos</h2>
            <div class="flex gap-1">
              <button onclick="document.getElementById('upcoming-7').classList.remove('hidden');document.getElementById('upcoming-30').classList.add('hidden');this.classList.add('bg-red-100','text-red-700');this.nextElementSibling.classList.remove('bg-red-100','text-red-700')"
                class="text-xs px-2.5 py-1 rounded-lg bg-red-100 text-red-700 font-medium transition-colors">7 dias</button>
              <button onclick="document.getElementById('upcoming-30').classList.remove('hidden');document.getElementById('upcoming-7').classList.add('hidden');this.classList.add('bg-red-100','text-red-700');this.previousElementSibling.classList.remove('bg-red-100','text-red-700')"
                class="text-xs px-2.5 py-1 rounded-lg text-gray-500 font-medium transition-colors">30 dias</button>
            </div>
          </div>
          <div id="upcoming-7">${upcomingRows(upcomingIn7)}</div>
          <div id="upcoming-30" class="hidden">${upcomingRows(upcoming)}</div>
        </div>
      </div>

      <!-- Evolução temporal das Províncias -->
      <div class="bg-white rounded-xl border border-gray-200 p-4 mb-6">
        <div class="flex items-center justify-between mb-1">
          <h2 class="text-sm font-semibold text-gray-700">Evolução por Província</h2>
          <span class="text-xs text-gray-400">Progresso ponderado acumulado por data de conclusão de tarefas · Ranking atual: maior → menor</span>
        </div>
        <div id="chart-evolution" class="echo-chart" style="height:420px"></div>
      </div>

      <!-- Províncias grid -->
      <h2 class="text-sm font-semibold text-gray-700 mb-3">Províncias (${folders.length})</h2>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        ${foldersHTML}
      </div>
    `);

    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        var foldersSorted = folders.slice().sort(function (a, b) {
          var rA = a.total_tasks > 0 ? a.completed_tasks / a.total_tasks : 0;
          var rB = b.total_tasks > 0 ? b.completed_tasks / b.total_tasks : 0;
          return rA - rB; // ascendente → ECharts coloca o mais avançado no topo
        });
        Charts.renderProgressBars('chart-folders', foldersSorted, 'name', 'completed_tasks', 'total_tasks', true, function (f) {
          window.__folderName = f.name;
          location.hash = '#/folder/' + f.folder_id;
        });
        Charts.renderStatusDonut('chart-donut', overview.status_distribution);
        Charts.renderAssigneeChart('chart-assignees', assignees);
        Charts.renderEvolutionChart('chart-evolution', evolution);
      });
    });
  }

  /* ── VIEW: Folder (listas) ───────────────────────────────────────── */
  async function renderFolder(folderId) {
    loading();
    const folderName = window.__folderName || 'Província';
    setBreadcrumb([
      { label: 'Visão Geral', href: '#/' },
      { label: folderName, href: '#/folder/' + folderId },
    ]);

    let lists, disciplines;
    try {
      [lists, disciplines] = await Promise.all([
        api('/dashboard/folder/' + folderId),
        fetch('/disciplines/folder/' + folderId).then(function (r) { return r.json(); }).then(function (j) { return j.success ? j.data : null; }).catch(function () { return null; }),
      ]);
    } catch (e) {
      setView(`<div class="text-red-500 text-center py-12">Erro: ${esc(e.message)}</div>`);
      return;
    }

    nav.folderId = folderId;
    nav.folderName = folderName;

    const totalTasks     = lists.reduce(function (s, l) { return s + l.total_tasks; }, 0);
    const completedTasks = lists.reduce(function (s, l) { return s + l.completed_tasks; }, 0);
    const overdueTasks   = lists.reduce(function (s, l) { return s + l.overdue_tasks; }, 0);
    const rate           = totalTasks > 0 ? completedTasks / totalTasks : 0;
    const wp             = disciplines && disciplines.weights_configured ? disciplines.weighted_progress : null;
    const wpPct          = wp !== null && wp !== undefined ? fmtPct(wp) : null;

    const listsHTML = lists.map(function (l) {
      const disc = disciplines && disciplines.disciplines
        ? disciplines.disciplines.find(function (d) { return d.list_id === l.list_id; })
        : null;
      const weightBadge = disc && disc.weight !== null
        ? `<span class="text-xs text-indigo-600 font-medium bg-indigo-50 px-1.5 py-0.5 rounded ml-1">${Math.round(disc.weight * 100)}%</span>`
        : '';
      return `<div class="bg-white rounded-xl border border-gray-200 p-4 card-hover cursor-pointer"
               onclick="location.hash='#/list/${esc(l.list_id)}'; window.__listName='${esc(l.name)}'">
        <div class="flex items-start justify-between gap-2">
          <div class="flex items-center gap-1 min-w-0">
            <p class="font-medium text-gray-800 truncate">${esc(l.name)}</p>
            ${weightBadge}
          </div>
          <span class="text-sm font-bold ${l.completion_rate >= 0.8 ? 'text-emerald-600' : l.completion_rate >= 0.4 ? 'text-amber-600' : 'text-red-500'} shrink-0">
            ${fmtPct(l.completion_rate)}
          </span>
        </div>
        <p class="text-xs text-gray-400 mt-0.5">${l.total_tasks} task(s)</p>
        ${progressBar(l.completion_rate)}
        ${l.overdue_tasks > 0 ? `<p class="text-xs text-red-500 mt-1.5 flex items-center gap-1">${WARN_ICON} ${l.overdue_tasks} em atraso</p>` : ''}
      </div>`;
    }).join('');

    const wpCard = wpPct
      ? kpiCard(
          `<svg class="w-6 h-6 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 3v17.25m0 0c-1.472 0-2.882.265-4.185.75M12 20.25c1.472 0 2.882.265 4.185.75M18.75 4.97A48.416 48.416 0 0 0 12 4.5c-2.291 0-4.545.16-6.75.47m13.5 0c1.01.143 2.01.317 3 .52m-3-.52 2.62 7.5h-1.57a2.25 2.25 0 0 0-2.187 1.715l-.38 1.5A2.25 2.25 0 0 1 14.25 18H9.75a2.25 2.25 0 0 1-2.182-1.715l-.38-1.5A2.25 2.25 0 0 0 5.003 12.97H3.383l2.62-7.5h13.994Z"/></svg>`,
          'Prog. Ponderado',
          wpPct,
          'EVM por disciplina',
          'text-indigo-600'
        )
      : '';

    const warnNoWeights = (!disciplines || !disciplines.weights_configured)
      ? `<div class="mb-4 bg-amber-50 border border-amber-200 rounded-lg px-4 py-2.5 flex items-center gap-2 text-xs text-amber-700">
          <svg class="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"/></svg>
          Pesos de disciplinas não configurados. Configure para ativar o progresso ponderado (EVM).
          <button onclick="openDisciplinesModal('${esc(folderId)}')" class="ml-auto text-xs bg-amber-100 hover:bg-amber-200 text-amber-800 px-2.5 py-1 rounded-lg font-medium transition-colors">Configurar</button>
        </div>`
      : '';

    setView(`
      ${warnNoWeights}
      <!-- KPIs -->
      <div class="grid grid-cols-2 ${wpPct ? 'sm:grid-cols-5' : 'sm:grid-cols-4'} gap-3 mb-6">
        ${kpiCard(ICONS.folder, 'Áreas / Disciplinas', lists.length)}
        ${kpiCard(ICONS.tasks,  'Tasks', totalTasks)}
        ${kpiCard(ICONS.check,  'Progresso Simples', fmtPct(rate), completedTasks + ' concluídas', 'text-emerald-600')}
        ${kpiCard(ICONS.clock,  'Em Atraso', overdueTasks, null, overdueTasks > 0 ? 'text-red-600' : '')}
        ${wpCard}
      </div>

      <!-- Chart + botão configurar -->
      <div class="bg-white rounded-xl border border-gray-200 p-4 mb-6">
        <div class="flex items-center justify-between mb-3 gap-2">
          <h2 class="text-sm font-semibold text-gray-700">Progresso por Disciplina</h2>
          <div class="flex items-center gap-2">
            <button onclick="openDisciplinesModal('${esc(folderId)}')"
              class="text-xs bg-indigo-50 text-indigo-700 px-2.5 py-1 rounded-lg hover:bg-indigo-100 transition-colors font-medium flex items-center gap-1 shrink-0">
              <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 3v17.25m0 0c-1.472 0-2.882.265-4.185.75M12 20.25c1.472 0 2.882.265 4.185.75M18.75 4.97A48.416 48.416 0 0 0 12 4.5c-2.291 0-4.545.16-6.75.47m13.5 0c1.01.143 2.01.317 3 .52m-3-.52 2.62 7.5h-1.57a2.25 2.25 0 0 0-2.187 1.715l-.38 1.5A2.25 2.25 0 0 1 14.25 18H9.75a2.25 2.25 0 0 1-2.182-1.715l-.38-1.5A2.25 2.25 0 0 0 5.003 12.97H3.383l2.62-7.5h13.994Z"/></svg>
              Pesos
            </button>
            <a href="#/gantt/folder/${esc(folderId)}"
              class="text-xs bg-red-50 text-red-700 px-2.5 py-1 rounded-lg hover:bg-red-100 transition-colors font-medium flex items-center gap-1 shrink-0">
              <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 6h18M3 12h18M3 18h18"/>
              </svg>
              Cronograma
            </a>
          </div>
        </div>
        <div id="chart-lists" class="echo-chart" style="height:${Math.max(200, lists.length * 38)}px"></div>
      </div>

      <!-- Lists grid -->
      <h2 class="text-sm font-semibold text-gray-700 mb-3">Disciplinas / Áreas (${lists.length})</h2>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        ${listsHTML}
      </div>
    `);

    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        Charts.renderProgressBars('chart-lists', lists, 'name', 'completed_tasks', 'total_tasks', true, function (l) {
          window.__listName = l.name;
          location.hash = '#/list/' + l.list_id;
        });
      });
    });
  }

  /* ── Modal: Configurar Pesos de Disciplinas ──────────────────────── */
  window.openDisciplinesModal = async function (folderId) {
    let data;
    try {
      const res = await fetch('/disciplines/folder/' + folderId);
      const json = await res.json();
      data = json.data;
    } catch (e) {
      showToast('Erro ao carregar disciplinas: ' + e.message, 'error');
      return;
    }

    const discs = data.disciplines || [];
    const totalDiscs = discs.length;
    const equalW = totalDiscs > 0 ? Math.floor(100 / totalDiscs) : 0;

    const rows = discs.map(function (d, i) {
      const w = d.weight !== null ? Math.round(d.weight * 1000) / 10 : equalW;
      return `<tr class="border-b border-gray-100">
        <td class="py-2.5 pr-3">
          <p class="text-sm font-medium text-gray-800">${esc(d.name)}</p>
          <p class="text-xs text-gray-400">${d.total_tasks} tarefa(s) · ${Math.round(d.completion_rate * 100)}% concluídas</p>
        </td>
        <td class="py-2.5 w-20">
          <input type="number" id="disc-w-${i}" data-listid="${esc(d.list_id)}"
            value="${w}" min="0" max="100" step="0.5"
            class="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm text-right focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
            oninput="updateWeightSum()">
        </td>
        <td class="py-2.5 pl-2 w-8 text-xs text-gray-400">%</td>
      </tr>`;
    }).join('');

    const modal = document.createElement('div');
    modal.id = 'disciplines-modal';
    modal.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm';
    modal.innerHTML = `
      <div class="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        <div class="bg-indigo-600 px-5 py-4">
          <h2 class="text-white font-bold text-base">Pesos das Disciplinas</h2>
          <p class="text-indigo-200 text-xs mt-0.5">Os pesos definem a importância de cada disciplina no progresso geral (EVM)</p>
        </div>
        <div class="px-5 py-4 max-h-96 overflow-y-auto">
          <table class="w-full">
            <thead><tr class="text-xs text-gray-400 uppercase">
              <th class="pb-2 text-left">Disciplina</th>
              <th class="pb-2 text-right">Peso</th>
              <th></th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <div class="px-5 py-3 border-t border-gray-100 flex items-center justify-between gap-3">
          <div class="text-xs">
            Soma: <span id="weight-sum" class="font-bold text-gray-800">—</span>%
            <span id="weight-warn" class="text-red-500 ml-1 hidden">(deve ser 100%)</span>
          </div>
          <div class="flex gap-2">
            <button onclick="distributeEqualWeights(${totalDiscs})"
              class="text-xs text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded-lg hover:bg-gray-100 transition-colors">Igualar</button>
            <button onclick="document.getElementById('disciplines-modal').remove()"
              class="text-xs text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded-lg hover:bg-gray-100 transition-colors">Cancelar</button>
            <button onclick="saveDisciplineWeights('${esc(folderId)}')"
              class="text-xs bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-1.5 rounded-lg font-medium transition-colors">Salvar</button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.addEventListener('click', function (e) {
      if (e.target === modal) modal.remove();
    });
    updateWeightSum();
  };

  window.updateWeightSum = function () {
    const inputs = document.querySelectorAll('[id^="disc-w-"]');
    let sum = 0;
    inputs.forEach(function (inp) { sum += parseFloat(inp.value) || 0; });
    const sumEl = document.getElementById('weight-sum');
    const warnEl = document.getElementById('weight-warn');
    if (!sumEl) return;
    sumEl.textContent = Math.round(sum * 10) / 10;
    const ok = Math.abs(sum - 100) < 0.5;
    sumEl.className = ok ? 'font-bold text-emerald-600' : 'font-bold text-red-500';
    if (warnEl) warnEl.classList.toggle('hidden', ok);
  };

  window.distributeEqualWeights = function (n) {
    if (!n) return;
    const base = Math.floor(1000 / n) / 10;
    const inputs = document.querySelectorAll('[id^="disc-w-"]');
    inputs.forEach(function (inp) { inp.value = base; });
    updateWeightSum();
  };

  window.saveDisciplineWeights = async function (folderId) {
    const inputs = document.querySelectorAll('[id^="disc-w-"]');
    let sum = 0;
    const weights = [];
    inputs.forEach(function (inp) {
      const w = parseFloat(inp.value) || 0;
      sum += w;
      weights.push({ list_id: inp.dataset.listid, weight: Math.round(w * 10000) / 1000000 });
    });
    if (Math.abs(sum - 100) > 0.5) {
      showToast('A soma dos pesos deve ser 100%. Soma atual: ' + Math.round(sum * 10) / 10 + '%', 'error');
      return;
    }
    const password = prompt('Digite a senha para alterar os pesos das disciplinas:');
    if (password === null) return;
    try {
      const res = await fetch('/disciplines/folder/' + folderId, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Delete-Password': password },
        body: JSON.stringify({ weights: weights }),
      });
      if (res.status === 403) {
        showToast('Senha incorreta.', 'error');
        return;
      }
      const json = await res.json();
      if (!json.success) throw new Error(json.detail || 'Erro ao salvar');
      document.getElementById('disciplines-modal').remove();
      showToast('Pesos salvos com sucesso!', 'success');
      renderFolder(folderId);
    } catch (e) {
      showToast('Erro ao salvar: ' + e.message, 'error');
    }
  };

  /* ── VIEW: Lista (tasks) ─────────────────────────────────────────── */
  async function renderList(listId) {
    loading();
    const listName = window.__listName || 'Área';
    setBreadcrumb([
      { label: 'Visão Geral', href: '#/' },
      nav.folderId
        ? { label: nav.folderName || 'Província', href: '#/folder/' + nav.folderId }
        : null,
      { label: listName, href: '#/list/' + listId },
    ].filter(Boolean));

    let tasks;
    try {
      tasks = await api('/dashboard/list/' + listId);
    } catch (e) {
      setView(`<div class="text-red-500 text-center py-12">Erro: ${esc(e.message)}</div>`);
      return;
    }

    nav.listId   = listId;
    nav.listName = listName;

    const total     = tasks.length;
    const completed = tasks.filter(function (t) { return t.status_type === 'done' || t.status_type === 'closed'; }).length;
    const overdue   = tasks.filter(function (t) { return t.is_overdue; }).length;
    const rate      = total > 0 ? completed / total : 0;

    const rows = tasks.map(function (t) {
      const assigneeNames = (t.assignees || []).map(function (a) { return a.username || '?'; }).join(', ') || '—';
      const dueCls = t.is_overdue ? 'text-red-500 font-medium' : 'text-gray-500';
      const subtaskIcon = t.has_subtasks
        ? `<span class="text-xs text-red-500 ml-1" title="Tem subtasks">◈</span>` : '';
      return `<tr class="hover:bg-slate-50 cursor-pointer" onclick="location.hash='#/task/${esc(t.task_id)}'; window.__taskName='${esc(t.name)}'">
        <td class="py-3 px-4">
          <span class="font-medium text-gray-800">${esc(t.name)}</span>${subtaskIcon}
        </td>
        <td class="py-3 px-4">${statusBadge(t.status, t.status_type, t.status_color)}</td>
        <td class="py-3 px-4 text-sm text-gray-500">${esc(assigneeNames)}</td>
        <td class="py-3 px-4 text-sm ${dueCls}">${t.is_overdue ? WARN_ICON + ' ' : ''}${fmtDate(t.due_date)}</td>
      </tr>`;
    }).join('');

    const emptyMsg = total === 0
      ? `<tr><td colspan="4" class="py-12 text-center text-gray-400 text-sm">Nenhuma task nesta área</td></tr>` : '';

    setView(`
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        ${kpiCard(ICONS.tasks,    'Tasks', total)}
        ${kpiCard(ICONS.check,    'Concluídas', completed, fmtPct(rate), 'text-emerald-600')}
        ${kpiCard(ICONS.sync,     'Em Andamento', total - completed - overdue, null, 'text-blue-600')}
        ${kpiCard(ICONS.clock,    'Em Atraso', overdue, null, overdue > 0 ? 'text-red-600' : '')}
      </div>

      <div class="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div class="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
          <h2 class="text-sm font-semibold text-gray-700">${esc(listName)} — Tasks (${total})</h2>
          <div class="flex items-center gap-3">
            <div class="w-32">${progressBar(rate)}</div>
            <a href="#/gantt/${esc(listId)}"
              class="text-xs bg-red-50 text-red-700 px-2.5 py-1 rounded-lg hover:bg-red-100 transition-colors font-medium flex items-center gap-1 shrink-0">
              <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 6h18M3 12h18M3 18h18"/>
              </svg>
              Cronograma
            </a>
          </div>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-xs text-gray-400 uppercase tracking-wide border-b border-slate-100">
                <th class="py-2 px-4 text-left font-medium w-1/2">Task</th>
                <th class="py-2 px-4 text-left font-medium">Status</th>
                <th class="py-2 px-4 text-left font-medium">Responsável</th>
                <th class="py-2 px-4 text-left font-medium">Prazo</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-50">
              ${rows || emptyMsg}
            </tbody>
          </table>
        </div>
      </div>
    `);
  }

  /* ── VIEW: Task (detalhe + subtasks) ─────────────────────────────── */
  async function renderTask(taskId) {
    loading();
    const taskName = window.__taskName || 'Task';
    setBreadcrumb([
      { label: 'Visão Geral', href: '#/' },
      nav.folderId ? { label: nav.folderName || 'Província', href: '#/folder/' + nav.folderId } : null,
      nav.listId   ? { label: nav.listName || 'Área',       href: '#/list/' + nav.listId }     : null,
      { label: taskName, href: '#/task/' + taskId },
    ].filter(Boolean));

    let task;
    try {
      task = await api('/dashboard/task/' + taskId);
    } catch (e) {
      if (e.message.includes('404')) {
        setView(`<div class="text-gray-500 text-center py-12">Task não encontrada no cache. Aguarde o próximo refresh.</div>`);
      } else {
        setView(`<div class="text-red-500 text-center py-12">Erro: ${esc(e.message)}</div>`);
      }
      return;
    }

    const assigneeNames = (task.assignees || []).map(function (a) { return a.username || '?'; }).join(', ') || '—';
    const tags = (task.tags || []).map(function (t) {
      return `<span class="text-xs bg-red-50 text-red-700 px-2 py-0.5 rounded-full">${esc(t)}</span>`;
    }).join('');

    const subtaskRows = (task.subtasks || []).map(function (s) {
      const names = (s.assignees || []).map(function (a) { return a.username || '?'; }).join(', ') || '—';
      const dueCls = s.is_overdue ? 'text-red-500 font-medium' : 'text-gray-500';
      return `<tr class="hover:bg-slate-50">
        <td class="py-2.5 px-4 text-sm text-gray-700">${esc(s.name)}</td>
        <td class="py-2.5 px-4">${statusBadge(s.status, s.status_type, s.status_color)}</td>
        <td class="py-2.5 px-4 text-sm text-gray-500">${esc(names)}</td>
        <td class="py-2.5 px-4 text-sm ${dueCls}">${s.is_overdue ? WARN_ICON + ' ' : ''}${fmtDate(s.due_date)}</td>
      </tr>`;
    }).join('');

    const subtaskSection = task.has_subtasks ? `
      <div class="bg-white rounded-xl border border-gray-200 overflow-hidden mt-4">
        <div class="px-4 py-3 border-b border-slate-100">
          <h3 class="text-sm font-semibold text-gray-700">Subtasks (${task.subtasks.length})</h3>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-xs text-gray-400 uppercase tracking-wide border-b border-slate-100">
                <th class="py-2 px-4 text-left font-medium">Nome</th>
                <th class="py-2 px-4 text-left font-medium">Status</th>
                <th class="py-2 px-4 text-left font-medium">Responsável</th>
                <th class="py-2 px-4 text-left font-medium">Prazo</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-50">${subtaskRows}</tbody>
          </table>
        </div>
      </div>` : '';

    setView(`
      <!-- Cabeçalho da task -->
      <div class="bg-white rounded-xl border border-gray-200 p-5 mb-4">
        <div class="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 class="text-lg font-bold text-slate-900">${esc(task.name)}</h1>
            <div class="flex items-center gap-2 mt-2 flex-wrap">
              ${statusBadge(task.status, task.status_type, task.status_color)}
              ${task.is_overdue ? `<span class="status-badge bg-red-50 text-red-600 inline-flex items-center gap-1">${WARN_ICON} Em atraso</span>` : ''}
              ${tags}
            </div>
          </div>
          <div class="flex items-center gap-3 shrink-0">
            ${task.has_subtasks ? `<a href="#/gantt/task/${esc(task.task_id)}"
              class="text-xs bg-red-50 text-red-700 px-2.5 py-1 rounded-lg hover:bg-red-100 transition-colors font-medium flex items-center gap-1">
              <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 6h18M3 12h18M3 18h18"/>
              </svg>
              Cronograma
            </a>` : ''}
            ${task.url ? `<a href="${esc(task.url)}" target="_blank" rel="noopener"
              class="text-xs text-red-600 hover:underline">Abrir no ClickUp ↗</a>` : ''}
          </div>
        </div>

        <!-- Metadados -->
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-5 pt-4 border-t border-slate-100 text-sm">
          <div>
            <p class="text-xs text-gray-400 uppercase tracking-wide mb-1">Responsável</p>
            <p class="text-gray-700 font-medium">${esc(assigneeNames)}</p>
          </div>
          <div>
            <p class="text-xs text-gray-400 uppercase tracking-wide mb-1">Prazo</p>
            <p class="${task.is_overdue ? 'text-red-500 font-medium' : 'text-gray-700'}">${fmtDate(task.due_date)}</p>
          </div>
          <div>
            <p class="text-xs text-gray-400 uppercase tracking-wide mb-1">Início</p>
            <p class="text-gray-700">${fmtDate(task.start_date)}</p>
          </div>
          <div>
            <p class="text-xs text-gray-400 uppercase tracking-wide mb-1">Criada em</p>
            <p class="text-gray-700">${fmtDate(task.date_created)}</p>
          </div>
        </div>

        ${task.description ? `
        <div class="mt-4 pt-4 border-t border-slate-100">
          <p class="text-xs text-gray-400 uppercase tracking-wide mb-2">Descrição</p>
          <p class="text-sm text-gray-600 whitespace-pre-wrap leading-relaxed">${esc(task.description)}</p>
        </div>` : ''}
      </div>

      ${subtaskSection}
    `);
  }

  /* ── VIEW: Cronograma Geral (overview de províncias) ─────────────── */
  async function renderGanttOverview() {
    loading();
    setBreadcrumb([
      { label: 'Visão Geral', href: '#/' },
      { label: 'Cronograma Geral' },
    ]);
    var rows;
    try {
      var res = await fetch('/dashboard/gantt/overview');
      var json = await res.json();
      rows = json.data || [];
    } catch (e) {
      setView('<div class="text-center py-16 text-red-500 text-sm">Erro ao carregar cronograma geral.</div>');
      return;
    }
    var tasks = rows.filter(function (r) { return r.due_date; });
    var noDate = rows.length - tasks.length;

    /* Converte para o formato esperado por renderGanttChart */
    var ganttTasks = tasks.map(function (r) {
      var rate = r.completion_rate || 0;
      var isOverdue = r.is_overdue && !r.is_done;
      return {
        task_id:         r.folder_id,
        name:            r.name,
        start_date:      r.start_date ? new Date(r.start_date) : null,
        due_date:        r.due_date   ? new Date(r.due_date)   : null,
        status:          r.is_done ? 'concluída' : (isOverdue ? 'em atraso' : 'em progresso'),
        status_color:    r.is_done ? '#86efac' : (isOverdue ? '#f87171' : (rate >= 0.8 ? '#4ade80' : rate >= 0.4 ? '#93c5fd' : '#cbd5e1')),
        is_done:         r.is_done,
        is_overdue:      isOverdue,
        total_tasks:     r.total_tasks,
        completed_tasks: r.completed_tasks,
        completion_rate: r.completion_rate,
        overdue_tasks:   r.overdue_tasks,
      };
    });

    var overdueN = ganttTasks.filter(function (t) { return t.is_overdue; }).length;
    var doneN    = ganttTasks.filter(function (t) { return t.is_done;    }).length;
    var subtitle = ganttTasks.length + ' províncias com prazo';
    if (noDate)    subtitle += ' · ' + noDate + ' sem prazo (ocultas)';
    if (overdueN)  subtitle += ' · <span class="text-red-500">' + overdueN + ' em atraso</span>';
    if (doneN)     subtitle += ' · <span class="text-green-600">' + doneN + ' concluídas</span>';

    setView(`
      <div class="mb-4 flex items-center justify-between gap-3">
        <div>
          <h1 class="text-base font-semibold text-gray-800">Cronograma Geral — Todas as Províncias</h1>
          <p class="text-xs text-gray-400 mt-0.5">${subtitle}</p>
        </div>
        <a href="#/" class="text-xs text-blue-600 hover:underline shrink-0">← Voltar para visão geral</a>
      </div>
      <div class="bg-white rounded-xl border border-gray-200 p-4 overflow-x-auto">
        <p class="text-xs text-gray-400 mb-3">Cada quadrado = 1 semana · Clique em uma província para ver o detalhe</p>
        <div id="chart-gantt-overview" style="width:100%;"></div>
      </div>
    `);

    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        Charts.renderGanttChart('chart-gantt-overview', ganttTasks, function (t) {
          window.__folderName = t.name;
          location.hash = '#/folder/' + t.task_id;
        });
      });
    });
  }

  /* ── Helper Gantt compartilhado ─────────────────────────────────── */
  function _renderGanttView(opts) {
    /* opts: { title, backHref, backLabel, chartId, tasks, noDateCount, onClickTask } */
    var tasks    = opts.tasks;
    var overdueN = tasks.filter(function (t) { return t.is_overdue && !t.is_done; }).length;
    var doneN    = tasks.filter(function (t) { return t.is_done; }).length;
    var noDate   = opts.noDateCount || 0;
    var subtitle = tasks.length + ' com prazo';
    if (noDate)    subtitle += ' · ' + noDate + ' sem prazo (ocultas)';
    if (overdueN)  subtitle += ' · <span class="text-red-500 font-medium">' + overdueN + ' em atraso</span>';
    if (doneN)     subtitle += ' · <span class="text-emerald-600">' + doneN + ' concluídas</span>';

    setView(`
      <div class="flex items-center justify-between mb-4 gap-4">
        <div class="min-w-0">
          <h1 class="text-base font-bold text-gray-800 truncate">${esc(opts.title)}</h1>
          <p class="text-xs text-gray-400 mt-0.5">${subtitle}</p>
        </div>
        <div class="flex items-center gap-4 shrink-0">
          <div class="flex items-center gap-3 text-xs text-gray-500">
            <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm inline-block bg-red-400"></span>Atraso</span>
            <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm inline-block bg-green-300"></span>Concluída</span>
            <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-sm inline-block bg-blue-300"></span>Em andamento</span>
          </div>
          <a href="${esc(opts.backHref)}"
            class="flex items-center gap-1 text-xs text-gray-500 hover:text-red-600 border-l border-gray-200 pl-4">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5 8.25 12l7.5-7.5"/>
            </svg>
            ${esc(opts.backLabel)}
          </a>
        </div>
      </div>
      <div class="bg-white rounded-xl border border-gray-200 p-4">
        <p class="text-xs text-gray-400 mb-3">Cada quadrado = 1 semana · Clique em uma tarefa para ver o detalhe · Role horizontalmente para navegar no tempo</p>
        <div id="${esc(opts.chartId)}" style="width:100%;"></div>
      </div>
    `);

    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        Charts.renderGanttChart(opts.chartId, tasks, opts.onClickTask);
      });
    });
  }

  /* ── VIEW: Gantt Província ───────────────────────────────────────── */
  async function renderGanttFolder(folderId) {
    loading();
    var folderName = window.__folderName || nav.folderName || 'Província';
    setBreadcrumb([
      { label: 'Visão Geral', href: '#/' },
      { label: folderName, href: '#/folder/' + folderId },
      { label: 'Cronograma', href: '#/gantt/folder/' + folderId },
    ]);

    var allTasks;
    try {
      allTasks = await api('/dashboard/gantt/folder/' + folderId);
    } catch (e) {
      setView(`<div class="text-red-500 text-center py-12">Erro: ${esc(e.message)}</div>`);
      return;
    }

    nav.folderId   = folderId;
    nav.folderName = folderName;

    var tasks   = allTasks.filter(function (t) { return t.due_date; });
    var noDate  = allTasks.length - tasks.length;

    _renderGanttView({
      title:        folderName + ' — Cronograma',
      backHref:     '#/folder/' + folderId,
      backLabel:    'Voltar para província',
      chartId:      'chart-gantt',
      tasks:        tasks,
      noDateCount:  noDate,
      onClickTask:  function (t) { window.__taskName = t.name; location.hash = '#/task/' + t.task_id; },
    });
  }

  /* ── VIEW: Gantt Task (task + subtasks) ─────────────────────────── */
  async function renderGanttTask(taskId) {
    loading();
    var taskName = window.__taskName || nav.taskName || 'Task';
    setBreadcrumb([
      { label: 'Visão Geral', href: '#/' },
      nav.folderId ? { label: nav.folderName || 'Província', href: '#/folder/' + nav.folderId } : null,
      nav.listId   ? { label: nav.listName   || 'Área',      href: '#/list/'   + nav.listId   } : null,
      { label: taskName, href: '#/task/' + taskId },
      { label: 'Cronograma', href: '#/gantt/task/' + taskId },
    ].filter(Boolean));

    var allTasks;
    try {
      allTasks = await api('/dashboard/gantt/task/' + taskId);
    } catch (e) {
      setView(`<div class="text-red-500 text-center py-12">Erro: ${esc(e.message)}</div>`);
      return;
    }

    var tasks  = allTasks.filter(function (t) { return t.due_date; });
    var noDate = allTasks.length - tasks.length;

    _renderGanttView({
      title:       taskName + ' — Cronograma',
      backHref:    '#/task/' + taskId,
      backLabel:   'Voltar para task',
      chartId:     'chart-gantt',
      tasks:       tasks,
      noDateCount: noDate,
      onClickTask: function (t) {
        if (!t.is_parent) { window.__taskName = t.name; location.hash = '#/task/' + t.task_id; }
      },
    });
  }

  /* ── VIEW: Gantt por área (lista) ───────────────────────────────── */
  async function renderGantt(listId) {
    loading();
    var listName = window.__listName || nav.listName || 'Área';
    setBreadcrumb([
      { label: 'Visão Geral', href: '#/' },
      nav.folderId ? { label: nav.folderName || 'Província', href: '#/folder/' + nav.folderId } : null,
      { label: listName, href: '#/list/' + listId },
      { label: 'Cronograma', href: '#/gantt/' + listId },
    ].filter(Boolean));

    var allTasks;
    try {
      allTasks = await api('/dashboard/gantt/' + listId);
    } catch (e) {
      setView(`<div class="text-red-500 text-center py-12">Erro: ${esc(e.message)}</div>`);
      return;
    }

    var tasks  = allTasks.filter(function (t) { return t.due_date; });
    var noDate = allTasks.length - tasks.length;

    _renderGanttView({
      title:       listName + ' — Cronograma',
      backHref:    '#/list/' + listId,
      backLabel:   'Voltar para lista',
      chartId:     'chart-gantt',
      tasks:       tasks,
      noDateCount: noDate,
      onClickTask: function (t) { window.__taskName = t.name; location.hash = '#/task/' + t.task_id; },
    });
  }

  /* ── Roteador ────────────────────────────────────────────────────── */
  function router() {
    const hash  = location.hash.replace(/^#\/?/, '');
    const parts = hash.split('/').filter(Boolean);
    const route = parts[0] || '';
    const param = parts[1] || '';

    if (route === 'folder' && param) {
      renderFolder(param);
    } else if (route === 'list' && param) {
      renderList(param);
    } else if (route === 'gantt') {
      if (param === 'overview') {
        renderGanttOverview();
      } else if (param === 'folder' && parts[2]) {
        renderGanttFolder(parts[2]);
      } else if (param === 'task' && parts[2]) {
        renderGanttTask(parts[2]);
      } else if (param) {
        renderGantt(param);
      }
    } else if (route === 'task' && param) {
      renderTask(param);
    } else {
      renderOverview();
    }
  }

  /* ── Refresh manual ──────────────────────────────────────────────── */
  window.triggerRefresh = async function () {
    const btn = document.getElementById('refresh-btn');
    const lbl = document.getElementById('refresh-label');
    if (btn) btn.disabled = true;
    if (lbl) lbl.textContent = 'Aguarde…';
    try {
      await fetch('/dashboard/refresh', { method: 'POST' });
      showToast('Refresh iniciado! Os dados serão atualizados em breve.', 'success');
    } catch (e) {
      showToast('Falha ao disparar refresh: ' + e.message, 'error');
    } finally {
      if (btn) btn.disabled = false;
      if (lbl) lbl.textContent = 'Atualizar';
    }
  };

  /* ── SSE: re-renderiza a view atual quando receber update ─────────── */
  document.addEventListener('dashboard-update', function (e) {
    const detail = e.detail || {};
    showToast('Dados atualizados pelo ClickUp (' + (detail.type || 'evento') + ')', 'info');
    router();
  });

  /* ── Polling fallback ────────────────────────────────────────────── */
  document.addEventListener('dashboard-poll', function () { router(); });

  /* ── Init ────────────────────────────────────────────────────────── */
  window.addEventListener('hashchange', router);
  window.addEventListener('load', router);
})();
