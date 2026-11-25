"""
quietserial.py — mở cổng serial của board ESP32 mà KHÔNG làm board khởi động lại.

Mạch tự reset của board nối DTR/RTS với chân IO0/EN: (DTR=0, RTS=1) kéo EN xuống thấp = RESET. Sau `os.open` hệ điều hành bật cả DTR lẫn RTS;
`serial.Serial.open()` rồi hạ DTR TRƯỚC, RTS SAU → giữa hai lệnh có đúng trạng thái (DTR=0, RTS=1) → board reset mỗi lần cổng được mở
(đo thật: up=0, lý do «poweron» sau MỌI lần mở — app khởi động, quét board, `farm` chạy độc lập — mất BLE ~1 s dù đã đặt dtr=rts=False trước khi mở).

`QuietSerial` hạ RTS TRƯỚC (đi qua (DTR=1, RTS=0): chỉ IO0 thấp thoáng qua lúc board đang chạy — vô hại) rồi mới hạ DTR.
"""
from __future__ import annotations
import errno

import serial


class QuietSerial(serial.Serial):
    def open(self):
        dtr, rts = self._dtr_state, self._rts_state
        self._dtr_state, self._rts_state = True, False      # lúc mở: DTR giữ cao (như hệ điều hành đã bật), RTS hạ NGAY
        try:
            super().open()
        finally:
            self._dtr_state, self._rts_state = dtr, rts
        if self.is_open:
            for name, value in (("rts", rts), ("dtr", dtr)):   # RTS đã thấp; đặt lại giá trị người dùng muốn; hạ DTR SAU CÙNG
                try:
                    setattr(self, name, value)
                except OSError as e:                        # cổng ảo / không có đường điều khiển modem: pyserial cũng bỏ qua lỗi này
                    if e.errno not in (errno.EINVAL, errno.ENOTTY):
                        self.close()                        # lỗi lạ: đừng để cổng mở dở (giữ khoá độc quyền)
                        raise
