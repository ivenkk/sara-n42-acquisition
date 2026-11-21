(() => {
  const hostSelect = document.getElementById("instrument");
  const startInput = document.getElementById("start");
  const endInput = document.getElementById("end");
  const btnSearch = document.getElementById("btn-search");
  const btnDownload = document.getElementById("btn-download");
  const hint = document.getElementById("search-hint");
  const countEl = document.getElementById("search-count");
  const errorEl = document.getElementById("search-error");
  const statusLine = document.getElementById("status-line");

  let lastQuery = null;

  function setStatus(text) {
    statusLine.textContent = text;
  }

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function toLocalInputValue(d) {
    return (
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
      `T${pad(d.getHours())}:${pad(d.getMinutes())}`
    );
  }

  function initDefaults() {
    const end = new Date();
    const start = new Date(end.getTime() - 24 * 60 * 60 * 1000);
    startInput.value = toLocalInputValue(start);
    endInput.value = toLocalInputValue(end);
  }

  function queryParams() {
    const start = startInput.value;
    const end = endInput.value;
    if (!start || !end) {
      throw new Error("请填写起止测量时间");
    }
    const params = new URLSearchParams({ start, end });
    const host = hostSelect.value;
    if (host) params.set("host", host);
    return params;
  }

  function showError(msg) {
    errorEl.classList.remove("hidden");
    errorEl.textContent = msg;
    countEl.classList.add("hidden");
    hint.classList.add("hidden");
    btnDownload.disabled = true;
    lastQuery = null;
  }

  function showCount(data) {
    errorEl.classList.add("hidden");
    hint.classList.add("hidden");
    countEl.classList.remove("hidden");
    const scope = data.host ? `仪器 ${data.host}` : "全部仪器";
    countEl.textContent = `${scope}：匹配 ${data.count} 个文件`;
    btnDownload.disabled = data.count === 0;
  }

  async function runSearch() {
    let params;
    try {
      params = queryParams();
    } catch (err) {
      showError(err.message || String(err));
      setStatus("检索条件不完整");
      return;
    }

    setStatus("正在检索…");
    btnSearch.disabled = true;
    try {
      const resp = await fetch(`/api/search?${params.toString()}`);
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        showError(body.detail || `检索失败: HTTP ${resp.status}`);
        setStatus(`检索失败: HTTP ${resp.status}`);
        return;
      }
      lastQuery = params;
      showCount(body);
      setStatus(`检索完成：${body.count} 个文件`);
    } catch (err) {
      showError(String(err));
      setStatus("检索失败");
    } finally {
      btnSearch.disabled = false;
    }
  }

  function runDownload() {
    if (!lastQuery) return;
    const url = `/api/search/download?${lastQuery.toString()}`;
    setStatus("正在打包下载…");
    // Navigate so the browser handles the ZIP download.
    window.location.href = url;
  }

  btnSearch.addEventListener("click", () => runSearch());
  btnDownload.addEventListener("click", () => runDownload());
  [startInput, endInput, hostSelect].forEach((el) => {
    el.addEventListener("change", () => {
      btnDownload.disabled = true;
      lastQuery = null;
    });
  });

  initDefaults();
})();
