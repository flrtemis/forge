@echo off
setlocal
title My Voice - read what I copied

REM ==================================================================
REM   Click this AFTER copying text. Reads the clipboard once, then stops.
REM   Same OPTIONS line as "Watch My Voice.bat" if you want to tweak it.
REM ==================================================================
set "OPTIONS="

set "APP=C:\Users\l3ung\Desktop\forge\use-my-voice\speak.py"
set "PY=C:\Users\l3ung\Desktop\forge\.venv\Scripts\python.exe"
set "VOICE=%USERPROFILE%\forge\voices\my-voice"

if not exist "%APP%" if exist "%~dp0use-my-voice\speak.py" set "APP=%~dp0use-my-voice\speak.py"
if not exist "%APP%" if exist "%~dp0forge\use-my-voice\speak.py" set "APP=%~dp0forge\use-my-voice\speak.py"
if not exist "%PY%" set "PY=python"
if not exist "%APP%" goto :noapp

"%PY%" "%APP%" --voice "%VOICE%" %OPTIONS% %*
if errorlevel 1 pause
endlocal & exit /b 0

:noapp
echo.
echo  Could not find speak.py - fix the APP= line in this file.
echo    %APP%
pause
endlocal & exit /b 1
