param([ValidateSet('On','Off','Status','View','Start','Direct')][string]$Action = 'Status')
$ErrorActionPreference = 'Stop'
$bridgeRoot = $PSScriptRoot
$bridgePython = Join-Path $env:APPDATA 'uv\tools\claude-tap\Scripts\pythonw.exe'
$bridgeConsolePython = Join-Path $env:APPDATA 'uv\tools\claude-tap\Scripts\python.exe'
$bridgeStatusUrl = 'http://127.0.0.1:17842/bridge/status'
function Get-BridgeStatus {
    $result = Invoke-RestMethod $bridgeStatusUrl -TimeoutSec 3
    if ($result.service -ne 'codex-tap-bridge-v1') { throw 'Port 17842 is owned by another service.' }
    return $result
}
function Start-Bridge {
    try { $null = Get-BridgeStatus; return } catch {}
    if (Get-NetTCPConnection -State Listen -LocalPort 17842 -ErrorAction SilentlyContinue) {
        throw 'Port 17842 is occupied; refusing to start another service.'
    }
    $bridgeBasePython = & $bridgeConsolePython -c 'import sys; print(sys._base_executable)'
    if ($LASTEXITCODE -ne 0) { throw 'Could not locate the installed Python runtime.' }
    & $bridgeBasePython (Join-Path $bridgeRoot 'launch.py') $bridgePython
    if ($LASTEXITCODE -ne 0) { throw 'Could not start bridge outside the app lifecycle. See launcher.log.' }
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 200
        try { $null = Get-BridgeStatus; return } catch {}
    }
    throw 'Bridge startup failed. See service.log.'
}
function Set-Recording([bool]$enabled) {
    $state = @{ enabled = $enabled; session = [guid]::NewGuid().ToString() } | ConvertTo-Json -Compress
    $temporaryState = Join-Path $bridgeRoot 'capture-state.next.json'
    [IO.File]::WriteAllText($temporaryState, $state, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporaryState -Destination (Join-Path $bridgeRoot 'capture-state.json') -Force
}
switch ($Action) {
    'Start' { Start-Bridge; Get-BridgeStatus | ConvertTo-Json }
    'On' { Start-Bridge; Set-Recording $true; Get-BridgeStatus | ConvertTo-Json }
    'Off' { Set-Recording $false; Get-BridgeStatus | ConvertTo-Json }
    'Status' { Get-BridgeStatus | ConvertTo-Json }
    'View' {
        & (Join-Path $env:USERPROFILE '.local\bin\claude-tap.exe') dashboard --tap-live-port 19527
    }
    'Direct' {
        Set-Recording $false
        & $bridgeConsolePython (Join-Path $bridgeRoot 'route.py') direct
        if ($LASTEXITCODE -ne 0) { throw 'Could not restore direct route.' }
        # Keep the relay alive for requests that have already selected this endpoint.
        Write-Output 'Original 17841 route restored. Relay remains alive for in-flight requests. Restart Codex when convenient.'
    }
}
[IO.File]::AppendAllText((Join-Path $bridgeRoot 'control-operations.jsonl'),
    ((@{ time = (Get-Date).ToString('o'); action = $Action } | ConvertTo-Json -Compress) + [Environment]::NewLine),
    [Text.UTF8Encoding]::new($false))
