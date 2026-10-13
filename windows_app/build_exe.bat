@echo off
setlocal
cd /d "%~dp0"
py -3 -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name RotatorControl --paths ..\sdr_scan --hidden-import rotator_scan --collect-all bleak --collect-all numpy rotator_ble.py
if errorlevel 1 exit /b 1
echo Ready: dist\RotatorControl.exe
