/* Wrappers ECharts para o dashboard */

/* O tema 'u2dark' e os helpers U2_DARK/U2_TRACK vêm de echarts-theme-u2.js,
   carregado antes deste arquivo nos templates. */

const Charts = (function () {
  // Rótulos de gráfico: traduzidos aqui, antes de o ECharts medir e desenhar.
  const T = function (text) { return window.U2I18n ? window.U2I18n.t(text) : text; };
  const LOCALE = window.U2I18n && window.U2I18n.lang === 'en' ? 'en-GB' : 'pt-BR';
  const L_DONE = T('Concluídas');
  const L_OPEN = T('Em aberto');
  const _instances = {};
  const _observers = {};
  var _ganttTooltip = null;
  /* Faixa zebrada vermelho/branco das pausas, a mesma do PDF e do XLSX */
  var PAUSE_ZEBRA = 'repeating-linear-gradient(45deg,#dc2626 0 3px,#ffffff 3px 6px)';

  function _init(id) {
    if (_instances[id]) { _instances[id].dispose(); }
    if (_observers[id]) { _observers[id].disconnect(); delete _observers[id]; }
    const el = document.getElementById(id);
    if (!el) return null;
    const chart = echarts.init(el, U2_DARK() ? 'u2dark' : null, { renderer: 'svg' });
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
  function renderProgressBars(id, items, labelKey, completedKey, totalKey, asPercent, onClickItem, rateKey) {
    const chart = _init(id);
    if (!chart) return;

    const names = items.map(function (i) { return i[labelKey]; });

    var completed, open, xMax, xFmt, tooltipFmt;
    if (asPercent) {
      // Quando rateKey é passado, a % exibida vem do cálculo ponderado (EVM) do
      // backend, não da razão bruta completed/total — mesma fonte usada pelos
      // cards e relatórios, para manter consistência visual.
      var pctOf = function (i) {
        if (rateKey && i[rateKey] != null) return Math.round(i[rateKey] * 100);
        var t = i[totalKey]; return t > 0 ? Math.round(i[completedKey] / t * 100) : 0;
      };
      completed = items.map(pctOf);
      open = items.map(function (i) { return 100 - pctOf(i); });
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
          var count = p.seriesName === L_DONE ? done : pending;
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
      legend: { data: [L_DONE, L_OPEN], bottom: 0, textStyle: { fontSize: 11 } },
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
          name: L_DONE,
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
            color: (U2_DARK() ? '#06281a' : '#166534'),
          },
        },
        {
          name: L_OPEN,
          type: 'bar',
          stack: 'total',
          data: open,
          itemStyle: { color: (U2_DARK() ? U2_TRACK : '#e2e8f0'), borderRadius: [0, 3, 3, 0], cursor: onClickItem ? 'pointer' : 'default' },
          // Em percentual só a parte concluída leva rótulo: o "100%" da parte em
          // aberto de uma província a 0% lia-se como 100% concluído.
          label: {
            show: !asPercent,
            position: 'inside',
            formatter: function (p) { return p.value || ''; },
            fontSize: 10,
            color: (U2_DARK() ? '#8b8b93' : '#64748b'),
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
      return { name: T(name), value: value, itemStyle: { color: color } };
    });

    // Todos os status entram na rosca. "Planejando" já veio oculto por padrão, mas
    // sem ele a rosca ficava quase toda verde — parecia que estava tudo concluído.
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
        : [T('Sem responsável')];
      names.forEach(function (n) { counts[n] = (counts[n] || 0) + 1; });
    });

    const sorted = Object.entries(counts).sort(function (a, b) { return b[1] - a[1]; }).slice(0, 10);
    if (!sorted.length) {
      chart.setOption({
        graphic: [{
          type: 'text',
          left: 'center', top: 'middle',
          style: { text: T('✓ Nenhuma task em atraso'), fontSize: 13, fill: '#94a3b8' },
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
  function renderAssigneeChart(id, data, onClickAssignee) {
    const chart = _init(id);
    if (!chart) return;

    if (!data || !data.length) {
      chart.setOption({
        graphic: [{ type: 'text', left: 'center', top: 'middle',
          style: { text: T('Nenhum responsável atribuído'), fontSize: 13, fill: '#94a3b8' } }],
      });
      return;
    }

    var top = data.slice(0, 20);
    var barData = top.map(function (d) {
      var total = d.open + d.completed;
      var rate  = total > 0 ? d.completed / total : 0;
      var color = rate >= 0.7 ? '#4ade80' : rate >= 0.35 ? '#fbbf24' : '#f87171';
      return { value: total, rate: rate, open: d.open, completed: d.completed,
               overdue: d.overdue,
               itemStyle: { color: color, borderRadius: [4, 4, 0, 0],
                            cursor: onClickAssignee ? 'pointer' : 'default' } };
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
            (d.overdue ? '<br/><span style="color:#f87171">Em atraso: <b>' + d.overdue + '</b></span>' : '') +
            (onClickAssignee ? '<br/><span style="opacity:.65">clique para ver as tarefas</span>' : '');
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
        splitLine: { lineStyle: { color: (U2_DARK() ? U2_TRACK : '#f1f5f9') } },
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

    if (onClickAssignee) {
      chart.off('click');
      chart.on('click', function (params) {
        var row = top[params.dataIndex];
        if (row) { onClickAssignee(row.assignee); }
      });
      /* O clique só pega na barra; o rótulo do eixo é o alvo mais fácil num
         gráfico com poucas pessoas. */
      chart.getZr().on('click', function (ev) {
        if (ev.target) return;                       // já tratado pelo chart.on acima
        var pt = [ev.offsetX, ev.offsetY];
        if (!chart.containPixel({ gridIndex: 0 }, pt)) {
          var idx = chart.convertFromPixel({ xAxisIndex: 0 }, pt[0]);
          var row = top[idx];
          if (row) { onClickAssignee(row.assignee); }
        }
      });
    }
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
      return d ? new Date(d).toLocaleDateString(LOCALE, { day: '2-digit', month: '2-digit', year: 'numeric' }) : '—';
    }

    if (!tasks || !tasks.length) {
      el.innerHTML = '<div style="padding:48px;text-align:center;color:#94a3b8;font-size:13px;">Nenhuma task com datas definidas</div>';
      return;
    }

    var WEEK_MS = 604800000;
    var MONTHS  = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];

    /* "AAAA-MM-DD" → meia-noite local (new Date("AAAA-MM-DD") seria UTC e mudaria o dia) */
    function _localDay(s) {
      var p = String(s).slice(0, 10).split('-');
      return new Date(+p[0], +p[1] - 1, +p[2]).getTime();
    }

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

      /* Pausas: os dias parados, por semana (0 = segunda … 6 = domingo) — a faixa zebrada
         cobre só a fatia desses dias na célula, não a semana inteira */
      var pauseDays = (t.pauses || []).map(function (p) { return [_localDay(p.start), _localDay(p.end)]; });
      function _pauseRuns(wt) {
        var days = [];
        for (var i = 0; i < 7; i++) {
          var d = wt + i * 86400000;
          days.push(pauseDays.some(function (r) { return d >= r[0] && d <= r[1]; }));
        }
        var runs = [], i0 = -1;
        for (var j = 0; j <= 7; j++) {
          if (j < 7 && days[j]) { if (i0 < 0) i0 = j; }
          else if (i0 >= 0) { runs.push([i0, j - 1]); i0 = -1; }
        }
        return runs;
      }
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
        _pauseRuns(wt).forEach(function (run) {
          inner += '<div style="position:absolute;top:6px;height:14px;left:' + (run[0] / 7 * 100) + '%;'
            + 'width:' + ((run[1] - run[0] + 1) / 7 * 100) + '%;background:' + PAUSE_ZEBRA + ';'
            + 'box-shadow:inset 0 0 0 1px #dc2626;"></div>';
        });

        var tdBg = isNow ? '#fffbeb' : '#fff';
        var tdBd = isNow ? '#fde68a' : (U2_DARK() ? U2_TRACK : '#f3f4f6');
        cH += '<td style="position:relative;background:' + tdBg + ';border-right:1px solid ' + tdBd + ';'
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
      (t.pauses || []).forEach(function (p) {
        html += '<br><span style="color:#fca5a5">⏸ ' + T('Pausa') + ' ' + _fmtD(p.start) + ' – '
          + (p.open ? T('até nova ordem') : _fmtD(p.end)) + (p.reason ? ' · ' + _e(p.reason) : '') + '</span>';
      });
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
          style: { text: T('Nenhum dado de evolução disponível'), fontSize: 13, fill: '#94a3b8' } }],
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
        label: { show: true, formatter: T('Hoje'), position: 'insideStartTop', fontSize: 9, color: '#dc2626' },
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
          var dateStr = new Date(realParams[0].value[0]).toLocaleDateString(LOCALE, { day: '2-digit', month: '2-digit', year: 'numeric' });
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
            return new Date(val).toLocaleDateString(LOCALE, { month: 'short', year: '2-digit' });
          },
        },
        splitLine: { lineStyle: { color: (U2_DARK() ? U2_TRACK : '#f3f4f6') } },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 100,
        axisLabel: { fontSize: 10, color: '#6b7280', formatter: function (v) { return v + '%'; } },
        splitLine: { lineStyle: { color: (U2_DARK() ? U2_TRACK : '#f3f4f6') } },
      },
      series: series,
    });
  }


  /* ── Gantt detalhado de uma província ─────────────────────────────────────
     A mesma árvore do PDF — disciplina → grupo → tarefa — com as colunas de
     data e %, as barras planejado/executado e a linha de hoje.

     `data` vem de GET /dashboard/gantt/folder/<id>/detail, que é o mesmo
     _build_data que gera o PDF e o XLSX. Os três mostram os mesmos números de
     propósito: o cliente olha a tela e depois imprime o PDF.

     Não é ECharts: são divs posicionados por dia. Um gráfico de barras do
     ECharts não dá hierarquia indentada, colunas congeladas nem a zebra das
     pausas sem virar uma pilha de contornos. */
  function renderGanttDetail(id, data, onClickTask) {
    if (_instances[id]) { try { _instances[id].dispose(); } catch (_) {} delete _instances[id]; }
    if (_observers[id]) { try { _observers[id].disconnect(); } catch (_) {} delete _observers[id]; }

    var el = document.getElementById(id);
    if (!el) return;

    var tip = _getGanttTip();
    tip.style.display = 'none';

    function _e(s) {
      return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    var dark = U2_DARK();
    /* A estrutura é a do PDF; as cores seguem o tema da aplicação — um quadro
       branco no meio da página escura saltava à vista. */
    var C = dark
      ? { head: '#1c1c20', headTx: '#f4f4f2', headSub: '#a1a1aa', band: '#232327',
          line: '#2a2a2e', grid: '#242428', stripe: '#131315', bg: '#161618',
          tx: '#c9c9cf', dim: '#8b8b93', strong: '#f4f4f2',
          track: '#1e365f', trackLate: '#4a1d1d', summary: '#7a7a84' }
      : { head: '#1a1a1a', headTx: '#ffffff', headSub: '#d4d4d4', band: '#f1f1f1',
          line: '#e2e8f0', grid: '#eff1f4', stripe: '#f8f8f8', bg: '#ffffff',
          tx: '#334155', dim: '#64748b', strong: '#0f172a',
          track: '#bfdbfe', trackLate: '#fecaca', summary: '#636363' };
    var BAR = '#3b82f6';    /* parte executada */
    var DONE = dark ? '#34d399' : '#16a34a';
    var LATE = '#dc2626';   /* atraso e linha de hoje */

    var MONTHS = (window.U2I18n && window.U2I18n.lang === 'en')
      ? ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
      : ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];

    /* Datas em UTC: são dias puros ("AAAA-MM-DD"); lidas no fuso local, o
       horário de verão deslocaria uma barra num dia. */
    var DAY = 86400000;
    function _ms(s) {
      var p = String(s).slice(0, 10).split('-');
      return Date.UTC(+p[0], +p[1] - 1, +p[2]);
    }
    function _fmt(ms) {
      var d = new Date(ms);
      return ('0' + d.getUTCDate()).slice(-2) + '/' + ('0' + (d.getUTCMonth() + 1)).slice(-2)
        + '/' + d.getUTCFullYear();
    }

    var lists = data.lists || [];
    if (!lists.length) {
      el.innerHTML = '<div style="padding:48px;text-align:center;color:' + C.dim + ';font-size:13px;">'
        + _e(T('Nenhuma tarefa com datas definidas')) + '</div>';
      return;
    }

    var start = _ms(data.range_start);
    var end = _ms(data.range_end);
    var today = _ms(data.today);
    var totalDays = Math.round((end - start) / DAY) + 1;

    /* A coluna do nome encolhe em tela estreita (a app também roda embutida no
       Nextcloud): fixa em 300 px, as quatro colunas congeladas não deixavam
       sobrar linha do tempo nenhuma. */
    var NAME_W = Math.max(190, Math.min(300, Math.round((el.clientWidth || 1200) * 0.28)));
    var DATE_W = 82, PCT_W = 48;
    var ROW_H = 22;

    var weeks = [];
    for (var wms = start; wms <= end; wms += 7 * DAY) weeks.push(wms);

    /* A semana estica para a linha do tempo ocupar a largura que há — numa obra
       de dois meses, 32 px por semana deixavam a barra de um dia com 4 px e
       metade da tela vazia. Acima disso (cronograma longo) fica nos 32 e rola. */
    var frozenW = NAME_W + 2 * DATE_W + PCT_W;
    /* -20: a borda do quadro e a barra de rolagem vertical, que só aparece
       depois de o conteúdo existir — sem a folga, a tabela nasce com uma
       rolagem horizontal de poucos pixels. */
    var avail = Math.max(280, (el.clientWidth || 1200) - frozenW - 20);
    var WEEK_W = Math.max(32, Math.floor(avail / weeks.length));
    var tlW = weeks.length * WEEK_W;
    var dayW = tlW / totalDays;

    /* Posição em px de uma data dentro da linha do tempo */
    function X(ms) { return Math.round((ms - start) / DAY * dayW * 10) / 10; }

    var todayX = (today >= start && today <= end) ? X(today) + dayW / 2 : null;

    /* ── cabeçalho: meses ── */
    var mHtml = '';
    var first = new Date(start);
    var cur = Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), 1);
    while (cur <= end) {
      var d0 = new Date(cur);
      var nextM = Date.UTC(d0.getUTCFullYear(), d0.getUTCMonth() + 1, 1);
      var mx0 = X(Math.max(cur, start));
      var mx1 = X(Math.min(nextM, end + DAY));
      if (mx1 - mx0 >= 18) {
        mHtml += '<div style="position:absolute;left:' + mx0 + 'px;width:' + (mx1 - mx0) + 'px;'
          + 'top:0;height:100%;border-left:1px solid ' + (dark ? '#33333a' : '#3a3a3a') + ';'
          + 'font-size:9.5px;font-weight:600;color:' + C.headSub + ';padding-left:4px;'
          + 'line-height:17px;overflow:hidden;white-space:nowrap;box-sizing:border-box;">'
          + MONTHS[d0.getUTCMonth()] + '/' + d0.getUTCFullYear() + '</div>';
      }
      cur = nextM;
    }

    /* ── cabeçalho: semanas (a segunda-feira de cada uma, dd/mm) ── */
    var labelEvery = Math.max(1, Math.ceil(30 / WEEK_W));
    var wHtml = '';
    weeks.forEach(function (ms, i) {
      var left = X(ms);
      wHtml += '<div style="position:absolute;left:' + left + 'px;top:0;height:100%;'
        + 'border-left:1px solid ' + C.line + ';"></div>';
      if (i % labelEvery === 0 && tlW - left >= 26) {
        var d = new Date(ms);
        wHtml += '<div style="position:absolute;left:' + (left + 2) + 'px;top:0;'
          + 'font-size:8.5px;color:' + C.dim + ';line-height:15px;white-space:nowrap;">'
          + ('0' + d.getUTCDate()).slice(-2) + '/' + ('0' + (d.getUTCMonth() + 1)).slice(-2)
          + '</div>';
      }
    });
    if (todayX !== null) {
      wHtml += '<div style="position:absolute;left:' + (todayX - 1) + 'px;bottom:0;'
        + 'width:2px;height:4px;background:' + LATE + ';"></div>';
    }

    /* ── as barras de uma linha ── */
    function lane(row) {
      var x0 = X(_ms(row.start));
      var x1 = Math.max(X(_ms(row.end) + DAY), x0 + 3);
      var w = x1 - x0;
      var h = '';

      weeks.forEach(function (ms, i) {
        if (i === 0) return;
        h += '<div style="position:absolute;left:' + X(ms) + 'px;top:0;bottom:0;width:1px;'
          + 'background:' + C.grid + ';"></div>';
      });
      if (todayX !== null) {
        h += '<div style="position:absolute;left:' + (todayX - 0.5) + 'px;top:0;bottom:0;'
          + 'width:1px;background:' + LATE + ';opacity:.5;"></div>';
      }

      if (row.is_summary) {
        /* Resumo: barra achatada com as pontas viradas para baixo, como no PDF */
        var sc = row.is_overdue && !row.is_done ? LATE : C.summary;
        h += '<div style="position:absolute;left:' + x0 + 'px;width:' + w + 'px;top:7px;'
          + 'height:4px;background:' + sc + ';"></div>'
          + '<div style="position:absolute;left:' + x0 + 'px;width:2px;top:7px;height:9px;background:' + sc + ';"></div>'
          + '<div style="position:absolute;left:' + (x1 - 2) + 'px;width:2px;top:7px;height:9px;background:' + sc + ';"></div>';
      } else {
        var share = row.is_done ? 1 : Math.min(Math.max((row.progress_pct || 0) / 100, 0), 1);
        h += '<div style="position:absolute;left:' + x0 + 'px;width:' + w + 'px;top:5px;'
          + 'height:12px;border-radius:2px;background:' + (row.is_overdue ? C.trackLate : C.track) + ';"></div>';
        if (share > 0) {
          h += '<div style="position:absolute;left:' + x0 + 'px;width:' + (w * share) + 'px;top:5px;'
            + 'height:12px;border-radius:2px;background:'
            + (row.is_done ? DONE : row.is_overdue ? LATE : BAR) + ';"></div>';
        }
      }

      /* Pausas: a própria aparece onde estiver (antes da barra explica o atraso);
         a herdada da tarefa-mãe, só no trecho desta barra — igual ao PDF. */
      (row.pauses || []).forEach(function (p) {
        var lo = p.own ? Math.max(_ms(p.start), start)
          : Math.max(_ms(p.start), _ms(row.start), start);
        var hi = p.own ? Math.min(_ms(p.end), end)
          : Math.min(_ms(p.end), _ms(row.end), end);
        if (hi < lo) return;
        var px = X(lo), pw = Math.max(X(hi + DAY) - px, 2);
        h += '<div style="position:absolute;left:' + px + 'px;width:' + pw + 'px;'
          + 'top:' + (row.is_summary ? 6 : 5) + 'px;height:' + (row.is_summary ? 6 : 12) + 'px;'
          + 'background:' + PAUSE_ZEBRA + ';box-shadow:inset 0 0 0 1px ' + LATE + ';"></div>';
      });
      return h;
    }

    /* ── corpo ── */
    var flat = [];        /* índice no DOM → linha, para tooltip e clique */
    var body = '';
    lists.forEach(function (lst) {
      body += '<tr><td colspan="4" style="position:sticky;left:0;z-index:3;background:' + C.band + ';'
        + 'border-bottom:1px solid ' + C.line + ';border-left:3px solid ' + C.strong + ';'
        + 'padding:4px 10px;font-size:10px;font-weight:700;letter-spacing:.4px;color:' + C.strong + ';'
        + 'white-space:nowrap;box-sizing:border-box;">' + _e(String(lst.name).toUpperCase()) + '</td>'
        + '<td style="background:' + C.band + ';border-bottom:1px solid ' + C.line + ';"></td></tr>';

      lst.rows.forEach(function (row, n) {
        var i = flat.length;
        flat.push(row);
        var bg = (n % 2) ? C.bg : C.stripe;
        var color = row.is_done ? C.dim : row.is_overdue ? LATE
          : row.is_summary ? C.strong : C.tx;
        var weight = row.is_summary ? '700' : '400';
        var indent = 8 + row.level * 13;
        var pct = row.progress_pct == null ? '—'
          : (Math.round(row.progress_pct * 10) / 10) + '%';

        var td = 'border-bottom:1px solid ' + C.grid + ';background:' + bg + ';height:' + ROW_H + 'px;';
        var sticky = 'position:sticky;z-index:2;' + td;

        body += '<tr data-row="' + i + '" style="cursor:' + (onClickTask ? 'pointer' : 'default') + ';">'
          + '<td style="' + sticky + 'left:0;padding-left:' + indent + 'px;padding-right:6px;'
          + 'font-size:11px;font-weight:' + weight + ';color:' + color + ';'
          + (row.is_done ? 'text-decoration:line-through;' : '')
          + 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
          + _e(row.name) + '</td>'
          + '<td style="' + sticky + 'left:' + NAME_W + 'px;text-align:center;font-size:10px;color:' + C.dim + ';">'
          + _fmt(_ms(row.start)) + '</td>'
          + '<td style="' + sticky + 'left:' + (NAME_W + DATE_W) + 'px;text-align:center;font-size:10px;color:' + C.dim + ';">'
          + _fmt(_ms(row.end)) + '</td>'
          + '<td style="' + sticky + 'left:' + (NAME_W + 2 * DATE_W) + 'px;text-align:center;font-size:10px;'
          + 'font-weight:' + weight + ';color:' + color + ';border-right:1px solid ' + C.line + ';">'
          + pct + '</td>'
          + '<td style="' + td + 'position:relative;padding:0;">' + lane(row) + '</td>'
          + '</tr>';
      });
    });

    /* ── cabeçalho congelado ── */
    function headCell(label, width, left, align) {
      return '<th rowspan="2" style="position:sticky;top:0;left:' + left + 'px;z-index:6;'
        + 'width:' + width + 'px;min-width:' + width + 'px;background:' + C.head + ';color:' + C.headTx + ';'
        + 'font-size:10px;font-weight:700;text-align:' + align + ';padding:0 8px;height:33px;'
        + 'white-space:nowrap;box-sizing:border-box;">' + _e(label) + '</th>';
    }

    var head =
      '<tr>'
      + headCell(T('Tarefa'), NAME_W, 0, 'left')
      + headCell(T('Início'), DATE_W, NAME_W, 'center')
      + headCell(T('Término'), DATE_W, NAME_W + DATE_W, 'center')
      + headCell('%', PCT_W, NAME_W + 2 * DATE_W, 'center')
      + '<th style="position:sticky;top:0;z-index:5;background:' + C.head + ';padding:0;'
      + 'width:' + tlW + 'px;min-width:' + tlW + 'px;height:17px;">'
      + '<div style="position:relative;width:' + tlW + 'px;height:17px;">' + mHtml + '</div></th>'
      + '</tr>'
      + '<tr><th style="position:sticky;top:17px;z-index:5;background:' + C.bg + ';padding:0;'
      + 'border-bottom:1px solid ' + C.line + ';height:16px;">'
      + '<div style="position:relative;width:' + tlW + 'px;height:16px;">' + wHtml + '</div></th></tr>';

    /* ── legenda ──
       Montada aqui, e não no app.js, porque as cores são as da paleta acima:
       separadas, a legenda dizia "planejado é azul claro" enquanto a barra no
       tema escuro é azul-marinho. */
    function sw(bg, label, extra) {
      return '<span style="display:inline-flex;align-items:center;gap:4px;">'
        + '<span style="width:11px;height:11px;border-radius:2px;background:' + bg + ';'
        + (extra || '') + '"></span>' + _e(label) + '</span>';
    }
    var legend = '<div style="display:flex;flex-wrap:wrap;gap:14px;align-items:center;'
      + 'font-size:10.5px;color:' + C.dim + ';margin-bottom:8px;">'
      + sw(C.track, T('Planejado'))
      + sw(BAR, T('Executado'))
      + sw(DONE, T('Concluída'))
      + sw(LATE, T('Em atraso'))
      + sw(C.summary, T('Resumo'))
      + sw(PAUSE_ZEBRA, T('Pausa'), 'box-shadow:inset 0 0 0 1px ' + LATE + ';')
      + '<span style="display:inline-flex;align-items:center;gap:4px;">'
      + '<span style="width:2px;height:12px;background:' + LATE + ';"></span>'
      + _e(T('Hoje')) + ' (' + _fmt(today) + ')</span></div>';

    var note = '';
    if ((data.undated_lists || []).length) {
      note = '<p style="margin:8px 0 0;font-size:10.5px;color:' + C.dim + ';">'
        + _e(T('Sem datas definidas')) + ': <span data-no-i18n>'
        + _e(data.undated_lists.join(', ')) + '</span></p>';
    }

    el.innerHTML = legend
      + '<div class="gd-scroll" style="overflow:auto;max-height:calc(100vh - 255px);'
      + 'border:1px solid ' + C.line + ';border-radius:8px;background:' + C.bg + ';">'
      /* A largura explícita não é decoração: `table-layout:fixed` só vale com
         ela. Sem, o navegador cai no algoritmo automático e estica a coluna do
         nome até caber o nome mais comprido, empurrando a linha do tempo para
         fora da tela. */
      + '<table style="width:' + (frozenW + tlW) + 'px;table-layout:fixed;'
      + 'border-collapse:separate;border-spacing:0;">'
      + '<thead>' + head + '</thead><tbody>' + body + '</tbody></table></div>'
      + note;

    /* ── tooltip ── */
    var tbody = el.querySelector('tbody');
    tbody.addEventListener('mouseover', function (ev) {
      var tr = ev.target.closest('tr[data-row]');
      if (!tr) { tip.style.display = 'none'; return; }
      var row = flat[+tr.dataset.row];
      if (!row) return;
      var html = '<div style="font-weight:700;margin-bottom:3px;">' + _e(row.name) + '</div>'
        + T('Início') + ': <b>' + _fmt(_ms(row.start)) + '</b><br>'
        + T('Término') + ': <b>' + _fmt(_ms(row.end)) + '</b>';
      if (row.duration_days != null) {
        html += '<br>' + T('Duração') + ': <b>' + row.duration_days + ' ' + T('dias') + '</b>';
      }
      if (row.progress_pct != null) {
        html += '<br>' + T('Progresso') + ': <b>' + (Math.round(row.progress_pct * 10) / 10) + '%</b>';
      }
      if (row.status) html += '<br>' + T('Status') + ': ' + _e(row.status);
      if (row.is_done) html += '<br><span style="color:#86efac">&#10003; ' + T('Concluída') + '</span>';
      else if (row.is_overdue) html += '<br><span style="color:#f87171">&#9888; ' + T('Em atraso') + '</span>';
      (row.pauses || []).forEach(function (p) {
        html += '<br><span style="color:#fca5a5">&#9208; ' + T('Pausa') + ' ' + _fmt(_ms(p.start)) + ' – '
          + (p.open ? T('até nova ordem') : _fmt(_ms(p.end)))
          + (p.reason ? ' · ' + _e(p.reason) : '') + '</span>';
      });
      tip.innerHTML = html;
      tip.style.display = 'block';
    });
    tbody.addEventListener('mousemove', function (ev) {
      var px = ev.clientX + 14, py = ev.clientY - 8;
      if (px + 256 > window.innerWidth) px = ev.clientX - 256 - 14;
      if (py + 150 > window.innerHeight) py = ev.clientY - 150;
      tip.style.left = px + 'px';
      tip.style.top = py + 'px';
    });
    tbody.addEventListener('mouseleave', function () { tip.style.display = 'none'; });

    if (onClickTask) {
      tbody.addEventListener('click', function (ev) {
        var tr = ev.target.closest('tr[data-row]');
        if (!tr) return;
        var row = flat[+tr.dataset.row];
        if (row) onClickTask(row);
      });
    }

    /* Abre já com hoje à vista: num cronograma de um ano o início fica longe à
       esquerda e a tela abriria num trecho que já passou. */
    if (todayX !== null) {
      var scroller = el.querySelector('.gd-scroll');
      scroller.scrollLeft = Math.max(0, todayX - (scroller.clientWidth - frozenW) / 3);
    }
  }

  return { renderProgressBars, renderStatusDonut, renderOverdueByAssignee, renderAssigneeChart, renderGanttChart, renderGanttDetail, renderEvolutionChart, disposeAll };
})();
