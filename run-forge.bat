@echo off
REM ============================================================
REM  Launch FORGE — double-click this every time.
REM  Activates the .venv automatically, then starts the app.
REM ============================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo No virtual environment found. Run setup-forge.bat first.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
echo Starting FORGE...
python run.py
if %ERRORLEVEL%==42 (
    echo.
    echo [FORGE] Governor stop: RAM got dangerous, so FORGE shut itself down to protect your PC.
    echo [FORGE] Your checkpoint is safe. See forge_guard.json in the workdir, then start training again to resume.
    echo.
)
pause
