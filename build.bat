@echo off
echo ============================================
echo   HardwareMonitor-VRChatOSC Build Script
echo ============================================
echo.

REM --- Check Python ---
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found. Install Python 3.8+ from https://www.python.org/
    exit /b 1
)

REM --- Check/install pyinstaller ---
where pyinstaller >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [INFO] Installing pyinstaller...
    pip install pyinstaller
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] pyinstaller install failed
        exit /b 1
    )
)

REM --- Install project dependencies ---
echo [INFO] Installing project dependencies...
pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo [WARN] Some dependencies failed to install, build may be incomplete
)

REM --- Build ---
echo.
echo [INFO] Building executable...
pyinstaller ^
    --onefile ^
    --clean ^
    --name monitor_gpuz ^
    --hidden-import pynvml ^
    --hidden-import wmi ^
    --hidden-import utils ^
    --hidden-import utils.config ^
    --hidden-import utils.logger ^
    --hidden-import utils.gpuz_structures ^
    --hidden-import utils.gpuz_search ^
    --hidden-import utils.gpu_reader ^
    --hidden-import utils.osc_sender ^
    main.py

echo.
if %errorlevel%==0 (
    echo ============================================
    echo   Build successful! Output: dist\monitor_gpuz.exe
    echo ============================================
) else (
    echo ============================================
    echo   Build failed! Check errors above.
    echo ============================================
    exit /b 1
)
