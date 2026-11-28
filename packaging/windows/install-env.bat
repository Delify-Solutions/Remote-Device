@echo off
rem Chay boi bo cai sau khi chep tep: tao .venv tu Python kem theo (thu muc runtime), cai thu vien tu thu muc wheels (KHONG can mang),
rem dat mo hinh doc chu vao cho cua rapidocr, kiem tra. Ket qua ghi vao install.log; thanh cong thi tao tep .venv\ipf-ok.
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PIP_DISABLE_PIP_VERSION_CHECK=1
set "LOG=%~dp0install.log"
echo == iPhone Farm - cai moi truong (%date% %time%) > "%LOG%"
if exist .venv rmdir /s /q .venv >> "%LOG%" 2>&1
if exist .venv goto fail
runtime\python.exe -m venv .venv >> "%LOG%" 2>&1
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install --no-index --find-links wheels -r requirements-windows.txt -c constraints.txt >> "%LOG%" 2>&1
if errorlevel 1 goto fail
if not exist ".venv\Lib\site-packages\rapidocr\models" mkdir ".venv\Lib\site-packages\rapidocr\models" >> "%LOG%" 2>&1
copy /y models\*.onnx ".venv\Lib\site-packages\rapidocr\models\" >> "%LOG%" 2>&1
if errorlevel 1 goto fail
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'app'); import ocr; ok = ocr.available(); print('Bo doc chu:', ocr.engine_name() if ok else 'LOI - ' + ocr.why_unavailable()); sys.exit(0 if ok else 1)" >> "%LOG%" 2>&1
if errorlevel 1 goto fail
.venv\Scripts\python.exe -c "import webview, serial, cv2, numpy, pymobiledevice3, cryptography, esptool" >> "%LOG%" 2>&1
if errorlevel 1 goto fail
echo ok> .venv\ipf-ok
rmdir /s /q wheels >> "%LOG%" 2>&1
echo == xong >> "%LOG%"
exit /b 0
:fail
echo == LOI - cai moi truong that bai >> "%LOG%"
exit /b 1
