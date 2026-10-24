@echo off
rem Run the measurement (resident report) app locally. Opens http://localhost:8502
cd /d "%~dp0"
set APP_ENV=local
set DATA_MODE=live
start "" http://localhost:8502
python -m streamlit run measurement_app.py --server.port 8502 --server.headless true
pause
