@echo off
rem Uno 공기청정기 브리지: 서버 일정을 보드로 보내고 상태를 올린다. 보드 없이 시험: run_device_bridge.bat --sim
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python scripts\device_bridge.py %*
pause
