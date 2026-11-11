@echo off
REM One-click launcher: runs the SDN firewall demo inside WSL2.
setlocal

wsl.exe --cd "%~dp0" -d Ubuntu-22.04 -- bash run.sh
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo Demo finished successfully.
) else (
    echo Demo exited with code %RC%.
)
echo.
pause
