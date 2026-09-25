#requires -Version 7.4
<#
.SYNOPSIS
Invoke agy once and return one JSON result on stdout (exit 0 success, 1 failure).
.DESCRIPTION
PromptPath contains the task, not CLI instructions. Optional ArtifactPaths declare files
that this call must create or update. JsonSchemaPath validates JSON from the current reply.
The caller consumes output.value; oversized results use output.path with inline=false.
#>
[CmdletBinding()]
param(
    [string] $PromptPath,
    [string] $WorkingDirectory = (Get-Location).Path,
    [string] $ConversationId,
    [string] $Model = 'gemini-3.8-flash-high',
    [string] $JsonSchemaPath,
    [string[]] $ArtifactPaths = @()
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$taskResult = [ordered]@{
    ok = $false
    conversation_id = $(if ($ConversationId) { $ConversationId } else { $null })
    output = $null
    artifacts = @()
    error = $null
    log_dir = $null
}
$taskFailureCode = 'invalid_request'

try {
    if ([string]::IsNullOrWhiteSpace($PromptPath)) { throw '需要提供 PromptPath。' }
    $taskPromptPath = (Resolve-Path -LiteralPath $PromptPath).Path
    $taskWorkingDirectory = (Resolve-Path -LiteralPath $WorkingDirectory).Path
    if (-not (Test-Path -LiteralPath $taskWorkingDirectory -PathType Container)) { throw 'WorkingDirectory 必须是目录。' }
    $taskPrompt = Get-Content -LiteralPath $taskPromptPath -Raw -Encoding utf8
    if ([string]::IsNullOrWhiteSpace($taskPrompt)) { throw 'PromptPath 指向的提示为空。' }
    if ($JsonSchemaPath) {
        $JsonSchemaPath = (Resolve-Path -LiteralPath $JsonSchemaPath).Path
        # Test-Json compiles the schema before the provider is called. A normal
        # validation failure against null is expected; an invalid schema is not.
        $taskSchemaErrors = @()
        $null = Test-Json -Json 'null' -SchemaFile $JsonSchemaPath -ErrorAction SilentlyContinue -ErrorVariable taskSchemaErrors
        if ($taskSchemaErrors | Where-Object { $_.FullyQualifiedErrorId -notlike 'InvalidJsonAgainstSchema*' }) {
            throw "JsonSchemaPath 不是有效的 JSON Schema：$JsonSchemaPath"
        }
    }

    $taskArtifactsBefore = [ordered]@{}
    foreach ($taskPath in $ArtifactPaths) {
        $taskPath = [IO.Path]::GetFullPath($taskPath, $taskWorkingDirectory)
        $taskFile = Get-Item -LiteralPath $taskPath -ErrorAction SilentlyContinue
        if ($taskFile -and $taskFile.PSIsContainer) { throw "产物路径指向目录：$taskPath" }
        $taskArtifactsBefore[$taskPath] = $(if ($taskFile) { "$($taskFile.Length):$($taskFile.LastWriteTimeUtc.Ticks)" } else { $null })
    }

    $taskFailureCode = 'cli_unavailable'
    $taskAgyExe = (Get-Command agy -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    $taskFailureCode = 'io_error'
    $taskRunName = (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    $taskRunDirectory = Join-Path (Split-Path -Parent $taskPromptPath) "agy-runs/$taskRunName"
    New-Item -ItemType Directory -Path $taskRunDirectory | Out-Null
    $taskResult.log_dir = $taskRunDirectory
    $taskJsonPath = Join-Path $taskRunDirectory 'raw.json'
    $taskStderrPath = Join-Path $taskRunDirectory 'stderr.log'
    $taskRuntimeInstructions = @'
这是非交互调用。文件调查和产物写入使用原生文件工具（view_file、list_dir、grep_search、write_to_file），无需终端。缺少能力时返回具体操作或所需原始材料，由宿主处理。按实际完成情况报告。
以下是宿主提供的本轮任务原文：

'@
    $taskSentPrompt = $taskRuntimeInstructions + $taskPrompt
    if ($taskArtifactsBefore.Count) {
        $taskSentPrompt += "`n`n本轮应使用文件工具创建或写回以下完整产物：`n" + (@($taskArtifactsBefore.Keys) -join "`n")
    }
    if ($JsonSchemaPath) {
        $taskSentPrompt += "`n`n本轮最终回复直接输出符合本轮 JSON Schema 的完整 JSON，正文即为本轮数据。"
    }
    $taskSentPrompt | Set-Content -LiteralPath (Join-Path $taskRunDirectory 'prompt.md') -Encoding utf8 -NoNewline
    $taskAgyArgs = @('--model', $Model, '--output-format', 'json', '--print-timeout', '0')
    if ($ConversationId) { $taskAgyArgs += @('--conversation', $ConversationId) }
    if ($JsonSchemaPath) { $taskAgyArgs += @('--json-schema', $JsonSchemaPath) }
    $taskAgyArgs += @('--print', $taskSentPrompt)

    $taskFailureCode = 'launch_failed'
    Push-Location -LiteralPath $taskWorkingDirectory
    try {
        & $taskAgyExe @taskAgyArgs 1> $taskJsonPath 2> $taskStderrPath
        $taskExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    $taskFailureCode = 'invalid_result'
    $taskReply = & (Join-Path $PSScriptRoot 'Read-AgyResult.ps1') `
        -JsonPath $taskJsonPath -StderrPath $taskStderrPath -ExitCode $taskExitCode -JsonSchemaPath $JsonSchemaPath
    $taskResult.conversation_id = $taskReply.conversation_id
    $taskFailureCode = 'io_error'
    $taskSerializedValue = ConvertTo-Json -InputObject $taskReply.value -Depth 100 -Compress
    $taskExtension = if ($taskReply.format -eq 'json') { 'json' } else { 'md' }
    $taskReplyPath = Join-Path $taskRunDirectory "response.$taskExtension"
    $taskFileBody = if ($taskReply.format -eq 'json') { $taskSerializedValue } else { $taskReply.response }
    $taskFileBody | Set-Content -LiteralPath $taskReplyPath -Encoding utf8 -NoNewline

    foreach ($taskPath in $taskArtifactsBefore.Keys) {
        $taskFailureCode = 'artifact_missing'
        if (-not (Test-Path -LiteralPath $taskPath -PathType Leaf)) { throw "本轮未生成约定产物：$taskPath" }
        $taskFile = Get-Item -LiteralPath $taskPath
        $taskFailureCode = 'artifact_empty'
        if ($taskFile.Length -eq 0) { throw "本轮产物为空：$taskPath" }
        $taskFailureCode = 'artifact_not_updated'
        if ($taskArtifactsBefore[$taskPath] -eq "$($taskFile.Length):$($taskFile.LastWriteTimeUtc.Ticks)") {
            throw "约定产物仍是调用前的文件，未观测到本轮写入：$taskPath"
        }
    }

    $taskFailureCode = 'invalid_result'
    $taskInline = [Text.Encoding]::UTF8.GetByteCount($taskSerializedValue) -le 8192
    $taskResult.output = [ordered]@{
        format = $taskReply.format
        inline = $taskInline
        path = $taskReplyPath
        value = $null
    }
    # Assign directly: PowerShell subexpressions otherwise unwrap single-item arrays.
    if ($taskInline) { $taskResult.output.value = $taskReply.value }
    $taskResult.artifacts = @($taskArtifactsBefore.Keys)
    $taskResult.ok = $true
} catch {
    if ($_.Exception.Data['code']) { $taskFailureCode = $_.Exception.Data['code'] }
    if ($_.Exception.Data['conversation_id']) { $taskResult.conversation_id = $_.Exception.Data['conversation_id'] }
    $taskResult.error = [ordered]@{ code = $taskFailureCode; message = $_.Exception.Message }
}

$taskJson = ConvertTo-Json -InputObject $taskResult -Depth 100 -Compress
if ($taskResult.log_dir) {
    try { $taskJson | Set-Content -LiteralPath (Join-Path $taskResult.log_dir 'result.json') -Encoding utf8 -NoNewline }
    catch {
        $taskResult.ok = $false
        $taskResult.output = $null
        $taskResult.error = [ordered]@{ code = 'io_error'; message = $_.Exception.Message }
        $taskJson = ConvertTo-Json -InputObject $taskResult -Depth 100 -Compress
    }
}
Write-Output $taskJson
exit $(if ($taskResult.ok) { 0 } else { 1 })
