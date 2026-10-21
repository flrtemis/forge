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
REM  It finds a Python that can actually import torch and coqui-TTS:
REM  FORGE's .venv if present, else the "py" launcher, else python on PATH.
REM  Force one with:  set FORGE_PY=C:\path\to\python.exe
REM ============================================================
setlocal
cd /d "%~dp0"

set "PY="
if defined FORGE_PY call :check "%FORGE_PY%"
if not defined PY if exist "%~dp0..\.venv\Scripts\python.exe" call :check "%~dp0..\.venv\Scripts\python.exe"
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" call :check "%~dp0.venv\Scripts\python.exe"
if not defined PY call :checkpy 3.11
if not defined PY call :checkpy 3.12
if not defined PY call :checkpy 3.10
if not defined PY call :checkpy 3.13
if not defined PY call :checkplain

if not defined PY goto :nopython

"%PY%" speak.py %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
endlocal & exit /b %RC%

:check
"%~1" -c "import torch, TTS.Configs; from TTS.tts.configs.xtts_config import XttsConfig" >nul 2>&1
if not errorlevel 1 set "PY=%~1"
exit /b

:checkpy
py -%~1 -c "import torch, TTS.Configs; from TTS.tts.configs.xtts_config import XttsConfig" >nul 2>&1
if not errorlevel 1 set "PY=py -%~1"
exit /b

:checkplain
python -c "import torch, TTS.Configs; from TTS.tts.configs.xtts_config import XttsConfig" >nul 2>&1
if not errorlevel 1 set "PY=python"
exit /b

:nopython
echo.
echo [!] I could not find a Python that can fully load coqui-TTS.
echo.
echo     Find out what you have:
echo       where python
echo       py -0p
echo       python -c "import torch, TTS; print('ok')"
echo.
echo     Most common cause is a numpy/numba clash, which shows up as
echo       "Numba needs NumPy 2.3 or less. Got NumPy 2.4."
echo     Fix it with:
echo       python -m pip install "numpy<2.4"
echo
echo     If a package is actually missing, install both once:
echo       pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu130
echo       pip install coqui-TTS
echo.
echo     Already have a venv elsewhere? Tell me where:
echo       set FORGE_PY=C:\path\to\python.exe
echo.
pause
exit /b 1
