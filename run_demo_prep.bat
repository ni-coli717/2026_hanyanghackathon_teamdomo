@echo off
rem 시연 준비: 공기청정기 연결 코드 + 시연 가동 일정
cd /d "%~dp0"
python -m scripts.demo_prep
timeout /t 20
