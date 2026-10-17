"""Export curated AI-authored examples; no network calls or database writes."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCES = [
    dict(id="N01", title="อ้างบริษัทขนส่ง ส่ง SMS หลอกโอนเงิน", url="https://www.thaipbs.or.th/news/content/352261", kind="news", published_date="2025-05-18", pattern="อ้างพัสดุมีปัญหาและคืนเงินประกันเพื่อพาไปทำตามคำสั่ง"),
    dict(id="N02", title="ปลอมแอปพลิเคชัน ชวนลงทุนสูญเงิน 1.5 ล้านบาท", url="https://www.thaipbs.or.th/program/ThaiPBSNews/watch/215656", kind="news", published_date=None, pattern="งานรีวิวสินค้า ต้องเติมเงินเพิ่มก่อนถอนยอด"),
    dict(id="N03", title="สถานีร้องเรียน : เตือนภัย กู้เงินออนไลน์", url="https://www.thaipbs.or.th/program/People/watch/gquidF", kind="news", published_date=None, pattern="กู้เงินออนไลน์แล้วถูกหลอกให้โอนเงิน"),
    dict(id="N04", title="SMS หลอกติดตั้งแอปพลิเคชันดูดเงิน", url="https://www.thaipbs.or.th/program/NewsHour/watch/179337", kind="news", published_date=None, pattern="ส่ง SMS ล่อให้ติดตั้งแอปปลอม"),
    dict(id="N05", title="หลอกลงทุนออนไลน์ รวยง่ายไม่มีจริง", url="https://www.thaipbs.or.th/program/TicTacTech/episodes/109473", kind="news_explainer", published_date=None, pattern="ชวนลงทุนและอ้างรับประกันผลตอบแทน"),
    dict(id="A01", title="กลโกงธนาคารออนไลน์", url="https://www.bot.or.th/th/satang-story/fraud/online-fraud.html", kind="official_advisory", published_date=None, pattern="อ้างบัญชีมีปัญหา ให้กรอกข้อมูลหรือ OTP ผ่านลิงก์"),
]

# Each family includes four positive examples and two benign near-misses.
# Texts are invented from the documented mechanism, never quotations from victims.
FAMILIES = [
    ("parcel_refund", "N01", "sms", "อ้างบริษัทขนส่ง;ชวนกดลิงก์;ขอข้อมูลการเงิน", [
        "พัสดุของคุณจัดส่งไม่สำเร็จ กรุณายืนยันข้อมูลผ่าน https://parcel.example.invalid เพื่อรับเงินประกันคืน",
        "ฝ่ายบริการขนส่งสมมติแจ้งว่าของเสียหาย มีเงินชดเชยให้ กรุณาส่งข้อมูลบัญชีและรหัสยืนยันให้เจ้าหน้าที่ทางแชท",
        "รับเงินคืนค่าพัสดุได้วันนี้ เปิดลิงก์ https://refund.example.invalid แล้วกรอกข้อมูลบัตรเพื่อยืนยันผู้รับเงิน",
        "แจ้งเตือนพัสดุค้าง ระบบต้องยืนยันบัญชีธนาคารก่อนส่งใหม่ ให้ทำรายการตามผู้ดูแลในแชทนี้",
    ], [
        "พัสดุที่คุณสั่งอยู่ระหว่างนำจ่าย ตรวจสอบสถานะได้ในแอปที่ใช้สั่งซื้อ",
        "ร้านอนุมัติคืนเงินสินค้าแล้ว ติดตามยอดคืนผ่านคำสั่งซื้อเดิม ไม่ต้องส่งรหัสยืนยันให้ร้าน",
    ]),
    ("task_topup", "N02", "chat", "อ้างงานรีวิว;เติมเงินก่อนถอน;กดดันทำต่อ", [
        "รับงานรีวิวสินค้าในมือถือ ก่อนรับค่าคอมให้เติมยอดเริ่มงานเข้าระบบที่ผู้ดูแลส่งให้",
        "ยอดงานของคุณครบแล้ว แต่ถอนยังไม่ได้ ต้องโอนค่าปลดล็อกก่อน ระบบจะคืนทั้งหมดพร้อมค่าจ้าง",
        "งานกดรับออเดอร์รอบนี้ยอดไม่ครบ กรุณาเติมเงินส่วนต่างเข้าบัญชีที่แจ้ง มิฉะนั้นค่าคอมเดิมจะถูกระงับ",
        "ทำภารกิจสุดท้ายแล้วรับเงินได้เลยค่ะ ต้องสำรองทุนเพิ่มอีกครั้งเพื่อให้ระบบปิดชุดงาน",
    ], [
        "รับผู้ช่วยลงข้อมูลสินค้า จ่ายค่าจ้างตามชั่วโมง มีสัญญาจ้างและไม่เก็บค่าสมัคร",
        "ส่งรีวิวสินค้าที่ทดลองแล้วได้เลย ค่าจ้างจะเข้าบัญชีตามรอบที่ตกลง ไม่ต้องเติมเงินเพื่อรับงาน",
    ]),
    ("loan_advance_fee", "N03", "chat", "อ้างอนุมัติเงินกู้;โอนก่อนได้เงิน;ค่าธรรมเนียมเพิ่ม", [
        "สินเชื่อสมมติอนุมัติแล้ว กรุณาโอนค่าประกันวงเงินเข้าบัญชีผู้ดูแลก่อนรับเงินกู้",
        "กู้ด่วนไม่ต้องมีคนค้ำค่ะ ชำระค่าปลดล็อกสัญญาทางแชท แล้วเราจะโอนวงเงินให้ทันที",
        "ระบบแจ้งเลขบัญชีไม่ตรง ต้องจ่ายค่าแก้ไขข้อมูลเพิ่มก่อน จึงจะปล่อยเงินกู้ที่อนุมัติไว้ได้",
        "วงเงินพร้อมจ่ายแล้ว แต่ยังขาดยอดค้ำประกัน โอนให้เจ้าหน้าที่ก่อนนะคะ เงินส่วนนี้คืนพร้อมยอดกู้",
    ], [
        "นัดปรึกษาสินเชื่อที่สาขาพรุ่งนี้ กรุณาเตรียมเอกสารรายได้ไปยื่นกับเจ้าหน้าที่",
        "หากต้องการกู้เงิน ตรวจสอบชื่อผู้ให้บริการก่อน และอ่านอัตราดอกเบี้ยในสัญญาให้ครบ",
    ]),
    ("malicious_app", "N04", "sms", "ล่อให้ติดตั้งแอปนอกช่องทางปกติ;อ้างสิทธิประโยชน์", [
        "คุณมีสิทธิรับเงินช่วยเหลือ ติดตั้งแอปจาก https://benefit.example.invalid เพื่อยืนยันสิทธิวันนี้",
        "ระบบสมาชิกสมมติรุ่นเดิมหมดอายุ กรุณาดาวน์โหลดไฟล์ติดตั้งจากลิงก์ในข้อความนี้เพื่อใช้บัญชีต่อ",
        "รับคูปองคืนเงินได้แล้ว โหลดแอปที่แอดมินแนบในแชทและอนุญาตสิทธิที่ระบบร้องขอให้ครบ",
        "มีเงินชดเชยค้างรับ เปิด https://claim.example.invalid และติดตั้งตัวช่วยยืนยันก่อนรับยอด",
    ], [
        "อัปเดตแอปที่คุณใช้อยู่ผ่านร้านแอปในโทรศัพท์ ตรวจสอบชื่อผู้พัฒนาก่อนติดตั้ง",
        "มีคนส่งลิงก์ให้โหลดแอปรับเงินมา อย่าเพิ่งติดตั้งนะ ลองติดต่อหน่วยงานจากช่องทางที่หาเองก่อน",
    ]),
    ("investment_guarantee", "N05", "social_post", "รับประกันกำไร;ชวนโอนเงินลงทุน;อ้างกลุ่มพิเศษ", [
        "กลุ่มลงทุนสมมติรับสมาชิกเพิ่ม รับประกันกำไรทุกวัน ฝากทุนกับผู้ดูแลแล้วรอรับยอดได้เลย",
        "ไม่ต้องมีความรู้เรื่องลงทุน เราดูแลให้ครบ เงินต้นไม่หายแน่นอน สมัครแล้วโอนทุนเข้าบัญชีที่ส่งทางแชท",
        "รอบพิเศษเฉพาะสมาชิก ลงทุนแล้วได้ผลตอบแทนแน่นอน ไม่มีความเสี่ยง ทักผู้ดูแลเพื่อรับบัญชีฝากทุน",
        "เข้ากลุ่มลับลงทุนวันนี้ ผู้เชี่ยวชาญสมมติการันตีกำไรทุกครั้ง จองสิทธิด้วยการโอนเงินก่อนปิดรอบ",
    ], [
        "กองทุนมีความเสี่ยงและอาจขาดทุนได้ ศึกษาหนังสือชี้ชวนก่อนตัดสินใจลงทุน",
        "วันนี้คุยเรื่องการลงทุนกันไหม อยากเปรียบเทียบค่าธรรมเนียมกับระดับความเสี่ยงก่อนเลือก",
    ]),
    ("bank_phishing", "A01", "sms", "อ้างธนาคาร;ขู่ระงับบัญชี;ขอ OTP ผ่านลิงก์", [
        "ธนาคารสมมติแจ้งบัญชีจะถูกระงับ กรุณากรอกชื่อผู้ใช้ รหัสผ่านและ OTP ที่ https://bank.example.invalid",
        "พบรายการผิดปกติ หากต้องการยกเลิกให้ส่งรหัส OTP กลับในแชทนี้ เจ้าหน้าที่จะจัดการให้",
        "บัญชีของคุณยังไม่ผ่านการยืนยัน เปิด https://verify.example.invalid แล้วใส่รหัสเข้าแอปเพื่อรักษาสิทธิใช้งาน",
        "ฝ่ายความปลอดภัยธนาคารสมมติขอตรวจสอบบัญชี กรุณาบอกรหัสยืนยันที่เพิ่งได้รับแก่ผู้ดูแลทันที",
    ], [
        "อย่าบอก OTP ให้ใคร แม้ผู้ติดต่อจะอ้างเป็นเจ้าหน้าที่ธนาคารก็ตาม",
        "ได้รับข้อความว่าบัญชีจะถูกระงับ เลยเปิดแอปธนาคารเองเพื่อตรวจสอบ ไม่ได้กดลิงก์ในข้อความ",
    ]),
]


def main():
    sources = {s["id"]: s for s in SOURCES}
    rows = []
    for category, source_id, channel, cues, scams, benign in FAMILIES:
        for label, examples in (("spam", scams), ("ham", benign)):
            for index, message in enumerate(examples, 1):
                rows.append(dict(id=f"{category}-{label}-{index:02d}", label=label,
                    thai_text=message, category=category if label == "spam" else "benign",
                    contrast_family=category, channel=channel, source_id=source_id,
                    source_url=sources[source_id]["url"], is_synthetic=True,
                    derivation="pattern_based" if label == "spam" else "synthetic_contrast",
                    risk_cues=cues if label == "spam" else "",
                    generator="Codex (AI-authored curated examples)", review_status="needs_human_review",
                    created_date="2026-10-01", group_id=category))
    assert len(rows) == 36
    assert len({r["thai_text"] for r in rows}) == len(rows)
    assert all(r["source_id"] in sources for r in rows)
    with (ROOT / "news_synthetic_dataset.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (ROOT / "news_synthetic_dataset.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    (ROOT / "sources.json").write_text(json.dumps(SOURCES, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Exported 36 unique examples: 24 spam, 12 ham; 6 source records.")


if __name__ == "__main__":
    main()
