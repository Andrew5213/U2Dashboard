/* SSE client com reconexão exponencial */
(function () {
  const MAX_RETRIES = 10;
  const BASE_DELAY  = 1000;
  const MAX_DELAY   = 30000;

  let es = null;
  let retries = 0;
  let fallbackTimer = null;

  function setStatus(connected) {
    const dot   = document.getElementById('sse-dot');
    const label = document.getElementById('sse-label');
    if (!dot || !label) return;
    if (connected) {
      dot.className   = 'w-2 h-2 rounded-full bg-emerald-400 transition-colors';
      label.textContent = 'ao vivo';
    } else {
      dot.className   = 'w-2 h-2 rounded-full bg-amber-400 transition-colors';
      label.textContent = 'reconectando…';
    }
  }

  function startFallback() {
    if (fallbackTimer) return;
    fallbackTimer = setInterval(function () {
      document.dispatchEvent(new CustomEvent('dashboard-poll'));
    }, 30000);
  }

  function stopFallback() {
    if (fallbackTimer) {
      clearInterval(fallbackTimer);
      fallbackTimer = null;
    }
  }

  function connect() {
    if (es) { es.close(); es = null; }

    es = new EventSource('/dashboard/stream');

    es.addEventListener('open', function () {
      retries = 0;
      setStatus(true);
      stopFallback();
    });

    es.addEventListener('update', function (e) {
      try {
        const data = JSON.parse(e.data);
        document.dispatchEvent(new CustomEvent('dashboard-update', { detail: data }));
      } catch (_) {}
    });

    es.addEventListener('ping', function () { /* keepalive */ });

    es.addEventListener('error', function () {
      es.close();
      es = null;
      setStatus(false);

      retries++;
      if (retries > MAX_RETRIES) {
        startFallback();
        return;
      }
      const delay = Math.min(BASE_DELAY * Math.pow(2, retries - 1), MAX_DELAY);
      setTimeout(connect, delay);
    });
  }

  window.addEventListener('load', connect);
  window.__sseReconnect = connect;
})();
