@echo off
rem Builds dist\DBD-Kobe-Overlay.exe (single Windows executable). Needs Python 3.10+ from python.org.
setlocal
cd /d "%~dp0\.."
py -m venv .build-venv || goto :error
.build-venv\Scripts\pip install -q -r requirements.txt pyinstaller || goto :error
.build-venv\Scripts\python packaging\make_icon.py || goto :error
.build-venv\Scripts\pyinstaller --noconfirm --clean --distpath dist --workpath build packaging\dbd_overlay.spec || goto :error
echo Built: dist\DBD-Kobe-Overlay.exe
pause
exit /b 0
:error
echo Build failed.
pause
exit /b 1
