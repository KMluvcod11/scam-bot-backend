# ข้อมูลผลตรวจสำหรับ Backend และ Dashboard

บอตบันทึกข้อความประเภท text ที่ประมวลผลแล้วหนึ่งแถวต่อ `webhookEventId` ของ LINE ใน
`public.detection_logs` ส่วน `public.scam_dataset` ยังเป็นชุดตัวอย่างสำหรับค้นหาเทียบเคียง
ห้ามนำผลตรวจของผู้ใช้ไปเพิ่มในชุดตัวอย่างอัตโนมัติ

## ฟิลด์หลัก

| ฟิลด์ | ความหมาย |
| --- | --- |
| `id` | UUID ของผลตรวจที่ฐานข้อมูลสร้าง |
| `line_event_id` | รหัสเหตุการณ์ LINE; unique เพื่อกันแถวซ้ำแม้ LINE ส่งซ้ำหรือบอตรีสตาร์ต |
| `source_id`, `source_type` | อ้างอิง `line_sources`; `group`, `room` หรือ `user` |
| `message_text`, `message_preview` | ข้อความที่ตรวจฉบับเต็มและตัวอย่าง 160 ตัวอักษร; เฉพาะผู้ดูแลที่ได้รับสิทธิ์อ่าน |
| `received_at` | เวลาเหตุการณ์จาก LINE เป็น UTC |
| `detection_status` | `bypassed`, `conversation`, `no_risk_found`, `risk_found`, `uncertain`, `error` |
| `is_scam` | `true` เมื่อบอตพบความเสี่ยง, `false` เมื่อไม่แจ้งเตือน, `null` เมื่อตรวจไม่สำเร็จ |
| `risk_level`, `reason` | ระดับและเหตุผลตามผลวิเคราะห์ หากบอตส่งค่ามา |
| `decision_method`, `similarity_percent`, `matched_label` | วิธีตัดสินและหลักฐานประกอบ; ตอนนี้บอตยังไม่คืนคะแนนและวิธีส่วนใหญ่เป็น `unknown` จึงเป็น `null` ได้ |
| `warning_attempted`, `warning_sent` | การพยายามตอบ LINE และผลที่ LINE API ยอมรับ; สำหรับแชตส่วนตัวนับคำตอบทุกแบบ |
| `error_stage` | ขั้นตอนที่ตรวจไม่สำเร็จ โดยไม่บันทึกข้อความ error ดิบ |

`similarity_percent` คือคะแนนความคล้ายกับตัวอย่างในฐานข้อมูล ไม่ใช่ความมั่นใจว่าเป็นมิจฉาชีพ
แดชบอร์ดไม่ควรแสดงเป็นเปอร์เซ็นต์ความมั่นใจ เมื่อค่าเป็น `null` ให้แสดงว่าไม่มีคะแนน

`line_sources` เก็บรหัสต้นทางที่ LINE ส่งมา และเวลาล่าสุดที่พบ ส่วนชื่อกลุ่มกับจำนวนสมาชิก
ยังเป็น `null` จนกว่าจะเพิ่มการเรียก LINE API เพื่อเติมข้อมูลเหล่านั้น

## เปิดใช้งาน

1. รัน `dashboard_schema.sql` ใน SQL Editor ของ Supabase อีกครั้งเพื่อให้การตั้งค่าสิทธิ์ของ view ล่าสุดมีผล
2. ตั้ง `SUPABASE_HISTORY_KEY` เป็น service role key ในสภาพแวดล้อมของ Backend เท่านั้น และรีสตาร์ตบอต
3. ส่งข้อความ text ผ่าน LINE หนึ่งครั้ง แล้วดูแถวใหม่ใน `line_sources` และ `detection_logs`
4. ส่งเหตุการณ์ `webhookEventId` เดิมอีกครั้ง: จำนวนแถวใน `detection_logs` ต้องไม่เพิ่ม

ห้ามใส่ service role key ในโค้ดหน้า Dashboard หรือ commit ลง Git ส่วนบัญชี Dashboard
ต้องอยู่ใน `dashboard_admins` ก่อนอ่านประวัติผ่าน Supabase ได้
