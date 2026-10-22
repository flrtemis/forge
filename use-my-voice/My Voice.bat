@echo off
setlocal EnableExtensions EnableDelayedExpansion
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
REM ---- how many seconds the menu waits before starting ------------------
REM  8   = default: quick, but you have time to press a key
REM  20  = plenty of time to think
REM  0   = never auto-start; wait until you press a key (no countdown)
set "WAIT=8"
REM  (leave the line above as a plain number - anything else falls back to 8)
for /f "delims=0123456789" %%A in ("%WAIT%") do set "WAIT=8"
REM ---------------------------------------------------------------------

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
REM Load saved settings. One line with everything on it works, and so does
REM one flag per line, with blank lines and # / REM comments in between.
set "OPTIONS="
if exist "%SAVED%" (
    for /f "usebackq tokens=* delims=" %%L in ("%SAVED%") do (
        set "LINE=%%L"
        if not "!LINE:~0,1!"=="#" (
            if /i not "!LINE:~0,3!"=="REM" (
                if /i not "!LINE:~0,2!"=="::" (
                    set "OPTIONS=!OPTIONS! !LINE!"
                )
            )
        )
    )
)

REM ==================================================================
REM  The menu. If WAIT is above zero it counts down visibly: one
REM  'choice' per second (so a key press is caught immediately) and a
REM  redraw of the bar so you can see the time left ticking away.
REM ==================================================================
:menu
if "%WAIT%"=="0" goto :menu_untimed
set "LEFT=%WAIT%"

:countdown
call :draw
REM  X is the 9th character, so both a timeout and a literal X give
REM  ERRORLEVEL 9 - that is the "one second has gone by" tick.
choice /C 123456NQX /N /T 1 /D X >nul
set "KEY=%ERRORLEVEL%"
if "%KEY%"=="9" goto :tick
goto :handle

:tick
set /a LEFT-=1
if %LEFT% LEQ 0 goto :start
goto :countdown

:menu_untimed
set "LEFT=0"
call :draw
choice /C 123456NQ /N >nul
set "KEY=%ERRORLEVEL%"
goto :handle

REM ---- what each key does (1-6 pick a setting, 7 = start, 8 = quit) ----
:handle
if "%KEY%"=="1" set "OPTIONS=" & goto :save
if "%KEY%"=="2" set "OPTIONS=--speed 0.9" & goto :save
if "%KEY%"=="3" set "OPTIONS=--temperature 0.85" & goto :save
if "%KEY%"=="4" set "OPTIONS=--temperature 0.6" & goto :save
if "%KEY%"=="5" goto :language
if "%KEY%"=="6" goto :custom
if "%KEY%"=="7" goto :start
if "%KEY%"=="8" goto :quit
goto :menu

REM ---- one screen of menu, with the countdown at the bottom ----
:draw
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
call :bar
exit /b

REM ---- the countdown bar itself ----
:bar
if "%WAIT%"=="0" goto :bar_untimed
REM  FILL = how much of the wait is already used up, so the bar fills up
REM  as the time runs out.
set /a FILL=(%WAIT%-%LEFT%)*20/%WAIT% 2>nul
if %FILL% LSS 0 set "FILL=0"
if %FILL% GTR 20 set "FILL=20"
set /a EMPTY=20-FILL
REM  Two 20-character rulers, sliced by delayed expansion: hashes for the time
REM  already spent, dashes for the time left. A FOR loop cannot build this -
REM  %BAR% inside a block expands once, before the loop runs.
set "RULER=####################"
set "GAPS=--------------------"
set "DONE=!RULER:~0,%FILL%!"
set "LEFTBAR=!GAPS:~0,%EMPTY%!"
echo     [!DONE!!LEFTBAR!]  %LEFT%s  then it starts on its own
echo.
exit /b

:bar_untimed
echo     No countdown - press a key when you are ready.
echo.
exit /b

:save
REM  Save exactly what was picked. "echo" with nothing after it prints
REM  "ECHO is on.", so an empty choice deletes the file instead.
if defined OPTIONS (
    > "%SAVED%" echo %OPTIONS%
) else (
    del "%SAVED%" >nul 2>&1
)
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
