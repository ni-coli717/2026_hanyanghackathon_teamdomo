@echo off
rem Run the test suite; output goes to data\private\pytest.txt (gitignored).
cd /d "%~dp0"
if not exist data\private mkdir data\private
python -m pip install -q Authlib >nul 2>&1
set PYTHONIOENCODING=utf-8
python -m pytest -q --no-header -p no:cacheprovider tests > data\private\pytest.txt 2>&1
python -c "import streamlit;print('streamlit',streamlit.__version__)" >> data\private\pytest.txt 2>&1
