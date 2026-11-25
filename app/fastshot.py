#!/usr/bin/env python3
"""
fastshot.py — chụp màn hình iPhone qua MỘT kết nối giữ mở.

Cách cũ gọi lệnh `pymobiledevice3 developer dvt screenshot` cho MỖI ảnh: mỗi lần lại khởi động Python, bắt tay
lockdown, mở kênh DVT ≈ 1,3 giây. Ở đây kết nối được mở một lần cho mỗi máy rồi dùng lại: ≈ 0,33 giây/ảnh
(đo trên iPhone 8 / iOS 16). Một lần «đưa con trỏ tới nơi rồi bấm» cần 3–6 ảnh nên nhanh lên thấy rõ.

    import fastshot
    png = fastshot.grab(udid)        # bytes PNG; ném lỗi nếu không chụp được → bên gọi tự quay về cách cũ

Thư viện pymobiledevice3 đời mới chạy bất đồng bộ (asyncio) → mọi kết nối sống trên MỘT vòng lặp ở luồng nền;
hàm grab() gọi được từ bất kỳ luồng nào (mỗi máy một worker vẫn dùng chung vòng lặp này).
"""
from __future__ import annotations
import asyncio, atexit, contextlib, threading

try:
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
    from pymobiledevice3.services.dvt.instruments.screenshot import Screenshot
    AVAILABLE = True
except Exception:                       # thư viện thiếu / đời khác → không có đường nhanh, dùng cách cũ
    AVAILABLE = False

OPEN_TIMEOUT = 12.0
SHOT_TIMEOUT = 8.0

_loop = None
_loop_lock = threading.Lock()
_sessions = {}                          # udid -> _Session (chỉ đụng tới từ luồng của vòng lặp)


class _Session:
    def __init__(self, lockdown, stack, shot):
        self.lockdown, self.stack, self.shot = lockdown, stack, shot
        self.lock = asyncio.Lock()      # một kênh chụp chỉ phục vụ một yêu cầu một lúc

    async def close(self):
        with contextlib.suppress(Exception):
            await self.stack.aclose()
        with contextlib.suppress(Exception):
            await self.lockdown.close()


def _get_loop():
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, name="fastshot", daemon=True).start()
            _loop = loop
        return _loop


async def _open(udid: str) -> _Session:
    lockdown = await create_using_usbmux(serial=udid)
    stack = contextlib.AsyncExitStack()
    try:
        dvt = await stack.enter_async_context(DvtProvider(lockdown))
        shot = await stack.enter_async_context(Screenshot(dvt))
    except BaseException:
        with contextlib.suppress(Exception):
            await stack.aclose()
        with contextlib.suppress(Exception):
            await lockdown.close()
        raise
    return _Session(lockdown, stack, shot)


async def _drop(udid: str):
    s = _sessions.pop(udid, None)
    if s is not None:
        await s.close()


async def _grab(udid: str) -> bytes:
    s = _sessions.get(udid)
    if s is None:
        s = await asyncio.wait_for(_open(udid), OPEN_TIMEOUT)
        old = _sessions.get(udid)
        if old is not None:             # luồng khác vừa mở xong trước → dùng cái đó, đóng cái thừa
            await s.close()
            s = old
        else:
            _sessions[udid] = s
    try:
        async with s.lock:
            png = await asyncio.wait_for(s.shot.get_screenshot(), SHOT_TIMEOUT)
    except BaseException:
        if _sessions.get(udid) is s:    # kết nối hỏng (rút cáp, máy khoá…) → bỏ, lần sau mở lại
            await _drop(udid)
        raise
    if not png or png[:4] != b"\x89PNG":
        if _sessions.get(udid) is s:
            await _drop(udid)
        raise RuntimeError("thiết bị trả về dữ liệu không phải ảnh PNG")
    return bytes(png)


def grab(udid: str) -> bytes:
    """Chụp màn hình máy `udid`, trả bytes PNG. Lỗi → ném ngoại lệ (kết nối cũ đã được dọn, lần sau tự mở lại)."""
    if not AVAILABLE:
        raise RuntimeError("không có đường chụp nhanh (pymobiledevice3 đời này không hỗ trợ)")
    fut = asyncio.run_coroutine_threadsafe(_grab(udid), _get_loop())
    try:
        return fut.result(OPEN_TIMEOUT + SHOT_TIMEOUT + 4)
    except BaseException:
        fut.cancel()
        raise


def close(udid: str | None = None):
    """Đóng kết nối của một máy (hoặc tất cả). Gọi khi rút máy / đổi máy / thoát chương trình."""
    loop = _loop
    if loop is None or loop.is_closed():
        return

    async def run():
        for u in ([udid] if udid else list(_sessions)):
            await _drop(u)
    with contextlib.suppress(Exception):
        asyncio.run_coroutine_threadsafe(run(), loop).result(6)


atexit.register(close)
