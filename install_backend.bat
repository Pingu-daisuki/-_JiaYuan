@echo off
setlocal
cd /d "%~dp0"

echo Installing JiaYuan backend dependencies...
python -m pip install --upgrade pip
if errorlevel 1 goto :failed

python -m pip install -r backend\requirements.txt
if errorlevel 1 goto :failed

echo Backend dependencies installed successfully.
pause
exit /b 0

:failed
echo Backend dependency installation failed. Check the error output above.
pause
exit /b 1
