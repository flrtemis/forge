@echo off
REM ============================================================
REM  say.bat - read text aloud with YOUR model.pth. No FORGE app.
REM
REM    say.bat                      speak the clipboard
REM    say.bat "hello there"        speak this text
REM    say.bat --file notes.txt     speak a file
REM    say.bat --watch              speak whatever you copy (Ctrl+C to quit)
REM    say.bat "hi" --out hi.wav    save instead of playing
REM
REM  First run only: put your model folder in voice.txt, or pass
REM    say.bat "hi" --voice "C:\Users\you\forge\voices\my-voice"
REM  (Skip "Add argument" fuss: paths with spaces need quotes.)
REM ============================================================
setlocal
cd /d "%~dp0"

set "PY="
REM 1. FORGE's virtualenv, if it's the folder next door
if exist "%~dp0..\.venv\Scripts\python.exe" set "PY=%~dp0..\.venv\Scripts\python.exe"
REM 2. a venv inside this folder
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
REM 3. whatever python is on PATH
if not defined PY set "PY=python"

"%PY%" -c "import torch, TTS" 2>nul
if errorlevel 1 (
    echo.
    echo [!] This Python cannot see torch / coqui-TTS:
    echo     "%PY%"
    echo.
    echo     Install them once:
    echo       pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu130
    echo       pip install coqui-TTS
    echo.
    echo     ...or run this with FORGE's venv explicitly:
    echo       "..\.venv\Scripts\python.exe" speak.py "hello"
    echo.
    pause
    exit /b 1
)

REM No arguments at all = speak the clipboard.
"%PY%" speak.py %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
endlocal & exit /b %RC%
