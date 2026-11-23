#!/usr/bin/env python3
"""
ios.py — thông tin thiết bị iPhone đang cắm: model, phiên bản iOS, kết nối.
Dùng pymobiledevice3 usbmux list (đủ thông tin cơ bản).
"""
from __future__ import annotations
import json, os, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PMD = os.path.join(ROOT, ".venv", "bin", "pymobiledevice3")

# ProductType -> tên model dễ đọc
MODEL = {
    "iPhone10,1": "iPhone 8", "iPhone10,4": "iPhone 8",
    "iPhone10,2": "iPhone 8 Plus", "iPhone10,5": "iPhone 8 Plus",
    "iPhone10,3": "iPhone X", "iPhone10,6": "iPhone X",
    "iPhone11,2": "iPhone XS", "iPhone11,4": "iPhone XS Max",
    "iPhone11,6": "iPhone XS Max", "iPhone11,8": "iPhone XR",
    "iPhone12,1": "iPhone 11", "iPhone12,3": "iPhone 11 Pro",
    "iPhone12,5": "iPhone 11 Pro Max", "iPhone12,8": "iPhone SE 2",
    "iPhone13,1": "iPhone 12 mini", "iPhone13,2": "iPhone 12",
    "iPhone13,3": "iPhone 12 Pro", "iPhone13,4": "iPhone 12 Pro Max",
    "iPhone14,5": "iPhone 13", "iPhone14,2": "iPhone 13 Pro",
}


def model_name(product_type):
    return MODEL.get(product_type, product_type or "?")


def list_connected():
    """Trả [{udid, name, model, product_type, ios, connection}]."""
    try:
        r = subprocess.run([PMD, "usbmux", "list"], capture_output=True, text=True,
                           timeout=15, env=dict(os.environ, PYTHONWARNINGS="ignore"))
        data = json.loads(r.stdout or "[]")
    except Exception:
        return []
    out = []
    for d in data:
        pt = d.get("ProductType")
        out.append({
            "udid": d.get("Identifier") or d.get("UniqueDeviceID"),
            "name": d.get("DeviceName"),
            "model": model_name(pt),
            "product_type": pt,
            "ios": d.get("ProductVersion"),
            "connection": d.get("ConnectionType"),
        })
    return out


def info(udid):
    """Thông tin 1 máy theo udid (từ danh sách usbmux)."""
    for d in list_connected():
        if d["udid"] == udid:
            return d
    return None


if __name__ == "__main__":
    for d in list_connected():
        print(d["udid"][:12], "|", d["model"], "| iOS", d["ios"], "|", d["connection"], "|", d["name"])
