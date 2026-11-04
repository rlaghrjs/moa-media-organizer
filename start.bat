@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
 echo Local Python environment is missing. Please run setup.bat first.
 pause
 exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py"
