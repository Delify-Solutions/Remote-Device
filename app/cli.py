#!/usr/bin/env python3
"""
cli.py — điều khiển iPhone Farm bằng DÒNG LỆNH, và chạy máy chủ MCP để AI kết nối.

    ./farm devices                              danh sách máy
    ./farm screen iPhoneFarm-01                 chụp màn hình + đọc chữ kèm toạ độ (ảnh lưu vào shots/)
    ./farm tap iPhoneFarm-01 288 468            bấm vào toạ độ
    ./farm tap iPhoneFarm-01 --text "Cài đặt"   bấm vào chữ
    ./farm type iPhoneFarm-01 "hello" --enter   gõ chữ rồi Enter
    ./farm swipe iPhoneFarm-01 left             vuốt sang trái (trang sau)
    ./farm run iPhoneFarm-01 @steps.json        chạy một chuỗi bước
    ./farm status                               các máy đang làm gì + nhật ký
    ./farm tools                                mọi lệnh có thể dùng
    ./farm mcp                                  máy chủ MCP qua stdio (AI tự chạy lệnh này)
    ./farm mcp-config                           in sẵn cấu hình cho Claude Code / Claude Desktop / Cursor

App iPhone Farm Manager đang mở thì lệnh được chuyển cho app thực hiện; chưa mở thì CLI tự mở cổng của board.
Thêm --json để lấy kết quả dạng JSON (cho script).
"""
from __future__ import annotations
import argparse, base64, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import control
from mcpserver import McpServer, serve_stdio

VERSION = "1.0.0"


def _convert(prop: dict, raw):
    """Chuỗi gõ ở dòng lệnh → giá trị đúng kiểu của tham số."""
    t = prop.get("type")
    if t == "integer":
        return int(raw)
    if t == "number":
        return float(str(raw).replace(",", "."))
    if t in ("array", "object"):
        if isinstance(raw, str) and raw.startswith("@"):
            with open(raw[1:], "r", encoding="utf-8") as f:
                return json.load(f)
        return json.loads(raw)
    return raw


def build_parser(tools) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="farm", description="Điều khiển iPhone Farm bằng dòng lệnh / kết nối AI qua MCP.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--json", action="store_true", help="in kết quả dạng JSON")
    ap.add_argument("--out", help="nơi lưu ảnh chụp (mặc định: shots/<máy>-<giờ>.jpg)")
    ap.add_argument("--local", action="store_true", help="không gọi sang app đang mở, tự mở cổng của board")
    # ba cờ chung đặt TRƯỚC hay SAU tên lệnh đều được:  farm --json devices  ==  farm devices --json
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="in kết quả dạng JSON")
    common.add_argument("--out", default=argparse.SUPPRESS, help="nơi lưu ảnh chụp")
    common.add_argument("--local", action="store_true", default=argparse.SUPPRESS, help="không gọi sang app đang mở")
    sub = ap.add_subparsers(dest="cmd", metavar="<lệnh>")
    for t in tools:
        p = sub.add_parser(t.cli, help=t.help, description="%s\n\n(công cụ MCP: %s)" % (t.help, t.name), parents=[common],
                           formatter_class=argparse.RawDescriptionHelpFormatter)
        for name in t.positional:
            p.add_argument("pos_" + name, nargs="?", metavar=name, help=t.properties[name].get("description", ""))
        for name, prop in t.properties.items():
            flag = "--" + name.replace("_", "-")
            if prop.get("type") == "boolean":
                p.add_argument(flag, dest=name, action=argparse.BooleanOptionalAction, default=None, help=prop.get("description", ""))
            else:
                p.add_argument(flag, dest=name, default=None, help=prop.get("description", ""))
    sub.add_parser("tools", help="liệt kê mọi lệnh/công cụ")
    sub.add_parser("mcp", help="chạy máy chủ MCP qua stdio (để AI kết nối)")
    cfg = sub.add_parser("mcp-config", help="in cấu hình kết nối cho Claude Code / Claude Desktop / Cursor")
    cfg.add_argument("--show-token", action="store_true", help="in cả khoá của cầu nối HTTP (mặc định che đi)")
    return ap


def known_devices() -> set:
    """Tên + nhãn các máy đã khai (đọc tệp cấu hình tại chỗ, không đụng board) — để biết ô đầu có phải tên máy không."""
    try:
        import store
        from eyes import norm_text
        return {norm_text(v) for d in store.get_devices() for v in (d.get("name"), d.get("label")) if v}
    except Exception:
        return set()


def collect(tool, ns, devices=None) -> dict:
    """Gom tham số của một lệnh từ các ô theo vị trí + các cờ --tên.
    Lệnh nhận «máy» ở ô đầu: nếu ô đầu KHÔNG phải tên một máy đã khai thì coi như bỏ trống tên máy và dịch các ô
    sang phải —  `farm find Safari`, `farm type hello`, `farm tap 288 468`  (dùng khi chỉ có một máy sẵn sàng)."""
    given = [getattr(ns, "pos_" + n, None) for n in tool.positional]
    if tool.positional[:1] == ("device",) and given and given[0] is not None and len(tool.positional) > 1:
        from eyes import norm_text
        names = known_devices() if devices is None else {norm_text(x) for x in devices}
        if norm_text(given[0]) not in names and given[-1] is None:
            moved = [None] + given[:-1]
            try:                                # chỉ dịch khi các ô sau khi dịch vẫn đúng kiểu (vd x, y phải là số)
                for n, v in zip(tool.positional, moved):
                    if v is not None:
                        _convert(tool.properties[n], v)
            except (ValueError, OSError):
                moved = None
            if moved is not None:
                for n, v in zip(tool.positional, moved):
                    setattr(ns, "pos_" + n, v)
    args = {}
    for name, prop in tool.properties.items():
        pos = getattr(ns, "pos_" + name, None) if name in tool.positional else None
        opt = getattr(ns, name, None)
        if pos is not None and opt is not None:
            raise SystemExit("farm %s: «%s» được nêu hai lần (theo vị trí và bằng --%s)" % (tool.cli, name, name.replace("_", "-")))
        raw = pos if pos is not None else opt
        if raw is None:
            continue
        try:
            args[name] = raw if isinstance(raw, bool) else _convert(prop, raw)
        except (ValueError, OSError) as e:
            raise SystemExit("farm %s: giá trị của «%s» không hợp lệ (%s)" % (tool.cli, name, e))
    return args


def emit(tool, out: dict, ns) -> int:
    """In kết quả một công cụ ra màn hình; ảnh thì lưu thành tệp."""
    saved = []
    for c in out.get("content") or []:
        if c.get("type") == "image":
            dev = ((out.get("structuredContent") or {}).get("device") or "may").replace("/", "_")
            path = ns.out or os.path.join(ROOT, "shots", "%s-%s.jpg" % (dev, time.strftime("%H%M%S")))
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "wb") as f:
                f.write(base64.b64decode(c["data"]))
            saved.append(os.path.abspath(path))
    texts = [c.get("text", "") for c in out.get("content") or [] if c.get("type") == "text"]
    if ns.json:
        print(json.dumps({"ok": not out.get("isError"), "text": "\n".join(texts), "data": out.get("structuredContent"),
                          "images": saved}, ensure_ascii=False, indent=2))
    else:
        stream = sys.stderr if out.get("isError") else sys.stdout
        for t in texts:
            print(("LỖI: " if out.get("isError") else "") + t, file=stream)
        for p in saved:
            print("Ảnh: " + p)
    return 1 if out.get("isError") else 0


def mcp_config(show_token: bool = False) -> str:
    farm = os.path.join(ROOT, "farm.bat" if os.name == "nt" else "farm")      # Windows: farm.bat (./farm là script sh)
    lines = ["KẾT NỐI AI VỚI IPHONE FARM (MCP)", "",
             "1) Claude Code — chạy một lần trong terminal:",
             "     claude mcp add iphone-farm -- %s mcp" % farm, "",
             "2) Claude Desktop / Cursor / client khác — thêm vào tệp cấu hình MCP:",
             json.dumps({"mcpServers": {"iphone-farm": {"command": farm, "args": ["mcp"]}}}, ensure_ascii=False, indent=2), ""]
    ep = control.load_endpoint()
    live = control.remote(timeout=5) is not None
    if ep and live:
        tk = ep["token"] if show_token else "<khoá>"
        lines += ["3) Nối thẳng qua HTTP tới app đang mở (không cần chạy lệnh nào):",
                  "     địa chỉ:  http://127.0.0.1:%d/mcp" % ep["port"],
                  "     tiêu đề:  Authorization: Bearer %s" % tk,
                  "     Claude Code:  claude mcp add --transport http iphone-farm-http http://127.0.0.1:%d/mcp --header \"Authorization: Bearer %s\"" % (ep["port"], tk),
                  "" if show_token else "     (khoá: xem / copy ở mục «Kết nối AI» trong app, hoặc chạy  farm mcp-config --show-token)", ""]
    else:
        lines += ["3) Nối thẳng qua HTTP: mở app iPhone Farm Manager rồi chạy lại lệnh này để xem địa chỉ + khoá.", ""]
    lines += ["Trạng thái: app %s." % ("ĐANG MỞ — lệnh của AI/CLI sẽ do app thực hiện" if live else "chưa mở — AI/CLI sẽ tự mở cổng của board"),
              "Lưu ý: khoá ở mục 3 cho phép điều khiển máy — đừng chia sẻ."]
    return "\n".join(lines)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    tools, host = control.proxied_tools()
    ap = build_parser(tools)
    ns = ap.parse_args(argv)
    if ns.local:
        os.environ["FARM_LOCAL"] = "1"
    if not ns.cmd:
        ap.print_help()
        return 0
    if ns.cmd == "tools":
        for t in tools:
            print("%-8s %s   (MCP: %s)" % (t.cli, t.help, t.name))
        return 0
    if ns.cmd == "mcp-config":
        print(mcp_config(getattr(ns, "show_token", False)))
        return 0
    server = McpServer(tools, version=VERSION, instructions=control.INSTRUCTIONS)
    if ns.cmd == "mcp":
        try:
            serve_stdio(server)
        finally:
            host.close()
        return 0
    tool = next(t for t in tools if t.cli == ns.cmd)
    try:
        return emit(tool, server.call(tool, collect(tool, ns)), ns)
    finally:
        host.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
