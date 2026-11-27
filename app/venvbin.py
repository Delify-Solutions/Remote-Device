"""
venvbin.py — đường dẫn tới các lệnh nằm trong môi trường Python của app (.venv), chạy được trên cả macOS / Linux lẫn Windows.

macOS / Linux: .venv/bin/<tên>          Windows: .venv\\Scripts\\<tên>.exe
Ưu tiên thư mục của chính Python đang chạy app (app chạy bằng .venv thì đúng là .venv), rồi tới .venv của thư mục dự án.

    from venvbin import tool, python
    tool("pymobiledevice3")    → đường dẫn tới lệnh, hoặc chính cái tên (để hệ thống tự tìm trong PATH) nếu không thấy
    python()                   → Python của .venv (hoặc Python đang chạy)
"""
from __future__ import annotations
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # thư mục dự án (Remote-Device)
WINDOWS = os.name == "nt"


def _dirs():
    here = os.path.dirname(os.path.abspath(sys.executable or ""))
    venv = os.path.join(ROOT, ".venv")
    out = [here] if here else []
    out += [os.path.join(venv, "Scripts"), os.path.join(venv, "bin")]
    seen, res = set(), []
    for d in out:
        if d and d not in seen:
            seen.add(d)
            res.append(d)
    return res


def tool(name: str, dirs=None) -> str:
    """Lệnh `name` trong venv (Windows: thêm đuôi .exe). Không thấy → trả `name` (hệ thống tìm trong PATH)."""
    names = [name + ".exe", name] if WINDOWS else [name]
    for d in (dirs if dirs is not None else _dirs()):
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    return name


def python() -> str:
    """Python của venv dự án; không có thì Python đang chạy app."""
    venv = os.path.join(ROOT, ".venv")
    for p in (os.path.join(venv, "Scripts", "python.exe"), os.path.join(venv, "bin", "python")):
        if os.path.isfile(p):
            return p
    return sys.executable or ("python" if WINDOWS else "python3")
