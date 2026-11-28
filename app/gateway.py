#!/usr/bin/env python3
"""
gateway.py — khách (client) gọi API "tool" của Topup Gateway (thư mục Web-topup-gateway).

Tool KHÔNG nhận lệnh từ gateway: nó tự hỏi việc khi máy trống, tự xin/lấy OTP, tự gửi ảnh và
báo kết quả. Hợp đồng đầy đủ xem ở trang /docs của gateway (mục «Tool → Gateway»).

    gw = Gateway("https://gateway.vn", "gwt_xxx")
    r  = gw.claim("iPhoneFarm-01", "efootball-ios")     # {"job": {...}} hoặc {"job": None}
    gw.progress(job_id, "login")
    gw.result(job_id, "done", items=[...])

Chỉ dùng thư viện chuẩn (urllib) — không thêm phụ thuộc.
"""
from __future__ import annotations
import http.client, json, socket, time
import urllib.error, urllib.parse, urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """API của gateway không bao giờ chuyển hướng. Tự đi theo redirect thì header Authorization (khoá Tool)
    sẽ bị gửi sang máy chủ khác → từ chối, để lỗi 3xx nổi lên."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


class GatewayError(Exception):
    """Lỗi khi gọi gateway. status=0 là lỗi mạng (không tới được máy chủ)."""

    def __init__(self, status: int, error: str, message: str = "", body: dict | None = None):
        super().__init__(f"[{status}] {error}" + (f": {message}" if message else ""))
        self.status = status
        self.error = error
        self.message = message
        self.body = body or {}

    @property
    def retryable(self) -> bool:
        """Lỗi tạm thời: mạng / 5xx / 429 → gửi lại y nguyên được. 4xx khác thì KHÔNG gửi lại."""
        return self.status == 0 or self.status >= 500 or self.status == 429

    def vi(self) -> str:
        """Câu ngắn tiếng Việt để hiện cho người vận hành."""
        if self.status == 0:
            return "Không kết nối được gateway (" + (self.message or self.error) + ")"
        if self.status == 401:
            return "Gateway từ chối khoá Tool (sai hoặc đã bị khoá)"
        if self.status == 429:
            return "Gateway tạm chặn vì sai khoá quá nhiều lần"
        return self.message or f"Gateway trả lỗi {self.status} ({self.error})"


def call_retry(fn, tries: int = 3, base: float = 1.0, sleep=time.sleep):
    """Gọi fn(); gặp lỗi TẠM THỜI thì chờ 1s, 2s, 4s… rồi thử lại (tối đa `tries` lần)."""
    delay = base
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except GatewayError as e:
            if not e.retryable or attempt >= tries:
                raise
            sleep(delay)
            delay = min(delay * 2, 30)


class Gateway:
    def __init__(self, base_url: str, key: str, timeout: float = 30.0):
        self.base = (base_url or "").strip().rstrip("/")
        self.key = (key or "").strip()
        self.timeout = timeout
        if not self.base or not self.key:
            raise GatewayError(0, "not_configured", "Chưa cấu hình địa chỉ / khoá gateway")

    # ---------- lõi ----------
    def _call(self, method: str, path: str, body=None, raw: bytes | None = None,
              content_type: str | None = None, query: dict | None = None, timeout: float | None = None) -> dict:
        url = self.base + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"Authorization": "Bearer " + self.key, "Accept": "application/json",
                   "User-Agent": "farm-tool/1.0"}
        data = None
        if raw is not None:
            data = raw
            headers["Content-Type"] = content_type or "application/octet-stream"
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with _OPENER.open(req, timeout=timeout or self.timeout) as resp:
                status = resp.status
                text = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if 300 <= e.code < 400:
                raise GatewayError(e.code, "redirect", "Gateway chuyển hướng sang địa chỉ khác — kiểm tra lại địa chỉ gateway (http/https, có www hay không)")
            text = e.read().decode("utf-8", "replace")
            j = self._json(text)
            raise GatewayError(e.code, str(j.get("error") or "http_error"),
                               str(j.get("message") or text[:200]), j)
        except (urllib.error.URLError, socket.timeout, ConnectionError, http.client.HTTPException, OSError) as e:
            # mọi lỗi đường truyền (kể cả phản hồi đứt giữa chừng) → lỗi mạng, gửi lại được
            raise GatewayError(0, "network", str(getattr(e, "reason", e)) or type(e).__name__)
        j = self._json(text)
        if not j:
            raise GatewayError(status, "bad_response", "Gateway trả về dữ liệu không phải JSON")
        return j

    @staticmethod
    def _json(text: str) -> dict:
        try:
            d = json.loads(text)
            return d if isinstance(d, dict) else {}
        except ValueError:
            return {}

    # ---------- API tool ----------
    def ping(self) -> dict:
        return self._call("GET", "/api/tool/ping")

    def pools(self) -> list:
        """Danh sách pool (để chọn trong giao diện)."""
        return self._call("GET", "/api/tool/pools").get("pools") or []

    def pool(self, code: str) -> dict:
        """Cấu hình pool: trường đăng nhập, luật nhận diện, các bước, gói nạp."""
        return self._call("GET", "/api/tool/pools/" + urllib.parse.quote(code, safe="")).get("pool") or {}

    def heartbeat(self, devices: list, active: list) -> dict:
        return self._call("POST", "/api/tool/heartbeat", {"devices": devices, "active": active})

    def sync(self, body: dict, timeout: float = 12.0) -> dict:
        """Tự báo cho gateway: máy nào rảnh ở kịch bản nào (+ danh mục kịch bản khi gateway đòi). Xem presence.py.
        Trả nguyên phản hồi: {scripts_rev, need_scripts, devices, scripts}."""
        return self._call("POST", "/api/tool/sync", body, timeout=timeout)

    def claim(self, device: str, pool: str, wallet: dict | None = None) -> dict:
        """Máy trống xin việc. `wallet` = ví của máy ở tool {currency, available ×100} (None = máy không có ví, không kiểm tiền).
        Trả nguyên phản hồi: {job|None, paused, resumed?, wallet_short?}."""
        body = {"device": device, "pool": pool}
        if wallet:
            body["wallet"] = {"currency": str(wallet["currency"]), "available": int(wallet["available"]),
                              "applied": [int(x) for x in (wallet.get("applied") or [])][-300:]}
        return self._call("POST", "/api/tool/claim", body)

    def job(self, job_id: str) -> dict:
        return self._call("GET", f"/api/tool/jobs/{job_id}").get("job") or {}

    def progress(self, job_id: str, stage: str, message: str | None = None) -> dict:
        body = {"stage": stage}
        if message:
            body["message"] = message[:300]
        return self._call("POST", f"/api/tool/jobs/{job_id}/progress", body)

    def otp_request(self, job_id: str, reason: str = "first", message: str | None = None, attempt: int | None = None) -> dict:
        """Xin khách nhập OTP. `attempt` = lần xin thứ mấy theo tool: gửi lại cùng số (mất phản hồi) thì
        gateway trả lại trạng thái cũ, không tốn thêm lượt."""
        body = {"reason": reason}
        if attempt:
            body["attempt"] = int(attempt)
        if message:
            body["message"] = message[:300]
        return self._call("POST", f"/api/tool/jobs/{job_id}/otp/request", body)

    def otp_read(self, job_id: str, wait: int = 20) -> dict:
        """Lấy OTP khách nhập; gateway giữ kết nối tối đa `wait` giây nếu chưa có."""
        return self._call("GET", f"/api/tool/jobs/{job_id}/otp", query={"wait": int(wait)}, timeout=wait + 15)

    def upload_image(self, job_id: str, seq: int, kind: str, data: bytes, mime: str = "image/jpeg") -> dict:
        return self._call("POST", f"/api/tool/jobs/{job_id}/images", raw=data, content_type=mime,
                          query={"seq": int(seq), "kind": kind}, timeout=45)

    def result(self, job_id: str, result: str, message: str | None = None, items: list | None = None) -> dict:
        body = {"result": result}
        if message:
            body["message"] = message[:500]
        if items:
            body["items"] = items
        return self._call("POST", f"/api/tool/jobs/{job_id}/result", body)
