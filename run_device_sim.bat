@echo off
rem 보드 없이 시뮬레이터로 브리지 시험 (서버는 실제). 로그: data\private\bridge.log
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python scripts\device_bridge.py --sim --interval 15
pause
