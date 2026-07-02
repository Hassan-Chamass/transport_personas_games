@echo off
cd /d "%~dp0webapp"
start "" http://localhost:5000
python app.py
pause
