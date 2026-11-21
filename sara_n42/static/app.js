(() => {
  const hostSelect = document.getElementById("instrument");
  const fileList = document.getElementById("file-list");
  const fileEmpty = document.getElementById("file-empty");
  const chartTitle = document.getElementById("chart-title");
  const chartSubtitle = document.getElementById("chart-subtitle");
  const chartError = document.getElementById("chart-error");
  const statusLine = document.getElementById("status-line");
  const btnRefresh = document.getElementById("btn-refresh");
  const autoRefresh = document.getElementById("auto-refresh");

  const chart = echarts.init(document.getElementById("chart"));
  let selectedFile = null;
  let filesCache = [];

  function setStatus(text) {
    statusLine.textContent = text;
  }

  function currentHost() {
    return hostSelect.value || "";
  }

  async function loadFiles({ keepSelection = true } = {}) {
    const host = currentHost();
    if (!host) {
      fileList.innerHTML = "";
      fileEmpty.classList.remove("hidden");
      fileEmpty.textContent = "未配置仪器。请编辑 config.yaml 后重启。";
      return;
    }
    setStatus(`正在加载 ${host} 的文件列表…`);
    const resp = await fetch(`/api/files?host=${encodeURIComponent(host)}`);
    if (!resp.ok) {
      setStatus(`加载失败: HTTP ${resp.status}`);
      return;
    }
    const data = await resp.json();
    filesCache = data.files || [];
    fileList.innerHTML = "";

    if (data.empty || filesCache.length === 0) {
      fileEmpty.classList.remove("hidden");
      fileEmpty.textContent = "该仪器尚无符合规则的本地文件。";
      chart.clear();
      chartTitle.textContent = "暂无能谱";
      chartSubtitle.textContent = "";
      chartError.classList.add("hidden");
      selectedFile = null;
      setStatus(`${host}：无本地文件`);
      return;
    }

    fileEmpty.classList.add("hidden");
    for (const item of filesCache) {
      const li = document.createElement("li");
      li.dataset.filename = item.filename;
      li.innerHTML =
        `<div class="name"></div><div class="time"></div>`;
      li.querySelector(".name").textContent = item.filename;
      li.querySelector(".time").textContent = `测量时间：${item.measurement_time}`;
      li.addEventListener("click", () => selectFile(item.filename));
      fileList.appendChild(li);
    }

    const stillThere =
      keepSelection &&
      selectedFile &&
      filesCache.some((f) => f.filename === selectedFile);
    const next = stillThere ? selectedFile : filesCache[0].filename;
    await selectFile(next);
    setStatus(`${host}：${filesCache.length} 个文件`);
  }

  async function selectFile(filename) {
    selectedFile = filename;
    for (const li of fileList.querySelectorAll("li")) {
      li.classList.toggle("active", li.dataset.filename === filename);
    }
    const host = currentHost();
    chartTitle.textContent = filename;
    chartSubtitle.textContent = "正在解析能谱…";
    chartError.classList.add("hidden");

    const url =
      `/api/spectrum?host=${encodeURIComponent(host)}` +
      `&filename=${encodeURIComponent(filename)}`;
    const resp = await fetch(url);
    if (!resp.ok) {
      chart.clear();
      chartError.classList.remove("hidden");
      chartError.textContent = `加载失败: HTTP ${resp.status}`;
      chartSubtitle.textContent = "";
      return;
    }
    const data = await resp.json();
    chartSubtitle.textContent = `测量时间：${data.measurement_time}`;

    if (data.error) {
      chart.clear();
      chartError.classList.remove("hidden");
      chartError.textContent = data.error;
      return;
    }

    const points = data.channels.map((x, i) => [x, data.counts[i]]);
    chart.setOption(
      {
        animationDuration: 300,
        grid: { left: 56, right: 24, top: 28, bottom: 48 },
        tooltip: { trigger: "axis" },
        xAxis: {
          type: "value",
          name: data.x_label,
          nameLocation: "middle",
          nameGap: 28,
        },
        yAxis: {
          type: "value",
          name: data.y_label,
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

  btnRefresh.addEventListener("click", () => loadFiles({ keepSelection: true }));
  hostSelect.addEventListener("change", () => {
    selectedFile = null;
    loadFiles({ keepSelection: false });
  });
  window.addEventListener("resize", () => chart.resize());

  const intervalMs = (window.SARA_UI.pollIntervalSeconds || 300) * 1000;
  setInterval(() => {
    if (autoRefresh.checked) {
      loadFiles({ keepSelection: true });
    }
  }, intervalMs);

  loadFiles({ keepSelection: false });
})();
