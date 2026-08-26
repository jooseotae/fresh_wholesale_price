@echo off
rem Garak wholesale price - daily refresh
rem Windows Task Scheduler runs this every day at 14:00 (after fruit auctions settle).
rem NOTE: keep this file ASCII-only. cmd.exe reads it as the OEM codepage (cp949),
rem       so UTF-8 Korean text here would break parsing.
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PY=C:\Python314\python.exe"
if not exist "%PY%" set "PY=python"

rem 1) BIX5 source - 79 representative items (price) + 3 categories (volume)
"%PY%" src\collect_bix5.py
set RC_BIX5=%ERRORLEVEL%

rem 2) Legacy 12-item source - keeps the 400-day history series alive
"%PY%" src\collect.py
set RC_LEGACY=%ERRORLEVEL%

rem 3) News board (trend / forecast postings)
"%PY%" src\collect_news.py
set RC_NEWS=%ERRORLEVEL%

rem 4) Rebuild the drilldown dashboard even if collection failed, so the page
rem    still shows the last good data.
"%PY%" src\build_v2.py

if not "%RC_BIX5%"=="0"   echo [WARN] BIX5 collection failed - see logs\collect.log
if not "%RC_LEGACY%"=="0" echo [WARN] legacy collection failed - see logs\collect.log
if not "%RC_NEWS%"=="0"   echo [WARN] news collection failed - see logs\collect.log

rem 5) Auto-commit and push so Vercel redeploys with today's data.
rem    Skips if nothing changed. Non-fatal if git/network fails.
rem    First-time push needs manual auth via Git Credential Manager.
where git >nul 2>&1
if errorlevel 1 goto :skip_git

git diff --quiet HEAD -- data/prices.sqlite out/dashboard.html 2>nul
if not errorlevel 1 (
    echo [git] no data changes, skipping push
    goto :skip_git
)

for /f "tokens=1-3 delims=- " %%a in ("%date%") do set TODAY=%%a-%%b-%%c
git add data/prices.sqlite out/dashboard.html logs/collect.log 2>nul
git commit -q -m "chore: daily data refresh %TODAY%" 2>nul
if errorlevel 1 (
    echo [git] commit skipped
    goto :skip_git
)

git push -q origin main 2>>logs\collect.log
if errorlevel 1 echo [WARN] git push failed - Vercel not redeployed. Check auth.

:skip_git
endlocal
