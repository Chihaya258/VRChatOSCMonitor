@echo off
setlocal
set "PROJECT_DIR=%~dp0.."
set "VENV_DIR=%PROJECT_DIR%\.venv"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo ================================================
    echo   Virtual environment not found, deploying...
    echo ================================================
    echo.
    echo [1/2] Creating venv: %VENV_DIR%
    python -m venv "%VENV_DIR%"
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [2/2] Installing dependencies...
    call "%VENV_DIR%\Scripts\python.exe" -m pip install -r "%PROJECT_DIR%\requirements.txt"
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
)

echo Starting OSC Debug Receiver on UDP port 9000...
call "%VENV_DIR%\Scripts\python.exe" "%~dp0osc_receiver.py" %*
if %errorlevel% neq 0 (
    echo [ERROR] Program exited with code: %errorlevel%
    pause
)
