# Inspect only; no process is killed by name or by an unverified port owner.
param([int]$ProxyPort=18789,[switch]$StopDashboard)
$ErrorActionPreference='Stop'
Write-Host 'Close the diagnostic Codex client, then press Ctrl+C in its proxy terminal.'
Get-NetTCPConnection -State Listen -LocalPort $ProxyPort -ErrorAction SilentlyContinue |
    Select-Object LocalAddress,LocalPort,OwningProcess
Write-Host 'Any listed owner requires identification; this script does not terminate it.'
if ($StopDashboard) {
    & claude-tap dashboard stop
    if ($LASTEXITCODE -ne 0) { throw 'Dashboard stop failed.' }
}
