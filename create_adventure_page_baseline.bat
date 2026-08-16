@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Radio Outdoors safety checkpoint helper.
set "TASK_ID=RO-ADVENTURE-PAGE-BASELINE-20260816"
set "BASELINE_BRANCH=safety/adventure-page-v1-20260816"
set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=%SCRIPT_DIR%.venv\Scripts\python.exe"

pushd "%SCRIPT_DIR%" >nul 2>&1
if errorlevel 1 goto :end

echo.
echo %TASK_ID%
echo Creating a safety baseline before Adventure page redesign work.
echo.

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo ERROR: Put this batch file in the Radio Outdoors repository root.
  goto :end
)

git status --short
git branch --show-current
git diff --check
if errorlevel 1 (
  echo ERROR: Fix whitespace errors before continuing.
  goto :end
)

git show-ref --verify --quiet "refs/heads/%BASELINE_BRANCH%"
if not errorlevel 1 (
  echo ERROR: Branch "%BASELINE_BRANCH%" already exists. Nothing changed.
  goto :end
)

git switch -c "%BASELINE_BRANCH%"
if errorlevel 1 goto :end

git add -A -- . ^
  ":(exclude)db.sqlite3" ^
  ":(exclude)*.sqlite3" ^
  ":(exclude)media/**" ^
  ":(exclude)local-backups/**" ^
  ":(exclude)artifacts/**" ^
  ":(exclude)generated_images/**" ^
  ":(exclude)project-manager-logs/**" ^
  ":(exclude)logs/**" ^
  ":(exclude)*.log" ^
  ":(exclude).venv/**" ^
  ":(exclude)**/__pycache__/**" ^
  ":(exclude).env" ^
  ":(exclude).env.*" ^
  ":(exclude)*.pem" ^
  ":(exclude)*.key" ^
  ":(exclude)openai_api_key*.txt"

echo.
echo Proposed staged files:
git diff --cached --name-status
echo.
set /p "CONFIRM=Type YES to create the checkpoint commit, or anything else to cancel: "
if /I not "%CONFIRM%"=="YES" goto :end

git diff --cached --quiet
if not errorlevel 1 (
  echo Nothing eligible was staged; no commit created.
  goto :end
)

git commit -m "Safety baseline: preserved Adventure page before V2 redesign"
if errorlevel 1 goto :end

echo.
echo Checkpoint created:
git branch --show-current
git log -1 --oneline
git status --short

:end
echo.
echo Finished. No GitHub push was performed.
popd >nul 2>&1
pause
endlocal