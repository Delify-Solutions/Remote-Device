// _mock.js — giả lập window.pywebview.api để render thử giao diện trong trình duyệt.
// CHỈ dùng để test UI, không ảnh hưởng app thật.
(function () {
  const P = (v) => new Promise((res) => setTimeout(() => res(v), 120));
  const SMALL_PNG =
    "data:image/svg+xml;utf8," + encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" width="375" height="667"><rect width="100%" height="100%" fill="#223"/><text x="50%" y="50%" fill="#8af" font-size="26" text-anchor="middle">MOCK SCREEN</text></svg>'
    );
  let DEVICES = [
    { name: "iPhoneFarm-01", udid: "babfe8c8261743b1eb722aa5b0c8b599e58b8c9c", label: "Máy 01", configured: true, ble: true,
      board_online: true, port: "/dev/cu.usbserial-0001", ios_connected: true, ios: "16.7.10", model: "iPhone 8", device_name: "Hoành Anh eFootball" },
    { name: "iPhoneFarm-02", udid: "68b6f24f432ffa7c5beac3de43e0a79b4a792dd6", label: "Máy 02", configured: true, ble: false,
      board_online: true, port: "/dev/cu.usbserial-5", ios_connected: false, ios: null, model: null, device_name: null },
    { name: "iPhoneFarm-03", udid: null, label: "iPhoneFarm-03", configured: false, ble: null,
      board_online: true, port: "/dev/cu.usbserial-7", ios_connected: false, ios: null, model: null, device_name: null },
  ];
  const BOARDS = [
    { port: "/dev/cu.usbserial-0001", chip_desc: "CP2102 (Silicon Labs)", vid: 0x10c4, pid: 0xea60, serial: "0001", flashed: true, name: "iPhoneFarm-01", ble: true },
    { port: "/dev/cu.usbserial-7", chip_desc: "CH340", vid: 0x1a86, pid: 0x7523, serial: null, flashed: false, name: null },
  ];
  const IOS = [
    { udid: "babfe8c8261743b1eb722aa5b0c8b599e58b8c9c", name: "Hoành Anh eFootball", model: "iPhone 8", product_type: "iPhone10,1", ios: "16.7.10", connection: "USB" },
    { udid: "aaaa1111bbbb2222cccc3333dddd4444eeee5555", name: "XS Max", model: "iPhone XS Max", product_type: "iPhone11,6", ios: "18.7", connection: "USB" },
  ];
  let FLOWS = [{ id: "demo1", name: "Mở eFootball", steps: [
    { type: "launch", app: "efootball" }, { type: "wait", seconds: 3 }, { type: "tap", x: 300, y: 500 },
  ], created: 0, updated: 0 }];

  const OV = {
    ok: true,
    system: { os: "macOS", os_raw: "Darwin", os_version: "25.5.0", arch: "arm64", python: "3.9.6",
      python_ok: true, venv: "/Users/duogxaolin/orca/Remote-Device/.venv", has_brew: true, has_apt: false, has_winget: false },
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
      ok: true, board: name, udid: "babfe8c8261743b1eb722aa5b0c8b599e58b8c9c", label: "Máy 01",
      name: "Hoành Anh eFootball", model: "iPhone 8", ios: "16.7.10", shot: SMALL_PNG,
      ranked: [{ name: "Hoành Anh eFootball", udid: "babfe8c8…", score: 4210 }, { name: "XS Max", udid: "aaaa1111…", score: 60 }],
    }), 1500)),
    screenshot: (n) => P({ ok: true, img: SMALL_PNG, w: 375, h: 667 }),
    ble_status: (n) => P({ ok: true, status: "OK ble=connected" }),
    run_step: (n, s) => P({ ok: true, msg: "test " + s.type + " OK" }),
    get_flows: () => P(FLOWS),
    save_flow: (f) => { if (!f.id) f.id = "f" + Date.now(); const i = FLOWS.findIndex(x => x.id === f.id); if (i >= 0) FLOWS[i] = f; else FLOWS.push(f); return P(JSON.parse(JSON.stringify(f))); },
    delete_flow: (id) => { FLOWS = FLOWS.filter(x => x.id !== id); return P({ ok: true }); },
    run_flow: (n, id) => P({ ok: true, results: [{ i: 0, type: "launch", ok: true, msg: "mở app" }, { i: 1, type: "wait", ok: true, msg: "chờ 3s" }] }),
    run_flow_multi: (ns, id) => P({ ok: true, results: Object.fromEntries(ns.map(n => [n, [{ i: 0, type: "launch", ok: true, msg: "ok" }]])) }),
  }};
  // báo giao diện API đã sẵn sàng
  setTimeout(() => window.dispatchEvent(new Event("pywebviewready")), 60);
})();
