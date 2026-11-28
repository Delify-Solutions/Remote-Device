#!/usr/bin/env python3
"""
Kiểm phần CHẠY ĐƯỢC CẢ TRÊN WINDOWS (máy này là Mac nên chỉ kiểm được những gì không cần Windows thật):
  • venvbin: tìm lệnh trong .venv đúng kiểu từng hệ (macOS/Linux: bin/<tên>; Windows: Scripts\\<tên>.exe), không thấy thì trả tên để
    hệ thống tự tìm trong PATH;
  • mã nguồn không còn đường dẫn kiểu Mac viết cứng (".venv/bin/…", tách thư mục bằng «/»);
  • các file .bat dùng xuống dòng kiểu Windows (CRLF) và gọi đúng .venv\\Scripts;
  • bộ đọc chữ: không có Apple Vision (Windows) thì tự dùng RapidOCR — giả lập bằng IPF_OCR=rapid trong một tiến trình riêng.

    ./.venv/bin/python app/tests/test_portable.py
"""
from __future__ import annotations
import glob, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
ROOT = os.path.dirname(APP)
sys.path.insert(0, APP)
import venvbin

PASS = FAIL = 0


def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ✓", name)
    else:
        FAIL += 1; print("  ✗", name, "→", ctx if ctx is not None else "")


def main():
    print("== 1. venvbin: lệnh trong .venv theo từng hệ ==")
    tmp = tempfile.mkdtemp(prefix="ipf-venvbin-")
    win, unix = os.path.join(tmp, "Scripts"), os.path.join(tmp, "bin")
    os.makedirs(win); os.makedirs(unix)
    open(os.path.join(win, "pymobiledevice3.exe"), "w").close()
    open(os.path.join(unix, "pymobiledevice3"), "w").close()
    real = venvbin.WINDOWS
    try:
        venvbin.WINDOWS = True
        ok(venvbin.tool("pymobiledevice3", [win, unix]) == os.path.join(win, "pymobiledevice3.exe"), "Windows: Scripts\\pymobiledevice3.exe")
        venvbin.WINDOWS = False
        ok(venvbin.tool("pymobiledevice3", [win, unix]) == os.path.join(unix, "pymobiledevice3"), "macOS / Linux: bin/pymobiledevice3 (không lấy bản .exe)")
        ok(venvbin.tool("khong-co-lenh-nay", [win, unix]) == "khong-co-lenh-nay", "không thấy → trả tên lệnh (hệ thống tự tìm trong PATH)")
    finally:
        venvbin.WINDOWS = real
    ok(os.path.isfile(venvbin.python()), "python(): có Python của .venv (hoặc Python đang chạy)", venvbin.python())

    print("== 2. Mã nguồn không viết cứng đường dẫn kiểu Mac ==")
    bad = []
    for p in glob.glob(os.path.join(APP, "*.py")):
        src = open(p, encoding="utf-8").read()
        for pat, why in ((r'["\']\.venv["\'],\s*["\']bin["\']', ".venv/bin viết cứng"), (r'__file__\.rsplit\(["\']/["\']', "tách thư mục bằng «/»"),
                         (r'["\']/dev/cu\.', "tên cổng serial kiểu Mac viết cứng")):
            for m in re.finditer(pat, src):
                line = src[:m.start()].count("\n") + 1
                if not src.splitlines()[line - 1].lstrip().startswith(("#", "python app/")) and '"""' not in src.splitlines()[line - 1]:
                    bad.append("%s:%d %s" % (os.path.basename(p), line, why))
    ok(not bad, "không còn .venv/bin, __file__.rsplit('/'), /dev/cu.* viết cứng trong app/*.py", bad)

    print("== 3. File .bat cho Windows ==")
    for name in ("run.bat", "setup.bat", "farm.bat"):
        p = os.path.join(ROOT, name)
        b = open(p, "rb").read() if os.path.exists(p) else b""
        lf = b.count(b"\n")
        ok(b and lf == b.count(b"\r\n") and b".venv\\Scripts" in b, "%s: có, xuống dòng CRLF, gọi .venv\\Scripts" % name, (len(b), lf, b.count(b"\r\n")))
    sb = open(os.path.join(ROOT, "setup.bat"), "rb").read().decode()
    req = open(os.path.join(ROOT, "requirements-windows.txt"), encoding="utf-8").read()
    pk = {re.split(r"[=<>]", ln.split("#")[0].strip())[0].lower(): ln.split("#")[0].strip() for ln in req.splitlines() if ln.split("#")[0].strip()}
    ok("requirements-windows.txt" in sb and "errorlevel" in sb and "ocr.available()" in sb and "3.12" in sb,
       "setup.bat: cài từ requirements-windows.txt, dừng khi cài lỗi, nạp thử bộ đọc chữ (tải mô hình ngay lúc cài), ưu tiên Python 3.12")
    ok(pk.get("rapidocr") == "rapidocr==3.10.0" and "onnxruntime" in pk and "opencv-python-headless" in pk and "opencv-python" not in pk
       and pk.get("pymobiledevice3", "").startswith("pymobiledevice3=="),
       "requirements-windows.txt: RapidOCR ghim đúng bản + onnxruntime (rapidocr không tự kéo theo) + MỘT bản opencv (headless) + pymobiledevice3 ghim", pk)
    ga = open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8").read() if os.path.exists(os.path.join(ROOT, ".gitattributes")) else ""
    ok("*.bat text eol=crlf" in ga, ".gitattributes giữ CRLF cho .bat khi lấy repo về Windows")

    print("== 4. Không có Apple Vision → dùng RapidOCR (giả lập Windows bằng IPF_OCR=rapid) ==")
    try:
        import rapidocr  # noqa: F401
        have = True
    except Exception:
        have = False
    if not have:
        print("  (BỎ QUA: máy này chưa cài rapidocr)")
    else:
        code = ("import sys; sys.path.insert(0, %r); import ocr, sysinfo; print(ocr.engine(), '|', sysinfo.system_info()['ocr'])" % APP)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ, IPF_OCR="rapid"), timeout=300)
        ok(r.stdout.strip().endswith("rapid | RapidOCR"), "bộ đọc = RapidOCR, trang Tổng quan hiện đúng tên bộ đọc", (r.stdout[-200:], r.stderr[-300:]))
        code = "import sys; sys.path.insert(0, %r); import ocr; print(ocr.available(), ocr.why_unavailable())" % APP
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ, IPF_OCR="vision"), timeout=120)
        ok(r.stdout.startswith("True") if sys.platform == "darwin" else r.stdout.startswith("False"), "IPF_OCR=vision: chỉ Apple Vision (có trên macOS)", r.stdout)

    print("== 5. Máy Windows MỚI CÀI (giả lập): thiếu onnxruntime / có gói pytesseract mà không có chương trình tesseract ==")
    if have:
        block = ("import sys, importlib.abc\n"
                 "class B(importlib.abc.MetaPathFinder):\n"
                 "    def find_spec(self, name, path, target=None):\n"
                 "        if name == 'onnxruntime' or name.startswith('onnxruntime.'): raise ImportError('onnxruntime is not installed.')\n"
                 "sys.meta_path.insert(0, B())\n")
        code = block + ("sys.path.insert(0, %r); import ocr; print(ocr.available(), '|', ocr.why_unavailable())" % APP)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ, IPF_OCR="rapid"), timeout=300)
        ok(r.stdout.startswith("False") and "onnxruntime" in r.stdout, "thiếu onnxruntime → «không có bộ đọc», lý do nêu rõ onnxruntime (không báo «có» rồi lần đọc nào cũng hỏng)",
           (r.stdout[-300:], r.stderr[-300:]))
        code = ("import sys; sys.path.insert(0, %r)\n"
                "import pytesseract; pytesseract.pytesseract.tesseract_cmd = '/khong/co/tesseract'\n"
                "import cv2, numpy as np, eyes\n"
                "im = np.full((160, 700, 3), (40, 20, 120), np.uint8); cv2.putText(im, 'Continue Download', (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3)\n"
                "e = eyes.Eyes('khong-dung-toi')\n"
                "print(eyes.pytesseract is None, '|', 'download' in eyes.norm_text(e.read_text(im)), '|', e.find_text('Khong co chu nay', im), '|', e.text_lines(np.zeros((80, 80, 3), np.uint8)))\n") % APP
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ, IPF_OCR="rapid"), timeout=300)
        ok(r.stdout.strip() == "True | True | None | []", "có gói pytesseract mà KHÔNG có chương trình tesseract → coi như không có tesseract: đọc chữ bằng RapidOCR vẫn chạy, "
           "không thấy chữ / màn trống thì trả «không thấy» chứ không ném lỗi", (r.stdout[-300:], r.stderr[-400:]))

    print("== 6. Nạp lại bộ đọc chữ (sau lần hỏng) không bắt các máy khác chờ ==")
    import threading, time
    import ocr
    saved = dict(ocr._state)
    real = ocr._load_vision, ocr._load_rapid

    def slow():
        time.sleep(2.0)
        raise RuntimeError("mạng treo")
    try:
        ocr._state.update(tried=True, ok=False, retry_at=time.time() - 1)     # đã nạp HỎNG một lần, nay tới hạn thử lại
        ocr._load_vision = ocr._load_rapid = slow
        t = threading.Thread(target=ocr._load)
        t.start(); time.sleep(0.3)
        a = time.time(); r = ocr._load(); waited = time.time() - a
        t.join()
        ok(r is False and waited < 0.5 and ocr._state["retry_at"] > time.time(),
           "đang có một luồng thử nạp lại (vd tải mô hình, mạng treo) → luồng khác trả ngay «chưa có bộ đọc», không chờ khoá", (r, round(waited, 2)))
        def slow_ok():
            time.sleep(1.5)
        ocr._state.update(tried=False, ok=False, engine="", error="", retry_at=0.0)
        ocr._load_vision = slow_ok
        got = {}

        def call(i):
            got[i] = ocr._load()
        ts = [threading.Thread(target=call, args=(i,)) for i in range(3)]
        for t in ts:
            t.start(); time.sleep(0.3)
        for t in ts:
            t.join()
        ok(got == {0: True, 1: True, 2: True}, "lần nạp ĐẦU (chậm — vd RapidOCR đọc thử): các luồng gọi cùng lúc CHỜ rồi cùng nhận «có bộ đọc» (không bị báo «không có» oan)", got)
    finally:
        ocr._load_vision, ocr._load_rapid = real
        ocr._state.clear(); ocr._state.update(saved)

    print("== 7. Không biến cục bộ nào che tên một module của app rồi lại gọi hàm của chính module đó ==")
    # vd trong một hàm có tham số `steps` (danh sách bước) mà lại gọi `steps.exec_step(…)` của module cùng tên: Python lấy biến cục bộ →
    # AttributeError lúc CHẠY, biên dịch không báo. Bắt ngay từ mã nguồn.
    import ast

    def shadowed_calls(sources):
        """sources = {tên module: mã nguồn}. Trả các chỗ «<module>.<tên cấp module>» nằm trong một hàm (def / async def / lambda) mà ở đó
        <module> là tham số hoặc biến cục bộ (không tính hàm tự `import <module>` ở bên trong)."""
        trees = {m: ast.parse(src) for m, src in sources.items()}
        tops = {m: {n.name for n in t.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
                   | {x.id for n in t.body if isinstance(n, ast.Assign) for x in n.targets if isinstance(x, ast.Name)} for m, t in trees.items()}
        fn_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)

        def local_names(fn):
            a = fn.args
            out = {x.arg for x in a.args + a.kwonlyargs + a.posonlyargs} | ({a.vararg.arg} if a.vararg else set()) | ({a.kwarg.arg} if a.kwarg else set())
            for x in ast.walk(fn):
                if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store):
                    out.add(x.id)
                elif isinstance(x, ast.ExceptHandler) and x.name:
                    out.add(x.name)
                elif isinstance(x, (ast.Import, ast.ImportFrom)):               # `import x as jobflow`: tên cục bộ khác module thật
                    out |= {a2.asname for a2 in x.names if a2.asname}
            return out
        found = []
        for m, t in trees.items():
            for fn in ast.walk(t):
                if not isinstance(fn, fn_types):
                    continue
                same_import = {a2.name for x in ast.walk(fn) if isinstance(x, ast.Import) for a2 in x.names if not a2.asname}
                hidden = (local_names(fn) & set(sources)) - same_import
                for x in ast.walk(fn):
                    if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name) and x.value.id in hidden and x.attr in tops[x.value.id]:
                        found.append("%s.py:%d %s(): %s.%s" % (m, x.lineno, getattr(fn, "name", "lambda"), x.value.id, x.attr))
        return sorted(set(found))
    mods = {os.path.basename(f)[:-3]: open(f, encoding="utf-8").read() for f in glob.glob(os.path.join(APP, "*.py"))}
    hits = shadowed_calls(mods)
    ok(len(mods) > 25 and {"stepexec", "jobflow", "runner", "gui"} <= set(mods) and hits == [],
       "trong %d module của app: không hàm nào có biến cục bộ / tham số trùng tên module mà lại dùng hàm cấp module của module đó" % len(mods), hits[:5])
    lib = "def exec_step(n): return n\nSTEP_GAP = 1\n"
    sample = shadowed_calls({"stepexec": lib, "user": (
        "import stepexec\n"
        "def by_param(stepexec): return stepexec.exec_step(1)\n"                    # tham số che module
        "def by_local(x):\n    stepexec = x\n    return stepexec.STEP_GAP\n"        # biến cục bộ che module
        "async def by_async(stepexec): return stepexec.exec_step(2)\n"
        "by_lambda = lambda stepexec: stepexec.exec_step(3)\n"
        "def by_alias():\n    import json as stepexec\n    return stepexec.exec_step(4)\n"
        "def fine_local_import():\n    import stepexec\n    return stepexec.exec_step(5)\n"     # tự import module thật → không phải che
        "def fine_other_attr(stepexec): return stepexec.append(1)\n"                 # gọi thứ KHÔNG phải tên cấp module → không báo
        "def fine_plain(): return stepexec.exec_step(6)\n")})
    ok(sorted(h.split(" ", 1)[1] for h in sample) == ["by_alias(): stepexec.exec_step", "by_async(): stepexec.exec_step", "by_local(): stepexec.STEP_GAP",
                                                "by_param(): stepexec.exec_step", "lambda(): stepexec.exec_step"],
       "phép kiểm bắt đúng 5 kiểu che tên trên mã mẫu (tham số, biến cục bộ, async, lambda, import … as) và không báo nhầm 3 kiểu hợp lệ", sample)

    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
