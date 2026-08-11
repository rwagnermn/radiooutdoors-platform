@echo off
cd /d C:\Users\rwagn\Development\radiooutdoors-platform
call .venv\Scripts\activate

echo.
echo === APPLYING RADIO OUTDOORS MIGRATIONS ===
python manage.py migrate

echo.
echo === DJANGO SYSTEM CHECK ===
python manage.py check

echo.
pause