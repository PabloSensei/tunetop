@echo off
rem Build a standalone Tunetop.exe into dist\ (no Python needed to run it).
setlocal
set "ROOT=%~dp0"

if not exist "%ROOT%.venv\Scripts\python.exe" (
    echo Run run.bat once first to create the virtual environment.
    pause
    exit /b 1
)

"%ROOT%.venv\Scripts\python.exe" -m pip install --quiet pyinstaller || goto :error

"%ROOT%.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name Tunetop ^
    --distpath "%ROOT%dist" --workpath "%ROOT%build" --specpath "%ROOT%build" ^
    --add-data "%ROOT%skins;skins" ^
    --add-data "%ROOT%locales;locales" ^
    "%ROOT%main.py" || goto :error

echo.
echo Done: %ROOT%dist\Tunetop.exe
exit /b 0

:error
echo.
echo Build failed.
pause
exit /b 1
