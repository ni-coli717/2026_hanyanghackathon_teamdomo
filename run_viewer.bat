@echo off
rem Run the public viewer app locally. Opens http://localhost:8501. 서버 로그: data\private\viewer.log
cd /d "%~dp0"
set APP_ENV=local
set DATA_MODE=live
set PYTHONIOENCODING=utf-8
if not exist data\private mkdir data\private
start "" http://localhost:8501
python -m streamlit run viewer_app.py --server.port 8501 --server.headless true >> data\private\viewer.log 2>&1
pause
