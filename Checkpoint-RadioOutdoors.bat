@echo off
cd /d C:\Users\rwagn\Development\radiooutdoors-platform
call .venv\Scripts\activate

echo.
echo ==========================================
echo RADIO OUTDOORS CHECKPOINT PRE-FLIGHT
echo ==========================================
echo.

echo === GIT STATUS ===
git status

echo.
echo === DIFF CHECK ===
git diff --check

echo.
echo === DJANGO CHECK ===
python manage.py check

echo.
echo === CORE MIGRATIONS ===
python manage.py showmigrations core

echo.
echo === MISSING MIGRATION CHECK ===
python manage.py makemigrations --check --dry-run

echo.
echo === DIFF STAT ===
git diff --stat

echo.
echo ==========================================
echo PRE-FLIGHT COMPLETE
echo.
echo Review the results above BEFORE staging.
echo Do not continue if you see API keys,
echo db.sqlite3, media files, bundles, or temp files.
echo ==========================================
echo.
pause