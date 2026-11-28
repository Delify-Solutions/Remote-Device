#!/usr/bin/env python3
"""
Test đầu-cuối CHẾ ĐỘ API của tool:   ./.venv/bin/python app/tests/test_api_mode.py

  tool (code nạp THẬT: runner.py + jobflow.py + stepexec.py + gateway.py)
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

import jobflow, stepexec
from jobflow import Journal
from eyes import norm_text
from gateway import Gateway, GatewayError
from runner import Runner

# ---- chạy nhanh: bỏ các quãng nghỉ dành cho máy thật (vẫn giữ kiểm «Dừng ngay») ----
def _fast_sleep(sec, abort=None):
    if abort and abort():
        raise stepexec.Aborted()
    time.sleep(min(max(sec, 0), 0.02))
stepexec._sleep = _fast_sleep
stepexec.STEP_GAP = 0
PROD_NEG_GRACE = jobflow.JobFlow.NEG_GRACE        # hằng số THẬT — có một bài thử riêng chạy với nó (đồng hồ giả)
jobflow.JobFlow.NEG_GRACE = 0.25         # (thật: 30 giây) thời gian chữ báo lỗi phải hiện ổn định trước khi được tin

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
    """Board có lệnh gửi liền mạch (như board thật) → code đi nhánh `burst` của stepexec.click()."""
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

    def text_lines(self, img=None):
        """Chữ theo DÒNG (có toạ độ) — chỉ màn cửa hàng có bố cục ô gói (ảnh giả 45×80): ô «1,050 / 249.000» và ô gói «1 lần»
        «Khởi đầu / 25.000» kèm «Remaining: 1». Tài khoản đã mua gói khởi đầu thì game ẨN ô đó (như game thật)."""
        g = self.g
        if g.screen == "shop":
            box = lambda t, x, y: {"text": t, "x": x, "y": y, "w": 8, "h": 4}
            out = [box("1,050", 33, 20), box("249.000", 33, 40)]
            if not (g.user and "starter" in (g.accounts.get(g.user) or {}).get("owned", set())):
                out += [box("Khởi đầu", 12, 20), box("25.000", 12, 40), box("Remaining: 1", 12, 12)]
            return out
        return [{"text": g.text(), "x": 22, "y": 40, "w": 10, "h": 4}]

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
// Bước của đơn soạn ở TOOL (BASE_STEPS bên dưới) — pool trên gateway chỉ có luật + gói.
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
// pool có gói nằm ở TRANG 2 của cửa hàng: phải vuốt mới thấy (bước vuốt + bấm giữ nằm trong kịch bản của tool — SWIPE_NAV)
$sid = Pools::save(null, "game-swipe", "Game vuốt trang", "eFootball", true, $cfg);
if (is_string($sid)) { fwrite(STDERR, $sid); exit(1); }
Pools::savePackages($sid, [["code" => "legend", "name" => "Gói Huyền thoại", "ocr_text" => "Huyền thoại", "limit_type" => "multi", "max_qty" => 5, "active" => true]]);
// pool ĐỜI CŨ: còn lưu các danh sách bước soạn ở gateway (dạng {type, value}) — tool đời mới chép chúng về kịch bản đúng MỘT lần
$old = $cfg;
$old["login_steps"] = [
    ["type" => "launch", "value" => "efootball"], ["type" => "wait_text", "value" => "Konami ID @3s"],
    ["type" => "tap_text", "value" => "Đăng nhập"], ["type" => "type", "value" => "{{username}}"],
    ["type" => "key", "value" => "tab"], ["type" => "type", "value" => "{{password}}"], ["type" => "key", "value" => "enter"],
];
$old["nav_steps"] = [["type" => "tap_text", "value" => "Cửa hàng"]];
$old["purchase_steps"] = [["type" => "tap_text", "value" => "{{package.ocr_text}}"], ["type" => "tap_text", "value" => "Mua ngay"]];
$old["after_purchase_steps"] = [["type" => "tap_text", "value" => "Đóng"]];
$old["finish_steps"] = [["type" => "tap_text", "value" => "Đóng", "optional" => true], ["type" => "tap_text", "value" => "Đăng xuất"],
                        ["type" => "wait_text", "value" => "Konami ID @3s"], ["type" => "home", "value" => ""]];
$lid = Pools::save(null, "game-legacy", "Game đời cũ", "eFootball", true, $old);
if (is_string($lid)) { fwrite(STDERR, $lid); exit(1); }
Pools::savePackages($lid, [["code" => "coin_1050", "name" => "1050 Coins", "ocr_text" => "1050|1,050", "price_text" => "249.000", "limit_type" => "multi", "max_qty" => 5, "active" => true]]);
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


# Bước của MỘT đơn, soạn trong kịch bản nhận đơn ở tool (nơi duy nhất soạn bước). OTP để trống = gõ mã rồi Enter.
# «Đóng» ở giai đoạn kết thúc là bước TUỲ CHỌN: có hộp thoại thì đóng, không có thì bỏ qua → dùng được từ mọi màn hình.
BASE_STEPS = {
    "login": [{"type": "launch", "app": "efootball"}, {"type": "wait_text", "text": "Konami ID", "timeout": 3}, {"type": "tap_text", "text": "Đăng nhập"},
              {"type": "type", "text": "{{username}}"}, {"type": "key", "name": "tab"}, {"type": "type", "text": "{{password}}"}, {"type": "key", "name": "enter"}],
    "otp": [],
    "nav": [{"type": "tap_text", "text": "Cửa hàng"}],
    "purchase": [{"type": "tap_text", "text": "{{package.ocr_text}}"}, {"type": "tap_text", "text": "Mua ngay"}],
    "after": [{"type": "tap_text", "text": "Đóng"}],
    "finish": [{"type": "tap_text", "text": "Đóng", "optional": True}, {"type": "tap_text", "text": "Đăng xuất"},
               {"type": "wait_text", "text": "Konami ID", "timeout": 3}, {"type": "home"}],
}
# pool «game-swipe»: gói nằm ở TRANG 2 của cửa hàng → vuốt mới thấy; thêm một bước bấm giữ (tuỳ chọn)
SWIPE_NAV = [{"type": "tap_text", "text": "Cửa hàng"}, {"type": "swipe", "dir": "left"}, {"type": "hold_text", "text": "trang 2", "seconds": 0.5, "optional": True}]


def order_script(pool="game-test", local_steps=None, check_keyboard=False):
    """Kịch bản NHẬN ĐƠN cho phép thử: BASE_STEPS, `local_steps` thay nguyên giai đoạn được nêu (đã đánh dấu «đã chép bước đời cũ»: không đụng gateway)."""
    steps = json.loads(json.dumps(BASE_STEPS))
    steps.update(json.loads(json.dumps(local_steps or {})))
    return {"id": "nd-test", "name": "Nạp theo đơn", "mode": "orders", "steps": [], "loops": 1,
            "orders": {"pool": pool, "steps": steps, "login_wait": 5, "purchase_wait": 5, "check_keyboard": check_keyboard, "gw_steps_copied": True}}


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
        self.group = {"id": "g-test", "name": "Nhóm thử", "devices": [self.name]}
        self.script = order_script(pool, local_steps, check_keyboard)

    def start(self):
        return self.runner.start_machine(self.name, self.group, self.script)

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
    import store
    store.DATA_DIR = tempfile.mkdtemp(prefix="api-data-")        # bộ chạy đọc ví / nhóm của tool: dùng thư mục tạm, không đụng dữ liệu thật
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
    steps = jobflow.order_steps(BASE_STEPS)
    ok([len(steps[p]) for p in jobflow.PHASES] == [7, 2, 1, 2, 1, 4], "bước 6 giai đoạn lấy từ KỊCH BẢN của tool (OTP để trống → mặc định: gõ mã + Enter)",
       {p: len(steps[p]) for p in jobflow.PHASES})
    only = jobflow.order_steps({"purchase": [{"type": "tap", "x": 1, "y": 2}, "rác", {"khong": "co-type"}]})
    ok(only["purchase"] == [{"type": "tap", "x": 1, "y": 2}] and only["login"] == [] and only["finish"] == [] and len(only["otp"]) == 2,
       "giai đoạn kịch bản không soạn thì TRỐNG — bộ chạy không lấy bước nào từ gateway; phần tử rác bị bỏ", only)
    ok(jobflow.legacy_gateway_steps(pool) == ({}, {}) and not any(k.endswith("_steps") for k in pool), "pool thường: gateway không giữ (và không trả) bước nào", [k for k in pool if k.endswith("_steps")])
    legacy, bad = jobflow.legacy_gateway_steps(c.pool("game-legacy"))
    ok(bad == {} and legacy == {p: BASE_STEPS[p] for p in jobflow.PHASES if BASE_STEPS[p]},
       "pool ĐỜI CŨ: bước còn lưu ở gateway đổi đúng sang dạng của tool (giữ cờ «bỏ qua nếu lỗi», «chờ chữ @3s» → chờ 3 giây)", legacy)
    old_pool = {"login_steps": [{"type": "home", "value": "", "note": " về home "}], "nav_steps": [{"type": "tap_text", "value": "Shop"}, {"type": "tap", "value": "sai"}], "finish_steps": "rác"}
    lg2, bad2 = jobflow.legacy_gateway_steps(old_pool)
    ok(lg2 == {"login": [{"type": "home", "note": "về home"}]} and list(bad2) == ["nav"] and "x,y" in bad2["nav"],
       "giai đoạn đời cũ có bước sai dạng → bỏ CẢ giai đoạn đó kèm lời báo theo giai đoạn; giai đoạn khác vẫn đổi (ghi chú của bước đi theo)", (lg2, bad2))
    # bộ chạy (lưới an toàn khi kịch bản chưa chép): giai đoạn kịch bản đang trống mà bước đời cũ sai dạng → KHÔNG chạy; có bước rồi thì không vướng
    import store as _store
    said = []
    ap1 = _store.api_defaults({"pool": "x", "steps": {"login": [{"type": "home"}]}})
    stuck = Runner(lambda n: None)._adopt_gateway_steps({"group_id": None, "script_id": None}, ap1, dict(old_pool, finish_steps=[{"type": "home", "value": ""}]), lambda t, k="": said.append(t))
    ok(bool(stuck) and "sai dạng" in stuck and "Vào danh sách gói" in stuck and ap1["gw_steps_copied"] is False and ap1["steps"]["finish"] == [] and said == [],
       "bộ chạy: bước đời cũ sai dạng ở giai đoạn kịch bản đang TRỐNG → trả lời báo để dừng máy, không chép gì, không đánh dấu", stuck)
    ap2 = _store.api_defaults({"pool": "x", "steps": {"login": [{"type": "home"}], "nav": [{"type": "tap_text", "text": "Shop"}]}})
    free = Runner(lambda n: None)._adopt_gateway_steps({"group_id": None, "script_id": None}, ap2, dict(old_pool, finish_steps=[{"type": "home", "value": ""}]), lambda t, k="": said.append(t))
    ok(free is None and ap2["gw_steps_copied"] is True and ap2["steps"]["finish"] == [{"type": "home"}] and ap2["steps"]["nav"] == [{"type": "tap_text", "text": "Shop"}]
       and ap2["steps"]["login"] == [{"type": "home"}] and len(said) == 1 and "Đã chép 1 bước cũ" in said[0],
       "…giai đoạn sai dạng mà kịch bản đã tự có bước → không vướng: chép các giai đoạn trống còn lại, giữ nguyên bước của kịch bản", (free, said))
    ok(jobflow.validate(pool, steps) == [], "pool đủ luật + kịch bản đủ bước → tool chịu chạy", jobflow.validate(pool, steps))
    bare = c.pool("game-bare")
    miss = jobflow.validate(bare, steps)
    ok(len(miss) == 3 and all("thiếu luật" in m for m in miss), "pool thiếu 3 luật bắt buộc (chưa đăng nhập / đăng nhập thành công / nạp thành công) → bị từ chối", miss)
    ok(any("chưa có bước" in m for m in jobflow.validate(pool, dict(steps, finish=[]))), "thiếu bước kết thúc đơn (đăng xuất) → bị từ chối")

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

    print("\n== 1b. Tạm dừng / Tiếp tục (người xử lý tay): lúc tạm dừng KHÔNG nhận đơn mới ==")
    ok(r.runner.pause_machine(r.name) is True and wait_until(lambda: r.status().get("paused") is True, 5), "bấm Tạm dừng lúc đang chờ đơn → máy tạm dừng", r.status())
    ok(r.status()["status"].startswith("TẠM DỪNG") and r.running(), "trạng thái ghi rõ TẠM DỪNG, máy vẫn giữ chỗ (không ai chạy chồng lên được)", r.status())
    buys0, keys0 = len(g.purchases), len(g.keylog)
    purchases_before, keylog_before = list(g.purchases), list(g.keylog)     # các phần sau đếm chính xác số lần mua / gõ của game giả này
    jp = gw.new_job("T-PAUSE", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    time.sleep(2.0)
    held_status = gw.job(jp)["status"]
    ok(held_status not in ("done", "failed", "review", "running") and len(g.purchases) == buys0 and len(g.keylog) == keys0,
       "có đơn mới nhưng máy đang tạm dừng → KHÔNG nhận đơn, không gõ / không mua gì", (held_status, len(g.purchases) - buys0, len(g.keylog) - keys0))
    # Tiếp tục → máy phải KIỂM LẠI «game đã đăng xuất chưa» (sau khi xử lý tay game có thể đã khác). Và nếu người vận hành bấm Tạm dừng
    # đúng lúc máy đang kiểm tra đó thì máy KHÔNG được xin thêm đơn nào nữa.
    checks = {"n": 0, "pause_once": True}
    real_elo = r.runner._ensure_logged_out

    def elo_spy(*a, **k):
        checks["n"] += 1
        out = real_elo(*a, **k)
        if checks["pause_once"]:
            checks["pause_once"] = False
            r.runner.pause_machine(r.name)              # bấm «Tạm dừng» ngay trong lúc đang kiểm tra trước khi xin đơn
        return out
    r.runner._ensure_logged_out = elo_spy
    ok(r.runner.resume_machine(r.name) is True, "bấm Tiếp tục")
    ok(wait_until(lambda: checks["n"] >= 1, 5), "tiếp tục → kiểm lại «game đã đăng xuất chưa» trước khi nhận đơn", checks)
    ok(wait_until(lambda: r.status().get("paused") is True, 5), "bấm Tạm dừng giữa lúc đang kiểm tra → máy tạm dừng lại", r.status())
    time.sleep(1.5)
    mid_status = gw.job(jp)["status"]
    ok(mid_status == held_status and len(g.purchases) == buys0 and g.user is None,
       "…và KHÔNG xin thêm đơn nào sau khi đã bấm Tạm dừng (đơn vẫn nằm chờ, không đăng nhập tài khoản nào)", (mid_status, len(g.purchases) - buys0, g.user))
    r.runner._ensure_logged_out = real_elo
    ok(r.runner.resume_machine(r.name) is True, "bấm Tiếp tục lần nữa")
    jobp = gw.wait_job(jp, ("done", "failed", "review"))
    ok(jobp["status"] == "done" and len(g.purchases) == buys0 + 1 and r.status().get("paused") is False, "tiếp tục → máy nhận và làm xong đơn đang chờ", (jobp["status"], r.status()))
    ok(wait_until(lambda: r.status().get("status") == "Chờ đơn", 8) and r.running(), "rồi quay lại chờ đơn như thường", r.status())
    ok(r.status()["counts"] == {"done": 2, "failed": 0, "review": 0}, "bộ đếm của máy đúng (2 đơn xong)", r.status())
    g.purchases[:] = purchases_before; g.keylog[:] = keylog_before          # trả game giả về như trước phần 1b
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
    hold10 = r10.runner.hold_reason(r10.name)
    ok(bool(hold10) and "còn đăng nhập" in hold10 and r10.runner.customers()[0]["name"] == r10.name,
       "dừng ngay GIỮA đơn (đã bắt đầu đăng nhập, không chạy bước đăng xuất) → máy được GIỮ chờ người kiểm tra: game có thể còn đăng nhập tài khoản khách", hold10)
    r10.runner.stop_machine(r10.name); r10.runner.stop_all(force=True)
    ok(r10.runner.hold_reason(r10.name) == hold10, "…bấm Dừng / Dừng tất cả sau đó KHÔNG gỡ giữ")
    ok(r10.runner.start_machine(r10.name, {"id": "khac", "name": "Nhóm khác", "mode": "once", "devices": [r10.name]},
                                {"id": "s", "name": "S", "steps": [{"type": "home"}], "mode": "once", "loops": 1}) is False,
       "…và kịch bản của nhóm khác không chạy đè lên được")
    ok(r10.runner.ack_hold(r10.name) is True and r10.runner.hold_reason(r10.name) is None, "người vận hành xác nhận «Đã kiểm tra xong» → hết giữ")

    print("\n== 10b. Dừng NGAY đúng lúc đang gõ tài khoản (giữa các bước đăng nhập) → máy phải được GIỮ ==")
    g10b = FakeGame(accounts())
    r10b = rig(g10b)
    real_type = g10b.type

    def type_then_stop(s):
        real_type(s)
        if s == "a@test.vn":                       # vừa gõ xong tài khoản của khách → người vận hành bấm «Dừng ngay»
            r10b.runner.stop_machine(r10b.name, True)
    g10b.type = type_then_stop
    r10b.nav.e.udid, r10b.nav.h.port = "ab-12-cd", "/dev/cu.gia-10b"        # iPhone + cổng của PHIÊN đang dùng thật
    j10b = gw.new_job("T-010b", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    r10b.start()
    job = gw.wait_job(j10b, ("done", "failed", "review"), 15)
    ok(wait_until(lambda: not r10b.running(), 8) and job["status"] == "failed" and g10b.purchases == [], "dừng ngay lúc đang gõ tài khoản → đơn failed (chưa nạp), máy dừng", (job["status"], job["message"]))
    hold10b = r10b.runner.hold_reason(r10b.name)
    ok(bool(hold10b) and [c["name"] for c in r10b.runner.customers()] == [r10b.name],
       "…và máy được GIỮ chờ người kiểm tra: tài khoản của khách đã được gõ vào game, không còn chắc «chưa đăng nhập» (trước đây máy KHÔNG được giữ)", hold10b)
    ok(r10b.runner.start_machine(r10b.name, {"id": "khac", "name": "Nhóm khác", "mode": "once", "devices": [r10b.name]},
                                 {"id": "s", "name": "S", "steps": [{"type": "home"}], "mode": "once", "loops": 1}) is False,
       "…nên kịch bản của nhóm khác không chạy đè lên được")
    c10b = r10b.runner.customers()[0]
    ok(c10b["udid"] == "AB12CD" and c10b["port"] == "/dev/cu.gia-10b" and r10b.runner.conflict("ten-khac", "AB-12-cd", None) == r10b.name,
       "máy của khách được ghi theo iPhone + cổng của phiên đang dùng thật (bộ chạy thật), UDID ở dạng chuẩn", c10b)
    # «Chạy lại» của CHÍNH nhóm đó: tự kiểm game đã đăng xuất; kiểm xong (sạch) thì mới hết giữ
    g10b.type = real_type
    r10b.start()
    ok(wait_until(lambda: r10b.status().get("status") == "Chờ đơn", 10) and r10b.running(), "«Chạy lại» của chính nhóm nhận đơn: máy tự đưa game về chưa đăng nhập rồi chờ đơn", r10b.status())
    r10b.stop()
    ok(r10b.runner.hold_reason(r10b.name) is None and r10b.runner.customers() == [],
       "lần chạy lại ĐÃ kiểm xong game sạch → trạng thái giữ cũ hết hiệu lực (dừng sau đó không giữ lại)", r10b.runner.hold_reason(r10b.name))

    print("\n== 10c. Tài khoản / mật khẩu tool KHÔNG gõ được → từ chối ngay, không đụng game, máy KHÔNG bị giữ ==")
    g10c = FakeGame(accounts())
    r10c = rig(g10c)
    r10c.start()
    ok(wait_until(lambda: r10c.status().get("status") == "Chờ đơn", 8), "máy đang chờ đơn")
    keys_c = len(g10c.keylog)
    j10c = gw.new_job("T-010c", "khách có dấu@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])
    job = gw.wait_job(j10c, ("done", "failed", "review"), 15)
    ok(job["status"] == "failed" and "không gõ được" in (job["message"] or "") and g10c.purchases == [] and "PassA#1" not in g10c.keylog[keys_c:],
       "tài khoản có ký tự tool không gõ được → đơn failed với lý do rõ ràng, KHÔNG gõ gì của khách vào game", (job["status"], job["message"], g10c.keylog[keys_c:]))
    j10c2 = gw.new_job("T-010c2", "a@test.vn", "mật khẩu có dấu", [{"code": "coin_1050", "qty": 1}])
    job2 = gw.wait_job(j10c2, ("done", "failed", "review"), 15)
    ok(job2["status"] == "failed" and "a@test.vn" not in g10c.keylog[keys_c:],
       "MẬT KHẨU không gõ được cũng bị phát hiện TRƯỚC khi gõ tài khoản (không gõ dở nửa chừng rồi bỏ)", (job2["status"], g10c.keylog[keys_c:]))
    ok(wait_until(lambda: r10c.status().get("status") == "Chờ đơn", 10) and r10c.running() and r10c.runner.hold_reason(r10c.name) is None and r10c.runner.customers()[0]["hold"] is None,
       "lỗi do dữ liệu của khách → máy KHÔNG bị dừng / giữ, chờ đơn tiếp như thường", r10c.status())
    r10c.stop()

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
        st = jobflow.order_steps(dict(BASE_STEPS, login=login_steps) if login_steps else BASE_STEPS)
        class NoGw:                                # không gọi mạng: chỉ xét quyết định của luồng xử lý đơn
            def progress(self, *a, **k): return {"ok": True}
            def upload_image(self, *a, **k): return {"ok": True}
        job = {"id": "JDIRECT", "login": {"username": "otp@test.vn", "password": "PassB#2"}, "items": [{"code": "coin_1050", "name": "1050 Coins", "qty": 1, "ocr_text": "1050|1,050"}]}
        return jobflow.JobFlow(FakeNav(game), NoGw(), job, pool_cfg, st, opts={"login_wait": 2, "purchase_wait": 2, "clear_wait": 0.2}).run()
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
        jf = jobflow.JobFlow(Seq(texts), NoGw(), {"id": "J", "login": {}, "items": []}, pool_cfg, jobflow.order_steps(BASE_STEPS),
                             opts={"login_wait": 1, "purchase_wait": wait, "clear_wait": 0.2})
        return jf._read_result(list(jobflow.RESULT_RULES))[0]
    ok(reader(["Đang xử lý", "Thanh toán thất bại", "Mua thành công! Đóng"]) == "purchase_success", "thoáng thấy chữ «thất bại» rồi «thành công» hiện ra → tính là ĐÃ NẠP")
    ok(reader(["Đang xử lý", "Thanh toán thất bại. Đóng"]) == "purchase_fail", "chữ «thất bại» hiện ổn định (nhiều lần nhìn liền, đủ lâu) → mới kết luận thất bại")
    ok(reader(["Thanh toán thất bại", "Đang xử lý", "Đang xử lý", "Mua thành công!"]) == "purchase_success", "chữ báo lỗi chỉ lóe lên một lần (OCR nhầm) → không kết luận, chờ tiếp tới khi có kết quả thật")
    ok(reader(["Đang xử lý"], wait=0.6) is None, "hết giờ mà không có chữ kết quả nào → «không xác nhận được» (đơn sẽ chuyển đối soát)")
    ok(reader(["Đã mua gói này rồi"], wait=1.0) == "package_unavailable", "«không mua được» hiện ổn định → kết luận đúng loại")

    # --- hằng số THẬT (NEG_GRACE mặc định) trên đồng hồ giả: game chậm không được làm báo sai «không mua được» sau khi đã mua (verify vòng 6, W-5) ---
    import types
    class Clock:
        t = 0.0
    real_time_mod, real_sleep_fn, real_grace = stepexec.time, stepexec._sleep, jobflow.JobFlow.NEG_GRACE      # (stepexec.time và jobflow.time là cùng một mô-đun time)
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
        flow = jobflow.JobFlow(nav, None, {"id": "J", "items": [{"code": "c", "name": "1050 Coins", "qty": 1}]}, {"rules": prod_rules}, steps,
                               opts={"purchase_wait": 60, "clear_wait": 8}, log=lambda *a, **k: None)
        return flow._buy_one({"code": "c", "name": "1050 Coins", "qty": 1}, {})[0]
    try:
        stepexec.time = jobflow.time = types.SimpleNamespace(time=lambda: Clock.t, sleep=lambda s: setattr(Clock, "t", Clock.t + s), strftime=time.strftime)
        stepexec._sleep = lambda sec, abort=None: setattr(Clock, "t", Clock.t + sec)
        jobflow.JobFlow.NEG_GRACE = PROD_NEG_GRACE
        wrong = [(tl, oa, lag_run(tl, oa)) for tl in (0.0, 6.0, 9.0, 20.0) for oa in (1.0, 5.0, 15.0, 25.0) if lag_run(tl, oa) != "ok"]
        ok(wrong == [], "hằng số THẬT: nhãn «Đã mua gói này» ở ô khác hiện muộn + hộp thoại «thành công» hiện chậm tới 25 s sau khi bấm → vẫn tính ĐÃ NẠP (trước đây báo «không mua được» dù đã trừ tiền)", wrong)
        ok(lag_run(0.0, None, 2.0) == "failed" and lag_run(0.0, None, None) in ("unavailable", "uncertain"),
           "hằng số THẬT: lỗi thật («Thanh toán thất bại» hiện sau 2 s, không bao giờ có «thành công») vẫn được kết luận «thất bại»; chỉ có nhãn cũ thì không bao giờ ra «thành công»")
        def lag_run_wait(t_label, t_ok_after, wait):
            Clock.t = 0.0
            nav = LagNav(t_label, t_ok_after)
            steps = {"login": [], "finish": [], "otp": [], "nav": [], "after": [], "purchase": [{"type": "key", "name": "enter"}]}
            flow = jobflow.JobFlow(nav, None, {"id": "J", "items": [{"code": "c", "name": "1050 Coins", "qty": 1}]}, {"rules": prod_rules}, steps,
                                   opts={"purchase_wait": wait, "clear_wait": 8}, log=lambda *a, **k: None)
            return flow._buy_one({"code": "c", "name": "1050 Coins", "qty": 1}, {})[0]
        wrong = [(w_, tl, oa, lag_run_wait(tl, oa, w_)) for w_ in (10, 20, 30, 45, 60, 120) for tl in (0.0, 6.0, 9.0) for oa in (1.0, 5.0, 9.0, 15.0, 20.0, 25.0, 30.0)
                 if oa + 6 < w_ and lag_run_wait(tl, oa, w_) != "ok"]
        ok(wrong == [], "hằng số THẬT: purchase_wait NGẮN (10–45 s) + nhãn cũ hiện muộn + «thành công» hiện chậm trong khoảng chờ → vẫn tính ĐÃ NẠP (trước đây ngưỡng co theo purchase_wait → báo «không mua được» dù đã mua)", wrong[:4])
        ok(lag_run_wait(0.0, None, 20) in ("uncertain", "unavailable") and lag_run_wait(0.0, None, 20) != "failed",
           "purchase_wait ngắn mà chỉ có nhãn cũ, không có «thành công» → không bao giờ ra «đã nạp»")
        class AdNav:                               # cửa hàng; có hộp quảng cáo thì chữ «Quảng cáo» + nút «Đóng» hiện ở lần nhìn đầu
            def __init__(self, ad):
                self.ad, self.sent, self.taps = ad, [], []
                self.e = self; self.h = self
            def screenshot(self): Clock.t += 0.5; return None
            def read_text(self, img=None, **kw):
                Clock.t += 0.5
                return "Cửa hàng 1050 Coins" + (" Quảng cáo Đóng" if self.ad else "")
            def find_text(self, needle, img=None, **kw):
                return (600, 300) if (self.ad and "dong" in stepexec.norm_text(needle)) else None
            def tap_at(self, x, y, click=True, verify=None):
                self.taps.append((x, y)); self.ad = False; return True
            def send(self, cmd, wait=0.5):
                self.sent.append(cmd); Clock.t += 0.2; return "OK " + cmd.split(" ")[0]
        def ad_run(ad):
            Clock.t = 0.0
            nav = AdNav(ad)
            steps = {"login": [], "finish": [], "otp": [], "nav": [], "after": [],
                     "purchase": [{"type": "tap_if", "text": "Quảng cáo", "tap": "Đóng", "timeout": 0}, {"type": "tap_text", "text": "Gói không có trên màn hình"}]}
            flow = jobflow.JobFlow(nav, None, {"id": "J", "items": [{"code": "c", "name": "1050 Coins", "qty": 1}]}, {"rules": prod_rules}, steps,
                                   opts={"purchase_wait": 20, "clear_wait": 8}, log=lambda *a, **k: None)
            return flow._buy_one({"code": "c", "name": "1050 Coins", "qty": 1}, {})[0], flow.risky, nav.taps, nav.sent
        clean_, dirty_ = ad_run(False), ad_run(True)
        ok(clean_[0] == "failed_tool" and clean_[1] is False and clean_[2] == [] and not any(c.startswith(("click", "key", "type")) for c in clean_[3]),
           "giai đoạn mua: bước «nếu thấy thì bấm» KHÔNG thấy gì (bỏ qua, chưa đụng vào máy) rồi bước kế không thấy gói → «chưa mua» (lỗi tool), KHÔNG thành «không chắc» / đối soát giả", clean_)
        ok(dirty_[0] == "uncertain" and dirty_[1] is True and dirty_[2] == [(600, 300)],
           "…còn nếu bước đó ĐÃ BẤM đóng một hộp thoại thì từ đó là «đã chạm luồng mua» → trục trặc sau nó vẫn là «không chắc» (đối soát)", dirty_)
        ok(lag_run(0.0, None, 55.0) == "uncertain" and lag_run(0.0, None, 40.0) == "uncertain" and lag_run(0.0, None, 15.0) == "failed",
           "hằng số THẬT: chữ báo lỗi chỉ mới hiện vài giây trước khi hết giờ (chưa ổn định đủ lâu, success có thể còn đang tới) → «không xác nhận được» (đối soát), KHÔNG kết luận thất bại")
    finally:
        stepexec.time, stepexec._sleep, jobflow.JobFlow.NEG_GRACE = real_time_mod, real_sleep_fn, real_grace
        jobflow.time = real_time_mod
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
    r = stepexec.exec_step(FakeNav(gc), {"type": "tap_text", "text": "Cửa hàng"}, {})
    ok(r[0] is False and r[2] is False and gc.clicks == 0, "bấm chữ: màn hình đổi trước khi kịp bấm → không bấm, và chắc chắn chưa chạm", r)
    gc2 = FakeGame(accounts(), change_before_click=True); gc2.screen = "main"
    r = stepexec.exec_step(FakeNav(gc2), {"type": "hold_text", "text": "Cửa hàng", "seconds": 1}, {})
    ok(r[0] is False and gc2.gestures == [], "giữ chữ: màn hình đổi trước khi kịp nhấn → không nhấn", (r, gc2.gestures))
    # cử chỉ hỏng: đã nhấn nút hay chưa?
    class Press:                                           # board có đếm số lần nhấn nút (như Hands thật)
        presses = 0
    gg = FakeGame(accounts()); ng = FakeNav(gg); ng.h = Press(); ng._hid_sent = 7
    r = stepexec.gesture(ng, "vuốt", lambda: False)
    ok(r[0] is False and r[2] is False and ng._hid_sent == 7 and "chưa chạm" in r[1], "cử chỉ hỏng mà nút CHƯA hề được nhấn (con trỏ không tới điểm đầu) → chắc chắn chưa chạm vào app", r)
    def half():
        ng.h.presses += 1; return False
    r = stepexec.gesture(ng, "vuốt", half)
    ok(r[0] is False and r[2] is True and ng._hid_sent == 8, "cử chỉ hỏng SAU khi đã nhấn nút → «không chắc» (ở bước mua sẽ thành review)", r)
    def boom():
        ng.h.presses += 1; raise OSError("cổng chết")
    try:
        stepexec.gesture(ng, "vuốt", boom); raised = False
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

    print("\n== 24. Vuốt + bấm giữ trong kịch bản → tool chạy đúng (gói nằm ở trang 2 của cửa hàng) ==")
    g30 = FakeGame(accounts())
    r30 = rig(g30, pool="game-swipe", local_steps={"nav": SWIPE_NAV})
    j30 = gw.new_job("T-030", "a@test.vn", "PassA#1", [{"code": "legend", "qty": 1}], pool="game-swipe")
    r30.start()
    job = gw.wait_job(j30, ("done", "failed", "review"))
    ok(job["status"] == "done" and g30.purchases == [("a@test.vn", "legend")], "đơn hoàn tất, mua đúng gói ở trang 2", (job["status"], job["message"], g30.purchases))
    ok(g30.gestures[:1] == [("flick", "left")] and len(g30.gestures) == 2 and g30.gestures[1][0] == "hold" and g30.gestures[1][3] == 0.5,
       "máy nhận đúng: vuốt sang trái rồi bấm giữ 0,5 giây vào chữ", g30.gestures)
    r30.stop()

    print("\n== 25. Vuốt / bấm giữ: đổi cấu hình thành bước, mô tả, chạy, báo lỗi ==")
    conv = jobflow.gw_step_to_engine
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
        except stepexec.ConfigError: bad += 1
    ok(bad == 3, "giá trị sai dạng → báo lỗi cấu hình rõ ràng (không chạy bừa)", bad)
    ok(stepexec.describe({"type": "swipe", "dir": "left"}) and "trái" in stepexec.describe({"type": "swipe", "dir": "left"})
       and "giữ" in stepexec.describe({"type": "hold", "x": 1, "y": 2, "seconds": 1.5}).lower(), "có mô tả tiếng Việt cho nhật ký")
    gq = FakeGame(accounts()); nq = FakeNav(gq)
    ok(stepexec.exec_step(nq, {"type": "swipe", "x1": 375, "y1": 1000, "x2": 375, "y2": 400}, {}) == (True, "", True) and gq.gestures == [("swipe", 375, 1000, 375, 400)], "chạy bước vuốt theo toạ độ", gq.gestures)
    ok(stepexec.exec_step(nq, {"type": "hold", "x": 636, "y": 468, "seconds": 1.3}, {})[0] is True and gq.gestures[-1] == ("hold", 636, 468, 1.3), "chạy bước bấm giữ", gq.gestures)
    r = stepexec.exec_step(nq, {"type": "hold_text", "text": "Chữ không có trên màn", "seconds": 1}, {})
    ok(r[0] is False and r[2] is False and len(gq.gestures) == 2, "bấm giữ vào chữ KHÔNG có trên màn hình → lỗi, chắc chắn chưa chạm gì", r)
    gf = FakeGame(accounts(), pointer_fail=True); nf = FakeNav(gf)
    r = stepexec.exec_step(nf, {"type": "swipe", "dir": "up"}, {})
    ok(r[0] is False and r[2] is True and gf.gestures == [], "cử chỉ hỏng giữa chừng → coi là «không chắc đã chạm» (ở bước mua sẽ thành review, không phải failed)", r)
    try:
        stepexec.exec_step(nq, {"type": "swipe", "dir": "cheo"}, {}); raised = False
    except stepexec.ConfigError:
        raised = True
    ok(raised and set(("swipe", "hold", "hold_text")) <= set(stepexec.INPUT_TYPES), "hướng lạ → lỗi cấu hình; vuốt/bấm giữ được tính là «thao tác vào máy»")

    print("\n== 26. Đoạn «mở game» + điểm chặn trước khi gõ tài khoản ==")
    L = lambda *steps: [dict(s) for s in steps]
    std = L({"type": "launch", "app": "efootball"}, {"type": "wait_text", "text": "Konami ID", "timeout": 3}, {"type": "tap_text", "text": "Đăng nhập"},
            {"type": "type", "text": "{{username}}"}, {"type": "key", "name": "tab"}, {"type": "type", "text": "{{password}}"}, {"type": "key", "name": "enter"})
    ok([s["type"] for s in jobflow.open_prefix(std)] == ["launch", "wait_text"] and jobflow.credential_gate(std) == 3,
       "danh sách thường: đoạn mở game dừng TRƯỚC cú bấm đầu tiên; chặn ngay trước bước gõ {{username}}")
    fixed = L({"type": "launch", "app": "efootball"}, {"type": "type", "text": "vn"}, {"type": "key", "name": "enter"}, {"type": "type", "text": "{{username}}"})
    ok(len(jobflow.open_prefix(fixed)) == 3 and jobflow.credential_gate(fixed) == 3, "gõ chữ CỐ ĐỊNH (không phải của khách) vẫn thuộc đoạn mở game")
    tapin = L({"type": "launch", "app": "efootball"}, {"type": "tap_text", "text": "Vào bằng Game Center"})
    ok(jobflow.credential_gate(tapin) == 1 and jobflow.credential_gate([]) == 0 and jobflow.open_prefix(None) == [],
       "đăng nhập bằng cách BẤM (không gõ tài khoản): chặn ngay sau đoạn mở game, trước cú bấm")
    for odd in ("hold", "hold_text", "swipe", "tap"):
        ok(jobflow.open_prefix(L({"type": "launch", "app": "x"}, {"type": odd}, {"type": "wait", "seconds": 1})) == [{"type": "launch", "app": "x"}],
           "bước «%s» (có chạm vào app) không bao giờ nằm trong đoạn mở game" % odd)
    gp = FakeGame(accounts()); gp.user = "a@test.vn"                    # game còn phiên của khách trước
    rules = pool_cfg.get("rules") or []
    state = jobflow.session_probe(FakeNav(gp), {"login": std}, rules, 2)
    ok(state == "in" and gp.clicks == 0 and gp.keylog == ["efootball"], "dò phiên: chỉ mở game rồi ĐỌC màn hình — không bấm, không gõ gì của khách", (state, gp.clicks, gp.keylog))
    ok(jobflow.session_probe(FakeNav(FakeGame(accounts())), {"login": std}, rules, 2) == "out", "game chưa ai đăng nhập → «out»")
    gu = FakeGame(accounts())
    ok(jobflow.session_probe(FakeNav(gu), {"login": L({"type": "launch", "app": "app-khong-co"})}, rules, 1) == "unknown", "không nhận ra màn hình → «unknown» (máy sẽ không nhận đơn)")

    print("\n== 27. Máy đang giữ đơn của pool KHÁC với pool của nhóm → đối soát, không chạy bằng cấu hình sai ==")
    g29 = FakeGame(accounts())
    r29 = rig(g29, pool="game-swipe", local_steps={"nav": SWIPE_NAV})
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

    print("\n== 30. Bước có điều kiện «nếu thấy chữ … thì bấm» (hộp thoại lúc có lúc không) ==")

    class Popup:                                   # màn hình giả: danh sách (các dòng chữ, {chữ: toạ độ}) theo từng lần chụp
        def __init__(self, shots):
            self.shots, self.n, self.taps, self.cur, self.sent = list(shots), 0, [], None, []
            self.e, self.h = self, self

        def screenshot(self):
            self.cur = self.shots[min(self.n, len(self.shots) - 1)]; self.n += 1
            return self.cur

        def read_text(self, img=None, **kw):
            return "\n".join((img or self.cur)[0])

        def find_text(self, needle, img=None, **kw):
            want = stepexec.norm_text(needle).replace(" ", "")
            for k, pos in (img or self.cur)[1].items():
                if want in stepexec.norm_text(k).replace(" ", ""):
                    return pos
            return None

        def tap_at(self, x, y, click=True, verify=None):
            if verify is not None and not verify(self.cur):
                return False
            self.taps.append((x, y))
            if len(self.taps) > 40:                # bước bấm mãi không dừng → bài thử HỎNG NGAY (không treo)
                raise AssertionError("bước bấm quá 40 lần — không có chốt dừng")
            return True

        def send(self, cmd, wait=0.5):
            self.sent.append(cmd)
            return "OK"
    gc = (["Hủy", "Chào mừng đến", "Game Center", "ID Apple"], {"Hủy": (73, 33), "Game Center": (668, 308)})
    title = (["FOOTBALL", "2027", "Konami Digital Entertainment"], {"FOOTBALL": (666, 435)})
    real_settle, real_sleep = stepexec.LOOK_SETTLE, stepexec._sleep
    stepexec.LOOK_SETTLE = 0
    stepexec._sleep = lambda sec, abort=None: None
    try:
        ti = {"type": "tap_if", "text": "Game Center", "tap": "Hủy", "timeout": 8}
        n1 = Popup([gc, title])
        r1 = stepexec.exec_step(n1, ti, {})
        ok(r1[0] is True and r1[2] is True and n1.taps == [(73, 33)] and n1.sent == ["click"] and "đã bấm «Hủy»" in r1[1],
           "thấy hộp thoại → bấm đúng chữ cần bấm (một lần), báo «đã bấm»", (r1, n1.taps, n1.sent))
        n2 = Popup([title])
        r2 = stepexec.exec_step(n2, dict(ti, timeout=0), {})
        ok(r2 == (True, "không thấy «Game Center» — bỏ qua", False) and n2.taps == [] and n2.sent == [] and n2.n == 1,
           "không có hộp thoại (timeout 0: chỉ xem một lần) → bước XONG, không bấm gì", (r2, n2.n))
        n3 = Popup([title, title, gc, title])
        r3 = stepexec.exec_step(n3, ti, {})
        ok(r3[0] is True and n3.taps == [(73, 33)] and n3.n == 4, "hộp thoại hiện CHẬM (lần chụp thứ 3) → vẫn bắt được trong thời gian chờ rồi bấm", (r3, n3.n))
        n4 = Popup([(["Game Center", "ID Apple"], {"Game Center": (668, 308)})])
        r4 = stepexec.exec_step(n4, dict(ti, timeout=0), {})
        ok(r4[0] is False and r4[2] is False and n4.taps == [] and "không thấy chữ «Hủy» để bấm" in r4[1],
           "hết thời gian chờ mà vẫn thấy hộp thoại nhưng KHÔNG thấy chữ cần bấm → bước hỏng (màn hình đang bị chắn — không đi tiếp bấm nhầm)", r4)
        slide = (["Game Center"], {})                  # hộp thoại đang trượt vào: tiêu đề đã hiện, nút «Hủy» chưa
        n4b = Popup([slide, slide, gc, title])
        r4b = stepexec.exec_step(n4b, ti, {})
        ok(r4b[0] is True and n4b.taps == [(73, 33)] and n4b.n == 4, "nút cần bấm hiện CHẬM hơn chữ (hộp thoại đang trượt vào) → nhìn lại rồi bấm, không báo hỏng vội", (r4b, n4b.n))
        # đo thật trên iPhone 8: trước trang «Chào mừng đến Game Center» (có «Hủy») còn trang «Tính năng mới trong Game Center» (chỉ có «Tiếp tục»)
        news = (["Tính năng mới trong", "Game Center", "Tiếp tục"], {"Tiếp tục": (668, 694), "Game Center": (324, 405)})
        real = {"type": "tap_if", "timeout": 0, "cases": [{"text": "Game Center", "tap": "Hủy"}, {"text": "Tính năng mới", "tap": "Tiếp tục"}]}
        n4c = Popup([news, gc, title])
        r4c = stepexec.exec_step(n4c, real, {})
        ok(r4c[0] is True and n4c.taps == [(668, 694), (73, 33)],
           "hai màn hình cùng có chữ «Game Center»: màn nào không có nút của trường hợp thứ nhất thì xét trường hợp kế (bấm «Tiếp tục»), màn sau mới bấm «Hủy»", (r4c, n4c.taps))
        n5 = Popup([gc, title])
        r5 = stepexec.exec_step(n5, {"type": "tap_if", "text": "Game Center|Trung tâm trò chơi"}, {})
        ok(r5[0] is True and n5.taps == [(668, 308)], "không ghi «bấm vào đâu» → bấm chính chữ vừa thấy; nhiều cách viết ngăn bằng «|»", (r5, n5.taps))

        # NHIỀU trường hợp trong một bước: hỏi mật khẩu → Hủy; Game Center → Hủy; không thấy gì → bỏ qua
        pw = (["Đăng nhập bằng ID Apple", "Nhập mật khẩu cho tài khoản", "Hủy", "OK"], {"Hủy": (300, 500), "OK": (520, 500)})
        multi = {"type": "tap_if", "timeout": 0, "cases": [{"text": "mật khẩu", "tap": "Hủy"}, {"text": "Game Center", "tap": "Hủy"}]}
        m1 = Popup([pw, gc, title])
        q1 = stepexec.exec_step(m1, multi, {})
        ok(q1[0] is True and q1[2] is True and m1.taps == [(300, 500), (73, 33)] and m1.sent == ["click", "click"] and "thấy «mật khẩu»" in q1[1] and "thấy «Game Center»" in q1[1],
           "hai hộp thoại nối nhau (hỏi mật khẩu rồi Game Center) → bấm «Hủy» của TỪNG cái, đúng chỗ, rồi xong", (q1, m1.taps))
        m2 = Popup([gc, pw, title])
        q2 = stepexec.exec_step(m2, multi, {})
        ok(q2[0] is True and m2.taps == [(73, 33), (300, 500)], "hộp thoại hiện theo thứ tự NGƯỢC lại → vẫn xử lý đủ (không phụ thuộc thứ tự ghi trong bước)", (q2, m2.taps))
        m3 = Popup([title])
        q3 = stepexec.exec_step(m3, multi, {})
        ok(q3 == (True, "không thấy «mật khẩu» / «Game Center» — bỏ qua", False) and m3.taps == [], "không có hộp thoại nào → bỏ qua, không bấm gì", q3)
        m4 = Popup([gc, title])
        q4 = stepexec.exec_step(m4, multi, {})
        ok(q4[0] is True and m4.taps == [(73, 33)], "chỉ một trong các trường hợp xảy ra → chỉ bấm cái đó")
        m5 = Popup([gc])                               # bấm «Hủy» rồi mà hộp thoại vẫn còn mãi
        q5 = stepexec.exec_step(m5, multi, {})
        ok(q5[0] is False and q5[2] is True and len(m5.taps) == stepexec.IF_REPEAT and "hộp thoại không đóng" in q5[1],
           "bấm rồi mà hộp thoại KHÔNG đóng → dừng sau %d lần, báo hỏng (không bấm mãi)" % stepexec.IF_REPEAT, (q5, m5.taps))
        m6 = Popup([(["Nhập mật khẩu"], {})])
        q6 = stepexec.exec_step(m6, multi, {})
        ok(q6[0] is False and m6.taps == [] and "không thấy chữ «Hủy» để bấm" in q6[1], "thấy hộp thoại nhưng không thấy nút cần bấm → hỏng, không bấm bừa", q6)
        for bad in ({"type": "tap_if", "cases": ["rác"]}, {"type": "tap_if", "cases": [{"text": "a"}, {"text": ""}]}):
            try:
                stepexec.exec_step(Popup([gc]), bad, {}); raised = False
            except stepexec.ConfigError:
                raised = True
            ok(raised, "danh sách trường hợp sai dạng → báo lỗi cấu hình")
        ok(stepexec.describe(multi) == "Nếu thấy chữ «mật khẩu» thì bấm «Hủy»; Nếu thấy chữ «Game Center» thì bấm «Hủy»", "mô tả bước nhiều trường hợp", stepexec.describe(multi))

        class Moved(Popup):                          # chữ cần bấm biến mất trước khi con trỏ tới nơi
            def tap_at(self, x, y, click=True, verify=None):
                self.cur = title
                return super().tap_at(x, y, click, verify)
        n6 = Moved([gc])
        r6 = stepexec.exec_step(n6, ti, {})
        ok(r6[0] is False and n6.taps == [] and n6.sent == [], "hộp thoại tự biến mất trước khi kịp bấm → KHÔNG bấm vào chỗ cũ", r6)
        for bad in ({"type": "tap_if", "text": ""}, {"type": "tap_if", "text": "x", "timeout": "abc"}):
            try:
                stepexec.exec_step(Popup([gc]), bad, {}); raised = False
            except stepexec.ConfigError:
                raised = True
            ok(raised, "bước có điều kiện cấu hình sai (%s) → báo lỗi cấu hình, không chạy bừa" % ("thiếu chữ cần thấy" if not bad["text"] else "thời gian chờ không phải số"))
        ok(stepexec.describe(ti) == "Nếu thấy chữ «Game Center» thì bấm «Hủy»" and stepexec.describe({"type": "tap_if", "text": "{{otp}}", "optional": True}, {"otp": "123"}) == "Nếu thấy chữ «{{otp}}» thì bấm «{{otp}}» (bỏ qua nếu lỗi)",
           "mô tả bước có điều kiện; biến bí mật vẫn chỉ hiện TÊN biến", stepexec.describe(ti))
        ok("tap_if" in stepexec.INPUT_TYPES, "bước có điều kiện được tính là bước CÓ THỂ chạm vào máy (trong giai đoạn mua: trục trặc sau nó là «không chắc», không phải «chưa nạp»)")
        login = [{"type": "launch", "app": "efootball"}, ti, {"type": "wait_text", "text": "Konami ID"}, {"type": "tap_text", "text": "Đăng nhập"}, {"type": "type", "text": "{{username}}"}]
        ok([x["type"] for x in jobflow.open_prefix(login)] == ["launch", "tap_if", "wait_text"] and jobflow.credential_gate(login) == 4,
           "trong các bước đăng nhập, bước dọn hộp thoại thuộc «đoạn mở game» (chạy cả khi kiểm «game chưa đăng nhập» trước lúc nhận đơn); chốt chặn vẫn ở bước gõ tài khoản")
        # bộ chạy kịch bản thường dùng CÙNG cách làm
        import engine
        n7 = Popup([gc, title])
        ok7, msg7 = engine.run_step(n7, ti)
        n8 = Popup([title])
        ok8, msg8 = engine.run_step(n8, dict(ti, timeout=0))
        ok(ok7 is True and n7.taps == [(73, 33)] and "đã bấm" in msg7 and ok8 is True and n8.taps == [] and "bỏ qua" in msg8 and "tap_if" in stepexec.STEP_TYPES,
           "kịch bản thường / thử một bước: cùng kết quả (bấm khi thấy, bỏ qua khi không thấy) và nói rõ đã làm gì", (msg7, msg8))

        class Slow(Popup):                           # đưa con trỏ tới nơi tốn thời gian THẬT (trên máy thật: vài giây tới hơn chục giây)
            def tap_at(self, x, y, click=True, verify=None):
                time.sleep(0.25)
                return super().tap_at(x, y, click, verify)
        loading = (["đang tải"], {})
        m7 = Slow([pw, loading, gc, title])
        q7 = stepexec.exec_step(m7, dict(multi, timeout=0.2), {})
        ok(q7[0] is True and m7.taps == [(300, 500), (73, 33)],
           "bấm xong một hộp thoại thì thời gian chờ được tính LẠI từ lúc đó (đưa con trỏ tới nơi đã ngốn hết thời gian chờ ban đầu) → hộp thoại kế hiện sau một nhịp vẫn được xử lý",
           (q7, m7.taps))

        # «thì NHẤN PHÍM»: hộp «lưu mật khẩu» của iOS không nhận cú bấm của con trỏ, chỉ đóng được bằng phím esc (đo trên trang đăng nhập KONAMI)
        sp = (["Bạn có muốn lưu mật khẩu này để sử dụng với các", "ứng dụng và trang web không?", "Lưu mật khẩu", "Không lưu cho trang này", "Để sau"],
              {"Lưu mật khẩu": (667, 433), "Không lưu cho trang này": (663, 550), "Để sau": (667, 675)})
        # Cú bấm lên hộp thoại hệ thống có lúc KHÔNG «ăn» (đo trên iPhone 8: bước báo đã bấm mà hộp thoại vẫn còn) → bước một trường hợp
        # cũng phải nhìn lại: còn thì bấm lần nữa, hết mới báo xong; bấm đủ số lần vẫn còn thì HỎNG (không báo ✓ để các bước sau trượt khó hiểu).
        k1 = Popup([gc, gc, gc, title])
        j1 = stepexec.exec_step(k1, ti, {})
        ok(j1[0] is True and k1.taps == [(73, 33), (73, 33)] and "đã bấm «Hủy» (2 lần)" in j1[1], "bấm lần đầu không ăn (nhìn lại rồi kiểm thêm lần nữa vẫn còn hộp thoại) → bấm lần nữa, báo rõ đã bấm 2 lần", (j1, k1.taps))
        k1b = Popup([gc, gc, title])
        j1b = stepexec.exec_step(k1b, ti, {})
        ok(j1b[0] is True and k1b.taps == [(73, 33)] and "2 lần" not in j1b[1], "hộp thoại ĐÓNG CHẬM (lần nhìn lại còn, kiểm thêm thì đã hết) → KHÔNG bấm lần hai, bước xong", (j1b, k1b.taps))

        class LateClose(Popup):                      # hộp thoại tự đóng đúng lúc con trỏ đang đi tới để bấm lần hai
            def tap_at(self, x, y, click=True, verify=None):
                if self.taps:
                    self.cur = title
                    self.shots = [title]
                    return False
                return super().tap_at(x, y, click, verify)
        k1c = LateClose([gc, gc, gc, gc])
        j1c = stepexec.exec_step(k1c, ti, {})
        ok(j1c[0] is True and k1c.taps == [(73, 33)], "lần bấm lặp bị chặn vì hộp thoại vừa đóng trong lúc con trỏ đang đi → nhìn lại thấy đã hết → bước XONG (không báo «con trỏ không tới nơi»)", (j1c, k1c.taps))
        flick = [gc, gc] + [title, gc] * 40          # sau lần bấm đầu: lần nhìn thấy hộp thoại, lần kiểm lại thì không, cứ thế mãi
        k1e = Popup(flick)
        j1e = stepexec.exec_step(k1e, ti, {})
        ok(j1e[0] is False and j1e[2] is True and k1e.taps == [(73, 33)] and "lúc thấy lúc không" in j1e[1] and k1e.n <= 4 + 2 * (stepexec.IF_FLIPS_MAX + 2),
           "hộp thoại lúc thấy lúc không (chữ nhấp nháy / đọc lúc được lúc không) → bước DỪNG sau %d lần nhìn lại, không nhìn mãi và không bấm thêm" % stepexec.IF_FLIPS_MAX, (j1e, k1e.n))
        k1f = Popup([sp, sp] + [title, sp] * 40)
        j1f = stepexec.exec_step(k1f, {"type": "tap_if", "text": "lưu mật khẩu này", "key": "esc", "timeout": 0}, {})
        ok(j1f[0] is False and k1f.sent == ["key esc"] and "lúc thấy lúc không" in j1f[1], "…trường hợp «nhấn phím» cũng có chốt dừng đó (và không nhấn phím thêm)", (j1f, k1f.sent))
        # «xong khi thấy chữ» (until): chờ lâu được (hộp thoại hiện muộn sau khi game tải) mà màn hình đã sạch thì xong ngay
        home = (["Home", "Shop", "Academy", "Extras", "Match"], {"Shop": (514, 110)})
        bonus = (["Login Bonus", "Continue", "10,000"], {"Continue": (668, 587)})
        loading = (["KONAMI"], {})
        pops = {"type": "tap_if", "timeout": 60, "until": "Shop", "cases": [{"text": "Login Bonus", "tap": "Continue"}, {"text": "Sign Players", "tap": "OK"}]}
        real_stable = stepexec.UNTIL_STABLE
        stepexec.UNTIL_STABLE = 0.3                     # (bài thử: «sạch liên tục» rút còn 0,3 giây cho nhanh)
        u1 = Popup([loading, loading, loading, bonus, home])
        t0 = time.time()
        v1 = stepexec.exec_step(u1, pops, {})
        ok(v1[0] is True and u1.taps == [(668, 587)] and time.time() - t0 < 5 and "Continue" in v1[1],
           "hộp thoại hiện MUỘN (sau 3 lần nhìn) → vẫn bắt được; xử lý xong, thấy «Shop» là xong NGAY (không chờ hết 60 giây)", (v1, u1.taps))
        u2 = Popup([home])
        v2 = stepexec.exec_step(u2, pops, {})
        ok(v2 == (True, "thấy «Shop» — không có gì phải xử lý", False) and u2.taps == [] and u2.n >= 2,
           "màn hình đã sạch ngay từ đầu → xong ngay khi «sạch» đủ lâu (không chờ hết 60 giây), không bấm gì", (v2, u2.n))
        covered = (["Home", "Shop", "Sign Players", "OK"], {"OK": (667, 571)})     # chữ «until» lộ ra nhưng hộp thoại vẫn đang che
        u3 = Popup([covered, home])
        v3 = stepexec.exec_step(u3, pops, {})
        ok(v3[0] is True and u3.taps == [(667, 571)], "chữ «until» có trên màn hình nhưng vẫn còn hộp thoại → xử lý hộp thoại trước (trường hợp được xét trước «until»)", (v3, u3.taps))
        slid = (["Home", "Shop", "Sign Players"], {})                         # thấy chữ hộp thoại mà chưa thấy nút → không được coi là sạch
        u4 = Popup([slid, covered, home])
        v4 = stepexec.exec_step(u4, pops, {})
        ok(v4[0] is True and u4.taps == [(667, 571)], "hộp thoại đang trượt vào (chưa thấy nút) mà «until» đã lộ → KHÔNG kết thúc sớm, chờ nút rồi bấm", (v4, u4.taps))

        class Slow(Popup):                           # mỗi lần chụp mất 0,1 giây thật: hộp thoại «trượt vào» kéo dài LÂU HƠN thời gian «sạch liên tục»
            def screenshot(self):
                time.sleep(0.1)
                return super().screenshot()
        u4b = Slow([slid] * 6 + [covered, home])
        v4b = stepexec.exec_step(u4b, pops, {})
        ok(v4b[0] is True and u4b.taps == [(667, 571)], "…kể cả khi chữ của hộp thoại (chưa có nút) cùng «until» kéo dài quá thời gian «sạch» → vẫn chờ nút, không kết thúc sớm / không báo hỏng sớm", (v4b, u4b.taps))
        ok(stepexec.describe(pops).endswith(" (xong khi thấy «Shop»)"), "mô tả bước nói rõ điều kiện xong sớm", stepexec.describe(pops))
        u5 = Popup([home, bonus, home])                # đo thật: tab «Shop» hiện THOÁNG QUA trước khi «Login Bonus» trượt vào
        v5 = stepexec.exec_step(u5, pops, {})
        ok(v5[0] is True and u5.taps == [(668, 587)], "«Shop» chỉ thoáng qua (chưa đủ thời gian «sạch liên tục») → KHÔNG kết thúc sớm; hộp thoại hiện sau đó vẫn được xử lý", (v5, u5.taps))
        # nút không đọc được chữ (đo thật: chữ «OK» xanh nhạt của hộp «Sign Players» không có trong kết quả đọc chữ) → «bấm tại toạ độ»
        sign = (["Home", "Extras", "Sign Players", "Sign players to create your ideal team."], {})
        atc = {"type": "tap_if", "timeout": 60, "until": "Shop", "cases": [{"text": "Sign Players", "at": [667, 571]}]}
        u6 = Popup([sign, home])
        v6 = stepexec.exec_step(u6, atc, {})
        ok(v6[0] is True and u6.taps == [(667, 571)] and "bấm tại (667, 571)" in v6[1], "trường hợp «bấm tại toạ độ»: thấy chữ của hộp thoại → bấm đúng toạ độ đó, kiểm hộp thoại đã đóng", (v6, u6.taps))

        class GoneAt(Popup):                         # hộp thoại tự đóng trong lúc con trỏ đang đi tới toạ độ
            def tap_at(self, x, y, click=True, verify=None):
                self.cur = home
                return super().tap_at(x, y, click, verify)
        u7 = GoneAt([sign, home])
        v7 = stepexec.exec_step(u7, dict(atc, until=""), {})
        ok(u7.taps == [] and u7.sent == [], "hộp thoại đã đóng ngay trước cú bấm → KHÔNG bấm vào toạ độ đó (không bấm mù)", (v7, u7.taps))
        u8 = Popup([home])
        v8 = stepexec.exec_step(u8, dict(atc, timeout=0, until=""), {})
        ok(v8[0] is True and u8.taps == [], "không thấy chữ của hộp thoại → không bấm toạ độ", v8)
        for bad in ([667], ["x", 1], [-1, 5], "667,571"):
            try:
                stepexec.exec_step(Popup([sign]), dict(atc, cases=[{"text": "Sign Players", "at": bad}]), {}); raised = False
            except stepexec.ConfigError:
                raised = True
            ok(raised, "toạ độ sai dạng (%r) → báo lỗi cấu hình" % (bad,))
        ok(stepexec.describe(atc) == "Nếu thấy chữ «Sign Players» thì bấm tại (667, 571) (xong khi thấy «Shop»)", "mô tả trường hợp «bấm tại»", stepexec.describe(atc))
        stepexec.UNTIL_STABLE = real_stable
        # đã bấm xong, hộp thoại đóng, nhưng CHỮ của nó vẫn còn ở chỗ khác (đo thật: «konami.net» trên thanh địa chỉ của trang vừa mở)
        knet = (["\"eFootball\" muốn sử dụng", "\"konami.net\" để đăng nhập", "Hủy", "Tiếp tục"], {"Tiếp tục": (802, 500), "Hủy": (533, 501)})
        page = (["Hủy", "my.konami.net", "KONAMI ID", "Login"], {"Hủy": (71, 47), "Login": (669, 529)})
        k1g = Popup([knet, page])
        j1g = stepexec.exec_step(k1g, {"type": "tap_if", "text": "konami.net", "tap": "Tiếp tục", "timeout": 10}, {})
        ok(j1g[0] is True and k1g.taps == [(802, 500)], "đã bấm rồi, nút biến mất, chữ còn ở chỗ khác (thanh địa chỉ) → hộp thoại ĐÃ ĐÓNG, bước xong (không báo «bị chắn»)", (j1g, k1g.taps))
        k1h = Popup([page])
        j1h = stepexec.exec_step(k1h, {"type": "tap_if", "text": "konami.net", "tap": "Tiếp tục", "timeout": 0}, {})
        ok(j1h[0] is False and "không thấy chữ «Tiếp tục» để bấm" in j1h[1] and k1h.taps == [],
           "…còn CHƯA bấm lần nào mà thấy chữ không có nút → vẫn là «bị chắn» như trước (không bấm bừa)", j1h)
        real_reappear = stepexec.IF_REAPPEAR_WAIT
        stepexec.IF_REAPPEAR_WAIT = 0.2
        try:
            knetP = (knet[0], dict(knet[1], **{"\"konami.net\" để đăng nhập": (640, 300)}))
            pageP = (page[0], dict(page[1], **{"my.konami.net": (300, 20)}))
            k1i = Popup([knetP, pageP])
            j1i = stepexec.exec_step(k1i, {"type": "tap_if", "text": "konami.net", "tap": "Tiếp tục", "timeout": 10}, {})
            ok(j1i[0] is True and k1i.taps == [(802, 500)], "đo được chỗ chữ: lúc bấm ở giữa màn hình, sau đó ở thanh địa chỉ (CHỖ KHÁC) → hộp thoại đã đóng", (j1i, k1i.taps))
            nobtn = (gc[0], {"Game Center": (668, 308)})            # hộp thoại HIỆN LẠI (chữ ở đúng chỗ cũ) mà nút «Hủy» chưa thấy
            k1j = Popup([gc, nobtn])
            j1j = stepexec.exec_step(k1j, {"type": "tap_if", "text": "Game Center", "tap": "Hủy", "timeout": 0}, {})
            ok(j1j[0] is False and "không thấy chữ «Hủy» để bấm" in j1j[1] and k1j.taps == [(73, 33)],
               "đã bấm, hộp thoại hiện lại ĐÚNG CHỖ cũ mà không có nút (chờ thêm vẫn không có) → «bị chắn», KHÔNG báo ✓", (j1j, k1j.taps))
            k1k = Popup([gc, nobtn, gc, gc, title])
            j1k = stepexec.exec_step(k1k, {"type": "tap_if", "text": "Game Center", "tap": "Hủy", "timeout": 0}, {})
            ok(j1k[0] is True and k1k.taps == [(73, 33), (73, 33)], "…nút hiện muộn trong lúc chờ thêm → bấm lại, hộp thoại đóng → xong", (j1k, k1k.taps))
            k1l = Popup([gc, title, nobtn])
            j1l = stepexec.exec_step(k1l, {"type": "tap_if", "text": "Game Center", "tap": "Hủy", "timeout": 0, "until": "FOOTBALL"}, {})
            gcU = (gc[0], {"Hủy": (73, 33)})                        # không đo được chỗ chữ → «đã mất rồi hiện lại» = hiện lại
            k1m = Popup([gcU, title, (gc[0], {}), (gc[0], {})])
            j1m = stepexec.exec_step(k1m, {"type": "tap_if", "timeout": 1, "cases": [{"text": "Game Center", "tap": "Hủy"}, {"text": "Login Bonus", "tap": "Continue"}]}, {})
            ok(j1m[0] is False and "không thấy chữ «Hủy» để bấm" in j1m[1], "không đo được chỗ chữ: chữ đã MẤT rồi HIỆN LẠI không có nút → «bị chắn»", (j1m, k1m.taps))
            ok(j1l[0] is True, "hộp thoại đã đóng (màn hình sạch) thì bước xong như trước", j1l)
        finally:
            stepexec.IF_REAPPEAR_WAIT = real_reappear
        k1d = Popup([sp, sp, title])
        j1d = stepexec.exec_step(k1d, {"type": "tap_if", "text": "lưu mật khẩu này", "key": "esc", "timeout": 0}, {})
        ok(j1d[0] is True and k1d.sent == ["key esc"], "trường hợp «nhấn phím» mà hộp thoại đóng chậm → chỉ nhấn phím MỘT lần (phím esc thứ hai sẽ rơi vào màn hình bên dưới)", (j1d, k1d.sent))
        k2 = Popup([gc])
        j2 = stepexec.exec_step(k2, ti, {})
        ok(j2[0] is False and j2[2] is True and len(k2.taps) == stepexec.IF_REPEAT and "đã bấm «Hủy» %d lần mà vẫn còn thấy «Game Center»" % stepexec.IF_REPEAT in j2[1],
           "bước MỘT trường hợp: bấm %d lần mà hộp thoại vẫn còn → HỎNG (trước đây báo ✓ ngay sau lần bấm đầu)" % stepexec.IF_REPEAT, (j2, k2.taps))
        ke = {"type": "tap_if", "text": "lưu mật khẩu này", "key": "esc", "timeout": 0}
        k3 = Popup([sp, title])
        j3 = stepexec.exec_step(k3, ke, {})
        ok(j3 == (True, "thấy «lưu mật khẩu này» → đã nhấn phím esc", True) and k3.sent == ["key esc"] and k3.taps == [], "trường hợp «nhấn phím»: thấy chữ → nhấn đúng phím đó (không bấm vào đâu), kiểm lại đã đóng", (j3, k3.sent))
        k4 = Popup([title])
        j4 = stepexec.exec_step(k4, ke, {})
        ok(j4 == (True, "không thấy «lưu mật khẩu này» — bỏ qua", False) and k4.sent == [], "…không thấy hộp thoại → KHÔNG nhấn phím nào (phím esc lúc không có hộp thoại có thể đóng nhầm thứ khác)", (j4, k4.sent))
        k5 = Popup([sp])
        j5 = stepexec.exec_step(k5, ke, {})
        ok(j5[0] is False and k5.sent == ["key esc"] * stepexec.IF_REPEAT and "đã nhấn phím esc %d lần mà vẫn còn thấy" % stepexec.IF_REPEAT in j5[1], "…nhấn đủ số lần mà hộp thoại vẫn còn → hỏng", (j5, k5.sent))
        mixed = {"type": "tap_if", "timeout": 0, "cases": [{"text": "lưu mật khẩu này", "key": "esc"}, {"text": "Game Center", "tap": "Hủy"}]}
        k6 = Popup([sp, gc, title])
        j6 = stepexec.exec_step(k6, mixed, {})
        ok(j6[0] is True and k6.sent == ["key esc", "click"] and k6.taps == [(73, 33)] and "nhấn phím esc (thấy «lưu mật khẩu này»)" in j6[1] and "bấm «Hủy» (thấy «Game Center»)" in j6[1],
           "một bước lẫn cả hai kiểu: hộp thoại nào nhấn phím thì nhấn phím, hộp thoại nào bấm chữ thì bấm chữ", (j6, k6.sent, k6.taps))
        for badk in ("f13", "ctrl a", "esc\nclick"):
            try:
                stepexec.exec_step(Popup([sp]), dict(ke, key=badk), {}); raised = False
            except stepexec.ConfigError:
                raised = True
            ok(raised, "phím lạ ở trường hợp «nhấn phím» (%r) → báo lỗi cấu hình, không gửi gì xuống board" % badk)
        ok(stepexec.describe(ke) == "Nếu thấy chữ «lưu mật khẩu này» thì nhấn phím esc" and stepexec.describe(mixed) == "Nếu thấy chữ «lưu mật khẩu này» thì nhấn phím esc; Nếu thấy chữ «Game Center» thì bấm «Hủy»",
           "mô tả bước có trường hợp «nhấn phím»", stepexec.describe(mixed))
        # một bước xử lý tối đa IF_MAX_TAPS hộp thoại: quá số đó thì dừng với đúng lý do (không phải «bấm rồi vẫn còn»)
        chain = [([("Hop thoai %d" % i), "Dong %d" % i], {"Dong %d" % i: (100 + i, 200)}) for i in range(stepexec.IF_MAX_TAPS + 1)]
        many = {"type": "tap_if", "timeout": 0, "cases": [{"text": "Hop thoai %d" % i, "tap": "Dong %d" % i} for i in range(stepexec.IF_MAX_TAPS + 1)]}
        k7 = Popup(chain + [title])
        j7 = stepexec.exec_step(k7, many, {})
        ok(j7[0] is False and len(k7.taps) == stepexec.IF_MAX_TAPS and "đã xử lý %d hộp thoại liên tiếp" % stepexec.IF_MAX_TAPS in j7[1] and "Hop thoai %d" % stepexec.IF_MAX_TAPS in j7[1],
           "hộp thoại hiện nối nhau quá %d cái trong một bước → dừng, nói đúng lý do" % stepexec.IF_MAX_TAPS, (j7, len(k7.taps)))

        print("\n== 30b. «Gõ chữ» từng ký tự; «Mở app» tắt hẳn rồi mở mới ==")
        t1, t2, t3 = Popup([title]), Popup([title]), Popup([title])
        g1_ = stepexec.exec_step(t1, {"type": "type", "text": "{{otp}}", "gap": 0.4}, {"otp": "135790"})
        g2_ = stepexec.exec_step(t2, {"type": "type", "text": "{{otp}}"}, {"otp": "135790"})
        g3_ = stepexec.exec_step(t3, {"type": "type", "text": "a b", "gap": 5}, {})
        ok(g1_ == (True, "", True) and t1.sent == ["type 1", "type 3", "type 5", "type 7", "type 9", "type 0"] and t2.sent == ["type 135790"] and t3.sent == ["type a", "key space", "type b"],
           "có ghi quãng nghỉ → gõ TỪNG ký tự (ô mã mỗi số một ô không bị rơi phím); không ghi → gõ liền một mạch như trước; dấu cách đi bằng phím space", (t1.sent, t2.sent, t3.sent))
        for badg in ("nhanh", [1]):
            try:
                stepexec.exec_step(Popup([title]), {"type": "type", "text": "x", "gap": badg}, {}); raised = False
            except stepexec.ConfigError:
                raised = True
            ok(raised, "quãng nghỉ giữa các ký tự không phải số (%r) → báo lỗi cấu hình" % (badg,))

        class Stop(Popup):                           # board ngừng trả lời giữa chừng lúc đang gõ từng ký tự
            def send(self, cmd, wait=0.5):
                self.sent.append(cmd)
                return "OK" if len(self.sent) < 3 else ""
        t4 = Stop([title])
        g4_ = stepexec.exec_step(t4, {"type": "type", "text": "123456", "gap": 0.4}, {})
        ok(g4_[0] is False and g4_[2] is True and len(t4.sent) == 3, "đang gõ từng ký tự mà board không trả lời → DỪNG ngay (không gõ tiếp các ký tự sau), báo là đã có gõ dở", (g4_, t4.sent))

        import iosapp

        class Usb(Popup):
            def __init__(self, shots, fail=None):
                super().__init__(shots); self.opened, self.fail = [], fail

            def relaunch(self, name):
                if self.fail:
                    raise self.fail if isinstance(self.fail, Exception) else RuntimeError(self.fail)
                self.opened.append(name); return "jp.vi.du"
        fr = {"type": "launch", "app": "efootball", "fresh": True}
        u1, u2, u3 = Usb([title]), Usb([title], fail=iosapp.AppNotFound("máy không có app nào tên «efootball»")), Usb([title])
        f1_ = stepexec.exec_step(u1, fr, {})
        f2_ = stepexec.exec_step(u2, fr, {})
        f3_ = stepexec.exec_step(u3, {"type": "launch", "app": "efootball"}, {})
        ok(f1_ == (True, "đã tắt hẳn rồi mở mới", True) and u1.opened == ["efootball"] and u1.sent == [], "«tắt hẳn rồi mở mới»: đi qua USB, KHÔNG gõ phím nào", (f1_, u1.opened, u1.sent))
        ok(f2_[0] is False and f2_[2] is False and "không tắt hẳn / mở mới được app «efootball»: máy không có app nào tên" in f2_[1] and u2.sent == [],
           "…không làm được → bước HỎNG kèm lý do, KHÔNG lặng lẽ quay về cách mở cũ (app sẽ ở màn hình dở dang)", f2_)
        ok(f3_[0] is True and u3.opened == [] and any(c.startswith("type efootball") for c in u3.sent) and "combo gui space" in u3.sent, "không chọn «mở mới» → vẫn mở bằng ô tìm kiếm như trước", u3.sent)
        u5, u6, u7 = Usb([title], fail="hết giờ"), Usb([title]), Usb([title])
        f5_ = stepexec.exec_step(u5, fr, {})
        f6_ = stepexec.exec_step(u6, {"type": "launch", "app": "Cài đặt", "fresh": True}, {})
        f7_ = stepexec.exec_step(u7, {"type": "launch", "app": "efootball", "fresh": "false"}, {})
        ok(f5_[0] is False and f5_[2] is True and "hết giờ" in f5_[1], "mở mới hỏng GIỮA CHỪNG (hết giờ, rút cáp…) → app có thể đã bị tắt → báo là «đã đụng vào máy»; chỉ «không chọn được app» mới chắc chắn chưa đụng", f5_)
        ok(f6_[0] is True and u6.opened == ["Cài đặt"] and u6.sent == [], "mở mới không gõ phím nên tên app CÓ DẤU vẫn dùng được", (f6_, u6.opened))
        ok(f7_[0] is True and u7.opened == [] and "combo gui space" in u7.sent, "cờ «mở mới» ghi sai kiểu (chuỗi \"false\") không bị hiểu thành bật", u7.sent)
        ok(stepexec.describe(fr) == "Mở app efootball (tắt hẳn rồi mở mới)" and [x["type"] for x in jobflow.open_prefix([fr, ti, {"type": "tap_text", "text": "x"}])] == ["launch", "tap_if"],
           "mô tả nói rõ kiểu mở; bước mở mới vẫn thuộc «đoạn mở game»")
        u4, t5 = Usb([title]), Popup([title])
        ok16, msg16 = engine.run_step(u4, fr)
        ok17, msg17 = engine.run_step(t5, {"type": "type", "text": "12", "gap": 0.3})
        ok(ok16 is True and u4.opened == ["efootball"] and "tắt hẳn rồi mở mới" in msg16 and ok17 is True and t5.sent == ["type 1", "type 2"], "kịch bản thường / «thử một bước» dùng chung cách làm cho hai kiểu mới", (msg16, msg17))

        import iosapp
        apps = {"jp.konami.pesactionmobile": {"CFBundleDisplayName": "eFootball™", "CFBundleName": "PESmobile"},
                "com.apple.Preferences": {"CFBundleDisplayName": "Cài đặt", "CFBundleName": "Settings"},
                "com.vidu.hub": {"CFBundleDisplayName": "eFootball Hub"}, "com.vidu.fm": {"CFBundleName": "Football Manager"}, "com.vidu.rong": None,
                # app ẨN của hệ thống trùng tên với app thường (đo trên iPhone 8: ba app cùng tên «Cài đặt», hai cái ẩn)
                "com.apple.MBHelperApp": {"CFBundleDisplayName": "Cài đặt", "SBAppTags": ["hidden"]}, "com.apple.CarPlaySettings": {"CFBundleDisplayName": "Cài đặt", "SBAppTags": ["hidden"]}}

        def pick(name):
            try:
                return iosapp.pick_bundle(apps, name)
            except LookupError as e:
                return "LỖI: %s" % e
        ok(pick("efootball") == "jp.konami.pesactionmobile" and pick("eFootball™") == "jp.konami.pesactionmobile" and pick("PESmobile") == "jp.konami.pesactionmobile"
           and pick("jp.konami.pesactionmobile") == "jp.konami.pesactionmobile",
           "mở mới theo tên: tên hiển thị ĐÚNG BẰNG tên gõ thắng app chỉ «có chứa» («eFootball™» chứ không phải «eFootball Hub»); nhận cả tên gói và bundle id")
        ok(pick("Settings") == "com.apple.Preferences" and pick("cai dat") == "com.apple.Preferences" and pick("hub") == "com.vidu.hub", "không phân biệt dấu / hoa thường / khoảng trắng; một app duy nhất «có chứa» thì nhận")
        ok(pick("football").startswith("LỖI: có 3 app cùng khớp") and "eFootball Hub" in pick("football") and pick("khong co app nay").startswith("LỖI: máy không có app nào tên")
           and pick("").startswith("LỖI: chưa ghi tên app") and pick("™").startswith("LỖI: chưa ghi tên app"),
           "nhiều app cùng khớp / không có app nào / tên rỗng → báo rõ, KHÔNG đoán (tắt nhầm app còn tệ hơn không tắt)", (pick("football"), pick("khong co app nay")))
        ok(pick("Cai dat") == "com.apple.Preferences" and pick("com.apple.CarPlaySettings") == "com.apple.CarPlaySettings" and pick("CarPlaySettings").startswith("LỖI: máy không có app nào"),
           "app ẨN của hệ thống trùng tên («Cài đặt» có ba cái) không làm tên bị «nhiều app cùng khớp»; app ẩn chỉ chọn được bằng đúng bundle id")
        ok(iosapp.norm("eFootball™ 2027") == "efootball2027" and iosapp.norm("Cài đặt") == "caidat" and iosapp.norm(None) == "", "chuẩn hoá tên app: bỏ dấu, ký hiệu, khoảng trắng")

        print("\n== 31. «Bấm / giữ vào chữ» chờ chữ hiện ra (màn hình game chuyển cảnh chậm) ==")
        # đo thật trên eFootball: bấm biểu tượng menu ở màn tiêu đề → danh sách có «Data Transfer»; bấm nó → màn «Data Transfer» với hai dòng «Transfer data linked to …»
        menu = (["Legal and Privacy", "General Contact", "Data Transfer", "Graphics"], {"Data Transfer": (951, 378)})
        tt = {"type": "tap_text", "text": "Data Transfer"}
        w1 = Popup([title, title, menu])
        s1 = stepexec.exec_step(w1, tt, {})
        ok(s1 == (False, "không thấy chữ «Data Transfer» trên màn hình", False) and w1.n == 1 and w1.taps == [],
           "không ghi thời gian chờ → nhìn đúng MỘT lần như trước giờ (bước đã có không tự đổi hành vi)", (s1, w1.n))
        w2 = Popup([title, title, menu])
        s2 = stepexec.exec_step(w2, dict(tt, timeout=5), {})
        ok(s2[0] is True and s2[2] is True and w2.taps == [(951, 378)] and w2.sent == ["click"], "có ghi thời gian chờ: chữ hiện CHẬM (lần nhìn thứ 3) → vẫn thấy rồi bấm, đúng một lần", (s2, w2.taps, w2.n))
        sliding = (["Data Transfer"], {"Data Transfer": (951, 640)})          # danh sách đang trượt vào: chữ đã đọc được nhưng chưa nằm đúng chỗ
        w3 = Popup([title, sliding, menu])
        s3 = stepexec.exec_step(w3, dict(tt, timeout=5), {})
        ok(s3[0] is True and w3.taps == [(951, 378)], "thấy chữ ở lần nhìn LẠI (màn hình có thể còn đang trượt) → chờ đứng yên rồi lấy lại vị trí, bấm vào chỗ đã đứng yên", (s3, w3.taps))
        w4 = Popup([menu])
        s4 = stepexec.exec_step(w4, dict(tt, timeout=5), {})
        ok(s4[0] is True and w4.taps == [(951, 378)] and w4.n == 1, "chữ có sẵn ngay lần nhìn đầu → bấm luôn, không tốn thêm lần nhìn nào", (s4, w4.n))
        w5 = Popup([title])
        t0 = time.time()
        s5 = stepexec.exec_step(w5, dict(tt, timeout=0.3), {})
        ok(s5 == (False, "chờ 0.3s không thấy chữ «Data Transfer» trên màn hình", False) and w5.taps == [] and w5.sent == [] and w5.n > 1 and 0.25 <= time.time() - t0 < 3,
           "hết thời gian chờ vẫn không thấy → báo hỏng kèm số giây đã chờ, không bấm gì", (s5, w5.n))
        w6 = Popup([title, menu, title])               # chữ loé lên rồi mất (màn hình lướt qua) → không bấm vào chỗ đã mất
        s6 = stepexec.exec_step(w6, dict(tt, timeout=0.2), {})
        ok(s6[0] is False and w6.taps == [] and w6.sent == [], "chữ vừa thấy đã mất khi màn hình đứng yên → không bấm", (s6, w6.taps))
        for bad in ("abc", [5]):
            try:
                stepexec.exec_step(Popup([menu]), dict(tt, timeout=bad), {}); raised = False
            except stepexec.ConfigError:
                raised = True
            ok(raised, "thời gian chờ chữ không phải số (%r) → báo lỗi cấu hình, không bấm" % (bad,))
        w7 = Popup([menu])
        stepexec.exec_step(w7, dict(tt, timeout=10 ** 6), {})
        ok(stepexec._text_wait({"timeout": 10 ** 6}, "x") == stepexec.TEXT_WAIT_MAX and stepexec._text_wait({}, "x") == 0 and stepexec._text_wait({"timeout": -4}, "x") == 0 and w7.taps == [(951, 378)],
           "thời gian chờ bị chặn trong khoảng 0 … %d giây" % stepexec.TEXT_WAIT_MAX)

        class Holder(Popup):
            def __init__(self, shots):
                super().__init__(shots); self.holds = []

            def hold_at(self, x, y, sec, verify=None):
                if verify is not None and not verify(self.cur):
                    return False
                self.holds.append((x, y, sec)); return True
        ht = {"type": "hold_text", "text": "Data Transfer", "seconds": 1.2}
        h1 = Holder([title, sliding, menu])
        g1 = stepexec.exec_step(h1, dict(ht, timeout=5), {})
        h2 = Holder([title, menu])
        g2 = stepexec.exec_step(h2, ht, {})
        ok(g1[0] is True and h1.holds == [(951, 378, 1.2)] and g2 == (False, "không thấy chữ «Data Transfer» trên màn hình", False) and h2.holds == [] and h2.n == 1,
           "«bấm giữ vào chữ» cũng vậy: có ghi thời gian chờ thì chờ chữ hiện ra (giữ ở chỗ đã đứng yên); không ghi thì nhìn một lần", (g1, h1.holds, g2))

        # kịch bản thường / «thử một bước»: cùng MỘT bộ chạy với lúc nhận đơn — có ghi thời gian chờ thì chờ, không ghi thì nhìn một lần
        e1 = Popup([title, menu])
        ok9, msg9 = engine.run_step(e1, dict(tt, timeout=5))
        e2 = Popup([title])
        ok10, msg10 = engine.run_step(e2, dict(tt, timeout=0.2))

        class Old(Popup):
            def tap_text(self, needle, verbose=False):
                self.old = needle; return True
        e3 = Old([menu])
        ok11, msg11 = engine.run_step(e3, tt)
        e3b = Old([title, menu])
        ok11b, msg11b = engine.run_step(e3b, tt)
        e4 = Holder([title, menu])
        ok12, msg12 = engine.run_step(e4, dict(ht, timeout=5))
        ok(ok9 is True and e1.taps == [(951, 378)] and msg9 == "Tap chữ «Data Transfer»" and ok10 is False and "chờ 0.2s không thấy chữ «Data Transfer»" in msg10 and e2.taps == []
           and ok11 is True and e3.taps == [(951, 378)] and msg11 == "Tap chữ «Data Transfer»" and not hasattr(e3, "old")
           and ok11b is False and e3b.taps == [] and e3b.n == 1 and "không thấy chữ «Data Transfer»" in msg11b and not hasattr(e3b, "old")
           and ok12 is True and e4.holds == [(951, 378, 1.2)],
           "bộ chạy kịch bản thường = bộ chạy lúc nhận đơn: có ghi thời gian chờ thì chờ rồi bấm / giữ (báo rõ đã chờ bao lâu); không ghi thì nhìn MỘT lần rồi bấm có kiểm lại — không còn đường riêng nav.tap_text",
           (ok9, msg9, ok10, msg10, ok11, msg11, ok11b, msg11b, ok12, msg12))

        print("\n== 32. «Bấm vào vùng ảnh» (nút không có chữ: tìm đúng HÌNH rồi bấm, thay cho toạ độ cố định) ==")
        import base64
        import cv2
        import eyes as eyes_mod
        MENU = (1257, 682)                             # chỗ nút menu ở màn tiêu đề eFootball (iPhone 8 xoay ngang, ảnh 1334×750)

        def scene(btn=MENU, extra=None, dim=1.0, gray=False, blur=0):
            rng = np.random.RandomState(7)             # nền nhiều mảng màu, giống nhau ở mọi lần dựng
            im = np.full((750, 1334, 3), (90, 40, 120), np.uint8)
            for _ in range(70):
                cv2.circle(im, (int(rng.randint(0, 1334)), int(rng.randint(0, 750))), int(rng.randint(15, 70)), tuple(int(v) for v in rng.randint(30, 255, 3)), -1)
            for at in (btn, extra):
                if at:                                 # nút tròn có ba gạch
                    cv2.circle(im, at, 34, (250, 250, 250), 4)
                    for k in (-12, 0, 12):
                        cv2.line(im, (at[0] - 14, at[1] + k), (at[0] + 16, at[1] + k), (250, 250, 250), 4)
            if blur:
                im = cv2.GaussianBlur(im, (blur, blur), 0)
            if dim != 1.0:
                im = cv2.convertScaleAbs(im, alpha=dim, beta=0)
            if gray:
                im = cv2.cvtColor(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
            return im

        def b64png(im):
            return base64.b64encode(cv2.imencode(".png", im)[1].tobytes()).decode()

        class Pic:                                     # máy giả cho bước tìm hình: ảnh chụp theo từng lần nhìn, tìm hình bằng CHÍNH hàm của app
            def __init__(self, shots):
                self.shots, self.n, self.taps, self.cur, self.sent = list(shots), 0, [], None, []
                self.e, self.h = self, self

            def screenshot(self):
                self.cur = self.shots[min(self.n, len(self.shots) - 1)]; self.n += 1
                return self.cur

            def find_image(self, tmpl, img=None, min_score=0.9, near=None):
                return eyes_mod.locate_image(self.cur if img is None else img, tmpl, min_score, near)

            def tap_at(self, x, y, click=True, verify=None):
                if verify is not None and not verify(self.cur):
                    return False
                self.taps.append((x, y))
                return True

            def send(self, cmd, wait=0.5):
                self.sent.append(cmd)
                return "OK"
        title_scr = scene()
        crop = title_scr[MENU[1] - 45:MENU[1] + 45, MENU[0] - 45:MENU[0] + 45]
        ti_ = {"type": "tap_image", "image": b64png(crop), "x": MENU[0] - 45, "y": MENU[1] - 45, "w": 90, "h": 90}
        p1 = Pic([title_scr])
        i1 = stepexec.exec_step(p1, ti_, {})
        ok(i1 == (True, "", True) and p1.taps == [MENU] and p1.sent == ["home", "click"] and p1.n == 1,
           "thấy đúng hình → bấm vào GIỮA hình, đúng một lần (trước khi tìm, con trỏ được cất về góc để không che hình)", (i1, p1.taps, p1.sent))
        p2 = Pic([scene(btn=(1000, 300))])
        i2 = stepexec.exec_step(p2, ti_, {})
        ok(i2[0] is True and p2.taps == [(1000, 300)], "nút nằm ở chỗ KHÁC với lúc cắt hình → vẫn tìm ra và bấm đúng chỗ mới (không bấm theo toạ độ cũ)", (i2, p2.taps))
        p3 = Pic([scene(btn=None)])
        i3 = stepexec.exec_step(p3, ti_, {})
        ok(i3[0] is False and i3[2] is False and p3.taps == [] and p3.sent == ["home"] and p3.n == 1 and i3[1].startswith("không thấy vùng ảnh cần bấm trên màn hình (chỗ giống nhất ") and "cần 90%" in i3[1],
           "màn hình KHÔNG có hình đó → không bấm gì, báo rõ chỗ giống nhất được bao nhiêu %", i3)
        p4 = Pic([scene(btn=None), scene(btn=None), title_scr])
        i4 = stepexec.exec_step(p4, dict(ti_, timeout=5), {})
        ok(i4[0] is True and p4.taps == [MENU] and p4.n == 4, "hình hiện CHẬM (game đang tải) + có ghi thời gian chờ → nhìn lại tới khi thấy, chờ đứng yên rồi bấm", (i4, p4.n))
        p5 = Pic([scene(btn=None)])
        i5 = stepexec.exec_step(p5, dict(ti_, timeout=0.3), {})
        ok(i5[0] is False and i5[1].startswith("chờ 0.3s không thấy vùng ảnh") and p5.taps == [] and p5.n > 1, "hết thời gian chờ vẫn không có → hỏng, kèm số giây đã chờ", i5)
        for label, shot in (("màn hình bị PHỦ MỜ (hộp thoại che lên)", scene(dim=0.6)), ("hình cùng dạng nhưng MẤT MÀU (nút xám «chưa bấm được»)", scene(gray=True)),
                            ("màn hình khác cỡ, nhỏ hơn cả hình mẫu", title_scr[:60, :60])):
            pz = Pic([shot])
            iz = stepexec.exec_step(pz, ti_, {})
            ok(iz[0] is False and pz.taps == [] and "click" not in pz.sent, "%s → không coi là «giống», không bấm" % label, iz)
        two = title_scr.copy()                         # HAI chỗ giống hệt nhau: chép nguyên vùng nút sang một chỗ khác
        two[200 - 45:200 + 45, 300 - 45:300 + 45] = crop
        p6 = Pic([two]); stepexec.exec_step(p6, ti_, {})
        p7 = Pic([two]); stepexec.exec_step(p7, dict(ti_, x=300 - 45, y=200 - 45), {})
        ok(p6.taps == [MENU] and p7.taps == [(300, 200)], "hai chỗ giống hệt nhau → bấm chỗ GẦN nơi hình được cắt ra nhất", (p6.taps, p7.taps))
        soft = scene(blur=7)                           # hình hơi nhoè (nền sau nút đổi nhẹ)
        s_soft = eyes_mod.locate_image(soft, crop, 0.5)[1]
        p8, p9, p10 = Pic([soft]), Pic([soft]), Pic([soft])
        i8 = stepexec.exec_step(p8, dict(ti_, min=0.99), {})
        i9 = stepexec.exec_step(p9, dict(ti_, min=round(s_soft - 0.03, 3)), {})
        i10 = stepexec.exec_step(p10, dict(ti_, min=int(round((s_soft - 0.03) * 100))), {})
        ok(0.6 < s_soft < 0.97 and i8[0] is False and p8.taps == [] and i9[0] is True and p9.taps == [MENU] and i10[0] is True,
           "«độ giống tối thiểu»: đòi 99%% thì hình hơi nhoè (%.0f%%) không đạt; hạ ngưỡng thì bấm; ghi theo phần trăm (vd 90) cũng nhận" % (s_soft * 100), (s_soft, i8, i9, i10))

        class Gone(Pic):                               # hình biến mất trong lúc con trỏ đang đi tới
            def tap_at(self, x, y, click=True, verify=None):
                self.cur = scene(btn=None)
                return super().tap_at(x, y, click, verify)
        p11 = Gone([title_scr])
        i11 = stepexec.exec_step(p11, ti_, {})
        ok(i11[0] is False and p11.taps == [] and "click" not in p11.sent, "hình biến mất trước khi con trỏ tới nơi → KHÔNG bấm vào chỗ cũ", i11)
        # NHIỀU chỗ giống hệt nhau (dãy nút mua không chữ): phải xét HẾT rồi mới chọn chỗ gần nơi cắt hình — trước đây chỉ xét 4 chỗ đầu
        row = title_scr.copy()
        spots = [(120 + 160 * i, 150) for i in range(7)]
        for cx, cy in spots:
            row[cy - 45:cy + 45, cx - 45:cx + 45] = crop
        hit_ = []
        for cx, cy in spots:
            pr = Pic([row]); stepexec.exec_step(pr, dict(ti_, x=cx - 45, y=cy - 45), {})
            hit_.append(pr.taps)
        ok(hit_ == [[s_] for s_ in spots], "7 nút giống hệt nhau xếp hàng (+ nút gốc): khoanh nút nào thì bấm ĐÚNG nút đó, kể cả nút thứ 5, 6, 7", hit_)
        hit2_ = []
        for cx, cy in spots:                           # nút đã xê dịch chút ít so với lúc cắt (chỗ cắt không còn trùng khít bản sao nào)
            pr = Pic([row]); stepexec.exec_step(pr, dict(ti_, x=cx - 45 + 30, y=cy - 45 + 20), {})
            hit2_.append(pr.taps)
        ok(hit2_ == [[s_] for s_ in spots], "…nút xê dịch chút ít so với lúc cắt → vẫn chọn đúng bản sao GẦN nhất trong cả 8 chỗ giống nhau", hit2_)
        # ảnh mẫu TRÙM nhiều chu kỳ của một nội dung lặp (khoanh trùm 2,4 hàng giống hệt nhau): hình còn đúng chỗ cũ thì phải ra đúng chỗ đó
        stripes = np.full((750, 1334, 3), (60, 60, 60), np.uint8)
        for r_ in range(10):
            y_ = 100 + 50 * r_
            cv2.rectangle(stripes, (200, y_ + 6), (900, y_ + 40), (200, 120, 40), -1)
            cv2.circle(stripes, (260, y_ + 23), 12, (250, 250, 250), -1)
            cv2.putText(stripes, "Mua", (300, y_ + 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        wrong = []
        for r_ in (1, 3, 6):
            y_ = 100 + 50 * r_
            tm = stripes[y_:y_ + 120, 220:420].copy()
            got = eyes_mod.locate_image(stripes, tm, 0.9, (320, y_ + 60))[0]
            if got != (320, y_ + 60):
                wrong.append((r_, got))
        ok(wrong == [], "ảnh mẫu trùm 2,4 hàng giống hệt nhau: hình còn nằm ĐÚNG chỗ được cắt → trả đúng chỗ đó (trước đây lệch một hàng ở 2/3 vị trí)", wrong)
        small = crop[30:60, 30:60]
        wall = np.full((750, 1334, 3), (90, 40, 120), np.uint8)
        for gy in range(8):
            for gx in range(9):
                wall[40 + gy * 80:70 + gy * 80, 40 + gx * 120:70 + gx * 120] = small
        pw_, pw2_ = Pic([wall]), Pic([wall])
        iw_ = stepexec.exec_step(pw_, {"type": "tap_image", "image": b64png(small), "x": 445, "y": 395, "w": 30, "h": 30}, {})      # chỗ cắt nằm GIỮA các bản sao
        iw2_ = stepexec.exec_step(pw2_, {"type": "tap_image", "image": b64png(small), "x": 400, "y": 360, "w": 30, "h": 30}, {})    # chỗ cắt vẫn còn đúng hình đó
        ok(iw_[0] is False and pw_.taps == [] and "quá nhiều chỗ giống hệt" in iw_[1] and eyes_mod.locate_image(wall, small, 0.9, (460, 410)) == (None, eyes_mod.IMAGE_TOO_MANY)
           and eyes_mod.locate_image(wall, small, 0.9)[0] is None,
           "hình lặp lại quá nhiều chỗ (72 chỗ, quá %d) mà chỗ cắt không còn hình đó → không phân xử được → KHÔNG bấm, báo đúng lý do" % eyes_mod.IMAGE_PEAKS_MAX, iw_)
        ok(iw2_[0] is True and pw2_.taps == [(415, 375)], "…còn nếu hình vẫn nằm ĐÚNG chỗ được cắt thì bấm chỗ đó (không cần phân xử)", (iw2_, pw2_.taps))
        flat = np.full((40, 40, 3), 77, np.uint8)
        red = np.zeros((40, 40, 3), np.uint8); red[:, :, 2] = 255
        bads = {"ảnh một màu ĐẬM (đỏ thuần)": dict(ti_, image=b64png(red)), "thiếu ảnh": {"type": "tap_image"}, "ảnh không phải base64": dict(ti_, image="không phải ảnh"), "base64 nhưng không phải ảnh": dict(ti_, image=base64.b64encode(b"abc").decode()),
                "ảnh một màu": dict(ti_, image=b64png(flat)), "ảnh quá nhỏ": dict(ti_, image=b64png(crop[:5, :5])), "ảnh quá lớn": dict(ti_, image=b64png(title_scr[:700, :700])),
                "độ giống không phải số": dict(ti_, min="cao"), "thời gian chờ không phải số": dict(ti_, timeout="lâu")}
        for why, bad in bads.items():
            pb = Pic([title_scr])
            try:
                stepexec.exec_step(pb, bad, {}); raised = False
            except stepexec.ConfigError:
                raised = True
            ok(raised and pb.taps == [], "bước cấu hình sai (%s) → báo lỗi cấu hình, không bấm" % why)
        pic_, need_, near_ = stepexec.step_image(dict(ti_, image="data:image/png;base64," + ti_["image"], min=5))
        ok(pic_.shape == (90, 90, 3) and need_ == 0.5 and near_ == MENU and stepexec.step_image({"image": ti_["image"]})[1:] == (stepexec.IMAGE_MIN, None)
           and stepexec.step_image(dict(ti_, min=100))[1] == 0.99 and stepexec.step_image(dict(ti_, min=-3))[1] == stepexec.IMAGE_MIN
           and stepexec.step_image(dict(ti_, min=float("nan")))[1] == stepexec.IMAGE_MIN and stepexec.describe(dict(ti_, w="<b>", h=None)) == "Bấm vào vùng ảnh"
           and stepexec.describe(dict(ti_, w=float("inf"))) == "Bấm vào vùng ảnh" and stepexec.step_image(dict(ti_, x=float("inf")))[2] is None,
           "đọc bước: nhận cả ảnh có tiền tố «data:»; độ giống bị chặn trong 50…99%; không ghi chỗ cắt thì không ưu tiên chỗ nào")
        login2 = [{"type": "launch", "app": "efootball"}, {"type": "wait_text", "text": "Konami"}, ti_, {"type": "type", "text": "{{username}}"}]
        ok("tap_image" in stepexec.INPUT_TYPES and [x["type"] for x in jobflow.open_prefix(login2)] == ["launch", "wait_text"] and stepexec.describe(ti_) == "Bấm vào vùng ảnh 90×90"
           and stepexec.describe({"type": "tap_image"}) == "Bấm vào vùng ảnh",
           "bước bấm vào vùng ảnh là bước CHẠM vào máy: đoạn mở game dừng trước nó; mô tả không chứa dữ liệu ảnh")
        p12, p13 = Pic([title_scr]), Pic([scene(btn=None)])
        ok14, msg14 = engine.run_step(p12, ti_)
        ok15, msg15 = engine.run_step(p13, ti_)
        ok(ok14 is True and p12.taps == [MENU] and msg14 == "Bấm vào vùng ảnh 90×90" and ok15 is False and p13.taps == [] and "không thấy vùng ảnh" in msg15 and "tap_image" in stepexec.STEP_TYPES,
           "kịch bản thường / «thử một bước» dùng chung cách làm", (msg14, msg15))
        ok(eyes_mod.locate_image(None, crop) == (None, 0.0) and eyes_mod.locate_image(title_scr, None) == (None, 0.0) and eyes_mod.locate_image(title_scr[:, :, 0], crop) == (None, 0.0)
           and eyes_mod.locate_image(np.dstack([title_scr, title_scr[:, :, :1]]), crop) == (None, 0.0) and eyes_mod.locate_image(title_scr.astype(np.float32), crop) == (None, 0.0),
           "thiếu ảnh / ảnh không đủ ba kênh màu / 4 kênh / không phải 8 bit → «không thấy», không ném lỗi")

        # Chữ + toạ độ đọc bằng Vision trên danh sách gói eFootball THẬT (iPhone 8 xoay ngang, 1334×750, tài khoản Apple vùng CHF), lật từ trái sang phải
        L = lambda *rows: [{"text": t, "x": x, "y": y, "w": w, "h": h} for t, x, y, w, h in rows]
        HEAD = [("Terms of Use", 434, 30, 188, 28), ("Product Details", 774, 30, 216, 28), ("Back", 123, 705, 78, 26), ("Details", 668, 705, 100, 26)]
        SHOP = [
            L(*HEAD, ("6 day(s) 0 hr(s)", 394, 116, 192, 28), ("500", 201, 407, 62, 26), ("1,500", 800, 411, 88, 34), ("Paid: 291", 180, 453, 112, 26),
              ("Paid: 937", 771, 454, 114, 30), ("Pa", 1316, 453, 32, 26), ("Free: 209", 182, 493, 116, 28), ("Free: 563", 769, 492, 114, 24),
              ("CHF 2.30", 191, 553, 134, 30), ("CHF 7.50", 780, 553, 136, 32), ("CH", 1316, 552, 32, 28), ("Remaining: 1", 201, 592, 154, 32)),
            L(*HEAD, ("4,500", 216, 412, 92, 36), ("Starter Set: Bambang Pamungkas", 881, 364, 350, 28), ("10", 776, 407, 40, 26), ("Paid: 2,666", 195, 456, 142, 32),
              ("Paid: 10", 762, 453, 96, 28), ("Free: 1,834", 192, 493, 136, 32), ("Free: 0", 754, 492, 84, 24), ("CHF 21.00", 200, 553, 152, 32),
              ("CHF 0.60", 782, 553, 140, 30), ("CH", 1316, 552, 32, 28)),
            L(*HEAD, ("Starter Set: Luis Suárez", 243, 363, 238, 22), ("Starter Set: Iker Casillas", 833, 365, 242, 22), ("50", 191, 406, 42, 28),
              ("100", 786, 407, 60, 26), ("Paid: 50", 175, 453, 102, 26), ("Paid: 100", 769, 453, 114, 26), ("Free: 0", 166, 492, 84, 24),
              ("Free: 0", 754, 492, 84, 24), ("CHF 0.60", 194, 553, 140, 32), ("CHF 1.80", 778, 553, 132, 30), ("CH", 1316, 568, 32, 28)),
            L(*HEAD, ("100", 198, 137, 60, 26), ("500", 789, 137, 62, 26), ("Paid: 97", 175, 183, 102, 28), ("Paid: 477", 771, 183, 114, 26),
              ("Free: 3", 165, 224, 82, 24), ("Free: 23", 762, 224, 96, 24), ("CHF 0.80", 194, 284, 140, 32), ("CHF 3.80", 780, 284, 136, 32),
              ("300", 201, 422, 62, 28), ("1,000", 802, 426, 92, 36), ("Paid: 291", 180, 468, 112, 30), ("Paid: 937", 770, 468, 116, 28),
              ("Free: 9", 166, 508, 84, 24), ("Free: 63", 761, 508, 98, 26), ("CHF 2.30", 191, 569, 134, 30), ("CHF 7.50", 780, 569, 136, 30)),
            L(*HEAD, ("2,000", 217, 142, 94, 36), ("5,000", 805, 141, 94, 36), ("CHF 15.00", 200, 284, 152, 32), ("CHF 34.00", 790, 284, 156, 32),
              ("3,000", 216, 426, 92, 36), ("10,000", 812, 427, 112, 38), ("CHF 21.00", 200, 569, 152, 32), ("CHF 63.00", 791, 569, 158, 30)),
            L(*HEAD, ("5,000", 217, 141, 94, 38), ("15,000", 812, 142, 108, 36), ("CHF 34.00", 202, 284, 156, 32), ("CHF 93.00", 791, 284, 158, 32),
              ("10,000", 224, 427, 112, 38), ("CHF 63.00", 203, 569, 158, 30)),
        ]

        print("\n== 33. «Bấm vào ô có chữ … và …» (danh sách gói: khớp số coin + giá trong CÙNG MỘT ô) ==")
        WH = (1334, 750)
        pc = lambda k, coin, price: stepexec.pick_card(SHOP[k], stepexec.alternatives(coin), stepexec.alternatives(price), WH)
        ok(pc(0, "500", "CHF 2.30") == (201, 407) and pc(3, "500", "CHF 3.80") == (789, 137) and pc(3, "500", "CHF 2.30") is None and pc(0, "500", "CHF 3.80") is None,
           "hai gói cùng 500 coin: chọn đúng gói theo GIÁ cùng ô (gói sale 2.30 ≠ gói thường 3.80); giá không nằm cùng ô thì không chọn")
        ok(pc(3, "300", "CHF 2.30") == (201, 422) and pc(0, "300", "CHF 2.30") is None,
           "cùng giá 2.30 có hai gói (sale 500 và thường 300): số coin quyết định; màn hình không có ô «300» thì không thấy")
        ok(pc(3, "100", "CHF 0.80") == (198, 137) and pc(2, "100", "CHF 1.80") == (786, 407) and pc(2, "100", "CHF 0.80") is None and pc(3, "100", "CHF 1.80") is None,
           "«100» không khớp vào «Paid: 100» / «1,000»; ô Starter 100 coin (1.80) ≠ ô thường 100 coin (0.80)")
        ok(pc(3, "300", "CHF 0.80") is None and pc(3, "100", "CHF 2.30") is None,
           "giá của ô HÀNG KHÁC (ngay trên / hàng dưới cùng cột) không được tính là cùng ô")
        ok(pc(0, "1,500|1500", "CHF 7.50") == (800, 411) and pc(3, "1,000|1000", "CHF 7.50") == (802, 426) and pc(3, "1,500|1500", "CHF 7.50") is None
           and pc(0, "1,000|1000", "CHF 7.50") is None,
           "cùng giá 7.50: gói 1,500 (sale) và 1,000 (thường) không lẫn; viết «1000» hay «1,000» đều khớp")
        ok(pc(1, "4,500|4500", "CHF 21.00") == (216, 412) and pc(4, "3,000|3000", "CHF 21.00") == (216, 426) and pc(4, "10,000|10000", "CHF 63.00") == (812, 427)
           and pc(5, "15,000|15000", "CHF 93.00") == (812, 142) and pc(4, "15,000", "CHF 93.00") is None,
           "các gói lớn: đúng ô, kể cả khi hai trang lật chồng lên nhau (5,000 / 10,000 nằm ở cả hai trang nhưng ở chỗ khác)")
        ok(pc(1, "10", "CHF 0.60") == (776, 407) and pc(2, "50", "CHF 0.60") == (191, 406) and pc(1, "50", "CHF 0.60") is None,
           "Starter Set 10 coin và 50 coin cùng giá 0.60: số coin quyết định; «10» không khớp vào «Paid: 10» khi có ô ghi đúng «10»")
        ok(stepexec.pick_card(SHOP[3], ["100"], [], WH) == (198, 137) and stepexec.pick_card([], ["100"], ["CHF 0.80"], WH) is None,
           "không ghi chữ đi kèm → chỉ chọn khi có ĐÚNG MỘT dòng khớp nguyên dòng; màn hình trống → không thấy")
        side = [{"text": "Mua", "x": 900, "y": 300, "w": 60, "h": 30}, {"text": "1050 Coins", "x": 600, "y": 300, "w": 160, "h": 30},
                {"text": "Mua", "x": 900, "y": 450, "w": 60, "h": 30}, {"text": "2150 Coins", "x": 600, "y": 452, "w": 160, "h": 30}]
        ok(stepexec.pick_card(side, ["Mua"], ["2150 Coins"], WH, "left") == (900, 450) and stepexec.pick_card(side, ["2150 Coins"], ["Mua"], WH, "right") == (600, 452)
           and stepexec.pick_card(side, ["Mua"], ["2150 Coins"], WH, "below") is None and stepexec.pick_card(side, ["Mua"], ["2150"], WH, "left") is None,
           "chữ đi kèm nằm BÊN TRÁI / PHẢI (danh sách dạng hàng ngang: «1050 Coins … Mua»): chọn đúng nút «Mua» của hàng có gói cần mua")

        class Shop(Popup):                         # danh sách gói lật được: mỗi lần lướt sang trái là sang trang kế (hết danh sách thì đứng yên)
            def __init__(self, start=0):
                super().__init__([title]); self.page, self.swipes = start, []

            def screenshot(self):
                self.n += 1
                self.cur = SHOP[self.page]
                return np.zeros((750, 1334, 3), np.uint8)

            def text_lines(self, img=None):
                return SHOP[self.page]

            def read_text(self, img=None, **kw):
                return "\n".join(r["text"] for r in SHOP[self.page])

            def swipe(self, x1, y1, x2, y2):
                self.swipes.append("left" if x2 < x1 else "right")
                self.page = max(0, min(len(SHOP) - 1, self.page + (1 if x2 < x1 else -1)))
                return True

            def tap_at(self, x, y, click=True, verify=None):
                if verify is not None and not verify(np.zeros((750, 1334, 3), np.uint8)):
                    return False
                self.taps.append((x, y, self.page))
                return True
        tc = {"type": "tap_text", "text": "{{package.ocr_text}}", "near": "{{package.price_text}}", "scroll": "left"}
        pv = {"package.ocr_text": "10,000|10000", "package.price_text": "CHF 63.00"}
        s1 = Shop(0)
        q1 = stepexec.exec_step(s1, tc, pv)
        ok(q1[0] is True and q1[2] is True and s1.taps == [(812, 427, 4)] and s1.swipes == ["left"] * 4 and s1.sent[-1] == "click",
           "gói chưa có trên màn hình → lướt sang trái tới trang có gói đó rồi bấm đúng ô (10,000 — CHF 63.00)", (q1, s1.taps, s1.swipes))
        s2 = Shop(5)
        q2 = stepexec.exec_step(s2, dict(tc), {"package.ocr_text": "500", "package.price_text": "CHF 2.30"})
        ok(q2[0] is True and s2.taps == [(201, 407, 0)] and s2.swipes[:1] == ["left"] and s2.swipes.count("right") == 5,
           "máy đang đứng CUỐI danh sách: lướt sang trái không đổi gì (hết danh sách) → tự lướt ngược lại tìm, bấm đúng gói sale 500", (s2.taps, s2.swipes))
        s3 = Shop(2)
        q3 = stepexec.exec_step(s3, dict(tc, scrolls=2), {"package.ocr_text": "7,777", "package.price_text": "CHF 1.00"})
        ok(q3[0] is False and q3[2] is False and s3.taps == [] and "không thấy ô «7,777» có «CHF 1.00» ngay dưới" in q3[1] and len(s3.swipes) <= 2 + 4,
           "gói không có trong danh sách → lướt hết số lần cho phép theo cả hai chiều rồi báo hỏng, KHÔNG bấm gì; lướt xong xuôi không tính là «đã chạm» "
           "(gói hết hạn = «chưa mua», không thành đối soát)", (q3, s3.swipes))
        s3b = Shop(2)
        q3b = stepexec.exec_step(s3b, {"type": "tap_text", "text": "{{otp}}", "near": "{{password}}", "scroll": "left", "scrolls": 1}, {"otp": "135790", "password": "MatKhau-Bi-Mat"})
        ok(q3b[0] is False and "135790" not in q3b[1] and "MatKhau-Bi-Mat" not in q3b[1] and "{{otp}}" in q3b[1] and "{{password}}" in q3b[1],
           "lời báo của bước tìm ô chỉ ghi TÊN biến bí mật, không ghi giá trị", q3b)
        # ghép nhầm giữa các ô / nhập nhằng / ô bị cắt ở mép → không chọn
        grid = [{"text": "300", "x": 200, "y": 140, "w": 60, "h": 26}, {"text": "CHF 2.30", "x": 195, "y": 285, "w": 134, "h": 30},
                {"text": "500", "x": 200, "y": 425, "w": 60, "h": 26}, {"text": "CHF 3.80", "x": 195, "y": 570, "w": 134, "h": 30}]
        ok(stepexec.pick_card(grid, ["500"], ["CHF 2.30"], WH) is None and stepexec.pick_card(grid, ["300"], ["CHF 2.30"], WH) == (200, 140)
           and stepexec.pick_card(grid, ["500"], ["CHF 3.80"], WH) == (200, 425) and stepexec.pick_card(grid, ["300"], ["CHF 3.80"], WH) is None,
           "giá của ô KHÁC (hàng trên / hàng dưới) không ghép được vào số coin của ô này")
        try:
            stepexec.exec_step(Shop(0), {"type": "tap_text", "text": "500", "near": "CHF 2.30", "near_dir": "above"}, {}); raised = False
        except stepexec.ConfigError:
            raised = True
        ok(raised, "chế độ «ngay trên» đã bỏ (giá của ô hàng trên nằm gần số coin hơn giá của chính ô đó) → báo lỗi cấu hình")
        tight = [{"text": "300", "x": 200, "y": 100, "w": 60, "h": 26}, {"text": "Paid: 291", "x": 190, "y": 130, "w": 110, "h": 26},
                 {"text": "CHF 2.30", "x": 195, "y": 160, "w": 134, "h": 30}, {"text": "500", "x": 200, "y": 220, "w": 60, "h": 26},
                 {"text": "Paid: 477", "x": 190, "y": 250, "w": 110, "h": 26}, {"text": "CHF 3.80", "x": 195, "y": 280, "w": 134, "h": 30}]
        ok(stepexec.pick_card(tight, ["300"], ["CHF 3.80"], WH) is None and stepexec.pick_card(tight, ["300"], ["CHF 2.30"], WH) == (200, 100)
           and stepexec.pick_card(tight, ["500"], ["CHF 3.80"], WH) == (200, 220),
           "hàng ô SÁT nhau (giá của ô hàng dưới lọt vào tầm): giữa số coin và giá có một số coin khác = đã sang ô khác → không ghép; dòng «Paid: …» thì không chặn")
        twins = grid + [{"text": "500", "x": 800, "y": 425, "w": 60, "h": 26}, {"text": "CHF 3.80", "x": 795, "y": 570, "w": 134, "h": 30}]
        ok(stepexec.pick_card(twins, ["500"], ["CHF 3.80"], WH) is None, "HAI ô cùng đủ điều kiện → không chọn (nhập nhằng: không đoán ô nào)")
        edge = [{"text": "500", "x": 1310, "y": 425, "w": 60, "h": 26}, {"text": "CHF 2.30", "x": 1300, "y": 570, "w": 80, "h": 30}]
        ok(stepexec.pick_card(edge, ["500"], ["CHF 2.30"], WH) is None, "ô bị CẮT ở mép màn hình (chữ chạm mép: «1,500» cắt còn «500») → không chọn")
        vnd = [{"text": "130", "x": 200, "y": 140, "w": 60, "h": 26}, {"text": "126.000đ", "x": 195, "y": 285, "w": 134, "h": 30}]
        ok(stepexec.pick_card(vnd, ["130"], ["26.000đ"], WH) is None and stepexec.pick_card(vnd, ["130"], ["126.000đ"], WH) == (200, 140),
           "giá phải khớp NGUYÊN DÒNG: «26.000đ» không khớp vào «126.000đ»")
        far = [{"text": "Mua", "x": 900, "y": 300, "w": 60, "h": 30}, {"text": "2150", "x": 310, "y": 300, "w": 80, "h": 30}]
        ok(stepexec.pick_card(far, ["Mua"], ["2150"], WH, "left") is None, "«bên trái / phải»: chữ ở ô bên cạnh (cách ~590 px) không tính là cùng ô")
        PW = (750, 1334)                            # màn DỌC, ô sát nhau, số coin có chữ đi kèm («500 Coins»)
        coins = [{"text": "500 Coins", "x": 200, "y": 100, "w": 160, "h": 30}, {"text": "1,500 Coins", "x": 200, "y": 220, "w": 180, "h": 30},
                 {"text": "CHF 7.50", "x": 200, "y": 280, "w": 134, "h": 30}]
        ok(stepexec.pick_card(coins, ["500 Coins"], ["CHF 7.50"], PW) is None and stepexec.pick_card(coins, ["1,500 Coins"], ["CHF 7.50"], PW) == (200, 220),
           "«500 Coins» và «1,500 Coins» là CÙNG LOẠI (mọi cụm số coi như nhau) → giá của ô 1,500 không ghép nhầm vào ô 500")
        split = [{"text": "1,", "x": 180, "y": 425, "w": 24, "h": 26}, {"text": "500", "x": 215, "y": 425, "w": 46, "h": 26},
                 {"text": "CHF 7.50", "x": 200, "y": 570, "w": 134, "h": 30},
                 {"text": "500", "x": 800, "y": 425, "w": 60, "h": 26}, {"text": "CHF 3.80", "x": 800, "y": 570, "w": 134, "h": 30}]
        ok(stepexec.pick_card(split, ["500"], ["CHF 3.80"], WH) == (800, 425) and stepexec.pick_card(split, ["500"], ["CHF 7.50"], WH) is None
           and stepexec.pick_card(split, ["500"], [], WH) == (800, 425),
           "đọc chữ TÁCH «1,500» thành «1,» + «500»: mảnh «500» dính sát một mảnh số khác cùng hàng = một phần của số lớn hơn → không khớp")
        try:
            stepexec.exec_step(Shop(0), {"type": "tap_text", "text": "500", "near": "x", "near_dir": "any"}, {}); raised = False
        except stepexec.ConfigError:
            raised = True
        ok(raised, "chế độ «ở gần» (không rõ hướng) đã bỏ — dễ ghép nhầm sang ô khác → báo lỗi cấu hình")
        s4 = Shop(3)
        q4 = stepexec.exec_step(s4, {"type": "assert_text", "text": "500", "near": "CHF 3.80"}, {})
        s5 = Shop(0)
        q5 = stepexec.exec_step(s5, {"type": "assert_text", "text": "500", "near": "CHF 3.80"}, {})
        ok(q4 == (True, "", False) and s4.taps == [] and s4.sent == ["home"] and q5[0] is False and s5.swipes == [] and s5.taps == [],
           "«Kiểm có chữ» + chữ đi kèm: chỉ KIỂM (không bấm gì) — dùng để chạy thử việc tìm gói mà không mua; không ghi hướng lướt thì không lướt", (q4, q5))

        class Shift(Shop):                         # ô bị trôi khỏi chỗ cũ trong lúc con trỏ đang đi tới
            def tap_at(self, x, y, click=True, verify=None):
                self.page = 5
                return super().tap_at(x, y, click, verify)
        s6 = Shift(4)
        q6 = stepexec.exec_step(s6, dict(tc), {"package.ocr_text": "3,000", "package.price_text": "CHF 21.00"})
        ok(q6[0] is False and s6.taps == [], "danh sách trôi đi trước khi con trỏ tới nơi (ô không còn ở chỗ cũ) → KHÔNG bấm", q6)
        for bad in ({"near": "x", "near_dir": "cheo"}, {"scroll": "cheo"}, {"near": "x", "scrolls": "nhieu"}, {"near": "  |  "}):
            try:
                stepexec.exec_step(Shop(0), dict({"type": "tap_text", "text": "500"}, **bad), {}); raised = False
            except stepexec.ConfigError:
                raised = True
            ok(raised, "tuỳ chọn «trong cùng ô» sai (%s) → báo lỗi cấu hình, không bấm" % bad)
        ok(stepexec.describe(tc, pv) == "Tap chữ «10,000|10000» có «CHF 63.00» ngay dưới (chưa thấy thì lướt trái)"
           and stepexec.describe({"type": "assert_text", "text": "Mua", "near": "{{password}}", "near_dir": "left"}, {"password": "bi-mat"}) == "Kiểm chữ «Mua» có «{{password}}» bên trái",
           "mô tả bước: hiện giá trị của gói, giữ TÊN biến bí mật", stepexec.describe(tc, pv))
        e7 = Shop(4)
        ok7, msg7 = engine.run_step(e7, dict(tc), )
        ok(ok7 is False and "package.ocr_text" in msg7, "kịch bản thường (không có dữ liệu đơn) dùng chung cách làm: thiếu {{biến}} → báo rõ", msg7)
        e8 = Shop(4)
        ok8, _ = engine.run_step(e8, {"type": "tap_text", "text": "3,000", "near": "CHF 21.00"})
        ok(ok8 is True and e8.taps == [(216, 426, 4)], "kịch bản thường: bước có chữ đi kèm đi qua cùng bộ chạy, bấm đúng ô", e8.taps)

    finally:
        stepexec.LOOK_SETTLE, stepexec._sleep = real_settle, real_sleep

    print("\n== 29. KỊCH BẢN NHẬN ĐƠN: một đơn đi qua kịch bản có cách chạy «nhận đơn» (cùng bộ máy, cùng các chốt) ==")
    for x in rigs:                                   # không rig nào khác còn hỏi đơn của pool này
        if x.running():
            x.stop(force=True, wait=5)
    gk = FakeGame(accounts())
    rk = rig(gk)
    # Kịch bản mới chỉ soạn giai đoạn ĐĂNG NHẬP (thêm một lần «về home» ở đầu để nhận ra); pool của nó là pool ĐỜI CŨ còn lưu bước ở gateway
    # → lần chạy đầu tool CHÉP các giai đoạn còn trống về kịch bản (một lần), ghi vào kịch bản đã lưu.
    import store as store_mod
    real_store = (store_mod.DATA_DIR, store_mod.GROUPS_FILE, store_mod.DEVICES_FILE)
    tmp_store = tempfile.mkdtemp(prefix="tool-store-")
    store_mod.DATA_DIR, store_mod.GROUPS_FILE, store_mod.DEVICES_FILE = tmp_store, os.path.join(tmp_store, "groups.json"), os.path.join(tmp_store, "devices.json")
    kb_login = [{"type": "home"}, {"type": "launch", "app": "efootball"}, {"type": "wait_text", "text": "Konami ID", "timeout": 3}, {"type": "tap_text", "text": "Đăng nhập"},
                {"type": "type", "text": "{{username}}"}, {"type": "key", "name": "tab"}, {"type": "type", "text": "{{password}}"}, {"type": "key", "name": "enter"}]
    script = {"id": "nd", "name": "Nạp theo đơn", "mode": "orders", "steps": [], "loops": 1,
              "orders": {"pool": "game-legacy", "steps": {"login": kb_login}, "login_wait": 5, "purchase_wait": 5, "check_keyboard": False}}
    grp_kb = {"id": "g-kb", "name": "Nhóm kịch bản", "devices": [rk.name], "scripts": [script]}
    store_mod.save_group(json.loads(json.dumps(grp_kb)))
    stored = lambda: next(s for s in store_mod.get_group("g-kb")["scripts"] if s["id"] == "nd")
    jk = gw.new_job("T-KB1", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}], pool="game-legacy")
    ok(rk.runner.start_machine(rk.name, grp_kb, script) is True, "kịch bản nhận đơn khởi động (app cửa sổ)")
    jobk = gw.wait_job(jk, ("done", "failed", "review"))
    ok(jobk["status"] == "done" and gk.purchases == [("a@test.vn", "coin_1050")] and jobk["device"] == rk.name, "đơn hoàn tất qua kịch bản nhận đơn: đúng tài khoản, đúng gói, đúng máy", (jobk["status"], gk.purchases))
    ok(gk.keylog.count("a@test.vn") == 1 and gk.keylog.count("PassA#1") == 1, "tài khoản và mật khẩu chỉ gõ đúng một lần (bước đăng nhập của KỊCH BẢN được dùng)", gk.keylog)
    stk = rk.status()
    ok(stk.get("mode") == "api" and stk.get("group_id") == "g-kb" and stk.get("script_id") == "nd" and stk.get("script_name") == "Nạp theo đơn",
       "máy hiện đang chạy «nhóm · kịch bản» ở chế độ nhận đơn", stk)
    ok([c["name"] for c in rk.runner.customers()] == [rk.name], "…và được tính là MÁY CỦA KHÁCH (mọi luật riêng tư / không chạy đè của chế độ nhận đơn áp dụng)")
    ok(wait_until(lambda: gk.user is None, 5), "xong đơn: đã đăng xuất (bước kết thúc là bước vừa chép về kịch bản)", gk.user)
    so = stored()["orders"]
    rest = ("nav", "purchase", "after", "finish")
    ok(rk.text().count("Đã chép 8 bước cũ từ gateway") == 1 and so["gw_steps_copied"] is True and so["steps"]["login"] == kb_login
       and {p: so["steps"][p] for p in rest} == {p: BASE_STEPS[p] for p in rest} and so["steps"]["otp"] == [],
       "lần chạy đầu: 4 giai đoạn kịch bản còn trống được CHÉP từ pool đời cũ vào kịch bản ĐÃ LƯU (đăng nhập của kịch bản giữ nguyên), đánh dấu đã chép",
       ({p: len(so["steps"][p]) for p in jobflow.PHASES}, so["gw_steps_copied"]))
    wait_until(lambda: rk.status().get("status") == "Chờ đơn", 8)       # máy báo «trống» cho gateway SAU khi đăng xuất xong → chờ nó về «Chờ đơn» rồi mới đọc
    wait_until(lambda: gw.sql("SELECT state FROM devices WHERE name=?", (rk.name,)) == [("free",)], 5)
    devk = gw.sql("SELECT state, pool_code FROM devices WHERE name=?", (rk.name,))
    ok(devk == [("free", "game-legacy")], "gateway thấy máy đang trống ở đúng pool của kịch bản", devk)
    rk.stop()
    gone = stored()
    gone["orders"]["steps"]["after"] = []                          # người dùng xoá hết bước «sau mỗi lần mua» rồi lưu
    store_mod.save_group(dict(store_mod.get_group("g-kb"), scripts=[gone]))
    ok(rk.runner.start_machine(rk.name, store_mod.get_group("g-kb"), stored()) is True and rk.running(), "dừng rồi chạy lại kịch bản nhận đơn được")
    wait_until(lambda: rk.status().get("status") == "Chờ đơn", 8)
    ok(rk.text().count("Đã chép") == 1 and stored()["orders"]["steps"]["after"] == [], "đã chép MỘT lần thì không chép lại: giai đoạn người dùng xoá trống vẫn trống", stored()["orders"]["steps"]["after"])
    rk.stop()
    store_mod.DATA_DIR, store_mod.GROUPS_FILE, store_mod.DEVICES_FILE = real_store
    shutil.rmtree(tmp_store, ignore_errors=True)
    rk.runner.allow_api = False
    ok(rk.runner.start_machine(rk.name, grp_kb, script) is False and not rk.running(), "tiến trình không được nhận đơn (bản web) → kịch bản nhận đơn không khởi động")
    rk.runner.allow_api = True

    print("\n== 34. VÍ của máy do TOOL quản lý (gateway thật): giá theo loại tiền, tiền của đơn về tool qua đồng bộ, ví không đủ → không nhận đơn ==")
    for x in rigs:
        if x.running():
            x.stop(force=True, wait=5)
    gw.sql("UPDATE jobs SET status='cancelled' WHERE status='queued'")             # đơn cũ còn trong hàng đợi của các phần trước
    import notify, wallets, presence, store
    real_data = store.DATA_DIR
    store.DATA_DIR = tempfile.mkdtemp(prefix="api-wallets-")                     # ví của tool trong thư mục tạm (không đụng dữ liệu thật)
    try:
        pkg = gw.sql("SELECT p.id FROM packages p JOIN pools o ON o.id=p.pool_id WHERE o.code='game-test' AND p.code='coin_1050'")[0][0]
        gw.sql("INSERT INTO package_prices (package_id, currency, amount, display) VALUES (?, 'JPY', 160000, '¥1,600')", (pkg,))
        wallets.save("wallet-01", "acb@example.com", "JPY", password="MatKhauApple#9")
        wallets.topup("wallet-01", "4.000", "số dư ban đầu")                      # 4.000 ¥
        claims = []

        class ClaimSpy(Gateway):
            def claim(self, device, pool, wallet=None):
                r = super().claim(device, pool, wallet)
                claims.append((wallet, r))
                return r
        sync = lambda: presence.Reporter(lambda: Gateway(gw.url, gw.tool_key), lambda: ([], []), wallets=wallets).once()
        gwal = FakeGame(accounts())
        rw = rig(gwal, name="wallet-01", gateway_cls=ClaimSpy)
        alerts = []
        rw.runner.alert = lambda ev, name, lines, photo=None: alerts.append((ev, name, lines))
        jw = gw.new_job("T-WAL1", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 2}])
        rw.start()
        jobw = gw.wait_job(jw, ("done", "failed", "review"))
        sent, got = next(((w_, c["job"]) for w_, c in claims if c.get("job")), (None, {}))
        it = (got.get("items") or [{}])[0]
        ok(jobw["status"] == "done" and sent == {"currency": "JPY", "available": 400000, "applied": []} and it.get("price_text") == "¥1,600" and it.get("price") == 160000
           and it.get("currency") == "JPY" and got.get("wallet") == {"source": "tool", "currency": "JPY", "cost": 320000},
           "máy có ví JPY ở tool: xin đơn gửi kèm «JPY, còn 4.000» → đơn giao kèm chữ giá ĐÚNG loại tiền của máy (¥1,600) + giá + chi phí", (jobw["status"], sent, it, got.get("wallet")))
        ev = gw.sql("SELECT kind, d_balance, package_code, qty FROM tool_wallet_events WHERE job_pid=?", (jw,))
        ok(ev == [("purchase", -320000, "coin_1050", 2)] and wallets.get("wallet-01")["balance"] == 400000,
           "nạp được 2 gói → gateway ghi sự kiện «mua» −2 × 1.600 ¥ cho tool (tool chưa đồng bộ thì sổ chưa đổi)", (ev, wallets.get("wallet-01")["balance"]))
        sync()
        led = wallets.ledger("wallet-01")
        ok(wallets.get("wallet-01")["balance"] == 80000 and led[0]["kind"] == "purchase" and led[0]["job"] == jw and led[0]["actor"] == "gateway",
           "đồng bộ → tool áp tiền của đơn vào sổ: còn 800 ¥, dòng sổ ghi đơn nào trả", led[:1])
        sync()
        ok(gw.sql("SELECT COUNT(*) FROM tool_wallet_events WHERE job_pid=? AND acked_at IS NULL", (jw,))[0][0] == 0
           and gw.sql("SELECT balance, apple_account FROM tool_wallets WHERE device='wallet-01'") == [(80000, "acb@example.com")],
           "lần đồng bộ sau: tool báo «đã áp», gateway giữ bản sao ví mới (800 ¥)")
        ok("acb@" not in rw.text() and "MatKhauApple" not in rw.text(), "nhật ký tool không có tài khoản Apple trần / mật khẩu Apple ID", rw.text()[-200:])
        ok(any("tài khoản Apple" in e["text"] and "JPY" in e["text"] and "a***@example.com" in e["text"] for e in rw.logs),
           "nhật ký máy ghi tài khoản Apple (đã che) nào thanh toán đơn", rw.text()[-300:])
        jw2 = gw.new_job("T-WAL2", "a@test.vn", "PassA#1", [{"code": "coin_1050", "qty": 1}])         # cần 1.600 ¥, ví còn 800 ¥
        ok(wait_until(lambda: any(a[0] == "wallet" for a in alerts), 15), "ví không đủ → báo Telegram «Ví không đủ tiền»", alerts)
        time.sleep(1.5)
        wal = [a for a in alerts if a[0] == "wallet"]
        ok(gw.job(jw2)["status"] == "queued" and len(wal) == 1 and "800 JPY" in wal[0][2][-1] and "1.600 JPY" in wal[0][2][-1] and "a***@example.com" in wal[0][2][-1]
           and len(gwal.purchases) == 2, "…KHÔNG nhận đơn (đơn vẫn chờ máy khác), báo đúng một lần với số dư 800 JPY / cần 1.600 JPY, không mua gì thêm",
           (gw.job(jw2)["status"], [a[2][-1] for a in wal]))
        ok("ví" in (rw.status().get("status") or "").lower(), "trạng thái máy nói rõ ví không đủ", rw.status().get("status"))
        wallets.topup("wallet-01", "10000", "thẻ quà tặng")                       # nạp thêm 10.000 ¥ ở TOOL
        jobw2 = gw.wait_job(jw2, ("done", "failed", "review"))
        sync()
        ok(jobw2["status"] == "done" and wallets.get("wallet-01")["balance"] == 80000 + 1000000 - 160000,
           "nạp thêm tiền vào ví ở tool → máy tự nhận lại đơn; đồng bộ xong sổ trừ đúng", (jobw2["status"], wallets.get("wallet-01")["balance"]))
        rw.stop()
    finally:
        store.DATA_DIR = real_data
        gw.sql("DELETE FROM package_prices WHERE package_id=?", (pkg,))

    print("\n== 16. Bí mật không lọt vào nhật ký ==")
    everything = " ".join(x.text() for x in rigs)
    leaked = [s for s in ("PassA#1", "PassB#2", "PassC#3", "SaiMatKhau", "654321", "111111") if s in everything]
    ok(not leaked, "mật khẩu / OTP không xuất hiện trong nhật ký tool", leaked)
    shown = stepexec.describe({"type": "type", "text": "{{password}}"}, {"password": "PassA#1"})
    ok(shown == "Gõ «{{password}}»" and stepexec.describe({"type": "tap_text", "text": "{{package.ocr_text}}"}, {"package.ocr_text": "1050"}) == "Tap chữ «1050»",
       "mô tả bước chỉ ghi TÊN biến bí mật, riêng thông tin gói thì hiện giá trị", shown)
    jl = open(os.path.join(rigs[0].jdir, "api_journal.jsonl"), encoding="utf-8").read()
    ok("T-001" in jl and "PassA#1" not in jl, "sổ lịch sử đơn có ghi đơn, không chứa mật khẩu")


if __name__ == "__main__":
    sys.exit(main())
