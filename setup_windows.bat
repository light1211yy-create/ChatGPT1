@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 goto failed

if exist ".venv\Scripts\python.exe" goto verify
if exist ".venv\" (
    echo Existing .venv is not a Windows Python environment.
    echo Move only .venv aside and retry. Do not delete the data folder.
    goto failed
)

py -3.12 --version >nul 2>&1
if not errorlevel 1 (
    py -3.12 -m venv .venv
    if errorlevel 1 goto failed
    goto verify
)

python -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 (
    echo Install Python 3.12 64-bit from https://www.python.org/downloads/windows/
    echo Include the Python launcher or add Python to PATH.
    goto failed
)
python -m venv .venv
if errorlevel 1 goto failed

:verify
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32 else 1)"
if errorlevel 1 (
    echo The virtual environment must use Python 3.12 64-bit.
    echo Move only .venv aside and retry. Keep your data folder.
    goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto failed

echo.
echo Setup completed. Double-click start_windows.bat to open MAKASE AI Studio.
pause
exit /b 0

:failed
echo.
echo Setup failed. Read the error above and the Windows instructions in README.md.
pause
exit /b 1
