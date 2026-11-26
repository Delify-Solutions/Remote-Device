#!/usr/bin/env python3
"""
iosapp.py — TẮT HẲN rồi mở MỚI một app trên iPhone qua USB (kênh công cụ nhà phát triển, cùng kênh với chụp màn hình).

Mở app bằng ô tìm kiếm (Spotlight) chỉ đưa app ra trước: app đang chạy dở ở màn nào thì vẫn ở màn đó — kịch bản chạy lại sau một
lượt dở dang sẽ bắt đầu từ một màn hình bất kỳ. Ở đây app bị tắt hẳn rồi được khởi động lại, nên lần nào cũng bắt đầu từ màn đầu.

    import iosapp
    bundle = iosapp.relaunch(udid, "efootball")      # tên như người dùng gõ; ném lỗi kèm lý do nếu không làm được

Không cần cổng serial của board, không gõ phím nào.
"""
from __future__ import annotations
import asyncio, contextlib, unicodedata

import fastshot

try:
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
    from pymobiledevice3.services.dvt.instruments.process_control import ProcessControl
    from pymobiledevice3.services.installation_proxy import InstallationProxyService
    AVAILABLE = True
except Exception:                       # thư viện thiếu / đời khác
    AVAILABLE = False

TIMEOUT = 30.0
_bundles = {}                           # (udid, tên đã chuẩn hoá) -> bundle id đã tra được (danh sách app của máy ít khi đổi)


def norm(s) -> str:
    """Tên app để so: bỏ dấu, chữ thường, chỉ giữ chữ và số («eFootball™» → «efootball», «Cài đặt» → «caidat»)."""
    s = unicodedata.normalize("NFD", str(s or "")).replace("đ", "d").replace("Đ", "D")
    return "".join(ch for ch in s if ch.isalnum() and not unicodedata.combining(ch)).lower()


class AppNotFound(LookupError):
    """Không chọn được app theo tên (không có / nhiều app cùng khớp) — chắc chắn CHƯA đụng gì vào máy."""


def pick_bundle(apps: dict, name: str) -> str:
    """Chọn app theo tên người dùng gõ, trong `apps` = {bundle id: {CFBundleDisplayName, CFBundleName, SBAppTags, …}}.
    Thứ tự: bundle id ĐÚNG BẰNG tên gõ → tên hiển thị / tên gói đúng bằng → rồi mới tới «có chứa». Mỗi bậc phải ra ĐÚNG MỘT app;
    không thấy / nhiều app cùng khớp → AppNotFound (một LookupError) kèm lý do (không đoán: tắt nhầm app còn tệ hơn không tắt).
    App ẨN của hệ thống (SBAppTags có «hidden» — không có biểu tượng ngoài màn hình chính; máy thật có hơn trăm cái, nhiều cái trùng tên
    với app thường: ba app cùng tên «Cài đặt») chỉ được chọn khi gõ đúng bundle id của nó."""
    want = norm(name)
    if not want:
        raise AppNotFound("chưa ghi tên app")
    rows = []
    for bid, info in (apps or {}).items():
        info = info if isinstance(info, dict) else {}
        if norm(bid) == want:
            return str(bid)
        tags = info.get("SBAppTags")
        if isinstance(tags, (list, tuple)) and "hidden" in tags:
            continue
        names = [norm(info.get("CFBundleDisplayName")), norm(info.get("CFBundleName")), norm(bid)]
        rows.append((str(bid), str(info.get("CFBundleDisplayName") or info.get("CFBundleName") or bid), [n for n in names if n]))
    for test in (lambda n: n == want, lambda n: want in n):
        hits = [(bid, shown) for bid, shown, names in rows if any(test(n) for n in names)]
        if len(hits) == 1:
            return hits[0][0]
        if len(hits) > 1:
            raise AppNotFound("có %d app cùng khớp tên «%s» (%s) — ghi tên đầy đủ hơn" % (len(hits), name, ", ".join(sorted(s for _, s in hits))[:160]))
    raise AppNotFound("máy không có app nào tên «%s»" % name)


async def _relaunch(udid: str, name: str) -> str:
    lockdown = await create_using_usbmux(serial=udid)
    try:
        key = (udid, norm(name))
        bundle = _bundles.get(key)
        if not bundle:
            async with InstallationProxyService(lockdown) as proxy:
                apps = await proxy.get_apps(application_type="Any")
            bundle = pick_bundle(apps, name)
        async with DvtProvider(lockdown) as dvt:
            async with ProcessControl(dvt) as control:
                await control.launch(bundle, kill_existing=True)
        _bundles[key] = bundle
        return bundle
    finally:
        with contextlib.suppress(Exception):
            await lockdown.close()


def relaunch(udid: str, name: str) -> str:
    """Tắt hẳn app `name` (nếu đang chạy) rồi mở mới, đưa ra trước. Trả bundle id. Không làm được → ném lỗi kèm lý do."""
    if not AVAILABLE:
        raise RuntimeError("máy tính này thiếu thư viện điều khiển app qua USB (pymobiledevice3)")
    fut = asyncio.run_coroutine_threadsafe(_relaunch(udid, name), fastshot._get_loop())
    try:
        return fut.result(TIMEOUT)
    except AppNotFound:                                 # chưa đụng gì vào máy
        raise
    except Exception as e:                              # hết giờ, rút cáp, máy khoá… — app CÓ THỂ đã bị tắt mà chưa kịp mở lại
        fut.cancel()
        _bundles.pop((udid, norm(name)), None)          # lần sau tra lại danh sách app (app có thể vừa bị gỡ / cài lại)
        raise RuntimeError(str(e) or e.__class__.__name__)
