# Codex 与 Claude-Tap 旁路抓包实战指南（跨环境通用分享版）

> **写在前面**：本资料包专为想要彻底看清 AI Coding Agent（特别是 OpenAI Codex）底层网络通信、提示词组装和调用协议的开发者编写。  
> 无论你使用的是 **Windows、macOS 还是 Linux**，无论你是 **直连 OpenAI 官方 API** 还是 **搭配了本地 Web GPT 桥 / 反代工具**，本文都能让你用最符合直觉的心智模型，掌握全套抓包拦截、旁路监控与安全避坑技能。

---

## 目录

1. [为什么要给 Codex 抓包？（告别黑盒盲猜）](#一为什么要给-codex-抓包告别黑盒盲猜)
2. [认识 Claude-Tap：专为 AI Agent 定制的抓包神器](#二认识-claude-tap专为-ai-agent-定制的抓包神器)
3. [核心拓扑解析：有与没有本地 Web GPT 代理的流量走向](#三核心拓扑解析有与没有本地-web-gpt-代理的流量走向)
4. [跨环境安装与基础配置](#四跨环境安装与基础配置)
5. [Codex 旁路监控实操（CLI 与桌面版）](#五codex-旁路监控实操cli-与桌面版)
6. [9.24 事故防灾铁律：为什么抓包会清空桌面配置？](#六924-事故防灾铁律为什么抓包会清空桌面配置)
7. [自动化启停脚本开箱即用指南](#七自动化启停脚本开箱即用指南)
8. [抓包数据分析与纯净 Prompt 导出](#八抓包数据分析与纯净-prompt-导出)

---

## 一、为什么要给 Codex 抓包？（告别黑盒盲猜）

Codex 这类 Coding Agent 并不是普通的网页聊天机器人。当你在输入框里只打了一个字 `hi`，后台其实悄悄发起了一场庞大的网络交互：
* **隐形开销巨大**：单次请求的上下文动辄包含 2.5 万 tokens，你并不知道这其中有多少是工具定义、有多少是技能清单、有多少是权限规则；
* **配置生效盲盒**：你在 `config.toml` 里改了 `developer_instructions`，或者改了 `AGENTS.md`，大模型到底有没有收到？收到的位置是 `developer` 还是 `user`？
* **技能冲突与调用失常**：为什么某些技能在本地被重复加载了？

如果不抓包，你只能靠大模型的回答来“猜”配置是否生效（而大模型经常会产生幻觉）。**抓包，就是直接给客户端与服务端的真实数据流“拍 X 光片”，让所有隐藏的 Prompt 和交互细节无所遁形。**

---

## 二、认识 Claude-Tap：专为 AI Agent 定制的抓包神器

### 为什么不用 Wireshark / Fiddler / Charles？
* **传统工具很痛苦**：Fiddler 或 Charles 是为普通 Web 网页设计的。面对 AI Agent 每秒几十个的流式 SSE 分块（Server-Sent Events）、长连接 WebSocket 和几万字嵌套的 JSON Payload，传统工具不仅排版极其混乱，更无法将零碎的数据块自动还原为人类可读的对话流。
* **Claude-Tap 专为 Agent 而生**：由开源社区打造（原项目：`liaohch3/claude-tap`），原生支持 Claude Code、OpenAI Codex、Gemini CLI、Kimi Code 等几乎所有主流 Coding Agent。

### Claude-Tap 的三大杀手级特性
1. **自动还原对话流**：自动拼装 WebSocket / SSE 流式响应，彻底免去手动拼接数据块的折磨。
2. **极简优雅的 Web 仪表盘**：默认启动在本地 `http://127.0.0.1:19527`，提供像看即时通讯软件一样直观的界面，请求体、响应体、Token 消耗、延迟一目了然。
3. **本地记录存储**：抓取的所有会话无损保存在本地轻量 SQLite 数据库（`~/.local/share/claude-tap/traces.sqlite3`）中，本包提供 Markdown 提取脚本；记录过程本身会写库。

### 核心工作原理：透明中间人（MitM）
Claude-Tap 本质上是一个本地代理服务（默认监听端口例如 `18789`）。当客户端（Codex）发起网络请求时：
```
Codex 客户端 ───► Claude-Tap 本地监听端口 ───► 真实上游服务 (OpenAI / Web GPT)
                    │
                    ▼ (旁路静默记录)
               本地 SQLite 数据库
```
* **正向代理模式 (Forward)**：通过设置系统的 `HTTP_PROXY` / `HTTPS_PROXY`，借助本地根证书解密 TLS 流量；
* **反向代理模式 (Reverse)**：直接将客户端的 `base_url` 改为 Claude-Tap 的监听地址，Claude-Tap 负责透明转发至真实服务。

---

## 三、核心拓扑解析：有与没有本地 Web GPT 代理的流量走向

这是很多开发者最容易混淆的地方。理解网络拓扑的核心是：**搞清楚谁是谁的上游，坚决防止网络环路（Loop）**。

### 场景 A：直连官方模式（绝大多数普通用户的标准情况）

如果你直接使用 OpenAI 官方账号或官方 API Key，没有安装任何本地网关桥梁，你的拓扑极其纯粹：

```
┌────────────────────────┐
│  Codex 客户端 (CLI/桌面)│
└────────────────────────┘
            │
            │ (受该代理配置覆盖的模型请求)
            ▼
┌────────────────────────┐
│ Claude-Tap (18789 端口) │ ◄── 旁路记录 Request/Response 到 SQLite
└────────────────────────┘
            │
            │ (真实公网 HTTPS 请求)
            ▼
┌────────────────────────┐
│ OpenAI 官方云端服务器   │ (api.openai.com 或 chatgpt.com)
└────────────────────────┘
```

* **配置核心**：只需让 Codex 的网络出口指向 `127.0.0.1:18789`，流量就会直达 Claude-Tap，记录后直接出网。

---

### 场景 B：双层代理模式（有本地 Web GPT 桥 / 反代工具的高级玩法）

在已验证的本机环境中，`codex-chatgpt-web` 监听 **17841**；额外的记录桥监听 **17842**。两者不是同一个服务。这里保留“双层转发”的心智模型，但按实际实现标清位置：

**已验证顺序：Codex ──► 记录桥 ──► Web GPT ──► 原有网络出口 ──► 上游**

```
┌────────────────────────────────────────────────────────┐
│ 1. 正常 Codex 客户端（只开一个）                       │
│    openai_base_url = http://127.0.0.1:17842/v1          │
└────────────────────────────────────────────────────────┘
            │
            ▼
┌────────────────────────────────────────────────────────┐
│ 2. 本资料包 bridge/ 记录桥，监听 17842                 │
│    复用 Claude tap 解析与 SQLite 格式；On/Off 控制记录 │
└────────────────────────────────────────────────────────┘
            │ 固定转发至 17841
            ▼
┌────────────────────────────────────────────────────────┐
│ 3. Web GPT，监听 17841                                │
│    原生模型走其转发路径；Web 模型走其浏览器交互路径    │
└────────────────────────────────────────────────────────┘
            │ 原有外网代理（本机为 Xray 10808）或网络
            ▼
┌────────────────────────────────────────────────────────┐
│ 4. 上游服务                                           │
└────────────────────────────────────────────────────────┘
```

> [!IMPORTANT]
> **避坑与核心机制：**
> 1. **抓包边界**：记录桥位于 Codex 与 Web GPT 之间，记录的是 Codex 发向本地网关的原始模型请求（即客户端真实构造的 Prompt），不包含服务端内部追加逻辑；语音等独立流量不经过此桥。
> 2. **记录开关与进程生命周期**：`Off` 命令仅停止将报文存入 SQLite，网络转发依然正常进行；若直接杀掉桥进程，需将 Codex 路由切回 17841，否则会导致网络中断。
> 3. **防环路原则**：记录桥上游是 17841，Web GPT 必须对外发包，严禁将其上游反向指向 17842 造成死循环。
> 4. **环境适用性**：配套的常驻记录桥已在 Windows 环境经过实测验证；macOS / Linux 用户或临时诊断可使用通用 CLI 脚本。

---

## 四、跨环境安装与基础配置

安装命令可复用，但二进制路径和 Python 环境按平台选择。以下固定于本次核验的 Claude tap 版本：

### 1. 推荐安装方式（通过 Python uv 工具）
```bash
# 1. 安装 uv (如果尚未安装)
# Windows: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
# macOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 安装 claude-tap
uv tool install "claude-tap==0.1.145" --with "aiohttp==3.14.1" --with backports.zstd

# 3. 升级环境变量路径
uv tool update-shell
```
*(如果不使用 uv，也可以直接使用 `pip install claude-tap`)*

安装后确认 Codex 已安装并登录。Python 脚本要求 **Python 3.11+**，以及同一解释器环境中的 `claude_tap`、`backports.zstd`；桥还需要 `aiohttp`。`uv tool install` 的包不一定能被系统 `python` 导入。

Windows 后续 Python 命令使用：
```powershell
$tapPython = Join-Path (uv tool dir) 'claude-tap\Scripts\python.exe'
& $tapPython --version
```
macOS/Linux 使用 `"$(uv tool dir)/claude-tap/bin/python"`。若 uv 安装目录有自定义，按 `uv tool dir` 的结果定位。验证脚本可用 `--codex-exe` 显式指定与桌面相同版本的 Core；所需版本应支持 `debug prompt-input`、`exec --ignore-user-config --ephemeral`。原测试版本为 `0.155.0-alpha.16`。

### 2. 检查安装
在终端中执行：
```bash
claude-tap --version
# 输出类似: claude-tap 0.1.145
```

### 3. 打开 Web 历史仪表盘
```bash
# 在后台启动 Web 查看器服务
claude-tap dashboard
# 浏览器访问: http://127.0.0.1:19527
```

---

## 五、Codex 旁路监控实操（CLI 与桌面版）

### 模式一：监控 Codex CLI（命令行版，最推荐、最干净）

* **直连官方场景**：
  ```bash
  claude-tap --tap-client codex --tap-port 18789 --tap-host 127.0.0.1 --tap-live
  ```
  这些直接命令读取当前 CODEX_HOME 的配置和认证，会拉起新的 CLI 会话；本机已有 Web GPT 路由时不要把它当作强制官方直连。隔离诊断用下一节脚本，并先准备测试配置和认证。你在 CLI 里的每一句对话都会实时在网页仪表盘中呈现。

* **带本地 Web GPT 桥场景**：
  ```bash
  claude-tap --tap-client codex --tap-port 18789 --tap-host 127.0.0.1 --tap-target "http://127.0.0.1:17841/v1" --tap-live
  ```

---

### 模式二：监控 Codex 桌面版（Windows Store / ChatGPT.exe）

监控桌面版非常直观，但**暗藏重大危险**！在执行前必须先读懂下一章节的防灾逻辑。

---

## 六、9.24 事故防灾铁律：为什么抓包会清空桌面配置？

> [!CAUTION]
> **血泪教训（2026-09-24 真实事故）：**  
> 调试人员试图抓包桌面版，启动了第二个 Codex 桌面窗口，但**没有隔离 `CODEX_HOME`**。  
> 两个桌面进程同时抢占同一个沙箱锁与配置目录，抓包实例退出或同步时将其极简运行时状态回写，导致主配置被意外清空覆盖！

### 避免配置清空的三大保命铁律：

1. **铁律一：双开桌面版必须重定向 `CODEX_HOME`**  
   绝对不能让抓包实例和主力日常实例共用 `C:\Users\<用户名>\.codex`。必须在启动前将环境变量重定向到临时目录：
   ```powershell
   $env:CODEX_HOME = "$env:TEMP\codex-tap-isolated-home"
   ```
2. **铁律二：必须隔离桌面网页数据目录（`--user-data-dir`）**  
   使用独立的临时缓存目录存放 Cookie 和 Profile，避免与正在运行的正常窗口抢占文件句柄。
3. **铁律三：严格的退出顺序**  
   抓包调试结束后：**必须先关闭 Codex 桌面窗口，再关闭 Claude-Tap 代理服务**！如果先关代理，Codex 窗口会残留为无法联网的僵尸进程。

---

## 七、自动化启停脚本开箱即用指南

为了让读者完全免去手工敲环境变量、配置临时目录的繁琐操作，我们已经编写了独立客户端诊断脚本（Bash 版本需在目标系统验收），放置在 `scripts/` 目录下：

### Windows 用户使用指南 (PowerShell)

脚本位置：`抓包工具/scripts/`
* [start-tap.ps1](scripts/start-tap.ps1) (启动器)
* [stop-tap.ps1](scripts/stop-tap.ps1) (清理与终止)

#### 先准备独立诊断环境

此路径会启动另一个客户端，只用于专项诊断，不是你日常单实例记录的开关。`TestHome` 必须与正常 CODEX_HOME 不同，每个并发诊断使用不同目录。先在该目录建立 `config.toml`，写入**本次想验证的** model、developer_instructions 或 model_instructions_file；基础文件路径使用绝对路径。不要假设正常主目录的微调会自动复制过来。

若使用 ChatGPT 登录，需在测试目录完成独立登录；API key 用户则配置对应认证。示例（把目录改成你自己准备的路径）：
```powershell
$testHome = 'C:\codex-audit-home'
$previousCodexHome = $env:CODEX_HOME
try {
    $env:CODEX_HOME = $testHome
    codex login
} finally { $env:CODEX_HOME = $previousCodexHome }
```
脚本不自动复制凭证，也不安装缺失依赖。原有 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY 留给代理的上游出网使用，不要设成抓包入口自身。

#### 常见启动命令：
```powershell
# 场景 1: 启动 CLI 模式抓包 (默认直连)
.\start-tap.ps1 -Mode cli -TestHome $testHome

# 场景 2: 启动 CLI 模式并对接本地 Web GPT 桥 (17841)
.\start-tap.ps1 -Mode cli -WithWebBridge -TestHome $testHome

# 场景 3: 安全启动桌面版抓包 (使用已准备的独立配置和桌面 profile；不要并发复用同一 TestHome)
.\start-tap.ps1 -Mode desktop -TestHome $testHome -DesktopExecutable "C:\实际安装路径\ChatGPT.exe"

# 场景 4: 仅启动代理端口 (供自己其他特定命令接入)
.\start-tap.ps1 -Mode proxy-only -ProxyPort 18789 -TestHome $testHome
```

`proxy-only` 只启动监听，不会接管已运行的 Codex。需要在另一终端使用同一独立 TestHome，将诊断客户端的 `openai_base_url` 临时覆盖为 `http://127.0.0.1:18789/v1`；不要改动日常配置。启动代理时选定的上游仍应是原目标（Web GPT 场景为 17841），不能把上游也指向 18789。

#### 遇到残留或需要收尾时：
```powershell
# 检查端口占用；不强杀。先关闭诊断客户端，再在代理终端按 Ctrl+C
.\stop-tap.ps1

# 单独停止共享仪表盘（不会代替客户端/代理的退出）
.\stop-tap.ps1 -StopDashboard
```

---

#### 日常单实例：复用已验证的记录桥（Windows）

本包 [bridge/](bridge/) 含已验证实现的源文件副本，未带入运行状态、日志或凭证。原文证据在 [evidence/capture-2026-09-25/](evidence/capture-2026-09-25/manifest.json)。

1. 将整个资料包放到固定目录；确认 `uv tool dir` 等于 `%APPDATA%\uv\tools`，工具入口位于 `%USERPROFILE%\.local\bin`。不同布局需调整副本 `control.ps1` 的 Python 和 CLI 路径。
2. 启动可用的网络出口及 Web GPT，确认 Web GPT 监听 **17841**。本包不安装 Web GPT，不能只启动桥就假设上游存在；不使用 Web GPT 的读者采用上面的独立 Codex CLI 诊断路径。
3. 在 `抓包工具` 目录运行（保持默认 CODEX_HOME；不要使用诊断 TestHome）：
```powershell
.\bridge\control.ps1 Start
.\bridge\control.ps1 Status
& $tapPython .\bridge\route.py connect
# 正常重启 Codex 一次，然后：
.\bridge\control.ps1 On
.\bridge\control.ps1 Off
.\bridge\control.ps1 View
```
`route.py connect` 仅接受已有 `http://127.0.0.1:17841/v1` 路由，并备份后切到 17842；遇到其他路由会拒绝，不会猜测上游。`On`/`Off` 不改路由，已接入后开关记录无需再重启。查看器 19527 可选。

回退用 `.\bridge\control.ps1 Direct`，再正常重启 Codex；它恢复 **Web GPT 17841**，不等于官方直连。`Off` 不停桥进程。桥默认记录关闭，没有崩溃自动重启或失效自动绕行。

本机旧部署有登录启动项，但该项不随文件夹自动迁移。新机器可以每次登录后手动 Start；如需自动启动，在 Windows `shell:startup` 中创建指向 `pwsh.exe` 的快捷方式，参数为 `-NoProfile -WindowStyle Hidden -File "资料包实际路径\抓包工具\bridge\control.ps1" Start`。确保 PowerShell 7、D 盘/存放盘与上游服务可用；登录项不保证启动顺序。

桥修复过 Windows Job 生命周期问题；它仍依赖 Claude tap 私有存储/解析接口。升级工具版本后需重跑 `bridge/test_bridge.py`，不能承诺任意版本兼容。

---

### macOS / Linux 用户使用指南 (Bash)

脚本位置：`抓包工具/scripts/`
* [start-tap.sh](scripts/start-tap.sh)
* [stop-tap.sh](scripts/stop-tap.sh)

```bash
# 添加执行权限
chmod +x scripts/*.sh

# 启动 CLI 抓包
./scripts/start-tap.sh 18789 cli false "$HOME/codex-audit-home"

# 启动 CLI 抓包 (配合本地 Web GPT 桥)
./scripts/start-tap.sh 18789 cli true "$HOME/codex-audit-home"

# 仅启动代理端口
./scripts/start-tap.sh 18789 proxy-only false "$HOME/codex-audit-home"

# 仅检查；先关诊断客户端，再 Ctrl+C 结束代理
./scripts/stop-tap.sh 18789
```

---

## 八、抓包数据分析与纯净 Prompt 导出

抓包完成之后，如何提取出有价值的数据？

### 1. 网页可视化查看（最直观）
访问 `http://127.0.0.1:19527`：
* 左侧是所有捕获到的会话列表；
* 点击某个会话，即可查看每一轮对话的请求正文、耗时和返回文本；
* 可以展开查看底层的 WebSocket 帧和 SSE Stream 数据。

### 2. 本地只读解析导出脚本 (`export_prompt_capture.py`)
我们在本目录下提供了 [export_prompt_capture.py](export_prompt_capture.py)：
* 以严格的只读模式（`mode=ro`）连接本地 SQLite 数据库，绝不产生写锁；
* 自动解包压缩的 Compact Payload；
* 先用 `--list` 查询本机数据，再选择会话与记录；不是使用作者机器的固定 ID。示例：
```powershell
& $tapPython .\export_prompt_capture.py --list
& $tapPython .\export_prompt_capture.py --session "实际会话UUID" --list
& $tapPython .\export_prompt_capture.py --session "实际会话UUID" --record 1 --output-dir .\output\my-capture
```

自动将请求拆解为（文件下标按实际请求变化）：
  - `developer-000-tools.json` (完整的结构化工具定义)
  - `developer-001-00-base.raw.md` (官方纯净的基础指令)
  - `developer-008-01-skills-catalog.raw.md` (所有已加载技能的描述清单)
  - `developer-008-02-permissions.raw.md` (当前权限规则)
  - `manifest.json` (字符数、哈希与字段索引)

### 3. 零 Token 消耗离线发包测试 (`verify_prompt_wire.py`)
我们在本目录下提供了 [verify_prompt_wire.py](verify_prompt_wire.py)：
* 本地启动极简 HTTP 服务，当 Codex 发起请求时立即返回 HTTP 400 掐断；
* 测试请求仅送往临时本机接收端，不执行远端模型推理，做到 0 Token 消耗，专门用于快速验证配置项与请求头的组装行为。

---

## 结语：一套工具，深度掌控 Agent

通过这套旁路抓包与流量分析体系，你不仅能够看清每一句对话背后真实的 Token 构成与底层 Prompt 演变，更能在开发复杂 Agent 技能与定制指令时做到心中有数、调优有据。无论面对 Codex 还是未来的其他 AI 工具，掌握网络协议层的“真实心智”永远是排查问题与工程落地最坚实的护城河。
