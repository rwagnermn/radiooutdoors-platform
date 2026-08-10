@echo off
setlocal
cd /d "%~dp0"

echo Radio Outdoors POTA test-data reset
echo.
".venv\Scripts\python.exe" manage.py reset_pota_import_test_data
if errorlevel 1 goto :failed

echo.
echo Review the dry-run report above.
pause
set /p POTA_RESET_CONTINUE="Continue to the protected execution step? Type YES: "
if /I not "%POTA_RESET_CONTINUE%"=="YES" goto :cancelled

".venv\Scripts\python.exe" manage.py reset_pota_import_test_data --execute
if errorlevel 1 goto :failed
goto :done

:cancelled
echo Reset cancelled. No execution was requested.
goto :done

:failed
echo The reset did not complete. Review the report above.

:done
echo.
pause
endlocal
