#!/usr/bin/env python3
"""
iosdev.py — Kiểm tra & chuẩn bị iPhone cho việc CHỤP MÀN HÌNH (dịch vụ developer).

Phần điều khiển (chuột/phím qua ESP32 BLE) KHÔNG cần gì ở đây.
Phần chụp màn hình (pymobiledevice3 dvt screenshot) cần 3 thứ, mỗi máy làm 1 lần:
  1. Trust  — đã tin cậy máy tính (ghép nối lockdown)
  2. Dev Mode — Developer Mode đang bật (iOS 16+)
  3. DDI    — DeveloperDiskImage đã mount

Hàm check() trả trạng thái 3 mục; các hàm còn lại là hành động "bấm 1 cái để sửa".
"""
from __future__ import annotations
import os, re, json, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import venvbin
PMD = venvbin.tool("pymobiledevice3")          # trong .venv (Windows: .exe), không có thì tìm trong PATH

_NOISE = re.compile(r"(urllib3|OpenSSL|LibreSSL|NotOpenSSLWarning|warnings\.warn)", re.I)


def _run(args, timeout=30):
    """Chạy pymobiledevice3, trả (rc, stdout, stderr) đã lọc dòng cảnh báo rác."""
    try:
        p = subprocess.run([PMD, *args], capture_output=True, text=True, timeout=timeout)
        out = "\n".join(l for l in p.stdout.splitlines() if not _NOISE.search(l))
        err = "\n".join(l for l in p.stderr.splitlines() if not _NOISE.search(l))
        return p.returncode, out.strip(), err.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "hết thời gian chờ"
    except Exception as e:
        return 1, "", str(e)


def _first_json(text):
    """Lấy khối JSON đầu tiên trong text (bỏ qua dòng rác đứng trước)."""
    for i, ch in enumerate(text):
        if ch in "[{":
            try:
                return json.loads(text[i:])
            except Exception:
                break
    return None


# ------------------------- KIỂM TRA -------------------------
def is_trusted(udid):
    rc, out, err = _run(["lockdown", "info", "--udid", udid], timeout=15)
    return rc == 0 and out.lstrip().startswith("{")


def dev_mode_on(udid):
    rc, out, err = _run(["amfi", "developer-mode-status", "--udid", udid], timeout=15)
    return "true" in (out + err).lower()


def ddi_mounted(udid):
    rc, out, err = _run(["mounter", "list", "--udid", udid], timeout=15)
    data = _first_json(out)
    if not isinstance(data, list):
        return False
    return any(str(d.get("DiskImageType", "")).lower() in ("developer", "personalized")
               for d in data if isinstance(d, dict))


def check(udid):
    """Trả {trusted, dev_mode, ddi, ready} — ready = chụp màn hình được."""
    trusted = is_trusted(udid)
    dev = dev_mode_on(udid) if trusted else False
    ddi = ddi_mounted(udid) if trusted else False
    return {
        "udid": udid,
        "trusted": trusted,
        "dev_mode": dev,
        "ddi": ddi,
        "ready": bool(trusted and dev and ddi),
    }


# ------------------------- HÀNH ĐỘNG -------------------------
def pair(udid):
    """Ghép nối (iPhone sẽ hiện hỏi 'Tin cậy máy tính này?' → bấm Tin cậy)."""
    rc, out, err = _run(["lockdown", "pair", "--udid", udid], timeout=40)
    return {"ok": rc == 0, "log": (out + "\n" + err).strip() or "Đã gửi yêu cầu ghép nối."}


def enable_dev_mode(udid):
    """Bật Developer Mode — MÁY SẼ KHỞI ĐỘNG LẠI, sau đó xác nhận trên màn hình."""
    rc, out, err = _run(["amfi", "enable-developer-mode", "--udid", udid], timeout=40)
    return {"ok": rc == 0, "log": (out + "\n" + err).strip() or "Đã bật. Máy đang khởi động lại…"}


def reveal_dev_mode(udid):
    """Hiện mục Developer Mode trong Cài đặt (nếu chưa thấy)."""
    rc, out, err = _run(["amfi", "reveal-developer-mode", "--udid", udid], timeout=20)
    return {"ok": rc == 0, "log": (out + "\n" + err).strip() or "Đã hiện mục trong Cài đặt → Quyền riêng tư & Bảo mật."}


def mount_ddi(udid):
    """Tải (nếu cần) & mount DeveloperDiskImage. Lần đầu cần mạng."""
    rc, out, err = _run(["mounter", "auto-mount", "--udid", udid], timeout=180)
    log = (out + "\n" + err).strip()
    ok = rc == 0 or "already mounted" in log.lower()
    return {"ok": ok, "log": log or "Đã mount DDI."}
