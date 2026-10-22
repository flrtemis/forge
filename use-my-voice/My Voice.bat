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
REM The saved settings are read into four separate parts, so that picking a
REM menu option changes ONE part and leaves the rest alone (2 then 4 = slower
REM AND steadier). Anything unrecognised lands in EX and is passed through -
REM that includes old-style lines with several flags on them, and a flag whose
REM value sits on the next line (EX keeps them in order, a space apart).
set "SP="
set "TP="
set "LG="
set "EX="
if exist "%SAVED%" (
    for /f "usebackq tokens=* delims=" %%L in ("%SAVED%") do (
        set "L=%%L"
        if not "!L!"=="" if not "!L:~0,1!"=="#" if /i not "!L:~0,3!"=="REM" if /i not "!L:~0,2!"=="::" (
            if /i "!L:~0,8!"=="--speed " (
                set "V=!L:~8!"
                if "!V: --=!"=="!V!" (set "SP=!V!") else set "EX=!EX! !L!"
            ) else if /i "!L:~0,14!"=="--temperature " (
                set "V=!L:~14!"
                if "!V: --=!"=="!V!" (set "TP=!V!") else set "EX=!EX! !L!"
            ) else if /i "!L:~0,7!"=="--lang " (
                set "V=!L:~7!"
                if "!V: --=!"=="!V!" (set "LG=!V!") else set "EX=!EX! !L!"
            ) else (
                set "EX=!EX! !L!"
            )
        )
    )
)
call :build

REM ---- the four parts, glued back into one set of flags ----
:build
set "OPTIONS="
REM  Extras go first, so anything switched on in the menu comes after them
REM  and wins (speak.py keeps the last value it is given for a flag).
if defined EX set "OPTIONS=!OPTIONS! !EX!"
if defined SP set "OPTIONS=!OPTIONS! --speed !SP!"
if defined TP set "OPTIONS=!OPTIONS! --temperature !TP!"
if defined LG set "OPTIONS=!OPTIONS! --lang !LG!"
if defined OPTIONS set "OPTIONS=!OPTIONS:~1!"
exit /b

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
REM  X is the last character, so both a timeout and a literal X give
REM  ERRORLEVEL 10 - that is the "one second has gone by" tick.
choice /C 1234567NQX /N /T 1 /D X >nul
set "KEY=%ERRORLEVEL%"
if "%KEY%"=="10" goto :tick
goto :handle

:tick
set /a LEFT-=1
if %LEFT% LEQ 0 goto :start
goto :countdown

:menu_untimed
set "LEFT=0"
call :draw
choice /C 1234567NQ /N >nul
set "KEY=%ERRORLEVEL%"
goto :handle

REM ---- what each key does. 1-6 switch a setting on or off (they add up),
REM     7 or N starts with whatever is on now, Q quits.
:handle
if "%KEY%"=="1" goto :clear
if "%KEY%"=="2" goto :toggle_speed
if "%KEY%"=="3" goto :toggle_expr
if "%KEY%"=="4" goto :toggle_steady
if "%KEY%"=="5" goto :language
if "%KEY%"=="6" goto :custom
if "%KEY%"=="7" goto :start
if "%KEY%"=="8" goto :start
if "%KEY%"=="9" goto :quit
goto :menu

:clear
set "SP=" & set "TP=" & set "LG=" & set "EX="
goto :save

:toggle_speed
if defined SP (set "SP=") else (set "SP=0.9")
goto :save

:toggle_expr
if "!TP!"=="0.85" (set "TP=") else (set "TP=0.85")
goto :save

:toggle_steady
if "!TP!"=="0.6" (set "TP=") else (set "TP=0.6")
goto :save

REM ---- one screen of menu, with the countdown at the bottom ----
:draw
set "C1= "
set "C2= "
set "C3= "
set "C4= "
set "C5= "
set "C6= "
if not defined SP if not defined TP if not defined LG if not defined EX set "C1=x"
if defined SP set "C2=x"
if "!TP!"=="0.85" set "C3=x"
if "!TP!"=="0.6" set "C4=x"
if defined LG set "C5=x"
if defined EX set "C6=x"
cls
echo.
echo   ============================================================
echo     MY VOICE                                     x = switched on
echo   ============================================================
echo.
if defined OPTIONS (echo     Right now: !OPTIONS!) else echo     Right now: normal speech
echo.
echo    !C1!  1   Normal speech            switch everything off
echo    !C2!  2   Slower and clearer       --speed 0.9
echo    !C3!  3   More expressive          --temperature 0.85
echo    !C4!  4   Steadier, predictable    --temperature 0.6
echo    !C5!  5   Another language ...     --lang es
echo    !C6!  6   Extra flags ...          type anything
echo.
echo        7   Start watching the clipboard with the above
echo        Q   Quit
echo     Press as many numbers as you like before starting - they add up.
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
call :build
REM  One flag per line, so the menu can read the four parts back separately.
REM  "echo" with nothing after it prints "ECHO is on.", so when everything is
REM  switched off the file is deleted instead of written.
if not defined OPTIONS (
    del "%SAVED%" >nul 2>&1
) else (
    > "%SAVED%" break
    if defined SP (
        >> "%SAVED%" echo --speed !SP!
    )
    if defined TP (
        >> "%SAVED%" echo --temperature !TP!
    )
    if defined LG (
        >> "%SAVED%" echo --lang !LG!
    )
    if defined EX (
        >> "%SAVED%" echo !EX!
    )
)
goto :menu

:language
echo.
echo   Languages: en es fr de it pt pl tr ru nl cs ar zh-cn hu ko ja hi
if defined LG echo   Switched on now: --lang !LG!
set "LANGCODE="
set /p LANGCODE=  Type a language code (Enter switches it off): 
if defined LANGCODE (set "LG=!LANGCODE!") else set "LG="
goto :save

:custom
echo.
echo   Anything speak.py understands can go here, on top of what is on.
echo   Examples:  --device cpu    --speak-now    --speed 1.1
if defined EX echo   Switched on now: !EX!
set "CUSTOM="
set /p CUSTOM=  Extra flags (Enter switches them off): 
if defined CUSTOM (set "EX=!CUSTOM!") else set "EX="
goto :save

:start
call :build
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
