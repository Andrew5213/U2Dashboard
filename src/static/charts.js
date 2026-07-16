/* Wrappers ECharts para o dashboard */
const Charts = (function () {
  const _instances = {};
  const _observers = {};
  var _ganttTooltip = null;

  function _init(id) {
    if (_instances[id]) { _instances[id].dispose(); }
    if (_observers[id]) { _observers[id].disconnect(); delete _observers[id]; }
    const el = document.getElementById(id);
    if (!el) return null;
    const chart = echarts.init(el, null, { renderer: 'svg' });
    _instances[id] = chart;
    window.addEventListener('resize', function () { chart.resize(); });
    /* ResizeObserver corrige dimensões quando o CSS Grid resolve o layout
       depois da inicialização síncrona do chart */
    if (window.ResizeObserver) {
      var ro = new ResizeObserver(function () { chart.resize(); });
      ro.observe(el);
      _observers[id] = ro;
    }
    return chart;
  }

  function disposeAll() {
    Object.keys(_instances).forEach(function (id) {
      try { _instances[id].dispose(); } catch (_) {}
      delete _instances[id];
    });
    Object.keys(_observers).forEach(function (id) {
      try { _observers[id].disconnect(); } catch (_) {}
      delete _observers[id];
    });
  }

  /* Barras horizontais: progresso por item (folders ou listas).
     asPercent=true → eixo 0-100%, útil quando os totais são muito díspares. */
  function renderProgressBars(id, items, labelKey, completedKey, totalKey, asPercent, onClickItem) {
    const chart = _init(id);
    if (!chart) return;

    const names = items.map(function (i) { return i[labelKey]; });

    var completed, open, xMax, xFmt, tooltipFmt;
    if (asPercent) {
      completed = items.map(function (i) {
        var t = i[totalKey]; return t > 0 ? Math.round(i[completedKey] / t * 100) : 0;
      });
      open = items.map(function (i) {
        var t = i[totalKey]; return t > 0 ? Math.round((t - i[completedKey]) / t * 100) : 100;
      });
      xMax = 100;
      xFmt = function (v) { return v + '%'; };
      tooltipFmt = function (params) {
        var idx = params[0] ? params[0].dataIndex : 0;
        var item = items[idx] || {};
        var done = item[completedKey] || 0;
        var total = item[totalKey] || 0;
        var pending = total - done;
        var title = params[0] ? '<b>' + params[0].axisValue + '</b><br/>' : '';
        return title + params.map(function (p) {
          var count = p.seriesName === 'Concluídas' ? done : pending;
          return p.marker + ' ' + p.seriesName + ': <b>' + p.value + '%</b> (' + count + ' tasks)';
        }).join('<br/>');
      };
    } else {
      completed = items.map(function (i) { return i[completedKey]; });
      open      = items.map(function (i) { return i[totalKey] - i[completedKey]; });
      xMax = null;
      xFmt = null;
      tooltipFmt = null;
    }

    chart.setOption({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: tooltipFmt || undefined,
      },
      legend: { data: ['Concluídas', 'Em aberto'], bottom: 0, textStyle: { fontSize: 11 } },
      grid: { left: '2%', right: '4%', top: 10, bottom: 40, containLabel: true },
      xAxis: {
        type: 'value',
        max: xMax || undefined,
        axisLabel: { fontSize: 11, formatter: xFmt || undefined },
      },
      yAxis: {
        type: 'category',
        data: names,
        axisLabel: { fontSize: 11, width: 160, overflow: 'truncate' },
      },
      series: [
        {
          name: 'Concluídas',
          type: 'bar',
          stack: 'total',
          data: completed,
          itemStyle: { color: '#4ade80', cursor: onClickItem ? 'pointer' : 'default' },
          label: {
            show: true,
            position: 'inside',
            formatter: function (p) {
              if (!p.value) return '';
              return asPercent ? p.value + '%' : p.value;
            },
            fontSize: 10,
            color: '#166534',
          },
        },
        {
          name: 'Em aberto',
          type: 'bar',
          stack: 'total',
          data: open,
          itemStyle: { color: '#e2e8f0', borderRadius: [0, 3, 3, 0], cursor: onClickItem ? 'pointer' : 'default' },
          label: {
            show: true,
            position: 'inside',
            formatter: function (p) {
              if (!p.value) return '';
              return asPercent ? p.value + '%' : p.value;
            },
            fontSize: 10,
            color: '#64748b',
          },
        },
      ],
    });

    if (onClickItem) {
      chart.off('click');
      chart.on('click', function (params) {
        var item = items[params.dataIndex];
        if (item) { onClickItem(item); }
      });
    }
  }

  /* Donut de distribuição por status */
  function renderStatusDonut(id, distribution) {
    const chart = _init(id);
    if (!chart) return;

    const STATUS_COLORS = {
      'complete': '#4ade80',   'closed': '#22c55e',
      'in progress': '#60a5fa', 'em andamento': '#60a5fa',
      'to do': '#94a3b8',      'a fazer': '#94a3b8',    'open': '#94a3b8',
      'review': '#f59e0b',     'revisão': '#f59e0b',    'em revisão': '#60a5fa',
      'blocked': '#f87171',    'bloqueado': '#f87171',  'cancelled': '#f87171',
      'fazendo': '#818cf8',    'aprovação': '#f59e0b',  'planejando': '#94a3b8',
      'sem status': '#cbd5e1',
    };

    const FALLBACK_PALETTE = [
      '#a78bfa', '#fb923c', '#38bdf8', '#34d399',
      '#f472b6', '#facc15', '#e879f9', '#2dd4bf',
    ];
    var _fi = 0;

    const data = Object.entries(distribution).map(function ([name, value]) {
      var color = STATUS_COLORS[name.toLowerCase()];
      if (!color) { color = FALLBACK_PALETTE[_fi % FALLBACK_PALETTE.length]; _fi++; }
      return { name: name, value: value, itemStyle: { color: color } };
    });

    // "Planejando" vem desativado por padrão (oculto do donut), mas o usuário
    // pode reativar clicando na legenda — comportamento nativo do ECharts.
    var legendSelected = {};
    data.forEach(function (d) {
      if (d.name.toLowerCase() === 'planejando') legendSelected[d.name] = false;
    });

    chart.setOption({
      tooltip: {
        trigger: 'item',
        formatter: function (p) { return p.name + ': <b>' + p.value + '</b> (' + p.percent + '%)'; },
      },
      legend: {
        orient: 'horizontal',
        bottom: 4,
        left: 'center',
        itemWidth: 10,
        itemHeight: 10,
        textStyle: { fontSize: 10 },
        selected: legendSelected,
        formatter: function (name) {
          var item = data.find(function (d) { return d.name === name; });
          return item ? name + ' (' + item.value + ')' : name;
        },
      },
      series: [{
        type: 'pie',
        radius: ['40%', '62%'],
        center: ['50%', '42%'],
        avoidLabelOverlap: false,
        label: { show: false },
        labelLine: { show: false },
        emphasis: {
          label: { show: true, fontSize: 12, fontWeight: 'bold', formatter: '{b}\n{d}%' },
        },
        data: data,
      }],
    });
  }

  /* Barras de tarefas em atraso por assignee */
  function renderOverdueByAssignee(id, tasks) {
    const chart = _init(id);
    if (!chart) return;

    const counts = {};
    tasks.forEach(function (t) {
      if (!t.is_overdue) return;
      const names = t.assignees && t.assignees.length
        ? t.assignees.map(function (a) { return a.username || 'sem nome'; })
        : ['Sem responsável'];
      names.forEach(function (n) { counts[n] = (counts[n] || 0) + 1; });
    });

    const sorted = Object.entries(counts).sort(function (a, b) { return b[1] - a[1]; }).slice(0, 10);
    if (!sorted.length) {
      chart.setOption({
        graphic: [{
          type: 'text',
          left: 'center', top: 'middle',
          style: { text: '✓ Nenhuma task em atraso', fontSize: 13, fill: '#94a3b8' },
        }],
      });
      return;
    }

    chart.setOption({
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: '2%', right: '4%', top: 10, bottom: 10, containLabel: true },
      xAxis: { type: 'value', axisLabel: { fontSize: 11 } },
      yAxis: {
        type: 'category',
        data: sorted.map(function (s) { return s[0]; }),
        axisLabel: { fontSize: 11 },
      },
      series: [{
        type: 'bar',
        data: sorted.map(function (s) { return s[1]; }),
        itemStyle: { color: '#f87171', borderRadius: [0, 3, 3, 0] },
        label: { show: true, position: 'right', fontSize: 11 },
      }],
    });
  }

  /* Barras verticais de produtividade por responsável.
     Altura = total de tasks; cor = taxa de conclusão (verde/amarelo/vermelho). */
  function renderAssigneeChart(id, data) {
    const chart = _init(id);
    if (!chart) return;

    if (!data || !data.length) {
      chart.setOption({
        graphic: [{ type: 'text', left: 'center', top: 'middle',
          style: { text: 'Nenhum responsável atribuído', fontSize: 13, fill: '#94a3b8' } }],
      });
      return;
    }

    var top = data.slice(0, 20);
    var barData = top.map(function (d) {
      var total = d.open + d.completed;
      var rate  = total > 0 ? d.completed / total : 0;
      var color = rate >= 0.7 ? '#4ade80' : rate >= 0.35 ? '#fbbf24' : '#f87171';
      return { value: total, rate: rate, open: d.open, completed: d.completed,
               overdue: d.overdue, itemStyle: { color: color, borderRadius: [4, 4, 0, 0] } };
    });

    chart.setOption({
      tooltip: {
        trigger: 'item',
        formatter: function (p) {
          var d = p.data;
          var pct = Math.round((d.rate || 0) * 100);
          return '<b>' + top[p.dataIndex].assignee + '</b><br/>' +
            'Total: <b>' + d.value + '</b><br/>' +
            'Concluídas: <b>' + d.completed + '</b> (' + pct + '%)<br/>' +
            'Em aberto: <b>' + d.open + '</b>' +
            (d.overdue ? '<br/><span style="color:#f87171">Em atraso: <b>' + d.overdue + '</b></span>' : '');
        },
      },
      grid: { left: '2%', right: '2%', top: 24, bottom: 8, containLabel: true },
      xAxis: {
        type: 'category',
        data: top.map(function (d) { return d.assignee; }),
        axisLabel: { fontSize: 10, rotate: 30, overflow: 'truncate', width: 100 },
        axisTick: { alignWithLabel: true },
      },
      yAxis: {
        type: 'value',
        axisLabel: { fontSize: 10 },
        splitLine: { lineStyle: { color: '#f1f5f9' } },
      },
      series: [{
        type: 'bar',
        data: barData,
        barMaxWidth: 48,
        label: {
          show: true,
          position: 'top',
          fontSize: 10,
          color: '#64748b',
          formatter: function (p) {
            var pct = Math.round((p.data.rate || 0) * 100);
            return pct + '%';
          },
        },
      }],
    });
  }

  /* Retorna (criando se necessário) o div de tooltip singleton do Gantt */
  function _getGanttTip() {
    if (!_ganttTooltip) {
      _ganttTooltip = document.createElement('div');
      _ganttTooltip.style.cssText = [
        'display:none', 'position:fixed', 'z-index:9999',
        'background:rgba(15,23,42,0.92)', 'color:#fff',
        'font-size:11px', 'line-height:1.65', 'padding:8px 11px',
        'border-radius:7px', 'pointer-events:none',
        'max-width:250px', 'box-shadow:0 4px 16px rgba(0,0,0,0.28)',
      ].join(';');
      document.body.appendChild(_ganttTooltip);
    }
    return _ganttTooltip;
  }

  /* Gantt semanal — grade de quadradinhos, 1 coluna = 1 semana */
  function renderGanttChart(id, tasks, onClickTask) {
    /* Descarta qualquer instância ECharts prévia neste container */
    if (_instances[id]) { try { _instances[id].dispose(); } catch (_) {} delete _instances[id]; }
    if (_observers[id]) { try { _observers[id].disconnect(); } catch (_) {} delete _observers[id]; }

    var el = document.getElementById(id);
    if (!el) return;
    el.style.height = 'auto';

    var tip = _getGanttTip();
    tip.style.display = 'none';

    function _e(s) {
      return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function _fmtD(d) {
      return d ? new Date(d).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' }) : '—';
    }

    if (!tasks || !tasks.length) {
      el.innerHTML = '<div style="padding:48px;text-align:center;color:#94a3b8;font-size:13px;">Nenhuma task com datas definidas</div>';
      return;
    }

    var WEEK_MS = 604800000;
    var MONTHS  = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];

    /* Retorna a segunda-feira da semana de uma data */
    function _monStart(d) {
      var dt = new Date(typeof d === 'string' ? d : (d instanceof Date ? d.getTime() : d));
      dt.setHours(0, 0, 0, 0);
      var wd = dt.getDay(); // 0 = Dom
      dt.setDate(dt.getDate() - (wd === 0 ? 6 : wd - 1));
      return dt;
    }

    /* Intervalo global de datas — início mínimo fixo: jan/2026 */
    var minD = new Date(2026, 0, 1);
    var maxD = null;
    tasks.forEach(function (t) {
      if (t.due_date) { var d = new Date(t.due_date); if (!maxD || d > maxD) maxD = d; }
    });
    if (!maxD) maxD = new Date(minD.getTime() + WEEK_MS * 8);

    /* Primeira segunda-feira em ou após 01/jan/2026 */
    var wStart = _monStart(minD);
    if (wStart < minD) wStart = new Date(wStart.getTime() + WEEK_MS);

    /* Lista de semanas: fixada a partir da 1ª seg de jan/2026, sem padding esquerdo */
    var weeks = [];
    var wCur  = wStart;
    var wLast = _monStart(new Date(maxD.getTime() + WEEK_MS * 3));
    while (wCur <= wLast) {
      weeks.push(new Date(wCur));
      wCur = new Date(wCur.getTime() + WEEK_MS);
    }

    var nowMon = _monStart(new Date()).getTime();

    /* Estrutura de linhas (grupos opcionais + tasks) */
    var hasGroups = tasks.some(function (t) { return t.list_name; });
    var rows = [];
    if (hasGroups) {
      var byList = {}, listOrder = [];
      tasks.forEach(function (t, i) {
        var k = t.list_name || '—';
        if (!byList[k]) { byList[k] = []; listOrder.push(k); }
        byList[k].push({ task: t, idx: i });
      });
      listOrder.forEach(function (ln) {
        rows.push({ type: 'group', label: ln });
        byList[ln].forEach(function (item) { rows.push({ type: 'task', task: item.task, origIdx: item.idx }); });
      });
    } else {
      tasks.forEach(function (t, i) { rows.push({ type: 'task', task: t, origIdx: i }); });
    }

    /* Spans de mês para o cabeçalho superior */
    var mSpans = [], prevMK = null;
    weeks.forEach(function (w) {
      var mk = w.getFullYear() * 100 + w.getMonth();
      if (mk !== prevMK) { mSpans.push({ w: w, count: 1 }); prevMK = mk; }
      else mSpans[mSpans.length - 1].count++;
    });

    /* Dimensões em px */
    var NC = 190; /* coluna do nome */
    var WC = 22;  /* coluna de semana */

    /* ── Cabeçalho: linha de meses ── */
    var mhH = '<th style="width:' + NC + 'px;min-width:' + NC + 'px;position:sticky;left:0;z-index:4;background:#f8fafc;border-right:2px solid #e2e8f0;"></th>';
    mSpans.forEach(function (ms) {
      mhH += '<th colspan="' + ms.count + '" style="text-align:left;padding:4px 6px 2px;font-size:10px;color:#94a3b8;font-weight:600;border-right:1px solid #e2e8f0;border-bottom:1px solid #e2e8f0;white-space:nowrap;">'
        + MONTHS[ms.w.getMonth()] + ' ' + ms.w.getFullYear() + '</th>';
    });

    /* ── Cabeçalho: linha de semanas (número do dia) ── */
    var whH = '<th style="width:' + NC + 'px;min-width:' + NC + 'px;position:sticky;left:0;z-index:4;background:#f8fafc;border-right:2px solid #e2e8f0;padding:5px 10px;font-size:10px;color:#6b7280;font-weight:600;text-align:left;border-bottom:2px solid #e2e8f0;">Tarefa</th>';
    weeks.forEach(function (w) {
      var isNow = w.getTime() === nowMon;
      var title = 'Semana de ' + ('0' + w.getDate()).slice(-2) + '/' + ('0' + (w.getMonth() + 1)).slice(-2) + '/' + w.getFullYear();
      whH += '<th title="' + title + '" style="width:' + WC + 'px;min-width:' + WC + 'px;padding:2px 0;text-align:center;font-size:8px;'
        + 'color:' + (isNow ? '#d97706' : '#9ca3af') + ';font-weight:' + (isNow ? '700' : '500') + ';'
        + 'border-right:1px solid #f3f4f6;border-bottom:2px solid #e2e8f0;'
        + 'background:' + (isNow ? '#fffbeb' : 'transparent') + ';">'
        + w.getDate() + '</th>';
    });

    /* ── Linhas de dados ── */
    var bH = '';
    rows.forEach(function (row) {
      if (row.type === 'group') {
        bH += '<tr style="user-select:none"><td colspan="' + (weeks.length + 1)
          + '" style="background:#eff6ff;padding:5px 12px;font-size:10px;font-weight:700;color:#1d4ed8;'
          + 'border-top:2px solid #bfdbfe;border-bottom:1px solid #dbeafe;">'
          + _e(row.label) + '</td></tr>';
        return;
      }

      var t  = row.task;
      var oi = row.origIdx;

      /* Semana de início e semana de término (ambas = segunda da semana) */
      var ts = t.start_date ? _monStart(t.start_date).getTime() : null;
      var te = t.due_date   ? _monStart(t.due_date  ).getTime() : null;
      if (!ts && te) ts = te;
      if (!te && ts) te = ts;

      var color = t.is_done ? '#86efac' : (t.is_overdue ? '#f87171' : (t.status_color || '#93c5fd'));
      var opac  = t.is_done ? '0.7' : '1';
      var nc    = t.is_done ? '#94a3b8' : (t.is_overdue ? '#b91c1c' : '#1e293b');
      var nd    = t.is_done ? 'text-decoration:line-through;' : '';

      /* Células de semana */
      var cH = '';
      weeks.forEach(function (w) {
        var wt    = w.getTime();
        var isNow = wt === nowMon;
        var inR   = ts && te && wt >= ts && wt <= te;
        var isF   = inR && wt === ts;
        var isL   = inR && wt === te;

        var inner = '';
        if (inR) {
          /* Cantos arredondados apenas nas pontas da barra */
          var r = (isF && isL) ? 'border-radius:5px'
                : isF          ? 'border-radius:5px 0 0 5px'
                : isL          ? 'border-radius:0 5px 5px 0'
                : '';
          inner = '<div style="background:' + color + ';' + r + ';opacity:' + opac + ';height:14px;margin:0 1px;"></div>';
        }

        var tdBg = isNow ? '#fffbeb' : '#fff';
        var tdBd = isNow ? '#fde68a' : '#f3f4f6';
        cH += '<td style="background:' + tdBg + ';border-right:1px solid ' + tdBd + ';'
          + 'width:' + WC + 'px;min-width:' + WC + 'px;height:26px;padding:0;">' + inner + '</td>';
      });

      bH += '<tr data-tidx="' + oi + '" style="' + (onClickTask ? 'cursor:pointer;' : '') + '">';
      bH += '<td style="position:sticky;left:0;z-index:2;background:#fff;border-right:2px solid #e2e8f0;'
        + 'border-bottom:1px solid #f8fafc;padding:3px 10px;font-size:10px;'
        + 'color:' + nc + ';' + nd
        + 'width:' + NC + 'px;min-width:' + NC + 'px;max-width:' + NC + 'px;'
        + 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">';
      if (t.is_parent) bH += '<span style="color:#6366f1;margin-right:3px;font-size:9px;">▸</span>';
      bH += _e(t.name) + '</td>';
      bH += cH;
      bH += '</tr>';
    });

    el.innerHTML = [
      '<div style="overflow-x:auto;border-radius:8px;border:1px solid #e2e8f0;">',
        '<table style="border-collapse:collapse;table-layout:fixed;white-space:nowrap;">',
          '<thead><tr>' + mhH + '</tr><tr>' + whH + '</tr></thead>',
          '<tbody>' + bH + '</tbody>',
        '</table>',
      '</div>',
    ].join('');

    var tbody = el.querySelector('tbody');

    /* Tooltip rico ao passar o mouse */
    tbody.addEventListener('mouseover', function (e) {
      var row = e.target.closest('tr[data-tidx]');
      if (!row) { tip.style.display = 'none'; return; }
      var t = tasks[parseInt(row.dataset.tidx, 10)];
      if (!t) return;
      var html = '<div style="font-weight:700;margin-bottom:3px;">' + _e(t.name) + '</div>';
      if (t.list_name) html += '<div style="color:#94a3b8;font-size:10px;margin-bottom:4px;">' + _e(t.list_name) + '</div>';
      html += 'Início: <b>' + _fmtD(t.start_date) + '</b><br>Prazo: <b>' + _fmtD(t.due_date) + '</b>';
      if (t.total_tasks != null) {
        var pct = t.completion_rate != null ? Math.round(t.completion_rate * 100) : 0;
        html += '<br>Tarefas: <b>' + (t.completed_tasks || 0) + '/' + t.total_tasks + '</b> (' + pct + '%)';
        if (t.overdue_tasks) html += '<br><span style="color:#f87171">⚠ ' + t.overdue_tasks + ' em atraso</span>';
      } else {
        if (t.assignees && t.assignees.length) html += '<br>Resp.: ' + _e(t.assignees.join(', '));
      }
      if (t.is_done)         html += '<br><span style="color:#86efac">✓ Concluída</span>';
      else if (t.is_overdue) html += '<br><span style="color:#f87171">⚠ Em atraso</span>';
      tip.innerHTML = html;
      tip.style.display = 'block';
    });
    tbody.addEventListener('mousemove', function (e) {
      var x = e.clientX + 14, y = e.clientY - 8;
      if (x + 256 > window.innerWidth)  x = e.clientX - 256 - 14;
      if (y + 130 > window.innerHeight) y = e.clientY - 130;
      tip.style.left = x + 'px';
      tip.style.top  = y + 'px';
    });
    tbody.addEventListener('mouseleave', function () { tip.style.display = 'none'; });

    /* Clique para navegar até a task */
    if (onClickTask) {
      tbody.addEventListener('click', function (e) {
        var row = e.target.closest('tr[data-tidx]');
        if (!row) return;
        var idx = parseInt(row.dataset.tidx, 10);
        if (!isNaN(idx) && tasks[idx]) onClickTask(tasks[idx]);
      });
    }
  }

  /* Gráfico de linha — evolução temporal ponderada das províncias.
     provinces: [{folder_id, name, current_progress, start_date, points:[{date, progress}]}]
     Ordenadas por current_progress desc (já vem assim do backend). */
  function renderEvolutionChart(id, provinces) {
    const chart = _init(id);
    if (!chart) return;

    if (!provinces || !provinces.length) {
      chart.setOption({
        graphic: [{ type: 'text', left: 'center', top: 'middle',
          style: { text: 'Nenhum dado de evolução disponível', fontSize: 13, fill: '#94a3b8' } }],
      });
      return;
    }

    var COLORS = [
      '#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6',
      '#06b6d4','#ec4899','#84cc16','#f97316','#14b8a6',
      '#6366f1','#fb923c','#22c55e','#e879f9','#fbbf24',
      '#38bdf8','#4ade80','#f87171','#818cf8','#34d399',
    ];

    var todayMs = Date.now();

    /* Filtra províncias com ao menos 2 pontos (sem dados de histórico não há linha) */
    var active = provinces.filter(function (p) { return p.points && p.points.length >= 1; });

    var series = active.map(function (p, i) {
      var color = COLORS[i % COLORS.length];
      var pct = Math.round((p.current_progress || 0) * 100);
      var data = (p.points || []).map(function (pt) {
        return [new Date(pt.date).getTime(), Math.round((pt.progress || 0) * 100)];
      });
      return {
        name: p.name,
        type: 'line',
        smooth: 0.3,
        symbol: 'circle',
        symbolSize: function (val) { return val[1] > 0 ? 5 : 3; },
        data: data,
        lineStyle: { width: 2, color: color },
        itemStyle: { color: color },
        endLabel: {
          show: true,
          color: color,
          fontSize: 9,
          fontWeight: 'bold',
          formatter: function (params) {
            return params.seriesName.substring(0, 12) + ' ' + pct + '%';
          },
        },
        emphasis: { focus: 'series' },
      };
    });

    /* Linha vertical "Hoje" */
    series.push({
      type: 'scatter',
      data: [],
      markLine: {
        symbol: 'none',
        label: { show: true, formatter: 'Hoje', position: 'insideStartTop', fontSize: 9, color: '#dc2626' },
        lineStyle: { color: '#dc2626', width: 1.5, type: 'dashed' },
        data: [{ xAxis: todayMs }],
      },
    });

    chart.setOption({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross', snap: true },
        formatter: function (params) {
          var realParams = params.filter(function (p) { return p.seriesType === 'line'; });
          if (!realParams.length) return '';
          var dateStr = new Date(realParams[0].value[0]).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' });
          var sorted = realParams.slice().sort(function (a, b) { return b.value[1] - a.value[1]; });
          return '<div style="font-size:11px"><b>' + dateStr + '</b><br/>' +
            sorted.map(function (p) {
              return p.marker + ' ' + p.seriesName + ': <b>' + p.value[1] + '%</b>';
            }).join('<br/>') + '</div>';
        },
      },
      legend: {
        data: active.map(function (p) { return p.name; }),
        /* Oculta por padrão as províncias sem progresso; clique na legenda para exibir */
        selected: active.reduce(function (acc, p) {
          acc[p.name] = p.current_progress > 0;
          return acc;
        }, {}),
        bottom: 0,
        left: 'center',
        type: 'scroll',
        textStyle: { fontSize: 10 },
        pageTextStyle: { fontSize: 10 },
        itemWidth: 14,
        itemHeight: 8,
      },
      grid: { left: '1%', right: '12%', top: 16, bottom: 56, containLabel: true },
      xAxis: {
        type: 'time',
        axisLabel: {
          fontSize: 10,
          color: '#6b7280',
          formatter: function (val) {
            return new Date(val).toLocaleDateString('pt-BR', { month: 'short', year: '2-digit' });
          },
        },
        splitLine: { lineStyle: { color: '#f3f4f6' } },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 100,
        axisLabel: { fontSize: 10, color: '#6b7280', formatter: function (v) { return v + '%'; } },
        splitLine: { lineStyle: { color: '#f3f4f6' } },
      },
      series: series,
    });
  }

  return { renderProgressBars, renderStatusDonut, renderOverdueByAssignee, renderAssigneeChart, renderGanttChart, renderEvolutionChart, disposeAll };
})();
