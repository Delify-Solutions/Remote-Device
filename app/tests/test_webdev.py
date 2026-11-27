#!/usr/bin/env python3
"""
Kiểm chế độ WEB dev (app/webdev.py) bằng Api giả — không cần phần cứng, không mở cửa sổ:
  • cần cookie cho MỌI thứ; đổi KHOÁ lấy cookie HttpOnly + SameSite=Strict; cookie là MÃ PHIÊN (không phải khoá), giữ qua lần khởi động lại trong app;
  • chặn tên miền lạ (DNS rebinding), Origin lạ / null, yêu cầu chéo trang (Sec-Fetch-Site), Content-Type không phải JSON;
  • /api chỉ gọi được hàm CÔNG KHAI của LỚP Api; JSON hỏng / quá lớn / độ dài lạ / Transfer-Encoding bị từ chối; lỗi trong hàm → {ok:false};
  • yêu cầu bị từ chối thì ĐÓNG kết nối (thân chưa đọc không thành yêu cầu kế tiếp); kết nối im lặng bị đóng; ký tự có dấu trong khoá/cookie không làm sập;
  • tệp tĩnh chỉ trong thư mục web, bỏ «_…», «.», «..», mã hoá %2e%2e, liên kết tượng trưng trỏ ra ngoài;
  • trang chính được chèn cầu nối trước app.js; SSE đẩy đúng chuỗi JS từ `push()`; gui._push đi qua web khi bật chế độ web;
  • khoá tạo ra đã 0600 ngay từ đầu, tệp cũ quyền rộng được siết lại; chế độ web không chụp màn hình máy đang làm đơn của khách;
  • `pip install` chỉ nhận gói app cần; `--web-port` sai → báo lỗi, không mở cổng nào.

    ./.venv/bin/python app/tests/test_webdev.py
"""
from __future__ import annotations
import http.client, json, os, shutil, socket, stat, sys, tempfile, threading, time, types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["IPF_NO_TELEGRAM"] = "1"            # app có thể đã cấu hình Telegram thật: kiểm thử không bao giờ bắn tin
import webdev

PASS = FAIL = 0


def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ✓", name)
    else:
        FAIL += 1; print("  ✗", name, "→", ctx if ctx is not None else "")


class FakeApi:
    def echo(self, a, b=0):
        return {"a": a, "b": b, "chu": "tiếng Việt"}

    def boom(self):
        raise RuntimeError("hỏng rồi")

    def _private(self):
        return "bí mật"

    secret_attr = "không phải hàm"


def main():
    tmp = tempfile.mkdtemp(prefix="webdev-")
    try:
        web = os.path.join(tmp, "web"); os.makedirs(os.path.join(web, "sub")); os.makedirs(os.path.join(web, "_backup"))
        open(os.path.join(web, "index.html"), "w", encoding="utf-8").write('<html><head></head><body><script src="vendor.js"></script>\n<script src="app.js"></script></body></html>')
        open(os.path.join(web, "app.js"), "w").write("// app")
        open(os.path.join(web, "sub", "x.js"), "w").write("var x=1;")
        open(os.path.join(web, "_mock.js"), "w").write("// mock")
        open(os.path.join(web, "_backup", "y.js"), "w").write("// y")
        open(os.path.join(tmp, "secret.txt"), "w").write("NGOAI THU MUC WEB")
        tokfile = os.path.join(tmp, "data", "webdev.json")

        print("== 1. Khoá ==")
        tok = webdev.load_or_create_token(tokfile)
        ok(len(tok) >= 24 and stat.S_IMODE(os.stat(tokfile).st_mode) == 0o600 and webdev.load_or_create_token(tokfile) == tok, "khoá đủ dài, lưu 0600, dùng lại ở lần chạy sau")
        modes = []
        real_open = os.open
        os.open = lambda path, flags, mode=0o777, **kw: (modes.append((os.path.basename(path), mode, bool(flags & os.O_EXCL))), real_open(path, flags, mode, **kw))[1]
        try:
            tok_b = webdev.load_or_create_token(os.path.join(tmp, "data", "khoa-moi.json"))
        finally:
            os.open = real_open
        mine = [m for m in modes if m[0].startswith("khoa-moi.json")]
        ok(len(tok_b) >= 24 and mine and all(m[1] == 0o600 and m[2] for m in mine) and os.listdir(os.path.join(tmp, "data")) .count("khoa-moi.json") == 1
           and not [f for f in os.listdir(os.path.join(tmp, "data")) if f.endswith(".tmp")],
           "tệp khoá được TẠO với quyền 0600 ngay từ đầu (O_EXCL), không có lúc nào ai cũng đọc được; không để lại tệp tạm", mine)
        loose = os.path.join(tmp, "data", "khoa-cu.json")
        open(loose, "w").write(json.dumps({"token": "k" * 30})); os.chmod(loose, 0o644)
        t_new = webdev.load_or_create_token(loose)
        ok(t_new != "k" * 30 and len(t_new) >= 24 and stat.S_IMODE(os.stat(loose).st_mode) == 0o600 and webdev.load_or_create_token(loose) == t_new,
           "tệp khoá cũ mà người khác đọc được (0644) → coi như khoá đã lộ: tạo khoá MỚI, lưu 0600, lần sau dùng lại khoá mới")
        open(loose, "w").write("[1, 2]")
        ok(len(webdev.load_or_create_token(loose)) >= 24 and stat.S_IMODE(os.stat(loose).st_mode) == 0o600, "tệp khoá hỏng (không phải dạng mong đợi) → tạo khoá mới, không sập")
        w = webdev.WebDev(FakeApi(), web, tok, port=47860)
        port = w.start()

        def req(method, path, body=None, headers=None, cookie=True, host=None, raw=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            h = {"Host": host or "127.0.0.1:%d" % port}
            if cookie:
                h["Cookie"] = "%s=%s" % (webdev.COOKIE, w.session)
            h.update(headers or {})
            data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
            if data is not None:
                h["Content-Type"] = "application/json"
            c.request(method, path, body=data, headers=h)
            r = c.getresponse(); b = r.read(); hd = dict(r.getheaders()); c.close()
            return r.status, b, hd

        for p in ("/", "/app.js", "/api/echo", "/events"):
            st, _, _ = req("GET" if p != "/api/echo" else "POST", p, body={"args": [1]} if p == "/api/echo" else None, cookie=False)
            ok(st == 401, "không có cookie → 401 (%s)" % p, st)
        ok(req("GET", "/?t=sai-khoa", cookie=False)[0] == 401, "đổi khoá SAI → 401")
        st, _, hd = req("GET", "/?t=" + tok, cookie=False)
        ck = hd.get("Set-Cookie", "")
        ok(st == 302 and hd.get("Location") == "/" and "HttpOnly" in ck and "SameSite=Strict" in ck and w.session in ck, "đổi khoá ĐÚNG → 302 về «/» + cookie HttpOnly, SameSite=Strict", (st, ck))
        ok(tok not in ck and w.session != tok and len(w.session) >= 32, "cookie là MÃ PHIÊN ngẫu nhiên — không chứa khoá")
        ok(req("GET", "/", cookie=False, headers={"Cookie": "%s=%s" % (webdev.COOKIE, tok)})[0] == 401, "đưa KHOÁ làm cookie → 401 (khoá chỉ dùng để đổi lấy mã phiên)")
        ok(req("GET", "/", cookie=True, headers={"Cookie": "%s=%s" % (webdev.COOKIE, "x" * len(w.session))})[0] == 401, "cookie sai → 401")
        # ký tự có dấu trong khoá / cookie: trước đây làm luồng xử lý ném TypeError (hmac trên str)
        c0 = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c0.putrequest("GET", "/?t=%C3%A9%C3%A0", skip_host=True); c0.putheader("Host", "127.0.0.1:%d" % port); c0.endheaders()
        st_a = c0.getresponse().status; c0.close()
        s0 = socket.create_connection(("127.0.0.1", port), timeout=5)
        s0.sendall(("GET / HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nCookie: %s=é-à-ỹ\r\nConnection: close\r\n\r\n" % (port, webdev.COOKIE)).encode("utf-8"))
        st_b = s0.recv(4096)[:12]; s0.close()
        ok(st_a == 401 and st_b.startswith(b"HTTP/1.1 401") and req("GET", "/")[0] == 200, "khoá / cookie có ký tự có dấu → 401 gọn gàng, máy chủ vẫn phục vụ tiếp", (st_a, st_b))
        ok(webdev.SESSION_ENV not in os.environ, "mã phiên KHÔNG nằm lại trong môi trường (tiến trình con như pip / esptool không thấy được)")
        os.environ[webdev.SESSION_ENV] = w.session                       # giả lập: tiến trình cũ trao mã phiên cho tiến trình mới qua os.execve
        w2 = webdev.WebDev(FakeApi(), web, tok, port=47890)
        ok(w2.session == w.session and webdev.SESSION_ENV not in os.environ, "khởi động lại trong app: nhận lại đúng mã phiên (trang đang mở không bị văng) rồi xoá khỏi môi trường")
        ok(webdev.WebDev(FakeApi(), web, tok, port=47890).session != w.session, "mở app mới hẳn (không ai trao mã phiên) → mã phiên mới")
        os.environ[webdev.SESSION_ENV] = "ngắn"
        ok(webdev.WebDev(FakeApi(), web, tok, port=47890).session not in ("ngắn", w.session) and webdev.SESSION_ENV not in os.environ, "mã phiên trong môi trường không hợp lệ → tạo mã mới")

        print("\n== 2. Tên miền / nguồn lạ ==")
        ok(req("GET", "/", host="ke-gian.example")[0] == 403 and req("GET", "/", host="127.0.0.1:1")[0] == 403, "Host lạ (DNS rebinding) → 403 dù có cookie")
        ok(req("GET", "/", host="localhost:%d" % port)[0] == 200, "Host «localhost» + đúng cổng → được")
        ok(req("POST", "/api/echo", {"args": [1]}, headers={"Origin": "https://trang-la.example"})[0] == 403, "POST từ trang web lạ (Origin khác) → 403")
        ok(req("POST", "/api/echo", {"args": [1]}, headers={"Origin": "http://127.0.0.1:%d" % port})[0] == 200, "POST từ chính trang này (Origin trùng) → được")
        ok(req("POST", "/api/echo", {"args": [1]}, host="ke-gian.example")[0] == 403, "POST với Host lạ → 403 (không chỉ GET)")
        ok(req("POST", "/api/echo", {"args": [1]}, headers={"Origin": "null"})[0] == 403, "POST với Origin «null» (trang trong khung cát / tệp cục bộ) → 403")
        ok(req("POST", "/api/echo", {"args": [1]}, headers={"Sec-Fetch-Site": "cross-site"})[0] == 403 and req("POST", "/api/echo", {"args": [1]}, headers={"Sec-Fetch-Site": "same-site"})[0] == 403
           and req("POST", "/api/echo", {"args": [1]}, headers={"Sec-Fetch-Site": "same-origin"})[0] == 200, "trình duyệt báo yêu cầu CHÉO trang (Sec-Fetch-Site) → 403; cùng trang → được")
        c1 = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c1.request("POST", "/api/echo", body=b'{"args":[1]}', headers={"Host": "127.0.0.1:%d" % port, "Cookie": "%s=%s" % (webdev.COOKIE, w.session), "Content-Type": "text/plain"})
        ok(c1.getresponse().status == 415, "POST không phải application/json (form / text/plain từ trang khác) → 415"); c1.close()
        st, _, hd = req("GET", "/")
        ok(hd.get("X-Content-Type-Options") == "nosniff" and hd.get("Referrer-Policy") == "no-referrer" and hd.get("X-Frame-Options") == "DENY"
           and "frame-ancestors 'none'" in hd.get("Content-Security-Policy", ""), "trang không cho nhúng vào khung, không lộ địa chỉ qua Referer, không đoán kiểu tệp", hd)

        print("\n== 3. /api ==")
        st, b, _ = req("POST", "/api/echo", {"args": ["x", 5]})
        r = json.loads(b)
        ok(st == 200 and r == {"ok": True, "result": {"a": "x", "b": 5, "chu": "tiếng Việt"}}, "gọi hàm công khai: tham số theo vị trí, kết quả JSON (giữ tiếng Việt)", r)
        r = json.loads(req("POST", "/api/boom", {"args": []})[1])
        ok(r["ok"] is False and "RuntimeError" in r["error"] and "hỏng rồi" in r["error"], "hàm ném lỗi → {ok:false, error} (không làm sập máy chủ)", r)
        ok(req("POST", "/api/_private", {"args": []})[0] == 404, "hàm bắt đầu bằng «_» → 404")
        st, b, _ = req("POST", "/api/secret_attr", {"args": []})
        ok(json.loads(b).get("ok") is False and "không có hàm" in json.loads(b)["error"], "thuộc tính không phải hàm → từ chối", b)
        ok(json.loads(req("POST", "/api/khong_co", {"args": []})[1])["ok"] is False, "tên lạ → từ chối")
        ok(req("POST", "/api/__class__", {"args": []})[0] == 404 and req("POST", "/api/echo/../boom", {"args": []})[0] == 404, "tên có dấu gạch dưới đôi / đường dẫn lạ → 404")
        ok(req("POST", "/api/echo", raw=b"{khong phai json")[0] == 400 and req("POST", "/api/echo", {"args": "khong phai list"})[0] == 400, "JSON hỏng / args không phải danh sách → 400")
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.putrequest("POST", "/api/echo", skip_host=True); c.putheader("Host", "127.0.0.1:%d" % port); c.putheader("Cookie", "%s=%s" % (webdev.COOKIE, w.session))
        c.putheader("Content-Type", "application/json"); c.putheader("Content-Length", str(webdev.MAX_BODY + 1)); c.endheaders()
        ok(c.getresponse().status == 413, "thân yêu cầu quá lớn → 413 ngay, không đọc vào bộ nhớ"); c.close()

        def raw_post(extra_headers, body=b""):
            """Gửi POST thô (tự đặt mọi tiêu đề) rồi đọc tới khi máy chủ đóng → (mã đầu tiên, số câu trả lời HTTP nhận được)."""
            s1 = socket.create_connection(("127.0.0.1", port), timeout=5)
            head = "POST /api/echo HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nCookie: %s=%s\r\nContent-Type: application/json\r\n" % (port, webdev.COOKIE, w.session)
            s1.sendall(head.encode() + extra_headers + b"\r\n" + body)
            buf = b""
            try:
                while True:
                    part = s1.recv(65536)
                    if not part:
                        break
                    buf += part
            except socket.timeout:
                buf += b"<<KHONG DONG>>"
            s1.close()
            return int(buf[9:12] or 0), buf.count(b"HTTP/1.1 "), buf
        for label, hdr in (("âm", b"Content-Length: -5\r\n"), ("có dấu gạch dưới «5_0»", b"Content-Length: 5_0\r\n"), ("không phải số", b"Content-Length: abc\r\n")):
            code, n, buf = raw_post(hdr)
            ok(code == 400 and n == 1 and b"KHONG DONG" not in buf, "Content-Length %s → 400 và đóng kết nối (không treo luồng chờ đọc)" % label, (code, n))
        code, n, buf = raw_post(b"Transfer-Encoding: chunked\r\n", b"5\r\nhello\r\n0\r\n\r\n")
        ok(code == 400 and n == 1 and b"KHONG DONG" not in buf, "Transfer-Encoding (thân kiểu chunked) → 400 và đóng, không chạy hàm nào", (code, n))

        # thân của yêu cầu BỊ TỪ CHỐI không được thành yêu cầu kế tiếp trên cùng kết nối (keep-alive)
        smuggled = ("GET /__devshim.js HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nCookie: %s=%s\r\n\r\n" % (port, webdev.COOKIE, w.session)).encode()
        s2 = socket.create_connection(("127.0.0.1", port), timeout=5)
        s2.sendall(("POST /api/khong_co HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nCookie: %s=%s\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n"
                    % (port, webdev.COOKIE, w.session, len(smuggled))).encode() + smuggled)
        buf = b""
        try:
            while True:
                part = s2.recv(65536)
                if not part:
                    break
                buf += part
        except socket.timeout:
            buf += b"<<KHONG DONG>>"
        s2.close()
        ok(buf.count(b"HTTP/1.1 ") == 1 and buf.startswith(b"HTTP/1.1 404") and b"window.pywebview" not in buf and b"KHONG DONG" not in buf,
           "POST bị từ chối kèm thân giả làm yêu cầu thứ hai → chỉ MỘT câu trả lời rồi đóng (không lệch yêu cầu)", buf[:60])
        s3 = socket.create_connection(("127.0.0.1", port), timeout=5)
        s3.sendall(("POST /api/echo HTTP/1.1\r\nHost: ke-gian.example\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n" % len(smuggled)).encode() + smuggled)
        buf = b""
        try:
            while True:
                part = s3.recv(65536)
                if not part:
                    break
                buf += part
        except socket.timeout:
            buf += b"<<KHONG DONG>>"
        s3.close()
        ok(buf.count(b"HTTP/1.1 ") == 1 and buf.startswith(b"HTTP/1.1 403") and b"KHONG DONG" not in buf, "…kể cả khi bị từ chối từ sớm (Host lạ, chưa đăng nhập)", buf[:60])
        code_g = socket.create_connection(("127.0.0.1", port), timeout=5)
        code_g.sendall(("GET / HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nCookie: %s=%s\r\nContent-Length: %d\r\n\r\n" % (port, webdev.COOKIE, w.session, len(smuggled))).encode() + smuggled)
        buf = b""
        try:
            while True:
                part = code_g.recv(65536)
                if not part:
                    break
                buf += part
        except socket.timeout:
            buf += b"<<KHONG DONG>>"
        code_g.close()
        ok(buf.count(b"HTTP/1.1 ") == 1 and buf.startswith(b"HTTP/1.1 400"), "GET kèm thân → 400 và đóng", buf[:40])

        def raw(request_bytes):
            """Gửi nguyên văn, đọc tới khi máy chủ đóng → (mã đầu tiên, số câu trả lời, toàn bộ)."""
            sk = socket.create_connection(("127.0.0.1", port), timeout=5)
            sk.sendall(request_bytes)
            out = b""
            try:
                while True:
                    part = sk.recv(65536)
                    if not part:
                        break
                    out += part
            except socket.timeout:
                out += b"<<KHONG DONG>>"
            sk.close()
            return int(out[9:12] or 0), out.count(b"HTTP/1.1 "), out
        H = "Host: 127.0.0.1:%d\r\n" % port
        CK = "Cookie: %s=%s\r\n" % (webdev.COOKIE, w.session)
        CL = "Content-Length: %d\r\n" % len(smuggled)
        code, n, out = raw(("POST /api/echo HTTP/1.1\r\n" + H + "Content-Type: application/json\r\n" + CL + "\r\n").encode() + smuggled)
        ok(code == 401 and n == 1 and b"KHONG DONG" not in out and b"window.pywebview" not in out, "POST chưa đăng nhập kèm thân giả → 401, MỘT câu trả lời, đóng", (code, n))
        code, n, out = raw(("POST /api/echo HTTP/1.1\r\n" + H + CK + "Content-Type: text/plain\r\n" + CL + "\r\n").encode() + smuggled)
        ok(code == 415 and n == 1 and b"KHONG DONG" not in out and b"window.pywebview" not in out, "POST sai Content-Type kèm thân giả → 415, MỘT câu trả lời, đóng", (code, n))
        code, n, out = raw(("POST /api/echo HTTP/1.1\r\n" + H + CK + "Content-Type: application/json\r\nTransfer-Encoding: chunked\r\nContent-Length: 13\r\n\r\n").encode() + b'{"args":[1]}\n')
        ok(code == 400 and n == 1 and b'"ok": true' not in out, "POST có CẢ Transfer-Encoding lẫn Content-Length hợp lệ → vẫn 400 (không chạy hàm)", (code, n, out[-80:]))
        code, n, out = raw(("GET / HTTP/1.1\r\n" + H + CK + "Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n").encode())
        ok(code == 400 and n == 1, "GET kèm Transfer-Encoding → 400 và đóng", (code, n))
        code, n, out = raw(("GET / HTTP/1.1\r\n" + H + "Host: ke-gian.example\r\n" + CK + "Connection: close\r\n\r\n").encode())
        ok(code == 403, "hai tiêu đề Host (một thật một lạ) → 403", code)
        body1 = b'{"args":[1]}'
        code, n, out = raw(("POST /api/echo HTTP/1.1\r\n" + H + CK + "Content-Type: application/json\r\nOrigin: http://127.0.0.1:%d\r\nOrigin: https://ke-gian.example\r\nContent-Length: %d\r\n\r\n" % (port, len(body1))).encode() + body1)
        ok(code == 403 and b'"ok": true' not in out, "hai tiêu đề Origin (một thật một lạ) → 403", code)
        code, n, out = raw(("POST /api/echo HTTP/1.1\r\n" + H + CK + "Content-Type: application/json\r\nContent-Length: %d\r\nContent-Length: %d\r\n\r\n" % (len(body1), len(body1) + len(smuggled))).encode() + body1 + smuggled)
        ok(code == 400 and n == 1 and b"window.pywebview" not in out, "hai tiêu đề Content-Length → 400, đóng (không đoán độ dài thân)", (code, n))

        fake = w.api
        fake.injected = lambda: "gắn thêm vào đối tượng"
        ok(req("POST", "/api/injected", {"args": []})[0] == 404, "hàm gắn thêm vào ĐỐI TƯỢNG (không có trong lớp Api) → không gọi được")

        print("\n== 4. Trang chính + tệp tĩnh ==")
        st, b, hd = req("GET", "/")
        html = b.decode()
        ok(st == 200 and html.index("__devshim.js") < html.index('src="app.js"') and "vendor.js" in html and "text/html" in hd.get("Content-Type", ""), "trang chính chèn cầu nối TRƯỚC app.js")
        st, b, hd = req("GET", "/__devshim.js")
        ok(st == 200 and b"window.pywebview" in b and b"EventSource" in b and b"/api/" in b and "javascript" in hd.get("Content-Type", ""), "tệp cầu nối: window.pywebview.api + EventSource")
        st, b, hd = req("GET", "/sub/x.js")
        ok(st == 200 and b == b"var x=1;" and "javascript" in hd.get("Content-Type", ""), "tệp tĩnh trong thư mục web → phục vụ đúng kiểu")
        bad = ["/_mock.js", "/_backup/y.js", "/../secret.txt", "/%2e%2e/secret.txt", "/sub/../../secret.txt", "/sub/..%2f..%2fsecret.txt", "/.git/config", "/sub", "/khong-co.js", "/%00"]
        res = {p: req("GET", p)[0] for p in bad}
        ok(all(v in (404, 400) for v in res.values()), "tệp «_…», thư mục, đường dẫn ra ngoài thư mục web (kể cả %2e%2e) → 404", res)
        ok(b"NGOAI" not in b"".join(req("GET", p)[1] for p in bad), "nội dung ngoài thư mục web không lọt ra")
        os.symlink(os.path.join(tmp, "secret.txt"), os.path.join(web, "lien-ket.txt"))
        os.symlink(tmp, os.path.join(web, "thu-muc-ngoai"))
        r1, r2 = req("GET", "/lien-ket.txt"), req("GET", "/thu-muc-ngoai/secret.txt")
        ok(r1[0] == 404 and r2[0] == 404 and b"NGOAI" not in r1[1] + r2[1], "liên kết tượng trưng (tệp / thư mục) trỏ RA NGOÀI thư mục web → 404", (r1[0], r2[0]))
        open(os.path.join(web, "sub", "that.js"), "w").write("var t=2;")
        os.symlink(os.path.join(web, "sub", "that.js"), os.path.join(web, "trong.js"))
        ok(req("GET", "/trong.js")[1] == b"var t=2;", "liên kết tượng trưng trỏ vào TRONG thư mục web vẫn phục vụ bình thường")
        ok(req("PUT", "/api/echo")[0] == 405 and req("DELETE", "/")[0] == 405, "PUT / DELETE → 405")

        print("\n== 5. Luồng sự kiện (SSE) ==")
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        s.sendall(("GET /events HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nCookie: %s=%s\r\n\r\n" % (port, webdev.COOKIE, w.session)).encode())
        buf = b""
        t0 = time.time()
        while b": ok" not in buf and time.time() - t0 < 3:
            buf += s.recv(4096)
        w.push('window.__espUpdate({"name":"Tiếng Việt"})')
        t0 = time.time()
        while b"__espUpdate" not in buf and time.time() - t0 < 3:
            buf += s.recv(4096)
        txt = buf.decode("utf-8", "ignore")
        line = next((l for l in txt.splitlines() if l.startswith("data: ")), "")
        ok("text/event-stream" in txt and json.loads(line[6:]) == 'window.__espUpdate({"name":"Tiếng Việt"})', "push(js) tới trang đúng chuỗi JS (JSON-hoá, giữ tiếng Việt)", txt[-200:])
        ok("X-Frame-Options: DENY" in txt and "nosniff" in txt, "luồng sự kiện cũng mang tiêu đề bảo mật")
        s.close()
        w.stop()

        print("\n== 5b. Kết nối im lặng bị đóng ==")
        old_idle = webdev.IDLE_TIMEOUT
        webdev.IDLE_TIMEOUT = 1
        w3 = webdev.WebDev(FakeApi(), web, tok, port=47870)
        p3 = w3.start()
        try:
            idle = socket.create_connection(("127.0.0.1", p3), timeout=6)
            t0 = time.time()
            try:
                got = idle.recv(100)
            except socket.timeout:
                got = b"<<VAN MO>>"
            idle.close()
            ok(got == b"" and time.time() - t0 < 5, "kết nối không gửi gì → máy chủ tự đóng sau thời gian chờ (không giữ luồng / tệp mãi)", (got, round(time.time() - t0, 1)))
        finally:
            w3.stop(); webdev.IDLE_TIMEOUT = old_idle
        ok('name === "then"' in webdev.SHIM and "r.status === 401" in webdev.SHIM, "cầu nối: `await api` không treo («then» = undefined); 401 báo rõ là phiên hết hạn")

        print("\n== 6. gui._push đi qua web khi bật chế độ web ==")
        if "webview" not in sys.modules:
            sys.modules["webview"] = types.SimpleNamespace(create_window=lambda *a, **k: None, start=lambda *a, **k: None)
        import gui, history
        gui.HISTORY = gui.RUNNER.history = history.History(None)      # không ghi lịch sử vào dữ liệu THẬT của người vận hành
        got = []
        old_web, old_win = gui.WEBDEV, gui.WINDOW
        try:
            gui.WEBDEV = types.SimpleNamespace(push=lambda js: got.append(js))
            gui.WINDOW = types.SimpleNamespace(evaluate_js=lambda js: got.append("CUA SO:" + js))
            gui._push("window.__x(1)")
        finally:
            gui.WEBDEV, gui.WINDOW = old_web, old_win
        ok(got == ["window.__x(1)"], "có WEBDEV → đẩy qua web, KHÔNG gọi cửa sổ pywebview", got)
        got.clear()
        try:
            gui.WEBDEV = None
            gui.WINDOW = types.SimpleNamespace(evaluate_js=lambda js: got.append("CUA SO:" + js))
            gui._push("window.__x(2)")
        finally:
            gui.WEBDEV, gui.WINDOW = old_web, old_win
        ok(got == ["CUA SO:window.__x(2)"], "không có WEBDEV → vẫn đẩy qua cửa sổ pywebview như cũ", got)

        print("\n== 7. Chế độ web: máy của khách (đang làm đơn / đang giữ chờ đối soát) ==")
        import threading as _th

        class Th:
            def __init__(self, alive): self.alive = alive
            def is_alive(self): return self.alive

        def worker(mode, alive, udid, port, gid, hold=None):
            return {"stop": _th.Event(), "abort": _th.Event(), "pause": _th.Event(), "paused": False, "thread": Th(alive), "udid": udid, "port": port,
                    "carry_hold": None, "group_id": gid, "group_name": gid, "script_id": None, "script_name": None, "mode": mode, "iter": 0,
                    "status": "x", "last_ok": None, "last_msg": None, "job_id": None, "job_ref": None, "pool": None,
                    "counts": {"done": 0, "failed": 0, "review": 0}, "hold": hold}
        old_udid, old_eyes, old_map, old_busy = gui.MGR._udid, gui.Eyes, gui.MGR.board_map, gui._busy
        old_getg, old_sess, saved_workers = gui.store.get_group, gui.MGR.session, dict(gui.RUNNER.workers)
        # bảng gán HIỆN TẠI (tên board → iPhone / cổng) — chính là thứ trang web sửa được; máy của khách được ghi theo lúc BẮT ĐẦU chạy
        UDID = {"M-API": "U-1", "M-HOLD": "U-2", "M-KB": "U-3"}
        PORT = {"M-API": "/dev/p1", "M-HOLD": "/dev/p2", "M-KB": "/dev/p3", "M-RANH": "/dev/p4"}
        shots, sessions = [], []

        class FakeEyes:
            def __init__(self, udid): self.udid = udid
            def screenshot(self):
                shots.append(self.udid)
                raise RuntimeError("máy giả: không có ảnh")
        gui.MGR._udid = lambda n: UDID.get(n)
        gui.MGR.board_map = PORT
        gui.Eyes = FakeEyes
        gui.MGR.session = lambda n: sessions.append(n) or (_ for _ in ()).throw(RuntimeError("máy giả"))
        gui._busy = lambda name=None: None
        gui.store.get_group = lambda gid: {"id": gid, "name": "Nhóm " + gid, "mode": "api" if gid == "ga" else "once", "devices": ["M-HOLD", "M-API", "M-RANH", "alias"],
                                           "scripts": [] if gid == "ga" else [{"id": "s", "name": "S", "steps": [{"type": "home"}], "mode": "once", "loops": 1}]}
        fake_web = types.SimpleNamespace(push=lambda js: None, session="S" * 40)
        try:
            gui.RUNNER.workers.clear()
            gui.RUNNER.workers.update({"M-API": worker("api", True, "U-1", "/dev/p1", "ga"), "M-HOLD": worker("api", False, "U-2", "/dev/p2", "ga", hold="đơn T-9 cần đối soát"),
                                       "M-KB": worker("loop", True, "U-3", "/dev/p3", "gk")})
            gui.WEBDEV = fake_web
            r_api, r_hold, r_kb = gui.Api().screenshot("M-API"), gui.Api().screenshot("M-HOLD"), gui.Api().screenshot("M-KB")
            ok(r_api["ok"] is False and "đơn của khách" in r_api["error"] and r_hold["ok"] is False and "U-1" not in shots and "U-2" not in shots,
               "chế độ web: KHÔNG chụp màn hình máy đang làm đơn của khách / đang giữ chờ đối soát (không đụng tới iPhone)", (r_api, shots))
            ok(shots == ["U-3"], "…máy chạy kịch bản thường của chủ thì vẫn chụp được như cũ", (r_kb, shots))

            # --- bảng gán bị SỬA sau khi máy đã bắt đầu: vẫn nhận ra theo máy thật ---
            shots.clear()
            UDID["M-HOLD"] = "rac"; UDID["alias"] = "U-2"            # như set_udid("M-HOLD","rác") rồi set_udid("alias", <iPhone của khách>)
            r1, r2 = gui.Api().screenshot("alias"), gui.Api().screenshot("M-HOLD")
            ok(r1["ok"] is False and r2["ok"] is False and shots == [], "gán iPhone của khách sang tên board khác (kể cả đã gán rác cho tên cũ) → vẫn không chụp được", (r1, r2, shots))
            del UDID["M-HOLD"]                                        # như delete_device("M-HOLD")
            ok(gui.Api().screenshot("alias")["ok"] is False and shots == [], "xoá máy khỏi bảng rồi dùng tên khác → vẫn không chụp được")
            UDID["alias2"] = "U-1"
            ok(gui.Api().screenshot("alias2")["ok"] is False and shots == [], "…máy đang CHẠY đơn cũng vậy (tên khác trỏ vào cùng iPhone)")
            # UDID viết KHÁC ĐI nhưng vẫn là cùng một iPhone (thư viện chụp bỏ qua dấu gạch / hoa-thường)
            gui.RUNNER.workers["M-HOLD"]["udid"] = "00008030ABCDEF12"
            for variant in ("00008030-ABCDEF12", "00008030abcdef12", "0000-8030-abcd-ef12"):
                UDID["bien-the"] = variant
                rv = gui.Api().screenshot("bien-the")
                if rv["ok"] is not False or "đơn của khách" not in rv["error"] or shots:
                    ok(False, "UDID viết khác đi (%s) vẫn phải bị nhận ra là iPhone của khách" % variant, (rv, shots)); break
            else:
                ok(True, "UDID viết khác đi (thêm dấu gạch, chữ thường) vẫn bị nhận ra là iPhone của khách → không chụp")
            gui.RUNNER.workers["M-HOLD"]["udid"] = "U-2"
            # PHIÊN ĐÃ MỞ SẴN cho một tên đang trỏ vào iPhone của khách, dù bảng gán hiện tại nói khác (bảng bị đổi lại sau khi mở phiên)
            UDID["phien-cu"] = "U-7"; PORT["phien-cu"] = "/dev/p7"
            gui.MGR.sessions["phien-cu"] = types.SimpleNamespace(e=types.SimpleNamespace(udid="U-2"), h=types.SimpleNamespace(port="/dev/p7"), close=lambda: None)
            r_shot, r_step2 = gui.Api().screenshot("phien-cu"), gui.Api().run_step("phien-cu", {"type": "assert_text", "text": "654321"})
            ok(r_shot["ok"] is False and r_step2["ok"] is False and shots == [] and sessions == [],
               "tên có phiên mở sẵn đang nhìn vào iPhone của khách (bảng gán đã bị đổi lại) → không chụp, không «kiểm chữ» được", (r_shot, r_step2))
            gui.MGR.sessions.pop("phien-cu", None)
            # bấm / thử bước: tên khác trỏ vào cùng iPhone (đọc chữ màn hình khách) hoặc cùng board (bấm lên máy khách)
            UDID["M-RANH"] = "U-2"
            r_step = gui.Api().run_step("M-RANH", {"type": "assert_text", "text": "OTP"})
            ok(r_step["ok"] is False and "cùng iPhone" in r_step["msg"] and sessions == [], "tên khác gán CÙNG iPhone → không thử bước được («kiểm chữ» sẽ dò màn hình của khách)", r_step)
            UDID["M-RANH"] = "U-9"; PORT["cung-board"] = "/dev/p2"
            r_step = gui.Api().run_step("cung-board", {"type": "tap", "x": 1, "y": 1})
            ok(r_step["ok"] is False and sessions == [], "tên khác trỏ vào CÙNG board với máy đang giữ → không bấm được", r_step)
            r_step, r_flow, r_apis = gui.Api().run_step("M-HOLD", {"type": "assert_text", "text": "OTP"}), gui.Api().test_flow("M-HOLD", [{"type": "home"}]), gui.Api().test_api_steps("M-HOLD", [{"type": "home"}])
            ok(r_step["ok"] is False and "CHỜ NGƯỜI KIỂM TRA" in r_step["msg"] and r_flow["ok"] is False and r_apis["ok"] is False and sessions == [] and gui.CLAIMS.names() == [],
               "chế độ web: không thử bước / kịch bản lên máy đang giữ chờ đối soát", (r_step, sessions))
            r_ok = gui.Api().run_step("M-RANH", {"type": "home"})
            ok(sessions == ["M-RANH"], "máy rảnh, không trùng máy nào của khách → vẫn thử bước bình thường", (r_ok, sessions))

            # --- chạy kịch bản lên tên khác trỏ vào iPhone của khách: bị bỏ qua ---
            started = []
            real_start_group, real_start_machine = gui.RUNNER.start_group, gui.RUNNER.start_machine
            gui.RUNNER.start_group = lambda g, names=None, sc=None: started.extend(names or []) or list(names or [])
            gui.RUNNER.start_machine = lambda n, g, sc=None: started.append(n) or True
            real_runnable = gui.Api._runnable
            gui.Api._runnable = lambda self, g, script=None: None            # coi như nhóm đủ điều kiện chạy (pool, bước…)
            try:
                r_grp = gui.Api().group_run("gk", ["alias", "M-RANH"], "s")
                r_one = gui.Api().machine_run("gk", "alias", "s")
                r_again = gui.Api().machine_run("ga", "M-HOLD")
                r_grp2 = gui.Api().group_run("ga", ["M-HOLD"])
            finally:
                gui.RUNNER.start_group, gui.RUNNER.start_machine, gui.Api._runnable = real_start_group, real_start_machine, real_runnable
            ok(started == ["M-RANH"] and "alias" in r_grp["held"] and r_one["ok"] is False, "chạy kịch bản: tên trỏ vào iPhone của khách bị bỏ qua (báo trong held), máy khác vẫn chạy", (r_grp, r_one, started))
            ok(r_again["ok"] is False and "CHỜ NGƯỜI KIỂM TRA" in r_again["error"] and r_grp2.get("held", {}).get("M-HOLD"), "chế độ web: «Chạy lại» máy đang giữ cũng bị từ chối (đó cũng là gỡ giữ)", (r_again, r_grp2))

            # --- lời xác nhận / dừng / xoá nhóm ---
            r_ack, r_stop, r_del = gui.Api().machine_ack("M-HOLD"), gui.Api().machine_stop("M-HOLD"), gui.Api().group_delete("ga")
            gui.Api().group_stop("ga"); gui.Api().stop_all()
            ok(r_ack["ok"] is False and "cửa sổ" in r_ack["error"] and r_stop["ok"] is False and r_del["ok"] is False and gui.RUNNER.hold_reason("M-HOLD") == "đơn T-9 cần đối soát",
               "chế độ web: «Đã kiểm tra xong», Dừng, Dừng nhóm, Dừng tất cả, XOÁ NHÓM — không cái nào gỡ được trạng thái giữ", (r_ack, r_stop, r_del))
            ok(gui.RUNNER.workers["M-API"]["stop"].is_set(), "…còn máy đang chạy thì vẫn dừng được")

            # --- cổng chặn: khi có máy của khách, chỉ danh sách lệnh an toàn được gọi ---
            public = [n for n in dir(gui.Api) if not n.startswith("_") and callable(getattr(gui.Api, n))]
            blocked = [n for n in public if gui._web_gate(n)]
            must_block = {"set_udid", "delete_device", "esp_flash", "esp_erase", "esp_chip", "probe_match", "restart_app", "group_delete", "ios_pair", "ios_enable_devmode",
                          "ios_reveal_devmode", "ios_mount", "ios_check", "board_restart", "board_disconnect_bt", "gateway_save", "ai_set_enabled", "ai_renew_token",
                          "sys_install_pip", "sys_install_tool", "save_flow", "delete_flow", "run_flow", "run_flow_multi"}
            ok(must_block <= set(blocked), "có máy của khách: đổi bảng gán / xoá máy / nạp-xoá board / dò máy / khởi động lại / xoá nhóm / đổi gateway-AI… đều bị khoá", sorted(must_block - set(blocked)))
            ok(set(public) - set(blocked) == set(gui.WEB_SAFE_WITH_CUSTOMERS) & set(public) and gui.WEB_SAFE_WITH_CUSTOMERS <= set(public),
               "mặc định là KHOÁ: mọi lệnh công khai ngoài danh sách an toàn đều bị từ chối (lệnh mới thêm sau này cũng vậy); danh sách an toàn không có tên lạ",
               (sorted(set(public) - set(blocked) - set(gui.WEB_SAFE_WITH_CUSTOMERS)), sorted(gui.WEB_SAFE_WITH_CUSTOMERS - set(public))))
            ok(gui._web_gate("lenh_moi_chua_ai_xep_loai") and "set_udid" in gui._web_gate("set_udid") and "M-HOLD" in gui._web_gate("set_udid"), "câu từ chối nêu rõ lệnh và máy nào đang vướng")
            # qua đúng đường HTTP của chế độ web
            calls = []

            class GateApi:
                def set_udid(self, name, udid): calls.append(("set_udid", name)); return {"ok": True}
                def list_devices(self): calls.append(("list_devices",)); return []
            wg = webdev.WebDev(GateApi(), web, tok, port=47875, gate=gui._web_gate)
            pg = wg.start()
            try:
                def post(method, args):
                    cg = http.client.HTTPConnection("127.0.0.1", pg, timeout=5)
                    cg.request("POST", "/api/" + method, body=json.dumps({"args": args}).encode(),
                               headers={"Host": "127.0.0.1:%d" % pg, "Cookie": "%s=%s" % (webdev.COOKIE, wg.session), "Content-Type": "application/json"})
                    out = json.loads(cg.getresponse().read()); cg.close()
                    return out
                a, b = post("set_udid", ["alias", "U-2"]), post("list_devices", [])
                ok(a["ok"] is False and "set_udid" in a["error"] and b["ok"] is True and calls == [("list_devices",)], "qua HTTP: lệnh bị khoá KHÔNG được chạy (hàm không hề được gọi); lệnh an toàn vẫn chạy", (a, calls))
                wg.gate = lambda m: (_ for _ in ()).throw(RuntimeError("cổng chặn hỏng"))
                c0 = post("list_devices", [])
                ok(c0["ok"] is False and calls == [("list_devices",)], "cổng chặn tự nó lỗi → TỪ CHỐI (không «cho qua khi lỗi»)", c0)
            finally:
                wg.stop()

            # --- khởi động lại: mã phiên chỉ trao cho tiến trình mới ---
            execs = []
            real_execve, real_timer = gui.os.execve, gui.threading.Timer
            gui.os.execve = lambda exe, argv, env: execs.append(env)
            gui.threading.Timer = lambda delay, fn: types.SimpleNamespace(start=fn)
            try:
                r_rs = gui.Api().restart_app()
                ok(r_rs["ok"] is False and execs == [], "chế độ web: không khởi động lại app khi còn máy làm đơn / đang giữ (khởi động lại là mất trạng thái giữ)", r_rs)
                gui.RUNNER.workers.clear(); gui.RUNNER.workers["M-KB"] = worker("loop", True, "U-3", "/dev/p3", "gk")
                ok([n for n in public if gui._web_gate(n)] == [], "không còn máy của khách → không lệnh nào bị khoá")
                r_rs = gui.Api().restart_app()
                ok(r_rs["ok"] is True and len(execs) == 1 and execs[0].get(webdev.SESSION_ENV) == "S" * 40 and webdev.SESSION_ENV not in os.environ,
                   "không còn máy của khách → khởi động lại được; mã phiên chỉ đưa cho tiến trình mới (os.execve), không để trong môi trường chung", (r_rs, len(execs)))
            finally:
                gui.os.execve, gui.threading.Timer = real_execve, real_timer

            # --- đổi bảng gán: không gán iPhone của khách cho tên khác, không đổi / xoá máy của khách (cả khi cổng chặn không có mặt) ---
            ups, dels, closed = [], [], []
            real_up, real_delete = gui.store.upsert_device, gui.store.delete_device
            gui.store.upsert_device = lambda n, u, label=None: ups.append((n, u))
            gui.store.delete_device = lambda n: dels.append(n)
            gui.RUNNER.workers.clear()
            gui.RUNNER.workers.update({"M-API": worker("api", True, "U-1", "/dev/p1", "ga"), "M-HOLD": worker("api", False, "U-2", "/dev/p2", "ga", hold="đơn T-9 cần đối soát")})
            UDID.clear(); UDID.update({"M-API": "U-1", "M-HOLD": "U-2", "M-RANH": "U-9"})
            gui.MGR.sessions["M-RANH"] = types.SimpleNamespace(e=types.SimpleNamespace(udid="U-9"), h=types.SimpleNamespace(port="/dev/p4"), close=lambda: closed.append("M-RANH"))
            try:
                a1, a2, a3 = gui.Api().set_udid("alias", "u-2"), gui.Api().set_udid("M-HOLD", "rac"), gui.Api().delete_device("M-HOLD")
                ok(a1["ok"] is False and a2["ok"] is False and a3["ok"] is False and ups == [] and dels == [],
                   "gán iPhone của khách cho tên khác / gán lại / xoá máy của khách → từ chối ngay ở chính các lệnh đó", (a1, a2, a3))
                a4 = gui.Api().set_udid("M-RANH", "U-8")
                ok(a4["ok"] is True and ups == [("M-RANH", "U-8")] and closed == ["M-RANH"] and "M-RANH" not in gui.MGR.sessions,
                   "gán lại iPhone cho máy rảnh: được, và PHIÊN CŨ (đang nhìn iPhone cũ) bị đóng — lần sau mở theo bảng gán mới", (a4, ups, closed))
            finally:
                gui.store.upsert_device, gui.store.delete_device = real_up, real_delete
                gui.MGR.sessions.pop("M-RANH", None)

            # --- chế độ web KHÔNG chạy đơn của khách (gốc của mọi thứ ở trên: không có đơn thì không có «máy của khách») ---
            gui.RUNNER.workers.clear()
            real_allow, real_runnable2 = gui.RUNNER.allow_api, gui.Api._runnable
            gui.Api._runnable = lambda self, g, script=None: None
            gui.RUNNER._run_api = lambda name, group, w: None
            gui.RUNNER._ensure_heartbeat = lambda: None
            try:
                gui.RUNNER.allow_api = False                      # như gui.main đặt khi chạy --web
                r_g, r_m = gui.Api().group_run("ga"), gui.Api().machine_run("ga", "M-RANH")
                direct = gui.RUNNER.start_machine("M-RANH", {"id": "ga", "name": "Nhóm nhận đơn", "mode": "api", "devices": ["M-RANH"], "api": {"pool": "p"}})
                ok(r_g["ok"] is False and "cửa sổ" in r_g["error"] and r_m["ok"] is False and direct is False and gui.RUNNER.workers == {} and gui.RUNNER.customers() == [],
                   "chế độ web: nhóm nhận đơn KHÔNG chạy được (giao diện, từng máy, lẫn gọi thẳng bộ chạy) → không bao giờ có máy của khách trong bản web", (r_g, direct))
                r_s = gui.Api().group_run("gk", ["M-RANH"], "s")
                ok(r_s["ok"] is True and r_s["started"] == ["M-RANH"], "…kịch bản thường thì vẫn chạy ở chế độ web", r_s)
                gui.RUNNER.stop_all(True)
                gui.RUNNER.workers["M-RANH"]["thread"].join(5)
                gui.RUNNER.workers.clear()
                gui.RUNNER.allow_api = True
                ok(gui.RUNNER.start_machine("M-RANH", {"id": "ga", "name": "Nhóm nhận đơn", "mode": "api", "devices": ["M-RANH"], "api": {"pool": "p"}}) is True,
                   "app dạng cửa sổ (allow_api): nhóm nhận đơn chạy bình thường")
                gui.RUNNER.workers["M-RANH"]["thread"].join(5)
            finally:
                gui.RUNNER.allow_api, gui.Api._runnable = real_allow, real_runnable2
                del gui.RUNNER._run_api, gui.RUNNER._ensure_heartbeat

            # --- cửa sổ app thật: người vận hành không bị chặn ---
            gui.RUNNER.workers.clear()
            gui.RUNNER.workers.update({"M-API": worker("api", True, "U-1", "/dev/p1", "ga"), "M-HOLD": worker("api", False, "U-2", "/dev/p2", "ga", hold="đơn T-9 cần đối soát")})
            UDID.update({"M-API": "U-1", "M-HOLD": "U-2"})
            gui.WEBDEV = None
            shots.clear()
            gui.Api().screenshot("M-API"); gui.Api().screenshot("M-HOLD")
            r_stop, r_ack = gui.Api().machine_stop("M-HOLD"), gui.Api().machine_ack("M-HOLD")
            ok(shots == ["U-1", "U-2"] and r_stop["ok"] is False and r_ack["ok"] is True and gui.RUNNER.hold_reason("M-HOLD") is None,
               "cửa sổ app thật (không --web): người vận hành vẫn xem được; Dừng không gỡ giữ, «Đã kiểm tra xong» mới gỡ", (shots, r_stop, r_ack))
        finally:
            gui.WEBDEV = old_web
            gui.MGR._udid, gui.Eyes, gui.MGR.board_map, gui._busy = old_udid, old_eyes, old_map, old_busy
            gui.store.get_group, gui.MGR.session = old_getg, old_sess
            gui.RUNNER.workers.clear(); gui.RUNNER.workers.update(saved_workers)

        # --- khoá gateway: không tự gửi sang máy chủ khác; bản web không đổi cấu hình gateway ---
        saved_cfg = {"gateway_url": "https://gw.that.example/api", "gateway_key": "KHOA-THAT"}
        writes, pings = [], []
        real_get, real_save, real_test = gui.store.get_settings, gui.store.save_settings, gui.Api.gateway_test
        gui.store.get_settings = lambda: dict(saved_cfg)
        gui.store.save_settings = lambda patch: (writes.append(dict(patch)), saved_cfg.update(patch))[1]
        gui.Api.gateway_test = lambda self: pings.append(saved_cfg["gateway_url"]) or {"ok": True}
        try:
            gui.WEBDEV = types.SimpleNamespace(push=lambda js: None, session="S" * 40)
            r_web = gui.Api().gateway_save("https://ke-gian.example", "")
            r_web2 = gui.Api().gateway_save("https://ke-gian.example", "khoa-cua-ke-gian")
            ok(r_web["ok"] is False and r_web2["ok"] is False and "cửa sổ" in r_web["error"] and writes == [] and pings == [] and saved_cfg["gateway_url"] == "https://gw.that.example/api",
               "chế độ web: KHÔNG đổi được cấu hình gateway (không ghi, không gọi thử tới địa chỉ mới — khoá đang lưu không bị gửi đi đâu)", (r_web, writes, pings))
            gui.WEBDEV = None
            r1 = gui.Api().gateway_save("https://ke-gian.example/api", "")
            r2 = gui.Api().gateway_save("http://gw.that.example/api", None)
            r3 = gui.Api().gateway_save("https://gw.that.example:8443/api", "   ")
            ok(r1["ok"] is False and r2["ok"] is False and r3["ok"] is False and "NHẬP LẠI khoá" in r1["error"] and writes == [] and pings == [],
               "app cửa sổ: đổi sang MÁY CHỦ khác (tên miền / giao thức / cổng khác) mà để trống khoá → từ chối, khoá cũ không bị gửi sang máy chủ mới", (r1, r2, r3, pings))
            r4 = gui.Api().gateway_save("https://GW.that.example/api/v2/", "")
            ok(r4["ok"] is True and writes == [{"gateway_url": "https://GW.that.example/api/v2"}] and saved_cfg["gateway_key"] == "KHOA-THAT",
               "cùng máy chủ, chỉ đổi đường dẫn → giữ khoá đang lưu như cũ", (r4, writes))
            writes.clear(); pings.clear()
            r5 = gui.Api().gateway_save("https://gw.moi.example", " KHOA-MOI ")
            ok(r5["ok"] is True and writes == [{"gateway_url": "https://gw.moi.example", "gateway_key": "KHOA-MOI"}] and pings == ["https://gw.moi.example"],
               "đổi máy chủ KÈM khoá mới → lưu cả hai rồi mới gọi thử", (r5, writes, pings))
            saved_cfg.clear(); saved_cfg.update({"gateway_url": "", "gateway_key": ""}); writes.clear()
            ok(gui.Api().gateway_save("https://gw.dau-tien.example", "")["ok"] is True and writes == [{"gateway_url": "https://gw.dau-tien.example"}],
               "chưa từng lưu khoá nào → đặt địa chỉ lần đầu không bị chặn (không có khoá nào để lộ)")
        finally:
            gui.WEBDEV = old_web
            gui.store.get_settings, gui.store.save_settings, gui.Api.gateway_test = real_get, real_save, real_test

        import sysinfo
        ran = []
        old_run = sysinfo._run
        sysinfo._run = lambda cmd, timeout=0: (ran.append(cmd), (0, "ok"))[1]
        try:
            bad = [["--index-url", "http://ke-gian.example/simple", "pyserial"], ["git+https://ke-gian.example/x.git"], ["pyserial; rm -rf ~"], [{"a": 1}], "goi-la"]
            res = [sysinfo.pip_install(b) for b in bad]
            ok(all(r["ok"] is False for r in res) and ran == [], "pip: tên lạ / tuỳ chọn của pip / địa chỉ git → từ chối, KHÔNG chạy pip", (res[0], ran))
            ok(sysinfo.pip_install(["pyserial", "numpy"])["ok"] is True and ran and ran[0][-2:] == ["pyserial", "numpy"], "pip: gói app cần thì cài bình thường", ran)
        finally:
            sysinfo._run = old_run

        started = []
        old_srv, old_api = gui.control.AppServer, gui.Api
        gui.control.AppServer = lambda *a, **k: started.append("control") or types.SimpleNamespace(start=lambda p: True, stop=lambda: None, token="")
        try:
            codes = [gui.main(["--web", "--web-port", v]) for v in ("abc", "0", "70000", "-1", "80", "²")] + [gui.main(["--web", "--web-port"])]
        finally:
            gui.control.AppServer, gui.Api = old_srv, old_api
        ok(codes == [2] * 7 and started == [] and gui.WEBDEV is old_web, "--web-port sai (chữ, 0, quá lớn, âm, cổng hệ thống, chữ số lạ «²», thiếu số) → báo lỗi, KHÔNG mở cổng nào", (codes, started))

        # chạy --web: cờ «không chạy đơn của khách» phải được đặt TRƯỚC khi cầu nối AI (MCP) mở cổng — AI gọi «chạy nhóm» sớm cũng không lọt
        order = []
        real_allow = gui.RUNNER.allow_api
        real_srv, real_webdev_cls, real_sleep, real_settings = gui.control.AppServer, webdev.WebDev, gui.time.sleep, gui.store.get_settings
        real_presence = gui._start_presence
        # main() thật sẽ chạy luồng TỰ BÁO GATEWAY (gửi dữ liệu tới gateway đang cấu hình trên máy này) — bài thử không bao giờ được để nó chạy thật
        gui._start_presence = lambda: order.append(("luồng tự báo gateway", gui.RUNNER.allow_api))
        gui.RUNNER.allow_api = True
        gui.store.get_settings = lambda: {"ai_enabled": True, "ai_port": 47995}
        gui.control.AppServer = lambda *a, **k: types.SimpleNamespace(start=lambda p: order.append(("cầu nối AI mở cổng", gui.RUNNER.allow_api)) or True, stop=lambda: None, token="")
        webdev.WebDev = lambda *a, **k: types.SimpleNamespace(start=lambda: order.append(("web mở cổng", gui.RUNNER.allow_api)) or 47822, stop=lambda: None, url=lambda: "http://127.0.0.1:47822/?t=***", session="x")

        def stop_loop(sec):
            raise KeyboardInterrupt()
        gui.time.sleep = stop_loop
        try:
            gui.main(["--web"])
            ok(order == [("cầu nối AI mở cổng", False), ("web mở cổng", False), ("luồng tự báo gateway", False)] and gui.RUNNER.allow_api is False,
               "chạy --web: «không chạy đơn của khách» có hiệu lực từ TRƯỚC khi cầu nối AI, trang web mở cổng và luồng tự báo gateway chạy", order)
        finally:
            gui.control.AppServer, webdev.WebDev, gui.time.sleep, gui.store.get_settings = real_srv, real_webdev_cls, real_sleep, real_settings
            gui._start_presence = real_presence
            gui.RUNNER.allow_api = real_allow
            gui.WEBDEV = old_web
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
