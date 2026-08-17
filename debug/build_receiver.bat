@echo off
setlocal
set "PROJECT_DIR=%~dp0.."
echo ============================================
echo   OSC Debug Receiver Build Script
echo ============================================
echo.

where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found. Install Python 3.8+ from https://www.python.org/
    exit /b 1
)

where pyinstaller >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [INFO] Installing pyinstaller...
    pip install pyinstaller
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] pyinstaller install failed
        exit /b 1
    )
)

echo [INFO] Installing project dependencies...
pip install -r "%PROJECT_DIR%\requirements.txt"
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Dependency installation failed.
    exit /b 1
)

echo [INFO] Building executable...
pyinstaller ^
    --onefile ^
    --clean ^
    --name osc_receiver ^
    --distpath "%~dp0dist" ^
    --workpath "%~dp0build" ^
    --specpath "%~dp0" ^
    "%~dp0osc_receiver.py"
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Build failed.
    exit /b 1
)

echo.
echo Build successful! Output: debug\dist\osc_receiver.exe
