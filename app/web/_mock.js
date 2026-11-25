// _mock.js — giả lập window.pywebview.api để render thử giao diện trong trình duyệt.
// CHỈ dùng để test UI, không ảnh hưởng app thật.
(function () {
  const P = (v) => new Promise((res) => setTimeout(() => res(v), 120));
  const SMALL_PNG =
    "data:image/svg+xml;utf8," + encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" width="375" height="667"><rect width="100%" height="100%" fill="#223"/><text x="50%" y="50%" fill="#8af" font-size="26" text-anchor="middle">MOCK SCREEN</text></svg>'
    );
  let DEVICES = [
    { name: "iPhoneFarm-01", udid: "1111aaaa2222bbbb3333cccc4444dddd5555eeee", label: "Máy 01", configured: true, ble: true,
      board_online: true, port: "/dev/cu.usbserial-0001", ios_connected: true, ios: "16.7.10", model: "iPhone 8", device_name: "iPhone 8 (demo)" },
    { name: "iPhoneFarm-02", udid: "6666ffff7777aaaa8888bbbb9999cccc0000dddd", label: "Máy 02", configured: true, ble: false,
      board_online: true, port: "/dev/cu.usbserial-5", ios_connected: false, ios: null, model: null, device_name: null },
    { name: "iPhoneFarm-03", udid: null, label: "iPhoneFarm-03", configured: false, ble: null,
      board_online: true, port: "/dev/cu.usbserial-7", ios_connected: false, ios: null, model: null, device_name: null },
  ];
  const BOARDS = [
    { port: "/dev/cu.usbserial-0001", chip_desc: "CP2102 (Silicon Labs)", vid: 0x10c4, pid: 0xea60, serial: "0001", flashed: true, name: "iPhoneFarm-01", ble: true,
      health: { level: "ok", summary: "RAM dùng 129 / 256 KB (51%) · chạy 14 phút · reset: poweron · BLE rớt 0", notes: [], fw: 3,
                ram_used: 132096, ram_total: 262144, ram_pct: 50, connected: true, bthold: 0 } },
    { port: "/dev/cu.usbserial-7", chip_desc: "CH340", vid: 0x1a86, pid: 0x7523, serial: null, flashed: false, name: null },
  ];
  const IOS = [
    { udid: "1111aaaa2222bbbb3333cccc4444dddd5555eeee", name: "iPhone 8 (demo)", model: "iPhone 8", product_type: "iPhone10,1", ios: "16.7.10", connection: "USB" },
    { udid: "aaaa1111bbbb2222cccc3333dddd4444eeee5555", name: "XS Max", model: "iPhone XS Max", product_type: "iPhone11,6", ios: "18.7", connection: "USB" },
  ];
  let FLOWS = [{ id: "demo1", name: "Mở eFootball", steps: [
    { type: "launch", app: "efootball" }, { type: "wait", seconds: 3 }, { type: "tap", x: 300, y: 500 },
  ], created: 0, updated: 0 }];
  let GROUPS = [
    { id: "g1", name: "iPhone 8 · 16.7", mode: "loop", loops: 0,
      devices: ["iPhoneFarm-01"], steps: [{ type: "home" }, { type: "wait", seconds: 2 }] },
    { id: "g2", name: "eFootball · nhận đơn", mode: "api", loops: 0, devices: ["iPhoneFarm-02"], steps: [],
      api: { pool: "efootball-ios", login_wait: 45, purchase_wait: 60, check_keyboard: true,
             steps: { login: [], otp: [], nav: [], purchase: [{ type: "tap", x: 320, y: 610 }, { type: "tap_text", text: "Mua" }], after: [], finish: [] } } },
  ];
  let GWCFG = { url: "https://gateway.example.com", key: "gwt_demo1234" };
  const GWPOOLS = [{ code: "efootball-ios", name: "eFootball (iOS) — Konami ID", game: "eFootball", active: true },
                   { code: "idv-asia", name: "Identity V (Asia)", game: "Identity V", active: false }];
  const GWPOOL = { ok: true, code: "efootball-ios", name: "eFootball (iOS) — Konami ID", active: true,
    steps: {
      login: [{ type: "launch", app: "efootball" }, { type: "wait_text", text: "Đăng nhập", timeout: 20 }, { type: "tap_text", text: "Đăng nhập" },
              { type: "type", text: "{{username}}" }, { type: "key", name: "tab" }, { type: "type", text: "{{password}}" }, { type: "key", name: "enter" }],
      otp: [], nav: [{ type: "tap_text", text: "Cửa hàng" }, { type: "tap_text", text: "eFootball Coins" }],
      purchase: [{ type: "tap_text", text: "{{package.ocr_text}}" }, { type: "tap_text", text: "Mua" }],
      after: [{ type: "tap_text", text: "OK" }], finish: [{ type: "tap_text", text: "Đăng xuất" }, { type: "home" }] },
    rules: [{ when: "logged_out", value: "Konami ID|Đăng nhập", note: "" }, { when: "login_success", value: "Trang chủ", note: "" }],
    packages: [{ code: "coin_1050", name: "1050 eFootball Coins" }],
    login_fields: [{ key: "username" }, { key: "password" }], otp: { enabled: true },
    missing_rules: ["Nạp gói THÀNH CÔNG"], required_phases: ["login", "purchase", "finish"] };
  let RUN = {};   // name -> {running, stopping, status, iter, last_ok, last_msg, group_id, mode, job, counts}
  function mockRun(g) {
    return g && g.mode === "api"
      ? { running: true, stopping: false, mode: "api", group_id: g.id, iter: 2, status: "NG261124A008 · Đang mua 1050 eFootball Coins (1/1)",
          job: "NG261124A008", last_ok: true, last_msg: "NG261124A007: HOÀN TẤT", counts: { done: 2, failed: 1, review: 0 } }
      : { running: true, stopping: false, mode: (g && g.mode) || "loop", group_id: g && g.id, iter: 1, status: "đang chạy · vòng 1",
          last_ok: true, last_msg: "2/2 bước OK", counts: { done: 0, failed: 0, review: 0 } };
  }
  function mockStop(n, force) {
    const r = RUN[n]; if (!r) return;
    if (r.mode === "api" && !force && !r.stopping) { r.stopping = true; return; }     // dừng thường: làm nốt đơn
    r.running = false; r.stopping = false; r.status = "đã dừng";
  }
  function syncGroupFields() {
    DEVICES.forEach(d => { d.group_id = null; d.group_name = null; d.running = !!(RUN[d.name] && RUN[d.name].running); });
    GROUPS.forEach(g => (g.devices || []).forEach(dn => { const d = DEVICES.find(x => x.name === dn); if (d) { d.group_id = g.id; d.group_name = g.name; } }));
  }
  syncGroupFields();

  const OV = {
    ok: true,
    system: { os: "macOS", os_raw: "Darwin", os_version: "25.5.0", arch: "arm64", python: "3.9.6",
      python_ok: true, venv: "/duong/dan/Remote-Device/.venv", has_brew: true, has_apt: false, has_winget: false },
    packages: [
      { name: "pymobiledevice3", desc: "Chụp màn hình + đọc thông tin iPhone", ok: true, version: "11.59.0" },
      { name: "pyserial", desc: "Điều khiển board ESP32 qua cổng serial", ok: true, version: "3.5" },
      { name: "opencv-python", desc: "Nhận diện nút/con trỏ trên ảnh", ok: true, version: "4.10.0" },
      { name: "numpy", desc: "Xử lý ảnh", ok: true, version: "2.0.2" },
      { name: "pillow", desc: "Đọc/ghi ảnh", ok: true, version: "11.3.0" },
      { name: "pytesseract", desc: "OCR đọc chữ trên màn", ok: false, version: null },
      { name: "pywebview", desc: "Giao diện app desktop", ok: true, version: "6.2.1" },
      { name: "esptool", desc: "Nạp/xoá firmware ESP32", ok: true, version: "4.14.0" },
    ],
    tools: [
      { name: "arduino-cli", desc: "Biên dịch + nạp firmware ESP32", ok: true, path: "/opt/homebrew/bin/arduino-cli", cmd: "brew install arduino-cli" },
      { name: "tesseract", desc: "Máy OCR đọc chữ trên màn hình", ok: false, path: null, cmd: "brew install tesseract tesseract-lang" },
      { name: "iproxy", desc: "Chuyển cổng USB iPhone (tuỳ chọn)", ok: true, path: "/opt/homebrew/bin/iproxy", cmd: "brew install libimobiledevice" },
    ],
    pkgs_ok: 7, pkgs_total: 8, tools_ok: 2, tools_total: 3,
  };
  // cầu nối AI (MCP) — số liệu giả để xem thử trang «Kết nối AI»
  const AI = { enabled: true, token: "tok-vidu-0123456789abcdefghij" };
  const AI_TOOLS = [["list_devices", "devices", "Danh sách máy: board, Bluetooth, iPhone, nhóm, đang chạy hay không", true],
    ["read_screen", "screen", "Chụp màn hình + đọc chữ kèm toạ độ", true], ["find_text", "find", "Tìm chữ trên màn hình → toạ độ", true],
    ["tap", "tap", "Bấm vào toạ độ (x y) hoặc vào chữ (--text)", false], ["swipe", "swipe", "Vuốt theo hướng hoặc theo toạ độ", false],
    ["type_text", "type", "Gõ chữ (chỉ ASCII) vào ô đang được chọn", false], ["farm_status", "status", "Trạng thái các máy + nhật ký chạy gần đây", true],
    ["start_run", "start", "Cho nhóm (hoặc một máy của nhóm) chạy", false], ["stop_run", "stop", "Dừng một máy (hoặc --group nhóm)", false]];
  const AIINFO = () => ({
    enabled: AI.enabled, running: AI.enabled, port: AI.enabled ? 47821 : null, token: AI.token, error: null,
    url: AI.enabled ? "http://127.0.0.1:47821/mcp" : null, farm: "/duong/dan/Remote-Device/farm", active: AI.enabled ? ["iPhoneFarm-01"] : [],
    claude_code: "claude mcp add iphone-farm -- /duong/dan/Remote-Device/farm mcp",
    json: JSON.stringify({ mcpServers: { "iphone-farm": { command: "/duong/dan/Remote-Device/farm", args: ["mcp"] } } }, null, 2),
    tools: AI_TOOLS.map(([name, cli, help, read_only]) => ({ name, cli, help, read_only })),
  });
  window.pywebview = { api: {
    sys_overview: () => P(OV),
    sys_install_pip: (n) => P({ ok: true, log: "Collecting pytesseract…\nSuccessfully installed pytesseract-0.3.13" }),
    sys_install_tool: (n) => P({ ok: true, log: "==> Pouring tesseract…\n🍺  tesseract installed" }),
    restart_app: () => P({ ok: true }),
    rescan: () => P({ ok: true, boards: { "iPhoneFarm-01": "/dev/cu.usbserial-0001" } }),
    list_devices: () => P(DEVICES),
    set_udid: (n, u, l) => P({ ok: true }),
    delete_device: (n) => { const i = DEVICES.findIndex(d => d.name === n); if (i >= 0) DEVICES.splice(i, 1); return P({ ok: true }); },
    esp_scan: () => {
      // mô phỏng backend streaming: trả ngay danh sách cổng (flashed=null),
      // rồi đẩy từng board về qua __espUpdate/__devBoard, kết thúc bằng __scanDone.
      const ports = BOARDS.map(b => ({ port: b.port, chip_desc: b.chip_desc, vid: b.vid, pid: b.pid, serial: b.serial, flashed: null, name: null }));
      BOARDS.forEach((b, i) => setTimeout(() => {
        window.__espUpdate && window.__espUpdate(Object.assign({}, b));
        window.__devBoard && window.__devBoard({ name: b.name, port: b.port, ble: b.ble });
      }, 600 + i * 900));
      setTimeout(() => window.__scanDone && window.__scanDone(BOARDS.length), 600 + BOARDS.length * 900 + 400);
      return P(ports);
    },
    esp_chip: (p) => P({ ok: true, chip: "ESP32-D0WD-V3", mac: "b4:a6:4a:72:05:e0" }),
    esp_flash: (p, n) => P({ ok: true, name: n, log: "Biên dịch…\nNạp…\n✓ Nạp xong, tên=" + n }),
    esp_erase: (p) => P({ ok: true, log: "Đã xoá sạch flash." }),
    ios_list: () => P(IOS),
    ios_check: (u) => P({ ok: true, udid: u, trusted: true, dev_mode: false, ddi: false, ready: false }),
    ios_pair: (u) => P({ ok: true, log: "Đã ghép nối." }),
    ios_enable_devmode: (u) => P({ ok: true, log: "Đã bật. Máy đang khởi động lại…" }),
    ios_reveal_devmode: (u) => P({ ok: true, log: "Đã hiện mục trong Cài đặt." }),
    ios_mount: (u) => P({ ok: true, log: "Đã mount DDI." }),
    probe_match: (name) => new Promise((res) => setTimeout(() => res({
      ok: true, board: name, udid: "1111aaaa2222bbbb3333cccc4444dddd5555eeee", label: "Máy 01",
      name: "iPhone 8 (demo)", model: "iPhone 8", ios: "16.7.10", shot: SMALL_PNG,
      ranked: [{ name: "iPhone 8 (demo)", udid: "1111aaaa…", score: 4210 }, { name: "XS Max", udid: "aaaa1111…", score: 60 }],
    }), 1500)),
    screenshot: (n) => P({ ok: true, img: SMALL_PNG, w: 375, h: 667 }),
    ble_status: (n) => P({ ok: true, status: "OK ble=connected", health: { level: "ok", summary: "RAM dùng 129 / 256 KB (51%) · chạy 14 phút · reset: poweron · BLE rớt 0", notes: [] } }),
    board_restart: (n) => P({ ok: true, msg: "Đã khởi động lại board " + n + " — iPhone đã nối lại Bluetooth." }),
    board_disconnect_bt: (n, hold) => P({ ok: true, msg: "Đã huỷ kết nối Bluetooth của board " + n + "; sau " + hold + " giây iPhone sẽ tự nối lại." }),
    run_step: (n, s) => P({ ok: true, msg: "test " + s.type + " OK" }),
    // ---- nhóm & chạy ----
    groups_list: () => P(JSON.parse(JSON.stringify(GROUPS))),
    group_save: (g) => { g = JSON.parse(JSON.stringify(g)); if (!g.id) g.id = "g" + Date.now(); const i = GROUPS.findIndex(x => x.id === g.id); if (i >= 0) GROUPS[i] = g; else GROUPS.push(g); syncGroupFields(); return P(JSON.parse(JSON.stringify(g))); },
    group_delete: (id) => { GROUPS = GROUPS.filter(x => x.id !== id); syncGroupFields(); return P({ ok: true }); },
    set_device_group: (name, gid) => {
      GROUPS.forEach(g => { if (g.id !== gid) g.devices = (g.devices || []).filter(d => d !== name); });
      if (gid) { const g = GROUPS.find(x => x.id === gid); if (g && !(g.devices || []).includes(name)) (g.devices = g.devices || []).push(name); }
      syncGroupFields(); return P({ ok: true });
    },
    group_run: (gid) => { const g = GROUPS.find(x => x.id === gid); (g ? g.devices : []).forEach(n => RUN[n] = mockRun(g)); syncGroupFields(); return P({ ok: true, started: g ? g.devices : [] }); },
    group_stop: (gid, force) => { const g = GROUPS.find(x => x.id === gid); (g ? g.devices : []).forEach(n => mockStop(n, force)); syncGroupFields(); return P({ ok: true }); },
    machine_run: (gid, name) => { const g = GROUPS.find(x => x.id === gid); RUN[name] = mockRun(g); syncGroupFields(); return P({ ok: true, started: true }); },
    machine_stop: (name, force) => { mockStop(name, force); syncGroupFields(); return P({ ok: true }); },
    run_status: () => P(JSON.parse(JSON.stringify(RUN))),
    run_log: () => P([{ t: "10:02:11", name: "iPhoneFarm-02", text: "Bắt đầu nhận đơn từ pool «efootball-ios»", kind: "" },
                      { t: "10:02:40", name: "iPhoneFarm-02", text: "Nhận đơn NG261124A007 — 1050 eFootball Coins×1", kind: "" },
                      { t: "10:04:02", name: "iPhoneFarm-02", text: "Đơn NG261124A007 → HOÀN TẤT — Nạp đủ 1 gói", kind: "ok" }]),
    test_flow: (name, steps) => P({ ok: true, results: (steps || []).map((s, i) => ({ i, type: s.type, ok: true, msg: "test " + s.type })) }),
    test_api_steps: (name, steps, vars) => P({ ok: true, results: (steps || []).map((s, i) => ({ i, type: s.type, ok: true, msg: "thử " + s.type + " (biến: " + Object.keys(vars || {}).join(",") + ")" })) }),
    // ---- gateway ----
    ai_info: () => P(AIINFO()),
    ai_set_enabled: (on) => { AI.enabled = !!on; return P(AIINFO()); },
    ai_renew_token: () => { AI.token = "tok-" + Math.random().toString(36).slice(2, 12) + "-moi-" + Math.random().toString(36).slice(2, 12); return P(AIINFO()); },
    gateway_get: () => P({ url: GWCFG.url, has_key: !!GWCFG.key, key_hint: GWCFG.key ? GWCFG.key.slice(0, 8) + "…" : "" }),
    gateway_save: (url, key) => { GWCFG.url = url; if (key) GWCFG.key = key; return P({ ok: true, key: "iPhone Farm (demo)" }); },
    gateway_test: () => P({ ok: true, key: "iPhone Farm (demo)" }),
    gateway_pools: () => P(GWCFG.url && GWCFG.key ? { ok: true, pools: GWPOOLS } : { ok: false, error: "Chưa cấu hình", pools: [] }),
    gateway_pool: (code) => P(code === "efootball-ios" ? JSON.parse(JSON.stringify(GWPOOL)) : { ok: false, error: "Không có pool này." }),
    get_flows: () => P(FLOWS),
    save_flow: (f) => { if (!f.id) f.id = "f" + Date.now(); const i = FLOWS.findIndex(x => x.id === f.id); if (i >= 0) FLOWS[i] = f; else FLOWS.push(f); return P(JSON.parse(JSON.stringify(f))); },
    delete_flow: (id) => { FLOWS = FLOWS.filter(x => x.id !== id); return P({ ok: true }); },
    run_flow: (n, id) => P({ ok: true, results: [{ i: 0, type: "launch", ok: true, msg: "mở app" }, { i: 1, type: "wait", ok: true, msg: "chờ 3s" }] }),
    run_flow_multi: (ns, id) => P({ ok: true, results: Object.fromEntries(ns.map(n => [n, [{ i: 0, type: "launch", ok: true, msg: "ok" }]])) }),
  }};
  // báo giao diện API đã sẵn sàng
  setTimeout(() => window.dispatchEvent(new Event("pywebviewready")), 60);
})();
