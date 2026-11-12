@echo off
rem Konect demo web: serves this folder and opens the demo page (Chrome or Edge).
cd /d "%~dp0"
start "" http://localhost:8765/demo/
python -m http.server 8765
