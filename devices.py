"""Liệt kê và kiểm tra thông số tất cả iPhone đang cắm USB.

Chạy:  .venv/bin/python devices.py
"""
import asyncio
import warnings

warnings.filterwarnings("ignore")

from pymobiledevice3.lockdown import create_using_usbmux  # noqa: E402
from pymobiledevice3.usbmux import list_devices  # noqa: E402

# Giá trị mong muốn — chỉnh theo nhu cầu. None = không kiểm tra.
EXPECTED = {
    "ios": "16.7.9",
    "region": None,       # ví dụ "VN/A"
    "timezone": None,     # ví dụ "Asia/Ho_Chi_Minh"
    "language": None,     # ví dụ "vi"
    "min_battery": 30,
}


async def read_device(serial: str) -> dict:
    ld = await create_using_usbmux(serial=serial, autopair=False)
    info = ld.all_values
    battery = await ld.get_value(domain="com.apple.mobile.battery") or {}
    intl = await ld.get_value(domain="com.apple.international") or {}
    return {
        "udid": serial,
        "name": info.get("DeviceName"),
        "model": info.get("ProductType"),
        "ios": info.get("ProductVersion"),
        "region": info.get("RegionInfo"),
        "timezone": info.get("TimeZone"),
        "language": intl.get("Language"),
        "locale": intl.get("Locale"),
        "battery": battery.get("BatteryCurrentCapacity"),
        "charging": battery.get("BatteryIsCharging"),
        "sim": info.get("SIMStatus"),
    }


def check(d: dict) -> list[str]:
    problems = []
    for key in ("ios", "region", "timezone", "language"):
        want = EXPECTED[key]
        if want is not None and d.get(key) != want:
            problems.append(f"{key}={d.get(key)} (cần {want})")
    if d.get("battery") is not None and d["battery"] < EXPECTED["min_battery"]:
        problems.append(f"pin {d['battery']}% < {EXPECTED['min_battery']}%")
    return problems


async def main() -> None:
    devices = [d for d in await list_devices() if d.connection_type == "USB"]
    if not devices:
        print("Không có iPhone nào đang cắm.")
        return
    for dev in devices:
        try:
            d = await read_device(dev.serial)
        except Exception as e:  # máy khoá / chưa tin cậy / rớt kết nối
            print(f"[LỖI] {dev.serial}: {e!r}")
            continue
        problems = check(d)
        status = "OK " if not problems else "SAI"
        print(f"[{status}] {d['name']} ({d['udid'][:8]}…) iOS {d['ios']} | "
              f"vùng {d['region']} | {d['timezone']} | ngôn ngữ {d['language']} | "
              f"pin {d['battery']}%{' ⚡' if d['charging'] else ''}")
        for p in problems:
            print(f"       - {p}")


if __name__ == "__main__":
    asyncio.run(main())
