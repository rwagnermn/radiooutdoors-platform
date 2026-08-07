@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."

echo Current repository status:
git status --short
if errorlevel 1 exit /b 1

echo.
set /p "COMMIT_MESSAGE=Commit message: "
if not defined COMMIT_MESSAGE (
    echo Commit message is required. Nothing was staged, committed, or pushed.
    exit /b 1
)

echo.
echo Enter the files to stage, separated by spaces.
echo Review the list carefully; unrelated files must not be committed.
set /p "STAGE_PATHS=Files to stage: "
if not defined STAGE_PATHS (
    echo No files selected. Nothing was staged, committed, or pushed.
    exit /b 1
)

git add -- %STAGE_PATHS%
if errorlevel 1 exit /b 1

echo.
echo Files staged for commit:
git diff --cached --name-status
git diff --cached --quiet
if not errorlevel 1 (
    echo No staged changes. Nothing was committed or pushed.
    exit /b 1
)

git commit -m "%COMMIT_MESSAGE%"
if errorlevel 1 (
    echo Commit failed. Nothing was pushed.
    exit /b 1
)

echo.
echo Branch and commits that will be pushed:
git branch --show-current
git status -sb
git log --oneline --decorate @{upstream}..HEAD 2>nul
if errorlevel 1 git log --oneline --decorate -5

echo.
set /p "CONFIRM_PUSH=Push these commits? Type YES to continue: "
if /I not "%CONFIRM_PUSH%"=="YES" (
    echo Push cancelled. The local commit was preserved.
    exit /b 0
)

git push
if errorlevel 1 exit /b 1

echo.
echo Push complete.
