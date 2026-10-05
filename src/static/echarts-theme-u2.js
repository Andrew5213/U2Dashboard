/* Tema escuro do ECharts + helpers de cor, compartilhados por todas as telas
   que desenham gráficos (dashboard, chat, e as variantes mobile de ambos).
   Fica fora de charts.js porque o chat não carrega aquele arquivo. */

/* Tema escuro U2 — cores de u2broadcast.engenhariarf.com.
   Sem isto o ECharts desenha eixos, legendas e tooltips em cinza-escuro, que
   some no fundo preto. Registrado uma vez e aplicado no _init(). */
if (window.echarts) {
  echarts.registerTheme('u2dark', {
    darkMode: true,
    backgroundColor: 'transparent',
    textStyle: { color: '#c9c9cf', fontFamily: 'Archivo, "Segoe UI", system-ui, sans-serif' },
    title: { textStyle: { color: '#f4f4f2' }, subtextStyle: { color: '#8b8b93' } },
    legend: { textStyle: { color: '#c9c9cf' }, inactiveColor: '#4a4a52' },
    tooltip: {
      backgroundColor: '#161618',
      borderColor: '#2a2a2e',
      borderWidth: 1,
      textStyle: { color: '#f4f4f2' },
      axisPointer: { lineStyle: { color: '#2a2a2e' }, crossStyle: { color: '#2a2a2e' } },
    },
    categoryAxis: {
      axisLine: { lineStyle: { color: '#2a2a2e' } },
      axisTick: { lineStyle: { color: '#2a2a2e' } },
      axisLabel: { color: '#8b8b93' },
      splitLine: { lineStyle: { color: '#1c1c20' } },
      splitArea: { areaStyle: { color: ['rgba(255,255,255,0.02)', 'transparent'] } },
    },
    valueAxis: {
      axisLine: { lineStyle: { color: '#2a2a2e' } },
      axisTick: { lineStyle: { color: '#2a2a2e' } },
      axisLabel: { color: '#8b8b93' },
      splitLine: { lineStyle: { color: '#1c1c20' } },
    },
    timeAxis: {
      axisLine: { lineStyle: { color: '#2a2a2e' } },
      axisLabel: { color: '#8b8b93' },
      splitLine: { lineStyle: { color: '#1c1c20' } },
    },
    timeline: { lineStyle: { color: '#2a2a2e' }, label: { color: '#8b8b93' } },
  });
}

/* Trilho das barras "em aberto". Mais claro que --u2-panel-2 de propósito:
   a #1c1c20 o retângulo somia contra o card (#161618) e o gráfico parecia vazio. */
var U2_TRACK = '#2e2e34';
var U2_DARK = function () {
  return document.body && document.body.classList.contains('theme-dark');
};
