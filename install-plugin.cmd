@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" install_plugin.py %*
if errorlevel 1 pause
