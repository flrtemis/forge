@echo off
setlocal EnableExtensions
title My Voice

REM ==================================================================
REM  MY VOICE - double-click this. It ASKS how you want to sound,
REM  remembers your answer, then reads whatever you copy.
REM
REM  You never have to edit this file. If you would rather pass flags
REM  yourself, they all work too:
REM      "My Voice.bat" --speed 0.9 --lang es
REM      "My Voice.bat" --file article.txt
REM      (drop a .txt file onto the icon and it reads that file)
REM ==================================================================

set "APP=C:\Users\l3ung\Desktop\forge\use-my-voice\speak.py"
set "PY=C:\Users\l3ung\Desktop\forge\.venv\Scripts\python.exe"
set "VOICE=%USERPROFILE%\forge\voices\my-voice"
set "SAVED=%LOCALAPPDATA%\MyVoice\settings.txt"
if not exist "%LOCALAPPDATA%\MyVoice" mkdir "%LOCALAPPDATA%\MyVoice" >nul 2>&1

if not exist "%APP%" if exist "%~dp0use-my-voice\speak.py" set "APP=%~dp0use-my-voice\speak.py"
if not exist "%APP%" if exist "%~dp0forge\use-my-voice\speak.py" set "APP=%~dp0forge\use-my-voice\speak.py"
if not exist "%APP%" if exist "%USERPROFILE%\forge\use-my-voice\speak.py" set "APP=%USERPROFILE%\forge\use-my-voice\speak.py"
if not exist "%PY%" set "PY=python"

if not exist "%APP%" goto :noapp

REM ---- flags on the command line? use them as-is, no menu ----
if not "%~1"=="" goto :run_args

REM ---- otherwise: ask ----
set "OPTIONS="
if exist "%SAVED%" set /p OPTIONS=<"%SAVED%"

:menu
cls
echo.
echo   ============================================================
echo     MY VOICE
echo   ============================================================
echo.
if defined OPTIONS echo     Right now: %OPTIONS%
if not defined OPTIONS echo     Right now: normal speech
echo.
echo     1   Normal speech
echo     2   Slower and clearer        --speed 0.9
echo     3   More expressive           --temperature 0.85
echo     4   Steadier, predictable     --temperature 0.6
echo     5   Another language ...      --lang es
echo     6   Custom flags ...          type anything
echo.
echo     N   Start watching the clipboard with the above
echo     Q   Quit
echo.
choice /C 123456NQ /N /T 8 /D N /M "  Press 1-6 to change, N to start now: "

if errorlevel 8 goto :quit
if errorlevel 7 goto :start
if errorlevel 6 goto :custom
if errorlevel 5 goto :language
if errorlevel 4 set "OPTIONS=--temperature 0.6" & goto :save
if errorlevel 3 set "OPTIONS=--temperature 0.85" & goto :save
if errorlevel 2 set "OPTIONS=--speed 0.9" & goto :save
if errorlevel 1 set "OPTIONS=" & goto :save

:save
> "%SAVED%" echo %OPTIONS%
goto :menu

:language
echo.
echo   Languages: en es fr de it pt pl tr ru nl cs ar zh-cn hu ko ja hi
set "LANGCODE="
set /p LANGCODE=  Type a language code (Enter for es): 
if not defined LANGCODE set "LANGCODE=es"
set "OPTIONS=--lang %LANGCODE%"
goto :save

:custom
echo.
echo   Examples:  --speed 0.9   --temperature 0.85   --lang de   --speak-now
echo   Combine:   --speed 0.9 --temperature 0.85
set "OPTIONS="
set /p OPTIONS=  Flags: 
goto :save

:start
cls
echo.
echo   ============================================================
echo     Listening for the clipboard
echo   ============================================================
echo.
if defined OPTIONS echo     Settings: %OPTIONS%
if not defined OPTIONS echo     Settings: normal speech
echo.
echo     Copy text anywhere - Ctrl+C - and it is read aloud here.
echo     Leave this window open - minimise it if you like.
echo     Close it, or press Ctrl+C, to stop.
echo.
echo     Your choice is remembered in:
echo       %SAVED%
echo     Delete that file if you want to start over.
echo.
"%PY%" "%APP%" --watch --voice "%VOICE%" %OPTIONS%
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :oops
endlocal & exit /b 0

:run_args
if exist "%~1" goto :run_file
"%PY%" "%APP%" --voice "%VOICE%" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
endlocal & exit /b %RC%

:run_file
REM a file was dropped on the icon - read that file, with your saved settings
if defined OPTIONS echo   Settings: %OPTIONS%
"%PY%" "%APP%" --voice "%VOICE%" --file "%~1" %OPTIONS%
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
endlocal & exit /b %RC%

:quit
endlocal & exit /b 0

:noapp
echo.
echo   Could not find speak.py. Looked for:
echo     %APP%
echo   Put speak.py next to this .bat, or edit the APP= line above.
echo.
pause
endlocal & exit /b 1

:oops
echo.
echo   Stopped with code %RC% - the message above says why.
echo.
pause
endlocal & exit /b %RC%
