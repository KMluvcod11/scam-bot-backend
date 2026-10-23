# เอกสารโปรเจกต์

เริ่มติดตั้ง รันบอต และทดสอบจาก [README หลัก](../README.md)
คำสั่งในเอกสารแต่ละฉบับให้รันจากโฟลเดอร์ที่เอกสารนั้นระบุ

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
- [บันทึกความคืบหน้า Backend วันที่ 30 กันยายน 2026](../supabase/BACKEND_PROGRESS_2026-09-30.md)

## ชุดข้อมูล

- [ชุดข้อมูลข่าวสังเคราะห์](../scam-ai-engine/news_dataset/README.md)
- [ชุดข้อมูลขยาย 1,000 รายการ](../scam-ai-engine/news_dataset/expanded_1000/README.md)

## แบบและแผนงาน Mini App

- [แบบประวัติผลตรวจถาวร](superpowers/specs/2026-10-23-mini-persistent-history-design.md)
- [แผนดำเนินงานประวัติผลตรวจถาวร](superpowers/plans/2026-10-23-mini-persistent-history.md)
