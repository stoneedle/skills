#requires -Version 7.4
# Private provider boundary. Invoke-Agy.ps1 is the only public entry point.
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $JsonPath,
    [Parameter(Mandatory)] [string] $StderrPath,
    [Parameter(Mandatory)] [int] $ExitCode,
    [string] $JsonSchemaPath
)

$ErrorActionPreference = 'Stop'
$taskConversation = $null
$taskProvider = $null
function Stop-AgyResult([string] $Code, [string] $Message) {
    $taskException = [Exception]::new($Message)
    $taskException.Data['code'] = $Code
    $taskException.Data['conversation_id'] = $taskConversation
    throw $taskException
}

$taskStderr = Get-Content -LiteralPath $StderrPath -Raw -Encoding utf8
$taskRaw = Get-Content -LiteralPath $JsonPath -Raw -Encoding utf8
if (-not [string]::IsNullOrWhiteSpace($taskRaw)) {
    try { $taskProvider = ConvertFrom-Json -InputObject $taskRaw -AsHashtable -NoEnumerate }
    catch { Stop-AgyResult 'invalid_result' 'agy 未返回完整、可解析的 JSON。' }
    if ($taskProvider -isnot [System.Collections.IDictionary]) { Stop-AgyResult 'invalid_result' 'agy 返回值不是结果对象。' }
    $taskConversation = $taskProvider.conversation_id
}

$taskDenied = @($taskProvider.denied_actions | Where-Object { $null -ne $_ })
if ($taskDenied.Count -gt 0 -or $taskStderr -match 'auto-denied|permission.+(?:denied|cannot prompt)') {
    $taskActions = ($taskDenied | ForEach-Object { "$($_.action) $($_.display_name)" }) -join ', '
    Stop-AgyResult 'tool_denied' "工具操作被拒绝：$taskActions。按当前任务处理所需动作或提供原始材料，再续接会话。"
}
if ($taskStderr -match 'timed?\s*out|timeout|partial (?:response|result|output)') {
    Stop-AgyResult 'incomplete_result' 'agy 报告超时或部分输出，本轮尚未完成。'
}
if ($ExitCode -ne 0) { Stop-AgyResult 'cli_failed' "agy 退出码为 $ExitCode。" }
if (-not $taskProvider) { Stop-AgyResult 'invalid_result' 'agy 没有返回结果。' }
if ($taskProvider.status -ne 'SUCCESS') { Stop-AgyResult 'cli_failed' "agy 未完成，状态为 $($taskProvider.status)。" }
if ($taskProvider.response -isnot [string] -or [string]::IsNullOrWhiteSpace($taskProvider.response)) {
    Stop-AgyResult 'empty_response' 'agy 本轮正文为空。'
}

$taskValue = $taskProvider.response
$taskFormat = 'text'
if ($JsonSchemaPath) {
    # response is the current turn's final message. structured_output may belong to
    # an earlier turn, even when it matches the same schema; never consume it.
    try { $taskValue = ConvertFrom-Json -InputObject $taskProvider.response -AsHashtable -NoEnumerate }
    catch { Stop-AgyResult 'invalid_json' '本轮正文不是完整 JSON；需让 Gemini 按本轮 schema 重新给出结果。' }
    $taskSchema = Get-Content -LiteralPath $JsonSchemaPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
    # Recorded CLI replies add these UI-only fields to otherwise valid objects.
    # A field explicitly owned by the requested data schema is always retained.
    if ($taskValue -is [System.Collections.IDictionary] -and
        $taskSchema.additionalProperties -eq $false -and
        $taskSchema.properties -is [System.Collections.IDictionary]) {
        foreach ($taskMetadata in @('toolAction', 'toolSummary')) {
            if (-not $taskSchema.properties.Contains($taskMetadata) -and $taskValue[$taskMetadata] -is [string]) {
                $taskValue.Remove($taskMetadata)
            }
        }
    }
    $taskDataJson = ConvertTo-Json -InputObject $taskValue -Depth 100 -Compress
    if (-not (Test-Json -Json $taskDataJson -SchemaFile $JsonSchemaPath -ErrorAction SilentlyContinue)) {
        Stop-AgyResult 'schema_mismatch' '本轮 JSON 未通过所请求的 schema。'
    }
    $taskFormat = 'json'
}
[pscustomobject]@{
    conversation_id = $taskConversation
    format = $taskFormat
    value = $taskValue
    response = $taskProvider.response
}
