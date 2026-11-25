#!/usr/bin/env python3
"""
Test MCP + CLI + lõi điều khiển (không cần iPhone):   ./.venv/bin/python app/tests/test_mcp.py

  1. giao thức MCP — đời cũ (bắt tay initialize) và đời mới 2026-07-28 (không bắt tay, mỗi yêu cầu tự mang phiên bản);
  2. đường truyền stdio — mỗi dòng một thông điệp, stdout không lẫn rác;
  3. đường truyền HTTP trong app — khoá Bearer, chặn trang web lạ, mã trạng thái;
  4. lõi điều khiển — chọn máy, từ chối khi máy đang chạy đơn, không lặp lại chữ đã gõ, chạy chuỗi bước;
  5. CLI — đọc tham số, lưu ảnh, mã thoát;
  6. app đang mở thì lệnh đi qua app, chưa mở thì tự làm tại chỗ.
"""
from __future__ import annotations
import base64, io, json, os, shutil, sys, tempfile, threading, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import cv2
import numpy as np

import apimode, cli, control, mcpserver
from mcpserver import McpServer, Remote, Result, Tool, ToolError, serve_http, serve_stdio
import test_api_mode as T

REAL_SLEEP = time.sleep
time.sleep = lambda s: None              # bỏ các quãng nghỉ dành cho máy thật (apimode/control dùng chung mô-đun time)

PASS = FAIL = 0
def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ " + name)
    else:
        FAIL += 1
        print("  ✗ " + name + ("" if ctx is None else "   → %s" % (ctx,)))


# ====================== máy giả cho lõi điều khiển ======================
class FakeHost:
    def __init__(self):
        self.games = {"iPhoneFarm-01": T.FakeGame(T.accounts()), "iPhoneFarm-02": T.FakeGame(T.accounts())}
        self.navs = {n: T.FakeNav(g) for n, g in self.games.items()}
        self.labels = {"iPhoneFarm-01": "Máy số một", "iPhoneFarm-02": "Máy số hai"}
        self.running = set()
        self.held = []
        self.opened, self.closed = [], []
        self.started, self.stopped = [], []
        self.group_list = [{"id": "g1", "name": "Nhóm eFootball", "mode": "api", "devices": ["iPhoneFarm-01"], "pool": "game-test", "steps": 0}]
        self.full_lists = 0

    def names(self): return list(self.games)
    def devices(self):
        self.full_lists += 1
        return [{"name": n, "label": self.labels[n], "board": True, "bluetooth": True, "iphone": True, "ios": "16.7", "model": "iPhone 8",
                 "group": "Nhóm eFootball" if n == "iPhoneFarm-01" else None, "running": n in self.running, "status": "Chờ đơn" if n in self.running else ""}
                for n in self.games]
    def acquire(self, name):
        if name in self.running:
            return "Máy «%s» đang chạy — dừng máy đó trước." % name
        self.held.append(name); return None
    def release(self, name): self.held.remove(name)
    def active(self): return list(self.held)
    def session(self, name): self.opened.append(name); return self.navs[name]
    def done(self, name): self.closed.append(name)
    def eyes(self, name): return self.navs[name].e
    def status(self): return {"machines": {n: {"name": n, "running": True, "status": "Chờ đơn", "counts": {"done": 2, "failed": 0, "review": 1}} for n in self.running},
                              "log": [{"t": "10:00:00", "name": "iPhoneFarm-01", "text": "Đã mua 1050 Coins (1/1)"}]}
    def groups(self): return list(self.group_list)
    def start(self, gid, name=None): self.started.append((gid, name)); return {"ok": True, "started": [name] if name else ["iPhoneFarm-01"]}
    def stop(self, name=None, gid=None, force=False): self.stopped.append((name, gid, force)); return {"ok": True}
    def rescan(self): return {"ok": True}


def fake_lines(img_text):
    """Thay OCR thật: mỗi từ của màn hình giả thành một «dòng chữ» có toạ độ."""
    return [{"text": w, "x": 40 + 70 * i, "y": 100, "w": 60, "h": 24} for i, w in enumerate(img_text.split())]


def rig():
    host = FakeHost()
    c = control.Control(host)
    server = McpServer(control.build_tools(c), instructions=control.INSTRUCTIONS)
    return host, c, server


def call(server, name, args=None, mid=1, modern=False):
    params = {"name": name, "arguments": args or {}}
    if modern:
        params["_meta"] = {mcpserver.META_VERSION: "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}
    return server.handle({"jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": params})


def body(resp):
    return "\n".join(c.get("text", "") for c in resp["result"]["content"] if c["type"] == "text")


def main():
    real_ocr = control.ocr_lines
    control.ocr_lines = lambda img, **kw: fake_lines(CURRENT[0].text())
    tmp = tempfile.mkdtemp(prefix="mcp-test-")
    try:
        run_all(tmp, real_ocr)
    finally:
        control.ocr_lines = real_ocr
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if FAIL == 0 else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 0 if FAIL == 0 else 1


CURRENT = [None]        # màn hình giả mà «OCR» đang đọc


def run_all(tmp, real_ocr):
    host, c, server = rig()
    CURRENT[0] = host.games["iPhoneFarm-01"]
    req = lambda method, params=None, mid=1: server.handle({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
    META = {"_meta": {mcpserver.META_VERSION: "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}}

    print("\n== 1. Giao thức — đời cũ (client bắt tay initialize) ==")
    r = req("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    res = r["result"]
    ok(res["protocolVersion"] == "2025-06-18" and res["capabilities"] == {"tools": {"listChanged": False}} and res["serverInfo"]["name"] == "iphone-farm"
       and isinstance(res["instructions"], str) and "resultType" not in res, "initialize: trả đúng phiên bản client xin + khả năng «tools» + tên máy chủ", res)
    ok(all(req("initialize", {"protocolVersion": v})["result"]["protocolVersion"] == v for v in ("2024-11-05", "2025-03-26", "2025-11-25")),
       "nhận mọi phiên bản đời cũ: 2024-11-05, 2025-03-26, 2025-11-25")
    ok(req("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == "2025-11-25",
       "client xin phiên bản lạ → máy chủ đề nghị phiên bản đời cũ mới nhất của mình (không báo lỗi)")
    ok(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
       and server.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 9}}) is None, "thông báo (không có id) → không trả lời gì")
    ok(req("ping") == {"jsonrpc": "2.0", "id": 1, "result": {}}, "ping → kết quả rỗng")
    tl = req("tools/list")["result"]
    names = [t["name"] for t in tl["tools"]]
    ok("resultType" not in tl and len(names) == len(set(names)) and {"list_devices", "read_screen", "tap", "type_text", "swipe", "long_press", "run_steps", "farm_status"} <= set(names),
       "tools/list: đủ công cụ đọc màn hình + điều khiển, tên không trùng", names)
    shape = all(t["inputSchema"].get("type") == "object" and isinstance(t["inputSchema"].get("properties"), dict) and t["description"] and t["title"]
                and set(t["annotations"]) >= {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}
                and all(k in t["inputSchema"]["properties"] for k in t["inputSchema"].get("required", [])) for t in tl["tools"])
    ok(shape, "mỗi công cụ: mô tả + inputSchema kiểu object + gợi ý (chỉ-đọc / có-tác-động)")
    ro = {t["name"]: t["annotations"]["readOnlyHint"] for t in tl["tools"]}
    ok(ro["read_screen"] and ro["list_devices"] and ro["find_text"] and not ro["tap"] and not ro["type_text"] and not ro["start_run"],
       "công cụ chỉ ĐỌC được đánh dấu chỉ-đọc; bấm / gõ / chạy nhóm thì không", ro)
    ok(all(1 <= len(n) <= 64 and n.replace("_", "").isalnum() for n in names), "tên công cụ chỉ gồm chữ, số, gạch dưới")
    e = req("tools/call", {"name": "khong_co", "arguments": {}})
    ok(e.get("error", {}).get("code") == -32602 and "Unknown tool" in e["error"]["message"], "gọi công cụ không tồn tại → lỗi giao thức −32602", e)
    ok(req("khong/co")["error"]["code"] == -32601, "phương thức lạ → −32601")
    ok(server.handle({"id": 1, "method": "ping"})["error"]["code"] == -32600 and server.handle("x")["error"]["code"] == -32600, "thông điệp không phải JSON-RPC 2.0 → −32600")
    ok(server.handle({"jsonrpc": "2.0", "id": 5, "result": {}}) is None, "client gửi một CÂU TRẢ LỜI (không phải yêu cầu) → bỏ qua")
    bad = call(server, "tap", {"device": "iPhoneFarm-01", "x": "ba trăm", "y": 5})
    ok(bad["result"]["isError"] is True and "integer" in body(bad), "tham số sai kiểu → KẾT QUẢ có isError (để AI tự sửa), không phải lỗi giao thức", bad)
    ok(call(server, "tap", {"device": "iPhoneFarm-01", "la": 1})["result"]["isError"] is True
       and call(server, "find_text", {})["result"]["isError"] is True and "missing required" in body(call(server, "find_text", {})), "tham số lạ / thiếu tham số bắt buộc → isError kèm lời chỉ dẫn")
    batch = server.handle([{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"jsonrpc": "2.0", "id": 2, "method": "ping"}])
    ok(isinstance(batch, list) and [b["id"] for b in batch] == [1, 2], "gộp lô (client 2025-03-26) → trả lời từng yêu cầu, bỏ qua thông báo")

    print("\n== 1b. Giao thức — đời mới 2026-07-28 (không bắt tay) ==")
    d = req("server/discover", META)["result"]
    ok(d["resultType"] == "complete" and "2026-07-28" in d["supportedVersions"] and "2025-11-25" in d["supportedVersions"] and d["capabilities"] == {"tools": {}}
       and isinstance(d["ttlMs"], int) and d["cacheScope"] in ("public", "private") and d["_meta"][mcpserver.META_SERVER_INFO]["name"] == "iphone-farm",
       "server/discover: phiên bản hỗ trợ + khả năng + ttlMs/cacheScope + tên máy chủ nằm trong _meta", d)
    tl2 = req("tools/list", META)["result"]
    ok(tl2["resultType"] == "complete" and "ttlMs" in tl2 and tl2["cacheScope"] in ("public", "private") and len(tl2["tools"]) == len(names), "tools/list đời mới có resultType + ttlMs + cacheScope")
    m = call(server, "list_devices", modern=True)["result"]
    ok(m["resultType"] == "complete" and m["isError"] is False and "iPhoneFarm-01" in m["content"][0]["text"], "tools/call đời mới có resultType: complete", m)
    ok(call(server, "tap", {"x": "a"}, modern=True)["result"].get("resultType") == "complete", "kết quả lỗi của công cụ cũng mang resultType")
    u = req("tools/list", {"_meta": {mcpserver.META_VERSION: "2030-01-01"}})
    ok(u["error"]["code"] == -32022 and u["error"]["data"]["requested"] == "2030-01-01" and "2026-07-28" in u["error"]["data"]["supported"],
       "phiên bản đời mới không hỗ trợ → −32022 kèm danh sách phiên bản hỗ trợ", u)
    ok(req("ping", META)["error"]["code"] == -32601, "đời mới đã bỏ ping → −32601")
    ok("resultType" not in call(server, "list_devices")["result"], "yêu cầu kiểu đời cũ KHÔNG bị gắn resultType")

    print("\n== 2. Đường truyền stdio ==")
    lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}),
             json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}), "", "{day khong phai json",
             json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
             json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_devices", "arguments": {}}}),
             json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "read_screen", "arguments": {"device": "iPhoneFarm-01"}}})]
    out = io.BytesIO()
    serve_stdio(server, stdin=io.BytesIO(("\n".join(lines) + "\n").encode("utf-8")), stdout=out)
    raw = out.getvalue().decode("utf-8")
    got = [json.loads(l) for l in raw.splitlines()]
    by = {g.get("id"): g for g in got}
    ok(raw.endswith("\n") and all(l.strip() and "\n" not in l for l in raw.splitlines()) and len(got) == 5, "mỗi câu trả lời đúng MỘT dòng JSON; thông báo và dòng trống không sinh câu trả lời", len(got))
    ok(by[None]["error"]["code"] == -32700, "dòng không phải JSON → lỗi −32700, máy chủ vẫn chạy tiếp")
    ok(by[1]["result"]["protocolVersion"] == "2025-06-18" and len(by[2]["result"]["tools"]) == len(names) and "iPhoneFarm-01" in body(by[3]), "bắt tay → liệt kê công cụ → gọi công cụ: đều có câu trả lời")
    img = [c for c in by[4]["result"]["content"] if c["type"] == "image"]
    ok(len(img) == 1 and img[0]["mimeType"] == "image/jpeg" and base64.b64decode(img[0]["data"])[:2] == b"\xff\xd8", "read_screen trả ẢNH (JPEG, base64) cho AI nhìn")

    print("\n== 3. Đường truyền HTTP (app mở sẵn trên 127.0.0.1) ==")
    httpd, port = serve_http(server, "khoa-bi-mat-123", 47900, extra_health=lambda: {"mode": "test"})
    base = "http://127.0.0.1:%d" % port
    def http(method, path, payload=None, headers=None, token="khoa-bi-mat-123"):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if token:
            h["Authorization"] = "Bearer " + token
        h.update(headers or {})
        data = None if payload is None else (payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        try:
            with urllib.request.urlopen(urllib.request.Request(base + path, data=data, method=method, headers=h), timeout=10) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None), dict(r.headers)
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, (json.loads(raw) if raw else None), dict(e.headers)
    try:
        st, b, _ = http("GET", "/health", token=None)
        ok(st == 200 and b["ok"] is True and b["app"] == "iphone-farm" and b["mode"] == "test", "/health trả lời (để CLI biết app đang mở)", b)
        st, b, hd = http("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=None)
        ok(st == 401 and "Bearer" in (hd.get("WWW-Authenticate") or ""), "không có khoá → 401", st)
        ok(http("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, token="sai")[0] == 401, "khoá sai → 401")
        st, b, _ = http("POST", "/mcp", {"jsonrpc": "2.0", "id": 7, "method": "ping"})
        ok(st == 200 and b == {"jsonrpc": "2.0", "id": 7, "result": {}}, "đúng khoá → trả lời JSON", (st, b))
        ok(http("POST", "/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"})[:2] == (202, None), "thông báo → 202, không có thân")
        ok(http("GET", "/mcp")[0] == 405 and http("DELETE", "/mcp")[0] == 405, "GET / DELETE trên /mcp → 405")
        ok(http("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"Origin": "https://trang-la.example"})[0] == 403, "trang web lạ (Origin khác máy này) → 403")
        ok(http("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"Origin": "http://localhost:3000"})[0] == 200, "Origin là chính máy này → được")
        ok(http("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"Host": "ke-gian.example"})[0] == 403, "tên miền trỏ lén về 127.0.0.1 (DNS rebinding) → 403")
        ok(http("POST", "/mcp", b"{khong phai json")[0] == 400, "thân không phải JSON → 400")
        ok(http("POST", "/khac", {"jsonrpc": "2.0", "id": 1, "method": "ping"})[0] == 404, "đường dẫn khác /mcp → 404")
        ok(http("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"MCP-Protocol-Version": "1900-01-01"})[0] == 400, "tiêu đề MCP-Protocol-Version lạ → 400")
        st, b, _ = http("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": META},
                        {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/list"})
        ok(st == 200 and b["result"]["resultType"] == "complete", "client đời mới (kèm tiêu đề MCP-Protocol-Version / Mcp-Method) → 200", st)
        st, b, _ = http("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": META}, {"Mcp-Method": "tools/call"})
        ok(st == 400 and b["error"]["code"] == -32020, "tiêu đề không khớp thân yêu cầu → 400 + −32020", (st, b))
        st, b, _ = http("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "khong/co", "params": META})
        ok(st == 404 and b["error"]["code"] == -32601, "đời mới: phương thức lạ → 404 + −32601", st)
        st, b, _ = http("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": {mcpserver.META_VERSION: "2031-01-01"}}})
        ok(st == 400 and b["error"]["code"] == -32022, "đời mới: phiên bản không hỗ trợ → 400 + −32022", st)
        ok(http("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "khong/co"})[0] == 200, "đời cũ: lỗi JSON-RPC vẫn trả 200 kèm thân lỗi")
        rm = Remote(port, "khoa-bi-mat-123")
        res = rm.call("list_devices")
        ok(rm.health()["ok"] and res["isError"] is False and "iPhoneFarm-02" in res["content"][0]["text"], "khách Remote (CLI / máy chủ stdio dùng) gọi được công cụ của app")
        ok(Remote(port, "sai-khoa").health() is not None and _raises(lambda: Remote(port, "sai-khoa").call("list_devices")), "Remote với khoá sai → báo lỗi rõ, không treo")
        ok(Remote(1, "x").health() is None, "app không chạy → health() trả None ngay")
        ok(http("GET", "/health", headers={"Origin": "https://trang-la.example"}, token=None)[0] == 403
           and http("GET", "/health", headers={"Host": "ke-gian.example"}, token=None)[0] == 403, "/health cũng chặn trang web lạ / tên miền trỏ lén")
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.putrequest("POST", "/mcp"); conn.putheader("Authorization", "Bearer khoa-bi-mat-123"); conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(mcpserver.MAX_BODY + 1)); conn.endheaders()
        big = conn.getresponse()
        ok(big.status == 413, "thân yêu cầu khai lớn hơn giới hạn → 413 ngay, không đọc vào bộ nhớ", big.status)
        conn.close()
    finally:
        httpd.shutdown(); httpd.server_close()

    print("\n== 4. Lõi điều khiển ==")
    host, c, server = rig()
    CURRENT[0] = host.games["iPhoneFarm-01"]
    t = body(call(server, "list_devices"))
    ok("iPhoneFarm-01 (Máy số một)" in t and "Bluetooth đã nối" in t and "iPhone 8 iOS 16.7" in t and "nhóm «Nhóm eFootball»" in t, "danh sách máy: nhãn, Bluetooth, loại máy, nhóm", t)
    sc = call(server, "list_devices")["result"]["structuredContent"]
    ok(isinstance(sc["devices"], list) and "udid" not in json.dumps(sc).lower(), "dữ liệu có cấu trúc kèm theo; KHÔNG lộ UDID của máy")
    r = call(server, "read_screen", {"device": "iPhoneFarm-01"})["result"]
    ok(r["structuredContent"]["device"] == "iPhoneFarm-01" and r["structuredContent"]["texts"][0]["text"] == "Màn" and "(40,100) Màn" in r["content"][0]["text"]
       and r["content"][1]["type"] == "image", "read_screen: chữ kèm toạ độ + ảnh", r["content"][0]["text"][:120])
    r = call(server, "read_screen", {"device": "iPhoneFarm-01", "include_image": False, "include_text": False})["result"]
    ok(len(r["content"]) == 1 and "texts" not in r["structuredContent"], "tắt được ảnh / tắt được đọc chữ (cho nhanh)")
    r = call(server, "read_screen", {"device": "iPhoneFarm-01", "scale": 0.5})["result"]
    ok(r["structuredContent"]["image_scale"] == 0.5 and "thu nhỏ" in r["content"][0]["text"], "ảnh thu nhỏ → nói rõ cách quy đổi toạ độ")
    ok(host.opened == [], "ĐỌC màn hình không mở cổng serial của board")
    f = call(server, "find_text", {"text": "safari|khong co", "device": "Máy số một"})["result"]
    ok(f["structuredContent"]["matches"][0]["text"] == "Safari" and f["structuredContent"]["device"] == "iPhoneFarm-01", "find_text: không phân biệt hoa thường, nhận nhiều cách viết; gọi máy theo NHÃN cũng được", f["structuredContent"])
    ok(call(server, "find_text", {"text": "Chữ này không có", "device": "iPhoneFarm-01"})["result"]["structuredContent"]["matches"] == [], "không thấy chữ → danh sách rỗng (không phải lỗi)")

    g = host.games["iPhoneFarm-01"]
    g.screen = "login"
    r = call(server, "tap", {"device": "iPhoneFarm-01", "text": "Đăng nhập"})
    ok(r["result"]["isError"] is False and g.clicks == 1 and g.focus == "user" and host.opened == ["iPhoneFarm-01"] and host.closed == ["iPhoneFarm-01"],
       "tap vào chữ: bấm đúng 1 lần, mở phiên rồi báo «xong» cho nơi giữ cổng", (body(r), g.clicks))
    r = call(server, "type_text", {"device": "iPhoneFarm-01", "text": "a@test.vn"})
    ok(r["result"]["isError"] is False and g.typed["user"] == "a@test.vn" and "a@test.vn" not in body(r) and "9 ký tự" in body(r), "type_text: gõ đúng; câu trả lời KHÔNG lặp lại nội dung đã gõ (có thể là mật khẩu)", body(r))
    call(server, "press_key", {"device": "iPhoneFarm-01", "key": "tab"})
    call(server, "type_text", {"device": "iPhoneFarm-01", "text": "PassA#1", "enter": True})
    ok(g.screen == "main" and g.user == "a@test.vn", "phím Tab + gõ + Enter → đăng nhập được trên máy giả", g.screen)
    ok(call(server, "type_text", {"device": "iPhoneFarm-01", "text": "tiếng Việt"})["result"]["isError"] is True and "ASCII" in body(call(server, "type_text", {"device": "iPhoneFarm-01", "text": "ế"})),
       "gõ chữ có dấu → từ chối kèm lý do (board chỉ gõ được ASCII)")
    ok(call(server, "press_key", {"device": "iPhoneFarm-01", "key": "f13"})["result"]["isError"] is True, "phím không hỗ trợ → từ chối")
    good = [call(server, "key_combo", {"device": "iPhoneFarm-01", "keys": k})["result"]["isError"] for k in ("GUI+Space", "ctrl shift 4", "gui h")]
    badc = [call(server, "key_combo", {"device": "iPhoneFarm-01", "keys": k})["result"]["isError"] for k in ("", "h gui", "gui home", "a b c d e f g")]
    ok(good == [False] * 3 and badc == [True] * 4, "tổ hợp phím: nhận «gui h», «GUI+Space»; từ chối dạng sai", (good, badc))
    ok(g.screen == "home", "«gui h» đưa máy giả về màn hình chính")
    r = call(server, "tap", {"device": "iPhoneFarm-01"})
    ok(r["result"]["isError"] is True and "x,y" in body(r), "tap thiếu cả toạ độ lẫn chữ → lời chỉ dẫn")
    before = len(g.gestures)
    call(server, "swipe", {"device": "iPhoneFarm-01", "direction": "left"}); call(server, "swipe", {"device": "iPhoneFarm-01", "x1": 1, "y1": 2, "x2": 3, "y2": 4})
    call(server, "long_press", {"device": "iPhoneFarm-01", "x": 10, "y": 20, "seconds": 1.5})
    ok(g.gestures[before:] == [("flick", "left"), ("swipe", 1, 2, 3, 4), ("hold", 10, 20, 1.5)], "vuốt theo hướng / theo toạ độ / bấm giữ tới đúng máy", g.gestures[before:])
    ok(call(server, "swipe", {"device": "iPhoneFarm-01", "direction": "cheo"})["result"]["isError"] is True and call(server, "swipe", {"device": "iPhoneFarm-01", "x1": 1})["result"]["isError"] is True, "vuốt sai hướng / thiếu toạ độ → từ chối")
    gp = T.FakeGame(T.accounts(), pointer_fail=True); host.navs["iPhoneFarm-02"] = T.FakeNav(gp); host.games["iPhoneFarm-02"] = gp
    r = call(server, "tap", {"device": "iPhoneFarm-02", "x": 5, "y": 5})
    ok(r["result"]["isError"] is True and "con trỏ" in body(r) and gp.clicks == 0, "con trỏ không tới nơi → báo lỗi, KHÔNG bấm", body(r))

    ok("nhiều máy" in body(call(server, "tap", {"device": "iphonefarm", "x": 1, "y": 1})) and "Không có máy" in body(call(server, "tap", {"device": "may-la", "x": 1, "y": 1})),
       "tên máy mơ hồ / không tồn tại → liệt kê các máy để AI chọn lại")
    ok("Cần nêu tên máy" in body(call(server, "go_home", {})), "nhiều máy sẵn sàng mà không nêu tên → hỏi lại (không tự chọn bừa)")
    n0 = host.full_lists
    call(server, "go_home", {"device": "iPhoneFarm-01"})
    ok(host.full_lists == n0, "ghi đúng tên máy → không phải dò lại cả đội máy")
    host.running.add("iPhoneFarm-01")
    clicks = g.clicks
    r = call(server, "tap", {"device": "iPhoneFarm-01", "x": 1, "y": 1})
    ok(r["result"]["isError"] is True and "đang chạy" in body(r) and g.clicks == clicks, "máy đang chạy đơn → TỪ CHỐI mọi thao tác chạm (không chen vào giữa đơn nạp)", body(r))
    ok(call(server, "read_screen", {"device": "iPhoneFarm-01", "include_image": False})["result"]["isError"] is False, "…nhưng vẫn ĐỌC được màn hình của máy đang chạy")
    st = body(call(server, "farm_status"))
    ok("iPhoneFarm-01: đang chạy — Chờ đơn (xong 2, lỗi 0, đối soát 1)" in st and "Đã mua 1050 Coins" in st, "farm_status: trạng thái + bộ đếm + nhật ký", st)
    host.running.clear()

    g.screen, g.focus = "login", None
    steps = [{"type": "tap_text", "text": "Đăng nhập"}, {"type": "type", "value": "{{user}}"}, {"type": "key", "name": "tab"},
             {"type": "tap_text", "text": "Nút không có", "optional": True}, {"type": "type", "text": "{{pw}}"}, {"type": "key", "name": "enter"}, {"type": "wait_text", "text": "Trang chủ", "timeout": 2}]
    g.user = None
    r = call(server, "run_steps", {"device": "iPhoneFarm-01", "steps": steps, "vars": {"user": "a@test.vn", "pw": "PassA#1"}})
    ok(r["result"]["isError"] is False and r["result"]["structuredContent"]["completed"] is True and g.user == "a@test.vn" and "PassA#1" not in body(r),
       "run_steps: chạy cả chuỗi (nhận cả dạng bước của gateway), bước tuỳ chọn hỏng thì bỏ qua, không lộ giá trị biến", body(r))
    r = call(server, "run_steps", {"device": "iPhoneFarm-01", "steps": [{"type": "tap_text", "text": "Không có chữ này"}, {"type": "home"}]})
    ok(r["result"]["isError"] is True and "✗ 1." in body(r) and "2." not in body(r), "run_steps dừng ở bước lỗi đầu tiên và nói rõ bước nào", body(r))
    ok(call(server, "run_steps", {"device": "iPhoneFarm-01", "steps": [{"type": "swipe", "value": "cheo"}]})["result"]["isError"] is True
       and call(server, "run_steps", {"device": "iPhoneFarm-01", "steps": []})["result"]["isError"] is True, "bước sai cấu hình / danh sách rỗng → từ chối trước khi chạm vào máy")

    gl = body(call(server, "list_groups"))
    ok("Nhóm eFootball (id g1) — chế độ api" in gl and "pool «game-test»" in gl, "danh sách nhóm", gl)
    call(server, "start_run", {"group": "nhom efootball", "device": "iPhoneFarm-01"}); call(server, "stop_run", {"device": "iPhoneFarm-01", "force": True}); call(server, "stop_run", {"group": "g1"})
    ok(host.started == [("g1", "iPhoneFarm-01")] and host.stopped == [("iPhoneFarm-01", None, True), (None, "g1", False)], "chạy / dừng theo tên nhóm hoặc id, dừng thường và dừng ngay", (host.started, host.stopped))
    ok(call(server, "start_run", {"group": "nhóm lạ"})["result"]["isError"] is True and call(server, "stop_run", {})["result"]["isError"] is True, "nhóm không tồn tại / không nêu gì để dừng → từ chối")

    done = []
    slow = host.navs["iPhoneFarm-01"]
    orig_tap = slow.tap_at
    def tap_slow(*a, **k):
        done.append(("vào", threading.current_thread().name)); REAL_SLEEP(0.25); done.append(("ra", threading.current_thread().name)); return orig_tap(*a, **k)
    slow.tap_at = tap_slow
    th = [threading.Thread(target=lambda: call(server, "tap", {"device": "iPhoneFarm-01", "x": 3, "y": 3}), name="L%d" % i) for i in range(3)]
    [x.start() for x in th]; [x.join() for x in th]
    slow.tap_at = orig_tap
    ok([a for a, _ in done] == ["vào", "ra"] * 3, "ba lệnh cùng lúc lên MỘT máy → chạy lần lượt, không chen nhau", done)

    # --- giá trị lạ không được lọt xuống board (verify vòng 5, W-4) ---
    g.screen = "home"; logged = len(g.keylog); clicks0 = g.clicks
    r = call(server, "open_app", {"device": "iPhoneFarm-01", "app": "Settings\nclick"})
    ok(r["result"]["isError"] is True and g.clicks == clicks0 and len(g.keylog) == logged, "tên app có lẫn XUỐNG DÒNG («Settings⏎click») → từ chối, board không nhận lệnh nào", (body(r), g.keylog[logged:]))
    r = call(server, "open_app", {"device": "iPhoneFarm-01", "app": "Cài đặt"})
    ok(r["result"]["isError"] is True and "không dấu" in body(r) and len(g.keylog) == logged, "tên app có dấu tiếng Việt → từ chối kèm hướng dẫn (trước đây báo «đã mở» trong khi board gõ ra rác)", body(r))
    r = call(server, "run_steps", {"device": "iPhoneFarm-01", "steps": [{"type": "combo", "keys": "gui h\ndown"}]})
    ok(r["result"]["isError"] is True and g.clicks == clicks0, "tổ hợp phím có lẫn lệnh khác («gui h⏎down») trong run_steps → từ chối", body(r))
    r = call(server, "run_steps", {"device": "iPhoneFarm-01", "steps": [{"type": "type", "text": "mat-khau-thu-123"}, {"type": "key", "name": "enter"}]})
    ok("mat-khau-thu-123" not in json.dumps(r["result"], ensure_ascii=False) and "Gõ 16 ký tự" in body(r), "run_steps không lặp lại chữ đã gõ trong kết quả (có thể là mật khẩu)", body(r))
    st0 = call(server, "farm_status", {"log_lines": 0})["result"]
    ok(st0["structuredContent"]["log"] == [] and "nhật ký gần đây" not in body({"result": st0}), "farm_status log_lines=0 → không kèm dòng nhật ký nào (trước đây trả cả nhật ký)")

    # --- huỷ lệnh đang chạy (verify vòng 5, W-7) ---
    g.screen = "home"
    started = threading.Event()
    slowe = host.navs["iPhoneFarm-01"].e
    orig_read = slowe.read_text
    def read_and_flag(img=None, **kw):
        started.set(); return orig_read(img, **kw)
    slowe.read_text = read_and_flag
    box = {}
    th = threading.Thread(target=lambda: box.update(r=server.handle({"jsonrpc": "2.0", "id": "dai-1", "method": "tools/call",
                                                                      "params": {"name": "wait_for_text", "arguments": {"device": "iPhoneFarm-01", "text": "Chữ không bao giờ có", "timeout": 60}}})))
    t0 = time.time(); th.start(); started.wait(5)
    server.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": "dai-1", "reason": "thử"}})
    th.join(8)
    ok(not th.is_alive() and time.time() - t0 < 8 and box["r"]["result"]["isError"] is True and "huỷ" in body(box["r"]),
       "client xin HUỶ (notifications/cancelled) → lệnh chờ 60 giây dừng ngay, báo đã huỷ", (round(time.time() - t0, 1), box.get("r")))
    started.clear()
    th = threading.Thread(target=lambda: box.update(r2=call(server, "run_steps", {"device": "iPhoneFarm-01", "steps": [{"type": "wait_text", "text": "Không có", "timeout": 60}, {"type": "home"}]}, mid="dai-2")))
    t0 = time.time(); th.start(); started.wait(5)
    c.cancel_all()
    th.join(8)
    ok(not th.is_alive() and box["r2"]["result"]["isError"] is True and "huỷ" in body(box["r2"]) and host.held == [],
       "«huỷ hết» (tắt cầu nối / đổi khoá) → chuỗi bước đang chạy dừng lại, máy được nhả", box.get("r2"))
    slowe.read_text = orig_read
    ok(call(server, "go_home", {"device": "iPhoneFarm-01"})["result"]["isError"] is False, "sau khi huỷ, lệnh mới vẫn chạy bình thường")
    deep = "[" * 5000 + "]" * 5000
    out = io.BytesIO()
    serve_stdio(server, stdin=io.BytesIO((deep + "\n" + json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"}) + "\n").encode()), stdout=out)
    got = [json.loads(l) for l in out.getvalue().decode().splitlines()]
    ok(len(got) == 2 and got[0]["error"]["code"] == -32700 and got[1] == {"jsonrpc": "2.0", "id": 9, "result": {}}, "một dòng JSON lồng 5000 tầng → chỉ là lỗi phân tích; máy chủ stdio KHÔNG chết, vẫn trả lời yêu cầu sau", got[:1])

    # --- board ESP32: xem sức khoẻ + phục hồi qua MCP / CLI ---
    import test_board as TB
    nav1 = host.navs["iPhoneFarm-01"]
    old_h, host.running = nav1.h, set()
    nav1.h = TB.FakeBoard([TB.GOOD])
    r = call(server, "board_health", {"device": "iPhoneFarm-01"})
    sc = r["result"].get("structuredContent") or {}
    ok(r["result"]["isError"] is False and "KHOẺ" in body(r) and sc.get("level") == "ok" and sc.get("heap") == 152000 and "temp_c" in sc and nav1.h.soft == 0,
       "board_health: board khoẻ → báo KHOẺ kèm RAM / thời gian chạy / lý do reset, không reset gì", body(r))
    nav1.h = TB.FakeBoard([TB.line(heap=18000, min=9000), TB.GOOD])
    r = call(server, "board_health", {"device": "iPhoneFarm-01"})
    ok(r["result"]["isError"] is False and "NẶNG" in body(r) and "RAM" in body(r) and nav1.h.soft == 0, "board_health: thiếu RAM → báo NẶNG và nói rõ, nhưng chỉ XEM, không tự reset", body(r))
    r = call(server, "board_recover", {"device": "iPhoneFarm-01"})
    ok(r["result"]["isError"] is False and nav1.h.soft == 1 and "reset mềm" in body(r), "board_recover: thiếu RAM → reset mềm rồi báo đã dùng được", body(r))
    nav1.h = TB.FakeBoard([TB.GOOD])
    r = call(server, "board_recover", {"device": "iPhoneFarm-01"})
    ok(r["result"]["isError"] is False and nav1.h.soft == 0 and nav1.h.hard == 0 and "Không cần làm gì" in body(r), "board_recover trên board khoẻ → không làm gì", body(r))
    nav1.h = TB.FakeBoard([TB.GOOD], silent_first=10 ** 12, dead=True)
    r = call(server, "board_health", {"device": "iPhoneFarm-01"})
    ok(r["result"]["isError"] is True and "không trả lời" in body(r), "board_health: board im → báo lỗi rõ, gợi ý board_recover", body(r))
    r = call(server, "board_recover", {"device": "iPhoneFarm-01"})
    ok(r["result"]["isError"] is True and nav1.h.hard == 1 and "VẪN CHƯA ỔN" in body(r), "board_recover: reset cứng xong vẫn im → báo hỏng, KHÔNG lặp vô hạn", body(r))
    nav1.h = TB.FakeBoard([TB.GOOD]); host.running.add("iPhoneFarm-01")
    r = call(server, "board_recover", {"device": "iPhoneFarm-01"})
    ok(r["result"]["isError"] is True and "đang chạy" in body(r) and nav1.h.soft == 0 and nav1.h.hard == 0, "máy đang chạy đơn / kịch bản → từ chối khởi động lại board (reset giữa đơn làm rớt BLE)", body(r))
    host.running.discard("iPhoneFarm-01"); nav1.h = old_h

    print("\n== 4b. Đọc chữ thật (tesseract): nhãn cùng hàng tách thành từng cụm ==")
    canvas = np.full((300, 750, 3), 255, np.uint8)
    for label, x in (("FaceTime", 40), ("Camera", 320), ("Settings", 590)):
        cv2.putText(canvas, label, (x, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
    cv2.putText(canvas, "Wi-Fi is turned on", (40, 250), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
    try:
        lines = real_ocr(canvas)
    except ToolError as e:
        lines = None
        print("  (bỏ qua: %s)" % e)
    if lines is not None:
        row = sorted([l for l in lines if abs(l["y"] - 140) < 30], key=lambda l: l["x"])
        ok([norm(l["text"]) for l in row] == ["facetime", "camera", "settings"] and row[0]["x"] < 200 < row[1]["x"] < 500 < row[2]["x"],
           "ba nhãn cách xa nhau trên một hàng → ba cụm chữ, mỗi cụm một toạ độ riêng", row)
        sent = [l for l in lines if abs(l["y"] - 240) < 30]
        ok(len(sent) == 1 and "turned" in norm(sent[0]["text"]), "một câu liền (cách nhau bằng dấu cách thường) vẫn là MỘT dòng", sent)

    print("\n== 5. Dòng lệnh (CLI) ==")
    tools = control.build_tools(c)
    ap = cli.build_parser(tools)
    tap = next(t for t in tools if t.cli == "tap")
    ok(cli.collect(tap, ap.parse_args(["tap", "iPhoneFarm-01", "288", "468"])) == {"device": "iPhoneFarm-01", "x": 288, "y": 468}, "farm tap <máy> <x> <y>")
    ok(cli.collect(tap, ap.parse_args(["tap", "iPhoneFarm-01", "--text", "Cài đặt"])) == {"device": "iPhoneFarm-01", "text": "Cài đặt"}, "farm tap <máy> --text \"…\"")
    ok(cli.collect(tap, ap.parse_args(["tap", "--x", "1", "--y", "2"])) == {"x": 1, "y": 2}, "bỏ tên máy, dùng cờ --x --y")
    typ = next(t for t in tools if t.cli == "type")
    ok(cli.collect(typ, ap.parse_args(["type", "iPhoneFarm-01", "hello", "--enter"])) == {"device": "iPhoneFarm-01", "text": "hello", "enter": True}, "cờ bật/tắt: --enter")
    scr = next(t for t in tools if t.cli == "screen")
    ok(cli.collect(scr, ap.parse_args(["screen", "iPhoneFarm-01", "--no-include-image", "--scale", "0.5"])) == {"device": "iPhoneFarm-01", "include_image": False, "scale": 0.5}, "--no-include-image, số thực")
    run = next(t for t in tools if t.cli == "run")
    sf = os.path.join(tmp, "steps.json")
    json.dump([{"type": "home"}], open(sf, "w"))
    ok(cli.collect(run, ap.parse_args(["run", "iPhoneFarm-01", "@" + sf]))["steps"] == [{"type": "home"}]
       and cli.collect(run, ap.parse_args(["run", "iPhoneFarm-01", '[{"type":"home"}]']))["steps"] == [{"type": "home"}], "chuỗi bước: JSON trực tiếp hoặc @tệp.json")
    known = ["iPhoneFarm-01", "Máy số một"]
    fnd = next(t for t in tools if t.cli == "find"); swp = next(t for t in tools if t.cli == "swipe"); key = next(t for t in tools if t.cli == "key")
    ok(cli.collect(fnd, ap.parse_args(["find", "Safari"]), known) == {"text": "Safari"} and cli.collect(typ, ap.parse_args(["type", "hello"]), known) == {"text": "hello"}
       and cli.collect(swp, ap.parse_args(["swipe", "left"]), known) == {"direction": "left"} and cli.collect(key, ap.parse_args(["key", "enter"]), known) == {"key": "enter"}
       and cli.collect(tap, ap.parse_args(["tap", "288", "468"]), known) == {"x": 288, "y": 468},
       "bỏ tên máy ở ô đầu được: farm find Safari · farm type hello · farm swipe left · farm key enter · farm tap 288 468")
    ok(cli.collect(fnd, ap.parse_args(["find", "may so mot", "Safari"]), known) == {"device": "may so mot", "text": "Safari"}
       and cli.collect(fnd, ap.parse_args(["find", "iPhoneFarm-01", "Safari"]), known)["device"] == "iPhoneFarm-01", "ô đầu là tên / nhãn một máy đã khai → vẫn hiểu là tên máy")
    ok(_raises(lambda: cli.collect(tap, ap.parse_args(["tap", "iPhoneFarm-01", "ba", "5"])), SystemExit)
       and _raises(lambda: cli.collect(tap, ap.parse_args(["tap", "iPhoneFarm-01", "1", "2", "--x", "3"])), SystemExit), "giá trị sai kiểu / nêu hai lần → báo lỗi dễ hiểu")
    ns = ap.parse_args(["--out", os.path.join(tmp, "anh", "m.jpg"), "screen", "iPhoneFarm-01"])
    buf = io.StringIO(); old = sys.stdout; sys.stdout = buf
    try:
        code = cli.emit(scr, server.call(scr, cli.collect(scr, ns)), ns)
    finally:
        sys.stdout = old
    ok(code == 0 and os.path.getsize(os.path.join(tmp, "anh", "m.jpg")) > 100 and "Ảnh: " in buf.getvalue() and "(40,100)" in buf.getvalue(), "farm screen: in chữ kèm toạ độ, lưu ảnh ra tệp", buf.getvalue()[-90:])
    ns = ap.parse_args(["--json", "devices"])
    buf = io.StringIO(); sys.stdout = buf
    try:
        code = cli.emit(tools[0], server.call(tools[0], {}), ns)
    finally:
        sys.stdout = old
    js = json.loads(buf.getvalue())
    ok(code == 0 and js["ok"] is True and js["data"]["devices"][0]["name"] == "iPhoneFarm-01", "--json: kết quả máy đọc được")
    ns = ap.parse_args(["tap", "may-la", "1", "1"])
    err = io.StringIO(); olde = sys.stderr; sys.stderr = err
    try:
        code = cli.emit(tap, server.call(tap, cli.collect(tap, ns)), ns)
    finally:
        sys.stderr = olde
    ok(code == 1 and "LỖI: Không có máy" in err.getvalue(), "lệnh hỏng → mã thoát 1, lỗi ra stderr", err.getvalue()[:60])
    ok(len({t.cli for t in tools}) == len(tools) and all(t.help for t in tools) and not {t.cli for t in tools} & {"tools", "mcp", "mcp-config"}, "mỗi công cụ một lệnh con riêng, có mô tả tiếng Việt")

    print("\n== 6. App đang mở → lệnh đi qua app; chưa mở → tự làm tại chỗ ==")
    old_file = control.ENDPOINT_FILE
    control.ENDPOINT_FILE = os.path.join(tmp, "control.json")
    try:
        ok(control.load_endpoint() is None and control.remote() is None, "chưa có tệp cổng/khoá → coi như app chưa mở")
        tk = control.token()
        httpd, port = serve_http(server, tk, 47930)
        try:
            control.save_endpoint(port, tk)
            mode = os.stat(control.ENDPOINT_FILE).st_mode & 0o777
            ok(mode == 0o600 and control.token() == tk and control.token(renew=True) != tk, "tệp khoá chỉ chủ máy đọc được (600); khoá giữ nguyên giữa các lần mở app", oct(mode))
            ptools, phost = control.proxied_tools()
            local_calls = []
            phost.devices = lambda: local_calls.append(1) or []
            r = next(t for t in ptools if t.name == "list_devices").fn()
            ok("iPhoneFarm-01" in r.content[0]["text"] and local_calls == [], "app đang mở → CLI/MCP chuyển lệnh cho app (không tự mở cổng)")
            ok(_raises(lambda: next(t for t in ptools if t.name == "tap").fn(device="may-la", x=1, y=1), ToolError), "lỗi từ app được chuyển nguyên về cho người gọi")
            class Idle:
                closed = 0
                def close(self): Idle.closed += 1
            phost.sessions["m-ranh"] = Idle(); phost.sessions["m-ban"] = Idle(); phost.inuse["m-ban"] = 1
            next(t for t in ptools if t.name == "list_devices").fn()
            ok(Idle.closed == 1 and list(phost.sessions) == ["m-ban"], "trước khi chuyển lệnh cho app: nhả các cổng đang giữ tại chỗ (để app mở được) — trừ phiên đang chạy lệnh", list(phost.sessions))
            phost.used["m-ban"] = 0
            phost._reap_once(now=10 ** 9)
            ok(list(phost.sessions) == ["m-ban"], "phiên ĐANG chạy lệnh không bị dọn dù đã «rảnh» rất lâu (lệnh dài không bị rút cổng giữa chừng)")
            phost.inuse["m-ban"] = 0
            phost._reap_once(now=10 ** 9)
            ok(phost.sessions == {} and Idle.closed == 2, "lệnh xong + rảnh quá hạn → phiên được đóng, nhả cổng cho app")
            os.environ["FARM_LOCAL"] = "1"
            next(t for t in ptools if t.name == "list_devices").fn()
            os.environ.pop("FARM_LOCAL")
            ok(local_calls == [1], "--local → bỏ qua app, làm tại chỗ")
            # --- huỷ phải ĐI QUA proxy `farm mcp` tới app (verify vòng 6, W-1): bấm Esc trong Claude Code thì điện thoại dừng ---
            pserver = McpServer(ptools, instructions=control.INSTRUCTIONS)
            started = threading.Event()
            slowe = host.navs["iPhoneFarm-01"].e
            orig_rt = slowe.read_text
            def flag_read(img=None, **kw):
                started.set(); return orig_rt(img, **kw)
            slowe.read_text = flag_read
            box = {}
            th = threading.Thread(target=lambda: box.update(r=pserver.handle({"jsonrpc": "2.0", "id": "px-1", "method": "tools/call",
                "params": {"name": "wait_for_text", "arguments": {"device": "iPhoneFarm-01", "text": "Chữ không bao giờ có", "timeout": 60}}})))
            t0 = time.time(); th.start(); started.wait(8)
            pserver.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": "px-1"}})
            th.join(20)
            slowe.read_text = orig_rt
            ok(not th.is_alive() and time.time() - t0 < 20 and box["r"]["result"]["isError"] is True and "huỷ" in body(box["r"]),
               "client xin HUỶ qua máy chủ stdio (proxy) → báo tới APP, lệnh dài trên điện thoại dừng ngay (trước đây chạy nốt)", (round(time.time() - t0, 1), box.get("r")))
            # --- Ctrl-C ở dòng lệnh (W-6): báo app huỷ đúng yêu cầu của mình rồi mới thoát ---
            import _thread, signal
            rm = Remote(port, tk)
            posts, gate = [], threading.Event()
            def fake_post(payload, timeout):
                posts.append(payload)
                if "id" in payload:
                    gate.wait(10)
                    return {"jsonrpc": "2.0", "id": payload["id"], "result": {}}
                return None
            rm._post = fake_post
            old_sig = signal.signal(signal.SIGINT, signal.default_int_handler)     # chạy nền có thể đã tắt SIGINT
            threading.Timer(0.4, _thread.interrupt_main).start()
            try:
                rm.call("list_devices"); got = "không bị ngắt"
            except KeyboardInterrupt:
                got = "bị ngắt"
            finally:
                signal.signal(signal.SIGINT, old_sig)
            gate.set()
            note = [p for p in posts if p.get("method") == "notifications/cancelled"]
            ok(got == "bị ngắt" and len(note) == 1 and note[0]["params"]["requestId"] == posts[0]["id"],
               "Ctrl-C khi đang chờ app → báo app HUỶ đúng yêu cầu của mình rồi mới thoát", (got, posts))
            cfg = cli.mcp_config()
            ok("claude mcp add iphone-farm -- " in cfg and '"mcpServers"' in cfg and ("http://127.0.0.1:%d/mcp" % port) in cfg and tk not in cfg, "farm mcp-config: lệnh cho Claude Code + JSON cho client khác + địa chỉ HTTP; KHÔNG in khoá ra màn hình", cfg[:80])
            ok(tk in cli.mcp_config(show_token=True), "…chỉ in khoá khi được yêu cầu rõ (--show-token)")
        finally:
            httpd.shutdown(); httpd.server_close()
        local_calls.clear()
        next(t for t in ptools if t.name == "list_devices").fn()
        ok(local_calls == [1] and control.remote() is None, "app tắt → lệnh kế tiếp tự làm tại chỗ")
        ok("mở app" in cli.mcp_config(), "mcp-config khi app tắt: hướng dẫn mở app để lấy địa chỉ HTTP")
    finally:
        control.ENDPOINT_FILE = old_file

    print("\n== 7. Máy chủ điều khiển chạy TRONG app ==")
    control.ENDPOINT_FILE = os.path.join(tmp, "control-app.json")
    try:
        class FakeRunner:
            def __init__(self): self.on, self.holds, self.mode = set(), {}, "api"
            def is_running(self, n): return n in self.on
            def running_names(self): return list(self.on)
            def hold_reason(self, n): return self.holds.get(n)
            def status(self):
                out = {n: {"name": n, "running": True, "mode": self.mode, "status": "Đang mua 1050 Coins (1/2)", "counts": {"done": 1, "failed": 0, "review": 0}} for n in self.on}
                for n, why in self.holds.items():      # máy đã dừng nhưng đang được GIỮ cho người kiểm tra (như runner thật)
                    out.setdefault(n, {"name": n, "running": False, "mode": self.mode, "status": "dừng", "hold": why, "counts": {"done": 0, "failed": 0, "review": 1}})
                return out
            def log_tail(self, limit=200): return [{"t": "09:00:00", "name": "iPhoneFarm-01", "text": "Bắt đầu nhận đơn"}]
        class FakeMgr:
            def __init__(self, navs): self.navs, self.asked, self.board_map, self.sessions, self.rescans = navs, [], {}, {}, 0
            def rescan(self): self.rescans += 1; self.board_map = {n: "/dev/cu.gia-" + n for n in self.navs}
            def session(self, n):
                if n not in self.board_map: raise RuntimeError("Không thấy board '%s' (bấm Quét board)" % n)
                self.asked.append(n); self.sessions[n] = self.navs[n]; return self.navs[n]
            def _udid(self, n): return "UDID-" + n if n in self.navs else None
        class FakeApi:
            def __init__(self): self.calls = []
            def list_devices(self):
                return [{"name": "iPhoneFarm-01", "udid": "BI-MAT-UDID", "label": "Máy A", "board_online": True, "port": "/dev/cu.x", "ble": True, "ios_connected": True,
                         "ios": "16.7", "model": "iPhone 8", "group_id": "g1", "group_name": "Nhóm A", "running": True}]
            def machine_run(self, gid, n): self.calls.append(("machine_run", gid, n)); return {"ok": True, "started": True}
            def group_run(self, gid): self.calls.append(("group_run", gid)); return {"ok": False, "error": "Nhóm chưa chọn pool của gateway."}
            def machine_stop(self, n, force=False): self.calls.append(("machine_stop", n, force)); return {"ok": True}
            def group_stop(self, gid, force=False): self.calls.append(("group_stop", gid, force)); return {"ok": True}
            def rescan(self): self.calls.append(("rescan",)); return {"ok": False, "error": "Đang có máy chạy"}
        fh = FakeHost()
        runner, mgr, api = FakeRunner(), FakeMgr(fh.navs), FakeApi()
        store_devs, store_groups = control.store.get_devices, control.store.get_groups
        control.store.get_devices = lambda: [{"name": "iPhoneFarm-01", "udid": "BI-MAT-UDID", "label": "Máy A"}]
        control.store.get_groups = lambda: [{"id": "g1", "name": "Nhóm A", "mode": "api", "devices": ["iPhoneFarm-01"], "api": {"pool": "game-test", "steps": {"login": [{"type": "type", "text": "{{password}}"}]}}, "steps": []}]
        try:
            ah = control.AppHost(mgr, runner, api)
            runner.on.add("iPhoneFarm-01")
            d = ah.devices()[0]
            ok(d == {"name": "iPhoneFarm-01", "label": "Máy A", "board": True, "bluetooth": True, "iphone": True, "ios": "16.7", "model": "iPhone 8",
                     "group": "Nhóm A", "running": True, "status": "Đang mua 1050 Coins (1/2)", "hold": None}, "máy trong app → thông tin gọn cho AI (không kèm UDID, cổng)", d)
            why = ah.acquire("iPhoneFarm-01")
            ok("đang chạy" in (why or "") and ah.acquire("iPhoneFarm-02") is None and ah.active() == ["iPhoneFarm-02"], "máy đang nhận đơn = không xin được; máy rảnh thì xin được", why)
            ah.release("iPhoneFarm-02")
            gv = ah.groups()[0]
            ok(gv == {"id": "g1", "name": "Nhóm A", "mode": "api", "devices": ["iPhoneFarm-01"], "pool": "game-test", "steps": 0} and "password" not in json.dumps(gv),
               "nhóm: chỉ tên / chế độ / máy / pool — KHÔNG lộ các bước (có thể chứa dữ liệu riêng)", gv)
            srv = control.AppServer(ah)
            okstart = srv.start(47960)
            info = srv.info()
            ok(okstart and info["running"] and info["url"] == "http://127.0.0.1:%d/mcp" % srv.port and info["claude_code"].startswith("claude mcp add iphone-farm -- ")
               and info["claude_code"].endswith("/farm mcp") and '"mcpServers"' in info["json"], "app mở máy chủ điều khiển + có sẵn câu lệnh / JSON để dán cho AI", {k: info[k] for k in ("running", "url", "error")})
            rm = control.remote()
            ok(rm is not None and rm.health()["host"] == "app", "CLI / `farm mcp` tìm thấy app qua tệp cổng+khoá")
            t = rm.call("tap", {"device": "iPhoneFarm-01", "x": 5, "y": 5})
            ok(t["isError"] is True and "đang chạy kịch bản" in t["content"][0]["text"] and mgr.asked == [], "qua app: máy đang nhận đơn → từ chối, KHÔNG mở phiên điều khiển", t["content"][0]["text"])
            runner.on.clear()
            t = rm.call("tap", {"device": "iPhoneFarm-01", "x": 5, "y": 5})
            ok(t["isError"] is False and mgr.asked == ["iPhoneFarm-01"] and mgr.rescans == 1, "máy rảnh → bấm qua phiên của app (app vừa mở chưa quét board → tự quét một lần)", (mgr.asked, mgr.rescans))
            rm.call("tap", {"device": "iPhoneFarm-01", "x": 5, "y": 5})
            ok(mgr.rescans == 1, "đã biết board rồi thì không quét lại mỗi lệnh")
            rm.call("start_run", {"group": "Nhóm A", "device": "iPhoneFarm-01"}); r2 = rm.call("start_run", {"group": "g1"})
            rm.call("stop_run", {"device": "iPhoneFarm-01"}); rm.call("stop_run", {"group": "Nhóm A", "force": True}); r3 = rm.call("rescan_boards")
            ok(api.calls == [("machine_run", "g1", "iPhoneFarm-01"), ("group_run", "g1"), ("machine_stop", "iPhoneFarm-01", False), ("group_stop", "g1", True), ("rescan",)],
               "chạy / dừng / quét lại đi qua đúng các hàm của app", api.calls)
            ok(r2["isError"] is True and "chưa chọn pool" in r2["content"][0]["text"] and r3["isError"] is True and "Đang có máy chạy" in r3["content"][0]["text"],
               "app từ chối (nhóm thiếu cấu hình, đang có máy chạy) → lý do tới được người gọi")
            st = rm.call("farm_status")["content"][0]["text"]
            ok("Bắt đầu nhận đơn" in st, "xem được nhật ký chạy của app", st[:80])
            # máy đang được AI điều khiển thì app phải biết (để không dò/đóng cổng của nó giữa chừng)
            seen = []
            nav = fh.navs["iPhoneFarm-01"]; orig = nav.tap_at
            def slow_tap(*a, **k):
                seen.append(list(srv.control.active())); return orig(*a, **k)
            nav.tap_at = slow_tap
            rm.call("tap", {"device": "iPhoneFarm-01", "x": 6, "y": 6}); nav.tap_at = orig
            ok(seen == [["iPhoneFarm-01"]] and srv.control.active() == [], "trong lúc AI đang bấm, app biết máy đó đang bận; xong thì hết bận", (seen, srv.control.active()))
            old_tk = srv.token
            ok(srv.renew_token() and srv.token != old_tk and _raises(lambda: Remote(srv.port, old_tk).call("list_devices"), ToolError)
               and control.remote().call("list_devices")["isError"] is False, "đổi khoá: khoá cũ bị từ chối ngay, CLI tự dùng khoá mới")
            port_was = srv.port
            srv.stop()
            ok(control.remote() is None and Remote(port_was, srv.token).health() is None and control.load_endpoint()["token"] == srv.token,
               "tắt máy chủ điều khiển → CLI biết app không còn nghe; khoá vẫn được giữ cho lần mở sau")
            blocker = __import__("socket").socket(); blocker.bind(("127.0.0.1", 47990)); blocker.listen(1)
            try:
                s2 = control.AppServer(ah)
                ok(s2.start(47990) and s2.port != 47990, "cổng mặc định đang bận → tự lấy cổng kế tiếp", s2.port)
                s2.stop()
            finally:
                blocker.close()
            # --- sổ dùng chung: AI / giao diện / bộ chạy không bao giờ cùng vào một máy (verify vòng 5, W-1..W-3) ---
            claims = control.Claims(running=runner.is_running)
            ok(claims.acquire("m1", "ai") is None and claims.acquire("m1", "ai") is None and "AI / dòng lệnh" in (claims.acquire("m1", "ui") or ""),
               "AI đang điều khiển máy → thao tác thử trên giao diện bị từ chối (nhiều lệnh AI nối đuôi thì được)")
            ok(claims.names("ai") == ["m1"] and claims.names() == ["m1"] and claims.names("ui") == [], "sổ biết ai đang giữ máy nào")
            started = []
            res, why = claims.start(["m1", "m2"], lambda: started.append(1) or "đã chạy")
            ok(res is None and "m1" in why and started == [], "bộ chạy KHÔNG khởi động trên máy đang được điều khiển tay (kiểm + chạy trong cùng một khoá)", why)
            claims.release("m1", "ai"); claims.release("m1", "ai")
            ok(claims.acquire("m1", "ui") is None and "giao diện app" in (claims.acquire("m1", "ai") or ""), "ngược lại: giao diện đang chạy thử → AI bị từ chối")
            claims.release("m1", "ui")
            res, why = claims.start(["m1", "m2"], lambda: started.append(1) or "đã chạy")
            ok(res == "đã chạy" and why is None and started == [1], "không ai giữ máy → bộ chạy khởi động được")
            runner.on.add("m1")
            ok("đang chạy kịch bản" in (claims.acquire("m1", "ai") or "") and "đang chạy kịch bản" in (claims.acquire("m1", "ui") or ""), "máy đang chạy kịch bản/đơn → cả AI lẫn giao diện đều không xin được")
            runner.on.clear()
            race = {"both": 0}
            for _ in range(200):                           # đua thật: AI xin máy ↔ bộ chạy khởi động, cùng lúc
                cl = control.Claims(running=lambda n: bool(flag))
                flag = []
                got = {}
                t1 = threading.Thread(target=lambda: got.update(ai=cl.acquire("m", "ai")))
                t2 = threading.Thread(target=lambda: got.update(run=cl.start(["m"], lambda: flag.append(1) or True)))
                t1.start(); t2.start(); t1.join(); t2.join()
                if got["ai"] is None and got["run"][0]:
                    race["both"] += 1
            ok(race["both"] == 0, "200 lần đua «AI xin máy» với «bộ chạy khởi động» → không lần nào cả hai cùng lọt", race)
            cl = control.Claims()
            ok(cl.acquire("m", "ui") is None and "thao tác thử khác" in (cl.acquire("m", "ui") or "") and cl.acquire("m2", "ui") is None,
               "hai thao tác thử trên giao diện CÙNG một máy → bên sau bị từ chối (không hai luồng cùng trong một Nav); máy khác vẫn xin được")
            cl.release("m", "ui")
            ok(cl.acquire("m", "ui") is None, "…thao tác trước xong thì xin lại được")

            # --- máy dừng chờ đối soát: giữ nguyên màn hình (W-6) ---
            real_eyes_early = control.Eyes
            ah2 = control.AppHost(mgr, runner, api)
            srv2 = control.AppServer(ah2); srv2.start(47975)
            rm2 = control.remote()
            runner.holds["iPhoneFarm-01"] = "đơn T-9 cần đối soát — kiểm tra máy rồi bấm Chạy lại"
            asked0 = list(mgr.asked)
            t = rm2.call("tap", {"device": "iPhoneFarm-01", "x": 5, "y": 5})
            ok(t["isError"] is True and "CHỜ NGƯỜI KIỂM TRA" in t["content"][0]["text"] and "T-9" in t["content"][0]["text"] and mgr.asked == asked0,
               "máy đang dừng chờ đối soát → AI KHÔNG được chạm (màn hình giữ nguyên cho người kiểm tra)", t["content"][0]["text"][:90])
            ok("ON HOLD" in rm2.call("list_devices")["content"][0]["text"], "danh sách máy nói rõ máy nào đang chờ người kiểm tra")
            calls0 = len(api.calls)
            t = rm2.call("start_run", {"group": "Nhóm A", "device": "iPhoneFarm-01"})
            ok(t["isError"] is True and "CHỜ NGƯỜI KIỂM TRA" in t["content"][0]["text"] and len(api.calls) == calls0, "AI cũng không tự «Chạy lại» được máy đang chờ đối soát", t["content"][0]["text"][:90])
            stops0 = [c for c in api.calls if c[0] in ("machine_stop", "group_stop")]
            t1 = rm2.call("stop_run", {"device": "iPhoneFarm-01"}); t2 = rm2.call("stop_run", {"group": "Nhóm A", "force": True})
            ok(t1["isError"] is True and t2["isError"] is True and "CHỜ NGƯỜI KIỂM TRA" in t1["content"][0]["text"] and "CHỜ NGƯỜI KIỂM TRA" in t2["content"][0]["text"]
               and [c for c in api.calls if c[0] in ("machine_stop", "group_stop")] == stops0,
               "AI KHÔNG gỡ được trạng thái chờ kiểm tra bằng stop_run (Dừng = lời xác nhận «đã đối soát» — chỉ người vận hành đưa ra, trong app)", (t1["content"][0]["text"][:90], api.calls[-2:]))
            control.Eyes = lambda udid: fh.navs["iPhoneFarm-01"].e
            t = rm2.call("read_screen", {"device": "iPhoneFarm-01"})
            ok(t["isError"] is True and "đơn của khách" in t["content"][0]["text"] and not [c for c in t["content"] if c["type"] == "image"],
               "máy vừa dừng GIỮA CHỪNG đơn của khách (màn hình còn hiện thông tin khách) → read_screen cũng bị từ chối", t["content"][0]["text"][:80])
            runner.mode = "loop"
            ok(rm2.call("read_screen", {"device": "iPhoneFarm-01", "include_image": False})["isError"] is False, "(máy đang giữ ở chế độ lặp của chủ, không phải đơn khách → vẫn xem được)")
            runner.mode = "api"
            runner.holds.clear()
            ok(rm2.call("read_screen", {"device": "iPhoneFarm-01", "include_image": False})["isError"] is False, "người vận hành xử lý xong (hết chờ) → xem lại được")
            ok(rm2.call("tap", {"device": "iPhoneFarm-01", "x": 5, "y": 5})["isError"] is False, "người vận hành xử lý xong (hết chờ) → điều khiển lại được")
            ok(rm2.call("stop_run", {"device": "iPhoneFarm-01"})["isError"] is False and ("machine_stop", "iPhoneFarm-01", False) in api.calls, "hết chờ rồi thì stop_run bình thường")
            control.Eyes = real_eyes_early

            # --- máy đang làm đơn của KHÁCH: AI không xem được màn hình (riêng tư) ---
            real_eyes = control.Eyes
            control.Eyes = lambda udid: fh.navs["iPhoneFarm-01"].e          # «mắt» giả: không có iPhone thật trong bài thử
            runner.on.add("iPhoneFarm-01"); runner.mode = "api"
            t = rm2.call("read_screen", {"device": "iPhoneFarm-01"})
            ok(t["isError"] is True and "đơn của khách" in t["content"][0]["text"] and not [c for c in t["content"] if c["type"] == "image"],
               "máy đang nhận đơn của khách → read_screen bị từ chối (không đưa tài khoản / OTP của khách cho AI)", t["content"][0]["text"][:80])
            ok(rm2.call("find_text", {"device": "iPhoneFarm-01", "text": "x"})["isError"] is True and rm2.call("farm_status")["isError"] is False, "…tìm chữ cũng vậy; xem tiến độ bằng farm_status thì được")
            runner.mode = "loop"
            ok(rm2.call("read_screen", {"device": "iPhoneFarm-01", "include_image": False})["isError"] is False, "máy đang chạy kịch bản LẶP của chính chủ (không phải đơn khách) → vẫn xem được")
            runner.on.clear(); runner.mode = "api"
            control.Eyes = real_eyes

            # --- đưa khoá cho ĐÚNG app (W: remote() kiểm pid) ---
            ep = control.load_endpoint()
            control.save_endpoint(ep["port"], ep["token"])
            fake_pid = dict(control.load_endpoint(), pid=ep["pid"] + 12345)
            json.dump(fake_pid, open(control.ENDPOINT_FILE, "w"))
            ok(control.remote() is None, "tệp cổng/khoá ghi tiến trình KHÁC với thứ đang nghe ở cổng đó → không gửi khoá, coi như app chưa mở")
            control.save_endpoint(ep["port"], ep["token"])
            ok(control.remote() is not None, "(đúng tiến trình thì nối bình thường)")
            # tắt cầu nối giữa lúc AI đang chạy lệnh → lệnh dừng
            flagged = threading.Event()
            e1 = fh.navs["iPhoneFarm-01"].e; orig_rt = e1.read_text
            def rt(img=None, **kw):
                flagged.set(); return orig_rt(img, **kw)
            e1.read_text = rt
            res = {}
            th = threading.Thread(target=lambda: res.update(r=rm2.call("wait_for_text", {"device": "iPhoneFarm-01", "text": "Không bao giờ có", "timeout": 60})))
            t0 = time.time(); th.start(); flagged.wait(5); srv2.stop(); th.join(10)
            e1.read_text = orig_rt
            ok(not th.is_alive() and time.time() - t0 < 10, "tắt cầu nối trong lúc AI đang chạy một lệnh dài → lệnh đó dừng theo (không chạy ngầm tiếp)", round(time.time() - t0, 1))
        finally:
            control.store.get_devices, control.store.get_groups = store_devs, store_groups
    finally:
        control.ENDPOINT_FILE = old_file

    print("\n== 8. Trong app (gui.py): thao tác thử, quét / nạp board, chạy nhóm đều tôn trọng máy đang được điều khiển ==")
    import types
    if "webview" not in sys.modules:                       # không cần cửa sổ thật để thử phần logic
        sys.modules["webview"] = types.SimpleNamespace(create_window=lambda *a, **k: None, start=lambda *a, **k: None)
    import gui
    api2 = gui.Api()
    saved = (gui.MGR.board_map, gui.MGR.sessions, gui.esp.list_boards, gui.esp.probe, gui.esp.chip_info, gui.store.get_devices, gui._push, gui.store.get_group, gui.Api._runnable)
    closed, probed = [], []
    class Sess:
        def __init__(self, n): self.n = n; self.h = types.SimpleNamespace(status=lambda: "OK ble=connected")
        def close(self): closed.append(self.n)
    try:
        gui.MGR.board_map = {"A": "/dev/cu.A", "B": "/dev/cu.B"}
        gui.MGR.sessions = {"A": Sess("A"), "B": Sess("B")}
        gui.esp.list_boards = lambda: [{"port": "/dev/cu.A"}, {"port": "/dev/cu.B"}]
        gui.esp.probe = lambda port, timeout=3.0: probed.append(port) or {"flashed": True, "name": port[-1], "ble": True}
        gui.esp.chip_info = lambda port: {"ok": True, "chip": "ESP32"}
        gui._push = lambda js: None
        ok(gui.CLAIMS.acquire("A", "ai") is None, "(AI đang điều khiển máy A)")
        r = api2.run_step("A", {"type": "home"})
        ok(r["ok"] is False and "AI / dòng lệnh" in r["msg"], "giao diện «chạy thử bước» trên máy AI đang điều khiển → bị từ chối", r)
        ok(api2.test_api_steps("A", [{"type": "home"}])["ok"] is False and api2.test_flow("A", [])["ok"] is False and api2.run_flow("A", "x")["ok"] is False,
           "«chạy thử kịch bản / bước API» cũng bị từ chối")
        ok("máy đang được điều khiển" in api2.ble_status("A")["status"], "hỏi trạng thái Bluetooth KHÔNG chen lệnh vào cổng của máy AI đang dùng", api2.ble_status("A"))
        r = api2.esp_chip("/dev/cu.A")
        ok(r.get("ok") is False and "điều khiển tay" in r["error"], "«Thông tin chip» trên board AI đang dùng → từ chối", r)
        closed.clear()
        r = api2.esp_chip("/dev/cu.B")
        ok(r.get("ok") is True and closed == ["B"] and "A" in gui.MGR.sessions, "«Thông tin chip» trên board KHÁC → chỉ đóng phiên rảnh, KHÔNG đóng phiên của máy AI đang dùng (trước đây đóng cả hai)", closed)
        gui.MGR.sessions["B"] = Sess("B"); closed.clear(); probed.clear()
        api2.esp_scan()
        for _ in range(100):
            if gui.MGR.scan_idle.is_set(): break
            REAL_SLEEP(0.02)
        ok(closed == ["B"] and probed == ["/dev/cu.B"] and gui.MGR.board_map.get("A") == "/dev/cu.A",
           "quét board: không đóng phiên, không dò cổng của máy AI đang điều khiển", (closed, probed))
        ok(api2.rescan()["ok"] is False and api2.probe_match("B")["ok"] is False, "«Quét lại» / «Dò máy» (đóng mọi phiên) bị hoãn khi có máy đang được điều khiển tay")
        gui.store.get_group = lambda gid: {"id": gid, "name": "G", "mode": "loop", "devices": ["A", "B"], "steps": [{"type": "home"}]}
        gui.Api._runnable = lambda self, g: None
        r = api2.machine_run("g", "A"); r2 = api2.group_run("g")
        ok(r["ok"] is False and r2["ok"] is False and gui.RUNNER.running_names() == [], "chạy máy / chạy nhóm có máy AI đang điều khiển → từ chối, không khởi động máy nào", (r, r2))
        gui.CLAIMS.release("A", "ai")
        with gui._Using("A") as why:
            ok(why is None and "giao diện app" in (gui.CLAIMS.acquire("A", "ai") or ""), "giao diện đang chạy thử trên máy A → AI xin máy bị từ chối")
        ok(gui.CLAIMS.names() == [] and api2.esp_chip("/dev/cu.A").get("ok") is True, "chạy thử xong thì máy được nhả")
    finally:
        (gui.MGR.board_map, gui.MGR.sessions, gui.esp.list_boards, gui.esp.probe, gui.esp.chip_info, gui.store.get_devices, gui._push, gui.store.get_group, gui.Api._runnable) = saved


def norm(s):
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _raises(fn, kind=Exception):
    try:
        fn()
    except kind:
        return True
    return False


if __name__ == "__main__":
    sys.exit(main())
