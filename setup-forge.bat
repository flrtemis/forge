@echo off
REM ============================================================
REM  FORGE one-time setup — double-click this, that's it.
REM  Creates a virtual environment (.venv) and installs
REM  everything inside it, so nothing collides with your
REM  other Python projects ever again.
REM ============================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo [1/3] Creating virtual environment .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo FAILED to create the venv. Is Python on PATH? Run: python --version
        pause
        exit /b 1
    )
) else (
    echo [1/3] Virtual environment already exists, reusing it.
)

call ".venv\Scripts\activate.bat"

echo [2/3] Installing CUDA-enabled torch (this is the big one) ...
REM cu130 because the RTX 5070 Ti is Blackwell sm_120 - needs CUDA 12.8+ kernels
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu130
if errorlevel 1 (
    echo Torch install failed. Check your internet and try again.
    pause
    exit /b 1
)

echo [3/3] Installing FORGE requirements ...
pip install -r requirements.txt
if errorlevel 1 (
    echo Requirements install hit an error. Send Rowan the output above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Setup complete. From now on, launch with run-forge.bat
echo  (it activates the venv for you — you can't forget it).
echo ============================================================
pause
