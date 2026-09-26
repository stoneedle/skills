# Codex 抓包与离线验证全能资料包 (Claude-Tap Toolkit)

> **资源定位**：这是一份**可供迁移参考，按平台与版本验证**的完整抓包与验证资料包。  
> 包含 Claude-Tap 的工作机理深度解析、有/无本地 Web GPT 桥的双场景网络拓扑、独立客户端诊断脚本与已验证的 Windows 记录桥副本，以及零 Token 消耗的本地 Mock 验证工具。

---

## 📚 核心文档与实战手册

| 文件 | 类型 | 说明与核心价值 |
| :--- | :---: | :--- |
| 📖 [Codex与Claude-Tap旁路抓包实战指南.md](Codex与Claude-Tap旁路抓包实战指南.md) | **万字实战手册** | **必读主手册**。详细介绍 Claude-Tap 运行原理、直连模式 vs 本地 Web 桥双层代理拓扑、防灾铁律（避开 9.24 事故）与数据分析。 |
| 🛠️ [scripts/ 自动化脚本目录](scripts) | **跨平台脚本** | 提供 Windows PowerShell 与 macOS/Linux Bash 的一键启动与状态检查脚本，使用指定的独立环境。 |

---

## ⚡ 自动化启停脚本清单 (`scripts/`)

为防止双开实例造成配置破坏，独立客户端脚本要求显式指定 **预先准备配置和认证的 TestHome**；常驻 bridge/ 则不启动新 Codex：

| 平台 | 启动脚本 | 状态检查脚本 | 适用场景与支持模式 |
| :---: | :--- | :--- | :--- |
| **Windows** | 📜 [start-tap.ps1](scripts/start-tap.ps1) | 📜 [stop-tap.ps1](scripts/stop-tap.ps1) | 支持 `-Mode cli`、`-Mode desktop`、`-Mode proxy-only`，支持 `-WithWebBridge` |
| **macOS / Linux** | 📜 [start-tap.sh](scripts/start-tap.sh) | 📜 [stop-tap.sh](scripts/stop-tap.sh) | 支持 CLI 与纯代理模式，支持对接本地 Web GPT 桥 |

### Windows 快速启动示例：
先按主手册第七节准备 `$testHome` 的配置与认证；以下是独立诊断客户端，不是日常记录开关。
```powershell
# 1. 启动 CLI 模式抓包 (默认直连)
.\scripts\start-tap.ps1 -Mode cli -TestHome $testHome

# 2. 启动 CLI 模式并对接本地 Web GPT 桥 (17841)
.\scripts\start-tap.ps1 -Mode cli -WithWebBridge -TestHome $testHome

# 3. 安全启动桌面版抓包 (自动隔离 CODEX_HOME，需要独立配置、认证与退出检查)
.\scripts\start-tap.ps1 -Mode desktop -TestHome $testHome -DesktopExecutable "C:\实际安装路径\ChatGPT.exe"

# 4. 先关诊断客户端、Ctrl+C 结束代理；此命令仅检查残留端口
.\scripts\stop-tap.ps1
```

---

## 🔬 零 Token 消耗：本地验证与提取工具箱

修改 `config.toml` 或 Prompt 文件后，你不必启动桌面版向 OpenAI 发起昂贵的真实请求。我们为你提供了配套的 Python 自动化脚本，可以在本地直接测试验证：

### 1. 本地内部 Prompt 组装渲染检查 (`verify_prompt_config.py`)
* **文件**：[verify_prompt_config.py](verify_prompt_config.py)
* **原理**：调用底层 CLI 的 `codex debug prompt-input` 命令。本地渲染当前配置下的上下文结构（不调用远端大模型），用于快速检查配置是否被成功解析。
* **执行命令**：
  ```powershell
  & $tapPython .\verify_prompt_config.py --codex-exe "实际Codex可执行文件路径"
  ```

---

### 2. 本地 Mock HTTP 400 截获真实发包 (`verify_prompt_wire.py`)
* **文件**：[verify_prompt_wire.py](verify_prompt_wire.py)
* **原理**：本地随机启动 HTTP 服务接收 Codex 发出的真实报文，**捕获后立即返回 HTTP 400 掐断**，保证 0 Token 消耗，绝不发送到远端大模型产生费用，专门用于抓取并断言真实发包结构。
* **执行命令**：
  ```powershell
  & $tapPython .\verify_prompt_wire.py --codex-exe "实际Codex可执行文件路径"
  ```

---

### 3. 从 Claude-Tap 数据库无损提取 Prompt (`export_prompt_capture.py`)
* **文件**：[export_prompt_capture.py](export_prompt_capture.py)
* **功能**：以只读模式（`mode=ro`）连接本地 SQLite（`~/.local/share/claude-tap/traces.sqlite3`），解包压缩的 Compact Payload，将请求中的基础指令、工具列表、技能清单拆分保存为独立的 Markdown 与 JSON 文件。
* **常用命令**：
  ```powershell
  # 1. 查看本地所有会话
  & $tapPython .\export_prompt_capture.py --list

  # 2. 查看指定会话的所有交互轮次
  & $tapPython .\export_prompt_capture.py --session "实际会话UUID" --list

  # 3. 导出指定轮次的 Prompt 资产
  & $tapPython .\export_prompt_capture.py --session "实际会话UUID" --record 1 --output-dir .\output\my-capture
  ```

---

## 💡 日常操作建议

1. **日常无感记录**：Windows 用户推荐直接使用 [bridge/](bridge/) 常驻桥（提供 `Start / On / Off / View / Direct` 管理命令），不需要反复启闭桌面窗口，透明无感记录。
2. **专项独立诊断**：若需要隔离排查特定配置或在 macOS/Linux 运行，可使用 `scripts/` 下的独立启动脚本。
3. **查验基线证据**：历史抓包解包的原始基线与哈希清单保存在 [evidence/capture-2026-09-25/](evidence/capture-2026-09-25/manifest.json) 中。
