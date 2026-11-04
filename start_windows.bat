@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 goto failed

if not exist ".venv\Scripts\python.exe" (
    echo Run setup_windows.bat first.
    goto failed
)
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)"
if errorlevel 1 (
    echo Python 3.12 is required. See README.md to recreate only .venv.
    goto failed
)

echo Starting MAKASE AI Studio. Keep this window open while using the app.
echo Press Ctrl+C to stop. If the browser does not open, use the displayed URL.
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless false --browser.gatherUsageStats false
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo Startup failed or stopped. See the error above and README.md.
pause
exit /b 1
