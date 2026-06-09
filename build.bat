@echo off
echo ============================================
echo   HardwareMonitor-VRChatOSC Build Script
echo ============================================
echo.

REM --- Check Python ---
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.8+ from https://www.python.org/
    exit /b 1
)

REM --- Check if pyinstaller is installed ---
where pyinstaller >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [INFO] Installing pyinstaller...
    pip install pyinstaller
)

REM --- Install dependencies ---
echo [INFO] Installing dependencies...
pip install -r requirements.txt

REM --- Build ---
echo.
echo [INFO] Building executable...
pyinstaller --onefile --clean --name monitor_gpuz monitor_gpuz.py

echo.
if %errorlevel%==0 (
    echo ============================================
    echo   Build successful! Output: dist\monitor_gpuz.exe
    echo ============================================
) else (
    echo ============================================
    echo   Build failed! Check error messages above
    echo ============================================
)
