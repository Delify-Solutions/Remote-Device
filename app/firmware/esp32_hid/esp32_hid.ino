/*
 * esp32_hid — ESP32 làm bàn phím + chuột BLE cho iPhone, nhận lệnh từ Mac qua Serial.
 *
 * Thư viện: ESP32-BLE-Combo (BLE Bluedroid sẵn trong core esp32 2.0.17).
 * Ghép: iPhone > Settings > Bluetooth chọn DEVICE_NAME; bật AssistiveTouch để dùng chuột.
 *
 * Lệnh Serial (115200), mỗi dòng kết thúc \n:
 *   ping | whoami
 *   status            OK ble=<connected|disconnected> fw=.. up=<giây> heap=<RAM trống> min=<đáy thấp nhất> blk=<mảng liền lớn nhất>
 *                        rst=<lý do reset lần trước> rxerr=.. ovf=.. drop=<số lần mất BLE> cmds=.. temp=<°C thô>
 *   info              OK info chip=.. rev=.. cores=.. mhz=.. flash=.. sdk=..
 *   reset             OK reset rồi tự khởi động lại (board đơ hẳn thì Mac reset cứng bằng chân EN qua RTS)
 *   type <chuỗi>      gõ chuỗi (giữ nguyên khoảng trắng sau "type ")
 *   key <tên>         enter|return|tab|esc|back|space
 *   move <dx> <dy>    di chuột tương đối (mỗi trục tự chia nhỏ nếu > 127)
 *   click | rclick | down | up
 * Trả về 1 dòng "OK..." hoặc "ERR...".
 */
#include <BleCombo.h>
#include <esp_system.h>

#define FW_VERSION 2             // 2 = có status sức khoẻ / info / reset / watchdog / chống tràn dòng lệnh
#define MAX_LINE 512             // dòng lệnh dài hơn → bỏ cả dòng + "ERR line-too-long" (không để ăn dần RAM)
#define RX_BUFFER 2048           // bộ đệm nhận serial (mặc định 256: gửi dồn nhiều lệnh khi board đang bận thì tràn, rớt lệnh)
#define LOW_HEAP 24000           // RAM trống dưới mức này mà board đang rảnh → tự khởi động lại trước khi hỏng hẳn
#define IDLE_HEAL_MS 30000       // «đang rảnh» = quá chừng này ms không nhận byte nào

#ifndef KEY_ESC
#define KEY_ESC 0xB1
#endif

// Tên mỗi board: đặt lúc build bằng -DDEVICE_NAME=\"iPhoneFarm-02\"; mặc định 01.
#ifndef DEVICE_NAME
#define DEVICE_NAME "iPhoneFarm-01"
#endif

BleCombo hid;

// Bộ đệm dòng lệnh CỐ ĐỊNH (không dùng String nối dần → không phân mảnh / không tràn RAM khi nhận rác không có xuống dòng).
static char lineBuf[MAX_LINE + 1];
static size_t lineLen = 0;
static bool lineOver = false;
static uint32_t lastRx = 0, rxErrors = 0, lineOverflows = 0, cmdCount = 0, bleDrops = 0;
static bool wasConnected = false;

void reply(const String &s) { Serial.println(s); }

const char *resetName() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON:   return "poweron";
    case ESP_RST_EXT:       return "ext";
    case ESP_RST_SW:        return "sw";
    case ESP_RST_PANIC:     return "panic";
    case ESP_RST_INT_WDT:   return "int_wdt";
    case ESP_RST_TASK_WDT:  return "task_wdt";
    case ESP_RST_WDT:       return "wdt";
    case ESP_RST_DEEPSLEEP: return "deepsleep";
    case ESP_RST_BROWNOUT:  return "brownout";   // nguồn USB yếu / tụt áp — nguyên nhân hay gặp nhất của ESP32 chạy BLE bị đơ
    case ESP_RST_SDIO:      return "sdio";
    default:                return "unknown";
  }
}

void doStatus() {
  bool c = hid.isConnected();
  String s = "OK ble=";
  s += c ? "connected" : "disconnected";
  s += " fw=" + String(FW_VERSION);
  s += " up=" + String(millis() / 1000);
  s += " heap=" + String(ESP.getFreeHeap());
  s += " min=" + String(ESP.getMinFreeHeap());
  s += " blk=" + String(ESP.getMaxAllocHeap());
  s += " rst=" + String(resetName());
  s += " rxerr=" + String(rxErrors);
  s += " ovf=" + String(lineOverflows);
  s += " drop=" + String(bleDrops);
  s += " cmds=" + String(cmdCount);
  s += " temp=" + String(temperatureRead(), 1);
  reply(s);
}

void doInfo() {
  reply(String("OK info chip=") + ESP.getChipModel() + " rev=" + String(ESP.getChipRevision()) +
        " cores=" + String(ESP.getChipCores()) + " mhz=" + String(ESP.getCpuFreqMHz()) +
        " flash=" + String(ESP.getFlashChipSize() / 1024) + "k sdk=" + ESP.getSdkVersion());
}

void doReset() {
  reply("OK reset");
  Serial.flush();
  delay(80);
  ESP.restart();
}

void setup() {
  Serial.setRxBufferSize(RX_BUFFER);          // phải gọi TRƯỚC begin
  Serial.begin(115200);
  Serial.onReceiveError([](hardwareSerial_error_t e) { rxErrors++; });   // tràn FIFO / tràn bộ đệm / lỗi khung
  delay(200);
  hid.setName(DEVICE_NAME);
  hid.begin();
  enableLoopWDT();                            // vòng loop() kẹt quá ~5 s → board tự reset (lý do rst=panic hoặc task_wdt tuỳ cấu hình core), không đơ vĩnh viễn
  lastRx = millis();
  reply(String("BOOT " DEVICE_NAME " fw=") + String(FW_VERSION) + " rst=" + resetName());
}

void doKey(const String &name) {
  if      (name == "enter" || name == "return") hid.write(KEY_RETURN);
  else if (name == "tab")   hid.write(KEY_TAB);
  else if (name == "esc")   hid.write(KEY_ESC);
  else if (name == "back")  hid.write(KEY_BACKSPACE);
  else if (name == "space") hid.write((uint8_t)' ');
  else { reply("ERR key?"); return; }
  hid.releaseAll();
  reply("OK key " + name);
}

// Tổ hợp phím: "gui h" (Cmd+H=Home), "gui tab" (chuyển app), "ctrl shift 4"...
void doCombo(String arg) {
  arg.trim();
  String tok[6]; int n = 0;
  while (arg.length() && n < 6) {
    int sp = arg.indexOf(' ');
    if (sp < 0) { tok[n++] = arg; arg = ""; }
    else { tok[n++] = arg.substring(0, sp); arg = arg.substring(sp + 1); }
  }
  if (n == 0) { reply("ERR combo?"); return; }
  for (int i = 0; i < n - 1; i++) {
    String m = tok[i];
    if      (m == "gui" || m == "cmd") hid.press(KEY_LEFT_GUI);
    else if (m == "ctrl")  hid.press(KEY_LEFT_CTRL);
    else if (m == "alt")   hid.press(KEY_LEFT_ALT);
    else if (m == "shift") hid.press(KEY_LEFT_SHIFT);
  }
  String k = tok[n - 1];
  if      (k == "enter" || k == "return") hid.press(KEY_RETURN);
  else if (k == "tab")   hid.press(KEY_TAB);
  else if (k == "space") hid.press((uint8_t)' ');
  else if (k.length() == 1) hid.press((uint8_t)k[0]);
  delay(50);
  hid.releaseAll();
  reply("OK combo");
}

// Gõ chuỗi an toàn: từng ký tự, nhả phím sau mỗi ký tự + nhịp nhỏ.
// Tránh lỗi phím cuối bị giữ -> iOS auto-repeat; chắc cho ký tự đặc biệt (mật khẩu).
void typeString(const String &s) {
  for (size_t i = 0; i < s.length(); i++) {
    hid.write((uint8_t)s[i]);
    hid.releaseAll();
    delay(14);
    feedLoopWDT();
  }
}

// di chuột theo BƯỚC NHỎ (tốc độ thấp) để tránh gia tốc của iOS -> tuyến tính, lặp lại được.
#define MV_STEP 5     // số đơn vị mỗi report (nhỏ = ít gia tốc)
#define MV_DELAY 5    // ms giữa các report
void moveBig(int dx, int dy) {
  while (dx != 0 || dy != 0) {
    int sx = dx >  MV_STEP ? MV_STEP : (dx < -MV_STEP ? -MV_STEP : dx);
    int sy = dy >  MV_STEP ? MV_STEP : (dy < -MV_STEP ? -MV_STEP : dy);
    hid.move((signed char)sx, (signed char)sy);
    dx -= sx; dy -= sy;
    delay(MV_DELAY);
    feedLoopWDT();
  }
}

void handle(String line) {
  line.trim();
  if (line.length() == 0) return;
  cmdCount++;
  if (line == "ping") { reply("pong"); return; }
  if (line == "whoami") { reply(String("NAME ") + DEVICE_NAME); return; }
  if (line == "status") { doStatus(); return; }
  if (line == "info") { doInfo(); return; }
  if (line == "reset") { doReset(); return; }
  if (line == "home") {                 // slam nhanh con trỏ về góc trên-trái
    if (!hid.isConnected()) { reply("ERR not-connected"); return; }
    for (int i = 0; i < 8; i++) { hid.move(-127, -127); delay(6); }
    reply("OK home"); return;
  }

  int sp = line.indexOf(' ');
  String cmd = (sp < 0) ? line : line.substring(0, sp);
  String arg = (sp < 0) ? ""  : line.substring(sp + 1);

  if (!hid.isConnected()) { reply("ERR not-connected"); return; }

  if      (cmd == "type")   { typeString(arg); reply("OK type " + String(arg.length())); }
  else if (cmd == "key")    { doKey(arg); }
  else if (cmd == "combo")  { doCombo(arg); }
  else if (cmd == "move")   {
    int s2 = arg.indexOf(' ');
    if (s2 < 0) { reply("ERR move x y"); return; }
    moveBig(arg.substring(0, s2).toInt(), arg.substring(s2 + 1).toInt());
    reply("OK move");
  }
  else if (cmd == "click")  { hid.click(MOUSE_LEFT);  reply("OK click"); }
  else if (cmd == "rclick") { hid.click(MOUSE_RIGHT); reply("OK rclick"); }
  else if (cmd == "down")   { hid.press(MOUSE_LEFT);  reply("OK down"); }
  else if (cmd == "up")     { hid.release(MOUSE_LEFT);reply("OK up"); }
  else { reply("ERR cmd?"); }
}

void loop() {
  feedLoopWDT();
  while (Serial.available()) {
    feedLoopWDT();                               // máy chủ gửi dồn liên tục thì vòng này cũng không được làm watchdog reset board
    char c = (char)Serial.read();
    lastRx = millis();
    if (c == '\n') {
      if (lineOver) { lineOverflows++; reply("ERR line-too-long"); }
      else { lineBuf[lineLen] = 0; handle(String(lineBuf)); }
      lineLen = 0; lineOver = false;
    } else if (c != '\r') {
      if (lineLen < MAX_LINE) lineBuf[lineLen++] = c; else lineOver = true;
    }
  }
  bool c = hid.isConnected();
  if (wasConnected && !c) bleDrops++;          // đếm số lần BLE bị rớt (iPhone đi xa, tắt Bluetooth, board nghẽn…)
  wasConnected = c;
  // Tự chữa: RAM gần cạn mà board đang rảnh → khởi động lại SỚM (lúc không ai nhờ gì) thay vì đơ giữa một lệnh.
  if (millis() - lastRx > IDLE_HEAL_MS && ESP.getFreeHeap() < LOW_HEAP) {
    reply("BOOT-HEAL low-heap");
    Serial.flush();
    delay(80);
    ESP.restart();
  }
}
