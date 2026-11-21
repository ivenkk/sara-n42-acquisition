# SARA N42 数据采集与展示系统

在可访问仪器内网的 Windows 电脑上运行：按配置轮询一台或多台 Envinet SARA 能谱仪，每 5 分钟增量下载 Spectra Folder 中文件名包含 `5min` 的 `.n42` 文件，并在本机页面展示各仪器最新能谱、按时间检索并打包下载。

**运维使用手册（中文）：** [docs/使用手册.md](docs/使用手册.md)

> **重要：** 云端开发环境通常无法访问 `192.168.4.x` 仪器局域网。SOAP 契约已按管理页脚本 + 实机联调实现；**实机联调必须在可访问仪器的内网 PC 上完成**。实机 `GetFileNames` 返回重复的 `<FilesFound>`；`DownloadPackage` 为 `/tmp/n42Files.tgz`（gzip tar，经 `/root/tmp/...` 下载），不是 zip。

## 环境要求

- Windows 10/11（开发亦可用其它 OS，部署以 Windows 为准）
- Python 3.11+
- 运行电脑必须能 HTTP 访问各仪器 IP（仪器仅提供 HTTP，Digest 认证）

## 安装

在项目根目录：

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Linux / macOS：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 配置

1. 复制示例配置（若尚未有可用模板）：

   ```bat
   copy config.example.yaml config.yaml
   ```

2. 编辑 `config.yaml`：

   - 已预填当前仪器 `192.168.4.136`
   - 按实际修改 `username` / `password`（HTTP Digest）
   - 增加第二、三台时，在 `instruments` 下追加条目即可，**无需改代码**

3. **热加载（无需重启进程）：** 保存对 `config.yaml` 的修改后，运行中的程序会按文件修改时间自动重载仪器列表与轮询相关设置。刷新浏览器页面（或等下一轮 API 轮询）后，实时能谱面板数量会与新配置一致。YAML 无效时保留上一份有效配置并打 ERROR 日志。绑定地址 `ui.host` / `ui.port` 仍需重启进程才会生效。

4. `config.example.yaml` 中密码为占位符，适合提交到仓库；`config.yaml` 为本地可用模板。请勿把真实密码推到公开仓库。

主要字段：

| 字段 | 说明 |
| --- | --- |
| `storage_root` | 本地存储根目录，默认 `./data` |
| `poll_interval_seconds` | 轮询周期，固定 `300` |
| `filename_contains` | 文件名关键字，默认 `5min` |
| `file_extension` | 扩展名，默认 `.n42` |
| `request_timeout_seconds` | HTTP 超时（建议 15–30） |
| `ui.host` / `ui.port` | 展示页绑定，默认 `127.0.0.1:8080` |
| `instruments` | 仪器列表（name / host / port / username / password） |

## 启动

```bat
python -m sara_n42
```

或指定配置：

```bat
python -m sara_n42 -c config.yaml
```

启动后会：

1. 立即执行一轮远程检查与增量下载
2. 之后每 300 秒再检查一次
3. 在本机打开展示页： [http://127.0.0.1:8080](http://127.0.0.1:8080)（实时能谱）；检索下载： [http://127.0.0.1:8080/search](http://127.0.0.1:8080/search)

仅调试 UI、不启动下载调度：

```bat
python -m sara_n42 --no-scheduler
```

## 存储规则

```text
data/
  192.168.4.136/
    2026-11/
      *.n42
    2026-12/
      *.n42
  download.log
```

- 按仪器 IP，再按**测量月份** `YYYY-MM` 分子目录
- 月份优先取自 N42 内容中的测量时间，其次文件名中的时间戳；都无法解析时，回退为**本机下载时刻的本地时区月份**
- 保留远程原始文件名；同名文件在该仪器下任意月份目录已存在则跳过，不覆盖
- 只保存扩展名为 `.n42` 且文件名包含 `5min`（大小写不敏感）的文件
- 启动时会把仍留在 `data/<ip>/` 根下的旧扁平 `.n42` 自动迁入对应月份目录
- 单台仪器失败只记日志，不影响其它仪器与后续轮询

## 展示页功能

### 实时能谱 `/`

- 为每台已配置仪器展示**测量时间最新**的一条能谱（无文件列表）
- 1–N 台仪器自适应网格布局
- 显示文件名与测量时间（优先 N42 内容，其次文件名，否则「未知」；**不用 HTTP Date / 下载时间**）
- 有能量刻度用 keV，否则用道址；手动刷新；默认按轮询周期自动刷新

### 检索下载 `/search`

- 按测量时间范围检索本地 `.n42`（可选按仪器过滤）
- 只显示匹配**数量**，不列出文件名
- 一键打包为 ZIP 下载（目录按仪器 IP 分组）

### 相关 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/spectra/latest` | 各仪器最新能谱 |
| GET | `/api/search?start=&end=&host=` | 匹配数量（`host` 可选） |
| GET | `/api/search/download?start=&end=&host=` | 匹配文件 ZIP |

## 远程接口（SOAP）

- `POST http://{host}:{port}/SARA_Server.soap`
- HTTP Digest（realm: `SARA Remote Administration`）
- 操作：`GetFileNames`、`DownloadFiles`
- 谱目录参数：`/home/httpd/html/spectra/`（勿改）
- 列表节点：`<sara:FilesFound>`（每个文件一条）
- 下载包：`DownloadPackage` → `/tmp/n42Files.tgz`，HTTP 路径 `/root/tmp/n42Files.tgz`

实现细节见需求规格说明书；联调时请记录实机响应格式。

## 测试（无实机）

使用 SOAP / N42 fixture 做离线测试：

```bat
pip install -r requirements.txt
pytest -q
```

## 日志

- 控制台：INFO / ERROR
- 下载记录：`data/download.log`（时间、仪器 IP、文件名、成功/失败）

## 验收对照（内网 PC）

1. 仅配置 `192.168.4.136` 时能 Digest 登录并列出 Spectra Folder 中的 `.n42`
2. 每 5 分钟检查；只下载含 `5min` 且本地没有的 `.n42`
3. 保存到 `data/192.168.4.136/YYYY-MM/`，原始文件名，不覆盖
4. 配置追加其它 IP 后自动建目录并同样下载
5. 某台不可达时日志有错，其它仪器继续
6. 展示页可显示各仪器最新能谱；检索页可按时间查数量并下载 ZIP
7. 本 README 可指导安装、配置、启动与打开页面
