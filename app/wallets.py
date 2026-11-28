#!/usr/bin/env python3
"""
wallets.py — VÍ của từng máy nạp, do TOOL quản lý (nguồn gốc; gateway chỉ giữ bản sao).

Mỗi máy (tên máy trong tool) trả tiền mua gói bằng MỘT tài khoản Apple đăng nhập trên máy, ở MỘT loại tiền (vùng App Store):
  - wallets.json        : {"wallets": {máy: {apple_account, currency, active, note, pw}}, "applied": [id sự kiện gateway đã áp], "acks": [id chờ báo]}
                           `pw` = mật khẩu Apple ID ĐÃ MÃ HOÁ (Fernet, khoá ở secret.key cạnh đó) — chỉ để gõ vào bảng mua của App Store.
  - wallet-ledger.jsonl : SỔ CHỈ GHI THÊM, mỗi dòng một việc: {t, machine, kind, currency, d_balance, d_held, note, job, event, actor}
                           số dư = tổng d_balance, đang tạm giữ = tổng d_held (×100, số nguyên), theo đúng loại tiền của dòng.
Tiền của từng ĐƠN (mua / tạm giữ / admin chốt / hoàn) do gateway tính và gửi về thành sự kiện qua /api/tool/sync (`wallet_events`):
tool áp MỖI id MỘT lần (nhớ trong `applied`), rồi báo lại trong `wallet_acks` ở lần đồng bộ sau. Nạp tiền / chỉnh số dư thì làm ở tool.
Khi xin đơn, tool gửi «loại tiền + còn dùng được» (claim_info) — gateway tự trừ thêm các khoản tool chưa kịp nhận.

Mật khẩu Apple ID KHÔNG BAO GIỜ ra khỏi máy tính này: không gửi gateway / Telegram / AI, không trả về giao diện (chỉ «có / chưa có»).
"""
from __future__ import annotations
import contextlib, json, os, re, threading, time

import store

def _p(name: str) -> str:
    return os.path.join(store.DATA_DIR, name)        # tính lại mỗi lần: bài thử đổi thư mục dữ liệu thì ví đi theo


ZERO_DECIMAL = ("JPY", "KRW", "VND", "IDR", "CLP", "TWD", "HUF", "ISK")
MAX = 100_000_000_000_000          # giống gateway (Money::MAX)
APPLIED_KEEP = 5000                 # nhớ bấy nhiêu id sự kiện gần nhất đã áp (gateway chỉ gửi lại sự kiện CHƯA ack)
EVENT_KINDS = ("purchase", "hold", "release", "charge", "refund")
KINDS = {"topup": "Nạp tiền", "adjust": "Chỉnh số dư", "purchase": "Mua gói", "hold": "Tạm giữ", "release": "Nhả tạm giữ",
         "charge": "Trừ khi đối soát", "refund": "Hoàn tiền đơn"}
_lock = threading.RLock()
_held = threading.local()


@contextlib.contextmanager
def _flock():
    """Khoá GHI ví cho cả tiến trình lẫn giữa các tiến trình (app cửa sổ + bản web cùng mở): mọi «đọc–sửa–ghi» wallets.json và mọi lần
    ghi sổ đi qua đây. Gọi lồng nhau trong cùng luồng thì không khoá lại."""
    with _lock:
        if getattr(_held, "n", 0):
            _held.n += 1
            try:
                yield
            finally:
                _held.n -= 1
            return
        path = _p("wallets.lock")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        f = open(path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                while True:
                    try:
                        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                        break
                    except OSError:
                        time.sleep(0.05)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            _held.n = 1
            try:
                yield
            finally:
                _held.n = 0
                if os.name == "nt":
                    import msvcrt
                    try:
                        f.seek(0)
                        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


class WalletError(Exception):
    """Lỗi người dùng nhập (câu tiếng Việt hiện được ngay)."""


# ---------- tiền ----------
def currency(v) -> str | None:
    c = str(v or "").strip().upper()
    return c if re.fullmatch(r"[A-Z]{3}", c) else None


def parse_money(raw, cur: str, signed: bool = False) -> int | None:
    """Chữ người nhập → số tiền ×100 (đúng luật của gateway, Money::parse): «1500», «1.500», «1,500.50», «1.500,50», «63,5»…
    Một dấu chấm / phẩy kèm 1–2 chữ số sau = phần lẻ; nhóm đúng 3 chữ số = dấu nghìn; tiền không phần lẻ (JPY…) mà có lẻ → sai."""
    s = str(raw if raw is not None else "").strip()
    for ch in (" ", " ", " ", "'", "_"):
        s = s.replace(ch, "")
    neg = False
    if s[:1] in ("-", "+"):
        if not signed:
            return None
        neg, s = s[0] == "-", s[1:]
    if not re.fullmatch(r"\d[\d.,]*\d|\d", s):
        return None
    dot, comma = s.rfind("."), s.rfind(",")
    int_part, frac = s, ""
    if dot >= 0 and comma >= 0:
        pos = max(dot, comma)
        int_part, frac = s[:pos], s[pos + 1:]
        if s[pos] in int_part:
            return None
    elif dot >= 0 or comma >= 0:
        parts = s.split("." if dot >= 0 else ",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            int_part, frac = parts
        elif any(len(g) != 3 for g in parts[1:]):
            return None
    int_part = int_part.replace(".", "").replace(",", "")
    if not int_part or len(int_part) > 13 or len(frac) > 2 or not int_part.isdigit() or (frac and not frac.isdigit()):
        return None
    cents = int(frac.ljust(2, "0")) if frac else 0
    if cents and cur.upper() in ZERO_DECIMAL:
        return None
    v = int(int_part) * 100 + cents
    if v > MAX:
        return None
    return -v if neg else v


def fmt(x100, cur) -> str:
    """40000000 JPY → «400.000 JPY», 80 CHF → «0,80 CHF» (giống thông báo của tool / gateway)."""
    try:
        v = int(x100)
    except (TypeError, ValueError):
        return "?"
    cur = str(cur or "").upper()
    neg, v = v < 0, abs(v)
    whole, part = divmod(v, 100)
    s = "{:,}".format(whole).replace(",", ".")
    if cur not in ZERO_DECIMAL:
        s += ",%02d" % part
    return ("-" if neg else "") + s + (" " + cur if cur else "")


def mask(acc: str) -> str:
    """apple01@example.com → a***@example.com (ghi nhật ký máy / gửi Telegram)."""
    acc = str(acc or "").strip()
    at = acc.rfind("@")
    if at > 0:
        return acc[0] + "***" + acc[at:]
    return "*" * len(acc) if len(acc) <= 4 else acc[:2] + "***" + acc[-2:]


# ---------- mã hoá mật khẩu Apple ID ----------
def _fernet():
    from cryptography.fernet import Fernet
    with _flock():                          # hai tiến trình cùng tạo khoá lần đầu → chỉ MỘT khoá (khác khoá là không giải mã được)
        if not os.path.exists(_p('secret.key')):
            os.makedirs(os.path.dirname(_p('secret.key')), exist_ok=True)
            tmp = _p('secret.key') + ".tmp"
            with open(tmp, "wb") as f:
                f.write(Fernet.generate_key())
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, _p('secret.key'))
        with open(_p('secret.key'), "rb") as f:
            return Fernet(f.read().strip())


def _enc(text: str) -> str:
    return _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def _dec(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except Exception:
        return None                 # khoá đổi / tệp hỏng → coi như chưa có mật khẩu (không đoán)


# ---------- tệp ----------
def _load() -> dict:
    path = _p('wallets.json')
    if not os.path.exists(path):
        d = {}
    else:
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError) as e:
            # tệp hỏng (mất điện giữa lúc ghi…): KHÔNG coi là rỗng — lần ghi sau sẽ xoá sạch ví + mật khẩu đã lưu
            raise WalletError("Tệp ví (app/data/wallets.json) đọc không được (%s) — khôi phục từ bản sao lưu rồi mở lại app." % e)
        if not isinstance(d, dict):
            raise WalletError("Tệp ví (app/data/wallets.json) sai dạng — khôi phục từ bản sao lưu rồi mở lại app.")
    d.setdefault("wallets", {})
    d.setdefault("applied", [])
    d.setdefault("acks", [])
    return d


def _save(d: dict):
    path = _p('wallets.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())                 # ghi hẳn xuống đĩa rồi mới thay tệp cũ (mất điện không để lại tệp dở)
    try:
        os.chmod(tmp, 0o600)                 # có mật khẩu Apple ID (đã mã hoá) → chỉ chủ máy đọc được
    except OSError:
        pass
    _replace(tmp, path)


def _replace(tmp: str, path: str):
    """os.replace có thử lại: trên Windows tệp đích đang được tiến trình khác mở (đọc) thì báo WinError 5 trong chốc lát."""
    for i in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == 19:
                raise WalletError("Không ghi được tệp ví (đang bị chương trình khác giữ) — thử lại sau ít giây.")
            time.sleep(0.05)


def _ledger() -> list:
    out = []
    try:
        with open(_p('wallet-ledger.jsonl'), "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict):
                    out.append(e)
    except OSError:
        pass
    return out


def _append(entry: dict):
    os.makedirs(os.path.dirname(_p('wallet-ledger.jsonl')), exist_ok=True)
    with open(_p('wallet-ledger.jsonl'), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    try:
        os.chmod(_p('wallet-ledger.jsonl'), 0o600)
    except OSError:
        pass


def _totals(entries, machine: str, cur: str) -> tuple:
    bal = held = 0
    for e in entries:
        if e.get("machine") == machine and e.get("currency") == cur:
            bal += int(e.get("d_balance") or 0)
            held += int(e.get("d_held") or 0)
    return bal, held


# ---------- đọc ----------
def get(machine: str) -> dict | None:
    """Ví của máy (không kèm mật khẩu — chỉ `has_password`), kèm số dư / tạm giữ / còn dùng được; chưa khai → None."""
    with _lock:
        w = _load()["wallets"].get(machine)
        if not w:
            return None
        bal, held = _totals(_ledger(), machine, w["currency"])
    return _view(machine, w, bal, held)


def _view(machine, w, bal, held) -> dict:
    return {"machine": machine, "apple_account": w.get("apple_account") or "", "currency": w["currency"], "active": bool(w.get("active", True)),
            "note": w.get("note") or "", "has_password": bool(w.get("pw")), "balance": bal, "held": held, "available": bal - held,
            "balance_text": fmt(bal, w["currency"]), "held_text": fmt(held, w["currency"]), "available_text": fmt(bal - held, w["currency"])}


def all_wallets() -> list:
    with _lock:
        d = _load()
        entries = _ledger()
        return [_view(m, w, *_totals(entries, m, w["currency"])) for m, w in sorted(d["wallets"].items())]


def ledger(machine: str, limit: int = 200) -> list:
    """Các dòng sổ của máy, mới nhất trước."""
    out = [dict(e, kind_label=KINDS.get(e.get("kind"), e.get("kind")),
                d_balance_text=fmt(e.get("d_balance") or 0, e.get("currency")) if e.get("d_balance") else "",
                d_held_text=fmt(e.get("d_held") or 0, e.get("currency")) if e.get("d_held") else "")
           for e in _ledger() if e.get("machine") == machine]
    return out[::-1][:max(1, int(limit))]


def claim_info(machine: str) -> dict | None:
    """Gửi kèm khi máy xin đơn: {currency, available, applied} — máy chưa có ví đang dùng → None (nhận đơn không kiểm tiền).
    `available` tính ĐỦ mọi dòng sổ; `applied` = id các sự kiện tiền của đơn tool ĐÃ áp vào sổ (gần nhất) → gateway chỉ cộng thêm các sự kiện
    tool CHƯA áp. Không phụ thuộc lời «đã áp» đã tới gateway hay chưa (mất phản hồi đồng bộ, lưu tệp hỏng giữa chừng): không khoản nào bị
    tính hai lần hay bỏ sót."""
    with _lock:
        d = _load()
        w = d["wallets"].get(machine)
        if not w or not w.get("active", True):
            return None
        bal = held = 0
        ids = []
        for e in _ledger():
            if e.get("machine") != machine:
                continue
            if isinstance(e.get("event"), int):
                ids.append(e["event"])
            if e.get("currency") == w["currency"]:
                bal += int(e.get("d_balance") or 0)
                held += int(e.get("d_held") or 0)
    return {"currency": w["currency"], "available": bal - held, "applied": ids[-300:]}


def apple(machine: str) -> dict:
    """Tài khoản + mật khẩu Apple ID của máy để GÕ vào bảng mua ({{apple.account}} / {{apple.password}}). Chỉ dùng trong bộ chạy đơn."""
    with _lock:
        w = _load()["wallets"].get(machine) or {}
    out = {}
    if w.get("apple_account"):
        out["account"] = w["apple_account"]
    if w.get("pw"):
        pw = _dec(w["pw"])
        if pw is not None:
            out["password"] = pw
    return out


def report() -> list:
    """Bản sao ví gửi gateway (sync). KHÔNG có mật khẩu."""
    return [{"device": w["machine"], "apple_account": w["apple_account"], "currency": w["currency"], "balance": w["balance"],
             "held": w["held"], "active": w["active"], "note": w["note"]} for w in all_wallets()]


# ---------- ghi ----------
def save(machine: str, apple_account: str, cur: str, note: str = "", active: bool = True, password: str | None = None,
         clear_password: bool = False) -> dict:
    """Khai / sửa ví của máy. `password` None hoặc rỗng = giữ mật khẩu cũ; clear_password=True = xoá mật khẩu.
    Đổi loại tiền khi ví còn tiền / đang tạm giữ → lỗi (đưa số dư về 0 trước, không thì số dư hai loại tiền lẫn nhau)."""
    machine = str(machine or "").strip()[:80]
    if not machine:
        raise WalletError("Chưa chọn máy.")
    acc = str(apple_account or "").strip()[:160]
    if not acc:
        raise WalletError("Chưa nhập tài khoản Apple đăng nhập trên máy.")
    c = currency(cur)
    if not c:
        raise WalletError("Loại tiền phải là mã ISO 3 chữ cái (vd JPY, CHF, USD).")
    with _flock():
        d = _load()
        old = d["wallets"].get(machine)
        if old and old["currency"] != c:
            pend = set(int(x) for x in d["acks"] if isinstance(x, int))
            if any(e.get("machine") == machine and e.get("event") in pend for e in _ledger()):
                raise WalletError("Ví vừa nhận tiền của đơn mà gateway chưa xác nhận — chờ vài giây (đồng bộ xong) rồi mới đổi loại tiền.")
            bal, held = _totals(_ledger(), machine, old["currency"])
            if bal or held:
                raise WalletError("Ví còn %s (tạm giữ %s) theo %s — chỉnh số dư về 0 trước rồi mới đổi loại tiền."
                                  % (fmt(bal, old["currency"]), fmt(held, old["currency"]), old["currency"]))
        w = dict(old or {})
        w.update(apple_account=acc, currency=c, note=str(note or "").strip()[:200], active=bool(active))
        if clear_password:
            w.pop("pw", None)
        elif password:
            w["pw"] = _enc(str(password))
        d["wallets"][machine] = w
        _save(d)
    return get(machine)


def remove(machine: str) -> bool:
    """Bỏ ví của máy (sổ giữ nguyên để tra). Ví còn tiền tạm giữ → lỗi (đơn đang chờ đối soát còn tính vào ví này)."""
    with _flock():
        d = _load()
        w = d["wallets"].get(machine)
        if not w:
            return False
        _, held = _totals(_ledger(), machine, w["currency"])
        if held:
            raise WalletError("Ví đang tạm giữ %s cho đơn chờ đối soát — chờ admin chốt đơn đó rồi mới bỏ ví." % fmt(held, w["currency"]))
        del d["wallets"][machine]
        _save(d)
    return True


def rename(old: str, new: str) -> bool:
    """Máy đổi tên (board đổi tên): ví + các dòng sổ đi theo máy sang tên mới (không thì máy mất kiểm tiền, tiền của đơn rơi vào ví mồ côi)."""
    old, new = str(old or "").strip(), str(new or "").strip()[:80]
    if not old or not new or old == new:
        return False
    with _flock():
        d = _load()
        if old not in d["wallets"] or new in d["wallets"]:
            return False
        entries = _ledger()
        for e in entries:
            if e.get("machine") == old:
                e["machine"] = new
        path = _p('wallet-ledger.jsonl')
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:            # sổ mới viết sẵn ra tệp tạm trước
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        d["wallets"][new] = d["wallets"].pop(old)
        _save(d)
        try:
            _replace(tmp, path)
        except Exception:
            d["wallets"][old] = d["wallets"].pop(new)          # thay sổ không được → trả ví về tên cũ (ví và sổ luôn cùng một tên)
            _save(d)
            raise
    return True


def topup(machine: str, raw_amount, note: str = "", actor: str = "tool") -> dict:
    with _flock():
        w = get(machine)
        if not w:
            raise WalletError("Máy này chưa có ví.")
        amount = parse_money(raw_amount, w["currency"])
        if amount is None or amount <= 0:
            raise WalletError("Số tiền nạp không hợp lệ" + (" (%s không có phần lẻ)." % w["currency"] if w["currency"] in ZERO_DECIMAL else "."))
        _append({"t": time.time(), "machine": machine, "kind": "topup", "currency": w["currency"], "d_balance": amount, "d_held": 0,
                 "note": str(note or "").strip()[:300] or "Nạp thêm tiền", "actor": actor})
    return get(machine)


def adjust(machine: str, raw_amount, note: str, actor: str = "tool") -> dict:
    with _flock():
        w = get(machine)
        if not w:
            raise WalletError("Máy này chưa có ví.")
        amount = parse_money(raw_amount, w["currency"], signed=True)
        if amount is None or amount == 0:
            raise WalletError("Số tiền chỉnh phải khác 0 (âm = bớt, dương = thêm).")
        note = str(note or "").strip()[:300]
        if not note:
            raise WalletError("Chỉnh số dư bắt buộc ghi lý do.")
        _append({"t": time.time(), "machine": machine, "kind": "adjust", "currency": w["currency"], "d_balance": amount, "d_held": 0,
                 "note": note, "actor": actor})
    return get(machine)


# ---------- sự kiện tiền của đơn (từ gateway) ----------
def apply_events(events) -> int:
    """Áp các sự kiện gateway gửi (mỗi id MỘT lần — gửi lại / trùng thì bỏ qua). Mọi id hợp lệ đều được đưa vào hàng «chờ báo đã nhận».
    Trả số sự kiện vừa áp mới."""
    if not isinstance(events, list):
        return 0
    n = 0
    with _flock():
        d = _load()
        # SỔ là bằng chứng «đã áp»: id nào đã có dòng trong sổ thì không áp lại — kể cả khi lần lưu danh sách `applied` trước đó hỏng
        # (tiến trình chết / tệp bị khoá giữa lúc ghi sổ và lúc lưu) — không bao giờ trừ / hoàn hai lần
        applied = set(int(x) for x in d["applied"] if isinstance(x, int)) | {int(e["event"]) for e in _ledger() if isinstance(e.get("event"), int)}
        acks = [int(x) for x in d["acks"] if isinstance(x, int)]
        for e in events:
            if not isinstance(e, dict) or not isinstance(e.get("id"), int):
                continue
            eid = e["id"]
            if eid not in acks:
                acks.append(eid)
            if eid in applied:
                continue
            kind, cur = e.get("kind"), currency(e.get("currency"))
            machine = str(e.get("device") or "").strip()[:80]
            db, dh = e.get("d_balance"), e.get("d_held")
            if kind not in EVENT_KINDS or not cur or not machine or not isinstance(db, int) or not isinstance(dh, int):
                continue        # sự kiện lạ: không áp (vẫn báo đã nhận để gateway không gửi mãi) — không đoán
            _append({"t": time.time(), "machine": machine, "kind": kind, "currency": cur, "d_balance": db, "d_held": dh,
                     "note": str(e.get("note") or "")[:300], "job": str(e.get("job") or "")[:24] or None,
                     "package": e.get("package_code"), "qty": e.get("qty") if isinstance(e.get("qty"), int) else None,
                     "event": eid, "actor": "gateway"})
            applied.add(eid)
            d["applied"].append(eid)
            n += 1
        d["applied"] = d["applied"][-APPLIED_KEEP:]
        d["acks"] = acks[-2000:]
        _save(d)
    return n


def pending_acks() -> list:
    with _lock:
        return [int(x) for x in _load()["acks"] if isinstance(x, int)]


def acked(ids) -> None:
    """Gateway đã nhận lời «đã áp» cho các id này → bỏ khỏi hàng chờ báo."""
    done = set(int(x) for x in ids or [] if isinstance(x, int))
    if not done:
        return
    with _flock():
        d = _load()
        d["acks"] = [x for x in d["acks"] if x not in done]
        _save(d)
