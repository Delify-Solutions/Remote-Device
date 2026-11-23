/*
 * esp32_hid — ESP32 làm bàn phím + chuột BLE cho iPhone, nhận lệnh từ Mac qua Serial.
 *
 * Thư viện: ESP32-BLE-Combo (BLE Bluedroid sẵn trong core esp32 2.0.17).
 * Ghép: iPhone > Settings > Bluetooth chọn DEVICE_NAME; bật AssistiveTouch để dùng chuột.
 *
 * Lệnh Serial (115200), mỗi dòng kết thúc \n:
 *   ping | status
 *   type <chuỗi>      gõ chuỗi (giữ nguyên khoảng trắng sau "type ")
 *   key <tên>         enter|return|tab|esc|back|space
 *   move <dx> <dy>    di chuột tương đối (mỗi trục tự chia nhỏ nếu > 127)
 *   click | rclick | down | up
 * Trả về 1 dòng "OK..." hoặc "ERR...".
 */
#include <BleCombo.h>

#ifndef KEY_ESC
#define KEY_ESC 0xB1
#endif

// Tên mỗi board: đặt lúc build bằng -DDEVICE_NAME=\"iPhoneFarm-02\"; mặc định 01.
#ifndef DEVICE_NAME
#define DEVICE_NAME "iPhoneFarm-01"
#endif

BleCombo hid;
String buf;

void reply(const String &s) { Serial.println(s); }

void setup() {
  Serial.begin(115200);
  delay(200);
  hid.setName(DEVICE_NAME);
  hid.begin();
  reply("BOOT " DEVICE_NAME);
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
  }
}

void handle(String line) {
  line.trim();
  if (line.length() == 0) return;
  if (line == "ping") { reply("pong"); return; }
  if (line == "whoami") { reply(String("NAME ") + DEVICE_NAME); return; }
  if (line == "home") {                 // slam nhanh con trỏ về góc trên-trái
    if (!hid.isConnected()) { reply("ERR not-connected"); return; }
    for (int i = 0; i < 8; i++) { hid.move(-127, -127); delay(6); }
    reply("OK home"); return;
  }
  if (line == "status") {
    reply(String("OK ble=") + (hid.isConnected() ? "connected" : "disconnected"));
    return;
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
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') { handle(buf); buf = ""; }
    else if (c != '\r') buf += c;
  }
}
