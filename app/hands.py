#!/usr/bin/env python3
"""
hands.py — điều khiển ESP32 (bàn phím+chuột BLE) qua Serial từ máy tính.

Dùng như thư viện:
    from hands import Hands
    h = Hands()                 # tự tìm cổng ESP32 (CP2102/CH340/CH9102)
    h.type("hello"); h.key("enter"); h.move(50,0); h.click()

Chạy trực tiếp để test tay:
    python app/hands.py                 # tự tìm cổng, mở REPL
    python app/hands.py /dev/cu.usbserial-0001
Trong REPL gõ thẳng lệnh firmware: ping / status / type ... / key enter / move 50 0 / click
Gõ 'q' để thoát.
"""
from __future__ import annotations
import os, sys, time
import serial
from serial.tools import list_ports

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quietserial import QuietSerial

UART_VIDPID = {(0x10C4, 0xEA60), (0x1A86, 0x7523), (0x1A86, 0x55D4), (0x0403, 0x6001)}


def find_port() -> str | None:
    for p in list_ports.comports():
        if p.vid is not None and (p.vid, p.pid) in UART_VIDPID:
            return p.device
    return None


class Hands:
    def __init__(self, port: str | None = None, baud: int = 115200, timeout: float = 2.0,
                 reset: bool = False):
        self.port = port or find_port()
        if not self.port:
            raise RuntimeError("Không tìm thấy cổng ESP32 (CP2102/CH340). Cắm board + chạy doctor.")
        # Mở cổng KHÔNG reset board (giữ phiên BLE): QuietSerial hạ RTS trước DTR lúc mở (xem quietserial.py;
        # chỉ đặt dtr/rts=False trước khi open KHÔNG đủ — pyserial vẫn hạ DTR trước và board vẫn bị reset).
        self.ser = QuietSerial()
        self.ser.port = self.port
        self.ser.baudrate = baud
        self.ser.timeout = timeout
        self.ser.dtr = False
        self.ser.rts = False
        if os.name == "posix":
            # Khoá ĐỘC QUYỀN: app, lệnh `farm` và máy chủ MCP có thể cùng muốn điều khiển một board. Hai bên cùng
            # mở một cổng sẽ đọc lẫn phản hồi của nhau (lệnh bấm của bên này bị bên kia «nuốt» câu trả lời).
            # Có khoá thì bên mở sau nhận lỗi rõ ràng. (Windows vốn không cho mở một cổng COM hai lần.)
            self.ser.exclusive = True
        try:
            self.ser.open()
        except serial.SerialException as e:
            if "lock" in str(e).lower() or "busy" in str(e).lower():
                raise RuntimeError("Cổng %s đang được chương trình khác điều khiển (app iPhone Farm, lệnh farm hoặc AI)." % self.port)
            raise
        self._rx = b""              # phần dòng chưa trọn vẹn đọc dở từ board
        self._sent_at = 0.0
        if reset:
            # chủ động reset nếu cần (EN qua RTS)
            self.ser.rts = True; time.sleep(0.1); self.ser.rts = False
            time.sleep(1.8)
        else:
            time.sleep(0.3)
        self._drain()

    def _drain(self):
        """Đọc bỏ hết rác khởi động (boot log) cho tới khi im."""
        self.ser.timeout = 0.3
        for _ in range(50):
            if not self.ser.readline():
                break
        self.ser.timeout = 2.0
        self.ser.reset_input_buffer()

    # Dòng trả lời của từng lệnh (firmware trả đúng MỘT dòng cho mỗi lệnh). Lệnh không có ở đây → "OK <lệnh>".
    REPLY = {"ping": ("pong",), "whoami": ("NAME ",), "status": ("OK ble=",)}
    MIN_GAP = 0.06      # nghỉ tối thiểu giữa hai lệnh liên tiếp (đừng dồn sự kiện HID sát nhau quá)

    def _lines(self, deadline: float):
        """Sinh lần lượt từng DÒNG trọn vẹn board gửi về, cho tới hạn `deadline`. Dòng mới về một nửa thì gom
        tiếp chứ không trả nửa dòng (đọc theo timeout ngắn hay cắt đôi một dòng thành hai mẩu vô nghĩa)."""
        while True:
            nl = self._rx.find(b"\n")
            if nl >= 0:
                line, self._rx = self._rx[:nl], self._rx[nl + 1:]
                text = line.decode("utf-8", "ignore").strip()
                if text:
                    yield text
                continue
            left = deadline - time.time()
            if left <= 0:
                return
            self.ser.timeout = min(0.05, max(0.005, left))
            self._rx += self.ser.read(max(1, getattr(self.ser, "in_waiting", 0) or 1))

    presses = 0         # số lần lệnh nhấn nút chuột (click / down) đã được GHI ra cổng — xem stepexec.gesture()

    _owed = False       # lệnh trước CHƯA nhận được câu trả lời (hết giờ) → câu trả lời muộn của nó có thể còn tới

    @staticmethod
    def _clean(cmd: str) -> str:
        """Một lệnh = MỘT dòng chữ ASCII in được. Xuống dòng lẫn trong tham số sẽ thành một lệnh thứ hai chạy mù
        trên board (vd tên app «Settings\\nclick» = bấm chuột bừa); chữ có dấu thì firmware gõ ra rác."""
        cmd = str(cmd).strip()
        if not cmd or any(not (32 <= ord(ch) <= 126) for ch in cmd):
            raise ValueError("lệnh gửi xuống board chỉ được gồm chữ không dấu, số, ký hiệu thường trên MỘT dòng")
        return cmd

    @staticmethod
    def _is_reply(line: str) -> bool:
        return line.startswith(("OK", "ERR", "pong", "NAME "))

    def _begin(self, data: str, urgent: bool = False):
        if any(c.split(" ", 1)[0] in ("click", "rclick", "down") for c in data.split("\n")):
            self.presses += 1               # đếm TRƯỚC khi ghi: ghi xong mà cổng lỗi thì lệnh vẫn có thể đã tới iPhone
        gap = self.MIN_GAP - (time.time() - self._sent_at)
        if gap > 0 and not urgent:          # lệnh NHẢ chuột thì gửi ngay, không chờ nhịp (không để điều gì chen vào trước nó)
            time.sleep(gap)
        if self._owed and not urgent:
            # Lệnh trước chưa trả lời: chờ board im hẳn (tối đa 1,5s) để câu trả lời muộn của nó tới và bị bỏ đi
            # TRƯỚC khi gửi lệnh mới — nếu không nó sẽ bị đọc thành câu trả lời của lệnh mới.
            end, quiet = time.time() + 1.5, time.time() + 0.25
            while time.time() < min(end, quiet):
                if next(self._lines(time.time() + 0.05), None) is not None:
                    quiet = time.time() + 0.25
        self.ser.reset_input_buffer()
        self._rx = b""
        self.ser.write(data.encode("ascii"))
        self.ser.flush()

    def send(self, cmd: str, wait: float = 0.5) -> str:
        """Gửi 1 lệnh, trả dòng phản hồi của nó ("" nếu hết `wait` giây mà không có câu trả lời nào CHẮC là của nó).

        Trả về NGAY khi thấy dòng trả lời của chính lệnh này ("OK <lệnh>…") — không chờ thêm. "ERR…" không mang
        tên lệnh: nó chỉ được coi là của lệnh này khi không còn lệnh nào trước đó «nợ» câu trả lời. Các dòng
        khác (câu trả lời muộn của lệnh trước, dòng log của board) bị bỏ qua trong lúc chờ. Hết giờ: trả dòng
        LẠ cuối cùng nếu có (để bên gọi biết board có nói gì đó), còn «OK của lệnh khác» / «ERR mơ hồ» thì KHÔNG
        được trả về như thể là của lệnh này → trả "" (bên gọi coi là «không rõ đã chạy hay chưa»).
        `wait` = tối đa bao lâu chờ (tối thiểu 0.5s). Lệnh chạy lâu (gõ chuỗi dài, di chuột xa) chỉ trả lời
        SAU khi làm xong → phải truyền `wait` đủ lớn, nếu không sẽ tưởng «không phản hồi» khi board còn đang làm."""
        cmd = self._clean(cmd)
        word = cmd.split(" ", 1)[0]
        want = self.REPLY.get(word, ("OK " + word,))
        self._begin(cmd + "\n")
        owed, odd = self._owed, ""
        self._owed = True                   # cho tới khi thấy đúng câu trả lời của lệnh này
        try:
            for line in self._lines(time.time() + max(0.5, wait)):
                if line.startswith(want):
                    self._owed = False
                    return line
                if line.startswith("ERR") and not owed:
                    self._owed = False
                    return line             # không lệnh nào trước đó còn nợ → ERR này là của lệnh vừa gửi
                if not self._is_reply(line):
                    odd = line
        finally:
            self.ser.timeout = 2.0
            self._sent_at = time.time()
        return odd

    def wait_connected(self, timeout: float = 15.0) -> bool:
        """Chờ tới khi iPhone kết nối HID ổn định."""
        end = time.time() + timeout
        while time.time() < end:
            if "ble=connected" in self.status():
                return True
            time.sleep(1)
        return False

    def do(self, cmd: str, retries: int = 3, wait: float = 0.5) -> str:
        """Gửi lệnh, tự chờ kết nối + thử lại nếu rớt."""
        for _ in range(retries):
            r = self.send(cmd, wait=wait)
            if r.startswith("OK") or r == "pong":
                return r
            if "not-connected" in r or r == "":
                self.wait_connected(8)
                time.sleep(0.2)
                continue
            return r
        return r

    # tiện ích
    def ping(self):   return self.send("ping")
    def status(self): return self.send("status")

    def type(self, text: str) -> str:
        """Gõ chuỗi. Firmware gõ từng ký tự rồi mới trả "OK type N" nên chờ theo độ dài.
        KHÔNG gõ lại khi không rõ kết quả (phản hồi rỗng) — gõ trùng làm hỏng mật khẩu/OTP;
        chỉ thử lại khi board báo rõ "not-connected" (chắc chắn chưa gõ ký tự nào)."""
        wait = 0.8 + 0.08 * len(text)
        r = ""
        for _ in range(3):
            r = self.send("type " + text, wait=wait)
            if "not-connected" in r:
                self.wait_connected(8)
                time.sleep(0.2)
                continue
            return r
        return r

    def key(self, name: str):  return self.do("key " + name)

    def move(self, dx: int, dy: int):
        # firmware di ~1000 đơn vị/giây và chỉ trả lời khi di xong
        return self.do(f"move {dx} {dy}", wait=0.5 + max(abs(dx), abs(dy)) * 0.002)
    # Con trỏ iOS «ngủ» sau ~2 giây đứng yên (mất trạng thái đang-trỏ-vào-nút); cú bấm lúc đó có thể bị BỎ QUA
    # (gặp thật ở nút của hộp thoại hệ thống). Nhích 1 đơn vị rồi về chỗ cũ ngay trước khi bấm để đánh thức.
    WAKE = ("move 1 0", "move -1 0")
    # Mỗi gói «di chuột» gửi lên iPhone đều mang kèm trạng thái nút. Nhích 1 đơn vị rồi về chỗ cũ NGAY SAU khi
    # nhả = gửi lại trạng thái «đã nhả» thêm 2 lần, phòng gói «nhả» bị rớt (chuột kẹt ở trạng thái nhấn thì mọi
    # thao tác sau đó thành kéo-thả). KHÔNG rung sau khi NHẤN: đã thử trên máy thật — iOS khi đó không còn coi
    # cú kéo là vuốt (lật trang hỏng 7/8 lần).
    def click(self) -> str:
        """Bấm chuột trái tại chỗ con trỏ đang đứng — đánh thức con trỏ rồi bấm, liền một mạch.
        Gửi ĐÚNG MỘT LẦN (không tự bấm lại khi mất phản hồi: bấm đôi còn tệ hơn không bấm)."""
        r = self.burst([*self.WAKE, "click", *self.WAKE], wait=1.0)
        return next((x for x in r if "click" in x), r[-1] if r else "")

    def down(self):   return self.do("down")
    def up(self):     return self.do("up")

    def hold(self, seconds: float = 1.0) -> bool:
        """BẤM GIỮ tại chỗ con trỏ đang đứng rồi nhả. Luôn gửi lệnh nhả, kể cả khi có lỗi giữa chừng."""
        r = []
        try:                                # kể cả lệnh «nhấn» lỗi giữa chừng (đã ghi ra cổng) cũng phải có lệnh nhả
            r = self.burst([*self.WAKE, "down"], wait=1.0)
            time.sleep(max(0.0, seconds))
        finally:
            u = self.burst(["up", *self.WAKE], wait=1.0, urgent=True)
            if not any(x.startswith("OK up") for x in u):
                if any("not-connected" in x for x in u):     # Bluetooth rớt đúng lúc đang giữ: chờ nối lại rồi mới nhả được
                    try:
                        self.wait_connected(8)
                    except Exception:
                        pass
                u = self.burst(["up", *self.WAKE], wait=1.0, urgent=True)
        return any(x.startswith("OK down") for x in r) and any(x.startswith("OK up") for x in u)

    RELEASE_AGAIN = (0.12, 0.25)    # sau cú kéo: nghỉ từng quãng này (giây) rồi gửi lại trạng thái «đã nhả»

    def swipe(self, dx: int, dy: int) -> bool:
        """VUỐT từ chỗ con trỏ đang đứng: nhấn → kéo (dx,dy) → nhả, LIỀN MỘT MẠCH. Nếu nhấn rồi nửa giây
        sau mới kéo (gửi từng lệnh) thì iOS coi là bấm giữ chứ không phải vuốt.

        Lệnh NHẢ được gửi lại thêm vài lần, cách quãng. Lý do (gặp trên máy thật, ~1/4 số lần ở một board):
        cú kéo dài làm board gửi dồn dập hàng trăm gói Bluetooth, hàng chờ đầy, và gói «nhả» đi ngay sau đó bị
        RỚT cùng các gói nhích kèm theo → iPhone tưởng ngón tay vẫn đang giữ, trang bị kẹt lưng chừng cho tới
        thao tác chuột kế tiếp. Chờ hàng chờ vơi rồi báo «đã nhả» lần nữa thì hết; gói đầu đã tới nơi thì các
        lần sau vô hại (nhả một nút đang nhả = không có gì xảy ra)."""
        cmds = [*self.WAKE, "down", f"move {int(dx)} {int(dy)}", "up", *self.WAKE]
        r = []
        try:
            r = self.burst(cmds, wait=1.0 + max(abs(dx), abs(dy)) * 0.002)
        finally:                            # lệnh chính lỗi giữa chừng (cổng rớt…) vẫn thử nhả nút thêm vài lần
            for pause in self.RELEASE_AGAIN:
                time.sleep(pause)
                try:
                    self.burst(["up", *self.WAKE], wait=0.6, urgent=True)
                except Exception:
                    pass
        if not any(x.startswith("OK up") for x in r):
            return False                    # board không xác nhận lệnh nhả trong mạch chính → báo «không chắc»
        return len(r) == len(cmds) and all(x.startswith("OK") for x in r)

    def burst(self, cmds: list, wait: float = 1.0, urgent: bool = False) -> list:
        """Gửi NHIỀU lệnh trong một lần ghi để board chạy LIỀN MẠCH (không có khoảng nghỉ giữa các lệnh như
        khi gửi từng lệnh). Cần cho cử chỉ: «nhấn → kéo → nhả» mà cách quãng thì iOS coi là bấm giữ chứ không
        phải vuốt. Trả danh sách phản hồi (đủ số lệnh thì dừng, hoặc hết `wait` giây kể từ dòng cuối).
        KHÔNG tự gửi lại."""
        cmds = [self._clean(c) for c in cmds]
        self._begin("".join(c + "\n" for c in cmds), urgent)
        out = []
        try:
            while len(out) < len(cmds):
                line = next(self._lines(time.time() + wait), None)     # còn lệnh đang chạy (di chuột dài) → chờ tiếp
                if line is None:
                    break
                if self._is_reply(line):                               # dòng log của board không tính là câu trả lời
                    out.append(line)
        finally:
            self.ser.timeout = 2.0
            self._sent_at = time.time()
            self._owed = len(out) < len(cmds)
        return out

    def close(self):
        try: self.ser.close()
        except Exception: pass


def repl(port: str | None):
    try:
        h = Hands(port)
    except Exception as e:
        print("Lỗi:", e); return
    print(f"Đã nối {h.port}. Gõ lệnh firmware (q để thoát).")
    print("Thử:  status  |  type xin chao  |  key enter  |  move 50 0  |  click")
    # đọc dòng BOOT nếu có
    try:
        h.ser.timeout = 0.5
        boot = h.ser.readline().decode("utf-8", "ignore").strip()
        if boot: print("  <", boot)
        h.ser.timeout = 2.0
    except Exception:
        pass
    while True:
        try:
            cmd = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if cmd in ("q", "quit", "exit"): break
        if not cmd: continue
        print("  <", h.send(cmd))
    h.close()
    print("Thoát.")


if __name__ == "__main__":
    port = sys.argv[1] if len(sys.argv) > 1 else None
    repl(port)
