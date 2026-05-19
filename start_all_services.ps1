param(
    [switch]$Restart,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

$ProjectRoot = "E:\develop\customer-agent-refactor-v3"
$FastGptRoot = "E:\develop\fastgpt"
$ProxyRoot = "E:\develop\customer-agent-coze"
$ProxyScript = Join-Path $ProxyRoot "ollama_proxy.py"
$Python = "D:\anaconda\python.exe"
$Docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$DockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$OllamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
$LogRoot = Join-Path $ProjectRoot "logs\startup"

function Write-Step($Text) {
    Write-Host ""
    Write-Host $Text -ForegroundColor Cyan
}

function Write-Ok($Text) {
    Write-Host "  OK  $Text" -ForegroundColor Green
}

function Write-Warn($Text) {
    Write-Host "  WARN $Text" -ForegroundColor Yellow
}

function Write-Fail($Text) {
    Write-Host "  FAIL $Text" -ForegroundColor Red
}

function Assert-File($Path, $Name) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Name not found: $Path"
    }
    Write-Ok "$Name found: $Path"
}

function Test-TcpPort($Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync("127.0.0.1", $Port)
        if (-not $task.Wait(700)) {
            return $false
        }
        return $client.Connected
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Wait-TcpPort($Port, $Name, $TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-TcpPort $Port) {
            Write-Ok "$Name is listening on port $Port"
            return $true
        }
        Start-Sleep -Seconds 2
    }
    Write-Warn "$Name did not open port $Port within ${TimeoutSeconds}s"
    return $false
}

function Wait-Http($Url, $Name, $TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
                Write-Ok "$Name responded: HTTP $($resp.StatusCode)"
                return $true
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    Write-Warn "$Name did not respond at $Url within ${TimeoutSeconds}s"
    return $false
}

function Wait-FastGpt($TimeoutSeconds) {
    if (Wait-Http "http://localhost:3000/api/system/version" "FastGPT API" $TimeoutSeconds) {
        return $true
    }
    Write-Warn "FastGPT API version endpoint did not respond; checking UI root."
    if (Wait-Http "http://localhost:3000" "FastGPT UI" 20) {
        return $true
    }
    return $false
}

function Get-ProcessByCommandLine($Pattern) {
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $Pattern }
}

function Stop-ProcessByCommandLine($Pattern, $Name) {
    $items = @(Get-ProcessByCommandLine $Pattern)
    foreach ($item in $items) {
        Write-Warn "Stopping $Name PID $($item.ProcessId)"
        Stop-Process -Id $item.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Start-LoggedProcess($Name, $FilePath, $ArgumentList, $WorkingDirectory, $StdoutFile, $StderrFile) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $StdoutFile) | Out-Null
    $proc = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StdoutFile `
        -RedirectStandardError $StderrFile `
        -PassThru
    Write-Ok "Started $Name PID $($proc.Id)"
    Write-Host "      stdout: $StdoutFile"
    Write-Host "      stderr: $StderrFile"
    return $proc
}

function Ensure-DockerEngine {
    Write-Step "[1/7] Checking Docker"
    Assert-File $Docker "Docker CLI"

    & $Docker info *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Docker Engine is running"
        return
    }

    if (Test-Path -LiteralPath $DockerDesktop) {
        Write-Warn "Docker Engine is not ready. Starting Docker Desktop."
        Start-Process -FilePath $DockerDesktop | Out-Null
    }

    for ($i = 1; $i -le 36; $i++) {
        & $Docker info *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Docker Engine is running"
            return
        }
        Start-Sleep -Seconds 5
    }

    throw "Docker Engine did not become ready within 180 seconds."
}

function Start-DockerCompose($Name, $Directory) {
    Write-Step "[Docker] Starting $Name"
    if (-not (Test-Path -LiteralPath (Join-Path $Directory "docker-compose.yml"))) {
        throw "$Name docker-compose.yml not found under $Directory"
    }
    Push-Location $Directory
    try {
        & $Docker compose up -d
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose up -d failed for $Name"
        }
        Write-Ok "$Name containers submitted"
        & $Docker compose ps
    } finally {
        Pop-Location
    }
}

function Ensure-Ollama {
    Write-Step "[4/7] Checking Ollama"
    if (Test-TcpPort 11434) {
        Write-Ok "Ollama is already listening on port 11434"
        return
    }

    if (-not (Test-Path -LiteralPath $OllamaExe)) {
        $cmd = Get-Command ollama -ErrorAction SilentlyContinue
        if ($cmd) {
            $script:OllamaExe = $cmd.Source
        } else {
            throw "Ollama executable not found. Expected $OllamaExe or ollama in PATH."
        }
    }

    if ($CheckOnly) {
        Write-Warn "CheckOnly: would start Ollama serve"
        return
    }

    Start-LoggedProcess `
        -Name "Ollama" `
        -FilePath $OllamaExe `
        -ArgumentList "serve" `
        -WorkingDirectory $ProjectRoot `
        -StdoutFile (Join-Path $LogRoot "ollama.out.log") `
        -StderrFile (Join-Path $LogRoot "ollama.err.log") | Out-Null
    Wait-Http "http://127.0.0.1:11434/api/tags" "Ollama" 60 | Out-Null
}

function Ensure-Proxy {
    Write-Step "[5/7] Checking Ollama/FastGPT proxy"
    Assert-File $ProxyScript "Proxy script"

    if ($Restart) {
        Stop-ProcessByCommandLine "ollama_proxy\.py" "proxy"
        Start-Sleep -Seconds 1
    }

    if (Test-TcpPort 11435) {
        Write-Ok "Proxy is already listening on port 11435"
        return
    }

    if ($CheckOnly) {
        Write-Warn "CheckOnly: would start proxy"
        return
    }

    Start-LoggedProcess `
        -Name "proxy" `
        -FilePath $Python `
        -ArgumentList "ollama_proxy.py" `
        -WorkingDirectory $ProxyRoot `
        -StdoutFile (Join-Path $LogRoot "proxy.out.log") `
        -StderrFile (Join-Path $LogRoot "proxy.err.log") | Out-Null
    Wait-TcpPort 11435 "Proxy" 30 | Out-Null
}

function Ensure-App {
    Write-Step "[6/7] Checking customer agent"
    if ($Restart) {
        Stop-ProcessByCommandLine "app\.py" "customer agent"
        Start-Sleep -Seconds 1
    }

    $running = @(Get-ProcessByCommandLine "app\.py")
    if ($running.Count -gt 0) {
        foreach ($item in $running) {
            Write-Ok "Customer agent already running PID $($item.ProcessId)"
        }
        return
    }

    if ($CheckOnly) {
        Write-Warn "CheckOnly: would start customer agent"
        return
    }

    Start-LoggedProcess `
        -Name "customer agent" `
        -FilePath $Python `
        -ArgumentList "app.py" `
        -WorkingDirectory $ProjectRoot `
        -StdoutFile (Join-Path $LogRoot "app.out.log") `
        -StderrFile (Join-Path $LogRoot "app.err.log") | Out-Null
}

function Show-Summary {
    Write-Step "[7/7] Summary"
    $checks = @(
        @{ Name = "FastGPT"; Port = 3000; Url = "http://localhost:3000" },
        @{ Name = "Ollama"; Port = 11434; Url = "http://127.0.0.1:11434/api/tags" },
        @{ Name = "Proxy"; Port = 11435; Url = "http://127.0.0.1:11435" }
    )
    foreach ($check in $checks) {
        if (Test-TcpPort $check.Port) {
            Write-Ok "$($check.Name) port $($check.Port) is open"
        } else {
            Write-Warn "$($check.Name) port $($check.Port) is not open"
        }
    }

    $proxy = @(Get-ProcessByCommandLine "ollama_proxy\.py")
    $app = @(Get-ProcessByCommandLine "app\.py")
    foreach ($p in $proxy) { Write-Ok "Proxy PID $($p.ProcessId)" }
    foreach ($p in $app) { Write-Ok "Customer agent PID $($p.ProcessId)" }

    Write-Host ""
    Write-Host "FastGPT UI: http://localhost:3000"
    Write-Host "Logs:       $LogRoot"
    Write-Host ""
    Write-Host "Use -Restart to restart proxy and app:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Restart"
}

try {
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " Customer Agent - One Click Startup"
    Write-Host "============================================================" -ForegroundColor Cyan

    New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
    Assert-File $Python "Python"
    Assert-File (Join-Path $ProjectRoot "app.py") "Customer agent entry"

    Ensure-DockerEngine
    if (-not $CheckOnly) {
        Write-Step "[2/7] Starting customer-agent dependencies"
        Start-DockerCompose "customer-agent Redis/Qdrant" $ProjectRoot

        Write-Step "[3/7] Starting FastGPT"
        Start-DockerCompose "FastGPT" $FastGptRoot
    } else {
        Write-Warn "CheckOnly: skipped docker compose startup"
    }

    if ($CheckOnly) {
        Wait-FastGpt 5 | Out-Null
    } else {
        Wait-FastGpt 180 | Out-Null
    }
    Ensure-Ollama
    Ensure-Proxy
    Ensure-App
    Show-Summary
} catch {
    Write-Fail $_.Exception.Message
    Write-Host ""
    Write-Host "Check logs under: $LogRoot"
    exit 1
}
