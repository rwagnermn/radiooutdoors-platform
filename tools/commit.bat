@echo off
cls

cd /d "%~dp0"

echo.
echo ==========================================
echo      Radio Outdoors Git Backup
echo ==========================================
echo.

git status

echo.
set /p MESSAGE=Commit message: 

echo.
git add .

git commit -m "%MESSAGE%"

if errorlevel 1 goto End

echo.
git push

echo.
echo -------- Last 5 Commits --------
git log --oneline -5

:End
echo.
pause