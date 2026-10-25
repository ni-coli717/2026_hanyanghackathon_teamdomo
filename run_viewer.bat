@echo off
rem Run the public viewer app locally. Opens http://localhost:8501
cd /d "%~dp0"
set APP_ENV=local
set DATA_MODE=live
start "" http://localhost:8501
python -m streamlit run viewer_app.py --server.port 8501 --server.headless true
pause
