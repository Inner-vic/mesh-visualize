@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" mesh_eval.py demo --out "outputs\demo-%RANDOM%-%RANDOM%" --open
if errorlevel 1 pause
