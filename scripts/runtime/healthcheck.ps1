param(
    [string]$StatusFile = "",
    [int]$StatusStaleSeconds = 30,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"

for ($i = 0; $i -lt $RemainingArgs.Count; $i++) {
    switch ($RemainingArgs[$i]) {
        "--status-file" {
            $i++
            if ($i -ge $RemainingArgs.Count) {
                throw "--status-file requires a value"
            }
            $StatusFile = $RemainingArgs[$i]
        }
        "--status-stale-seconds" {
            $i++
            if ($i -ge $RemainingArgs.Count) {
                throw "--status-stale-seconds requires a value"
            }
            $StatusStaleSeconds = [int]$RemainingArgs[$i]
        }
        default {
            throw "Unknown argument: $($RemainingArgs[$i])"
        }
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")

$argsList = @(
    "-m", "runtime.worker",
    "--healthcheck",
    "--status-stale-seconds", "$StatusStaleSeconds"
)

if ($StatusFile) {
    $argsList += @("--status-file", $StatusFile)
}

Push-Location $RepoRoot
try {
    & python @argsList
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
