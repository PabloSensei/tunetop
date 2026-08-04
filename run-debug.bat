@echo off
rem Same as run.bat but keeps the console open so errors are visible.
setlocal
set "ROOT=%~dp0"
"%ROOT%.venv\Scripts\python.exe" "%ROOT%main.py"
echo.
echo Exited with code %errorlevel%.
pause
