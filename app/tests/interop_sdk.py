#!/usr/bin/env python3
"""
KIỂM CHÉO với client của SDK MCP CHÍNH THỨC: máy chủ MCP viết tay của app có nói đúng giao thức không?

Cần Python ≥ 3.10 và gói `mcp` (KHÔNG cài vào môi trường của app) — chạy bằng uv:

    uv run --python 3.12 --with mcp app/tests/interop_sdk.py

Thử cả hai đường truyền (stdio, HTTP) × ba cách bắt đầu của client:
  legacy       bắt tay initialize (đời cũ);
  auto         hỏi server/discover trước, không được thì bắt tay (mặc định của SDK);
  2026-07-28   ghim thẳng đời mới, không bắt tay.
Máy chủ chạy trên máy giả (app/tests/fake_mcp_server.py) nên không cần iPhone.
"""
from __future__ import annotations
import asyncio, base64, os, socket, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PY = os.path.join(ROOT, ".venv", "bin", "python")
FAKE = os.path.join(HERE, "fake_mcp_server.py")
TOKEN = "khoa-thu-interop"

import httpx2
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

PASS = FAIL = 0
def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ✓ " + name)
    else:
        FAIL += 1; print("  ✗ " + name + ("" if ctx is None else "   → %s" % (ctx,)))


async def exercise(client, label):
    ver = client.protocol_version
    info = client.server_info
    if label.endswith("/2026-07-28"):           # ghim thẳng phiên bản = client KHÔNG hỏi server/discover nên không biết tên máy chủ
        ok(info is None or info.name == "iphone-farm", "%s: ghim thẳng đời mới, không cần bắt tay (phiên bản %s)" % (label, ver), info)
    else:
        ok(info is not None and info.name == "iphone-farm", "%s: nhận ra máy chủ «iphone-farm» (phiên bản giao thức %s)" % (label, ver), info)
    tools = (await client.list_tools()).tools
    names = [t.name for t in tools]
    ok({"list_devices", "read_screen", "tap", "type_text"} <= set(names) and all(t.input_schema.get("type") == "object" for t in tools),
       "%s: liệt kê %d công cụ, schema hợp lệ" % (label, len(names)))
    r = await client.call_tool("list_devices", {})
    ok(r.is_error is not True and "iPhoneFarm-01" in r.content[0].text and r.structured_content["devices"][0]["name"] == "iPhoneFarm-01",
       "%s: gọi list_devices → chữ + dữ liệu có cấu trúc" % label, r.content[0].text[:60])
    r = await client.call_tool("read_screen", {"device": "iPhoneFarm-01"})
    imgs = [c for c in r.content if c.type == "image"]
    ok(len(imgs) == 1 and imgs[0].mime_type == "image/jpeg" and base64.b64decode(imgs[0].data)[:2] == b"\xff\xd8", "%s: read_screen trả ẢNH màn hình" % label)
    r = await client.call_tool("tap", {"device": "may-khong-co", "x": 1, "y": 1})
    ok(r.is_error is True and "Không có máy" in r.content[0].text, "%s: công cụ thất bại → kết quả isError kèm lời giải thích" % label)
    r = await client.call_tool("type_text", {"device": "iPhoneFarm-01", "text": "abc"})
    ok(r.is_error is not True and "3 ký tự" in r.content[0].text, "%s: gọi công cụ có tác động (gõ chữ)" % label)
    try:
        await client.call_tool("cong_cu_khong_co", {})
        ok(False, "%s: công cụ không tồn tại phải là lỗi giao thức" % label)
    except MCPError as e:
        ok(e.error.code == -32602, "%s: công cụ không tồn tại → lỗi giao thức −32602" % label, e.error)
    return ver


def free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


async def main() -> int:
    want = {"legacy": lambda v: v.startswith("2025") or v.startswith("2024"), "auto": lambda v: v == "2026-07-28", "2026-07-28": lambda v: v == "2026-07-28"}
    print("\n== stdio (client tự chạy máy chủ như một tiến trình con) ==")
    for mode in ("legacy", "auto", "2026-07-28"):
        async with Client(StdioServerParameters(command=PY, args=[FAKE, "stdio"], env={"PYTHONWARNINGS": "ignore"}), mode=mode) as client:
            ver = await exercise(client, "stdio/" + mode)
            ok(want[mode](ver), "stdio/%s: thoả thuận đúng đời giao thức (%s)" % (mode, ver))

    print("\n== HTTP (máy chủ trong app, có khoá Bearer) ==")
    port = free_port()
    proc = subprocess.Popen([PY, FAKE, "http", str(port), TOKEN], stderr=subprocess.PIPE, env=dict(os.environ, PYTHONWARNINGS="ignore"))
    try:
        proc.stderr.readline()                      # chờ máy chủ báo đã mở cổng
        url = "http://127.0.0.1:%d/mcp" % port
        for mode in ("legacy", "auto", "2026-07-28"):
            async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + TOKEN}, timeout=30) as http:
                async with Client(streamable_http_client(url, http_client=http), mode=mode) as client:
                    ver = await exercise(client, "http/" + mode)
                    ok(want[mode](ver), "http/%s: thoả thuận đúng đời giao thức (%s)" % (mode, ver))
        try:
            async with httpx2.AsyncClient(headers={"Authorization": "Bearer sai-khoa"}, timeout=10) as http:
                async with Client(streamable_http_client(url, http_client=http), mode="legacy") as client:
                    await client.list_tools()
            ok(False, "khoá sai phải bị từ chối")
        except BaseException as e:                  # SDK gói lỗi 401 theo nhiều kiểu tuỳ phiên bản
            ok(True, "http: khoá sai → client không vào được (%s)" % type(e).__name__)
    finally:
        proc.terminate()
    print("\n" + ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if FAIL == 0 else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
