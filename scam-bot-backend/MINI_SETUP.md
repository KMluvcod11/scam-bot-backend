# Mini App: เปิดรายละเอียดจากผลเดิมใน LINE

## พฤติกรรมรอบนี้

ส่งข้อความในแชทส่วนตัว → `analyze_message()` คืน `risk_found` → `process_private_event()`
สร้างบทเรียนและรายละเอียด → `LessonStore.add()` คืนรหัสสุ่ม → `reply_to_line()` ส่งปุ่ม
`https://liff.line.me/{LIFF_ID}?case={รหัสสุ่ม}` → หน้า `/mini/result` เริ่ม LIFF →
ส่ง ID token ทาง Authorization header → Bot API ตรวจ token กับ LINE → เทียบเจ้าของ
→ คืนผลเดิมให้หน้าเว็บ ไม่เรียก AI หรือ Vector ซ้ำ และไม่เพิ่ม Dataset จากการเปิดหน้า

ปุ่มมีเฉพาะผล `risk_found` ที่สร้างบทเรียนสำเร็จตามพฤติกรรมเดิม ยังไม่เพิ่มประวัติส่วนตัวทั้งหมด
และไม่เปลี่ยนเกณฑ์การตรวจข้อความ รูปภาพ หรือคำตอบในกลุ่ม

## Webhook ตอบ LINE ก่อนทำงานหนัก

`line_webhook()` อ่าน body เดิมและตรวจลายเซ็นก่อน จากนั้นเลือก event ที่รองรับ
และเรียก `EventGuard.claim_batch()` เพื่อจองรหัสทั้งชุดพร้อมกัน ถ้าที่เก็บเต็ม
จะตอบ 503 โดยไม่จองบางรายการไว้; event ซ้ำจะไม่ถูกวิเคราะห์หรือส่งคำเตือนซ้ำ

เมื่อรับงานแล้ว Webhook ส่ง HTTP 200 ก่อน `process_accepted_events()` เริ่มวิเคราะห์
ส่งคำตอบ และบันทึกประวัติทีละ event งานยังอยู่ในโปรเซสเดียวกับบอต ไม่ใช่คิวถาวร
หากโปรเซสปิดหลังตอบ 200 แต่ก่อนทำงานเสร็จ งานนั้นอาจหายและ LINE อาจไม่ส่งซ้ำ
จึงควรรันหนึ่ง worker ตามขอบเขต Mini App ปัจจุบัน

log `ack_ready_after` คือเวลาจนเตรียมตอบ 200 ส่วน `processing_elapsed` คือเวลาทำงาน
หลังตอบ ไม่ใช่เวลาเดียวกัน หากบันทึกประวัติไม่สำเร็จ `save_detection()` จะพิมพ์
`stage=line_sources` หรือ `stage=detection_logs` พร้อม SQLSTATE/PostgREST code ที่กรองแล้ว
โดยไม่พิมพ์ข้อความผู้ใช้ คีย์ หรือรายละเอียดข้อผิดพลาดจากบริการ การส่งคำตอบ LINE
สำเร็จไม่ได้ยืนยันว่าบันทึกประวัติสำเร็จ

## ค่าที่ต้องตั้ง

ใน `.env` ข้าง `main.py` ของบอต (ไม่ใช่ `.env` ของ Dashboard):

```dotenv
MINI_LIFF_ID=ใส่-LIFF-ID-จริง
LINE_LOGIN_CHANNEL_ID=ใส่-Channel-ID-ของ-LINE-Login
MINI_WEB_ORIGIN=https://โดเมนเว็บของคุณ
```

ใน `.env.local` ที่ราก `Scam-bot-frontend`:

```dotenv
VITE_MINI_LIFF_ID=ใส่-LIFF-ID-เดียวกัน
VITE_MINI_API_BASE_URL=https://โดเมน-Bot-API-ของคุณ
```

ค่าตัวอย่างข้างบนเป็นคำอธิบาย ต้องแทนด้วยค่าจริง ส่วน `VITE_` เปิดเผยในเบราว์เซอร์ได้
จึงใส่เฉพาะ LIFF ID และ origin ไม่ใส่ Channel secret, Channel access token, Gemini key,
Supabase key หรือรหัส Dashboard

ถ้าใช้ reverse proxy โดเมนเดียวกับเว็บ ให้เว้น `VITE_MINI_API_BASE_URL` และส่ง `/api/mini/*`
ไป Bot API ตัวเดียวกับที่รับ webhook โดยเก็บ path เดิม การชี้ไป Dashboard API จะเปิดเคสไม่ได้
Vite ในเครื่องตั้ง `/api/mini` ไป `127.0.0.1:8001` และ `/api` ส่วนอื่นไป Dashboard ที่ `8000`
หาก Bot API ของเครื่องใช้พอร์ตอื่น ให้ปรับ proxy ให้ตรงกัน

หลังเปลี่ยน environment ต้องรีสตาร์ตบอตและ Vite; production ต้อง build เว็บใหม่
ยังไม่ตั้ง LIFF ID/Channel ID บอตจะใช้ปุ่มบทเรียนในแชทแบบเดิม เพื่อให้ยังใช้งานได้ระหว่างตั้งค่า

## ตั้ง LINE Developers

1. ใช้ LINE Login channel ใน Provider เดียวกับ Messaging API ของบอต
2. เพิ่ม LIFF app ขนาด Full เลือก scope `openid`
3. Endpoint URL เป็น `https://โดเมนเว็บของคุณ/mini/result` ไม่มี query หรือ fragment
4. นำ LIFF ID และ LINE Login Channel ID มาใส่ค่าข้างต้น
5. ถ้า channel อยู่ระหว่างพัฒนา ให้บัญชีที่ทดสอบมีสิทธิ์ทดสอบใน channel นั้น
6. เว็บต้องให้การเปิด `/mini/result` โดยตรงคืน `index.html` ของ SPA ด้วย
7. ส่งข้อความตรวจใหม่ แล้วทดสอบปุ่มใหม่ภายใน 15 นาที ปุ่ม postback เก่าไม่เปลี่ยนย้อนหลัง

Channel ID ของ Messaging API, Provider ID และ LIFF ID เป็นคนละค่า
เลขที่ใช้ตรวจ ID token ต้องเป็น Channel ID ของ LINE Login ที่ออก token ให้เว็บนี้

## รับอะไร / ทำอะไร / คืนอะไร / ถ้าพัง

| ฟังก์ชัน | รับและทำอะไร | คืนอะไร / เมื่อผิดพลาด |
|---|---|---|
| `lesson_points(text)` | เลือกไม่เกิน 3 หัวข้อจากคำที่มีจริง | การ์ดคำแนะนำ ไม่ถือคำที่พบเป็นหลักฐาน Scam |
| `build_case_detail(text, result, received_at)` | จัดผลเดิมที่ผ่าน `build_lesson()` แล้วเป็นข้อมูลหน้าเว็บ | dict ที่มีข้อความ เวลา reason และคำแนะนำ ไม่มีการเรียก AI |
| `LessonStore.add(owner, lesson, detail=...)` | คัดลอกข้อมูลเข้า RAM พร้อมเจ้าของและอายุ | รหัสสุ่ม; ไม่มีเจ้าของหรือเต็ม คืน None และไม่เพิ่มปุ่ม |
| `LessonStore.get_detail(case_id, owner)` | ล้างเคสหมดอายุแล้วเทียบเจ้าของ | สำเนารายละเอียด หรือ None; ไม่ส่ง owner ให้เว็บ |
| `get_mini_case_url(case_id)` | ตรวจรูปแบบ ID จาก environment และรหัสเคส | URL ที่ไม่มีข้อความ/user ID/token; ตั้งค่าไม่ครบคืน None |
| `verify_line_owner(authorization)` | ส่ง ID token ให้ LINE ตรวจด้วย client_id ฝั่ง server แล้วตรวจ aud/iss/exp/sub | เจ้าของจาก `sub`; ผิด/หมดอายุ 401, ยังไม่ตั้งค่าหรือ LINE ขัดข้อง 503 |
| `read_case(case_id, authorization)` | ตรวจตัวตนก่อนอ่านเคสของเจ้าของ | JSON + no-store; ไม่พบ/ผิดเจ้าของ/หมดอายุ ตอบ 404 ข้อความเดียวกัน |

เช่น ผู้ใช้ A ตรวจข้อความ 2 ครั้ง ปุ่มของครั้งแรกยังเปิดผลครั้งแรก;
ผู้ใช้ B ได้ URL เดียวกันก็อ่านผลของ A ไม่ได้ ไม่ยอมรับ user ID จาก query มาใช้เป็นสิทธิ์

## ข้อจำกัดและการทดสอบ

- เก็บเคสใน RAM process เดียว อายุ 900 วินาที สูงสุด 1,000 เคส รีสตาร์ตแล้วหาย
- รัน bot เป็น **1 worker / 1 instance** ในรอบนี้ API กับ webhook ต้องเข้าถึง store เดียวกัน
- `get_detail()` ตรวจอายุเมื่อขออ่าน ไม่สามารถถอนข้อมูลที่ผู้ใช้โหลดไปแล้วได้
- อ่านเคสไม่เขียนฐานข้อมูลเพิ่ม แต่การตรวจข้อความยังบันทึกประวัติตาม `save_detection()` เดิม
- `MINI_WEB_ORIGIN` รับ origin เดียว CORS ไม่ใช้ wildcard; CORS ไม่ใช้แทนการตรวจ token
- ก่อนเปิดสาธารณะ ให้โฮสต์ผ่าน HTTPS และป้องกันจำนวนคำขอที่ reverse proxy ตามสภาพใช้งาน

รันจากโฟลเดอร์ที่มี `main.py`:

```powershell
python -m unittest discover -s tests
```

ผลวันที่ 16 ตุลาคม 2569: 154 tests ผ่าน 153 มี 1 failure เดิม
`test_non_text_and_empty_events_are_skipped` (คาด 200 แต่ได้ 400 สำหรับ image event)
ตรวจด้วย `main.py` จาก HEAD ก่อนงาน Mini App แล้วยังพบ failure เดียวกัน จึงไม่แก้ส่วนรูปภาพในงานนี้
tests ใหม่ `test_mini_api.py` ทั้ง 10 ข้อผ่าน และ tests บทเรียนเดิมทั้ง 14 ข้อผ่าน
ทั้งหมดจำลอง LINE/AI/ฐานข้อมูล ไม่ได้ยืนยัน LINE Login จริงหรือความแม่นยำ AI

## เอกสารอ้างอิง

- [ใช้ ID token บน server](https://developers.line.biz/en/docs/liff/using-user-profile/)
- [ตรวจ ID token ด้วย LINE Login API](https://developers.line.biz/en/reference/line-login/#verify-id-token)
- [LIFF URL และ redirect](https://developers.line.biz/en/docs/liff/opening-liff-app/)
- [User ID ภายใต้ Provider เดียวกัน](https://developers.line.biz/en/docs/messaging-api/getting-user-ids/)
