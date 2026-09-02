@echo off
rem Garak wholesale price - daily refresh
rem
rem Scheduler runs this THREE times a day:
rem   08:00  run_daily.cmd <vegetable>  -- vegetable auctions confirmed overnight
rem   11:00  run_daily.cmd <fruit>      -- fruit auctions confirmed by 11am
rem   14:00  run_daily.cmd              -- final full refresh (no arg = both)
rem
rem The sector argument is Korean text supplied by Task Scheduler, never written
rem here: this file MUST stay ASCII-only. cmd.exe parses it byte-by-byte in the
rem OEM codepage, and the "chcp 65001" below switches codepage mid-parse -- any
rem non-ASCII byte in the file loses alignment and gets run as a command.
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PY=C:\Python314\python.exe"
if not exist "%PY%" set "PY=python"

set "SECTOR_ARG="
if not "%~1"=="" set "SECTOR_ARG=--sector %~1"

rem 1) BIX5 gauges (price + volume)
"%PY%" src\collect_bix5.py %SECTOR_ARG%
set RC_BIX5=%ERRORLEVEL%

rem 2) Legacy 12-item source - only on full refresh (has fixed items regardless of sector)
if "%~1"=="" (
    "%PY%" src\collect.py
    set RC_LEGACY=%ERRORLEVEL%
)

rem 3) Unit-level prices - filter by sector too so it fits within schedule window
"%PY%" src\collect_unit.py %SECTOR_ARG%
set RC_UNIT=%ERRORLEVEL%

rem 4) News - only on the final full refresh
if "%~1"=="" (
    "%PY%" src\collect_news.py
    set RC_NEWS=%ERRORLEVEL%
)

rem 5) Rebuild the dashboard
"%PY%" src\build_v2.py

if not "%RC_BIX5%"=="0"   echo [WARN] BIX5 collection failed
if defined RC_LEGACY if not "%RC_LEGACY%"=="0" echo [WARN] legacy collection failed
if not "%RC_UNIT%"=="0"   echo [WARN] unit-price collection failed
if defined RC_NEWS if not "%RC_NEWS%"=="0" echo [WARN] news collection failed

rem 6) Auto-commit and push so Vercel redeploys with fresh data
where git >nul 2>&1
if errorlevel 1 goto :skip_git

git diff --quiet HEAD -- data/prices.sqlite out/dashboard.html index.html 2>nul
if not errorlevel 1 (
    echo [git] no data changes, skipping push
    goto :skip_git
)

set "MSG=chore: daily data refresh"
if not "%~1"=="" set "MSG=chore: %~1 refresh"
git add data/prices.sqlite out/dashboard.html index.html logs/collect.log 2>nul
git commit -q -m "%MSG%" 2>nul
if errorlevel 1 (
    echo [git] commit skipped
    goto :skip_git
)

git push -q origin main 2>>logs\collect.log
if errorlevel 1 echo [WARN] git push failed

:skip_git
endlocal
