@echo off
cd /d C:\Users\rwagn\Development\radiooutdoors-platform
call .venv\Scripts\activate

echo.
echo === CORE MIGRATION STATUS ===
python manage.py showmigrations core

echo.
echo === CHECK FOR MISSING MIGRATIONS ===
python manage.py makemigrations --check --dry-run

echo.
pause