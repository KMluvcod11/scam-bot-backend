# Rich Menu ของ Eh?Bot

เมนู 3 ช่องโทนชมพู–มิ้นต์–ครีม ใช้มาสคอตชุดเดียวกับ Mini App ภาพสำเร็จอยู่ที่
`rich_menu/menu.png` ขนาด 2500 × 843 พิกเซล ไม่เกิน 1 MB ส่วน `menu.svg`
เป็นต้นฉบับที่แก้ไขต่อได้ และ `preview.png` เป็นภาพย่อสำหรับตรวจแบบ

| พื้นที่กดจากซ้าย | การทำงาน | เหตุผล |
|---|---|---|
| x=0, กว้าง 1000 | Postback `menu:check` → `process_menu_check()` | แสดงวิธีส่งข้อความในแชต ไม่เรียก AI และไม่เพิ่มผลตรวจ |
| x=1000, กว้าง 740 | LIFF URL + `/lessons` | เปิด `/mini/result/lessons` ซึ่งเป็นหน้าบทเรียนจริง |
| x=1740, กว้าง 760 | LIFF URL + `/help` | เปิด `/mini/result/help` ซึ่งเป็นหน้าวิธีใช้จริง |

พื้นที่ทั้งหมดสูง 843 พิกเซล รวมความกว้างครบ 2500 พิกเซล ไม่มีปุ่มประวัติทั้งหมด
เพราะระบบยังไม่ได้ให้ผู้ใช้อ่านประวัติทุกเคส ชื่อบนแถบเปิด/ปิดเมนูคือ `เมนู Eh?Bot`

## วิธีทำงานและนำเสนอ

`build_rich_menu(liff_id)` รับ LIFF ID → สร้างขนาดภาพ พื้นที่กด และ action ของแต่ละช่อง
→ คืน dict สำหรับ LINE API ถ้า ID ไม่ถูกต้องจะหยุดก่อนสร้างลิงก์

`line_webhook()` ตรวจลายเซ็นและกัน event ซ้ำตามเดิม เมื่อได้รับ `menu:check` จากแชตส่วนตัว
`_process_text_event()` จะเรียก `process_menu_check()` → ตอบขั้นตอนส่งข้อความผ่าน
`reply_to_line()` เท่านั้น ไม่เรียก `analyze_message()` และไม่สร้างแถวใน `detection_logs`
postback ของกลุ่ม/ห้องจะไม่ตอบวิธีใช้ส่วนตัว หากส่งคำตอบไม่สำเร็จจะบันทึกเฉพาะชนิด error
แล้วทำ event ถัดไปได้

ปุ่มบทเรียนกับวิธีใช้ใช้ `https://liff.line.me/{LIFF_ID}/...` โดย LINE ต่อ path กับ Endpoint
URL หลัง `liff.init()` หน้าลูกอยู่ใต้ `/mini/result` ที่มี route รองรับแล้ว URL ของ Tunnel
จึงอยู่ในการตั้งค่า LIFF ไม่อยู่ในภาพหรือโค้ด Rich Menu

## ก่อนเปิดใช้จริง

1. เปิด Bot API และ Webhook ให้ใช้งานได้ แล้วรีสตาร์ตบอตเพื่อโหลด `process_menu_check()` รุ่นใหม่
2. เปิดเว็บและตั้ง LIFF Endpoint ให้ตรง HTTPS ปัจจุบันตาม `MINI_SETUP.md`
3. ตรวจภาพเมนูและการเรียงปุ่มก่อนเผยแพร่
4. จากโฟลเดอร์ที่มี `main.py` รันคำสั่งตรวจในเครื่อง:

```powershell
python -X utf8 rich_menu_setup.py plan
```

`plan` อ่านรูปกับ `MINI_LIFF_ID` ใน `.env` แล้วแสดง JSON ไม่ติดต่อ LINE และไม่เปลี่ยนเมนู
สคริปต์ไม่ import `config.py` หรือ AI engine

ตรวจ API default Rich Menu ปัจจุบันแบบอ่านอย่างเดียว:

```powershell
python -X utf8 rich_menu_setup.py status
```

`apiDefaultRichMenuId: null` หมายถึงไม่มี default ที่ตั้งผ่าน Messaging API
ไม่ได้ยืนยันว่าไม่มีเมนูจาก LINE Official Account Manager หรือเมนูเฉพาะผู้ใช้

ให้ LINE ตรวจโครงสร้างเมนูโดยไม่สร้างเมนูจริง:

```powershell
python -X utf8 rich_menu_setup.py validate
```

`validate` ส่งเฉพาะโครงสร้างและลิงก์ไปจุดตรวจสอบของ LINE ไม่อัปโหลดรูปและไม่ตั้ง default

## เผยแพร่หลังตรวจแบบแล้ว

คำสั่งนี้เปลี่ยน API default Rich Menu ของบัญชีที่ `CHANNEL_ACCESS_TOKEN` ใน `.env` เป็นเจ้าของ
ผู้ใช้ที่ผูกเมนูเฉพาะรายอาจยังเห็นเมนูของตนเอง:

```powershell
python -X utf8 rich_menu_setup.py publish --apply
```

`publish_menu()` ตรวจขนาดภาพ → อ่าน default เดิม → ให้ LINE ตรวจ JSON → สร้าง Rich Menu
→ เก็บรหัสเก่าและใหม่ใน `rich_menu/deployment.local.json` → อัปโหลด PNG → ตั้ง default ใหม่
→ อ่านกลับเพื่อตรวจว่ารหัสตรงกัน ไม่มีการ retry คำสั่งสร้างอัตโนมัติ

ไฟล์ deployment ไม่มี token และถูก Git ignore เก็บไว้สำหรับย้อนกลับ หากอัปโหลดล้มเหลว
default เดิมยังอยู่ หากขั้นเปิดใช้ล้มเหลว ให้เก็บไฟล์นี้ไว้และตรวจ `status` ก่อนทำต่อ
การสั่งเผยแพร่แบบเดิมซ้ำหลังสำเร็จจะไม่สร้างเมนูเพิ่ม หากมีบันทึกการติดตั้งที่ยังไม่คืนค่า
สคริปต์จะหยุดแทนการเขียนทับทางย้อนกลับ

## ย้อนกลับ

```powershell
python -X utf8 rich_menu_setup.py restore --apply
```

`restore_menu()` ตรวจว่า default ปัจจุบันยังเป็นตัวที่เราติดตั้ง แล้วตั้งรหัสเดิมกลับ
หากเดิมไม่มี API default จะลบเฉพาะการตั้ง default เพื่อให้ LINE เลือกเมนูตามลำดับปกติ
ไม่ลบตัว Rich Menu หรือรูปที่สร้างไว้ หากพบว่ามีคนเปลี่ยนไปใช้เมนูอื่นแล้ว จะหยุดโดยไม่ทับงานนั้น

## ทดสอบ

```powershell
python -m unittest discover -s tests -p test_rich_menu.py
```

ชุดทดสอบจำลอง LINE API/AI/ฐานข้อมูล ตรวจปุ่มเริ่มตรวจ การกันซ้ำ ลายเซ็น การไม่ตอบในกลุ่ม
ขอบเขตพื้นที่กด ลิงก์ LIFF ลำดับอัปโหลดก่อนเปิดใช้ และการย้อนกลับอย่างระมัดระวัง
ไม่ใช่ผลทดสอบการกดจริงบนมือถือ

หลังเผยแพร่ต้องทดสอบบน LINE มือถือทั้ง 3 ปุ่ม รวมการเปิด `/lessons` และ `/help`
จาก LIFF URL จริง หน้า Mini App ยังมีข้อจำกัดเรื่องอายุเคสตาม `MINI_SETUP.md`

ผลตรวจวันที่ 17 ตุลาคม 2569: backend ผ่าน 204 tests ซึ่งจำลองบริการภายนอก
LINE API ตรวจโครงสร้างเมนูและอ่าน default กลับมาตรงกับแบบที่ติดตั้งแล้ว
หลังรีสตาร์ตบอตและตั้ง Webhook ให้ตรงกับ Tunnel ที่ยังเปิดอยู่ ผู้ใช้ยืนยันบน LINE จริงว่า
ปุ่มตรวจข้อความตอบคำแนะนำ และปุ่มเรียนรู้กับวิธีใช้เปิดหน้าถูกต้องทั้งสองปุ่ม
ผลนี้ยืนยันการเชื่อมต่อและเมนู ไม่ใช่ผลวัดความแม่นยำของ AI
Quick Tunnel เปลี่ยน URL เมื่อเปิดใหม่ ต้องปรับ Webhook ของบอตให้ตรงด้วย

`build_menu.cjs` เป็นเครื่องมือทำภาพจาก SVG กับมาสคอตเดิม ใช้ Sharp ตอนส่งออกเท่านั้น
บอตและสคริปต์ติดตั้งใช้ PNG ที่เตรียมแล้ว ไม่ต้องเพิ่ม dependency ของบอต

## เอกสาร LINE

- [ขั้นตอนสร้าง อัปโหลด และตั้ง Rich Menu](https://developers.line.biz/en/docs/messaging-api/using-rich-menus/)
- [ข้อกำหนดรูปภาพและโครงสร้าง Rich Menu](https://developers.line.biz/en/reference/messaging-api/#upload-rich-menu-image)
- [การต่อ path ของ LIFF URL กับ Endpoint](https://developers.line.biz/en/docs/liff/opening-liff-app/)
