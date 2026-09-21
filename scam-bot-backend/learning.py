"""บทเรียนในแชต: ใช้ผลตรวจเดิม ไม่เรียก AI และไม่เพิ่มข้อมูลลง Dataset."""
from collections import OrderedDict
from threading import Lock
from time import monotonic
from uuid import uuid4


def build_lesson(text: str, result: dict) -> str | None:
    """เลือกหัวข้อจากคำที่มีจริง ไม่ใช้คีย์เวิร์ดตัดสินว่าเป็นมิจฉาชีพ."""
    status = result.get("status")
    reason = result.get("reason")
    # สร้างบทเรียนและปุ่มเฉพาะผลที่พบความเสี่ยงเท่านั้น
    if (status != "risk_found" or result.get("is_scam") is not True
            or not isinstance(reason, str) or not reason.strip() or len(reason) > 500):
        return None
    # เลือกได้ไม่เกิน 3 หัวข้อ; คำที่พบอาจอยู่ในข่าว/คำเตือน จึงไม่ใช่ข้อกล่าวหา
    topics = (
        (("otp", "รหัสผ่าน"), "รหัสยืนยันใช้อนุมัติการเข้าถึงหรือทำรายการ อย่าส่งรหัสให้คู่สนทนา"),
        (("รับประกันกำไร", "ไม่มีความเสี่ยง", "ผลตอบแทน"), "คำรับรองผลตอบแทนไม่ใช่หลักฐานว่าจะได้รับเงินจริง ต้องตรวจผู้ให้บริการและเงื่อนไขจากแหล่งอิสระ"),
        (("ค่าประกัน", "มัดจำ", "โอนเงิน"), "ก่อนจ่ายเงิน ตรวจผู้รับและเงื่อนไขผ่านช่องทางที่ค้นหาเอง อย่าใช้หลักฐานจากผู้ชักชวนเพียงฝ่ายเดียว"),
        (("ตำรวจ", "ฟอกเงิน", "เจ้าหน้าที่"), "ชื่อหรือตำแหน่งที่อ้างยังยืนยันตัวตนไม่ได้ ติดต่อหน่วยงานผ่านช่องทางทางการที่ค้นหาเอง"),
        (("ด่วน", "ทันที", "ภายในวันนี้"), "การเร่งเวลาอาจทำให้ไม่มีเวลาตรวจสอบ ควรหยุดและตรวจข้อมูลก่อน ไม่ต้องรีบทำตาม"),
        (("https://", "http://", "ลิงก์"), "ข้อความลิงก์ไม่ยืนยันความปลอดภัยของเว็บไซต์ บอตยังไม่ได้เปิดตรวจปลายทาง ควรเข้าแอปหรือเว็บไซต์ทางการด้วยตนเอง"),
    )
    tips = []
    lower = text.lower()
    for words, explanation in topics:
        for word in words:
            start = lower.find(word)
            if start >= 0:
                quote = text[start:start + len(word)]
                tips.append(f"• พบคำว่า ‘{quote}’: {explanation}")
                break
        if len(tips) == 3:
            break
    if not tips:
        tips.append("• ตรวจที่มาและบริบทของข้อความผ่านช่องทางที่เชื่อถือได้ก่อนทำตาม โดยเฉพาะเมื่อมีการขอเงินหรือข้อมูลส่วนตัว")
    return (
        "📖 เรียนรู้จากข้อความนี้\nผลเดิมพบสัญญาณเสี่ยง ควรหยุดตรวจสอบก่อนทำตาม"
        + "\n\nเหตุผลจากผลตรวจเดิม:\n" + reason
        + "\n\nหัวข้อที่ควรตรวจเพิ่ม (ไม่ใช่หลักฐานยืนยันการหลอกลวง):\n" + "\n".join(tips)
        + "\n\nวิธีเช็ค: แยกให้ออกว่าเป็นคำชักชวนจริง หรือการยกตัวอย่าง/เตือนภัย "
          "หากข้อมูลไม่พอ ส่งข้อความเดิมพร้อมบริบทมาตรวจใหม่ โดยปิดบังข้อมูลส่วนตัว\n"
          "นี่เป็นคำแนะนำประกอบผลเดิม ไม่ใช่การตรวจซ้ำหรือยืนยันตัวตนผู้ส่ง"
    )


class LessonStore:
    """เก็บเฉพาะเจ้าของกับบทเรียน อายุ 15 นาที สูงสุด 1,000 เคส."""
    # ponytail: RAM process เดียวสำหรับเดโม; ใช้ที่เก็บร่วมเมื่อมีหลาย worker/ต้องเก็บข้าม restart
    def __init__(self, ttl_seconds=900, max_entries=1000, clock=monotonic):
        if ttl_seconds <= 0 or max_entries <= 0:
            raise ValueError("Limits must be positive")
        self.ttl_seconds, self.max_entries, self.clock = ttl_seconds, max_entries, clock
        self._cases = OrderedDict()
        self._lock = Lock()

    def _expire(self):
        now = self.clock()
        while self._cases and next(iter(self._cases.values()))[0] <= now:
            self._cases.popitem(last=False)

    def add(self, owner: str, lesson: str) -> str | None:
        if not isinstance(owner, str) or not owner.strip():
            return None
        with self._lock:
            self._expire()
            # เต็มแล้วงดปุ่มใหม่ ไม่ทิ้งเคสเก่าที่ปุ่มยังไม่หมดอายุ
            if len(self._cases) >= self.max_entries:
                return None
            case_id = uuid4().hex
            self._cases[case_id] = (self.clock() + self.ttl_seconds, owner, lesson)
            return case_id

    def get(self, case_id: str, owner: str) -> str | None:
        with self._lock:
            self._expire()
            case = self._cases.get(case_id)
            if case and isinstance(owner, str) and owner and case[1] == owner:
                return case[2]
            # ไม่แยกเหตุผลผิดเจ้าของ/ไม่มีเคส เพื่อไม่เปิดเผยว่าเคสของคนอื่นมีอยู่
            return None
