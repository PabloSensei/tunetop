@echo off
rem Build dist\Tunetop.exe (via build-exe.bat) and then dist\TunetopSetup-<version>.exe,
rem a proper Windows installer built with Inno Setup 6 (https://jrsoftware.org/isinfo.php).
setlocal
set "ROOT=%~dp0"

call "%ROOT%build-exe.bat" || exit /b 1

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo.
    echo Inno Setup 6 not found. Install it with:
    echo     choco install innosetup
    echo or download it from https://jrsoftware.org/isdl.php
    pause
    exit /b 1
)

for /f "delims=" %%v in ('"%ROOT%.venv\Scripts\python.exe" -c "from app import __version__; print(__version__)"') do set "VERSION=%%v"

"%ISCC%" "/DMyAppVersion=%VERSION%" "%ROOT%installer\Tunetop.iss" || goto :error

echo.
echo Done: %ROOT%dist\TunetopSetup-%VERSION%.exe
exit /b 0

:error
echo.
echo Build failed.
pause
exit /b 1
