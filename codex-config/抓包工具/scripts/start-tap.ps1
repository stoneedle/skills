<# Independent diagnostic client; not the single-instance recording bridge.
Prepare TestHome with its own config and authentication before use.
#>
param(
    [ValidateSet('cli','desktop','proxy-only')][string]$Mode='cli',
    [int]$ProxyPort=18789,
    [switch]$WithWebBridge,
    [string]$Upstream='http://127.0.0.1:17841/v1',
    [Parameter(Mandatory=$true)][string]$TestHome,
    [string]$DesktopExecutable
)
$ErrorActionPreference='Stop'
if (-not (Get-Command claude-tap -ErrorAction SilentlyContinue)) { throw 'Install claude-tap==0.1.145 first; see README.' }
if ($ProxyPort -lt 1 -or $ProxyPort -gt 65535) { throw 'Invalid port.' }
$testRoot=[IO.Path]::GetFullPath($TestHome)
$normalRoot=if ($env:CODEX_HOME) { [IO.Path]::GetFullPath($env:CODEX_HOME) } else { Join-Path $env:USERPROFILE '.codex' }
if ($testRoot.TrimEnd([char[]]'\/') -ieq $normalRoot.TrimEnd([char[]]'\/')) { throw 'TestHome must differ from the normal CODEX_HOME.' }
if (-not (Test-Path -LiteralPath (Join-Path $testRoot 'config.toml'))) { throw 'Prepare TestHome/config.toml with the prompt settings to verify; see README.' }
if (Get-NetTCPConnection -State Listen -LocalPort $ProxyPort -ErrorAction SilentlyContinue) { throw 'Proxy port is occupied; refusing to reuse it.' }
$saved=@{}
foreach ($name in @('CODEX_HOME','CODEX_APP_USER_DATA_DIR','CODEX_APP_EXECUTABLE')) { $saved[$name]=[Environment]::GetEnvironmentVariable($name,'Process') }
try {
    $env:CODEX_HOME=$testRoot
    # Leave HTTP_PROXY/HTTPS_PROXY/ALL_PROXY untouched: they belong to upstream egress.
    $tapArgs=@('--tap-client', $(if ($Mode -eq 'desktop') {'codexapp'} else {'codex'}), '--tap-host','127.0.0.1','--tap-port',"$ProxyPort",'--tap-live')
    if ($WithWebBridge) { $tapArgs+=@('--tap-target',$Upstream) }
    if ($Mode -eq 'proxy-only') { $tapArgs+=@('--tap-no-launch','--tap-proxy-mode','reverse') }
    if ($Mode -eq 'desktop') {
        if (-not $DesktopExecutable -or -not (Test-Path -LiteralPath $DesktopExecutable)) { throw 'Pass -DesktopExecutable with the installed Codex desktop executable.' }
        $env:CODEX_APP_EXECUTABLE=[IO.Path]::GetFullPath($DesktopExecutable)
        $env:CODEX_APP_USER_DATA_DIR=Join-Path $testRoot 'desktop-profile'
    }
    Write-Host "Diagnostic home: $testRoot; listener: 127.0.0.1:$ProxyPort"
    Write-Host 'Close the launched client before stopping this foreground proxy with Ctrl+C.'
    & claude-tap @tapArgs
    if ($LASTEXITCODE -ne 0) { throw "claude-tap exited with code $LASTEXITCODE" }
} finally {
    foreach ($name in $saved.Keys) {
        if ($null -eq $saved[$name]) { Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue }
        else { [Environment]::SetEnvironmentVariable($name,$saved[$name],'Process') }
    }
}
