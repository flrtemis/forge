@echo off
REM ============================================================
REM  Speak text with your trained FORGE voice, from one command.
REM    say.bat "Hello world"
REM    say.bat "Hi" --voice "D:\voices\my-voice" --speed 0.9
REM  Flags are passed straight to forge.synth (see README).
REM ============================================================
setlocal
cd /d "%~dp0"

if "%~1"=="" (
    echo Usage: say.bat "text to speak" [--voice folder^|model.pth] [--out file.wav]
    echo        say.bat --text-file script.txt
    exit /b 1
)

if not exist ".venv\Scripts\activate.bat" (
    echo No virtual environment found. Run setup-forge.bat first.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"

set "VOICE=%USERPROFILE%\forge\voices\my-voice"
REM Default voice is passed first, so an explicit --voice / --out wins.
python -m forge.synth --voice "%VOICE%" --out "%~dp0said.wav" %*
if errorlevel 1 (
    echo.
    echo [say] Failed. Pass your own voice explicitly, e.g.:
    echo       say.bat "Hello" --voice "C:\path\to\my-voice"
    echo       say.bat "Hello" --checkpoint "C:\path\to\model.pth" --speaker-ref "C:\path\to\ref.wav"
    pause
    exit /b 1
)

echo.
echo [say] wrote %~dp0said.wav
start "" "%~dp0said.wav"
endlocal
