#!/usr/bin/env python3
"""
mcpserver.py — máy chủ MCP (Model Context Protocol) viết tay, KHÔNG cần SDK (SDK chính thức đòi Python ≥ 3.10,
app này chạy trên 3.9). Nhờ nó một AI (Claude Code, Claude Desktop, Cursor…) nối được vào iPhone Farm Manager
để ĐỌC màn hình iPhone và ĐIỀU KHIỂN máy.

Hỗ trợ cả hai «đời» của giao thức (một client chỉ dùng một đời, máy chủ tự nhận ra theo cách client mở lời):
  • đời CŨ  (2024-11-05 … 2025-11-25): bắt tay `initialize` → `notifications/initialized`, rồi
            `tools/list`, `tools/call`, `ping`;
  • đời MỚI (2026-07-28): không bắt tay — mỗi yêu cầu tự mang phiên bản trong `params._meta`, có
            `server/discover`, và MỌI kết quả phải có `resultType`.

Hai đường truyền:
  • stdio — mỗi dòng một thông điệp JSON (client tự chạy lệnh `farm mcp`);
  • HTTP  — POST /mcp trên 127.0.0.1, cần `Authorization: Bearer <khoá>` (app mở sẵn khi đang chạy).

Tệp này chỉ lo GIAO THỨC. Các công cụ (bấm, đọc màn hình…) nằm ở control.py.
"""
from __future__ import annotations
import base64, hmac, json, os, sys, threading, urllib.error, urllib.request, uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")     # mới nhất đứng đầu
MODERN_VERSIONS = ("2026-07-28",)
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
HEADER_MISMATCH, UNSUPPORTED_VERSION = -32020, -32022
MAX_BODY = 4 * 1024 * 1024


_call = threading.local()                # yêu cầu tools/call mà luồng này đang phục vụ


def cancel_requested() -> bool:
    """Công cụ đang chạy ở luồng này có bị client xin HUỶ không (thông báo `notifications/cancelled`)."""
    ev = getattr(_call, "cancel", None)
    return bool(ev is not None and ev.is_set())


class RpcError(Exception):
    """Lỗi GIAO THỨC (JSON-RPC error) — khác với lỗi khi chạy công cụ (trả kết quả có isError)."""
    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


class ToolError(Exception):
    """Công cụ chạy không thành (tên máy sai, máy đang bận, con trỏ không tới nơi…). Nội dung là câu
    nói được cho AI/người đọc; trả về dưới dạng kết quả có `isError: true` để AI tự sửa rồi thử lại."""


def text(s) -> dict:
    return {"type": "text", "text": str(s)}


def image(data: bytes, mime: str = "image/jpeg") -> dict:
    return {"type": "image", "data": base64.b64encode(data).decode("ascii"), "mimeType": mime}


class Result:
    """Kết quả một công cụ: `content` (các khối text/image cho AI) + `data` (JSON có cấu trúc, tuỳ chọn)."""
    def __init__(self, content, data=None):
        self.content = [text(content)] if isinstance(content, str) else list(content)
        self.data = data


class Tool:
    def __init__(self, name, title, description, properties=None, required=(), fn=None, read_only=False,
                 destructive=False, idempotent=False, cli=None, positional=(), help=""):
        self.name, self.title, self.description = name, title, description
        self.properties = dict(properties or {})
        self.required = tuple(required)
        self.fn = fn
        self.read_only, self.destructive, self.idempotent = read_only, destructive, idempotent
        self.cli = cli or name            # tên lệnh con của CLI
        self.positional = tuple(positional)   # tham số nhận theo vị trí ở CLI
        self.help = help or title         # mô tả tiếng Việt cho người dùng CLI

    def schema(self) -> dict:
        s = {"type": "object", "properties": self.properties, "additionalProperties": False}
        if self.required:
            s["required"] = list(self.required)
        return s

    def describe(self) -> dict:
        return {"name": self.name, "title": self.title, "description": self.description, "inputSchema": self.schema(),
                "annotations": {"title": self.title, "readOnlyHint": self.read_only,
                                "destructiveHint": bool(self.destructive and not self.read_only),
                                "idempotentHint": self.idempotent, "openWorldHint": False}}

    def check(self, args) -> dict:
        """Kiểm tham số theo schema (phần dùng tới: kiểu, bắt buộc, enum, min/max). Sai → ToolError có hướng dẫn."""
        if not isinstance(args, dict):
            raise ToolError("arguments must be an object")
        out = {}
        for k, v in args.items():
            if k not in self.properties:
                raise ToolError("unknown argument «%s» for tool %s (allowed: %s)" % (k, self.name, ", ".join(self.properties) or "none"))
            if v is None:
                continue                  # null = bỏ trống
            p = self.properties[k]
            t = p.get("type")
            if t == "integer":
                if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v:
                    raise ToolError("argument «%s» must be an integer" % k)
                v = int(v)
            elif t == "number":
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise ToolError("argument «%s» must be a number" % k)
            elif t == "string":
                if not isinstance(v, str):
                    raise ToolError("argument «%s» must be a string" % k)
            elif t == "boolean":
                if not isinstance(v, bool):
                    raise ToolError("argument «%s» must be true or false" % k)
            elif t == "array":
                if not isinstance(v, list):
                    raise ToolError("argument «%s» must be an array" % k)
            if "enum" in p and v not in p["enum"]:
                raise ToolError("argument «%s» must be one of: %s" % (k, ", ".join(map(str, p["enum"]))))
            if t in ("integer", "number"):
                if "minimum" in p and v < p["minimum"]:
                    raise ToolError("argument «%s» must be ≥ %s" % (k, p["minimum"]))
                if "maximum" in p and v > p["maximum"]:
                    raise ToolError("argument «%s» must be ≤ %s" % (k, p["maximum"]))
            out[k] = v
        missing = [k for k in self.required if k not in out]
        if missing:
            raise ToolError("missing required argument(s): %s" % ", ".join(missing))
        return out


class McpServer:
    def __init__(self, tools, name="iphone-farm", title="iPhone Farm Manager", version="1.0.0", instructions=""):
        self.tools = {t.name: t for t in tools}
        self.info = {"name": name, "title": title, "version": version}
        self.instructions = instructions
        self._running = {}                  # id của yêu cầu tools/call đang chạy -> cờ huỷ
        self._running_lock = threading.Lock()

    def cancel(self, request_id=None) -> int:
        """Xin huỷ một yêu cầu đang chạy (theo id), hoặc TẤT CẢ nếu không nêu id. Trả số yêu cầu đã được báo huỷ."""
        with self._running_lock:
            evs = list(self._running.values()) if request_id is None else [e for k, e in self._running.items() if k == repr(request_id)]
        for ev in evs:
            ev.set()
        return len(evs)

    # ---------- một thông điệp vào → một thông điệp ra (hoặc None nếu không cần trả lời) ----------
    def handle(self, msg):
        if isinstance(msg, list):                  # gộp lô (chỉ đời 2025-03-26 có) → xử lý từng cái
            out = [r for r in (self.handle(m) for m in msg) if r is not None]
            return out or None
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return self._error(None, INVALID_REQUEST, "Invalid JSON-RPC 2.0 message")
        if "method" not in msg:
            return None                            # client trả lời một yêu cầu của máy chủ — ta không gửi yêu cầu nào
        if "id" not in msg:                        # thông báo: nhận, không trả lời
            if msg.get("method") == "notifications/cancelled" and isinstance(msg.get("params"), dict):
                self.cancel(msg["params"].get("requestId"))
            return None
        mid = msg["id"]
        try:
            params = msg.get("params")
            if params is None:
                params = {}
            if not isinstance(params, dict):
                raise RpcError(INVALID_PARAMS, "params must be an object")
            if msg["method"] == "tools/call":      # đăng ký cờ huỷ cho yêu cầu này (xem cancel_requested)
                ev = threading.Event()
                with self._running_lock:
                    self._running[repr(mid)] = ev
                _call.cancel = ev
            try:
                return {"jsonrpc": "2.0", "id": mid, "result": self._dispatch(str(msg["method"]), params)}
            finally:
                if msg["method"] == "tools/call":
                    _call.cancel = None
                    with self._running_lock:
                        self._running.pop(repr(mid), None)
        except RpcError as e:
            return self._error(mid, e.code, e.message, e.data)
        except Exception as e:                     # lỗi của chính máy chủ
            return self._error(mid, INTERNAL_ERROR, "Internal error: %s" % e)

    @staticmethod
    def _error(mid, code, message, data=None):
        err = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {"jsonrpc": "2.0", "id": mid, "error": err}

    @staticmethod
    def modern_version(msg):
        """Phiên bản đời MỚI mà yêu cầu tự khai trong `_meta` (None = yêu cầu kiểu đời cũ)."""
        params = msg.get("params") if isinstance(msg, dict) else None
        meta = params.get("_meta") if isinstance(params, dict) else None
        return meta.get(META_VERSION) if isinstance(meta, dict) else None

    def _dispatch(self, method: str, params: dict):
        ver = self.modern_version({"params": params})
        modern = ver is not None
        if modern and ver not in MODERN_VERSIONS:
            raise RpcError(UNSUPPORTED_VERSION, "Unsupported protocol version",
                           {"supported": list(MODERN_VERSIONS + LEGACY_VERSIONS), "requested": ver})

        if method == "initialize":                 # đời cũ: thương lượng phiên bản
            want = params.get("protocolVersion")
            return {"protocolVersion": want if want in LEGACY_VERSIONS else LEGACY_VERSIONS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": dict(self.info), "instructions": self.instructions}

        if method == "server/discover":            # đời mới: client hỏi máy chủ biết những gì
            return {"resultType": "complete", "supportedVersions": list(MODERN_VERSIONS + LEGACY_VERSIONS),
                    "capabilities": {"tools": {}}, "instructions": self.instructions,
                    "ttlMs": 60000, "cacheScope": "private", "_meta": {META_SERVER_INFO: dict(self.info)}}

        if method == "ping" and not modern:        # đời mới đã bỏ ping
            return {}

        if method == "tools/list":
            out = {"tools": [t.describe() for t in self.tools.values()]}
            if modern:
                out.update(resultType="complete", ttlMs=60000, cacheScope="private")
            return out

        if method == "tools/call":
            name = params.get("name")
            tool = self.tools.get(name) if isinstance(name, str) else None
            if tool is None:
                raise RpcError(INVALID_PARAMS, "Unknown tool: %s" % name)
            out = self.call(tool, params.get("arguments"))
            if modern:
                out["resultType"] = "complete"
            return out

        raise RpcError(METHOD_NOT_FOUND, "Method not found: %s" % method)

    def call(self, tool: Tool, args) -> dict:
        """Chạy một công cụ. Tham số sai hay công cụ không làm được KHÔNG phải lỗi giao thức: trả kết quả
        `isError: true` kèm lời giải thích để AI đọc được và tự sửa."""
        try:
            res = tool.fn(**tool.check({} if args is None else args))
            if not isinstance(res, Result):
                res = Result(res if isinstance(res, (str, list)) else json.dumps(res, ensure_ascii=False))
            out = {"content": res.content, "isError": False}
            if res.data is not None:
                out["structuredContent"] = res.data
            return out
        except ToolError as e:
            return {"content": [text(str(e))], "isError": True}
        except Exception as e:
            return {"content": [text("%s: %s" % (type(e).__name__, e))], "isError": True}


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))      # một dòng, không xuống dòng thừa


# ====================== đường truyền stdio ======================
def serve_stdio(server: McpServer, stdin=None, stdout=None, workers: int = 4):
    """Đọc từng dòng JSON từ stdin, trả lời ra stdout. stdout CHỈ được chứa thông điệp MCP — mọi thứ khác
    (print của thư viện, nhật ký) phải ra stderr, nếu không client sẽ đọc phải rác và ngắt kết nối.
    `tools/call` chạy ở luồng phụ để một cú bấm dài hàng chục giây không làm nghẽn ping/yêu cầu khác."""
    stdin = stdin or sys.stdin.buffer
    out = stdout or sys.stdout.buffer
    if stdout is None:
        sys.stdout = sys.stderr                    # print() lạc từ bất cứ đâu → stderr
    lock = threading.Lock()
    pool = ThreadPoolExecutor(max_workers=workers)

    def send(resp):
        if resp is None:
            return
        try:
            data = (dumps(resp) + "\n").encode("utf-8")
        except (RecursionError, ValueError, TypeError):
            data = (dumps(McpServer._error(resp.get("id") if isinstance(resp, dict) else None, INTERNAL_ERROR, "Unserializable result")) + "\n").encode("utf-8")
        with lock:
            try:
                out.write(data)
                out.flush()
            except (BrokenPipeError, ValueError):
                pass

    def slow(msg):
        return isinstance(msg, dict) and msg.get("method") == "tools/call"

    try:
        while True:
            raw = stdin.readline()
            if not raw:
                break                              # client đóng stdin → thoát
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8") if isinstance(line, bytes) else line)
            except (ValueError, UnicodeDecodeError, RecursionError):     # (JSON lồng quá sâu cũng chỉ là một dòng hỏng)
                send(McpServer._error(None, PARSE_ERROR, "Parse error"))
                continue
            if slow(msg):
                pool.submit(lambda m=msg: send(server.handle(m)))
            else:
                send(server.handle(msg))
    finally:
        pool.shutdown(wait=True)


# ====================== đường truyền HTTP (trong app) ======================
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1")


def _hostname(value: str) -> str:
    """Tên máy trong tiêu đề Host / Origin (bỏ giao thức và cổng)."""
    v = (value or "").strip().lower()
    if "://" in v:
        v = v.split("://", 1)[1]
    v = v.split("/", 1)[0]
    if v.startswith("["):
        return v.split("]", 1)[0] + "]"
    return v.rsplit(":", 1)[0] if ":" in v else v


def make_handler(server: McpServer, token: str, extra_health=None):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "iPhoneFarmMCP/1.0"

        def log_message(self, *a):                 # không in nhật ký truy cập ra console của app
            pass

        def _send(self, status: int, body=None, headers=None):
            data = b"" if body is None else dumps(body).encode("utf-8")
            self.send_response(status)
            if body is not None:
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if data:
                self.wfile.write(data)

        def _local(self) -> bool:
            """Chống DNS rebinding + trang web lạ gọi vào: Host phải là máy này; có Origin thì cũng phải là máy này."""
            if _hostname(self.headers.get("Host", "")) not in LOCAL_HOSTS:
                return False
            origin = self.headers.get("Origin")
            return origin is None or _hostname(origin) in LOCAL_HOSTS

        def _authed(self) -> bool:
            got = self.headers.get("Authorization", "")
            return got.startswith("Bearer ") and hmac.compare_digest(got[7:].strip().encode(), token.encode())

        def do_GET(self):
            if not self._local():
                return self._send(403, McpServer._error(None, INVALID_REQUEST, "Forbidden origin"))
            if self.path.split("?", 1)[0] == "/health":
                info = {"ok": True, "app": server.info["name"], "version": server.info["version"], "pid": os.getpid()}
                info.update((extra_health() if extra_health else {}) or {})
                return self._send(200, info)
            self._send(405, None, {"Allow": "POST"})          # đời cũ cho phép từ chối GET; đời mới đã bỏ GET

        do_DELETE = do_PUT = lambda self: self._send(405, None, {"Allow": "POST"})

        def do_POST(self):
            if not self._local():
                return self._send(403, McpServer._error(None, INVALID_REQUEST, "Forbidden origin"))
            if self.path.split("?", 1)[0] != "/mcp":
                return self._send(404, McpServer._error(None, METHOD_NOT_FOUND, "Not found"))
            if not self._authed():
                return self._send(401, McpServer._error(None, INVALID_REQUEST, "Missing or wrong bearer token"),
                                  {"WWW-Authenticate": "Bearer"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                self.close_connection = True       # thân chưa đọc → không dùng lại kết nối này (kẻo đọc thân thành yêu cầu kế)
                return self._send(413 if n > MAX_BODY else 400, McpServer._error(None, INVALID_REQUEST, "Bad Content-Length"))
            try:
                msg = json.loads(self.rfile.read(n).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, RecursionError):
                return self._send(400, McpServer._error(None, PARSE_ERROR, "Parse error"))

            modern = McpServer.modern_version(msg)
            hv = self.headers.get("MCP-Protocol-Version")
            if hv is not None and hv not in MODERN_VERSIONS + LEGACY_VERSIONS:
                return self._send(400, McpServer._error(msg.get("id") if isinstance(msg, dict) else None, UNSUPPORTED_VERSION,
                                                        "Unsupported protocol version",
                                                        {"supported": list(MODERN_VERSIONS + LEGACY_VERSIONS), "requested": hv}))
            if modern is not None and isinstance(msg, dict):   # đời mới: tiêu đề (nếu có) phải khớp với thân
                params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
                clash = (hv is not None and hv != modern) \
                    or (self.headers.get("Mcp-Method") not in (None, msg.get("method"))) \
                    or (msg.get("method") == "tools/call" and self.headers.get("Mcp-Name") not in (None, params.get("name")))
                if clash:
                    return self._send(400, McpServer._error(msg.get("id"), HEADER_MISMATCH, "Header does not match request body"))

            try:
                resp = server.handle(msg)
            except RecursionError:
                return self._send(400, McpServer._error(None, INVALID_REQUEST, "Message nested too deeply"))
            if resp is None:
                return self._send(202)             # thông báo: nhận, không có thân
            status = 200
            if modern is not None and isinstance(resp, dict) and "error" in resp:
                status = {METHOD_NOT_FOUND: 404}.get(resp["error"].get("code"), 400)
            self._send(status, resp)

    return Handler


class _QuietServer(ThreadingHTTPServer):
    """Client ngắt kết nối giữa chừng (tắt AI, Ctrl-C lệnh farm) là chuyện thường — không in cả chồng lỗi ra nhật ký app."""
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if not isinstance(exc, (ConnectionError, TimeoutError, OSError)):
            sys.stderr.write("mcp-http: %s: %s\n" % (type(exc).__name__, exc))


def serve_http(server: McpServer, token: str, port: int, host: str = "127.0.0.1", tries: int = 20, extra_health=None):
    """Mở máy chủ HTTP trên máy này (chỉ 127.0.0.1). Cổng bận thì thử các cổng kế tiếp. Trả (httpd, cổng thật)."""
    last = None
    for p in range(port, port + max(1, tries)):
        try:
            httpd = _QuietServer((host, p), make_handler(server, token, extra_health))
        except OSError as e:
            last = e
            continue
        threading.Thread(target=httpd.serve_forever, name="mcp-http", daemon=True).start()
        return httpd, p
    raise OSError("không mở được cổng điều khiển nào trong khoảng %d–%d (%s)" % (port, port + tries - 1, last))


# ====================== khách gọi sang app đang chạy ======================
class Remote:
    """Gọi công cụ của app đang chạy qua HTTP (CLI và máy chủ stdio dùng) — để app là nơi DUY NHẤT giữ cổng serial."""
    def __init__(self, port: int, token: str, host: str = "127.0.0.1", timeout: float = 600.0):
        self.base = "http://%s:%d" % (host, int(port))
        self.token, self.timeout, self._n = token, timeout, 0

    def health(self, timeout: float = 1.5):
        try:
            with urllib.request.urlopen(self.base + "/health", timeout=timeout) as r:
                info = json.loads(r.read().decode("utf-8"))
            return info if info.get("ok") else None
        except Exception:
            return None

    def _post(self, payload: dict, timeout: float):
        req = urllib.request.Request(self.base + "/mcp", data=dumps(payload).encode("utf-8"), method="POST", headers={
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + self.token})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
        return json.loads(raw.decode("utf-8")) if raw else None

    def _cancel(self, rid: str, reason: str):
        """Báo app DỪNG yêu cầu `rid` đang chạy dở (thông báo `notifications/cancelled` của MCP)."""
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": rid, "reason": reason}}, 3)
        except Exception:
            pass

    def _roundtrip(self, rid: str, method: str, params):
        try:
            return self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}, self.timeout)
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8"))
            except Exception:
                raise ToolError("app trả lỗi HTTP %d" % e.code)
        except Exception as e:
            raise ToolError("không gọi được app iPhone Farm Manager (%s)" % e)

    def rpc(self, method: str, params=None):
        """Gọi app và chờ kết quả. Việc chờ chạy ở luồng riêng để luồng này còn theo dõi được hai việc:
        người dùng bấm Ctrl-C (CLI), hoặc client MCP xin huỷ yêu cầu đang phục vụ (Esc trong Claude Code, khi đi qua
        `farm mcp`) → báo app dừng việc đang làm dở trên điện thoại, không để nó chạy nốt các bước còn lại."""
        rid = uuid.uuid4().hex               # id không trùng với client nào khác → huỷ đúng yêu cầu của mình
        box = {}

        def work():
            try:
                box["resp"] = self._roundtrip(rid, method, params)
            except BaseException as e:       # chuyển lỗi về luồng gọi
                box["err"] = e
        t = threading.Thread(target=work, daemon=True)
        t.start()
        sent = False
        try:
            while t.is_alive():
                t.join(0.2)
                if not sent and cancel_requested():
                    sent = True
                    self._cancel(rid, "client cancelled")
                    t.join(15)               # app trả ngay kết quả «đã huỷ»; chờ tối đa 15 s cho nó dừng hẳn
                    break
        except KeyboardInterrupt:            # người dùng bấm Ctrl-C: báo app dừng việc đang làm dở rồi mới thoát
            self._cancel(rid, "Ctrl-C")
            raise
        if t.is_alive():
            raise ToolError("đã huỷ, nhưng app chưa dừng xong việc đang làm — kiểm tra máy trước khi điều khiển tiếp")
        if "err" in box:
            raise box["err"]
        resp = box.get("resp") or {}
        if "error" in resp:
            raise ToolError("%s" % (resp["error"].get("message") or "lỗi không rõ"))
        return resp.get("result") or {}

    def call(self, name: str, args=None) -> dict:
        """Trả nguyên kết quả `tools/call` của app ({content, isError, structuredContent?})."""
        return self.rpc("tools/call", {"name": name, "arguments": args or {}})
