#!/usr/bin/env python3
"""
history.py — «máy nào đang chạy bước nào» + LỊCH SỬ riêng của từng máy và từng đơn.

Mỗi máy có một bộ theo dõi (`Tracker`). Bộ chạy bước (apimode.exec_step / engine.run_step) báo cho nó lúc BẮT ĐẦU và lúc XONG từng
bước; bộ chạy kịch bản (runner) báo lúc bắt đầu / kết thúc một lượt chạy, một giai đoạn, một đơn. Từ đó có:

  • trạng thái TRỰC TIẾP (trong bộ nhớ): máy đang ở lượt chạy nào, giai đoạn nào, bước thứ mấy / tổng số, là bước gì, từ bao giờ;
  • lịch sử theo MÁY: `<thư mục>/may-<tên>.jsonl` — mỗi dòng một sự kiện (bắt đầu / kết thúc lượt chạy, từng bước kèm kết quả và thời
    gian, bắt đầu / kết thúc đơn, lời nhắn của bộ chạy);
  • lịch sử theo ĐƠN: `<thư mục>/don.jsonl` — mỗi đơn một dòng tóm tắt; các bước của đơn lấy từ lịch sử của máy đã chạy nó.

KHÔNG có bí mật: chữ của bước là lời mô tả đã che (`apimode.describe` giữ nguyên tên `{{username}}`, `{{password}}`, `{{otp}}`), lý do
của bước do bộ chạy tạo ra và không chứa giá trị của khách; của đơn chỉ ghi mã đơn + gói, không ghi thông tin đăng nhập.

Ghi lịch sử không bao giờ được làm hỏng việc đang chạy: mọi lỗi đọc / ghi tệp đều bị nuốt.
"""
from __future__ import annotations
import json, os, re, threading, time, zlib

MACHINE_MAX_BYTES = 3_000_000       # tệp lịch sử của một máy lớn quá chừng này thì bỏ nửa cũ
ORDERS_MAX_LINES = 3000             # số đơn giữ lại trong sổ tóm tắt
TEXT_MAX = 300                      # độ dài tối đa của một lời mô tả / lý do được lưu
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _clip(s, n=TEXT_MAX) -> str:
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[:n - 1] + "…"


class History:
    def __init__(self, root):
        # thư mục lưu, hoặc HÀM trả thư mục (tính lại mỗi lần ghi / đọc — bài thử đổi thư mục dữ liệu thì lịch sử đi theo, không ghi vào dữ liệu
        # thật của người vận hành); None = chỉ giữ trạng thái trực tiếp, không ghi tệp
        self._root = root
        self.lock = threading.Lock()
        self.trackers = {}

    # ---------- bộ theo dõi của từng máy ----------
    def tracker(self, name: str) -> "Tracker":
        with self.lock:
            t = self.trackers.get(name)
            if t is None:
                t = self.trackers[name] = Tracker(self, name)
            return t

    def live(self) -> dict:
        """{tên máy: việc đang làm} cho các máy đang có lượt chạy (hoặc vừa có bước trong ít giây qua)."""
        with self.lock:
            ts = list(self.trackers.values())
        out = {}
        for t in ts:
            v = t.live()
            if v:
                out[t.name] = v
        return out

    # ---------- tệp ----------
    @property
    def root(self):
        try:
            return self._root() if callable(self._root) else self._root
        except Exception:
            return None

    def _path(self, name: str | None) -> str | None:
        root = self.root
        if not root:
            return None
        if name is None:
            return os.path.join(root, "don.jsonl")
        safe = _SAFE.sub("_", name) or "_"
        if safe != name:                                # tên phải làm sạch → thêm mã của tên GỐC để «Máy 1» và «Mây 1» không dùng chung một tệp
            safe += "-%08x" % zlib.crc32(name.encode("utf-8"))
        return os.path.join(root, "may-%s.jsonl" % safe)

    def _append(self, name: str | None, row: dict):
        path = self._path(name)
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with self.lock:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                if name is not None and os.path.getsize(path) > MACHINE_MAX_BYTES:
                    self._trim(path, keep_bytes=MACHINE_MAX_BYTES // 2)
                elif name is None and row.get("ev") == "order" and os.path.getsize(path) > ORDERS_MAX_LINES * 400:
                    self._trim(path, keep_lines=ORDERS_MAX_LINES)
        except Exception:
            pass

    @staticmethod
    def _trim(path: str, keep_bytes: int | None = None, keep_lines: int | None = None):
        with open(path, "rb") as f:
            data = f.read()
        lines = data.split(b"\n")
        if lines and not lines[-1]:
            lines.pop()
        if keep_lines is not None:
            if len(lines) <= keep_lines:
                return
            lines = lines[-keep_lines:]
        else:
            size, k = 0, len(lines)
            while k > 0 and size + len(lines[k - 1]) + 1 <= keep_bytes:
                k -= 1
                size += len(lines[k]) + 1
            lines = lines[k:]
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(b"\n".join(lines) + (b"\n" if lines else b""))
        os.replace(tmp, path)

    def _read(self, name: str | None) -> list:
        path = self._path(name)
        if not path or not os.path.exists(path):
            return []
        out = []
        try:
            with self.lock:
                with open(path, encoding="utf-8") as f:
                    raw = f.read()
            for line in raw.splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue                    # dòng ghi dở (mất điện giữa chừng) → bỏ dòng đó
                if isinstance(row, dict):
                    out.append(row)
        except Exception:
            return []
        return out

    # ---------- đọc lịch sử ----------
    def machine(self, name: str, limit: int = 300, before: float | None = None) -> list:
        """Các sự kiện MỚI NHẤT của một máy (cũ → mới), tối đa `limit`; `before` = chỉ lấy sự kiện trước mốc thời gian đó (xem tiếp phần cũ)."""
        rows = self._read(name)
        if before is not None:
            rows = [r for r in rows if float(r.get("t") or 0) < float(before)]
        return rows[-max(1, min(int(limit), 2000)):]

    def orders(self, limit: int = 200, machine: str | None = None) -> list:
        """Tóm tắt các đơn, MỚI NHẤT trước. Đơn chạy nhiều lượt (được giao lại) thì mỗi lượt một dòng."""
        rows = [r for r in self._read(None) if r.get("ev") == "order" and (machine is None or r.get("machine") == machine)]
        rows.reverse()
        return rows[:max(1, min(int(limit), ORDERS_MAX_LINES))]

    def order(self, order_id) -> dict:
        """Một đơn: các dòng tóm tắt (mỗi lượt chạy một dòng, mới nhất trước) + mọi sự kiện của nó trên (các) máy đã chạy, cũ → mới."""
        oid = str(order_id)
        runs = [r for r in self.orders(ORDERS_MAX_LINES) if str(r.get("id")) == oid]
        events = []
        for m in sorted({r.get("machine") for r in runs if r.get("machine")}):
            events += [dict(e, machine=m) for e in self._read(m) if str(e.get("order")) == oid]
        events.sort(key=lambda e: float(e.get("t") or 0))
        return {"id": oid, "runs": runs, "events": events}


class Tracker:
    """Việc đang làm + ghi lịch sử của MỘT máy. Mọi hàm đều an toàn khi gọi từ luồng bất kỳ và không bao giờ ném lỗi ra ngoài."""
    IDLE_KEEP = 20.0                    # bước lẻ (không thuộc lượt chạy nào) còn hiện ở «đang làm» thêm chừng này giây sau khi xong

    def __init__(self, hist: History, name: str):
        self.hist, self.name = hist, name
        self.lock = threading.RLock()
        self.run = None                 # {id, kind, group, script, mode, t0}
        self.order_ = None              # {id, ref, items, t0, steps, failed}
        self.phase_ = None              # {label, total, i}
        self.step = None                # {what, type, t0, i, n, phase}
        self.depth = 0                  # bước lồng nhau (engine.run_step gọi tiếp apimode.exec_step) chỉ tính bước NGOÀI CÙNG
        self.last = None                # bước vừa xong gần nhất: {what, ok, msg, t, i, n, phase}
        self.seq = 0

    # ---------- lượt chạy ----------
    def run_begin(self, kind: str, group: str | None = None, script: str | None = None, mode: str | None = None):
        try:
            with self.lock:
                self.seq += 1
                self.run = {"id": "%d-%d" % (int(time.time()), self.seq), "kind": _clip(kind, 40), "group": _clip(group, 80) if group else None,
                            "script": _clip(script, 80) if script else None, "mode": mode, "t0": time.time()}
                self.phase_, self.step, self.depth, self.last = None, None, 0, None
                self._write({"ev": "run_begin", **{k: v for k, v in self.run.items() if k != "t0" and v is not None}})
        except Exception:
            pass

    def run_end(self, status: str = ""):
        try:
            with self.lock:
                if self.run is None:
                    return
                self._write({"ev": "run_end", "run": self.run["id"], "status": _clip(status), "dur": round(time.time() - self.run["t0"], 1)})
                self.run, self.phase_, self.step, self.depth = None, None, None, 0
        except Exception:
            pass

    # ---------- đơn ----------
    def order_begin(self, job: dict, resumed: bool = False):
        """`job` = đơn của gateway. CHỈ lấy mã đơn + gói — không đụng tới thông tin đăng nhập của khách."""
        try:
            with self.lock:
                items = [{"code": _clip(it.get("code"), 60), "name": _clip(it.get("name"), 80), "qty": it.get("qty")}
                         for it in (job.get("items") or []) if isinstance(it, dict)][:20]
                self.order_ = {"id": str(job.get("id")), "ref": _clip(job.get("ref"), 80) if job.get("ref") else None, "items": items,
                               "t0": time.time(), "steps": 0, "failed": 0, "resumed": bool(resumed)}
                self._write({"ev": "order_begin", "order": self.order_["id"], "ref": self.order_["ref"], "items": items, "resumed": bool(resumed)})
        except Exception:
            pass

    def order_end(self, result, message: str = ""):
        try:
            with self.lock:
                o = self.order_
                if o is None:
                    return
                now = time.time()
                self._write({"ev": "order_end", "order": o["id"], "ref": o["ref"], "result": result, "msg": _clip(message), "dur": round(now - o["t0"], 1)})
                self.hist._append(None, {"ev": "order", "id": o["id"], "ref": o["ref"], "machine": self.name, "t": round(o["t0"], 2), "end": round(now, 2),
                                         "result": result, "msg": _clip(message), "items": o["items"], "steps": o["steps"], "failed": o["failed"],
                                         "resumed": o["resumed"], "run": self.run["id"] if self.run else None,
                                         "group": self.run.get("group") if self.run else None, "script": self.run.get("script") if self.run else None})
                self.order_ = None
        except Exception:
            pass

    # ---------- giai đoạn + bước ----------
    def phase(self, label: str | None, total: int | None = None, start: int = 0):
        """Sắp chạy một DANH SÁCH bước (một giai đoạn của đơn, hoặc cả kịch bản thường): từ đây các bước được đếm 1…total
        (chạy tiếp từ bước thứ `start` — 0 là đầu — thì đếm từ start+1)."""
        try:
            with self.lock:
                self.phase_ = {"label": _clip(label, 60) if label else None, "total": int(total) if total else None, "i": max(0, int(start or 0))}
        except Exception:
            pass

    def step_begin(self, what: str, kind: str | None = None):
        try:
            with self.lock:
                self.depth += 1
                if self.depth > 1:
                    return
                ph = self.phase_
                if ph is not None:
                    ph["i"] += 1
                self.step = {"what": _clip(what), "type": kind, "t0": time.time(), "i": ph["i"] if ph else None, "n": ph["total"] if ph else None,
                             "phase": ph["label"] if ph else None}
        except Exception:
            pass

    def step_end(self, ok, msg: str = ""):
        try:
            with self.lock:
                self.depth = max(0, self.depth - 1)
                if self.depth > 0 or self.step is None:
                    return
                s, now = self.step, time.time()
                self.step = None
                row = {"ev": "step", "t": round(s["t0"], 2), "dur": round(now - s["t0"], 2), "what": s["what"], "type": s["type"], "ok": bool(ok), "msg": _clip(msg)}
                for k in ("i", "n", "phase"):
                    if s.get(k) is not None:
                        row[k] = s[k]
                self.last = {"what": s["what"], "ok": bool(ok), "msg": row["msg"], "t": now, "i": s.get("i"), "n": s.get("n"), "phase": s.get("phase")}
                if self.order_ is not None:
                    self.order_["steps"] += 1
                    self.order_["failed"] += 0 if ok else 1
                self._write(row, stamp=False)
        except Exception:
            pass

    def note(self, text: str, kind: str = ""):
        """Một lời nhắn của bộ chạy («Đang đăng nhập», «đơn … cần đối soát»…)."""
        try:
            with self.lock:
                self._write({"ev": "note", "text": _clip(text), "kind": kind or ""})
        except Exception:
            pass

    # ---------- nội bộ ----------
    def _write(self, row: dict, stamp: bool = True):
        if stamp:
            row = {"t": round(time.time(), 2), **row}
        if self.run is not None and "run" not in row and row.get("ev") != "run_begin":
            row["run"] = self.run["id"]
        if self.order_ is not None and "order" not in row:
            row["order"] = self.order_["id"]
        self.hist._append(self.name, row)

    def live(self) -> dict | None:
        """Việc máy ĐANG làm, hoặc None nếu đang nghỉ."""
        with self.lock:
            now = time.time()
            if self.run is None and self.step is None and not (self.last and now - self.last["t"] < self.IDLE_KEEP):
                return None
            out = {"since": round(self.run["t0"], 2) if self.run else None}
            if self.run:
                out.update({k: self.run.get(k) for k in ("kind", "group", "script", "mode")})
            if self.order_:
                out["order"] = {"id": self.order_["id"], "ref": self.order_["ref"], "since": round(self.order_["t0"], 2), "steps": self.order_["steps"]}
            if self.phase_ and self.phase_.get("label"):
                out["phase"] = self.phase_["label"]
            if self.step:
                out["step"] = {k: self.step.get(k) for k in ("what", "type", "i", "n", "phase")}
                out["step"]["since"] = round(self.step["t0"], 2)
            if self.last:
                out["last"] = dict(self.last, t=round(self.last["t"], 2))
            return out
