@echo off
rem One-time setup for unattended git push (Method A auto-deploy to Vercel).
rem Run this ONCE after creating the GitHub repo and a Personal Access Token.
rem
rem 1. Create the repo at https://github.com/new
rem    Owner: jooseotae   Name: fresh_wholesale_price   Visibility: your choice
rem    Do NOT initialize with README/gitignore/license (repo already has commits).
rem
rem 2. Create a Personal Access Token (fine-grained, repo-scoped):
rem    https://github.com/settings/personal-access-tokens/new
rem    - Resource owner: jooseotae
rem    - Repository access: Only select repositories -> fresh_wholesale_price
rem    - Permissions -> Repository -> Contents: Read and write
rem    - Expiration: 1 year (mark your calendar to rotate before expiry)
rem    Copy the token starting with "github_pat_..."
rem
rem 3. Run this file. It prompts for the token and stores it in the remote URL
rem    (safe on a personal Windows account; the URL is git-only and not synced).
rem
setlocal enabledelayedexpansion
cd /d "%~dp0"

set /p TOKEN=Paste your PAT (input hidden? no - Windows cmd shows it): 
if "%TOKEN%"=="" (
  echo Token empty. Aborting.
  exit /b 1
)

git remote set-url origin https://jooseotae:%TOKEN%@github.com/jooseotae/fresh_wholesale_price.git
if errorlevel 1 (
  echo Failed to set remote.
  exit /b 1
)

echo.
echo Pushing initial commits...
git push -u origin main
if errorlevel 1 (
  echo.
  echo Push failed. Check that the repo exists on GitHub and the token has "Contents: Read and write".
  exit /b 1
)

echo.
echo === Setup done ===
echo Remote is configured. Every 14:00 the scheduler will auto-push to GitHub,
echo which triggers Vercel redeploy.
echo.
echo To rotate the token later, run this file again with the new token.
endlocal
