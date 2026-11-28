"""
webdev.py — chạy giao diện của app như một TRANG WEB trên máy này (chế độ dev: `python app/gui.py --web`), thay cho cửa sổ pywebview.

Cùng một tiến trình, cùng cổng serial, cùng cầu nối MCP — chỉ khác đường đi giữa giao diện và phần xử lý:
  • `window.pywebview.api.<hàm>(…)`  →  POST /api/<hàm>  (JSON {"args": […]}) → gọi đúng hàm của lớp Api;
  • `_push(js)` (phần xử lý đẩy cập nhật về giao diện)  →  luồng sự kiện SSE `/events`, trang tự chạy chuỗi JS đó.
Mở bằng trình duyệt thường (hoặc trình duyệt nhúng của Orca) để thao tác / chụp màn hình giao diện từ xa.

AN TOÀN (giao diện này làm được MỌI việc như cửa sổ thật: chạy đơn thật, nạp / xoá board…):
  • chỉ nghe 127.0.0.1; yêu cầu có tên miền `127.0.0.1` / `localhost` (chống DNS rebinding);
  • cần khoá: mở `http://127.0.0.1:<cổng>/?t=<khoá>` một lần để nhận cookie (HttpOnly, SameSite=Strict); khoá lưu ở app/data/webdev.json (0600, ngoài git);
    cookie KHÔNG phải là khoá: nó là mã phiên ngẫu nhiên, đổi mỗi lần mở app (giữ qua nút «Khởi động lại» trong app; không nằm trong môi trường của tiến trình con)
    → lộ cookie cũng không lộ khoá, và hết hạn khi tắt app;
  • POST /api chỉ nhận từ chính trang này (Origin trùng, Content-Type JSON, không phải yêu cầu chéo trang) và chỉ gọi được hàm CÔNG KHAI của lớp Api;
    tệp tĩnh chỉ phục vụ trong thư mục web, bỏ qua mọi tệp / thư mục bắt đầu bằng «_»;
  • yêu cầu bị từ chối thì ĐÓNG kết nối (không để phần thân chưa đọc bị hiểu thành yêu cầu kế tiếp); không nhận Transfer-Encoding; kết nối im quá 30 giây bị đóng;
  • trang không cho nhúng vào khung (frame-ancestors 'none'), không lộ địa chỉ qua Referer;
  • chế độ web KHÔNG chạy đơn của khách (gui.main đặt Runner.allow_api = False): trong tiến trình này không có «máy của khách». Lớp chặn dự phòng nếu vẫn có:
    `gate` (gui._web_gate) chỉ cho gọi một danh sách lệnh an toàn; chụp / bấm / thử bước so theo máy thật của phiên đang dùng; «Đã kiểm tra xong» chỉ nhận ở
    app dạng cửa sổ.
"""
from __future__ import annotations
import hmac, http.server, json, mimetypes, os, queue, re, secrets, socketserver, threading, urllib.parse

MAX_BODY = 1 << 20
COOKIE = "ipf_dev"
SESSION_ENV = "IPF_WEB_SESSION"          # mã phiên được trao cho tiến trình mới qua `os.execve` (nút «Khởi động lại») để trang đang mở không bị văng ra
IDLE_TIMEOUT = 30                        # giây: kết nối không gửi gì → đóng (không để kết nối treo chiếm hết luồng / tệp)
SEC_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
               "Content-Security-Policy": "frame-ancestors 'none'"}


def _same(a: str, b: str) -> bool:
    """So sánh hằng-thời-gian, chịu được ký tự không phải ASCII (hmac.compare_digest trên str ném TypeError)."""
    return hmac.compare_digest(a.encode("utf-8", "surrogatepass"), b.encode("utf-8", "surrogatepass"))
SHIM = r"""(function () {
  // Cầu nối thay cho pywebview: window.pywebview.api.<hàm>(...) → POST /api/<hàm>
  const call = (name, args) => fetch("/api/" + name, {
    method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json"}, body: JSON.stringify({args: args})
  }).then(r => {
    if (r.status === 401) throw new Error("phiên web đã hết — mở lại địa chỉ có khoá (?t=…) in ra lúc chạy app");
    const ct = r.headers.get("Content-Type") || "";
    if (!ct.includes("application/json")) throw new Error("máy chủ trả lời lạ (HTTP " + r.status + ")");
    return r.json();
  }).then(d => { if (!d.ok) throw new Error(d.error || "lỗi không rõ"); return d.result; });
  const local = {
    // F5 trong chế độ web chỉ cần tải lại trang (không có cầu nối nào để mất)
    reload_ui: () => { setTimeout(() => location.reload(), 150); return Promise.resolve({ok: true}); },
  };
  // «then» phải là undefined: nếu không, `await window.pywebview.api` coi đối tượng này là Promise và treo mãi
  window.pywebview = {api: new Proxy({}, {get: (_, name) => (typeof name !== "string" || name === "then") ? undefined : (name in local) ? local[name] : ((...a) => call(name, a))})};
  // Phần xử lý đẩy cập nhật về giao diện (window.__espUpdate, __runLog…) qua SSE; mất kết nối thì trình duyệt tự nối lại.
  const es = new EventSource("/events");
  es.onmessage = (e) => { try { (0, eval)(JSON.parse(e.data)); } catch (err) { console.error("push", err); } };
})();
"""


def _owner_only(path: str) -> bool:
    """Tệp chỉ chủ máy đọc được? Windows KHÔNG có bit quyền kiểu POSIX: st_mode luôn báo 0666 và quyền 0600 lúc tạo tệp cũng không có tác
    dụng — coi bit đó là «đã lộ» thì khoá bị tạo lại ở MỌI lần mở app mà tệp mới vẫn y quyền cũ (không an toàn hơn chút nào). Trên Windows
    quyền đọc tệp do ACL của thư mục cài quyết định: bộ cài đặt app trong %LOCALAPPDATA% (chỉ người dùng đó đọc được); cài tay bằng
    setup.bat vào thư mục dùng chung thì tài khoản khác trên CÙNG máy đọc được khoá (máy chủ chỉ nghe ở 127.0.0.1)."""
    return os.name == "nt" or not (os.stat(path).st_mode & 0o077)


def load_or_create_token(path: str) -> str:
    """Khoá đăng nhập của chế độ web, lưu ở `path` với quyền 0600 NGAY TỪ LÚC TẠO (không có khoảnh khắc ai cũng đọc được).
    Tệp cũ mà người khác đọc được (quyền rộng hơn 0600) thì KHÔNG dùng lại khoá trong đó — tạo khoá mới."""
    try:
        with open(path, encoding="utf-8") as f:
            t = (json.load(f) or {}).get("token")
        if isinstance(t, str) and len(t) >= 24 and _owner_only(path):
            return t                                  # tệp chỉ mình đọc được → dùng lại; tệp quyền rộng hơn coi như khoá đã lộ → tạo khoá mới ở dưới
    except (OSError, ValueError, AttributeError):
        pass
    t = secrets.token_urlsafe(24)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = "%s.%s.tmp" % (path, secrets.token_hex(4))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"token": t}, f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return t


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def handle_error(self, request, client_address):
        """Phía trình duyệt tự ngắt / hết thời gian chờ là chuyện thường — không in cả đống lỗi ra màn hình; lỗi khác vẫn in như cũ."""
        import sys
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


class WebDev:
    def __init__(self, api, web_dir: str, token: str, port: int = 47822, host: str = "127.0.0.1", gate=None):
        self.api, self.web_dir, self.token, self.host = api, os.path.realpath(web_dir), token, host
        self.gate = gate                              # (tên hàm) -> None | câu từ chối: app chặn lệnh theo tình trạng hiện tại (vd đang có máy của khách)
        self.port = port
        # Cookie = mã phiên ngẫu nhiên của LẦN CHẠY này (không phải khoá). Giữ qua os.execv để «Khởi động lại» không làm văng trang đang mở.
        # Lấy xong thì XOÁ khỏi môi trường: tiến trình con (pip, esptool, arduino-cli…) không được thấy mã phiên. Lần khởi động lại sau,
        # gui.restart_app tự đưa mã phiên vào môi trường của riêng tiến trình mới (os.execve).
        sess = os.environ.pop(SESSION_ENV, None) or ""
        self.session = sess if re.fullmatch(r"[A-Za-z0-9_-]{32,64}", sess) else secrets.token_urlsafe(32)
        self.httpd = None
        self._clients, self._lock = [], threading.Lock()

    # ---- đẩy cập nhật về giao diện ----
    def push(self, js: str):
        with self._lock:
            for q in list(self._clients):
                try:
                    q.put_nowait(js)
                except queue.Full:
                    pass

    def url(self) -> str:
        return "http://127.0.0.1:%d/?t=%s" % (self.port, self.token)

    # ---- vòng đời ----
    def start(self, tries: int = 20):
        outer = self
        for k in range(tries):
            try:
                self.httpd = _Server((self.host, self.port + k), _make_handler(outer))
                self.port += k
                break
            except OSError:
                if k == tries - 1:
                    raise
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self.port

    def stop(self):
        if self.httpd is not None:
            try:
                self.httpd.shutdown(); self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None


def _make_handler(w: WebDev):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "iPhoneFarmDev"
        timeout = IDLE_TIMEOUT                              # kết nối im lặng quá lâu → đóng

        def log_message(self, *a):
            pass

        # ---- tiện ích ----
        def _send(self, code, body=b"", ctype="application/json; charset=utf-8", headers=None):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in SEC_HEADERS.items():
                self.send_header(k, v)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _reject(self, code, body=b"", ctype="text/plain"):
            """Từ chối và ĐÓNG kết nối: phần thân chưa đọc không được phép bị hiểu thành yêu cầu kế tiếp (keep-alive)."""
            self.close_connection = True
            return self._send(code, body, ctype)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False, default=str))

        def _host_ok(self):
            hosts = self.headers.get_all("Host") or []
            return len(hosts) == 1 and hosts[0].lower() in ("127.0.0.1:%d" % w.port, "localhost:%d" % w.port)

        def _origin_ok(self):
            origins = self.headers.get_all("Origin") or []
            if len(origins) > 1:
                return False
            if origins and origins[0].lower() not in ("http://127.0.0.1:%d" % w.port, "http://localhost:%d" % w.port):
                return False
            site = (self.headers.get("Sec-Fetch-Site") or "").lower()       # trình duyệt tự gắn: trang KHÁC gọi sang thì không phải same-origin / none
            return site in ("", "same-origin", "none")

        def _authed(self):
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == COOKIE and _same(v, w.session):
                    return True
            return False

        # ---- GET ----
        def do_GET(self):
            if self.headers.get("Transfer-Encoding") or any((v or "").strip() not in ("", "0") for v in (self.headers.get_all("Content-Length") or [])):
                return self._reject(400, b"GET khong co than")      # thân của GET không được đọc → đừng để nó thành yêu cầu kế tiếp
            if not self._host_ok():
                return self._reject(403, b"host")
            u = urllib.parse.urlsplit(self.path)
            q = urllib.parse.parse_qs(u.query)
            if "t" in q:                                            # đổi khoá lấy cookie (mã phiên) rồi quay về trang chính
                if _same(q["t"][0], w.token):
                    return self._send(302, b"", "text/plain", {"Location": "/", "Set-Cookie": "%s=%s; Path=/; HttpOnly; SameSite=Strict" % (COOKIE, w.session)})
                return self._send(401, b"sai khoa", "text/plain")
            if not self._authed():
                return self._send(401, "Cần khoá: mở http://127.0.0.1:%d/?t=<khoá> (khoá ở app/data/webdev.json)" % w.port, "text/plain; charset=utf-8")
            path = urllib.parse.unquote(u.path)
            if path == "/events":
                return self._events()
            if path == "/__devshim.js":
                return self._send(200, SHIM, "application/javascript; charset=utf-8")
            if path in ("/", "/index.html"):
                with open(os.path.join(w.web_dir, "index.html"), encoding="utf-8") as f:
                    html = f.read()
                # cầu nối phải nạp TRƯỚC tệp JS đầu tiên của giao diện (thẻ <script src> đầu tiên không thuộc bộ giao diện mua sẵn vuexy/) —
                # tìm theo vị trí, không theo tên tệp; trang không có thẻ nào như vậy thì báo lỗi rõ thay vì lặng lẽ chạy không có cầu nối
                first = re.search(r'<script\s+src="(?!vuexy/)', html)
                if not first:
                    return self._send(500, "index.html không có thẻ <script src> nào của giao diện — không chèn được cầu nối của bản web", "text/plain; charset=utf-8")
                html = html[:first.start()] + '<script src="__devshim.js"></script>\n' + html[first.start():]
                return self._send(200, html, "text/html; charset=utf-8")
            return self._static(path)

        def _static(self, path):
            parts = [p for p in path.split("/") if p]
            if not parts or any(p.startswith("_") or p in (".", "..") or p.startswith(".") or "\\" in p or "\0" in p for p in parts):
                return self._send(404, b"khong co", "text/plain")
            full = os.path.realpath(os.path.join(w.web_dir, *parts))
            if not (full == w.web_dir or full.startswith(w.web_dir + os.sep)) or not os.path.isfile(full):
                return self._send(404, b"khong co", "text/plain")
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            with open(full, "rb") as f:
                self._send(200, f.read(), ctype)

        def _events(self):
            q = queue.Queue(maxsize=1000)
            with w._lock:
                w._clients.append(q)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                for k, v in SEC_HEADERS.items():
                    self.send_header(k, v)
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                self.wfile.write(b": ok\n\n"); self.wfile.flush()
                while True:
                    try:
                        js = q.get(timeout=15)
                        self.wfile.write(("data: %s\n\n" % json.dumps(js, ensure_ascii=False)).encode("utf-8"))
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (OSError, ValueError):
                pass
            finally:
                with w._lock:
                    if q in w._clients:
                        w._clients.remove(q)
            self.close_connection = True

        # ---- POST /api/<hàm> ----
        def do_POST(self):
            if not self._host_ok() or not self._origin_ok():
                return self._reject(403, b"nguon")
            if not self._authed():
                return self._reject(401, b"can khoa")
            if self.headers.get("Transfer-Encoding"):               # chỉ nhận thân có Content-Length (không đọc kiểu chunked → không lệch yêu cầu)
                return self._reject(400, b"khong nhan transfer-encoding")
            m = re.fullmatch(r"/api/([a-z][a-z0-9_]*)", urllib.parse.urlsplit(self.path).path)
            if not m:
                return self._reject(404, b"khong co")
            name = m.group(1)
            fn = getattr(type(w.api), name, None)
            if fn is None or not callable(fn):                      # chỉ hàm công khai của LỚP Api (như cầu nối pywebview) — không phải thuộc tính gắn thêm vào đối tượng
                self.close_connection = True
                return self._json(404, {"ok": False, "error": "không có hàm «%s»" % name})
            if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
                return self._reject(415, b"can application/json")   # form / text/plain từ trang khác không gọi được
            lens = self.headers.get_all("Content-Length") or []
            if len(lens) != 1:                                      # thiếu hoặc lặp lại → không đoán độ dài thân
                return self._reject(400, b"can dung mot content-length")
            raw_len = lens[0].strip()
            if not re.fullmatch(r"[0-9]{1,9}", raw_len) or int(raw_len) > MAX_BODY:     # số thập phân thuần (không «5_0», không âm) và không quá lớn
                return self._reject(413 if re.fullmatch(r"[0-9]+", raw_len) else 400, b"do dai than khong hop le")
            n = int(raw_len)
            try:
                data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                args = data.get("args", [])
                if not isinstance(args, list):
                    raise ValueError("args phải là danh sách")
            except (ValueError, UnicodeDecodeError, AttributeError):
                return self._json(400, {"ok": False, "error": "JSON không hợp lệ"})
            if w.gate is not None:
                try:
                    why = w.gate(name)
                except Exception as e:                              # cổng chặn hỏng → từ chối (không «cho qua khi lỗi»)
                    why = "không kiểm tra được quyền gọi lệnh (%s)" % e
                if why:
                    return self._json(200, {"ok": False, "error": str(why)})
            try:
                return self._json(200, {"ok": True, "result": getattr(w.api, name)(*args)})
            except Exception as e:
                return self._json(200, {"ok": False, "error": "%s: %s" % (type(e).__name__, e)})

        def do_PUT(self):
            self._reject(405)
        do_DELETE = do_PATCH = do_PUT
    return H
