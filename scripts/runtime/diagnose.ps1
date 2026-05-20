param(
    [string]$OutputDir = "",
    [string]$StatusFile = "",
    [int]$LogLines = 2000,
    [int]$MaxLogKb = 0,
    [switch]$NoZip,
    [switch]$IncludeGitStatus,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"

for ($i = 0; $i -lt $RemainingArgs.Count; $i++) {
    switch ($RemainingArgs[$i]) {
        "--output-dir" {
            $i++
            if ($i -lt $RemainingArgs.Count) { $OutputDir = $RemainingArgs[$i] }
        }
        "--status-file" {
            $i++
            if ($i -lt $RemainingArgs.Count) { $StatusFile = $RemainingArgs[$i] }
        }
        "--log-lines" {
            $i++
            if ($i -lt $RemainingArgs.Count) { $LogLines = [int]$RemainingArgs[$i] }
        }
        "--max-log-kb" {
            $i++
            if ($i -lt $RemainingArgs.Count) { $MaxLogKb = [int]$RemainingArgs[$i] }
        }
        "--no-zip" {
            $NoZip = $true
        }
        "--include-git-status" {
            $IncludeGitStatus = $true
        }
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
Set-Location $RepoRoot

function Invoke-PythonValue {
    param([string]$Code)

    $value = & python -c $Code 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($value)) {
        return $null
    }
    return ($value | Select-Object -First 1).Trim()
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $defaultOutput = Invoke-PythonValue "from core import settings; print(settings.data_dir() / 'diagnostics')"
    if ([string]::IsNullOrWhiteSpace($defaultOutput)) {
        $defaultOutput = Join-Path $RepoRoot "temp\diagnostics"
    }
    $OutputDir = $defaultOutput
}

if ([string]::IsNullOrWhiteSpace($StatusFile)) {
    $defaultStatus = Invoke-PythonValue "from core import settings; print(settings.worker_status_path())"
    if (-not [string]::IsNullOrWhiteSpace($defaultStatus)) {
        $StatusFile = $defaultStatus
    }
}

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
$DiagnoseDir = Join-Path $OutputDir "diagnose-$Timestamp"
New-Item -ItemType Directory -Path $DiagnoseDir -Force | Out-Null

$Manifest = [ordered]@{
    schema_version = 1
    created_at = (Get-Date).ToString("o")
    repo_root = $RepoRoot
    diagnose_dir = $DiagnoseDir
    status_file = $StatusFile
    log_lines = $LogLines
    max_log_kb = $MaxLogKb
    include_git_status = [bool]$IncludeGitStatus
    files = @()
    command_exit_codes = [ordered]@{}
}

function Redact-Text {
    param([string]$Text)

    if ($null -eq $Text) { return "" }
    $redacted = $Text
    $redacted = [regex]::Replace(
        $redacted,
        '(?i)("(?:access_token|authorization|api_key|password|cookie|secret|token)"\s*:\s*")[^"]*(")',
        '$1***REDACTED***$2'
    )
    $redacted = [regex]::Replace(
        $redacted,
        "(?i)('(?:access_token|authorization|api_key|password|cookie|secret|token)'\s*:\s*')[^']*(')",
        '$1***REDACTED***$2'
    )
    $redacted = [regex]::Replace(
        $redacted,
        '(?i)\b(access_token|authorization|api_key|password|cookie|secret|token)\b(\s*[:=]\s*)("[^"]*"|''[^'']*''|[^\s,;}]+)',
        '$1$2***REDACTED***'
    )
    $redacted = [regex]::Replace($redacted, '(?i)\bBearer\s+[A-Za-z0-9._~+\-/=]+', 'Bearer ***REDACTED***')
    $redacted = [regex]::Replace($redacted, '(?i)\bark-[A-Za-z0-9._-]+', '***REDACTED***')
    $redacted = [regex]::Replace($redacted, '(?i)\bfastgpt-[A-Za-z0-9._-]+', '***REDACTED***')
    $redacted = [regex]::Replace($redacted, '(?i)access_token|authorization|api_key|password|cookie|secret|token', '***REDACTED***')
    return $redacted
}

function Write-RedactedFile {
    param(
        [string]$RelativePath,
        [string]$Content
    )

    $target = Join-Path $DiagnoseDir $RelativePath
    $parent = Split-Path -Parent $target
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Redact-Text $Content | Set-Content -LiteralPath $target -Encoding UTF8
    $script:Manifest.files += $RelativePath
}

function Copy-RedactedFile {
    param(
        [string]$SourcePath,
        [string]$RelativePath
    )

    if (-not [string]::IsNullOrWhiteSpace($SourcePath) -and (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        $content = Get-Content -LiteralPath $SourcePath -Raw -ErrorAction Stop
        Write-RedactedFile -RelativePath $RelativePath -Content $content
    }
}

function Invoke-Capture {
    param(
        [string]$Name,
        [string[]]$Command,
        [string]$RelativePath
    )

    $output = & $Command[0] $Command[1..($Command.Count - 1)] 2>&1 | Out-String
    $script:Manifest.command_exit_codes[$Name] = $LASTEXITCODE
    Write-RedactedFile -RelativePath $RelativePath -Content $output
}

function Get-LogTail {
    param([System.IO.FileInfo]$File)

    if ($MaxLogKb -gt 0) {
        $bytes = [System.IO.File]::ReadAllBytes($File.FullName)
        if ($bytes.Length -eq 0) { return "" }
        $count = [Math]::Min($bytes.Length, $MaxLogKb * 1024)
        $buffer = New-Object byte[] $count
        [Array]::Copy($bytes, $bytes.Length - $count, $buffer, 0, $count)
        return [System.Text.Encoding]::UTF8.GetString($buffer)
    }

    return (Get-Content -LiteralPath $File.FullName -Tail $LogLines -ErrorAction Stop | Out-String)
}

$runtimePathsCode = @'
from core import settings
print('APP_ENV=' + str(settings.APP_ENV))
print('DATA_DIR=' + str(settings.data_dir()))
print('LOG_DIR=' + str(settings.log_dir()))
print('DB_PATH=' + str(settings.db_path()))
print('WORKER_STATUS_PATH=' + str(settings.worker_status_path()))
'@
Write-RedactedFile -RelativePath "metadata\runtime_paths.txt" -Content (& python -c $runtimePathsCode 2>&1 | Out-String)

Write-RedactedFile -RelativePath "metadata\python_version.txt" -Content (& python --version 2>&1 | Out-String)
Write-RedactedFile -RelativePath "metadata\pip_freeze.txt" -Content (& python -m pip freeze 2>&1 | Out-String)
Write-RedactedFile -RelativePath "metadata\os_info.txt" -Content @"
OSVersion=$([Environment]::OSVersion.VersionString)
MachineName=$([Environment]::MachineName)
UserDomainName=$([Environment]::UserDomainName)
PowerShell=$($PSVersionTable.PSVersion)
"@

if (-not [string]::IsNullOrWhiteSpace($StatusFile)) {
    Copy-RedactedFile -SourcePath $StatusFile -RelativePath "runtime\worker_status.json"
}

$statusArgs = @("-m", "runtime.worker", "--status", "--json")
$healthArgs = @("-m", "runtime.worker", "--healthcheck", "--json")
if (-not [string]::IsNullOrWhiteSpace($StatusFile)) {
    $statusArgs += @("--status-file", $StatusFile)
    $healthArgs += @("--status-file", $StatusFile)
}
Invoke-Capture -Name "runtime_status_json" -Command (@("python") + $statusArgs) -RelativePath "runtime\status.json"
Invoke-Capture -Name "runtime_healthcheck_json" -Command (@("python") + $healthArgs) -RelativePath "runtime\healthcheck.json"

Copy-RedactedFile -SourcePath (Join-Path $RepoRoot ".env.example") -RelativePath "config\.env.example"
Copy-RedactedFile -SourcePath (Join-Path $RepoRoot "docs\config\ENVIRONMENT_VARIABLES.md") -RelativePath "docs\ENVIRONMENT_VARIABLES.md"
Copy-RedactedFile -SourcePath (Join-Path $RepoRoot "docs\runtime\HEADLESS_WORKER_RUNBOOK.md") -RelativePath "docs\HEADLESS_WORKER_RUNBOOK.md"
Copy-RedactedFile -SourcePath (Join-Path $RepoRoot "docs\runtime\DIAGNOSE_PACKAGE.md") -RelativePath "docs\DIAGNOSE_PACKAGE.md"

$logDir = Invoke-PythonValue "from core import settings; print(settings.log_dir())"
if (-not [string]::IsNullOrWhiteSpace($logDir) -and (Test-Path -LiteralPath $logDir -PathType Container)) {
    $logs = Get-ChildItem -LiteralPath $logDir -Filter "*.log" -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 3
    foreach ($log in $logs) {
        $safeName = $log.FullName.Substring($logDir.Length).TrimStart('\', '/') -replace '[:\\\/]', '_'
        if ([string]::IsNullOrWhiteSpace($safeName)) { $safeName = $log.Name }
        Write-RedactedFile -RelativePath (Join-Path "logs" $safeName) -Content (Get-LogTail -File $log)
    }
}

if ($IncludeGitStatus) {
    Invoke-Capture -Name "git_status_short" -Command @("git", "status", "--short") -RelativePath "git\status_short.txt"
    Invoke-Capture -Name "git_diff_name_only" -Command @("git", "diff", "--name-only") -RelativePath "git\diff_name_only.txt"
}

$manifestJson = $Manifest | ConvertTo-Json -Depth 8
Write-RedactedFile -RelativePath "manifest.json" -Content $manifestJson

if (-not $NoZip) {
    $ZipPath = "$DiagnoseDir.zip"
    Compress-Archive -Path (Join-Path $DiagnoseDir "*") -DestinationPath $ZipPath -Force
    Write-Output "diagnose_zip=$ZipPath"
}

Write-Output "diagnose_dir=$DiagnoseDir"
exit 0
