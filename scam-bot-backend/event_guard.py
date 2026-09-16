"""กัน event ซ้ำใน process เดียว: ไม่เก็บข้อความ ผู้ส่ง หรือ reply token."""
from collections import OrderedDict
from threading import Lock
from time import monotonic


class EventGuard:
    """จำงานที่กำลังทำ และ ID ที่ทำจบไม่เกิน 24 ชั่วโมง รวมสูงสุด 10,000 รายการ."""
    def __init__(self, ttl_seconds=86400, max_entries=10000, clock=monotonic):
        if ttl_seconds <= 0 or max_entries <= 0:
            raise ValueError("Cache limits must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.clock = clock
        self._active = set()
        self._completed = OrderedDict()
        self._lock = Lock()

    def claim(self, event_id: str) -> str:
        """จอง ID ก่อนเริ่มงาน: คืน new, duplicate หรือ full โดยตรวจและจองพร้อมกัน."""
        with self._lock:
            now = self.clock()
            while self._completed:
                oldest = next(iter(self._completed))
                if self._completed[oldest] > now:
                    break
                self._completed.popitem(last=False)
            if event_id in self._active or event_id in self._completed:
                return "duplicate"
            # ไม่ลบงานที่ยังไม่หมดอายุเพื่อรับงานใหม่ เพราะจะทำให้ event เก่าถูกทำซ้ำ
            if len(self._active) + len(self._completed) >= self.max_entries:
                return "full"
            self._active.add(event_id)
            return "new"

    def finish(self, event_id: str) -> None:
        """จำว่าเคยพยายามทำแล้ว แม้ตรวจ/ส่งไม่สำเร็จ ตามนโยบายไม่ retry อัตโนมัติ."""
        with self._lock:
            if event_id in self._active:
                self._active.remove(event_id)
                self._completed[event_id] = self.clock() + self.ttl_seconds
