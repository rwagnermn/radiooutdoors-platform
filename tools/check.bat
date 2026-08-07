@echo off
setlocal
cd /d "%~dp0\.."

call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1

echo Running Django system checks...
python manage.py check
if errorlevel 1 exit /b 1

echo.
echo Running automated tests...
python manage.py test
if errorlevel 1 exit /b 1

echo.
echo All checks passed.
