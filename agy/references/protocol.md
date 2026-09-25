# agy 调用协议与维护

公开入口只有 `scripts/Invoke-Agy.ps1`。`Read-AgyResult.ps1` 是内部供应方适配，调用方不直接调用它。PowerShell 7.4+ 自带 JSON Schema 校验，运行时无需其他库。

## 返回值

成功退出码为 0，失败为 1；两者都在 stdout 返回一个 JSON 对象。成功的文本示例：

```json
{
  "ok": true,
  "conversation_id": "会话 ID",
  "output": {
    "format": "text",
    "inline": true,
    "path": "C:/.../response.md",
    "value": "Gemini 的完整原文"
  },
  "artifacts": ["C:/.../overview.html"],
  "error": null,
  "log_dir": "C:/.../agy-runs/本次目录"
}
```

传入 `JsonSchemaPath` 时，`format=json`，`value` 为校验后的 JSON 值，`path` 指向本轮完整 JSON。数组、单元素数组及 null 保留原类型。返回内容序列化后超过 8 KiB 时，`inline=false`、`value=null`，通过 `path` 获取完整内容；普通调用无需二次读取。

失败时 `ok=false`、`output=null`，`error={"code":"tool_denied","message":"具体受阻动作与原因"}`。能够取得的 `conversation_id` 和 `log_dir` 仍然返回；输入或环境检查阶段失败时日志目录可为空。

| 错误码 | 调用方需要处理的事情 |
| --- | --- |
| `invalid_request` | 修正提示文件、工作目录或 schema。 |
| `cli_unavailable` / `launch_failed` / `io_error` | Codex 修复本地调用环境或文件操作。 |
| `tool_denied` | 在当前授权内处理具体动作或补充原始材料。 |
| `cli_failed` / `invalid_result` / `incomplete_result` | 调用未完整结束；Codex 根据日志处理具体故障。 |
| `empty_response` / `invalid_json` / `schema_mismatch` | 在已有会话中要求提供完整且符合本轮约定的回复。 |
| `artifact_missing` / `artifact_empty` / `artifact_not_updated` | 按错误中的路径补齐本轮约定的产物。 |

脚本只执行一次调用，不自行发起重试或变更权限。宿主执行工具的后台等待仍由宿主承接，等待的是同一个脚本进程。

## 机械检查的范围

- 正文从供应方本轮 `response` 取得。请求 JSON 时也直接解析本轮正文并按本轮 schema 校验；供应方可能残留的历史 `structured_output` 完全不参与结果选择。当前正文不是 JSON 就明确失败。对于声明 `properties` 且关闭额外属性的对象，移除 CLI 混入、而 schema 未声明的字符串字段 `toolAction/toolSummary`；schema 明确声明的同名业务字段始终保留。
- 退出码、供应方终态、工具拒绝、超时提示和空正文统一转换为错误对象；`SUCCESS` 不单独构成成功。
- `ArtifactPaths` 声明本轮必须创建或写回的文件。脚本检查文件存在、非空，并通过调用前后的长度及修改时间观察写入。它不判断内容的事实正确性或图形呈现质量。需沿用未修改的参考文件时，将其放在任务资料中。
- 原文和供应方日志保存在提示文件旁的独立运行目录；文本保留字符和换行。结构化输出在去除上述协议元数据后解码、校验并保存，业务字段保持原值。实际发送的提示、未经改写的原始结果和 stderr 均可供 Codex 排障。

## 本地验证

```powershell
python '<本机 agy skill 目录>/tests/test_invoke_agy.py'
```

测试将真实公开入口连接到临时目录中的替身 `agy.exe`，不调用 Gemini。覆盖原文与参数传输、当前 JSON 与历史字段隔离、JSON 值类型、记录中的 SUCCESS+拒绝/空回复、约定文件写入、长内容和输入错误。替身仅位于测试目录；生产脚本按 PATH 使用实际 CLI。

测试依赖本机 Python 与 Windows .NET Framework 自带的 C# 编译器，均不构成运行时依赖。首次部署后真实供应方是否遵守本轮输出协议，仍需在用户实际委派任务中观察；本地替身测试不代表完成了线上模型验收。
