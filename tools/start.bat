@echo off
setlocal
cd /d "%~dp0\.."
call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1
python manage.py runserver
