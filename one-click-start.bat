@echo off
chcp 65001 >nul
setlocal

set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%start_all_services.ps1"

echo ============================================================
echo  Customer Agent - One Click Startup
echo ============================================================
echo.

if not exist "%PS_SCRIPT%" (
    echo [ERROR] PowerShell script not found:
    echo   %PS_SCRIPT%
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
    echo [ERROR] Startup failed with exit code %EXIT_CODE%.
) else (
    echo [OK] Startup script finished.
)

pause
exit /b %EXIT_CODE%
