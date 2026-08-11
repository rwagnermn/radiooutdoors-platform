cd /d C:\Users\rwagn\Development\radiooutdoors-platform

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo.
    echo Radio Outdoors server is already running on port 8000.
    echo PID: %%a
    echo.
    pause
    exit /b
)

call .venv\Scripts\activate
python manage.py runserver --noreload
pause