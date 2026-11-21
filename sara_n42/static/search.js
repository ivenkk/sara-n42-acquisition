(() => {
  const hostSelect = document.getElementById("instrument");
  const startDate = document.getElementById("start-date");
  const startTime = document.getElementById("start-time");
  const endDate = document.getElementById("end-date");
  const endTime = document.getElementById("end-time");
  const btnSearch = document.getElementById("btn-search");
  const btnDownload = document.getElementById("btn-download");
  const hint = document.getElementById("search-hint");
  const countEl = document.getElementById("search-count");
  const errorEl = document.getElementById("search-error");
  const statusLine = document.getElementById("status-line");

  const TIME_24H = /^(?:[01]\d|2[0-3]):[0-5]\d$/;

  let lastQuery = null;

  function setStatus(text) {
    statusLine.textContent = text;
  }

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function splitLocal(d) {
    return {
      date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
      time: `${pad(d.getHours())}:${pad(d.getMinutes())}`,
    };
  }

  function normalizeTimeInput(el) {
    let v = (el.value || "").trim().replace(/\./g, ":").replace(/\s+/g, "");
    if (/^\d{3,4}$/.test(v)) {
      v = v.padStart(4, "0");
      v = `${v.slice(0, 2)}:${v.slice(2)}`;
    }
    el.value = v;
    return v;
  }

  function combineDateTime(dateEl, timeEl, label) {
    const date = (dateEl.value || "").trim();
    const time = normalizeTimeInput(timeEl);
    if (!date || !time) {
      throw new Error(`请填写${label}的日期与时间（24小时制 HH:MM）`);
    }
    if (!TIME_24H.test(time)) {
      throw new Error(`${label}时间须为 24 小时制 HH:MM（例如 09:30 或 18:05）`);
    }
    return `${date}T${time}`;
  }

  function initDefaults() {
    const end = new Date();
    const start = new Date(end.getTime() - 24 * 60 * 60 * 1000);
    const s = splitLocal(start);
    const e = splitLocal(end);
    startDate.value = s.date;
    startTime.value = s.time;
    endDate.value = e.date;
    endTime.value = e.time;
  }

  function queryParams() {
    const start = combineDateTime(startDate, startTime, "起始");
    const end = combineDateTime(endDate, endTime, "结束");
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

  function invalidateDownload() {
    btnDownload.disabled = true;
    lastQuery = null;
  }

  btnSearch.addEventListener("click", () => runSearch());
  btnDownload.addEventListener("click", () => runDownload());
  [startDate, startTime, endDate, endTime, hostSelect].forEach((el) => {
    el.addEventListener("change", invalidateDownload);
    el.addEventListener("input", invalidateDownload);
  });
  [startTime, endTime].forEach((el) => {
    el.addEventListener("blur", () => normalizeTimeInput(el));
  });

  initDefaults();
})();
