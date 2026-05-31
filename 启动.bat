@echo off
title yt-dlp Manager

cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python and add it to PATH.
    pause
    exit /b 1
)

if not exist "server.py" (
    echo [ERROR] server.py not found in: %cd%
    pause
    exit /b 1
)

start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8080"

echo.
echo  yt-dlp Web Manager
echo  URL: http://localhost:8080
echo  Close this window to stop the server.
echo  ------------------------------------------
echo.

python server.py

echo.
echo [INFO] Server stopped.
pause
