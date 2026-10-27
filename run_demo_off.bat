@echo off
rem 시연 끝: 시연 가상 예보를 지우고 실제 예보로 기기 일정·지도를 되돌린다.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python -m scripts.demo_prep --off
pause
