@echo off
setlocal
cd /d "%~dp0"
py -3.12 windows\build.py %*
if errorlevel 1 (
  echo.
  echo Build failed. See the error above. Python 3.12 x64 and Visual Studio C++ Build Tools are required.
  pause
  exit /b 1
)
echo.
echo Done: dist\Zf2Lumix-Windows-x64.zip
pause
