@echo off
rem farm - dieu khien iPhone Farm bang dong lenh / may chu MCP cho AI (ban Windows cua ./farm).   farm --help
setlocal
if not defined PYTHONWARNINGS set PYTHONWARNINGS=ignore
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
"%~dp0.venv\Scripts\python.exe" "%~dp0app\cli.py" %*
