---
name: agy
description: 当需要调用 agy CLI 时使用，封装提示输入、会话续接、结果解析与产物检查。
---

# agy

本 skill 只负责 agy CLI 的调用契约与机械封装。调用时机、任务分工、提示内容、结果的语义核查及最终交付方式由调用方 skill 或用户要求决定。

## 输入

将调用方提供的任务与必要材料写入 UTF-8 提示文件。脚本会追加非交互工具使用说明，以及本轮声明的产物或 JSON 输出要求；实际发送的提示保存在运行目录的 `prompt.md`。

## 一个调用入口

在相关项目目录用 PowerShell 7.4+ 调用 [scripts/Invoke-Agy.ps1](scripts/Invoke-Agy.ps1)：

```powershell
& '<本机 agy skill 目录>/scripts/Invoke-Agy.ps1' -PromptPath '<提示文件绝对路径>'
```

入口路径相对本 `SKILL.md` 所在目录解析，不依赖固定用户名或盘符。工作目录是当前任务的项目目录，与 skill 安装目录分开。

日常只传 `-PromptPath`。续接同一主题传回 `-ConversationId`；从其他目录调用用 `-WorkingDirectory`。默认模型 `gemini-3.8-flash-high`，明确指定其他模型时用 `-Model`。

- 要求 JSON 数据：加 `-JsonSchemaPath '<schema 文件>'`，脚本返回已解析且通过校验的本轮数据。
- 要求创建或更新文件：加 `-ArtifactPaths @('<文件一>', '<文件二>')`，脚本将路径交给 Gemini，并检查实际产物。相对路径以工作目录为准。

命令输出一个 JSON 结果。宿主工具若返回后台进程 ID，等待同一进程完成后消费该结果；同主题追问与返工复用返回的 `conversation_id`，新主题省略它。

## 消费结果

- `ok=true`：`output.value` 是完整文本或解析后的 JSON；`output.format` 区分 `text/json`。`artifacts` 是已通过机械检查的产物路径。
- `output.inline=false`：内容较大，完整原文位于 `output.path`，按需读取或打开；脚本保留全量内容。
- `ok=false`：直接处理 `error.code` 与 `error.message`，已有会话 ID 仍会返回。提供缺失材料、处理具体受阻动作或附证据返工；权限决定遵循当前授权。

运行时只消费这一契约。CLI 参数、结果解析、历史字段处理、原文保存与产物检查由脚本拥有；`log_dir` 只用于设施排障。维护或需要完整协议时读 [references/protocol.md](references/protocol.md)。

## 契约边界

`ok` 表示调用与机械检查通过，结果的事实正确性、任务完成度和交付形式由调用方判断。

每次返回供应方的本轮 `response`，忽略可能残留的历史 `structured_output`；不拼接历史，也不对正文去重。文本结果保留原文字符和换行；JSON 结果按协议解析、清理元数据并校验。CLI 进度与 stderr 属于日志，不是正文输出。
