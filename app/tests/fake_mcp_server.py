#!/usr/bin/env python3
"""
Máy chủ MCP chạy trên MÁY GIẢ (không cần iPhone) — để thử một client MCP bất kỳ với đúng code giao thức của app:

    ./.venv/bin/python app/tests/fake_mcp_server.py stdio
    ./.venv/bin/python app/tests/fake_mcp_server.py http 47950 khoa-thu

Dùng bởi app/tests/interop_sdk.py (kiểm chéo với client của SDK MCP chính thức).
"""
from __future__ import annotations
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import control, mcpserver
import test_mcp as M


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    host, c, server = M.rig()
    M.CURRENT[0] = host.games["iPhoneFarm-01"]
    control.ocr_lines = lambda img, **kw: M.fake_lines(M.CURRENT[0].text())
    if mode == "stdio":
        mcpserver.serve_stdio(server)
        return 0
    httpd, port = mcpserver.serve_http(server, sys.argv[3], int(sys.argv[2]), tries=1)
    print("http %d" % port, file=sys.stderr, flush=True)
    try:
        while True:
            M.REAL_SLEEP(3600)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
