@echo off
cd /d "%~dp0"
py -3.12 --version >nul 2>nul
if not errorlevel 1 (py -3.12 setup.py %* & exit /b)
where py >nul 2>nul
if errorlevel 1 (python setup.py %*) else (py -3 setup.py %*)
if errorlevel 1 pause
