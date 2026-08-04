@echo off
rem Launch the widget without a console window. Creates the venv on first run.
setlocal
set "ROOT=%~dp0"

if not exist "%ROOT%.venv\Scripts\pythonw.exe" (
    echo Creating virtual environment...
    python -m venv "%ROOT%.venv" || goto :error
    "%ROOT%.venv\Scripts\python.exe" -m pip install -r "%ROOT%requirements.txt" || goto :error
)

start "" "%ROOT%.venv\Scripts\pythonw.exe" "%ROOT%main.py"
exit /b 0

:error
echo.
echo Setup failed. Make sure Python 3.10+ is installed and available as "python".
pause
exit /b 1
