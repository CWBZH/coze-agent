param(
    [Parameter(Mandatory = $true)]
    [string]$ShopId,
    [Parameter(Mandatory = $true)]
    [string]$UserId,
    [int]$RunSeconds = 30
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StopFile = Join-Path $RepoRoot "runtime.stop"

Push-Location $RepoRoot
try {
    if (Test-Path $StopFile) {
        Remove-Item -LiteralPath $StopFile -Force
    }

    & python -m runtime.worker --shop-id $ShopId --user-id $UserId --run-seconds $RunSeconds --status-interval 2
    $workerExit = $LASTEXITCODE
    if ($workerExit -ne 0) {
        Write-Host "worker_exit=$workerExit"
        exit $workerExit
    }

    & python -m runtime.worker --status
    $statusExit = $LASTEXITCODE
    if ($statusExit -ne 0) {
        Write-Host "status_exit=$statusExit"
        exit $statusExit
    }

    & python -m runtime.worker --healthcheck
    $healthExit = $LASTEXITCODE
    if ($healthExit -ne 5) {
        Write-Host "healthcheck_exit=$healthExit expected=5"
        exit 10
    }

    $statusFile = (& python -c "from core import settings; print(settings.worker_status_path())").Trim()

    if (-not (Test-Path $statusFile)) {
        Write-Host "status_file_missing=$statusFile"
        exit 11
    }

    $json = Get-Content -LiteralPath $statusFile -Raw | ConvertFrom-Json
    $errors = @()
    if ($json.snapshot_phase -ne "final") { $errors += "snapshot_phase=$($json.snapshot_phase)" }
    if ($json.worker_state -ne "stopped") { $errors += "worker_state=$($json.worker_state)" }
    if ([int]$json.connected_count -ne 0) { $errors += "connected_count=$($json.connected_count)" }
    if ($json.exit_reason -ne "run_seconds_elapsed") { $errors += "exit_reason=$($json.exit_reason)" }

    if ($errors.Count -gt 0) {
        Write-Host ("snapshot_invalid " + ($errors -join " "))
        exit 12
    }

    Write-Host "smoke_worker=passed status_file=$statusFile"
    exit 0
}
finally {
    Pop-Location
}
