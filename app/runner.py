#!/usr/bin/env python3
"""
runner.py — chạy kịch bản của NHÓM trên từng máy bằng worker riêng.

Mỗi máy = 1 thread + cờ dừng riêng → dừng 1 máy không ảnh hưởng máy khác.

Chế độ của nhóm:
  "loop"  lặp kịch bản N vòng (0 = vô hạn)        ─┐ dùng `group.steps`
  "once"  chạy kịch bản 1 lần                      ─┘
  "api"   NHẬN ĐƠN TỪ GATEWAY: máy trống tự xin việc → đăng nhập → OTP → mua gói → chụp bill
          → báo kết quả → đăng xuất → xin việc tiếp. Các bước lấy từ cấu hình pool trên gateway,
          nhóm có thể ghi đè từng giai đoạn (`group.api.steps`).

Dừng ở chế độ api:
  * Dừng thường  = KHÔNG nhận đơn mới; đơn đang làm vẫn làm cho xong (an toàn tiền).
  * Dừng ngay    = bỏ dở: chưa chạm luồng mua → báo `failed`; đã chạm → báo `review`.
Máy tự dừng khi: có đơn cần đối soát, bước đăng xuất lỗi, hoặc lỗi do máy/tool liên tiếp.

Trước MỖI lần xin đơn, máy phải ở trạng thái «game chưa đăng nhập» đã được KIỂM (mở game, đọc màn hình):
đơn vừa xong, máy vừa bấm Chạy lại sau khi đối soát, tool vừa khởi động lại… đều đi qua bước này, nên
không đơn nào của khách bị tiêu tốn chỉ để phát hiện ra máy còn đăng nhập tài khoản của người trước.
"""
from __future__ import annotations
import threading, time
from collections import deque

import engine
import store
import apimode
from apimode import Outcome
from gateway import GatewayError, call_retry

RESULT_LABEL = {"done": "HOÀN TẤT", "failed": "THẤT BẠI (chưa nạp)", "review": "CHỜ ĐỐI SOÁT"}


class Runner:
    # nhịp (giây) — test rút ngắn lại
    POLL_IDLE = 4.0           # không có đơn → bao lâu hỏi lại
    NOT_READY_WAIT = 15.0     # máy chưa sẵn sàng / gateway lỗi → bao lâu thử lại
    BOARD_CHECK_EVERY = 300.0  # lúc RẢNH (chưa nhận đơn) cứ chừng này giây kiểm sức khoẻ board ESP32 một lần (RAM, đơ…)
    POOL_REFRESH = 60.0       # bao lâu tải lại cấu hình pool
    HEARTBEAT_EVERY = 25.0
    RESULT_TRIES = 6          # số lần thử gửi kết quả (1s, 2s, 4s… giữa các lần)
    RESULT_BASE = 1.0
    OTP_WAIT = 20             # giây giữ kết nối mỗi lần hỏi OTP
    MAX_FAULTS = 2            # số đơn liên tiếp lỗi do máy/tool trước khi tự dừng máy
    CLEAR_WAIT = 8.0          # chờ hộp thoại «nạp thành công» của lần mua trước biến mất, quá thì dừng mua

    def __init__(self, session_getter, gateway_factory=None, journal=None, on_log=None):
        self._session = session_getter          # name -> Nav
        self._gateway = gateway_factory         # () -> Gateway (ném GatewayError nếu chưa cấu hình)
        self.journal = journal                  # apimode.Journal
        self.on_log = on_log                    # (entry dict) -> None
        self.lock = threading.Lock()
        self.workers = {}                       # name -> dict
        self.logs = deque(maxlen=400)
        self._hb = None
        self._hb_wake = threading.Event()

    # ====================== nhật ký ======================
    def _log(self, name, text, kind=""):
        entry = {"t": time.strftime("%H:%M:%S"), "name": name, "text": str(text), "kind": kind}
        self.logs.append(entry)
        if self.on_log:
            try:
                self.on_log(entry)
            except Exception:
                pass

    def log_tail(self, limit=200):
        return list(self.logs)[-limit:]

    # ====================== trạng thái ======================
    def is_running(self, name):
        """Máy có worker còn sống không (kể cả đang chờ làm nốt đơn để dừng) → cổng serial đang bận."""
        w = self.workers.get(name)
        return bool(w and w["thread"].is_alive())

    def running_names(self):
        return [n for n, w in list(self.workers.items()) if w["thread"].is_alive()]

    def _snap(self, name):
        w = self.workers.get(name)
        if not w:
            return {"name": name, "running": False, "status": "nghỉ"}
        alive = w["thread"].is_alive()
        return {
            "name": name, "running": alive, "stopping": alive and w["stop"].is_set(),
            "group_id": w["group_id"], "mode": w["mode"],
            "iter": w["iter"], "status": w["status"],
            "last_ok": w.get("last_ok"), "last_msg": w.get("last_msg"), "hold": (w.get("hold") if not alive else None),
            "job": w.get("job_ref"), "counts": dict(w["counts"]),
        }

    def status(self):
        with self.lock:
            return {n: self._snap(n) for n in list(self.workers)}

    def _board_check(self, nav, say):
        """Kiểm sức khoẻ board ESP32 của `nav` LÚC RẢNH và tự phục hồi nếu cần (board im → reset cứng; thiếu RAM / phân mảnh → reset
        mềm sớm). Trả (ok, lý do nếu hỏng). Chỉ làm được với bàn tay thật (có cổng serial); bàn tay giả / lỗi khi kiểm → coi là ổn."""
        h = getattr(nav, "h", None)
        if h is None or not hasattr(h, "ser") or not hasattr(h, "wait_connected"):
            return True, ""
        import boardhealth
        try:
            rec = boardhealth.recover(h, log=lambda m: say("Board ESP32: " + m))
        except Exception as e:
            say("Không kiểm được board ESP32: %s" % e, "warn")
            return True, ""                       # lỗi lúc KIỂM không có nghĩa board hỏng
        health = rec.get("health")
        if rec["actions"]:
            say("Board ESP32: " + "; ".join(rec["actions"]) + ((" → " + health["summary"]) if health else ""), "warn")
        if health and health["level"] in ("warn", "bad") and health.get("findings"):
            say("Board ESP32 %s: %s" % ("NẶNG" if health["level"] == "bad" else "cảnh báo", "; ".join(f["text"] for f in health["findings"])), "warn")
        return (True, "") if rec["ok"] else (False, "board ESP32 không dùng được (%s)" % ((health or {}).get("summary") or "không trả lời"))

    def hold_reason(self, name):
        """Lý do máy đang DỪNG CHỜ NGƯỜI KIỂM TRA (None = không). Máy nhận đơn tự dừng giữa chừng (đơn cần đối soát,
        không đăng xuất được, không nhận ra màn hình…) thì màn hình được GIỮ NGUYÊN để người vận hành xem — cho tới
        khi họ bấm Dừng (xác nhận đã xử lý) hoặc Chạy lại, không ai khác (AI, dòng lệnh) được điều khiển máy đó."""
        w = self.workers.get(name)
        return (w.get("hold") or None) if (w and not w["thread"].is_alive()) else None

    # ====================== điều khiển ======================
    def start_machine(self, name, group):
        with self.lock:
            if self.is_running(name):
                return False
            mode = group.get("mode", "loop")
            w = {"stop": threading.Event(), "abort": threading.Event(), "group_id": group.get("id"), "mode": mode,
                 "iter": 0, "status": "chuẩn bị", "last_ok": None, "last_msg": None,
                 "job_id": None, "job_ref": None, "pool": None, "counts": {"done": 0, "failed": 0, "review": 0}}
            target = self._run_api if mode == "api" else self._run
            t = threading.Thread(target=self._guard, args=(target, name, dict(group), w), daemon=True)
            w["thread"] = t
            self.workers[name] = w
            t.start()
        if mode == "api":
            self._ensure_heartbeat()
        return True

    def stop_machine(self, name, force=False):
        with self.lock:
            w = self.workers.get(name)
            if w:
                w["stop"].set()
                if force:
                    w["abort"].set()
                if not w["thread"].is_alive():
                    w["hold"] = None            # máy đã dừng từ trước: bấm Dừng = xác nhận đã kiểm tra xong
        return True

    def start_group(self, group, names=None):
        targets = names if names is not None else list(group.get("devices", []))
        return [n for n in targets if self.start_machine(n, group)]

    def stop_group(self, group, force=False):
        for n in list(group.get("devices", [])):
            self.stop_machine(n, force)
        return True

    def stop_all(self, force=False):
        with self.lock:
            for w in self.workers.values():
                w["stop"].set()
                if force:
                    w["abort"].set()

    def _guard(self, target, name, group, w):
        """Bọc worker: lỗi bất ngờ không được làm thread chết im lặng."""
        try:
            target(name, group, w)
        except Exception as e:
            w["status"] = "DỪNG: lỗi không mong đợi — %s" % e
            if w.get("mode") == "api":
                w["hold"] = "lỗi không mong đợi — %s" % e
            self._log(name, "Worker dừng vì lỗi không mong đợi: %s" % e, "bad")
        finally:
            w["job_id"] = w["job_ref"] = None

    # ====================== chế độ loop / once ======================
    def _run(self, name, group, w):
        stop = w["stop"]
        mode = group.get("mode", "loop")
        loops = int(group.get("loops") or 0)
        steps = group.get("steps", [])
        if not steps:
            w["status"] = "nhóm chưa có bước nào"
            return
        try:
            nav = self._session(name)
        except Exception as e:
            w["status"] = "lỗi mở máy: " + str(e)
            return
        count = 0
        while not stop.is_set():
            count += 1
            w["iter"] = count
            w["status"] = f"đang chạy · vòng {count}"
            try:
                res = engine.run_flow(nav, steps, stop_check=lambda: stop.is_set())
                oks = sum(1 for r in res if r.get("ok"))
                w["last_ok"] = (oks == len(res)) if res else True
                w["last_msg"] = f"{oks}/{len(res)} bước OK"
            except Exception as e:
                w["last_ok"] = False
                w["last_msg"] = str(e)
            if stop.is_set():
                break
            if mode == "once":
                break
            if mode == "loop" and loops > 0 and count >= loops:
                break
            stop.wait(1.0)      # nghỉ giữa vòng, vẫn thoát ngay khi bị dừng
        w["status"] = "đã dừng" if stop.is_set() else "xong"

    # ====================== chế độ api (nhận đơn từ gateway) ======================
    def _run_api(self, name, group, w):
        stop, abort = w["stop"], w["abort"]
        api = store.api_defaults(group.get("api"))
        pool_code = api["pool"]
        w["pool"] = pool_code

        def say(text, kind=""):
            self._log(name, text, kind)

        def status(text):
            w["status"] = text

        def halt(text, hold=False):
            """Dừng máy. `hold=True`: dừng giữa lúc đang làm việc với đơn / phiên đăng nhập của khách → màn hình phải
            được GIỮ NGUYÊN cho người kiểm tra (xem hold_reason). Lỗi cấu hình, lỗi kiểm bàn phím… thì không cần giữ."""
            status("DỪNG: " + text)
            w["hold"] = text if hold else None
            say("Máy dừng: " + text, "bad")

        if not pool_code:
            return halt("nhóm chưa chọn pool của gateway")
        try:
            gw = self._gateway()
        except Exception as e:
            return halt(e.vi() if isinstance(e, GatewayError) else str(e))
        try:
            nav = self._session(name)
        except Exception as e:
            return halt("không mở được máy — %s" % e)

        say("Bắt đầu nhận đơn từ pool «%s»" % pool_code)
        pool, steps, pool_at = None, None, 0.0
        kb_checked = not api["check_keyboard"]
        kb_errors = 0
        board_checked, board_errors = 0.0, 0     # lần kiểm board ESP32 gần nhất (0 = chưa kiểm) / số lần liền board không dùng được
        clean = False             # đã KIỂM là game đang ở trạng thái chưa đăng nhập chưa
        probe_errors = 0
        faults = 0
        opts = {"login_wait": api["login_wait"], "purchase_wait": api["purchase_wait"], "otp_wait": self.OTP_WAIT,
                "clear_wait": self.CLEAR_WAIT}

        while not stop.is_set():
            # --- kết quả đơn trước còn nợ (tool chết giữa chừng / mất mạng lúc gửi) ---
            st = self.journal.get(name) if self.journal else None
            if st and st.get("phase") == "purchasing":
                out = Outcome("review", "Tool bị tắt giữa lúc mua — cần đối soát")
                self.journal.set(name, phase="finished", outcome=out.to_dict(), delivered=False)
                self.journal.record(device=name, job=st.get("job"), ref=st.get("ref"), **out.to_dict())
                self._deliver(gw, name, st.get("job"), st.get("ref") or st.get("job"), out, say)
                return halt("đơn %s bị gián đoạn giữa lúc mua — kiểm tra máy rồi bấm Chạy lại" % (st.get("ref") or st.get("job")), hold=True)
            if st and st.get("phase") == "finished" and not st.get("delivered") and (st.get("outcome") or {}).get("result"):
                if not self._deliver(gw, name, st["job"], st.get("ref") or st["job"], Outcome.from_dict(st["outcome"]), say):
                    status("Chưa gửi được kết quả đơn trước — đang thử lại")
                    stop.wait(self.NOT_READY_WAIT)
                    continue

            # --- cấu hình pool (làm mới định kỳ để ăn thay đổi trên gateway) ---
            if pool is None or time.time() - pool_at > self.POOL_REFRESH:
                try:
                    pool = gw.pool(pool_code)
                    steps = apimode.effective_steps(pool, api["steps"])
                    pool_at = time.time()
                except apimode.ConfigError as e:
                    return halt("cấu hình bước sai — %s" % e)
                except GatewayError as e:
                    if e.status == 404:
                        return halt("gateway không có pool «%s»" % pool_code)
                    if e.status == 401:
                        return halt(e.vi())
                    status(e.vi())
                    stop.wait(self.NOT_READY_WAIT)
                    continue
                missing = apimode.validate(pool, steps)
                if missing:
                    return halt("pool «%s» chưa đủ cấu hình để máy tự chạy: %s — bổ sung ở trang quản trị gateway (Pool & gói nạp)"
                                % (pool_code, "; ".join(missing)))

            # --- máy có sẵn sàng không? (không nhận đơn khi máy đang hỏng) ---
            try:
                problem = apimode.preflight(nav)
            except Exception as e:
                problem = str(e)
            if problem:
                status("Chưa sẵn sàng: " + problem)
                if time.time() - board_checked > 60:        # có thể do board ESP32 đơ: thử cứu (đang rảnh, chưa nhận đơn nào)
                    board_checked = time.time()
                    self._board_check(nav, say)
                stop.wait(self.NOT_READY_WAIT)
                continue
            if not kb_checked:
                status("Kiểm tra bàn phím tiếng Anh…")
                try:
                    ok, _ = nav.ensure_english()
                except Exception as e:
                    # KHÔNG coi là đạt: máy đang Telex mà cứ chạy thì mọi mật khẩu gõ vào đều sai
                    kb_errors += 1
                    if kb_errors >= 3:
                        return halt("không kiểm tra được bàn phím iPhone (%s) — kiểm tra máy rồi bấm Chạy lại "
                                    "(hoặc tắt «Kiểm tra bàn phím» của nhóm nếu chắc chắn máy đang gõ tiếng Anh)" % e)
                    status("Chưa kiểm tra được bàn phím (%s) — thử lại" % e)
                    stop.wait(self.NOT_READY_WAIT)
                    continue
                if not ok and getattr(nav, "kb_reason", "ime") == "unreadable":
                    # không đọc được chữ vừa gõ (OCR hụt / Spotlight không mở) — CHƯA biết bàn phím đúng hay sai
                    kb_errors += 1
                    if kb_errors >= 3:
                        return halt("không đọc được chữ gõ thử trong ô tìm kiếm của iPhone để kiểm bàn phím — kiểm tra máy rồi bấm Chạy lại "
                                    "(hoặc tắt «Kiểm tra bàn phím» của nhóm nếu chắc chắn máy đang gõ tiếng Anh)")
                    status("Chưa đọc được chữ gõ thử để kiểm bàn phím — thử lại")
                    stop.wait(self.NOT_READY_WAIT)
                    continue
                kb_checked = True
                if not ok:
                    return halt("bàn phím iPhone đang ở bộ gõ tiếng Việt (Telex/VNI) nên chữ gõ vào bị biến đổi — "
                                "trên iPhone vào Cài đặt → Cài đặt chung → Bàn phím → Bàn phím, thêm «English» và xoá «Tiếng Việt», rồi bấm Chạy lại")

            # --- game phải đang ở trạng thái CHƯA đăng nhập thì mới được nhận đơn ---
            if not clean:
                status("Kiểm tra game đã đăng xuất chưa…")
                try:
                    state = self._ensure_logged_out(nav, steps, pool, api["login_wait"], say, abort.is_set)
                except apimode.Aborted:
                    break
                except Exception as e:
                    probe_errors += 1
                    if probe_errors >= 3:
                        return halt("không kiểm tra được trạng thái đăng nhập của game (%s)" % e, hold=True)
                    status("Chưa kiểm tra được trạng thái game (%s) — thử lại" % e)
                    stop.wait(self.NOT_READY_WAIT)
                    continue
                probe_errors = 0
                if state == "in":
                    return halt("game vẫn đang đăng nhập một tài khoản và tool không đăng xuất được — "
                                "đăng xuất tay trong game rồi bấm Chạy lại", hold=True)
                if state != "out":
                    return halt("không nhận ra màn hình game (không thấy chữ của luật «Màn hình CHƯA đăng nhập» "
                                "lẫn «Đăng nhập THÀNH CÔNG») — kiểm tra game và luật của pool rồi bấm Chạy lại", hold=True)
                clean = True
                if stop.is_set():
                    break

            # --- board ESP32 còn khoẻ không? (LÚC RẢNH — reset giữa đơn sẽ làm rớt BLE) ---
            if time.time() - board_checked > self.BOARD_CHECK_EVERY:
                board_checked = time.time()
                board_ok, board_why = self._board_check(nav, say)
                if not board_ok:
                    board_checked = 0.0                        # lần sau kiểm lại ngay
                    board_errors += 1
                    if board_errors >= 3:
                        return halt("%s — kiểm tra cáp USB / nguồn của board rồi bấm Chạy lại" % board_why)
                    status("%s — thử lại" % board_why)
                    stop.wait(self.NOT_READY_WAIT)
                    continue
                board_errors = 0
                if stop.is_set():
                    break

            # --- máy trống → xin việc ---
            try:
                r = gw.claim(name, pool_code)
            except GatewayError as e:
                if e.status == 401:
                    return halt(e.vi())
                status(e.vi())
                stop.wait(self.NOT_READY_WAIT)
                continue
            if r.get("paused"):
                status("Pool đang tạm dừng trên gateway")
                stop.wait(self.NOT_READY_WAIT)
                continue
            job = r.get("job")
            if not job:
                status("Chờ đơn")
                stop.wait(self.POLL_IDLE)
                continue

            clean = False         # sắp đụng vào game → phải kiểm lại trước đơn sau
            outcome = self._handle_job(name, w, gw, nav, job, bool(r.get("resumed")), pool, steps, opts, abort, say, status)
            w["job_id"] = w["job_ref"] = None
            if outcome.result:
                w["counts"][outcome.result] = w["counts"].get(outcome.result, 0) + 1
                w["last_ok"] = outcome.result == "done"
                w["last_msg"] = "%s: %s" % (job.get("ref") or job["id"], RESULT_LABEL.get(outcome.result, outcome.result))
            w["iter"] += 1

            # Đơn cần đối soát: DỪNG và giữ nguyên màn hình cho người kiểm tra (không tự đăng xuất).
            # Lần «Chạy lại» sau đó sẽ tự đăng xuất + kiểm game sạch trước khi nhận đơn mới.
            if outcome.result == "review":
                return halt("đơn %s cần đối soát — kiểm tra máy rồi bấm Chạy lại (máy sẽ tự đăng xuất trước khi nhận đơn mới)"
                            % (job.get("ref") or job["id"]), hold=True)
            if outcome.halt:
                return halt("%s — kiểm tra máy rồi bấm Chạy lại" % outcome.message, hold=True)
            if abort.is_set():
                break
            # đưa máy về trạng thái sạch cho đơn sau (đăng xuất…)
            if not self._finish(nav, steps, say, status, strict=outcome.session != "none"):
                return halt("bước kết thúc đơn (đăng xuất) bị lỗi — kiểm tra máy rồi bấm Chạy lại", hold=True)
            faults = faults + 1 if outcome.fault else 0
            if faults >= self.MAX_FAULTS:
                return halt("%d đơn liên tiếp lỗi do máy/tool — kiểm tra máy và cấu hình bước" % faults, hold=True)

        status("đã dừng")
        say("Đã dừng nhận đơn")

    def _ensure_logged_out(self, nav, steps, pool, wait, say, abort=None) -> str:
        """Đưa game về trạng thái CHƯA đăng nhập và KIỂM lại. Trả "out" | "in" | "unknown".
        Mở game → đọc màn hình. Nếu còn đăng nhập (hoặc không nhận ra màn hình) thì chạy các bước
        «Kết thúc đơn» (đăng xuất) rồi kiểm lần nữa."""
        rules = pool.get("rules") or []
        state = apimode.session_probe(nav, steps, rules, wait, abort)
        if state == "out":
            return state
        say("Game %s → chạy các bước kết thúc đơn (đăng xuất) rồi kiểm lại"
            % ("còn đang đăng nhập một tài khoản" if state == "in" else "đang ở màn hình lạ"))
        try:
            apimode.run_steps(nav, steps.get("finish") or [], {}, abort)
        except apimode.Aborted:
            raise
        except Exception as e:
            say("Bước kết thúc đơn lỗi: %s" % e, "bad")
        return apimode.session_probe(nav, steps, rules, wait, abort)

    def _finish(self, nav, steps, say, status=None, strict=True):
        """Chạy các bước kết thúc đơn (đăng xuất…).
        strict=True : game có thể đang đăng nhập tài khoản của khách → các bước PHẢI chạy được;
                      lỗi thì trả False để máy dừng (tránh đơn sau nạp nhầm tài khoản này).
        strict=False: chắc chắn chưa ai đăng nhập (vd sai mật khẩu) → chạy được thì tốt, lỗi thì
                      chỉ về màn hình chính rồi đi tiếp."""
        fin = steps.get("finish") or []
        if not fin:
            return True
        if status:
            status("Đang kết thúc đơn (đăng xuất)")
        try:
            ok, why, idx, _ = apimode.run_steps(nav, fin, {})
        except Exception as e:
            ok, why = False, str(e)
        if ok:
            return True
        if strict:
            say("Bước kết thúc đơn lỗi: %s" % why, "bad")
            return False
        try:
            apimode.hid(nav, "combo gui h")         # chưa đăng nhập gì → chỉ cần về màn hình chính
        except Exception:
            pass
        return True

    def _handle_job(self, name, w, gw, nav, job, resumed, pool, steps, opts, abort, say, status):
        jid = job["id"]
        ref = job.get("ref") or jid
        w["job_id"], w["job_ref"] = jid, ref
        j = self.journal
        st = j.get(name) if j else None

        if job.get("pool") and pool.get("code") and job["pool"] != pool["code"]:
            # máy đang giữ đơn của POOL KHÁC (máy vừa bị chuyển nhóm giữa chừng) → các bước/luật đang có không
            # phải của đơn này; không được chạy bằng cấu hình sai.
            out = Outcome("review", "Máy đang giữ đơn của pool «%s» nhưng nhóm đang chạy pool «%s» — cần đối soát"
                          % (job["pool"], pool["code"]))
            say("Đơn %s thuộc pool khác (%s) → chuyển đối soát, không chạy" % (ref, job["pool"]), "bad")
            if j:
                j.set(name, job=jid, ref=ref, phase="finished", outcome=out.to_dict(), delivered=False)
                j.record(device=name, job=jid, ref=ref, **out.to_dict())
            self._deliver(gw, name, jid, ref, out, say)
            return out

        if resumed:
            mine = bool(st and st.get("job") == jid)
            if mine and st.get("phase") == "claimed":
                # tool tắt TRƯỚC khi chạm luồng mua → làm lại từ đầu là an toàn
                # (game đã được kiểm «chưa đăng nhập» ngay trước khi xin đơn)
                say("Tiếp tục đơn %s (lần trước dừng trước khi mua) — làm lại từ đầu" % ref)
            elif not mine and job.get("status") == "claimed":
                # Gateway đã giao đơn nhưng phản hồi «nhận đơn» không tới tool (mất mạng đúng lúc đó).
                # Trạng thái trên gateway vẫn là «claimed» = CHƯA có lệnh nào của tool cho đơn này
                # (việc đầu tiên khi bắt đầu một đơn là báo tiến độ → «running») → bắt đầu bây giờ là an toàn.
                say("Nhận lại đơn %s — lần giao trước chưa tới tool, giờ mới bắt đầu" % ref)
                if j:
                    j.set(name, job=jid, ref=ref, phase="claimed", outcome=None, delivered=False)
            else:
                out = Outcome("review", "Tool không còn dữ liệu về đơn đang giữ — cần đối soát")
                say("Đơn %s: gateway nói máy đang giữ nhưng tool không có ghi chép → chuyển đối soát" % ref, "bad")
                if j:
                    j.set(name, job=jid, ref=ref, phase="finished", outcome=out.to_dict(), delivered=False)
                    j.record(device=name, job=jid, ref=ref, **out.to_dict())
                self._deliver(gw, name, jid, ref, out, say)
                return out
        else:
            if j:
                j.set(name, job=jid, ref=ref, phase="claimed", outcome=None, delivered=False)
            items = ", ".join("%s×%s" % (it.get("name") or it.get("code"), it.get("qty", 1)) for it in job.get("items") or [])
            say("Nhận đơn %s — %s" % (ref, items or "không có gói"))

        def on_buy():
            if j:
                j.set(name, phase="purchasing")

        flow = apimode.JobFlow(nav, gw, job, pool, steps, opts=opts,
                               status=lambda t: status("%s · %s" % (ref, t)), log=say,
                               abort=abort.is_set, on_purchase_start=on_buy)
        out = flow.run()
        if out.result in ("failed", "review"):
            flow._upload("error")           # ảnh màn hình lúc lỗi → người đối soát nhìn được
        if j:
            j.set(name, phase="finished", outcome=out.to_dict(), delivered=False)
            j.record(device=name, job=jid, ref=ref, **out.to_dict())
        self._deliver(gw, name, jid, ref, out, say)
        return out

    def _deliver(self, gw, name, jid, ref, out, say):
        """Gửi kết quả về gateway (idempotent). Trả True khi không cần gửi lại nữa."""
        def done():
            if self.journal:
                self.journal.set(name, delivered=True)
            return True

        if not out.result:                  # gateway đã tự đóng đơn → không có gì để báo
            say("Đơn %s: %s" % (ref, out.message))
            return done()
        try:
            r = call_retry(lambda: gw.result(jid, out.result, out.message, out.items),
                           tries=self.RESULT_TRIES, base=self.RESULT_BASE)
        except GatewayError as e:
            if e.status in (404, 409):      # gateway đã chốt trạng thái khác → không gửi lại
                say("Đơn %s: tool báo %s nhưng gateway đã chốt «%s»" % (ref, out.result, e.body.get("status") or e.error), "bad")
                return done()
            say("Đơn %s: CHƯA gửi được kết quả (%s) — sẽ tự gửi lại" % (ref, e.vi()), "bad")
            return False
        final = r.get("status") or out.result
        kind = "ok" if final == "done" else "bad"
        say("Đơn %s → %s%s" % (ref, RESULT_LABEL.get(final, final), (" — " + out.message) if out.message else ""), kind)
        return done()

    # ====================== nhịp tim ======================
    def _ensure_heartbeat(self):
        with self.lock:
            if self._hb and self._hb.is_alive():
                return
            self._hb_wake.clear()
            self._hb = threading.Thread(target=self._hb_loop, daemon=True)
            self._hb.start()

    def _hb_loop(self):
        while True:
            api = [(n, w) for n, w in list(self.workers.items()) if w["mode"] == "api" and w["thread"].is_alive()]
            if not api:
                return
            try:
                gw = self._gateway()
                devices = [{"name": n, "pool": w.get("pool") or "", "state": "busy" if w.get("job_id") else "free",
                            "job": w.get("job_id") or ""} for n, w in api]
                gw.heartbeat(devices, [w["job_id"] for _, w in api if w.get("job_id")])
            except Exception:
                pass                        # nhịp tim lỗi không được làm hỏng việc đang chạy
            self._hb_wake.wait(self.HEARTBEAT_EVERY)
