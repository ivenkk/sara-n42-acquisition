(() => {
  const grid = document.getElementById("spectra-grid");
  const liveEmpty = document.getElementById("live-empty");
  const statusLine = document.getElementById("status-line");
  const btnRefresh = document.getElementById("btn-refresh");
  const autoRefresh = document.getElementById("auto-refresh");

  /** @type {Map<string, echarts.ECharts>} */
  const charts = new Map();

  function setStatus(text) {
    statusLine.textContent = text;
  }

  function ensureCard(host, name) {
    let card = [...grid.querySelectorAll(".spectrum-card")].find(
      (el) => el.dataset.host === host
    );
    if (card) return card;

    card = document.createElement("section");
    card.className = "spectrum-card";
    card.dataset.host = host;
    card.innerHTML = `
      <div class="chart-meta">
        <div class="inst-name"></div>
        <div class="chart-title"></div>
        <div class="chart-subtitle"></div>
      </div>
      <div class="chart" role="img" aria-label="能谱曲线图"></div>
      <p class="empty-msg hidden"></p>
      <p class="error hidden"></p>
    `;
    card.querySelector(".inst-name").textContent = `${name} · ${host}`;
    grid.appendChild(card);

    const chartEl = card.querySelector(".chart");
    const chart = echarts.init(chartEl);
    charts.set(host, chart);
    return card;
  }

  function renderSpectrum(card, host, spectrum) {
    const chart = charts.get(host);
    const title = card.querySelector(".chart-title");
    const subtitle = card.querySelector(".chart-subtitle");
    const emptyMsg = card.querySelector(".empty-msg");
    const err = card.querySelector(".error");
    const chartEl = card.querySelector(".chart");

    emptyMsg.classList.add("hidden");
    chartEl.classList.remove("hidden");

    title.textContent = spectrum.filename;
    const doseDisplay = spectrum.dose_rate_display || "未知";
    subtitle.textContent = `测量时间：${spectrum.measurement_time}　剂量率：${doseDisplay}`;

    if (spectrum.error) {
      chart.clear();
      err.classList.remove("hidden");
      err.textContent = spectrum.error;
      return;
    }

    err.classList.add("hidden");
    const points = spectrum.channels.map((x, i) => [x, spectrum.counts[i]]);
    chart.setOption(
      {
        animationDuration: 300,
        grid: { left: 56, right: 24, top: 28, bottom: 48 },
        tooltip: { trigger: "axis" },
        xAxis: {
          type: "value",
          name: spectrum.x_label,
          nameLocation: "middle",
          nameGap: 28,
        },
        yAxis: {
          type: "value",
          name: spectrum.y_label,
          nameLocation: "middle",
          nameGap: 40,
        },
        series: [
          {
            type: "line",
            showSymbol: false,
            sampling: "lttb",
            lineStyle: { width: 1.4, color: "#1f6f54" },
            areaStyle: { color: "rgba(31, 111, 84, 0.08)" },
            data: points,
          },
        ],
      },
      true
    );
  }

  function renderEmpty(card, host, name) {
    const chart = charts.get(host);
    const title = card.querySelector(".chart-title");
    const subtitle = card.querySelector(".chart-subtitle");
    const emptyMsg = card.querySelector(".empty-msg");
    const err = card.querySelector(".error");
    const chartEl = card.querySelector(".chart");

    title.textContent = "暂无能谱";
    subtitle.textContent = "";
    err.classList.add("hidden");
    emptyMsg.classList.remove("hidden");
    emptyMsg.textContent = `${name}（${host}）尚无符合规则的本地文件。`;
    chartEl.classList.add("hidden");
    if (chart) chart.clear();
  }

  async function loadLatest() {
    setStatus("正在加载各仪器最新能谱…");
    const resp = await fetch("/api/spectra/latest");
    if (!resp.ok) {
      setStatus(`加载失败: HTTP ${resp.status}`);
      return;
    }
    const data = await resp.json();
    const items = data.instruments || [];

    if (items.length === 0) {
      liveEmpty.classList.remove("hidden");
      grid.innerHTML = "";
      charts.clear();
      setStatus("未配置仪器");
      return;
    }

    liveEmpty.classList.add("hidden");
    const seen = new Set();
    let withData = 0;

    for (const item of items) {
      seen.add(item.host);
      const card = ensureCard(item.host, item.name);
      if (item.empty || !item.spectrum) {
        renderEmpty(card, item.host, item.name);
      } else {
        renderSpectrum(card, item.host, item.spectrum);
        withData += 1;
      }
    }

    // Remove cards for instruments no longer configured
    for (const card of [...grid.querySelectorAll(".spectrum-card")]) {
      if (!seen.has(card.dataset.host)) {
        const host = card.dataset.host;
        const chart = charts.get(host);
        if (chart) {
          chart.dispose();
          charts.delete(host);
        }
        card.remove();
      }
    }

    for (const chart of charts.values()) {
      chart.resize();
    }

    setStatus(`已更新：${withData}/${items.length} 台有最新能谱`);
  }

  btnRefresh.addEventListener("click", () => loadLatest());
  window.addEventListener("resize", () => {
    for (const chart of charts.values()) chart.resize();
  });

  const intervalMs = (window.SARA_UI.pollIntervalSeconds || 300) * 1000;
  setInterval(() => {
    if (autoRefresh.checked) loadLatest();
  }, intervalMs);

  loadLatest();
})();
