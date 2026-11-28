#!/usr/bin/env python3
"""
Kiểm VÍ của từng máy do TOOL quản lý (app/wallets.py) + đồng bộ ví với gateway (presence.Reporter):
khai ví, mã hoá mật khẩu Apple ID, nạp / chỉnh số dư, áp tiền của đơn do gateway gửi (mỗi sự kiện MỘT lần), báo «đã áp», bản sao gửi gateway,
gói «1 lần» còn mua được (chữ «Remaining: 1» trong đúng ô gói).

    ./.venv/bin/python app/tests/test_wallets.py
"""
from __future__ import annotations
import json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import store, wallets, presence, jobflow, stepexec

PASS = FAIL = 0


def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ✓", name)
    else:
        FAIL += 1; print("  ✗", name, "→", ctx if ctx is not None else "")


def main():
    tmp = tempfile.mkdtemp(prefix="ipf-wallets-")
    real = store.DATA_DIR
    store.DATA_DIR = tmp                                  # KHÔNG đụng dữ liệu thật
    try:
        print("== 1. Tiền: đọc chữ người nhập (đúng luật gateway) ==")
        P = wallets.parse_money
        ok(P("1.500", "JPY") == 150000 and P("1500", "JPY") == 150000 and P("1,500", "JPY") == 150000 and P("63.5", "CHF") == 6350
           and P("63,50", "CHF") == 6350 and P("1.234,56", "CHF") == 123456 and P("1,234.56", "CHF") == 123456 and P("0", "JPY") == 0,
           "dấu nghìn / phần lẻ kiểu Việt lẫn kiểu Anh → ×100")
        ok(P("1500.50", "JPY") is None and P("-5", "JPY") is None and P("+5", "JPY") is None and P("-1.000", "JPY", True) == -100000
           and P("abc", "JPY") is None and P("1.5.0", "CHF") is None and P("", "JPY") is None and P("12.", "CHF") is None,
           "JPY không có phần lẻ; âm / «+» chỉ khi chỉnh số dư; chữ sai → None")
        ok(wallets.fmt(150000, "JPY") == "1.500 JPY" and wallets.fmt(6350, "CHF") == "63,50 CHF" and wallets.fmt(-100000, "JPY") == "-1.000 JPY",
           "hiện số tiền như gateway (1.500 JPY · 63,50 CHF)")
        ok(wallets.currency("¥") == "JPY" and wallets.currency("jp") == "JPY" and wallets.currency("円") == "JPY" and wallets.currency("kr") == "KR" and wallets.currency("1kr") is None and wallets.currency("kr.") == "KR" and wallets.currency("Rs.") == "RS" and wallets.currency("лв.") == "ЛВ"
       and wallets.currency("Fr.") == "FR" and wallets.currency("u.s.") == "USD" and wallets.currency(".") is None and wallets.currency("₹") == "₹" and wallets.currency("R$") == "R$"
       and wallets.currency("toolong") is None
           and wallets.label("JPY") == "JPY ¥", "loại tiền là nhãn: «¥» / «JP» → JPY (giống gateway); «kr» giữ nhãn riêng; nhãn «JPY ¥»")
        ok(wallets.mask("apple01@example.com") == "a***@example.com" and wallets.mask("0912345678") == "09***78", "che tài khoản Apple khi ghi nhật ký")

        print("== 2. Khai ví + mật khẩu Apple ID mã hoá ==")
        for bad, why in ((lambda: wallets.save("", "a@example.com", "JPY"), "thiếu máy"), (lambda: wallets.save("M1", "", "JPY"), "thiếu tài khoản"),
                         (lambda: wallets.save("M1", "a@example.com", "1J"), "loại tiền sai")):
            try:
                bad(); ok(False, "khai ví %s → báo lỗi" % why)
            except wallets.WalletError:
                ok(True, "khai ví %s → báo lỗi" % why)
        w = wallets.save("M1", "apple01@example.com", "jpy", "vùng Nhật", password="Mk-Apple#1")
        raw = open(os.path.join(tmp, "wallets.json"), encoding="utf-8").read()
        ok(w["currency"] == "JPY" and w["has_password"] and w["balance"] == 0 and "password" not in w and "pw" not in w,
           "khai ví: loại tiền viết hoa, có mật khẩu (giao diện chỉ thấy «đã lưu», không thấy mật khẩu)", w)
        ok("Mk-Apple" not in raw and json.loads(raw)["wallets"]["M1"]["pw"] and os.path.exists(os.path.join(tmp, "secret.key")),
           "mật khẩu lưu MÃ HOÁ trong tệp (không có chữ thật), khoá riêng ở secret.key")
        ok(wallets.apple("M1") == {"account": "apple01@example.com", "password": "Mk-Apple#1"}, "bộ chạy đơn lấy được tài khoản + mật khẩu để gõ vào bảng mua")
        wallets.save("M1", "apple01@example.com", "JPY", "vùng Nhật", password="")
        ok(wallets.apple("M1").get("password") == "Mk-Apple#1", "sửa ví để trống ô mật khẩu → giữ mật khẩu cũ")
        wallets.save("M1", "apple01@example.com", "JPY", "vùng Nhật", clear_password=True)
        ok("password" not in wallets.apple("M1") and not wallets.get("M1")["has_password"], "xoá mật khẩu đã lưu")
        wallets.save("M1", "apple01@example.com", "JPY", "vùng Nhật", password="Mk-Apple#1")
        r = wallets.report()
        ok(r == [{"device": "M1", "apple_account": "apple01@example.com", "currency": "JPY", "balance": 0, "held": 0, "active": True, "note": "vùng Nhật"}]
           and "Mk-Apple" not in json.dumps(r), "bản sao gửi gateway: tài khoản, loại tiền, số dư — KHÔNG có mật khẩu", r)

        print("== 3. Nạp / chỉnh số dư ==")
        wallets.topup("M1", "20.000", "số dư ban đầu")
        wallets.topup("M1", "5000", "thẻ quà tặng …1234")
        for f, why in ((lambda: wallets.topup("M1", "-5"), "nạp số âm"), (lambda: wallets.topup("M1", "12.5"), "JPY có phần lẻ"),
                       (lambda: wallets.adjust("M1", "-1.000", ""), "chỉnh không ghi lý do"), (lambda: wallets.adjust("M1", "0", "x"), "chỉnh 0"),
                       (lambda: wallets.topup("M-chua-co", "100"), "máy chưa có ví")):
            try:
                f(); ok(False, why + " → từ chối")
            except wallets.WalletError:
                ok(True, why + " → từ chối")
        wallets.adjust("M1", "-1.000", "đối chiếu số dư trên máy")
        w = wallets.get("M1")
        led = wallets.ledger("M1")
        ok(w["balance"] == 2400000 and w["available"] == 2400000 and [e["kind"] for e in led] == ["adjust", "topup", "topup"]
           and led[0]["note"] == "đối chiếu số dư trên máy", "nạp 20.000 + 5.000, chỉnh −1.000 → 24.000 JPY; sổ mới nhất trước", (w, [e["kind"] for e in led]))
        ok(wallets.claim_info("M1") == {"currency": "JPY", "available": 2400000, "applied": []} and wallets.claim_info("M-khac") is None,
           "xin đơn gửi kèm «loại tiền + còn dùng được»; máy chưa có ví → không gửi (không kiểm tiền)")
        try:
            wallets.save("M1", "apple01@example.com", "CHF"); ok(False, "đổi loại tiền khi ví còn tiền → từ chối")
        except wallets.WalletError as e:
            ok("về 0" in str(e), "đổi loại tiền khi ví còn tiền → từ chối (chỉnh số dư về 0 trước)", str(e))

        print("== 4. Tiền của đơn từ gateway: áp mỗi sự kiện MỘT lần ==")
        ev = [{"id": 11, "device": "M1", "job": "JAAA", "kind": "purchase", "currency": "JPY", "d_balance": -300000, "d_held": 0, "package_code": "gem_s", "qty": 2, "note": "Mua Gói nhỏ"},
              {"id": 12, "device": "M1", "job": "JBBB", "kind": "hold", "currency": "JPY", "d_balance": 0, "d_held": 400000, "note": "Tạm giữ"},
              {"id": 13, "device": "M1", "job": "JCCC", "kind": "la", "currency": "JPY", "d_balance": -5, "d_held": 0},       # loại lạ: không áp
              {"id": "x", "device": "M1", "kind": "purchase", "currency": "JPY", "d_balance": -1, "d_held": 0}]                   # id sai: bỏ qua
        n = wallets.apply_events(ev)
        w = wallets.get("M1")
        ok(n == 2 and w["balance"] == 2100000 and w["held"] == 400000 and w["available"] == 1700000 and wallets.pending_acks() == [11, 12, 13],
           "áp «mua» −3.000 và «tạm giữ» 4.000 → số dư 21.000, còn dùng được 17.000; sự kiện lạ không áp nhưng vẫn báo đã nhận", (n, w, wallets.pending_acks()))
        n2 = wallets.apply_events(ev[:2])
        ok(n2 == 0 and wallets.get("M1")["balance"] == 2100000, "gateway gửi lại cùng sự kiện (chưa kịp nhận lời «đã áp») → KHÔNG trừ lần hai")
        wallets.acked([11, 12, 13])
        ok(wallets.pending_acks() == [], "gateway xác nhận đã nhận lời «đã áp» → thôi gửi")
        wallets.apply_events([{"id": 14, "device": "M1", "job": "JBBB", "kind": "charge", "currency": "JPY", "d_balance": -250000, "d_held": -400000, "note": "Admin chốt"}])
        w = wallets.get("M1")
        ok(w["balance"] == 1850000 and w["held"] == 0 and w["available"] == 1850000, "admin chốt «đã nạp» 2.500 → trừ số dư, đóng tạm giữ", w)
        e14 = wallets.ledger("M1")[0]
        ok(e14["kind"] == "charge" and e14["actor"] == "gateway" and e14["job"] == "JBBB" and e14["event"] == 14, "sổ ghi rõ dòng nào là tiền của đơn nào (gateway gửi)", e14)
        try:
            wallets.apply_events([{"id": 15, "device": "M1", "job": "JD", "kind": "hold", "currency": "JPY", "d_balance": 0, "d_held": 100}])
            wallets.remove("M1"); ok(False, "bỏ ví đang tạm giữ → từ chối")
        except wallets.WalletError:
            ok(True, "bỏ ví đang tạm giữ tiền cho đơn chờ đối soát → từ chối")
        wallets.apply_events([{"id": 16, "device": "M1", "job": "JD", "kind": "release", "currency": "JPY", "d_balance": 0, "d_held": -100}])
        ok(wallets.remove("M1") and wallets.get("M1") is None and len(wallets.ledger("M1")) >= 6, "bỏ ví (sổ vẫn giữ để tra)")

        print("== 5. Đồng bộ với gateway: gửi bản sao + lời «đã áp», nhận sự kiện ==")
        wallets.save("M2", "apple02@example.com", "CHF")
        wallets.topup("M2", "100", "đầu")

        class GW:
            def __init__(self): self.bodies = []; self.events = [{"id": 21, "device": "M2", "job": "JX", "kind": "purchase", "currency": "CHF", "d_balance": -900, "d_held": 0}]
            def sync(self, body, timeout=12):
                self.bodies.append(body)
                ev, self.events = self.events, []
                return {"ok": True, "scripts_rev": body.get("scripts_rev"), "need_scripts": False, "wallet_events": ev}
        gw = GW()
        clock = [1000.0]
        rep = presence.Reporter(lambda: gw, lambda: ([], []), clock=lambda: clock[0], wallets=wallets)
        rep.once()
        b1 = gw.bodies[-1]
        ok(any(x["device"] == "M2" and x["balance"] == 10000 for x in b1.get("wallets") or []) and 21 not in (b1.get("wallet_acks") or [])
           and wallets.get("M2")["balance"] == 9100, "lần đồng bộ đầu: gửi bản sao ví; nhận sự kiện «mua» → áp ngay (100 − 9 = 91 CHF)", (b1.get("wallets"), wallets.get("M2"), rep.state()))
        clock[0] += 5
        rep.once()
        b2 = gw.bodies[-1]
        ok(len(gw.bodies) == 2 and b2.get("wallet_acks") == [21] and any(x["device"] == "M2" and x["balance"] == 9100 for x in b2["wallets"]) and wallets.pending_acks() == [],
           "vừa áp sự kiện → nhịp sau gửi ngay lời «đã áp» + bản sao số dư mới; gateway nhận xong thì thôi gửi", b2.get("wallet_acks"))

        print("== 6. Gói «1 lần»: chữ «Remaining: 1» phải nằm trong ĐÚNG ô gói ==")
        L = lambda t, x, y, w=60, h=20: {"text": t, "x": x, "y": y, "w": w, "h": h}
        # hai ô cạnh nhau: ô sale 500 (có Remaining: 1) và ô thường 500 (không có) — bố cục ngang như danh sách eFootball
        lines = [L("500", 200, 300), L("Remaining: 1", 200, 260, 120), L("CHF 2.30", 200, 420), L("500", 800, 300), L("CHF 3.80", 800, 420)]
        left = [stepexec._flat("Remaining: 1")]
        ok(stepexec.once_left_in_card(lines, (200, 300), left, (1334, 750)), "ô sale 500 có «Remaining: 1» trong ô → còn mua được")
        ok(not stepexec.once_left_in_card(lines, (800, 300), left, (1334, 750)), "ô thường 500 bên cạnh: «Remaining: 1» thuộc ô kia → KHÔNG tính")
        ok(not stepexec.once_left_in_card([L("500", 200, 300), L("CHF 2.30", 200, 420)], (200, 300), left, (1334, 750)), "ô không có chữ → gói đã mua / hết lượt")
        ok(not stepexec.once_left_in_card([L("500", 200, 300), L("Remaining: 1", 200, 700, 120)], (200, 300), left, (1334, 750)), "chữ ở quá xa ô gói → không tính")
        print("== 7. Bộ chạy đơn: gói «1 lần» — kiểm ô gói trước khi mua (không bấm gì) ==")
        import numpy as np
        stepexec._sleep = lambda *a, **k: None                          # bài thử: không chờ thật

        class E:
            def __init__(self, lines): self.lines = lines
            def screenshot(self): return np.zeros((750, 1334, 3), np.uint8)
            def text_lines(self, img=None): return list(self.lines)

        class H:
            def __init__(self): self.sent = []
            def send(self, c): self.sent.append(c)

        class Nv:
            def __init__(self, lines): self.e, self.h = E(lines), H()
        sale = [L("500", 200, 300), L("Remaining: 1", 200, 260, 120), L("CHF 2.30", 200, 420), L("500", 800, 300), L("CHF 3.80", 800, 420)]
        steps = {"purchase": [{"type": "tap_text", "text": "{{package.ocr_text}}", "near": "{{package.price_text}}", "timeout": 0}]}
        pv = {"package.ocr_text": "500", "package.price_text": "CHF 2.30", "package.name": "Coin Sale 500", "package.code": "sale_500"}
        item = {"code": "sale_500", "name": "Coin Sale 500", "limit_type": "once"}
        pkgs = [{"code": "coin_500", "ocr_text": "500"}, {"code": "sale_500", "ocr_text": "500"}]
        mk = lambda lines, rules=None: jobflow.JobFlow(Nv(lines), None, {"id": "J1", "items": [item]}, {"rules": rules or [], "packages": pkgs}, steps)
        f1 = mk(sale)
        ok(f1._once_left(item, pv) == (True, "") and not [c for c in f1.nav.h.sent if c != "home"],
           "ô sale 500 (500 · CHF 2.30) có «Remaining: 1» → còn mua được; không bấm gì", f1._once_left(item, pv))
        f2 = mk([L("500", 800, 300), L("CHF 3.80", 800, 420)])
        r2 = f2._once_left(item, pv)
        ok(r2[0] is False and "đã mua" in r2[1], "ô sale 500 không còn trên cửa hàng (chỉ còn ô thường 500 · CHF 3.80) → «đã mua rồi», không mua nhầm gói thường", r2)
        f3 = mk([L("500", 200, 300), L("CHF 2.30", 200, 420)])
        r3 = f3._once_left(item, pv)
        ok(r3[0] is False and "Remaining: 1" in r3[1], "ô gói còn nhưng không có «Remaining: 1» → coi như đã mua / hết lượt, không bấm", r3)
        f4 = mk([L("500", 200, 300), L("Còn lại: 1", 200, 260, 120), L("CHF 2.30", 200, 420)], rules=[{"when": "once_left", "value": "Còn lại: 1"}])
        ok(f4._once_left(item, pv) == (True, ""), "chữ «còn 1 lượt» lấy theo luật once_left của pool (game tiếng khác)")
        f5 = jobflow.JobFlow(None, None, {"id": "J1"}, {}, {}, apple={"account": "apple01@example.com", "password": "Mk-Apple#1"})
        ok(f5.apple == {"account": "apple01@example.com", "password": "Mk-Apple#1"}
           and stepexec.describe({"type": "type", "text": "{{apple.password}}"}, {"apple.password": "Mk-Apple#1"}) == "Gõ «{{apple.password}}»",
           "bộ chạy đơn nhận tài khoản / mật khẩu Apple của máy; nhật ký chỉ ghi TÊN biến {{apple.password}}, không ghi mật khẩu")
        print("== 8. Chống áp trùng / tính trùng tiền của đơn ==")
        wallets.save("M3", "apple03@example.com", "JPY")
        wallets.topup("M3", "10.000", "đầu")
        real_save = wallets._save
        boom = {"n": 1}

        def flaky(d):
            if boom["n"]:
                boom["n"] -= 1
                raise OSError("tệp đang bị khoá (giả lập Windows)")
            real_save(d)
        wallets._save = flaky
        evr = [{"id": 31, "device": "M3", "job": "JR", "kind": "refund", "currency": "JPY", "d_balance": 200000, "d_held": 0}]
        try:
            wallets.apply_events(evr)
        except OSError:
            pass
        wallets._save = real_save
        wallets.apply_events(evr)                                      # gateway gửi lại (chưa nhận lời «đã áp»)
        ok(wallets.get("M3")["balance"] == 1200000 and [e["event"] for e in wallets.ledger("M3") if e.get("event")] == [31],
           "lưu danh sách «đã áp» hỏng giữa chừng rồi gateway gửi lại → KHÔNG hoàn hai lần (sổ là bằng chứng đã áp)", wallets.get("M3")["balance"])
        ok(wallets.claim_info("M3") == {"currency": "JPY", "available": 1200000, "applied": [31]},
           "xin đơn: tính ĐỦ mọi dòng sổ + gửi kèm id các khoản đã áp (gateway chỉ cộng khoản tool CHƯA áp) → không cộng hai lần / không bỏ sót", wallets.claim_info("M3"))
        wallets.acked([31])
        wallets.save("M4", "apple04@example.com", "JPY")
        wallets.apply_events([{"id": 41, "device": "M4", "job": "JM", "kind": "purchase", "currency": "JPY", "d_balance": -100, "d_held": 0}])
        try:
            wallets.save("M4", "apple04@example.com", "CHF"); ok(False, "đổi loại tiền khi khoản vừa áp chưa được gateway xác nhận → từ chối")
        except wallets.WalletError as e:
            ok("chưa xác nhận" in str(e), "đổi loại tiền khi khoản vừa áp chưa được gateway xác nhận → từ chối", str(e))
        ok(wallets.rename("M3", "M3-moi") and wallets.get("M3") is None and wallets.get("M3-moi")["balance"] == 1200000
           and wallets.apple("M3-moi")["account"] == "apple03@example.com", "máy đổi tên → ví + sổ đi theo sang tên mới")
        with open(os.path.join(tmp, "wallets.json"), "w", encoding="utf-8") as f:
            f.write('{"wallets": {"M3-moi": ')                       # tệp dở (mất điện)
        try:
            wallets.save("M9", "x@example.com", "JPY"); ok(False, "tệp ví hỏng → từ chối ghi")
        except wallets.WalletError as e:
            ok("khôi phục" in str(e) and open(os.path.join(tmp, "wallets.json"), encoding="utf-8").read().startswith('{"wallets": {"M3-moi"'),
               "tệp ví hỏng → báo lỗi, KHÔNG ghi đè (không xoá sạch ví + mật khẩu đã lưu)", str(e))

        print("== 9. Gói «1 lần»: giá yên, máy ở sai màn hình, thiếu mật khẩu Apple ID ==")
        yen = [L("500", 200, 300), L("¥160", 200, 420), L("Remaining: 1", 200, 460, 120), L("500", 800, 300), L("¥320", 800, 420)]
        ok(stepexec.once_left_in_card(yen, (200, 300), left, (1334, 750)), "giá «¥160» không bị coi là số coin của ô khác → «Remaining: 1» vẫn thuộc đúng ô")
        f6 = mk([L("Trang chủ", 600, 100), L("Sự kiện", 600, 200)])
        f6.pool = {"rules": [], "packages": [{"code": "coin_500", "ocr_text": "500"}, {"code": "sale_500", "ocr_text": "500"}]}
        r6 = f6._once_left(item, pv)
        ok(r6[0] is None and "màn hình khác" in r6[1], "không thấy cửa hàng (máy ở màn hình khác) → lỗi máy, KHÔNG báo khách «đã mua»", r6)
        f7 = mk([L("500", 800, 300), L("CHF 3.80", 800, 420)])
        f7.pool = {"rules": [], "packages": [{"code": "coin_500", "ocr_text": "500"}, {"code": "sale_500", "ocr_text": "500"}]}
        ok(f7._once_left(item, pv)[0] is False, "đang ở cửa hàng (thấy ô gói khác) mà không có ô sale 500 → «đã mua rồi»")
        st8 = {"purchase": [{"type": "tap_text", "text": "{{package.ocr_text}}"}, {"type": "type", "text": "{{apple.password}}"}], "login": [], "finish": []}
        f8 = jobflow.JobFlow(Nv([]), None, {"id": "J8", "items": [item], "login": {"username": "k@example.com", "apple.password": "cua-khach"}}, {"rules": []}, st8)
        jobflow.validate, real_validate = (lambda pool, st: []), jobflow.validate
        try:
            try:
                f8._flow(); ok(False, "thiếu mật khẩu Apple ID → dừng trước khi đăng nhập")
            except stepexec.ConfigError as e:
                ok("apple.password" in str(e), "bước mua cần {{apple.password}} mà máy chưa lưu → dừng NGAY trước khi đăng nhập (trường «apple.password» của khách không thay được)", str(e))
        finally:
            jobflow.validate = real_validate
    finally:
        store.DATA_DIR = real
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
