#!/usr/bin/env python3
"""
prober.py — "dò máy": xác định board ESP32 đang điều khiển iPhone NÀO.

iOS giấu danh tính qua Bluetooth nên không đọc được. Cách làm: RUNG CON TRỎ qua
board rồi chụp màn TẤT CẢ iPhone đang cắm USB — máy nào con trỏ nhảy (ảnh đổi nhiều
nhất) chính là máy do board này điều khiển.

Yêu cầu: iPhone ứng viên đã mount DDI (chụp màn được) + bật AssistiveTouch (con trỏ hiện).
"""
from __future__ import annotations
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2
from hands import Hands
from eyes import Eyes


def _diff_score(a, b):
    """Số điểm ảnh thay đổi rõ giữa 2 khung (để đo con trỏ nhảy chỗ)."""
    if a is None or b is None:
        return 0
    if a.shape != b.shape:
        h = min(a.shape[0], b.shape[0]); w = min(a.shape[1], b.shape[1])
        a = a[:h, :w]; b = b[:h, :w]
    d = cv2.absdiff(a, b)
    g = cv2.cvtColor(d, cv2.COLOR_BGR2GRAY)
    return int((g > 28).sum())


def identify(port, candidates, settle=0.4):
    """Rung chuột qua board tại `port`, tìm iPhone phản ứng nhiều nhất.

    candidates: list {udid, name, model, ios} (các iPhone đang cắm USB).
    Trả (best|None, ranked[list(cand,score)], note|None).
    """
    hands = Hands(port, reset=False)
    try:
        if "ble=connected" not in hands.status():
            if not hands.wait_connected(6):
                return None, [], "Board chưa nối Bluetooth với iPhone (kiểm tra ghép nối)."

        eyes = {c["udid"]: Eyes(c["udid"]) for c in candidates}

        # Khung 1: ghim con trỏ về góc trên-trái
        hands.do("home"); time.sleep(settle)
        before, ready = {}, []
        for c in candidates:
            try:
                before[c["udid"]] = eyes[c["udid"]].grab(); ready.append(c)        # chỉ so hai ảnh với nhau: ảnh NGUYÊN, không cần quay thẳng
            except Exception:
                pass   # máy chưa chụp được (chưa mount DDI) → bỏ qua
        if not ready:
            return None, [], "Không iPhone nào chụp màn được (cần mount DDI + cắm USB)."

        # Khung 2: di con trỏ ra giữa màn → trên máy do board điều khiển, con trỏ nhảy chỗ
        hands.do("home"); time.sleep(0.1)
        hands.move(360, 540)
        time.sleep(settle)

        ranked = []
        for c in ready:
            try:
                after = eyes[c["udid"]].grab()
            except Exception:
                continue
            ranked.append((c, _diff_score(before[c["udid"]], after)))
        ranked.sort(key=lambda t: t[1], reverse=True)
        if not ranked:
            return None, [], "Không chụp lại được sau khi rung chuột."

        best, score = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0
        # cần đổi đủ nhiều VÀ vượt rõ máy thứ nhì (tránh nhầm do màn tự động đổi)
        if score < 150 or (len(ranked) > 1 and score < max(second * 1.6, second + 120)):
            return None, ranked, "Chưa chắc chắn — bật AssistiveTouch (cho con trỏ hiện) rồi thử lại."
        return best, ranked, None
    finally:
        hands.close()
