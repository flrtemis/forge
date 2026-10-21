@echo off
REM ============================================================
REM  FORGE TTS server - lets Firefox (and anything else) speak
REM  with your trained voice.
REM
REM    serve-forge.bat                        (newest voice)
REM    serve-forge.bat --voice "D:\voices\my-voice"
REM
REM  Then open http://127.0.0.1:5004/reader in Firefox.
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo No virtual environment found. Run setup-forge.bat first.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"

echo Starting FORGE TTS server on http://127.0.0.1:5004 ...
echo The model loads on the first sentence - that one takes a few seconds.
echo Leave this window open while you read. Ctrl+C here to stop.
echo.

REM Open the reader page in Firefox once the port is up.
start "" cmd /c "timeout /t 4 >nul & start firefox http://127.0.0.1:5004/reader"

python -m forge.server %*
if errorlevel 1 (
    echo.
    echo [serve] Server exited with an error. If it says "No voice given", pass:
    echo        serve-forge.bat --voice "%%USERPROFILE%%\forge\voices\my-voice"
    pause
)
endlocal
