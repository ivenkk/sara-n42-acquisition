# SARA N42 数据采集与展示系统

在可访问仪器内网的 Windows 电脑上运行：按配置轮询一台或多台 Envinet SARA 能谱仪，每 5 分钟增量下载 Spectra Folder 中文件名包含 `5min` 的 `.n42` 文件，并在本机页面列出文件、显示测量时间、绘制能谱曲线。

> **重要：** 云端开发环境通常无法访问 `192.168.4.x` 仪器局域网。SOAP 契约已按管理页脚本实现；**实机联调必须在可访问仪器的内网 PC 上完成**。第一次联调请核对 `DownloadPackage` 实际路径与是否为 zip，若与文档不符，以实机为准并回写需求说明。

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

3. `config.example.yaml` 中密码为占位符，适合提交到仓库；`config.yaml` 为本地可用模板。请勿把真实密码推到公开仓库。

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
3. 在本机打开展示页： [http://127.0.0.1:8080](http://127.0.0.1:8080)

仅调试 UI、不启动下载调度：

```bat
python -m sara_n42 --no-scheduler
```

## 存储规则

```text
data/
  192.168.4.136/
    <原始文件名>_5min_<.n42>
  download.log
```

- 按仪器 IP 分子目录
- 保留远程原始文件名；本地已存在则跳过，不覆盖
- 只保存扩展名为 `.n42` 且文件名包含 `5min`（大小写不敏感）的文件
- 单台仪器失败只记日志，不影响其它仪器与后续轮询

## 展示页功能

- 按仪器切换查看本地文件
- 显示文件名与测量时间（优先 N42 内容，其次文件名，否则「未知」；**不用 HTTP Date / 下载时间**）
- 默认按测量时间倒序；选中文件绘制能谱（有能量刻度用 keV，否则用道址）
- 手动刷新；默认每 5 分钟自动刷新列表

## 远程接口（SOAP）

- `POST http://{host}:{port}/SARA_Server.soap`
- HTTP Digest（realm: `SARA Remote Administration`）
- 操作：`GetFileNames`、`DownloadFiles`
- 谱目录参数：`/home/httpd/html/spectra/`（勿改）

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
3. 保存到 `data/192.168.4.136/`，原始文件名，不覆盖
4. 配置追加其它 IP 后自动建目录并同样下载
5. 某台不可达时日志有错，其它仪器继续
6. 展示页可列文件、显示测量时间、绘制能谱
7. 本 README 可指导安装、配置、启动与打开页面
