@echo off
cd /d "%~dp0"
set "MOA_PYTHON=python"
if exist "%LocalAppData%\Python\pythoncore-3.14-64\python.exe" set "MOA_PYTHON=%LocalAppData%\Python\pythoncore-3.14-64\python.exe"
if not exist "setup-temp" mkdir "setup-temp"
set "TEMP=%~dp0setup-temp"
set "TMP=%TEMP%"
"%MOA_PYTHON%" -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Setup completed. Double-click start.bat.
pause
exit /b 0
:failed
echo Setup failed. Python 3.14 64-bit and an Internet connection are required.
pause
exit /b 1
