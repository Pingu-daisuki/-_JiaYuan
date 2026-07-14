@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo Starting JiaYuan development services...
start "JiaYuan Backend" /D "%~dp0backend" cmd /k "set JIAYUAN_RELOAD=1&& python main.py"
start "JiaYuan Frontend" /D "%~dp0frontend" cmd /k "npm run dev"

echo Backend and frontend launch commands have been sent.
echo Open the address printed by Vite after both services are ready.
endlocal
