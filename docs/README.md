# เอกสารโปรเจกต์

เริ่มติดตั้ง รันบอต และทดสอบจาก [README หลัก](../README.md)
คำสั่งในเอกสารแต่ละฉบับให้รันจากโฟลเดอร์ที่เอกสารนั้นระบุ

หาไฟล์และฟังก์ชันจาก [สารบัญโค้ด](CODE_MAP.md) ซึ่งแยกงานบอต เครื่องมือ ชุดข้อมูล และ tests

## Backend และ LINE

| เอกสาร | เนื้อหา |
|---|---|
| [ความเสถียร Webhook](backend/STABILITY.md) | ตรวจ event ซ้ำ, thread pool, timeout และ log |
| [บทเรียนจากผลตรวจ](backend/LEARNING.md) | ปุ่มเรียนรู้และข้อจำกัดของเคส |
| [ติดตั้ง Mini App](backend/MINI_SETUP.md) | การตั้งค่า LIFF และการเปิดรายละเอียดผลตรวจ |
| [Rich Menu](backend/RICH_MENU.md) | สร้าง ตรวจ และตั้งเมนู LINE |
| [สมาชิกกลุ่ม](backend/GROUP_TRACKING.md) | ดึงและบันทึกจำนวนสมาชิกกลุ่ม |

## ฐานข้อมูล

- [รูปแบบข้อมูล Dashboard](../supabase/DATA_CONTRACT.md)
- [SQL โครงสร้าง Dashboard](../supabase/dashboard_schema.sql)
- [SQL เพิ่มข้อมูลผู้ส่ง](../supabase/add_detection_sender.sql)
- [SQL จำกัดชุดตัวอย่างให้อ่านได้อย่างเดียวสำหรับผู้ใช้ทั่วไป](../supabase/secure_scam_dataset.sql)
- [SQL จำกัดสิทธิ์สถิติ Dashboard](../supabase/secure_dashboard_daily_stats.sql)
- [SQL search_path ของ vector](../supabase/secure_vector_search_path.sql)

## ชุดข้อมูล

- [ชุดข้อมูลข่าวสังเคราะห์](../scam-ai-engine/news_dataset/README.md)
- [ชุดข้อมูลขยาย 1,000 รายการ](../scam-ai-engine/news_dataset/expanded_1000/README.md)

## เอกสารย้อนหลัง

- [คลังบันทึกความคืบหน้า แบบ และแผนงานเดิม](archive/README.md) — ใช้อ่านที่มาของงาน ไม่ใช้แทนคู่มือปัจจุบัน
