"""บทเรียนในแชต: ใช้ผลตรวจเดิม ไม่เรียก AI และไม่เพิ่มข้อมูลลง Dataset."""
from collections import OrderedDict
from copy import deepcopy
from threading import Lock
from time import monotonic
from uuid import uuid4


def lesson_points(text: str) -> list[dict]:
    """คำที่พบใช้เลือกคำแนะนำเท่านั้น ไม่ใช้ตัดสินความเสี่ยงซ้ำ."""
    topics = (
        (("otp", "รหัสผ่าน"), "user", "otp", "รหัสยืนยันใช้อนุมัติการเข้าถึงหรือทำรายการ อย่าส่งรหัสให้คู่สนทนา"),
        (("รับประกันกำไร", "ไม่มีความเสี่ยง", "ผลตอบแทน"), "gift", "payments", "คำรับรองผลตอบแทนไม่ใช่หลักฐานว่าจะได้รับเงินจริง ต้องตรวจผู้ให้บริการและเงื่อนไขจากแหล่งอิสระ"),
        (("ค่าประกัน", "มัดจำ", "โอนเงิน"), "message", "payments", "ก่อนจ่ายเงิน ตรวจผู้รับและเงื่อนไขผ่านช่องทางที่ค้นหาเอง อย่าใช้หลักฐานจากผู้ชักชวนเพียงฝ่ายเดียว"),
        (("ตำรวจ", "ฟอกเงิน", "เจ้าหน้าที่"), "user", "impersonation", "ชื่อหรือตำแหน่งที่อ้างยังยืนยันตัวตนไม่ได้ ติดต่อหน่วยงานผ่านช่องทางทางการที่ค้นหาเอง"),
        (("ด่วน", "ทันที", "ภายในวันนี้"), "clock", "urgency", "ตรวจว่าคำบอกเวลานี้เร่งให้ทำอะไร เช่น ‘เริ่มงานได้ทันที’ ไม่ได้หมายถึงเร่งโอนเงิน หากเร่งให้จ่ายเงินหรือส่งข้อมูลก่อนตรวจสอบ ควรหยุดตรวจสอบก่อนทำตาม"),
        (("https://", "http://", "ลิงก์"), "link", "links", "ข้อความลิงก์ไม่ยืนยันความปลอดภัยของเว็บไซต์ บอตยังไม่ได้เปิดตรวจปลายทาง ควรเข้าแอปหรือเว็บไซต์ทางการด้วยตนเอง"),
    )
    points = []
    lower = text.lower()
    for words, icon, topic, explanation in topics:
        for word in words:
            start = lower.find(word)
            if start >= 0:
                quote = text[start:start + len(word)]
                points.append({"icon": icon, "topic": topic,
                               "title": f"พบคำว่า ‘{quote}’", "description": explanation})
                break
        if len(points) == 3:
            break
    if not points:
        points.append({"icon": "help", "topic": "impersonation", "title": "ตรวจที่มาและบริบท",
                       "description": "ตรวจที่มาและบริบทของข้อความผ่านช่องทางที่เชื่อถือได้ก่อนทำตาม โดยเฉพาะเมื่อมีการขอเงินหรือข้อมูลส่วนตัว"})
    return points


def build_lesson(text: str, result: dict) -> str | None:
    """เลือกหัวข้อจากคำที่มีจริง ไม่ใช้คีย์เวิร์ดตัดสินว่าเป็นมิจฉาชีพ."""
    status = result.get("status")
    reason = result.get("reason")
    # สร้างบทเรียนและปุ่มเฉพาะผลที่พบความเสี่ยงเท่านั้น
    if (status != "risk_found" or result.get("is_scam") is not True
            or not isinstance(reason, str) or not reason.strip() or len(reason) > 500):
        return None
    tips = [f"• {point['title']}: {point['description']}" for point in lesson_points(text)]
    return (
        "📖 เรียนรู้จากข้อความนี้\nผลเดิมพบสัญญาณเสี่ยง ควรหยุดตรวจสอบก่อนทำตาม"
        + "\n\nเหตุผลจากผลตรวจเดิม:\n" + reason
        + "\n\nหัวข้อที่ควรตรวจเพิ่ม (ไม่ใช่หลักฐานยืนยันการหลอกลวง):\n" + "\n".join(tips)
        + "\n\nวิธีเช็ค: แยกให้ออกว่าเป็นคำชักชวนจริง หรือการยกตัวอย่าง/เตือนภัย "
          "หากข้อมูลไม่พอ ส่งข้อความเดิมพร้อมบริบทมาตรวจใหม่ โดยปิดบังข้อมูลส่วนตัว\n"
          "นี่เป็นคำแนะนำประกอบผลเดิม ไม่ใช่การตรวจซ้ำหรือยืนยันตัวตนผู้ส่ง"
    )


# คำแนะนำในหน้ารายละเอียด แยกตามสถานะผลตรวจ (หน้าเว็บต้องมีอย่างน้อย 1 ข้อ)
NEXT_STEPS = {
    "risk_found": [
        "หยุดก่อนคลิกลิงก์ โอนเงิน หรือส่งข้อมูล แล้วติดต่อหน่วยงานผ่านช่องทางที่ค้นหาเอง",
        "แยกคำชักชวนจริงออกจากข่าว การยกตัวอย่าง และคำเตือนภัย",
        "หากข้อมูลไม่พอ ส่งข้อความพร้อมบริบทมาตรวจใหม่ โดยปิดบังข้อมูลส่วนตัว ไม่ส่ง OTP หรือรหัสผ่าน",
    ],
    "uncertain": [
        "ตรวจกับหน่วยงานหรือผู้ส่งผ่านช่องทางทางการที่ค้นหาเอง ก่อนทำตามข้อความ",
        "ส่งข้อความเดิมพร้อมบริบทเพิ่มเติมมาตรวจใหม่ได้ โดยปิดบังข้อมูลส่วนตัว",
        "ถ้ามีการขอเงิน OTP หรือรหัสผ่านเพิ่มเข้ามา ให้หยุดและตรวจสอบก่อน",
    ],
    "no_risk_found": [
        "ยังระวังได้ตามปกติ ผลนี้ไม่รับรองว่าปลอดภัยและไม่ได้ยืนยันตัวตนผู้ส่ง",
        "ถ้าภายหลังมีการขอเงิน OTP หรือให้กดลิงก์ ให้ส่งข้อความนั้นมาตรวจใหม่",
    ],
}


def build_case_detail(text: str, result: dict, received_at: str) -> dict:
    """รับผลเดิม 3 สถานะ (เสี่ยง/ควรตรวจเพิ่ม/ยังไม่พบ) จัดข้อมูลสำหรับหน้าเว็บโดยไม่เรียก AI."""
    status = result["status"]
    points = lesson_points(text)
    reason = result.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        # หน้าเว็บไม่รับเหตุผลว่าง จึงใส่ข้อความกลางแทน
        reason = "ไม่มีเหตุผลเพิ่มเติมจากผลตรวจ"
    return {
        "title": " ".join(text.split())[:60], "category": "message", "message": text,
        "receivedAt": received_at, "status": status, "reason": reason,
        "lessonId": points[0]["topic"],
        "warningPoints": [{key: point[key] for key in ("icon", "title", "description")} for point in points],
        "nextSteps": list(NEXT_STEPS[status]),
    }


class LessonStore:
    """เก็บเจ้าของ บทเรียน และรายละเอียดใน RAM อายุ 15 นาที สูงสุด 1,000 เคส."""
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

    def add(self, owner: str, lesson: str, *, detail: dict | None = None,
            case_id: str | None = None) -> str | None:
        """case_id: ใช้รหัสเดียวกับแถวใน detection_logs ถ้ามี (ไม่ส่ง = สุ่มใหม่)."""
        if not isinstance(owner, str) or not owner.strip():
            return None
        with self._lock:
            self._expire()
            # เต็มแล้วงดปุ่มใหม่ ไม่ทิ้งเคสเก่าที่ปุ่มยังไม่หมดอายุ
            if len(self._cases) >= self.max_entries:
                return None
            case_id = case_id or uuid4().hex
            self._cases[case_id] = (self.clock() + self.ttl_seconds, owner, lesson, deepcopy(detail))
            return case_id

    def get(self, case_id: str, owner: str) -> str | None:
        with self._lock:
            self._expire()
            case = self._cases.get(case_id)
            if case and isinstance(owner, str) and owner and case[1] == owner:
                return case[2]
            # ไม่แยกเหตุผลผิดเจ้าของ/ไม่มีเคส เพื่อไม่เปิดเผยว่าเคสของคนอื่นมีอยู่
            return None

    def get_detail(self, case_id: str, owner: str) -> dict | None:
        with self._lock:
            self._expire()
            case = self._cases.get(case_id)
            if case and isinstance(owner, str) and owner and case[1] == owner and case[3]:
                return {**deepcopy(case[3]), "id": case_id}
            return None
