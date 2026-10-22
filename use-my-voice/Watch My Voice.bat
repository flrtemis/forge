@echo off
setlocal
title My Voice - clipboard reader  [Ctrl+C or close this window to stop]

REM ==================================================================
REM   THIS IS THE ONLY LINE YOU EVER EDIT.
REM   Leave it empty for normal speech. Examples - combine as you like:
REM
REM     set "OPTIONS=--speed 0.9"
REM     set "OPTIONS=--temperature 0.85"
REM     set "OPTIONS=--temperature 0.6"
REM     set "OPTIONS=--lang es"
REM     set "OPTIONS=--speed 0.9 --temperature 0.85"
REM
REM   Copy this file to make variants - e.g. "My Voice Slow.bat",
REM   "My Voice Spanish.bat" - and change just this line in each.
REM ==================================================================
set "OPTIONS="


REM ----- where things live: edit only if you move the files -----
set "APP=C:\Users\l3ung\Desktop\forge\use-my-voice\speak.py"
set "PY=C:\Users\l3ung\Desktop\forge\.venv\Scripts\python.exe"
set "VOICE=%USERPROFILE%\forge\voices\my-voice"
REM --------------------------------------------------------------


REM find speak.py if it is not where we expect
if not exist "%APP%" if exist "%~dp0use-my-voice\speak.py" set "APP=%~dp0use-my-voice\speak.py"
if not exist "%APP%" if exist "%~dp0forge\use-my-voice\speak.py" set "APP=%~dp0forge\use-my-voice\speak.py"
if not exist "%APP%" if exist "%USERPROFILE%\forge\use-my-voice\speak.py" set "APP=%USERPROFILE%\forge\use-my-voice\speak.py"
if not exist "%PY%" set "PY=python"

if not exist "%APP%" goto :noapp

echo.
echo  ============================================================
echo    MY VOICE  -  clipboard reader
echo  ============================================================
echo.
echo    Copy text anywhere   [Ctrl+C]   and it is read aloud here.
echo.
echo    Leave this window open. Minimise it if you like.
echo    Close it, or press Ctrl+C, to stop listening.
echo.
echo    It ignores whatever was already on the clipboard when it
echo    started, so old text is never read out loud by accident.
echo.
if defined OPTIONS echo    Options in use: %OPTIONS%
echo  ------------------------------------------------------------
echo    Slower and clearer ............  --speed 0.9
echo    Brisk ..........................  --speed 1.1
echo    Steadier, predictable ..........  --temperature 0.6
echo    More expressive, less flat .....  --temperature 0.85
echo    Other language .................  --lang es
echo    Read what is already copied ....  --speak-now
echo  ------------------------------------------------------------
echo.
echo    Voice: %VOICE%
echo    Model loads once - the first sentence takes 15-30 seconds.
echo.

"%PY%" "%APP%" --watch --voice "%VOICE%" %OPTIONS% %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :oops
endlocal & exit /b 0

:noapp
echo.
echo  Could not find speak.py. Looked at:
echo    %APP%
echo.
echo  Open this .bat in Notepad and fix the APP= line near the top.
echo.
pause
endlocal & exit /b 1

:oops
echo.
echo  It stopped with code %RC%. The message above says why.
echo  Common fixes:
echo    No module named ...        use the .venv python, or pip install it
echo    Could not find your model  edit the VOICE= line in this file
echo.
pause
endlocal & exit /b %RC%
