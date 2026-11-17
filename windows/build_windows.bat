@echo off
rem Run this ON WINDOWS. Produces dist\Cursor AI.exe (one file you can copy to any Windows PC).
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 goto :nopython
python -c "import tkinter" >nul 2>nul
if errorlevel 1 goto :notk

if exist .venv rmdir /s /q .venv
python -m venv .venv
if errorlevel 1 goto :fail
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 goto :fail

pyinstaller --noconfirm --windowed --onefile --icon icon.ico --add-data "icon.ico;." --name "Cursor AI" --hidden-import keyring.backends.Windows --collect-submodules win32ctypes app.py
if errorlevel 1 goto :fail

echo.
echo Built: dist\Cursor AI.exe
echo First launch: if Windows SmartScreen warns, click More info, then Run anyway.
pause
exit /b 0

:nopython
echo Python 3 was not found. Install it from https://www.python.org/downloads/windows/
echo and tick "Add python.exe to PATH" in the installer, then run this again.
pause
exit /b 1

:notk
echo This Python has no Tk. Reinstall from python.org and keep "tcl/tk and IDLE" ticked.
pause
exit /b 1

:fail
echo Build failed. Scroll up for the error message.
pause
exit /b 1
