@echo off
rem Cai dat iPhone Farm tren Windows: tao .venv (Python 3.12 / 3.11 / 3.10), cai goi trong requirements-windows.txt, tai mo hinh doc chu, kiem tra.
rem Can truoc: Python 3.10-3.12 (python.org, tick "Add python.exe to PATH"), ung dung "Apple Devices" (Microsoft Store) hoac iTunes.
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if exist .venv\Scripts\python.exe goto venv_ok
echo Tao moi truong Python .venv ...
for %%V in (3.12 3.11 3.10) do (
  if not exist .venv\Scripts\python.exe py -%%V -m venv .venv >nul 2>nul
)
if not exist .venv\Scripts\python.exe python -m venv .venv
if not exist .venv\Scripts\python.exe (
  echo LOI: khong tao duoc .venv - hay cai Python 3.12 tu python.org roi chay lai.
  pause
  exit /b 1
)
:venv_ok
.venv\Scripts\python -c "import sys; sys.exit(0 if (3, 9) <= sys.version_info[:2] <= (3, 12) else 1)"
if errorlevel 1 (
  echo LOI: .venv dang dung Python ngoai khoang 3.9-3.12. Xoa thu muc .venv, cai Python 3.12 roi chay lai setup.bat.
  pause
  exit /b 1
)
.venv\Scripts\python -m pip install --upgrade pip
if errorlevel 1 goto pipfail
.venv\Scripts\python -m pip install -r requirements-windows.txt
if errorlevel 1 goto pipfail
echo Nap bo doc chu (lan dau tai mo hinh ~19 MB, can mang) ...
.venv\Scripts\python -c "import sys; sys.path.insert(0, 'app'); import ocr; ok = ocr.available(); print('Bo doc chu:', ocr.engine_name() if ok else 'LOI - ' + ocr.why_unavailable()); sys.exit(0 if ok else 1)"
if errorlevel 1 (
  echo LOI: chua dung duoc bo doc chu - xem dong loi o tren, kiem tra mang roi chay lai setup.bat.
  pause
  exit /b 1
)
.venv\Scripts\python app\doctor.py
pause
exit /b 0
:pipfail
echo LOI: cai goi Python that bai - xem thong bao o tren.
pause
exit /b 1
