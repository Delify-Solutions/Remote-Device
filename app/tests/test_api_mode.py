#!/usr/bin/env python3
"""
Test đầu-cuối CHẾ ĐỘ API của tool:   ./.venv/bin/python app/tests/test_api_mode.py

  tool (code nạp THẬT: runner.py + apimode.py + gateway.py)
     │  điều khiển một iPHONE GIẢ (mô phỏng game: đăng nhập, OTP, cửa hàng, xác nhận mua…)
     ▼
  Topup Gateway THẬT (Web-topup-gateway, chạy tạm bằng `php -S` trên SQLite tạm)
     ▲
     │  bài test đóng vai SHOP (tạo đơn) và KHÁCH (nhập OTP)

Kiểm các nguyên tắc tiền: không mua trùng, không gõ đôi mật khẩu, không chắc thì `review`,
tool tắt giữa chừng không chạy lại đơn đã chạm bước mua, không nạp nhầm tài khoản khách trước…
Không đụng iPhone thật, không đụng dữ liệu thật.
"""
from __future__ import annotations
import json, os, shutil, signal, sqlite3, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
ROOT = os.path.dirname(APP)
GATEWAY_DIR = os.environ.get("GATEWAY_DIR", os.path.join(ROOT, "Web-topup-gateway"))
sys.path.insert(0, APP)

import numpy as np

import apimode
from apimode import Journal
from eyes import norm_text
from gateway import Gateway, GatewayError
from runner import Runner

# ---- chạy nhanh: bỏ các quãng nghỉ dành cho máy thật (vẫn giữ kiểm «Dừng ngay») ----
def _fast_sleep(sec, abort=None):
    if abort and abort():
        raise apimode.Aborted()
    time.sleep(min(max(sec, 0), 0.02))
apimode._sleep = _fast_sleep
apimode.STEP_GAP = 0
PROD_NEG_GRACE = apimode.JobFlow.NEG_GRACE        # hằng số THẬT — có một bài thử riêng chạy với nó (đồng hồ giả)
apimode.JobFlow.NEG_GRACE = 0.25         # (thật: 30 giây) thời gian chữ báo lỗi phải hiện ổn định trước khi được tin

PASS = FAIL = 0
def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ " + name)
    else:
        FAIL += 1
        print("  ✗ " + name + ("" if ctx is None else "   → " + (ctx if isinstance(ctx, str) else json.dumps(ctx, ensure_ascii=False, default=str))))

def wait_until(cond, timeout=20.0, step=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return bool(cond())


# ====================== iPhone giả ======================
SCREENS = {
    "home": "Màn hình chính Cài đặt Safari App Store",
    "spotlight": "Tìm kiếm",
    "login": "eFootball Đăng nhập Konami ID Email Mật khẩu",
    "login_error": "eFootball Konami ID. Email hoặc mật khẩu không chính xác. Đăng nhập",
    "otp": "Xác minh 2 bước. Nhập mã xác minh đã gửi tới email của bạn",
    "otp_error": "Mã không hợp lệ. Nhập mã xác minh",
    "main": "Trang chủ Cửa hàng Trận đấu Đội hình Đăng xuất",
    "shop": "Cửa hàng eFootball Coins 1,050 Coins 249.000đ Gói Khởi đầu 25.000đ Đăng xuất",
    "shop2": "Cửa hàng trang 2 Gói Huyền thoại 99.000đ Đăng xuất",
    "confirm": "Xác nhận mua. Mua ngay Huỷ",
    "result_ok": "Mua thành công! Đóng",
    "result_fail": "Thanh toán thất bại. Đóng",
    "owned": "Đã mua gói này rồi. Đóng",
    "frozen": "Đang xử lý",
}


class FakeGame:
    """Một iPhone đang chạy game. Màn hình = chuỗi chữ (thứ OCR sẽ đọc); thao tác làm đổi màn hình."""

    def __init__(self, accounts, **behavior):
        self.accounts = accounts        # {email: {"password", "otp": mã|None, "owned": set()}}
        self.behavior = behavior        # freeze_on_buy / fail_payment / no_logout / pointer_fail / sticky_result /
                                        # explode_click=N (cổng serial lỗi NGAY SAU lần bấm thứ N) / shot_fail_on=<màn> /
                                        # one_tap_buy (bấm vào gói là mua luôn, không hỏi lại) /
                                        # hide_under_pointer (con trỏ để yên trên màn thì che mất chữ kết quả) /
                                        # unavail_label (chữ «Đã mua gói này» in SẴN trên một ô gói khác) /
                                        # burst (board có lệnh gửi liền mạch như board thật) / shot_fail_once=<màn> /
                                        # change_before_click (màn hình đổi trong lúc con trỏ đang được đưa tới)
        self.gestures = []              # cử chỉ đã nhận: ("flick", hướng) / ("swipe", x1, y1, x2, y2) / ("hold", x, y, giây)
        self.on_purchase = None         # gọi ngay khi game ghi nhận một lần mua (để test chen việc vào đúng lúc đó)
        self.positions = {}             # nhãn -> toạ độ cố định
        self.screen = "home"
        self.focus = None
        self.typed = {"user": "", "pass": "", "otp": "", "spot": ""}
        self.user = None                # tài khoản đang đăng nhập trong game
        self.pending_user = None
        self.pending_pkg = None
        self.purchases = []             # [(email, mã gói)] — tiền thật đã tiêu
        self.keylog = []                # mọi chuỗi đã gõ
        self.clicks = 0
        self.pointer = None
        self.targets = {}               # (x,y) -> nhãn đã dò thấy
        self.ble = True
        self.can_shot = True
        self.lock = threading.Lock()

    def text(self):
        self.reads = getattr(self, "reads", 0) + 1
        if self.screen == "frozen" and getattr(self, "_slow", 0) > 0:     # game đang xử lý lần mua: vài lần đọc sau mới hiện kết quả
            self._slow -= 1
            if self._slow == 0:
                self.screen = "result_ok"
        t = SCREENS[self.screen]
        if self.screen == "result_ok" and self.behavior.get("sticky_result"):
            # hộp thoại kẹt nằm ĐÈ lên cửa hàng: chữ của cửa hàng và nút mua phía sau vẫn đọc được, vẫn «bấm» được
            t = SCREENS["result_ok"] + " " + SCREENS["shop"] + " Mua ngay"
        if self.behavior.get("unavail_label") and self.screen in ("shop", "confirm", "result_ok", "frozen"):
            t += " Ưu đãi tuần: Đã mua gói này rồi"          # nhãn in SẴN trên ô của một gói khác
        miss = self.behavior.get("ocr_miss")       # (màn hình, chữ bị đọc hụt, số lần hụt, [bỏ qua mấy lần đọc đầu])
        if miss and miss[0] == self.screen and miss[1] in t:
            skip = miss[3] if len(miss) > 3 else 0
            if skip > 0:
                self.behavior["ocr_miss"] = (miss[0], miss[1], miss[2], skip - 1)
            elif miss[2] > 0:
                self.behavior["ocr_miss"] = (miss[0], miss[1], miss[2] - 1, 0)
                t = t.replace(miss[1], "")
        if self.behavior.get("hide_under_pointer") and self.pointer is not None:
            t = t.replace("Mua thành công!", "")              # con trỏ đang nằm đè lên đúng dòng chữ kết quả
        return t

    def swipe(self, direction):
        if self.screen == "shop" and direction == "left":
            self.screen = "shop2"
        elif self.screen == "shop2" and direction == "right":
            self.screen = "shop"

    # ---- bàn phím ----
    def type(self, s):
        self.keylog.append(s)
        if self.focus:
            self.typed[self.focus] += s

    def key(self, name):
        if name == "back":
            if self.focus:
                self.typed[self.focus] = ""
        elif name == "tab":
            if self.screen in ("login", "login_error") and self.focus == "user":
                self.focus = "pass"
        elif name in ("enter", "return"):
            self._enter()

    def combo(self, keys):
        if keys == "gui h":
            self.screen, self.focus = "home", None
        elif keys == "gui space":
            self.screen, self.focus = "spotlight", "spot"
            self.typed["spot"] = ""

    def _enter(self):
        if self.screen == "spotlight":
            if self.typed["spot"].strip().lower() == "efootball":
                # game mở lại đúng trạng thái cũ: còn phiên → vào thẳng trang chủ
                self.screen, self.focus = ("main", None) if self.user else ("login", None)
                self.typed.update(user="", **{"pass": ""})
        elif self.screen in ("login", "login_error"):
            u, p = self.typed["user"], self.typed["pass"]
            acc = self.accounts.get(u)
            self.typed.update(user="", **{"pass": ""})
            if not acc or acc["password"] != p:
                self.screen, self.focus = "login_error", None
            elif acc.get("otp"):
                self.pending_user = u
                self.screen, self.focus = "otp", "otp"
                self.typed["otp"] = ""
            else:
                self.user, self.screen, self.focus = u, "main", None
        elif self.screen in ("otp", "otp_error"):
            acc = self.accounts[self.pending_user]
            if self.typed["otp"] == acc["otp"]:
                self.user, self.screen, self.focus = self.pending_user, "main", None
            else:
                self.screen, self.focus = "otp_error", "otp"
            self.typed["otp"] = ""

    # ---- chuột ----
    def click(self):
        self.clicks += 1
        label = self.targets.get(self.pointer)
        if label:
            self.tap(label)

    def tap(self, label):
        s = self.screen
        if s in ("login", "login_error") and "dangnhap" in label:
            self.screen, self.focus = "login", "user"
        elif s == "main" and "cuahang" in label:
            self.screen = "shop"
        elif s in ("main", "shop", "shop2") and "dangxuat" in label:
            if not self.behavior.get("no_logout"):
                self.user, self.screen, self.focus = None, "login", None
        elif s == "shop" and ("1050" in label or "1,050" in label):
            if self.behavior.get("one_tap_buy"):
                self.purchases.append((self.user, "coin_1050"))
                self.screen = "result_ok"
            else:
                self.pending_pkg, self.screen = "coin_1050", "confirm"
        elif s == "shop2" and "huyenthoai" in label:
            self.pending_pkg, self.screen = "legend", "confirm"
        elif s == "shop" and "khoidau" in label:
            if "starter" in self.accounts[self.user]["owned"]:
                self.screen = "owned"
            else:
                self.pending_pkg, self.screen = "starter", "confirm"
        elif s == "confirm" and "muangay" in label:
            if self.behavior.get("freeze_on_buy"):
                self.screen = "frozen"              # treo: không biết đã trừ tiền hay chưa
            elif self.behavior.get("fail_payment"):
                self.screen = "result_fail"
            else:
                self.purchases.append((self.user, self.pending_pkg))
                if self.pending_pkg == "starter":
                    self.accounts[self.user]["owned"].add("starter")
                self.screen = "result_ok"
                if self.behavior.get("slow_result"):                  # kết quả hiện ra CHẬM (game còn «Đang xử lý»)
                    self.screen, self._slow = "frozen", int(self.behavior["slow_result"])
                if self.on_purchase:
                    self.on_purchase()
        elif s in ("result_ok", "result_fail", "owned") and "dong" in label:
            if not (s == "result_ok" and self.behavior.get("sticky_result")):    # hộp thoại «mua thành công» kẹt, không đóng được
                self.screen = "shop"


class FakeHands:
    """Nhận đúng các lệnh của firmware ESP32 (type/key/combo/click/status)."""

    def __init__(self, game):
        self.g = game

    def send(self, cmd, wait=0.5):
        g = self.g
        with g.lock:
            if cmd == "status":
                return "OK ble=connected" if g.ble else "OK ble=disconnected"
            if not g.ble:
                return "ERR not-connected"
            if cmd == "home":                                   # ghim con trỏ về góc → không còn che gì
                g.pointer = None
                return "OK home"
            if cmd.startswith("move "):
                return "OK move"
            if cmd.startswith("type "):
                g.type(cmd[5:])
                return "OK type %d" % len(cmd[5:])
            if cmd.startswith("key "):
                g.key(cmd[4:])
                return "OK key " + cmd[4:]
            if cmd.startswith("combo "):
                g.combo(cmd[6:])
                return "OK combo"
            if cmd == "click":
                g.click()
                if g.behavior.get("explode_click") == g.clicks:      # lệnh ĐÃ tới iPhone rồi cổng serial mới lỗi
                    raise OSError("device reports readiness to read but returned no data (giả lập)")
                return "OK click"
            return "ERR cmd?"

    def wait_connected(self, timeout=15.0):
        return self.g.ble


class BurstHands(FakeHands):
    """Board có lệnh gửi liền mạch (như board thật) → code đi nhánh `burst` của apimode.click()."""
    WAKE = ("move 1 0", "move -1 0")

    def burst(self, cmds, wait=1.0):
        return [self.send(c) for c in cmds]


class FakeEyes:
    def __init__(self, game):
        self.g = game

    def screenshot(self):
        if not self.g.can_shot or self.g.behavior.get("shot_fail_on") == self.g.screen:
            raise RuntimeError("Chụp màn thất bại (máy giả)")
        if self.g.behavior.get("shot_fail_once") == self.g.screen:   # trục trặc thoáng qua: hỏng đúng một lần
            self.g.behavior["shot_fail_once"] = None
            raise RuntimeError("Chụp màn thất bại (máy giả, một lần)")
        img = np.zeros((80, 45, 3), dtype=np.uint8)
        img[:, :, 1] = (hash(self.g.screen) % 200) + 20
        return img

    def read_text(self, img=None, **kw):
        return self.g.text()

    def find_text(self, needle, img=None, **kw):
        n = norm_text(needle).replace(" ", "")
        if not n or n not in norm_text(self.g.text()).replace(" ", ""):
            return None
        pos = self.g.positions.setdefault(n, (11 + 60 * len(self.g.positions), 40 + len(n)))    # mỗi nhãn một chỗ cố định
        self.g.targets[pos] = n
        return pos


class FakeNav:
    def __init__(self, game):
        self.g = game
        self.h = (BurstHands if game.behavior.get("burst") else FakeHands)(game)
        self.e = FakeEyes(game)

    def tap_at(self, x, y, click=True, verify=None, **kw):
        if self.g.behavior.get("pointer_fail"):
            return False
        self.g.pointer = (x, y)
        if self.g.behavior.get("change_before_click"):          # trong lúc đưa con trỏ tới, màn hình đã đổi
            self.g.screen = "frozen"
        if verify is not None and not verify(self.e.screenshot()):    # thứ cần bấm không còn ở đó → không bấm
            return False
        if click:
            self.h.send("click")
        return True

    def flick(self, direction, at=None):
        if self.g.behavior.get("pointer_fail"):
            return False
        self.g.gestures.append(("flick", direction))
        self.g.swipe(direction)
        return True

    def swipe(self, x1, y1, x2, y2):
        if self.g.behavior.get("pointer_fail"):
            return False
        self.g.gestures.append(("swipe", x1, y1, x2, y2))
        return True

    def hold_at(self, x, y, seconds=1.0, verify=None):
        if self.g.behavior.get("pointer_fail"):
            return False
        if self.g.behavior.get("change_before_click"):
            self.g.screen = "frozen"
        if verify is not None and not verify(self.e.screenshot()):
            return False
        self.g.gestures.append(("hold", x, y, seconds))
        return True

    def ensure_english(self, **kw):
        self.kb_calls = getattr(self, "kb_calls", 0) + 1
        if self.g.behavior.get("kb_raise", 0) >= self.kb_calls:
            raise RuntimeError("Chụp màn thất bại (máy giả)")
        return (not self.g.behavior.get("kb_telex")), "afaf"


# ====================== gateway tạm ======================
FIXTURE = r'''<?php
require getenv("GW_DIR") . "/src/bootstrap.php";
Schema::migrate();
$cfg = Pools::defaults();
$cfg["otp"] = ["enabled" => true, "timeout" => 60, "max_requests" => 2, "hint" => ""];
$cfg["rules"] = [
    ["when" => "logged_out", "value" => "Konami ID"],
    ["when" => "login_success", "value" => "Trang chủ"], ["when" => "login_fail", "value" => "không chính xác", "note" => "sai tài khoản hoặc mật khẩu"],
    ["when" => "need_otp", "value" => "mã xác minh"], ["when" => "otp_wrong", "value" => "Mã không hợp lệ"],
    ["when" => "purchase_success", "value" => "Mua thành công"], ["when" => "purchase_fail", "value" => "Thanh toán thất bại"],
    ["when" => "package_unavailable", "value" => "Đã mua gói này"],
];
$cfg["login_steps"] = [
    ["type" => "launch", "value" => "efootball"], ["type" => "wait_text", "value" => "Konami ID @3s"],
    ["type" => "tap_text", "value" => "Đăng nhập"], ["type" => "type", "value" => "{{username}}"],
    ["type" => "key", "value" => "tab"], ["type" => "type", "value" => "{{password}}"], ["type" => "key", "value" => "enter"],
];
$cfg["nav_steps"] = [["type" => "tap_text", "value" => "Cửa hàng"]];
$cfg["purchase_steps"] = [["type" => "tap_text", "value" => "{{package.ocr_text}}"], ["type" => "tap_text", "value" => "Mua ngay"]];
$cfg["after_purchase_steps"] = [["type" => "tap_text", "value" => "Đóng"]];
// «Đóng» là bước TUỲ CHỌN: có hộp thoại thì đóng, không có thì bỏ qua → dùng được từ mọi màn hình
$cfg["finish_steps"] = [["type" => "tap_text", "value" => "Đóng", "optional" => true], ["type" => "tap_text", "value" => "Đăng xuất"],
                        ["type" => "wait_text", "value" => "Konami ID @3s"], ["type" => "home", "value" => ""]];
$id = Pools::save(null, "game-test", "Game test", "eFootball", true, $cfg);
if (is_string($id)) { fwrite(STDERR, $id); exit(1); }
Pools::savePackages($id, [
    ["code" => "coin_1050", "name" => "1050 Coins", "ocr_text" => "1050|1,050", "price_text" => "249.000", "limit_type" => "multi", "max_qty" => 5, "active" => true],
    ["code" => "starter", "name" => "Gói Khởi đầu", "ocr_text" => "Khởi đầu", "price_text" => "25.000", "limit_type" => "once", "active" => true],
    ["code" => "ghost", "name" => "Gói không có trên màn", "ocr_text" => "Kim cương vô cực", "limit_type" => "multi", "active" => true],
]);
// pool cấu hình DỞ: không có luật nào → tool phải từ chối chạy
$bare = $cfg; $bare["rules"] = [["when" => "login_fail", "value" => "không chính xác"]];
$bid = Pools::save(null, "game-bare", "Game thiếu luật", "eFootball", true, $bare);
Pools::savePackages($bid, [["code" => "coin_1050", "name" => "1050 Coins", "ocr_text" => "1050|1,050", "limit_type" => "multi", "max_qty" => 5, "active" => true]]);
// pool có gói nằm ở TRANG 2 của cửa hàng: phải vuốt mới thấy; thêm một bước bấm giữ (tuỳ chọn)
$sw = $cfg;
$sw["nav_steps"] = [["type" => "tap_text", "value" => "Cửa hàng"], ["type" => "swipe", "value" => "left"],
                    ["type" => "hold_text", "value" => "trang 2 @0.5s", "optional" => true]];
$sid = Pools::save(null, "game-swipe", "Game vuốt trang", "eFootball", true, $sw);
if (is_string($sid)) { fwrite(STDERR, $sid); exit(1); }
Pools::savePackages($sid, [["code" => "legend", "name" => "Gói Huyền thoại", "ocr_text" => "Huyền thoại", "limit_type" => "multi", "max_qty" => 5, "active" => true]]);
$shop = Keys::create("shop", "Shop test");
$tool = Keys::create("tool", "Farm test");
echo json_encode(["shop" => $shop["plain"], "tool" => $tool["plain"]]);
'''


class TempGateway:
    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="gw-tool-test-")
        self.port = 19000 + (os.getpid() % 800)
        self.url = "http://127.0.0.1:%d" % self.port
        self.db = os.path.join(self.tmp, "gw.sqlite")
        os.makedirs(os.path.join(self.tmp, "files"))
        self.env = dict(os.environ, GW_DIR=GATEWAY_DIR, APP_KEY="test-key-0123456789abcdef", APP_URL=self.url, APP_DEBUG="true",
                        DB_DSN="sqlite:" + self.db, STORAGE_DIR=os.path.join(self.tmp, "files"), PHP_CLI_SERVER_WORKERS="8")
        fx = os.path.join(self.tmp, "fixture.php")
        with open(fx, "w", encoding="utf-8") as f:
            f.write(FIXTURE)
        r = subprocess.run(["php", fx], env=self.env, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("Không dựng được gateway tạm: " + r.stderr + r.stdout)
        keys = json.loads(r.stdout)
        self.shop_key, self.tool_key = keys["shop"], keys["tool"]
        self.log = open(os.path.join(self.tmp, "server.log"), "w")
        # start_new_session: máy chủ + các worker con nằm chung một nhóm tiến trình → tắt được cả nhóm (không để rơi rớt)
        self.proc = subprocess.Popen(["php", "-S", "127.0.0.1:%d" % self.port, "-t", os.path.join(GATEWAY_DIR, "public"),
                                      os.path.join(GATEWAY_DIR, "public", "index.php")],
                                     env=self.env, stdout=self.log, stderr=self.log, cwd=GATEWAY_DIR, start_new_session=True)
        if not wait_until(self._up, 10):
            raise RuntimeError("Gateway tạm không lên")

    def _up(self):
        try:
            with urllib.request.urlopen(self.url + "/healthz", timeout=1) as r:
                return json.loads(r.read()).get("ok") is True
        except Exception:
            return False

    def shop(self, method, path, body=None):
        req = urllib.request.Request(self.url + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": "Bearer " + self.shop_key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def new_job(self, ref, user, password, items, pool="game-test"):
        code, j = self.shop("POST", "/api/shop/jobs", {"pool": pool, "ref": ref,
                                                        "login": {"username": user, "password": password}, "items": items})
        assert code == 201, (code, j)
        return j["job"]["id"]

    def job(self, jid):
        return self.shop("GET", "/api/shop/jobs/" + jid)[1]["job"]

    def wait_job(self, jid, statuses, timeout=40):
        box = {}
        def cond():
            box["j"] = self.job(jid)
            return box["j"]["status"] in statuses
        wait_until(cond, timeout, 0.15)
        return box["j"]

    def sql(self, q, args=()):
        con = sqlite3.connect(self.db, timeout=5)
        try:
            rows = con.execute(q, args).fetchall()
            con.commit()
            return rows
        finally:
            con.close()

    def close(self):
        for sig in (signal.SIGTERM, signal.SIGKILL):        # cả nhóm: tiến trình chính + worker con
            try:
                os.killpg(self.proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                break
            try:
                self.proc.wait(3)
                break
            except Exception:
                continue
        self.log.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


def customer(gw, jid, codes):
    """Đóng vai KHÁCH: mỗi lần đơn đòi OTP thì nhập mã kế tiếp trong `codes`."""
    def run():
        answered = 0
        end = time.time() + 60
        while time.time() < end:
            j = gw.job(jid)
            if j["status"] in ("done", "failed", "review", "cancelled", "expired"):
                return
            if j["status"] == "need_otp" and j["otp"]["state"] == "waiting" and j["otp"]["seq"] > answered and answered < len(codes):
                gw.shop("POST", "/api/shop/jobs/%s/otp" % jid, {"otp": codes[answered]})
                answered = j["otp"]["seq"]
            time.sleep(0.15)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


class Rig:
    """Một máy giả + bộ chạy thật, nối với gateway tạm."""
    N = 0

    def __init__(self, gw, game, name=None, gateway_cls=Gateway, local_steps=None, journal_dir=None, pool="game-test", check_keyboard=False):
        Rig.N += 1
        self.gw, self.game = gw, game
        self.name = name or "fake-%02d" % Rig.N
        self.logs = []
        self.jdir = journal_dir or tempfile.mkdtemp(prefix="tool-journal-")
        self.journal = Journal(self.jdir)
        self.nav = FakeNav(game)
        self.client = gateway_cls(gw.url, gw.tool_key)
        self.runner = Runner(lambda n: self.nav, gateway_factory=lambda: self.client, journal=self.journal,
                             on_log=lambda e: self.logs.append(e))
        r = self.runner
        r.POLL_IDLE, r.NOT_READY_WAIT, r.HEARTBEAT_EVERY, r.RESULT_BASE, r.RESULT_TRIES, r.OTP_WAIT = 0.2, 0.3, 0.4, 0.05, 2, 1
        r.CLEAR_WAIT = 0.3
        self.group = {"id": "g-test", "mode": "api",
                      "api": {"pool": pool, "steps": local_steps or {}, "login_wait": 5, "purchase_wait": 5, "check_keyboard": check_keyboard}}

    def start(self):
        return self.runner.start_machine(self.name, self.group)

    def status(self):
        return self.runner.status().get(self.name, {})

    def running(self):
        return self.runner.is_running(self.name)

    def stop(self, force=False, wait=10):
        self.runner.stop_machine(self.name, force)
        wait_until(lambda: not self.running(), wait)

    def text(self):
        return " | ".join(e["text"] for e in self.logs)


def accounts():
    return {
        "a@test.vn": {"password": "PassA#1", "otp": None, "owned": set()},
        "otp@test.vn": {"password": "PassB#2", "otp": "654321", "owned": set()},
        "owned@test.vn": {"password": "PassC#3", "otp": None, "owned": {"starter"}},
    }


def main():
    if not os.path.isdir(GATEWAY_DIR) or shutil.which("php") is None:
        print("BỎ QUA: cần thư mục Web-topup-gateway và lệnh php.")
        return 0
    gw = TempGateway()
    rigs = []
    try:
        run_all(gw, rigs)
    finally:
        for r in rigs:
            r.runner.stop_all(force=True)
        time.sleep(0.3)
        gw.close()
        for r in rigs:
            shutil.rmtree(r.jdir, ignore_errors=True)
    print("\n" + ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if FAIL == 0 else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 0 if FAIL == 0 else 1


def run_all(gw, rigs):
    def rig(game, **kw):
        r = Rig(gw, game, **kw)
        rigs.append(r)
        return r

    print("\n== 0. Kết nối + cấu hình pool ==")
    c = Gateway(gw.url, gw.tool_key)
    ok(c.ping().get("ok") is True, "tool ping gateway bằng khoá Tool")
    try:
        Gateway(gw.url, "gwt_sai").ping()
        ok(False, "sai khoá phải bị từ chối")
    except GatewayError as e:
        ok(e.status == 401 and "khoá" in e.vi(), "sai khoá → 401, có câu báo tiếng Việt", e.vi())
    pools = c.pools()
    ok(any(p.get("code") == "game-test" for p in pools), "tool lấy được danh sách pool để chọn", pools)
    pool = c.pool("game-test")
    steps = apimode.effective_steps(pool, {})
    ok([len(steps[p]) for p in apimode.PHASES] == [7, 2, 1, 2, 1, 4], "đủ 6 giai đoạn bước từ gateway (OTP mặc định: gõ mã + Enter)",
       {p: len(steps[p]) for p in apimode.PHASES})
    ok(steps["finish"][0].get("optional") is True and "optional" not in steps["finish"][1], "bước «bỏ qua nếu lỗi» của gateway được giữ đúng", steps["finish"][:2])
    ok(steps["login"][1] == {"type": "wait_text", "text": "Konami ID", "timeout": 3}, "bước «chờ chữ @3s» đổi đúng thời gian chờ", steps["login"][1])
    over = apimode.effective_steps(pool, {"purchase": [{"type": "tap", "x": 1, "y": 2}]})
    ok(over["purchase"] == [{"type": "tap", "x": 1, "y": 2}] and len(over["login"]) == 7, "nhóm ghi đè riêng 1 giai đoạn, giai đoạn khác vẫn lấy của gateway")
    ok(apimode.validate(pool, steps) == [], "pool đủ luật + đủ bước → tool chịu chạy", apimode.validate(pool, steps))
    bare = c.pool("game-bare")
    miss = apimode.validate(bare, apimode.effective_steps(bare, {}))
    ok(len(miss) == 3 and all("thiếu luật" in m for m in miss), "pool thiếu 3 luật bắt buộc (chưa đăng nhập / đăng nhập thành công / nạp thành công) → bị từ chối", miss)
    ok(any("chưa có bước" in m for m in apimode.validate(pool, dict(steps, finish=[]))), "thiếu bước kết thúc đơn (đăng xuất) → bị từ chối")

    print("\n== 1. Đơn thường: đăng nhập → mua 2 gói → bill → đăng xuất ==")
    g = FakeGame(accounts())
    r = rig(g)
    j1 = gw.new_job("T-001", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 2}])
    r.start()
    job = gw.wait_job(j1, ("done", "failed", "review"))
    ok(job["status"] == "done", "đơn hoàn tất", job)
    ok(g.purchases == [("a@test.vn", "coin_1050")] * 2, "game ghi nhận đúng 2 lần mua cho đúng tài khoản", g.purchases)
    ok(len([i for i in job["images"] if i["kind"] == "bill"]) == 2, "gửi 2 ảnh bill (mỗi lần mua một ảnh)", job["images"])
    ok(job["result"] == [{"code": "coin_1050", "qty_done": 2, "status": "done", "message": ""}], "kết quả từng gói đúng", job["result"])
    ok(g.keylog.count("a@test.vn") == 1 and g.keylog.count("PassA#1") == 1, "tài khoản và mật khẩu chỉ được gõ ĐÚNG MỘT LẦN", g.keylog)
    ok(wait_until(lambda: g.user is None and g.screen in ("home", "login"), 5), "xong đơn: đã đăng xuất (game về màn hình chưa đăng nhập)", (g.user, g.screen))
    ok(wait_until(lambda: r.status().get("status") == "Chờ đơn", 5) and r.running(), "máy quay lại chờ đơn tiếp", r.status())
    ok(r.status()["counts"] == {"done": 1, "failed": 0, "review": 0}, "bộ đếm của máy đúng", r.status())
    dev = gw.sql("SELECT state, pool_code FROM devices WHERE name=?", (r.name,))
    ok(dev == [("free", "game-test")], "gateway thấy máy đang TRỐNG (nhịp tim/claim)", dev)
    ok(gw.sql("SELECT login_enc, otp_enc FROM jobs WHERE pid=?", (j1,)) == [(None, None)], "gateway đã xoá thông tin đăng nhập của đơn")

    print("\n== 2. OTP: khách nhập SAI lần đầu, đúng lần hai ==")
    j2 = gw.new_job("T-002", "otp@test.vn", "PassB#2", [{"code": "coin_1050", "qty": 1}])
    customer(gw, j2, ["111111", "654321"])
    job = gw.wait_job(j2, ("done", "failed", "review"))
    ok(job["status"] == "done" and job["otp"]["seq"] == 2, "sai OTP → xin lại → đúng → hoàn tất (2 lần xin)", job)
    ok(g.purchases[-1] == ("otp@test.vn", "coin_1050") and len(g.purchases) == 3, "mua đúng 1 gói cho tài khoản có OTP", g.purchases)
    ok("654321" in g.keylog and "111111" in g.keylog, "tool đã gõ cả hai mã khách gửi")

    print("\n== 3. Sai mật khẩu → thất bại (chưa nạp), máy vẫn chạy tiếp ==")
    j3 = gw.new_job("T-003", "a@test.vn", "SaiMatKhau", [{"code": "coin_1050", "qty": 1}])
    job = gw.wait_job(j3, ("done", "failed", "review"))
    ok(job["status"] == "failed" and "Đăng nhập thất bại" in (job["message"] or ""), "báo failed kèm lý do", job["message"])
    ok(len(g.purchases) == 3, "không mua gì")
    ok([i["kind"] for i in job["images"]] == ["error"], "có ảnh màn hình lúc lỗi để người đối soát xem", job["images"])
    ok(wait_until(lambda: r.status().get("status") == "Chờ đơn", 8) and r.running(), "lỗi do khách → máy KHÔNG tự dừng", r.status())

    print("\n== 4. Gói 1-lần đã mua từ trước → thất bại (chưa nạp) ==")
    j4 = gw.new_job("T-004", "owned@test.vn", "PassC#3", [{"code": "starter", "qty": 1}])
    job = gw.wait_job(j4, ("done", "failed", "review"))
    ok(job["status"] == "failed" and job["result"][0]["status"] == "unavailable", "gói không mua được → failed, gói đánh dấu unavailable", job)
    ok(len(g.purchases) == 3, "không mua gì")

    print("\n== 5. Mua được 1 phần (1 gói mua được, 1 gói đã mua) → chờ đối soát + máy tự dừng ==")
    j5 = gw.new_job("T-005", "owned@test.vn", "PassC#3", [{"code": "coin_1050", "qty": 1}, {"code": "starter", "qty": 1}])
    job = gw.wait_job(j5, ("done", "failed", "review"))
    ok(job["status"] == "review" and "1/2" in (job["message"] or ""), "nạp 1/2 → review", job["message"])
    ok([(x["code"], x["qty_done"], x["status"]) for x in job["result"]] == [("coin_1050", 1, "done"), ("starter", 0, "unavailable")], "chi tiết từng gói đúng", job["result"])
    ok(len(g.purchases) == 4, "đúng 1 lần mua mới")
    ok(wait_until(lambda: not r.running(), 8) and r.status()["status"].startswith("DỪNG"), "có đơn cần đối soát → máy TỰ DỪNG chờ người", r.status())

    print("\n== 6. Bấm mua xong màn hình treo (không rõ đã trừ tiền chưa) → review, không mua tiếp ==")
    g6 = FakeGame(accounts(), freeze_on_buy=True)
    r6 = rig(g6)
    j6 = gw.new_job("T-006", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 3}])
    r6.start()
    job = gw.wait_job(j6, ("done", "failed", "review"))
    ok(job["status"] == "review" and "Không xác nhận được" in (job["message"] or ""), "không chắc → review (KHÔNG báo failed)", job["message"])
    ok(g6.clicks == 4, "dừng ngay sau lần bấm mua đầu tiên, không bấm mua lần 2-3", g6.clicks)
    ok(wait_until(lambda: not r6.running(), 8), "máy tự dừng")

    print("\n== 7. Game báo rõ «thanh toán thất bại» → failed (chắc chắn chưa trừ tiền) ==")
    g7 = FakeGame(accounts(), fail_payment=True)
    r7 = rig(g7)
    j7 = gw.new_job("T-007", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    r7.start()
    job = gw.wait_job(j7, ("done", "failed", "review"))
    ok(job["status"] == "failed" and "nạp thất bại" in (job["message"] or ""), "báo failed kèm lý do", job["message"])
    ok(wait_until(lambda: r7.status().get("status") == "Chờ đơn", 8) and r7.running(), "máy chạy tiếp", r7.status())

    print("\n== 8. Không tìm thấy gói trên màn hình (lỗi cấu hình/máy) 2 đơn liền → máy tự dừng ==")
    j8a = gw.new_job("T-008a", "a@test.vn", "PassA#1", [{"code": "ghost", "qty": 1}])
    job = gw.wait_job(j8a, ("done", "failed", "review"))
    ok(job["status"] == "failed" and "không bắt đầu mua được" in (job["message"] or ""), "không thấy gói → failed (chưa chạm gì)", job["message"])
    ok(r7.running(), "lỗi máy lần 1 → vẫn chạy")
    j8b = gw.new_job("T-008b", "a@test.vn", "PassA#1", [{"code": "ghost", "qty": 1}])
    gw.wait_job(j8b, ("done", "failed", "review"))
    ok(wait_until(lambda: not r7.running(), 8) and "liên tiếp" in r7.status()["status"], "lỗi máy 2 đơn liên tiếp → TỰ DỪNG", r7.status())
    ok(g7.purchases == [], "không mua gì")

    print("\n== 9. Dừng thường khi đang làm dở: làm nốt đơn, KHÔNG nhận đơn mới ==")
    g9 = FakeGame(accounts())
    r9 = rig(g9)
    j9 = gw.new_job("T-009", "otp@test.vn", "PassB#2", [{"code": "coin_1050", "qty": 1}])
    r9.start()
    gw.wait_job(j9, ("need_otp",))
    j9b = gw.new_job("T-009b", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    r9.runner.stop_machine(r9.name)            # dừng thường
    ok(r9.running() and r9.status().get("stopping") is True, "đang chờ OTP mà bấm Dừng → máy ở trạng thái «đang dừng…», chưa bỏ đơn", r9.status())
    customer(gw, j9, ["654321"])
    job = gw.wait_job(j9, ("done", "failed", "review"))
    ok(job["status"] == "done", "đơn đang dở vẫn được làm XONG", job)
    ok(wait_until(lambda: not r9.running(), 8), "xong đơn thì máy dừng hẳn")
    ok(gw.job(j9b)["status"] == "queued", "đơn mới KHÔNG bị máy đang dừng nhận", gw.job(j9b)["status"])

    print("\n== 10. Dừng NGAY khi chưa tới bước mua → failed (chưa nạp) ==")
    gw.shop("POST", "/api/shop/jobs/%s/cancel" % j9b)
    g10 = FakeGame(accounts())
    r10 = rig(g10)
    j10 = gw.new_job("T-010", "otp@test.vn", "PassB#2", [{"code": "coin_1050", "qty": 1}])
    r10.start()
    gw.wait_job(j10, ("need_otp",))
    r10.stop(force=True)
    job = gw.wait_job(j10, ("done", "failed", "review"), 10)
    ok(job["status"] == "failed" and "dừng" in (job["message"] or "").lower(), "dừng ngay trước bước mua → failed", job["message"])
    ok(g10.purchases == [] and not r10.running(), "không mua gì, máy đã dừng")

    print("\n== 11. Tool tắt giữa chừng ==")
    # 11a: tắt TRƯỚC khi chạm bước mua → lần sau làm lại từ đầu
    g11 = FakeGame(accounts())
    r11 = rig(g11)
    j11 = gw.new_job("T-011", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    held = r11.client.claim(r11.name, "game-test")["job"]
    r11.journal.set(r11.name, job=held["id"], ref="T-011", phase="claimed", outcome=None, delivered=False)
    r11.start()
    job = gw.wait_job(j11, ("done", "failed", "review"))
    ok(job["status"] == "done" and g11.purchases == [("a@test.vn", "coin_1050")], "tắt trước khi mua → mở lại làm lại từ đầu, mua đúng 1 lần", (job["status"], g11.purchases))
    r11.stop()
    # 11b: tắt SAU khi đã chạm bước mua → tuyệt đối không chạy lại, báo review
    g12 = FakeGame(accounts())
    r12 = rig(g12)
    j12 = gw.new_job("T-012", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    held = r12.client.claim(r12.name, "game-test")["job"]
    r12.journal.set(r12.name, job=held["id"], ref="T-012", phase="purchasing", outcome=None, delivered=False)
    r12.start()
    job = gw.wait_job(j12, ("done", "failed", "review"))
    ok(job["status"] == "review" and "giữa lúc mua" in (job["message"] or ""), "tắt giữa lúc mua → review", job["message"])
    ok(g12.purchases == [] and g12.keylog == [], "KHÔNG đăng nhập/mua lại (không chạm vào máy)", (g12.purchases, g12.keylog))
    ok(wait_until(lambda: not r12.running(), 8), "máy dừng chờ người kiểm tra")
    # 11c: gateway nói máy đang giữ đơn, tool không có ghi chép, và đơn ĐÃ có tiến độ (ai đó đã bắt đầu làm) → review
    g13 = FakeGame(accounts())
    r13 = rig(g13)
    j13 = gw.new_job("T-013", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    r13.client.claim(r13.name, "game-test")
    r13.client.progress(j13, "login", "Đang đăng nhập")
    r13.start()
    job = gw.wait_job(j13, ("done", "failed", "review"))
    ok(job["status"] == "review" and g13.purchases == [] and "PassA#1" not in g13.keylog, "đơn đang chạy dở mà tool mất ghi chép → review, không đăng nhập, không mua", (job["message"], g13.keylog))
    ok(wait_until(lambda: not r13.running(), 8), "máy dừng chờ người kiểm tra")
    # 11d: phản hồi «nhận đơn» không tới tool (mất mạng đúng lúc đó) → đơn CHƯA ai đụng tới → lần sau làm bình thường
    class LostClaim(Gateway):
        lost = 1
        def claim(self, *a, **k):
            r = super().claim(*a, **k)
            if r.get("job") and LostClaim.lost > 0:
                LostClaim.lost -= 1
                raise GatewayError(0, "network", "mất phản hồi (giả lập)")
            return r
    g13d = FakeGame(accounts())
    r13d = rig(g13d, gateway_cls=LostClaim)
    j13d = gw.new_job("T-013d", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    r13d.start()
    job = gw.wait_job(j13d, ("done", "failed", "review"))
    ok(job["status"] == "done" and g13d.purchases == [("a@test.vn", "coin_1050")] and LostClaim.lost == 0,
       "mất phản hồi «nhận đơn» → đơn KHÔNG bị đẩy sang đối soát oan, vẫn nạp đúng 1 lần", (job["status"], job["message"], g13d.purchases))
    ok("lần giao trước chưa tới tool" in r13d.text(), "nhật ký ghi rõ là nhận lại đơn chưa bắt đầu")
    r13d.stop()

    print("\n== 12. Máy chưa sẵn sàng thì KHÔNG nhận đơn ==")
    g14 = FakeGame(accounts())
    g14.ble = False
    r14 = rig(g14)
    j14 = gw.new_job("T-014", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    r14.start()
    time.sleep(1.5)
    ok(gw.job(j14)["status"] == "queued" and "Bluetooth" in r14.status().get("status", ""), "Bluetooth rớt → không xin việc, đơn vẫn nằm chờ", r14.status())
    g14.ble = True
    g14.can_shot = False
    time.sleep(1.2)
    ok(gw.job(j14)["status"] == "queued" and "chụp" in r14.status().get("status", ""), "không chụp được màn → cũng không xin việc", r14.status())
    g14.can_shot = True
    job = gw.wait_job(j14, ("done", "failed", "review"))
    ok(job["status"] == "done", "máy sẵn sàng lại → tự nhận và làm xong đơn", job["status"])
    r14.stop()

    print("\n== 13. Còn phiên của khách trước (đăng xuất hỏng) → KHÔNG nạp nhầm, KHÔNG tiêu tốn đơn của khách sau ==")
    # nhóm dùng bước đăng nhập riêng KHÔNG có bước chờ màn hình đăng nhập (cấu hình ẩu) + bước kết thúc không đăng xuất
    loose = {"login": [{"type": "launch", "app": "efootball"}, {"type": "type", "text": "{{username}}"},
                       {"type": "key", "name": "tab"}, {"type": "type", "text": "{{password}}"}, {"type": "key", "name": "enter"}],
             "finish": [{"type": "home"}]}
    g15 = FakeGame(accounts())
    g15.user = "a@test.vn"                       # phiên cũ còn nguyên trong game
    r15 = rig(g15, local_steps=loose)
    j15 = gw.new_job("T-015", "otp@test.vn", "PassB#2", [{"code": "coin_1050", "qty": 1}])
    r15.start()
    ok(wait_until(lambda: not r15.running(), 10) and "đang đăng nhập" in r15.status()["status"], "máy thấy game còn đăng nhập tài khoản cũ → TỰ DỪNG trước khi nhận đơn", r15.status())
    ok(gw.job(j15)["status"] == "queued", "đơn của khách sau KHÔNG bị nhận (vẫn nằm chờ máy khác)", gw.job(j15)["status"])
    ok(g15.purchases == [] and "PassB#2" not in g15.keylog and "otp@test.vn" not in g15.keylog, "không gõ gì của khách sau vào phiên người khác, không mua gì", g15.keylog)
    gw.shop("POST", "/api/shop/jobs/%s/cancel" % j15)
    # lớp chặn thứ hai (ngay trong lúc làm đơn): game đang đăng nhập sẵn → không gõ tài khoản, báo failed + dừng máy
    pool_cfg = Gateway(gw.url, gw.tool_key).pool("game-test")
    def direct(game, login_steps=None):
        st = apimode.effective_steps(pool_cfg, {"login": login_steps} if login_steps else {})
        class NoGw:                                # không gọi mạng: chỉ xét quyết định của luồng xử lý đơn
            def progress(self, *a, **k): return {"ok": True}
            def upload_image(self, *a, **k): return {"ok": True}
        job = {"id": "JDIRECT", "login": {"username": "otp@test.vn", "password": "PassB#2"}, "items": [{"code": "coin_1050", "name": "1050 Coins", "qty": 1, "ocr_text": "1050|1,050"}]}
        return apimode.JobFlow(FakeNav(game), NoGw(), job, pool_cfg, st, opts={"login_wait": 2, "purchase_wait": 2, "clear_wait": 0.2}).run()
    gs = FakeGame(accounts()); gs.user = "a@test.vn"
    out = direct(gs)
    ok(out.result == "failed" and out.halt and out.session == "in" and "PassB#2" not in gs.keylog and gs.purchases == [],
       "đang đăng nhập sẵn tài khoản khác → KHÔNG gõ tài khoản của khách, failed + yêu cầu dừng máy", (out.result, out.halt, out.message, gs.keylog))
    gn = FakeGame(accounts())
    out = direct(gn, [{"type": "launch", "app": "khong-co-app-nay"}, {"type": "type", "text": "{{username}}"}, {"type": "type", "text": "{{password}}"}])
    ok(out.result == "failed" and out.fault and "màn hình đăng nhập" in out.message and "PassB#2" not in gn.keylog and "otp@test.vn" not in gn.keylog,
       "không THẤY màn hình chưa-đăng-nhập thì không gõ tài khoản (dù cũng không thấy chữ «đã đăng nhập»)", (out.message, gn.keylog))
    # bước kết thúc (đăng xuất) lỗi → máy dừng ngay sau đơn đó
    g16 = FakeGame(accounts(), no_logout=True)
    r16 = rig(g16)
    j16 = gw.new_job("T-016", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    r16.start()
    job = gw.wait_job(j16, ("done", "failed", "review"))
    ok(job["status"] == "done", "đơn vẫn hoàn tất bình thường")
    ok(wait_until(lambda: not r16.running(), 10) and "đăng xuất" in r16.status()["status"], "không đăng xuất được → máy TỰ DỪNG, không nhận đơn sau", r16.status())

    print("\n== 14. Gateway đóng đơn giữa chừng → tool dừng, không mua ==")
    g17 = FakeGame(accounts())
    r17 = rig(g17)
    j17 = gw.new_job("T-017", "otp@test.vn", "PassB#2", [{"code": "coin_1050", "qty": 1}])
    r17.start()
    gw.wait_job(j17, ("need_otp",))
    Gateway(gw.url, gw.tool_key).result(j17, "failed", "đóng từ bên ngoài")      # coi như admin/hệ thống chốt đơn
    ok(wait_until(lambda: "đã đóng đơn" in r17.text(), 10), "tool nhận ra đơn đã bị đóng", r17.text()[-200:])
    ok(g17.purchases == [], "không mua gì cho đơn đã đóng")
    r17.stop()

    print("\n== 15. Mất mạng lúc gửi kết quả → tự gửi lại, không làm lại đơn ==")
    class Flaky(Gateway):
        fails = 3
        def result(self, *a, **k):
            if Flaky.fails > 0:
                Flaky.fails -= 1
                raise GatewayError(0, "network", "mất mạng (giả lập)")
            return super().result(*a, **k)
    g18 = FakeGame(accounts())
    r18 = rig(g18, gateway_cls=Flaky)
    j18 = gw.new_job("T-018", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    r18.start()
    job = gw.wait_job(j18, ("done", "failed", "review"), 30)
    ok(job["status"] == "done" and g18.purchases == [("a@test.vn", "coin_1050")], "kết quả tới được gateway sau khi gửi lại; chỉ mua 1 lần", (job["status"], g18.purchases))
    ok("CHƯA gửi được kết quả" in r18.text(), "nhật ký có ghi lần gửi hỏng")
    wait_until(lambda: (r18.journal.get(r18.name) or {}).get("delivered") is True, 8)      # tool ghi sổ SAU khi gateway nhận kết quả
    st = r18.journal.get(r18.name)
    ok(st["phase"] == "finished" and st["delivered"] is True, "sổ cục bộ đánh dấu đã gửi xong", st)
    r18.stop()

    print("\n== 17. Hộp thoại «mua thành công» của lần trước không đóng được → KHÔNG đếm nhầm thành lần mua mới ==")
    g19 = FakeGame(accounts(), sticky_result=True)
    r19 = rig(g19)
    j19 = gw.new_job("T-019", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 3}])
    r19.start()
    job = gw.wait_job(j19, ("done", "failed", "review"))
    ok(g19.purchases == [("a@test.vn", "coin_1050")], "game chỉ ghi nhận đúng 1 lần mua", g19.purchases)
    ok(job["status"] == "review" and "1/3" in (job["message"] or "") and job["result"][0]["qty_done"] == 1,
       "tool báo ĐÚNG 1/3 và chuyển đối soát (trước đây báo «nạp đủ 3 gói»)", (job["status"], job["message"], job["result"]))
    ok("còn chữ «nạp thành công»" in (job["message"] or ""), "lý do nói rõ: màn hình còn chữ của lần mua trước", job["message"])
    ok(len([i for i in job["images"] if i["kind"] == "bill"]) == 1, "chỉ 1 ảnh bill cho 1 lần mua thật", [i["kind"] for i in job["images"]])
    ok(wait_until(lambda: not r19.running(), 8), "máy dừng chờ người kiểm tra")

    print("\n== 18. Cổng serial lỗi đúng lúc bấm mua → «không chắc» (review), tuyệt đối không báo «chưa nạp» ==")
    g20 = FakeGame(accounts(), explode_click=4)          # lần bấm thứ 4 = «Mua ngay»: iPhone đã nhận, rồi cổng mới lỗi
    r20 = rig(g20)
    j20 = gw.new_job("T-020", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    r20.start()
    job = gw.wait_job(j20, ("done", "failed", "review"))
    ok(g20.purchases == [("a@test.vn", "coin_1050")], "(game ĐÃ ghi nhận lần mua trước khi cổng lỗi)", g20.purchases)
    ok(job["status"] == "review", "tool báo review — shop không hoàn tiền nhầm cho đơn đã nạp (trước đây báo failed)", (job["status"], job["message"]))
    ok(wait_until(lambda: not r20.running(), 8), "máy dừng chờ người kiểm tra")
    g21 = FakeGame(accounts(), shot_fail_on="shop")      # hỏng TRƯỚC khi chạm vào gì ở bước mua
    r21 = rig(g21)
    j21 = gw.new_job("T-021", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    r21.start()
    job = gw.wait_job(j21, ("done", "failed", "review"))
    ok(job["status"] == "failed" and g21.purchases == [] and g21.clicks == 2, "lỗi trước khi bấm bất cứ gì ở bước mua → failed (đúng là chưa nạp)", (job["status"], job["message"], g21.clicks))
    r21.stop(force=True)

    # danh sách mua chỉ có MỘT bước, và cổng lỗi ngay ở bước đó: chưa có bước mua nào «chạy xong» để đánh dấu rủi ro
    g20b = FakeGame(accounts(), one_tap_buy=True, explode_click=3)     # lần bấm thứ 3 = bấm vào gói = mua luôn
    r20b = rig(g20b, local_steps={"purchase": [{"type": "tap_text", "text": "{{package.ocr_text}}"}]})
    j20b = gw.new_job("T-020b", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    r20b.start()
    job = gw.wait_job(j20b, ("done", "failed", "review"))
    ok(g20b.purchases == [("a@test.vn", "coin_1050")] and job["status"] == "review",
       "bước mua DUY NHẤT ném lỗi sau khi lệnh bấm đã ra cổng → vẫn là «không chắc» (review), không phải «chưa nạp»", (job["status"], job["message"], g20b.purchases))
    r20b.stop(force=True)

    # board thật gửi lệnh bấm trong một mạch «burst»: lỗi cổng ngay sau cú bấm mua cũng phải ra «không chắc»
    g20c = FakeGame(accounts(), one_tap_buy=True, explode_click=3, burst=True)
    r20c = rig(g20c, local_steps={"purchase": [{"type": "tap_text", "text": "{{package.ocr_text}}"}]})
    j20c = gw.new_job("T-020c", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    r20c.start()
    job = gw.wait_job(j20c, ("done", "failed", "review"))
    ok(g20c.purchases == [("a@test.vn", "coin_1050")] and job["status"] == "review",
       "board kiểu thật (lệnh bấm đi trong mạch burst) + cổng chết ngay sau cú bấm mua → review, không phải «chưa nạp»", (job["status"], job["message"]))
    r20c.stop(force=True)
    g20d = FakeGame(accounts(), burst=True)
    r20d = rig(g20d)
    j20d = gw.new_job("T-020d", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 2}])
    r20d.start()
    job = gw.wait_job(j20d, ("done", "failed", "review"))
    ok(job["status"] == "done" and len(g20d.purchases) == 2, "board kiểu thật: đơn thường vẫn chạy trọn (đăng nhập → mua 2 → đăng xuất)", (job["status"], job["message"]))
    r20d.stop()

    print("\n== 18b. Các chốt an toàn quanh việc ĐỌC màn hình lúc mua ==")
    # con trỏ vừa bấm «Đóng» còn nằm trên màn, che đúng dòng «Mua thành công» của hộp thoại bị kẹt
    gh = FakeGame(accounts(), sticky_result=True, hide_under_pointer=True)
    rh = rig(gh)
    jh = gw.new_job("T-0H1", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 3}])
    rh.start()
    job = gw.wait_job(jh, ("done", "failed", "review"))
    ok(gh.purchases == [("a@test.vn", "coin_1050")] and job["status"] == "review" and "1/3" in (job["message"] or ""),
       "con trỏ che chữ kết quả của lần mua trước → tool CẤT con trỏ rồi mới đọc, nên vẫn thấy hộp thoại kẹt (không đếm khống 3/3)", (job["status"], job["message"], gh.purchases))
    wait_until(lambda: not rh.running(), 8)
    # chữ «Đã mua gói này» in sẵn trên một ô gói KHÁC: không được dùng để kết luận cho lần mua này
    gu = FakeGame(accounts(), unavail_label=True, slow_result=3)     # kết quả hiện chậm: lúc đầu trên màn chỉ có nhãn in sẵn
    ru = rig(gu)
    ju = gw.new_job("T-0U1", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    ru.start()
    job = gw.wait_job(ju, ("done", "failed", "review"))
    ok(job["status"] == "done" and gu.purchases == [("a@test.vn", "coin_1050")] and "có sẵn chữ của luật" in ru.text(),
       "chữ «không mua được» CÓ SẴN trên màn hình → bỏ qua luật đó, lần mua thật vẫn được tính là đã nạp (không báo «thất bại» oan cho đơn đã trừ tiền)", (job["status"], job["message"]))
    ru.stop()
    # verify vòng 5 (C-2): một lần OCR đọc HỤT không được quyết định thay
    # (a) nhãn «Đã mua gói này» có sẵn nhưng bị đọc hụt đúng lần nhìn đầu trước khi mua; kết quả thật hiện chậm
    gm1 = FakeGame(accounts(), unavail_label=True, slow_result=3, ocr_miss=("shop", "Đã mua gói này rồi", 1))
    rm1 = rig(gm1)
    jm1 = gw.new_job("T-0M1", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    rm1.start()
    job = gw.wait_job(jm1, ("done", "failed", "review"))
    ok(job["status"] == "done" and gm1.purchases == [("a@test.vn", "coin_1050")],
       "nhãn «không mua được» có sẵn bị đọc HỤT một lần lúc kiểm trước khi mua → vẫn không báo «thất bại» cho đơn đã trừ tiền", (job["status"], job["message"], gm1.purchases))
    rm1.stop()
    # (a2) nhãn có sẵn + game TREO sau khi bấm mua (không biết đã trừ tiền chưa): nhãn có sẵn không được biến «không rõ» thành «chưa nạp»
    for tag, miss, why in (("d", None, "nhãn «không mua được» có sẵn"),
                           ("e", ("shop", "Đã mua gói này rồi", 1), "…và bị đọc hụt ở lần nhìn ĐẦU trước khi mua"),
                           ("f", ("shop", "Đã mua gói này rồi", 1, 2), "…và bị đọc hụt ở lần nhìn CUỐI trước khi mua")):
        gfz = FakeGame(accounts(), unavail_label=True, freeze_on_buy=True, **({"ocr_miss": miss} if miss else {}))
        rfz = rig(gfz)
        jfz = gw.new_job("T-0F" + tag, "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
        rfz.start()
        job = gw.wait_job(jfz, ("done", "failed", "review"))
        ok(job["status"] == "review", "%s + game treo sau khi bấm mua → «không rõ» (đối soát), KHÔNG phải «chưa nạp»" % why, (job["status"], job["message"]))
        wait_until(lambda: not rfz.running(), 8)
    # (b) hộp thoại «Mua thành công» của lần trước còn kẹt, nhưng bị đọc hụt đúng một lần → KHÔNG được coi là màn hình đã sạch
    gm2 = FakeGame(accounts(), sticky_result=True)
    rm2 = rig(gm2)
    jm2 = gw.new_job("T-0M2", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 3}])
    def miss_once():                                       # ngay sau lần mua thật: lần đọc kế tiếp của hộp thoại kẹt bị hụt chữ
        gm2.behavior["ocr_miss"] = ("result_ok", "Mua thành công!", 2)
    gm2.on_purchase = miss_once
    rm2.start()
    job = gw.wait_job(jm2, ("done", "failed", "review"))
    ok(gm2.purchases == [("a@test.vn", "coin_1050")] and job["status"] == "review" and job["result"][0]["qty_done"] == 1,
       "chữ «thành công» của lần trước bị đọc hụt vài lần → vẫn nhận ra hộp thoại kẹt (đếm đúng 1/3, không đếm khống)", (job["status"], job["message"], job["result"]))
    wait_until(lambda: not rm2.running(), 8)
    # (c) đọc kết quả: chữ báo lỗi chỉ được tin khi hiện ỔN ĐỊNH; «thành công» xuất hiện trong lúc chờ thì thắng
    class Seq:                                             # màn hình giả: mỗi lần đọc trả một dòng chữ kế tiếp
        def __init__(self, texts): self.texts, self.i, self.e, self.h = list(texts), 0, self, self
        def screenshot(self): return None
        def read_text(self, img=None, **kw):
            t = self.texts[min(self.i, len(self.texts) - 1)]; self.i += 1; return t
        def send(self, cmd, wait=0.5): return "OK home"
    def reader(texts, wait=3.0):
        class NoGw: pass
        jf = apimode.JobFlow(Seq(texts), NoGw(), {"id": "J", "login": {}, "items": []}, pool_cfg, apimode.effective_steps(pool_cfg, {}),
                             opts={"login_wait": 1, "purchase_wait": wait, "clear_wait": 0.2})
        return jf._read_result(list(apimode.RESULT_RULES))[0]
    ok(reader(["Đang xử lý", "Thanh toán thất bại", "Mua thành công! Đóng"]) == "purchase_success", "thoáng thấy chữ «thất bại» rồi «thành công» hiện ra → tính là ĐÃ NẠP")
    ok(reader(["Đang xử lý", "Thanh toán thất bại. Đóng"]) == "purchase_fail", "chữ «thất bại» hiện ổn định (nhiều lần nhìn liền, đủ lâu) → mới kết luận thất bại")
    ok(reader(["Thanh toán thất bại", "Đang xử lý", "Đang xử lý", "Mua thành công!"]) == "purchase_success", "chữ báo lỗi chỉ lóe lên một lần (OCR nhầm) → không kết luận, chờ tiếp tới khi có kết quả thật")
    ok(reader(["Đang xử lý"], wait=0.6) is None, "hết giờ mà không có chữ kết quả nào → «không xác nhận được» (đơn sẽ chuyển đối soát)")
    ok(reader(["Đã mua gói này rồi"], wait=1.0) == "package_unavailable", "«không mua được» hiện ổn định → kết luận đúng loại")

    # --- hằng số THẬT (NEG_GRACE mặc định) trên đồng hồ giả: game chậm không được làm báo sai «không mua được» sau khi đã mua (verify vòng 6, W-5) ---
    import types
    class Clock:
        t = 0.0
    real_time_mod, real_sleep_fn, real_grace = apimode.time, apimode._sleep, apimode.JobFlow.NEG_GRACE
    prod_rules = [{"when": "logged_out", "value": "Konami ID"}, {"when": "login_success", "value": "Trang chủ"},
                  {"when": "purchase_success", "value": "Mua thành công"}, {"when": "purchase_fail", "value": "Thanh toán thất bại"},
                  {"when": "package_unavailable", "value": "Đã mua gói này"}]
    class LagNav:
        def __init__(self, t_label, t_ok_after, t_fail_after=None):
            self.t_label, self.t_ok_after, self.t_fail_after, self.pressed_at = t_label, t_ok_after, t_fail_after, None
            self.e = self; self.h = self
        def screenshot(self): Clock.t += 0.5; return None
        def read_text(self, img=None, **kw):
            Clock.t += 0.5
            txt = "Cửa hàng 1050 Coins Mua ngay"
            if Clock.t >= self.t_label: txt += " Ưu đãi tuần: Đã mua gói này rồi"          # nhãn in sẵn ở Ô KHÁC, hiện muộn
            if self.pressed_at is not None and self.t_ok_after is not None and Clock.t >= self.pressed_at + self.t_ok_after: txt += " Mua thành công!"
            if self.pressed_at is not None and self.t_fail_after is not None and Clock.t >= self.pressed_at + self.t_fail_after: txt += " Thanh toán thất bại"
            return txt
        def send(self, cmd, wait=0.5):
            if cmd.startswith("key"): self.pressed_at = Clock.t
            Clock.t += 0.2; return "OK " + cmd.split(" ")[0]
    def lag_run(t_label, t_ok_after, t_fail_after=None):
        Clock.t = 0.0
        nav = LagNav(t_label, t_ok_after, t_fail_after)
        steps = {"login": [], "finish": [], "otp": [], "nav": [], "after": [], "purchase": [{"type": "key", "name": "enter"}]}
        flow = apimode.JobFlow(nav, None, {"id": "J", "items": [{"code": "c", "name": "1050 Coins", "qty": 1}]}, {"rules": prod_rules}, steps,
                               opts={"purchase_wait": 60, "clear_wait": 8}, log=lambda *a, **k: None)
        return flow._buy_one({"code": "c", "name": "1050 Coins", "qty": 1}, {})[0]
    try:
        apimode.time = types.SimpleNamespace(time=lambda: Clock.t, sleep=lambda s: setattr(Clock, "t", Clock.t + s), strftime=time.strftime)
        apimode._sleep = lambda sec, abort=None: setattr(Clock, "t", Clock.t + sec)
        apimode.JobFlow.NEG_GRACE = PROD_NEG_GRACE
        wrong = [(tl, oa, lag_run(tl, oa)) for tl in (0.0, 6.0, 9.0, 20.0) for oa in (1.0, 5.0, 15.0, 25.0) if lag_run(tl, oa) != "ok"]
        ok(wrong == [], "hằng số THẬT: nhãn «Đã mua gói này» ở ô khác hiện muộn + hộp thoại «thành công» hiện chậm tới 25 s sau khi bấm → vẫn tính ĐÃ NẠP (trước đây báo «không mua được» dù đã trừ tiền)", wrong)
        ok(lag_run(0.0, None, 2.0) == "failed" and lag_run(0.0, None, None) in ("unavailable", "uncertain"),
           "hằng số THẬT: lỗi thật («Thanh toán thất bại» hiện sau 2 s, không bao giờ có «thành công») vẫn được kết luận «thất bại»; chỉ có nhãn cũ thì không bao giờ ra «thành công»")
        def lag_run_wait(t_label, t_ok_after, wait):
            Clock.t = 0.0
            nav = LagNav(t_label, t_ok_after)
            steps = {"login": [], "finish": [], "otp": [], "nav": [], "after": [], "purchase": [{"type": "key", "name": "enter"}]}
            flow = apimode.JobFlow(nav, None, {"id": "J", "items": [{"code": "c", "name": "1050 Coins", "qty": 1}]}, {"rules": prod_rules}, steps,
                                   opts={"purchase_wait": wait, "clear_wait": 8}, log=lambda *a, **k: None)
            return flow._buy_one({"code": "c", "name": "1050 Coins", "qty": 1}, {})[0]
        wrong = [(w_, tl, oa, lag_run_wait(tl, oa, w_)) for w_ in (10, 20, 30, 45, 60, 120) for tl in (0.0, 6.0, 9.0) for oa in (1.0, 5.0, 9.0, 15.0, 20.0, 25.0, 30.0)
                 if oa + 6 < w_ and lag_run_wait(tl, oa, w_) != "ok"]
        ok(wrong == [], "hằng số THẬT: purchase_wait NGẮN (10–45 s) + nhãn cũ hiện muộn + «thành công» hiện chậm trong khoảng chờ → vẫn tính ĐÃ NẠP (trước đây ngưỡng co theo purchase_wait → báo «không mua được» dù đã mua)", wrong[:4])
        ok(lag_run_wait(0.0, None, 20) in ("uncertain", "unavailable") and lag_run_wait(0.0, None, 20) != "failed",
           "purchase_wait ngắn mà chỉ có nhãn cũ, không có «thành công» → không bao giờ ra «đã nạp»")
        ok(lag_run(0.0, None, 55.0) == "uncertain" and lag_run(0.0, None, 40.0) == "uncertain" and lag_run(0.0, None, 15.0) == "failed",
           "hằng số THẬT: chữ báo lỗi chỉ mới hiện vài giây trước khi hết giờ (chưa ổn định đủ lâu, success có thể còn đang tới) → «không xác nhận được» (đối soát), KHÔNG kết luận thất bại")
    finally:
        apimode.time, apimode._sleep, apimode.JobFlow.NEG_GRACE = real_time_mod, real_sleep_fn, real_grace
    ok(PROD_NEG_GRACE >= 20, "hằng số NEG_GRACE thật đủ dài cho game chậm (≥ 20 s)", PROD_NEG_GRACE)

    # chụp màn hình trục trặc đúng MỘT lần ngay trước khi mua → thử lại, không bỏ đơn
    gs1 = FakeGame(accounts(), shot_fail_once="shop")
    rs1 = rig(gs1)
    js1 = gw.new_job("T-0S1", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    rs1.start()
    job = gw.wait_job(js1, ("done", "failed", "review"))
    ok(job["status"] == "done" and len(gs1.purchases) == 1, "chụp màn hình hỏng thoáng qua trước khi mua → đọc lại rồi mua bình thường", (job["status"], job["message"]))
    rs1.stop()
    # màn hình đổi trong lúc con trỏ đang được đưa tới → KHÔNG bấm (kiểm lại chữ cần bấm ngay trước khi bấm)
    gc = FakeGame(accounts(), change_before_click=True); gc.screen = "main"
    r = apimode.exec_step(FakeNav(gc), {"type": "tap_text", "text": "Cửa hàng"}, {})
    ok(r[0] is False and r[2] is False and gc.clicks == 0, "bấm chữ: màn hình đổi trước khi kịp bấm → không bấm, và chắc chắn chưa chạm", r)
    gc2 = FakeGame(accounts(), change_before_click=True); gc2.screen = "main"
    r = apimode.exec_step(FakeNav(gc2), {"type": "hold_text", "text": "Cửa hàng", "seconds": 1}, {})
    ok(r[0] is False and gc2.gestures == [], "giữ chữ: màn hình đổi trước khi kịp nhấn → không nhấn", (r, gc2.gestures))
    # cử chỉ hỏng: đã nhấn nút hay chưa?
    class Press:                                           # board có đếm số lần nhấn nút (như Hands thật)
        presses = 0
    gg = FakeGame(accounts()); ng = FakeNav(gg); ng.h = Press(); ng._hid_sent = 7
    r = apimode.gesture(ng, "vuốt", lambda: False)
    ok(r[0] is False and r[2] is False and ng._hid_sent == 7 and "chưa chạm" in r[1], "cử chỉ hỏng mà nút CHƯA hề được nhấn (con trỏ không tới điểm đầu) → chắc chắn chưa chạm vào app", r)
    def half():
        ng.h.presses += 1; return False
    r = apimode.gesture(ng, "vuốt", half)
    ok(r[0] is False and r[2] is True and ng._hid_sent == 8, "cử chỉ hỏng SAU khi đã nhấn nút → «không chắc» (ở bước mua sẽ thành review)", r)
    def boom():
        ng.h.presses += 1; raise OSError("cổng chết")
    try:
        apimode.gesture(ng, "vuốt", boom); raised = False
    except OSError:
        raised = True
    ok(raised and ng._hid_sent == 9, "cử chỉ NÉM LỖI giữa chừng → bộ đếm lệnh đã tăng từ trước (bên gọi biết có thể đã chạm)")

    print("\n== 19. Sau đơn phải đối soát, bấm Chạy lại → máy tự đăng xuất khách cũ rồi mới nhận đơn của khách mới ==")
    ok(g6.user == "a@test.vn" and not r6.running(), "(máy ở kịch bản 6 đang dừng, game còn đăng nhập khách cũ)", (g6.user, g6.screen))
    g6.behavior["freeze_on_buy"] = False
    before = len(g6.purchases)
    j22 = gw.new_job("T-022", "owned@test.vn", "PassC#3", [{"code": "coin_1050", "qty": 1}])
    r6.start()
    job = gw.wait_job(j22, ("done", "failed", "review"))
    ok(job["status"] == "done", "đơn của khách mới hoàn tất (trước đây: failed vì game còn phiên cũ)", (job["status"], job["message"]))
    ok(g6.purchases[before:] == [("owned@test.vn", "coin_1050")], "tiền nạp vào ĐÚNG tài khoản của khách mới", g6.purchases)
    ok("kết thúc đơn (đăng xuất)" in r6.text(), "nhật ký ghi: thấy game còn đăng nhập → chạy bước đăng xuất trước")
    r6.stop()

    print("\n== 20. Pool thiếu luật bắt buộc → máy KHÔNG nhận đơn ==")
    g23 = FakeGame(accounts())
    r23 = rig(g23, pool="game-bare")
    j23 = gw.new_job("T-023", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}], pool="game-bare")
    r23.start()
    ok(wait_until(lambda: not r23.running(), 8) and "chưa đủ cấu hình" in r23.status()["status"] and "thiếu luật" in r23.status()["status"],
       "máy dừng ngay, nói rõ pool thiếu luật gì", r23.status())
    ok(gw.job(j23)["status"] == "queued" and g23.keylog == [] and g23.clicks == 0, "không nhận đơn, không đụng vào máy", (gw.job(j23)["status"], g23.keylog))
    gw.shop("POST", "/api/shop/jobs/%s/cancel" % j23)

    print("\n== 21. Kiểm bàn phím: không kiểm được thì KHÔNG coi là đạt ==")
    g24 = FakeGame(accounts(), kb_raise=1)               # lần kiểm đầu hỏng (chụp màn lỗi), lần sau được
    r24 = rig(g24, check_keyboard=True)
    j24 = gw.new_job("T-024", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    r24.start()
    job = gw.wait_job(j24, ("done", "failed", "review"))
    ok(job["status"] == "done" and r24.nav.kb_calls == 2, "kiểm hỏng 1 lần → kiểm lại rồi mới nhận đơn", (job["status"], r24.nav.kb_calls))
    r24.stop()
    g25 = FakeGame(accounts(), kb_raise=99)
    r25 = rig(g25, check_keyboard=True)
    j25 = gw.new_job("T-025", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    r25.start()
    ok(wait_until(lambda: not r25.running(), 10) and "không kiểm tra được bàn phím" in r25.status()["status"], "kiểm hỏng 3 lần liền → máy dừng (trước đây: coi như đạt)", r25.status())
    ok(gw.job(j25)["status"] == "queued", "không nhận đơn khi chưa kiểm được bàn phím")
    g26 = FakeGame(accounts(), kb_telex=True)
    r26 = rig(g26, check_keyboard=True)
    r26.start()
    ok(wait_until(lambda: not r26.running(), 10) and "Telex" in r26.status()["status"] and gw.job(j25)["status"] == "queued", "máy đang bật Telex → dừng, không nhận đơn", r26.status())
    gw.shop("POST", "/api/shop/jobs/%s/cancel" % j25)

    print("\n== 22. Mất phản hồi lúc xin OTP → gửi lại KHÔNG tốn thêm lượt xin của khách ==")
    class LostOtp(Gateway):
        lost = 1
        def otp_request(self, *a, **k):
            r = super().otp_request(*a, **k)
            if LostOtp.lost > 0:
                LostOtp.lost -= 1
                raise GatewayError(0, "network", "mất phản hồi (giả lập)")
            return r
    g27 = FakeGame(accounts())
    r27 = rig(g27, gateway_cls=LostOtp)
    j27 = gw.new_job("T-027", "otp@test.vn", "PassB#2", [{"code": "coin_1050", "qty": 1}])
    customer(gw, j27, ["654321"])
    r27.start()
    job = gw.wait_job(j27, ("done", "failed", "review"))
    ok(job["status"] == "done" and job["otp"]["seq"] == 1 and LostOtp.lost == 0, "gửi lại yêu cầu OTP → vẫn chỉ tính 1 lượt, đơn hoàn tất", (job["status"], job["otp"]))
    r27.stop()

    print("\n== 23. Gateway tự đóng đơn khi tool ĐÃ mua được một phần → tool vẫn báo số đã mua cho người đối soát ==")
    g28 = FakeGame(accounts())
    r28 = rig(g28)
    j28 = gw.new_job("T-028", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 2}])
    g28.on_purchase = lambda: gw.sql("UPDATE jobs SET status='review', stage='review', review_reason='timeout' WHERE pid=? AND status='running'", (j28,))
    r28.start()
    ok(wait_until(lambda: not r28.running(), 15), "máy dừng sau khi biết đơn đã bị đóng", r28.status())
    ev = [m for (m,) in gw.sql("SELECT message FROM job_events WHERE type='late_report' AND job_id=(SELECT id FROM jobs WHERE pid=?)", (j28,))]
    ok(g28.purchases == [("a@test.vn", "coin_1050")] and gw.job(j28)["status"] == "review", "mua được 1/2 thì đơn bị đóng → không mua tiếp, đơn vẫn chờ đối soát", (g28.purchases, gw.job(j28)["status"]))
    ok(len(ev) == 1 and "coin_1050" in ev[0] and " 1]" in ev[0], "nhật ký đơn trên gateway có lời báo muộn kèm số đã mua của từng gói", ev)

    print("\n== 24. Vuốt + bấm giữ: cấu hình trên gateway → tool chạy đúng (gói nằm ở trang 2 của cửa hàng) ==")
    g30 = FakeGame(accounts())
    r30 = rig(g30, pool="game-swipe")
    j30 = gw.new_job("T-030", "a@test.vn", "PassA#1", [{"code": "legend", "qty": 1}], pool="game-swipe")
    r30.start()
    job = gw.wait_job(j30, ("done", "failed", "review"))
    ok(job["status"] == "done" and g30.purchases == [("a@test.vn", "legend")], "đơn hoàn tất, mua đúng gói ở trang 2", (job["status"], job["message"], g30.purchases))
    ok(g30.gestures[:1] == [("flick", "left")] and len(g30.gestures) == 2 and g30.gestures[1][0] == "hold" and g30.gestures[1][3] == 0.5,
       "máy nhận đúng: vuốt sang trái rồi bấm giữ 0,5 giây vào chữ", g30.gestures)
    r30.stop()

    print("\n== 25. Vuốt / bấm giữ: đổi cấu hình thành bước, mô tả, chạy, báo lỗi ==")
    conv = apimode.gw_step_to_engine
    ok(conv({"type": "swipe", "value": " LEFT "}) == {"type": "swipe", "dir": "left"}, "vuốt theo hướng")
    ok(conv({"type": "swipe", "value": "375,1000 > 375,400"}) == {"type": "swipe", "x1": 375, "y1": 1000, "x2": 375, "y2": 400}
       and conv({"type": "swipe", "value": "10 20 -> 30 40"})["x2"] == 30, "vuốt theo toạ độ «x1,y1 > x2,y2»")
    ok(conv({"type": "hold", "value": "636,468 @1.5s"}) == {"type": "hold", "x": 636, "y": 468, "seconds": 1.5}
       and conv({"type": "hold", "value": "636,468"})["seconds"] == 1.0 and conv({"type": "hold", "value": "1,2 @99s"})["seconds"] == 10.0,
       "bấm giữ toạ độ: «x,y @1.5s», mặc định 1 giây, tối đa 10 giây")
    ok(conv({"type": "hold_text", "value": "Sách @2s", "optional": True}) == {"type": "hold_text", "text": "Sách", "seconds": 2.0, "optional": True}, "bấm giữ vào chữ, giữ cờ «bỏ qua nếu lỗi»")
    bad = 0
    for v in ({"type": "swipe", "value": "cheo"}, {"type": "swipe", "value": "1,2"}, {"type": "hold", "value": "giua man hinh"}):
        try: conv(v)
        except apimode.ConfigError: bad += 1
    ok(bad == 3, "giá trị sai dạng → báo lỗi cấu hình rõ ràng (không chạy bừa)", bad)
    ok(apimode.describe({"type": "swipe", "dir": "left"}) and "trái" in apimode.describe({"type": "swipe", "dir": "left"})
       and "giữ" in apimode.describe({"type": "hold", "x": 1, "y": 2, "seconds": 1.5}).lower(), "có mô tả tiếng Việt cho nhật ký")
    gq = FakeGame(accounts()); nq = FakeNav(gq)
    ok(apimode.exec_step(nq, {"type": "swipe", "x1": 375, "y1": 1000, "x2": 375, "y2": 400}, {}) == (True, "", True) and gq.gestures == [("swipe", 375, 1000, 375, 400)], "chạy bước vuốt theo toạ độ", gq.gestures)
    ok(apimode.exec_step(nq, {"type": "hold", "x": 636, "y": 468, "seconds": 1.3}, {})[0] is True and gq.gestures[-1] == ("hold", 636, 468, 1.3), "chạy bước bấm giữ", gq.gestures)
    r = apimode.exec_step(nq, {"type": "hold_text", "text": "Chữ không có trên màn", "seconds": 1}, {})
    ok(r[0] is False and r[2] is False and len(gq.gestures) == 2, "bấm giữ vào chữ KHÔNG có trên màn hình → lỗi, chắc chắn chưa chạm gì", r)
    gf = FakeGame(accounts(), pointer_fail=True); nf = FakeNav(gf)
    r = apimode.exec_step(nf, {"type": "swipe", "dir": "up"}, {})
    ok(r[0] is False and r[2] is True and gf.gestures == [], "cử chỉ hỏng giữa chừng → coi là «không chắc đã chạm» (ở bước mua sẽ thành review, không phải failed)", r)
    try:
        apimode.exec_step(nq, {"type": "swipe", "dir": "cheo"}, {}); raised = False
    except apimode.ConfigError:
        raised = True
    ok(raised and set(("swipe", "hold", "hold_text")) <= set(apimode.INPUT_TYPES), "hướng lạ → lỗi cấu hình; vuốt/bấm giữ được tính là «thao tác vào máy»")

    print("\n== 26. Đoạn «mở game» + điểm chặn trước khi gõ tài khoản ==")
    L = lambda *steps: [dict(s) for s in steps]
    std = L({"type": "launch", "app": "efootball"}, {"type": "wait_text", "text": "Konami ID", "timeout": 3}, {"type": "tap_text", "text": "Đăng nhập"},
            {"type": "type", "text": "{{username}}"}, {"type": "key", "name": "tab"}, {"type": "type", "text": "{{password}}"}, {"type": "key", "name": "enter"})
    ok([s["type"] for s in apimode.open_prefix(std)] == ["launch", "wait_text"] and apimode.credential_gate(std) == 3,
       "danh sách thường: đoạn mở game dừng TRƯỚC cú bấm đầu tiên; chặn ngay trước bước gõ {{username}}")
    fixed = L({"type": "launch", "app": "efootball"}, {"type": "type", "text": "vn"}, {"type": "key", "name": "enter"}, {"type": "type", "text": "{{username}}"})
    ok(len(apimode.open_prefix(fixed)) == 3 and apimode.credential_gate(fixed) == 3, "gõ chữ CỐ ĐỊNH (không phải của khách) vẫn thuộc đoạn mở game")
    tapin = L({"type": "launch", "app": "efootball"}, {"type": "tap_text", "text": "Vào bằng Game Center"})
    ok(apimode.credential_gate(tapin) == 1 and apimode.credential_gate([]) == 0 and apimode.open_prefix(None) == [],
       "đăng nhập bằng cách BẤM (không gõ tài khoản): chặn ngay sau đoạn mở game, trước cú bấm")
    for odd in ("hold", "hold_text", "swipe", "tap"):
        ok(apimode.open_prefix(L({"type": "launch", "app": "x"}, {"type": odd}, {"type": "wait", "seconds": 1})) == [{"type": "launch", "app": "x"}],
           "bước «%s» (có chạm vào app) không bao giờ nằm trong đoạn mở game" % odd)
    gp = FakeGame(accounts()); gp.user = "a@test.vn"                    # game còn phiên của khách trước
    rules = pool_cfg.get("rules") or []
    state = apimode.session_probe(FakeNav(gp), {"login": std}, rules, 2)
    ok(state == "in" and gp.clicks == 0 and gp.keylog == ["efootball"], "dò phiên: chỉ mở game rồi ĐỌC màn hình — không bấm, không gõ gì của khách", (state, gp.clicks, gp.keylog))
    ok(apimode.session_probe(FakeNav(FakeGame(accounts())), {"login": std}, rules, 2) == "out", "game chưa ai đăng nhập → «out»")
    gu = FakeGame(accounts())
    ok(apimode.session_probe(FakeNav(gu), {"login": L({"type": "launch", "app": "app-khong-co"})}, rules, 1) == "unknown", "không nhận ra màn hình → «unknown» (máy sẽ không nhận đơn)")

    print("\n== 27. Máy đang giữ đơn của pool KHÁC với pool của nhóm → đối soát, không chạy bằng cấu hình sai ==")
    g29 = FakeGame(accounts())
    r29 = rig(g29, pool="game-swipe")
    j29 = gw.new_job("T-029", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    r29.client.claim(r29.name, "game-test")              # máy này đang giữ một đơn của pool game-test; nhóm vừa bị đổi sang game-swipe
    r29.start()
    job = gw.wait_job(j29, ("done", "failed", "review"))
    ok(job["status"] == "review" and "pool" in (job["message"] or "") and g29.purchases == [] and "PassA#1" not in g29.keylog,
       "đơn chuyển đối soát kèm lý do; không đăng nhập, không mua bằng các bước của pool khác", (job["status"], job["message"], g29.keylog))
    ok(wait_until(lambda: not r29.running(), 8), "máy dừng chờ người kiểm tra", r29.status())

    print("\n== 28. Board ESP32: tự kiểm / tự phục hồi LÚC RẢNH (trước khi nhận đơn) ==")
    import test_board as TB

    class BoardHands(FakeHands):
        """Bàn tay giả có «board» giả: ping / status / reset do FakeBoard trả lời (RAM, lý do reset…), còn lại như FakeHands."""
        def __init__(self, game, board):
            super().__init__(game)
            self.board, self.ser, self._rx = board, board.ser, b""

        def send(self, cmd, wait=0.5):
            if cmd in ("ping", "status", "reset"):
                return self.board.send(cmd, wait)
            return super().send(cmd, wait)

    gbd = FakeGame(accounts()); rbd = rig(gbd)
    brd = TB.FakeBoard([TB.line(heap=18000, min=9000), TB.GOOD])
    rbd.nav.h = BoardHands(gbd, brd)
    rbd.start()
    wait_until(lambda: brd.soft >= 1, 10)
    rbd.stop()
    ok(brd.soft == 1 and brd.hard == 0 and "reset mềm" in rbd.text() and "Board ESP32" in rbd.text(),
       "board sắp cạn RAM → bộ chạy tự khởi động lại board SỚM (lúc rảnh), ghi rõ vào nhật ký", (brd.soft, brd.hard, rbd.text()[-300:]))
    gok = FakeGame(accounts()); rok_ = rig(gok)
    bok = TB.FakeBoard([TB.GOOD])
    rok_.nav.h = BoardHands(gok, bok)
    rok_.start()
    time.sleep(1.5)
    rok_.stop()
    ok(bok.soft == 0 and bok.hard == 0 and "reset" not in rok_.text(), "board khoẻ → không reset gì", (bok.soft, bok.hard))
    gbr = FakeGame(accounts()); rbr = rig(gbr)
    bbr = TB.FakeBoard([TB.line(up=60, rst="brownout")])
    rbr.nav.h = BoardHands(gbr, bbr)
    rbr.start()
    wait_until(lambda: not rbr.running(), 12)
    sbr = rbr.status()
    ok(not rbr.running() and "board ESP32 không dùng được" in (sbr.get("status") or "") and not sbr.get("hold") and gbr.purchases == [] and bbr.soft == 0 and bbr.hard == 0,
       "board SỐNG nhưng nặng và reset không cứu được (vừa sụt nguồn) → 3 lần liền thì máy DỪNG báo rõ (không giữ chờ kiểm tra, không nhận đơn, không reset vô ích)", (sbr, bbr.soft, bbr.hard))
    gdd = FakeGame(accounts()); rdd = rig(gdd)
    bdd = TB.FakeBoard([TB.GOOD], silent_first=10 ** 12, dead=True)
    rdd.nav.h = BoardHands(gdd, bdd)
    rdd.start()
    wait_until(lambda: bdd.hard >= 1, 10)
    st_ = rdd.status()
    rdd.stop()
    ok(bdd.hard == 1 and "Chưa sẵn sàng" in (st_.get("status") or "") and gdd.purchases == [],
       "board ĐƠ (không trả lời) → thử reset cứng MỘT lần, máy báo «chưa sẵn sàng», không nhận đơn", (bdd.hard, st_.get("status")))

    print("\n== 16. Bí mật không lọt vào nhật ký ==")
    everything = " ".join(x.text() for x in rigs)
    leaked = [s for s in ("PassA#1", "PassB#2", "PassC#3", "SaiMatKhau", "654321", "111111") if s in everything]
    ok(not leaked, "mật khẩu / OTP không xuất hiện trong nhật ký tool", leaked)
    shown = apimode.describe({"type": "type", "text": "{{password}}"}, {"password": "PassA#1"})
    ok(shown == "Gõ «{{password}}»" and apimode.describe({"type": "tap_text", "text": "{{package.ocr_text}}"}, {"package.ocr_text": "1050"}) == "Tap chữ «1050»",
       "mô tả bước chỉ ghi TÊN biến bí mật, riêng thông tin gói thì hiện giá trị", shown)
    jl = open(os.path.join(rigs[0].jdir, "api_journal.jsonl"), encoding="utf-8").read()
    ok("T-001" in jl and "PassA#1" not in jl, "sổ lịch sử đơn có ghi đơn, không chứa mật khẩu")


if __name__ == "__main__":
    sys.exit(main())
