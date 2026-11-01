# สารบัญโค้ด linebot

เริ่มจาก [README หลัก](../README.md) สำหรับติดตั้ง และ [คู่มือแต่ละส่วน](README.md) สำหรับตั้งค่า
ไฟล์แอปและคำสั่งรันคงตำแหน่งเดิม การจัดรอบนี้แยกเฉพาะเอกสารย้อนหลังและเพิ่มคำอธิบายโค้ด

## โฟลเดอร์แต่ละส่วน

```text
linebot/
├── scam-bot-backend/         บอต, Webhook, Mini API และโมดูลวิเคราะห์
│   ├── scripts/             เครื่องมือที่ต้องสั่งรันเอง
│   ├── tests/               ทดสอบด้วยบริการจำลอง
│   └── rich_menu/           ต้นฉบับภาพ เมนูที่สร้างแล้ว และเครื่องมือสร้างภาพ
├── scam-ai-engine/          เตรียม แปล และอัปโหลดชุดข้อมูล
│   ├── news_dataset/        ตัวอย่างสังเคราะห์ แหล่งอ้างอิง และตัวสร้างข้อมูล
│   └── tests/               ทดสอบสคริปต์โดยไม่อัปโหลดจริง
├── supabase/                SQL และสัญญาข้อมูลของฐานข้อมูล
├── automation/              เครื่องมือ n8n ที่แยกจากการเปิดบอต
└── docs/
    ├── backend/            คู่มือใช้งานแต่ละฟีเจอร์
    └── archive/            บันทึกความคืบหน้าและแผนเดิม
```

`.env` เป็นค่าลับในเครื่อง ส่วน `.env.example` เป็นแบบฟอร์มที่ส่งต่อได้
`.venv`, `.venv-1`, `scam-ai-engine/venv` และ `node_modules` เป็น environment/dependencies ไม่ใช่โค้ดที่เราเขียน
ยังเก็บไว้เพราะไม่ยืนยันว่าเลิกใช้แล้ว เช่นเดียวกับ `.runtime` ของ n8n ที่อาจมี workflow/credentials
`cloudflared.exe` เป็นเครื่องมือ tunnel ไม่ใช่ไฟล์ขยะ

## เริ่มอ่านตามเส้นทางการทำงาน

| งาน | ลำดับฟังก์ชันที่ควรเปิดอ่าน |
|---|---|
| ข้อความ LINE | `main.line_webhook` → `parse_webhook` → `EventGuard.claim_batch` → `process_accepted_events` → `process_text_event` |
| วิเคราะห์ข้อความ | `detector.analyze_message` → `url_checker.check_url` → `find_similarity` → `analyze_with_llm` → `validate_llm_result` |
| วิเคราะห์รูป | `main._process_text_event` → `messaging.get_image_content` → `detector.extract_text_from_image` → `analyze_message` |
| ส่งผลและเก็บประวัติ | `main.private_reply`/`image_reply` → `flex_cards.build_result_card` → `messaging.reply_to_line` → `detection_history.save_detection` |
| อ่านเคสใน Mini App | `mini_api.verify_line_owner` → `mini_history.get_case` → `learning.build_case_detail` |
| กลุ่มเข้า/ออกและสมาชิก | `main.process_accepted_events` → `save_group_join`/`save_group_leave`/`save_group_members` |

นี่คือลำดับเพื่อหาโค้ด ไม่ได้หมายความว่าทุกข้อความเรียกครบทุกขั้น กฎข้าม คำทักทาย และ error อาจจบก่อน

## เครื่องมือที่ต้องสั่งรันเอง

| ไฟล์ | ผลกระทบเมื่อรัน |
|---|---|
| [compare_detection_inputs.py](../scam-bot-backend/scripts/compare_detection_inputs.py) | เรียก Gemini และค้น Supabase จริง; เขียนรายงานลง temp; ไม่ส่ง LINE หรือเพิ่ม Dataset |
| [rag_evaluation_cases.json](../scam-bot-backend/scripts/rag_evaluation_cases.json) | ข้อความสังเคราะห์ 12 เคสสำหรับ `--evaluation`; label เป็นเกณฑ์ทดสอบที่เสนอ ไม่ใช่ผลรับรองความแม่นยำ |
| [smoke_search.py](../scam-bot-backend/scripts/smoke_search.py) | ใช้โควตา Gemini และอ่านผลค้นจริง |
| [smoke_history.py](../scam-bot-backend/scripts/smoke_history.py) | เขียนประวัติสังเคราะห์ลงฐานข้อมูลจริง แล้วอ่านตรวจการกันซ้ำ |
| [sync_group_members.py](../scam-bot-backend/scripts/sync_group_members.py) | อ่านจำนวนสมาชิกจาก LINE และเติมค่าในฐานข้อมูลจริงเฉพาะกลุ่มที่ยังว่าง |
| [rich_menu_setup.py](../scam-bot-backend/rich_menu_setup.py) | `plan` ตรวจในเครื่อง; `status`/`validate` เรียก LINE; `publish --apply`/`restore --apply` เปลี่ยนเมนูจริง |
| [build_menu.cjs](../scam-bot-backend/rich_menu/build_menu.cjs) | `main` สร้าง SVG/PNG/ภาพ preview ในเครื่อง; `mascot` แปลง PNG เป็น data URL; ไม่ติดตั้งเมนู LINE |
| [upload_to_supabase.py](../scam-ai-engine/upload_to_supabase.py) | อ่าน CSV สร้าง embedding และเพิ่มข้อความใหม่ลง Dataset จริง |
| [translate_phishing.py](../scam-ai-engine/translate_phishing.py) | เรียกโมเดลแปลข้อความและเขียนผล/แถวที่ล้มเหลวเป็น CSV |
| [build_dataset.py](../scam-ai-engine/news_dataset/build_dataset.py) | สร้างไฟล์ชุดตัวอย่างสังเคราะห์ 36 รายการในเครื่อง |
| [build_expanded.py](../scam-ai-engine/news_dataset/expanded_1000/build_expanded.py) | สร้างชุดขยายและรายงาน; ต้องมี `tmp/supabase_dataset_snapshot.json` ที่สคริปต์อ้างก่อนรัน |
| [start-n8n.ps1](../automation/n8n/start-n8n.ps1) | เปิด n8n ในเครื่องและใช้ข้อมูล `.runtime`; ไม่ใช่ส่วนที่ต้องเปิดเพื่อรับ webhook บอต |
| [compose.yaml](../automation/n8n-docker/compose.yaml) | นิยาม n8n และ runner สำหรับ Docker พร้อม volume เก็บข้อมูล |

เก็บ CSV/JSONL และรายงานเดิมไว้เพื่ออ้างอิงที่มาของ Dataset ไม่ควรลบเพียงเพราะไม่มี import จากบอต
SQL ใน [supabase](../supabase/) เป็นโครงสร้างและบันทึกการเปลี่ยนสิทธิ์ ไม่ได้รันอัตโนมัติตอนเปิดบอต

## วิธีอ่านคำอธิบายฟังก์ชัน

ฟังก์ชัน Python ที่เขียนในโปรเจกต์ 526 จุด (รวม methods, helper และ tests) มีคำอธิบายไทยใน docstring เดิมหรือคอมเมนต์เหนือฟังก์ชัน
ไม่รวมฟังก์ชันจาก dependencies หรือ lambda สั้นที่ใช้ประกอบ mock/เงื่อนไข
คอมเมนต์ที่เพิ่มเป็น `# ชื่อฟังก์ชัน: หน้าที่` เพื่อค้นด้วยชื่อจริงได้ และไม่เปลี่ยน docstring ที่ framework อาจใช้งาน

ตัวอย่าง `redact_phone(text)` รับข้อความหรือ `None` → ปกปิดเบอร์มือถือไทยที่มีคำกำกับ → คืนข้อความใหม่หรือ `None`
ข้อจำกัดคือไม่ครอบคลุมข้อมูลส่วนตัวทุกชนิด และไม่ได้แก้ประวัติเก่า
ส่วน `save_detection(event, result, ...)` เตรียมแถวประวัติและเขียนตาม event ID → คืน `True` เมื่อเรียกบันทึกสำเร็จ
หากเขียนล้มเหลวจะ log ขั้นตอน/ชนิด error ที่อนุญาตและคืน `False` แทนการหยุด webhook

## ฟังก์ชันแอปและสคริปต์

ตารางนี้ใช้ชื่อจริงเพื่อค้นใน editor; เลขบรรทัดในลิงก์อาจเปลี่ยนเมื่อแก้โค้ดในอนาคต
`config.py` ไม่มีฟังก์ชัน: โหลดและตรวจค่าตั้งต้นให้โมดูลอื่นใช้
`scripts/sync_group_members.py` ไม่มีฟังก์ชันที่นิยามเอง: เรียก `sync_missing_group_members` เมื่อสั่งรันไฟล์

### scam-ai-engine/news_dataset/build_dataset.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`main`](../scam-ai-engine/news_dataset/build_dataset.py#L77) | สร้างตัวอย่างข่าวสังเคราะห์ 36 รายการ ตรวจจำนวนและข้อความซ้ำ แล้วเขียน CSV/JSONL พร้อมแหล่งอ้างอิง |

### scam-ai-engine/news_dataset/expanded_1000/build_expanded.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`normalize`](../scam-ai-engine/news_dataset/expanded_1000/build_expanded.py#L357) | ปรับ Unicode ช่องว่าง และตัวพิมพ์เพื่อใช้เทียบข้อความซ้ำ; คืนข้อความมาตรฐาน |
| [`export_csv`](../scam-ai-engine/news_dataset/expanded_1000/build_expanded.py#L361) | เขียนรายการข้อมูลตามคอลัมน์ที่กำหนดเป็น CSV แบบ UTF-8 BOM; ข้ามคอลัมน์ส่วนเกิน |
| [`main`](../scam-ai-engine/news_dataset/expanded_1000/build_expanded.py#L368) | อ่าน snapshot และชุดเดิม สร้างตัวอย่าง 1,000 รายการ แล้วส่งออกชุดข้อมูลและรายงานตรวจคุณภาพ |

### scam-ai-engine/translate_phishing.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`translate_to_line`](../scam-ai-engine/translate_phishing.py#L10) | แปลงอีเมลหนึ่งแถวเป็นข้อความ LINE ภาษาไทยด้วยโมเดล; ลองสูงสุดสามครั้งก่อนส่ง exception ต่อ |
| [`translate_rows`](../scam-ai-engine/translate_phishing.py#L54) | แปลทีละแถว แยกผลสำเร็จและข้อผิดพลาดลง CSV; บันทึกเมื่อถูกขัดจังหวะและคืน exit code |
| [`translate_rows.save_progress`](../scam-ai-engine/translate_phishing.py#L59) | บันทึกรายการแปลสำเร็จและเลขแถวที่แปลไม่สำเร็จลงไฟล์ผลลัพธ์สองไฟล์ |
| [`main`](../scam-ai-engine/translate_phishing.py#L80) | ตรวจ CSV และกันเขียนทับผลเดิมก่อนตั้งค่าโมเดลเพื่อแปล; คืน exit code เมื่อจบหรือผิดพลาด |

### scam-ai-engine/upload_to_supabase.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`select_new_rows`](../scam-ai-engine/upload_to_supabase.py#L18) | ตรวจ label และอ่านข้อมูลเดิมทุกหน้า; คืนเฉพาะข้อความใหม่ไม่ซ้ำ หรือยก error เมื่อข้อมูลขัดแย้ง |
| [`get_embedding`](../scam-ai-engine/upload_to_supabase.py#L54) | ส่งข้อความให้ Gemini สร้างเวกเตอร์ 768 มิติ; คืนเวกเตอร์เมื่อขนาดและตัวเลขถูกต้อง |
| [`main`](../scam-ai-engine/upload_to_supabase.py#L68) | อ่าน CSV → เลือกแถวใหม่ → embedding → insert; คืน exit code. |

### scam-bot-backend/bot_observability.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`error_summary`](../scam-bot-backend/bot_observability.py#L19) | คืนเฉพาะชนิด error และรหัสที่อนุญาตสำหรับ log โดยไม่รวมข้อความหรือรายละเอียดลับ |
| [`log`](../scam-bot-backend/bot_observability.py#L34) | ContextVar แยกรหัสแต่ละงาน และถูกส่งต่อไปยัง AnyIO thread pool. |
| [`timed_call`](../scam-bot-backend/bot_observability.py#L40) | จับเวลาโดยคงค่า return/exception เดิม; returned ไม่ใช่การยืนยัน HTTP success. |

### scam-bot-backend/detection_history.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`_history_client`](../scam-bot-backend/detection_history.py#L18) | สร้างและเก็บ client เขียนประวัติไว้ใช้ซ้ำ โดยกำหนด timeout ของ PostgREST สิบวินาที |
| [`_source`](../scam-bot-backend/detection_history.py#L27) | อ่านชนิดแชตจาก event แล้วคืนคู่ชนิดและรหัส user/group/room ที่ตรงกัน |
| [`_status`](../scam-bot-backend/detection_history.py#L35) | แปลงผลตรวจเป็นสถานะที่บันทึกได้ โดยแยก error, uncertain และข้อความกลุ่มที่ข้ามการตรวจ |
| [`save_group_join`](../scam-bot-backend/detection_history.py#L49) | เก็บกลุ่มก่อนดึงชื่อ; ไม่สร้าง detection_logs เพราะ join ไม่ใช่ข้อความ. |
| [`save_group_members`](../scam-bot-backend/detection_history.py#L75) | บันทึกจำนวนล่าสุดจาก LINE โดยไม่บวก/ลบซ้ำจาก webhook ที่ส่งซ้ำ. |
| [`sync_missing_group_members`](../scam-bot-backend/detection_history.py#L96) | เติมจำนวนสมาชิกของกลุ่มเดิมที่ยังเป็น null; ไม่แก้ประวัติข้อความ. |
| [`save_group_leave`](../scam-bot-backend/detection_history.py#L122) | ซ่อนกลุ่มที่บอตออก โดยไม่ลบกลุ่ม ชื่อ หรือประวัติการตรวจ. |
| [`redact_phone`](../scam-bot-backend/detection_history.py#L139) | ปกปิดเฉพาะเบอร์มือถือไทยที่มีคำกำกับ เพื่อลดการจับเลขทั่วไปผิด. |
| [`save_detection`](../scam-bot-backend/detection_history.py#L152) | รับ event และผลตรวจ ปกปิดเบอร์ที่มีคำกำกับ แล้วบันทึกครั้งเดียวต่อ event; คืน False เมื่อบันทึกไม่สำเร็จ |

### scam-bot-backend/detector.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`extract_text_from_image`](../scam-bot-backend/detector.py#L43) | อ่านข้อความในรูป; คืนสถานะ ok, uncertain หรือ error พร้อมข้อความ. |
| [`DetectionUnavailable.__init__`](../scam-bot-backend/detector.py#L101) | เก็บชื่อขั้นตอนและชนิดข้อผิดพลาดสำหรับแจ้งว่าตรวจไม่ได้ โดยไม่เก็บ error ดิบ |
| [`analyze_message`](../scam-bot-backend/detector.py#L110) | ตรวจลิงก์และเลือกเส้นทางกฎ/เวกเตอร์/LLM ตามชนิดแชต; คืนผลตรวจหรือสถานะตรวจไม่ได้ |
| [`find_similarity`](../scam-bot-backend/detector.py#L187) | คืน (คะแนน, label, ข้อความตัวอย่าง); ไม่พบคืน (0.0, None, ""). |
| [`validate_llm_result`](../scam-bot-backend/detector.py#L246) | รับ JSON ที่แปลงแล้ว; คืน dict เดิมเมื่อถูกต้อง หรือยก ValueError เพื่อลองโมเดลถัดไป. |
| [`analyze_with_llm`](../scam-bot-backend/detector.py#L269) | ลองโมเดลตามลำดับ; ใช้กฎสำรองเมื่อทุกโมเดลล้มเหลว. |

### scam-bot-backend/event_guard.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`EventGuard.__init__`](../scam-bot-backend/event_guard.py#L10) | ตรวจอายุและความจุที่เป็นบวก แล้วเตรียมชุดงานกำลังทำ งานเสร็จ และ lock สำหรับกัน event ซ้ำ |
| [`EventGuard.claim_batch`](../scam-bot-backend/event_guard.py#L20) | จองทั้งชุดพร้อมกัน; ถ้าที่ไม่พอจะไม่จองบางส่วนแล้วตอบ 503. |
| [`EventGuard.claim`](../scam-bot-backend/event_guard.py#L45) | ทางเรียกเดิมสำหรับหนึ่ง event; คืน new, duplicate หรือ full. |
| [`EventGuard.finish`](../scam-bot-backend/event_guard.py#L50) | จำว่าเคยพยายามทำแล้ว แม้ตรวจ/ส่งไม่สำเร็จ ตามนโยบายไม่ retry อัตโนมัติ. |

### scam-bot-backend/flex_cards.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`shorten`](../scam-bot-backend/flex_cards.py#L38) | รวมช่องว่างให้เป็นบรรทัดเดียว แล้วตัดให้ไม่เกิน limit ตัวอักษร โดยไม่ตัดกลางพยางค์ไทย. |
| [`reason_items`](../scam-bot-backend/flex_cards.py#L56) | แยกเหตุผลเป็นข้อ ๆ ตามขึ้นบรรทัดใหม่หรือ • ที่มากับผลตรวจ ไม่มีก็เป็นข้อเดียว. |
| [`asset_url`](../scam-bot-backend/flex_cards.py#L73) | รูปอยู่ใน public/ ของเว็บ Mini App; LINE ดึงรูปได้เฉพาะ HTTPS. |
| [`mascot_url`](../scam-bot-backend/flex_cards.py#L85) | คืน URL รูปมาสคอตตามชื่อท่าทาง หรือ None เมื่อยังไม่มีต้นทาง HTTPS ที่ใช้ได้ |
| [`note_heading`](../scam-bot-backend/flex_cards.py#L89) | หัวกรอบคำเตือน/คำแนะนำ; มีไอคอนเมื่อโหลดรูปได้ ไม่งั้นเป็นตัวหนังสืออย่างเดียว. |
| [`detail_action`](../scam-bot-backend/flex_cards.py#L100) | ปุ่มเปิด Mini App ถ้าตั้งค่าครบ; ไม่ครบใช้ postback บทเรียนในแชตแทน (ถ้าอนุญาต). |
| [`section_title`](../scam-bot-backend/flex_cards.py#L114) | แปลงข้อความหัวข้อเป็นองค์ประกอบ Flex แบบตัวหนา โดยใช้สีและขนาดร่วมของการ์ด |
| [`bullet`](../scam-bot-backend/flex_cards.py#L119) | จัดข้อความหนึ่งข้อเป็นแถว Flex พร้อมจุดนำหน้าและเปิดการตัดบรรทัด |
| [`card_style`](../scam-bot-backend/flex_cards.py#L126) | เลือกแบบการ์ดจากสถานะ; ผลที่เตือน (is_scam=True เช่นกฎสำรองในกลุ่ม) ใช้แบบพบสัญญาณเสี่ยงเสมอ. |
| [`build_result_card`](../scam-bot-backend/flex_cards.py#L134) | รับผลตรวจ คืน Flex Message หนึ่งข้อความ หรือ None ถ้าสถานะนี้ไม่ใช้การ์ด. |

### scam-bot-backend/learning.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`case_category`](../scam-bot-backend/learning.py#L14) | แยกประเภทเคสให้หน้า Mini App: มีลิงก์ = 'link', ไม่มี = 'message' (ไม่ได้ตัดสินความเสี่ยง). |
| [`lesson_points`](../scam-bot-backend/learning.py#L21) | คำที่พบใช้เลือกคำแนะนำเท่านั้น ไม่ใช้ตัดสินความเสี่ยงซ้ำ. |
| [`build_lesson`](../scam-bot-backend/learning.py#L49) | เลือกหัวข้อจากคำที่มีจริง ไม่ใช้คีย์เวิร์ดตัดสินว่าเป็นมิจฉาชีพ. |
| [`build_case_detail`](../scam-bot-backend/learning.py#L87) | รับผลเดิม 3 สถานะ (เสี่ยง/ควรตรวจเพิ่ม/ยังไม่พบ) จัดข้อมูลสำหรับหน้าเว็บโดยไม่เรียก AI. |
| [`LessonStore.__init__`](../scam-bot-backend/learning.py#L108) | เตรียมที่เก็บบทเรียนใน RAM พร้อมอายุ ความจุ และ lock; ปฏิเสธค่าขีดจำกัดที่ไม่เป็นบวก |
| [`LessonStore._expire`](../scam-bot-backend/learning.py#L116) | นำเคสที่หมดอายุด้านหน้าคิวออกจาก RAM ตามเวลาปัจจุบัน |
| [`LessonStore.add`](../scam-bot-backend/learning.py#L121) | case_id: ใช้รหัสเดียวกับแถวใน detection_logs ถ้ามี (ไม่ส่ง = สุ่มใหม่). |
| [`LessonStore.get`](../scam-bot-backend/learning.py#L136) | คืนบทเรียนเฉพาะเคสที่ยังไม่หมดอายุและตรงเจ้าของ; กรณีอื่นคืน None เหมือนกัน |
| [`LessonStore.get_detail`](../scam-bot-backend/learning.py#L146) | คืนสำเนารายละเอียดพร้อมรหัสเคสให้เจ้าของที่ตรงกันเท่านั้น หรือ None เมื่อเปิดไม่ได้ |

### scam-bot-backend/main.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`parse_webhook`](../scam-bot-backend/main.py#L49) | ตรวจลายเซ็นจาก body เดิมก่อนอ่าน JSON แล้วตรวจรูปแบบที่บอทต้องใช้. |
| [`root`](../scam-bot-backend/main.py#L145) | คืนสถานะว่า FastAPI ทำงานอยู่; ไม่ได้ตรวจความพร้อมของ LINE, Gemini หรือฐานข้อมูล |
| [`line_webhook`](../scam-bot-backend/main.py#L151) | ตรวจลายเซ็นและ payload จอง event ใหม่ แล้วตอบ HTTP 200 ก่อนประมวลผลเบื้องหลัง; ที่เก็บเต็มตอบ 503 |
| [`process_accepted_events`](../scam-bot-backend/main.py#L207) | ทำงานหลังส่ง HTTP 200; จบทีละ event และปล่อย ID แม้ขั้นใดเกิดข้อผิดพลาด. |
| [`process_text_event`](../scam-bot-backend/main.py#L227) | สร้างรหัสสุ่มเฉพาะงาน ไม่ใช้ LINE user ID หรือ token เป็นรหัส log. |
| [`_process_text_event`](../scam-bot-backend/main.py#L246) | วิเคราะห์และตอบหนึ่ง event; แยกไว้เพื่อให้ Webhook จัดการการกันซ้ำได้ชัดเจน. |
| [`private_reply`](../scam-bot-backend/main.py#L465) | สร้างคำตอบจากสถานะชัดเจน ไม่แปลง False หรือ fallback เป็นคำรับรอง. |
| [`image_reply`](../scam-bot-backend/main.py#L494) | สร้างคำตอบสำหรับข้อความในรูป โดยยังไม่ส่ง LINE. |
| [`case_id_for`](../scam-bot-backend/main.py#L528) | รหัสเคสคงที่ต่อ event: LINE ส่ง event ซ้ำหลังรีสตาร์ตก็ได้รหัสเดิม ตรงกับแถวที่บันทึกไว้แล้ว. |
| [`open_result_case`](../scam-bot-backend/main.py#L533) | เก็บเคสให้ Mini App แล้วสร้างการ์ดผลตรวจ คืน (case_id, card, has_lesson). |
| [`group_card`](../scam-bot-backend/main.py#L563) | การ์ดเตือนในกลุ่ม: ไม่มีปุ่มรายละเอียด ไม่เปิดเคสส่วนตัว; สร้างไม่ได้ก็ส่งข้อความธรรมดา. |
| [`process_private_event`](../scam-bot-backend/main.py#L572) | ตอบส่วนตัวและเพิ่มปุ่มเฉพาะผลที่มีบทเรียน โดยไม่เปลี่ยนผลตรวจเดิม. |
| [`process_menu_check`](../scam-bot-backend/main.py#L609) | ปุ่มเริ่มตรวจแสดงวิธีส่งข้อความ ไม่สร้างผลตรวจหรือเรียก AI. |
| [`process_learning_event`](../scam-bot-backend/main.py#L627) | รหัสเคสไม่ใช่สิทธิ์: ต้องตรวจ LINE user ID จาก webhook ที่ผ่านลายเซ็นด้วย. |

### scam-bot-backend/messaging.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`get_image_content`](../scam-bot-backend/messaging.py#L12) | ดาวน์โหลดรูปไว้ในหน่วยความจำ; คืนข้อมูลรูปกับชนิดไฟล์ หรือ None. |
| [`get_group_member_count`](../scam-bot-backend/messaging.py#L62) | ดึงจำนวนสมาชิกที่ไม่รวมบอต; ถ้าดึงไม่ได้คืน None เพื่อรักษาค่าเดิม. |
| [`get_group_name`](../scam-bot-backend/messaging.py#L83) | อ่านชื่อกลุ่มจาก LINE; ล้มเหลวคืน None ไม่พิมพ์ token/ชื่อกลุ่มใน log. |
| [`get_sender_display_name`](../scam-bot-backend/messaging.py#L101) | อ่านชื่อผู้ส่งจาก LINE; คืน None เมื่อ LINE ไม่อนุญาตหรืออ่านไม่สำเร็จ. |
| [`reply_to_line`](../scam-bot-backend/messaging.py#L129) | ส่งการ์ดหรือข้อความด้วย reply token; การ์ดถูกปฏิเสธ 400 จึงลองข้อความแทน คืน bool ว่า LINE ยอมรับหรือไม่ |

### scam-bot-backend/mini_api.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`get_mini_case_url`](../scam-bot-backend/mini_api.py#L17) | ตรวจ LIFF ID, channel ID และรหัสเคสก่อนคืนลิงก์รายละเอียดที่ไม่มีข้อมูลผู้ใช้; ค่าผิดคืน None |
| [`mini_web_origins`](../scam-bot-backend/mini_api.py#L29) | อ่าน origin ที่อนุญาตให้เรียก Mini API; คืนรายการว่างเมื่อไม่ตั้งค่า และยก ValueError เมื่อรูปแบบผิด |
| [`mini_error`](../scam-bot-backend/mini_api.py#L42) | สร้าง HTTPException พร้อม header ห้าม cache และห้ามส่ง referrer สำหรับข้อมูลส่วนตัว |
| [`verify_line_owner`](../scam-bot-backend/mini_api.py#L47) | ส่ง ID token ให้ LINE ยืนยันและตรวจผู้ให้บริการ ช่องทาง กับอายุ; คืน owner หรือปฏิเสธด้วย 401/503 |
| [`create_mini_router`](../scam-bot-backend/mini_api.py#L83) | history: โมดูล mini_history หรือของจำลองที่มี list_cases/get_case/delete_all. |
| [`create_mini_router.ask_history`](../scam-bot-backend/mini_api.py#L88) | เรียกงานประวัติแล้วคืนผลเดิม; แปลง HistoryUnavailable เป็น 503 โดยซ่อน error ดิบ |
| [`create_mini_router.read_history`](../scam-bot-backend/mini_api.py#L97) | ยืนยันเจ้าของด้วย token แล้วคืนรายการประวัติของคนนั้นพร้อม header ห้าม cache |
| [`create_mini_router.delete_history`](../scam-bot-backend/mini_api.py#L104) | ยืนยันเจ้าของก่อนลบประวัติส่วนตัวของคนนั้น แล้วคืนจำนวนรายการที่ผู้ใช้มองเห็นและถูกลบ |
| [`create_mini_router.read_case`](../scam-bot-backend/mini_api.py#L111) | ยืนยันเจ้าของและรหัสเคสก่อนคืนรายละเอียด; เคสหายหรือผิดเจ้าของตอบ 404 แบบเดียวกัน |

### scam-bot-backend/mini_history.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`get_client`](../scam-bot-backend/mini_history.py#L20) | โหลด client ประวัติเมื่อจำเป็น เพื่อไม่ให้ import โมดูลนี้บังคับโหลด config ของบอตทั้งหมด |
| [`_run`](../scam-bot-backend/mini_history.py#L26) | รัน query แล้วคืน data; ทุก error กลายเป็น HistoryUnavailable. |
| [`_owner_rows`](../scam-bot-backend/mini_history.py#L34) | เงื่อนไขร่วม: แถวของเจ้าของ เฉพาะแชตส่วนตัว และ 3 สถานะที่แสดงได้. |
| [`_short_title`](../scam-bot-backend/mini_history.py#L42) | รวมช่องว่างของข้อความแล้วตัดไม่เกิน 60 ตัวอักษรสำหรับชื่อเคสในรายการประวัติ |
| [`list_cases`](../scam-bot-backend/mini_history.py#L47) | อ่านเคสส่วนตัวของ owner ล่าสุดตาม limit แล้วคืนรายการย่อ; ฐานข้อมูลล้มเหลวยก HistoryUnavailable |
| [`get_case`](../scam-bot-backend/mini_history.py#L60) | อ่านเคสส่วนตัวตามรหัสและ owner แล้วสร้างรายละเอียดจากผลเดิม; ไม่พบหรือรหัสผิดคืน None |
| [`delete_all`](../scam-bot-backend/mini_history.py#L75) | ลบประวัติส่วนตัวทุกสถานะของ owner; คืนจำนวนเฉพาะสถานะที่แสดงใน Mini App ไม่แตะประวัติกลุ่ม |

### scam-bot-backend/rich_menu_setup.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`build_rich_menu`](../scam-bot-backend/rich_menu_setup.py#L21) | ตรวจ LIFF ID แล้วคืนโครงสร้างเมนูสามปุ่มที่เปิดประวัติ บทเรียน และวิธีใช้ |
| [`validate_menu_image`](../scam-bot-backend/rich_menu_setup.py#L43) | อ่านและคืน bytes ของ PNG ที่ไม่เกิน 1 MB และขนาด 2500×843; รูปแบบผิดยก ValueError |
| [`line_call`](../scam-bot-backend/rich_menu_setup.py#L53) | เรียก LINE API ด้วย timeout โดยไม่ retry; คืน JSON/None ตามเงื่อนไข หรือ error ที่ไม่เผย token |
| [`get_default_menu`](../scam-bot-backend/rich_menu_setup.py#L75) | อ่านรหัส Rich Menu เริ่มต้นจาก LINE; ไม่ได้ตั้งคืน None และรหัสผิดรูปแบบยก error |
| [`valid_menu_id`](../scam-bot-backend/rich_menu_setup.py#L86) | คืน bool ว่ารหัสเมนูตรงรูปแบบ richmenu- ตามด้วยตัวอักษรหรือตัวเลขหรือไม่ |
| [`write_state`](../scam-bot-backend/rich_menu_setup.py#L91) | เขียนสถานะการติดตั้งผ่านไฟล์ชั่วคราวแล้วแทนที่ไฟล์เดิม เพื่อเก็บข้อมูลสำหรับย้อนกลับ |
| [`publish_menu`](../scam-bot-backend/rich_menu_setup.py#L98) | ตรวจและสร้างเมนู เก็บรหัสเดิม อัปโหลดภาพ แล้วตั้งเมนูใหม่พร้อมยืนยัน; มีบันทึกค้างจะหยุดให้ตรวจ |
| [`restore_menu`](../scam-bot-backend/rich_menu_setup.py#L127) | คืนเมนูตามบันทึกการติดตั้งและยืนยันผล; หยุดถ้าพบคนอื่นเปลี่ยนเมนูไปแล้ว |
| [`main`](../scam-bot-backend/rich_menu_setup.py#L149) | อ่านคำสั่งจัดการเมนูและคืน exit code; publish/restore ต้องระบุ --apply ก่อนเปลี่ยน LINE |

### scam-bot-backend/safe_browsing_proto.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`decode_safe_browsing_response`](../scam-bot-backend/safe_browsing_proto.py#L63) | รับ bytes จาก Google; คืน dict หรือยก ValueError เมื่ออ่านผลไม่ได้. |

### scam-bot-backend/scripts/compare_detection_inputs.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`compare_inputs`](../scam-bot-backend/scripts/compare_detection_inputs.py#L26) | เทียบส่ง/ไม่ส่งตัวอย่าง โดยคงคะแนนและ label เดียวกันภายในคู่ของแต่ละชุดข้อความ. |
| [`summarize`](../scam-bot-backend/scripts/compare_detection_inputs.py#L87) | แยกผลไม่แน่ใจ/ตรวจไม่ได้ออกจากผลปลอดภัย เพื่อไม่ทำให้คะแนนดูดีเกินจริง. |
| [`main`](../scam-bot-backend/scripts/compare_detection_inputs.py#L120) | อ่านตัวเลือกและชุดประเมิน เรียกบริการจริงเพื่อเทียบผล แล้วเขียนรายงานใน temp; คืน exit code |

### scam-bot-backend/scripts/smoke_history.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`main`](../scam-bot-backend/scripts/smoke_history.py#L11) | เขียนประวัติสังเคราะห์ลง Supabase จริงสองครั้งแล้วอ่านยืนยันว่ามีแถวเดียว; ผิดเงื่อนไขหยุดด้วย SystemExit |

### scam-bot-backend/scripts/smoke_search.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`main`](../scam-bot-backend/scripts/smoke_search.py#L11) | สร้าง embedding และค้น Supabase จริงด้วยข้อความสังเคราะห์; แสดงคะแนนกับ label และคืน exit code |

### scam-bot-backend/url_checker.py

| ฟังก์ชัน | หน้าที่ / ผลลัพธ์ / ข้อจำกัด |
|---|---|
| [`extract_urls`](../scam-bot-backend/url_checker.py#L18) | ดึงลิงก์ HTTP/HTTPS ที่ไม่ซ้ำ โดยรักษาลำดับเดิม. |
| [`validate_url`](../scam-bot-backend/url_checker.py#L35) | ตรวจ URL แบบ HTTP/HTTPS ที่ไม่มี credentials หรืออักขระผิดกฎ แล้วคืน URL ที่ตัด fragment; ผิดยก ValueError |
| [`parse_safe_browsing_response`](../scam-bot-backend/url_checker.py#L80) | แปลงผลจาก Google เป็นผลตรวจและอายุ cache หน่วยวินาที. |
| [`_request_safe_browsing`](../scam-bot-backend/url_checker.py#L129) | เรียก Google แล้วคืนผลตรวจพร้อมอายุ cache. |
| [`check_url`](../scam-bot-backend/url_checker.py#L154) | ตรวจหนึ่ง URL; คืน matched, not_found หรือ error. |

## ชุดทดสอบและวิธีตรวจ

ทุก `test_*` และ helper มีคำอธิบายหน้าที่อยู่เหนือฟังก์ชันในไฟล์นั้น; เปิดตามส่วนที่แก้ได้โดยไม่ต้องอ่านทั้งชุด

| ส่วนที่ต้องการตรวจ | ไฟล์ทดสอบ |
|---|---|
| รับ webhook, งาน background และ event ซ้ำ | [test_webhook_threadpool.py](../scam-bot-backend/tests/test_webhook_threadpool.py), [test_webhook_guards.py](../scam-bot-backend/tests/test_webhook_guards.py) |
| การจัดเส้นทางและ validation ของ AI | [test_trigger_routing.py](../scam-bot-backend/tests/test_trigger_routing.py), [test_llm_validation.py](../scam-bot-backend/tests/test_llm_validation.py), [test_match_labels.py](../scam-bot-backend/tests/test_match_labels.py), [test_detection_errors.py](../scam-bot-backend/tests/test_detection_errors.py) |
| ผลต่างเมื่อส่งตัวอย่างให้ LLM | [test_compare_detection_inputs.py](../scam-bot-backend/tests/test_compare_detection_inputs.py) |
| Safe Browsing และการตรวจ URL | [test_url_checker.py](../scam-bot-backend/tests/test_url_checker.py), [test_url_routing.py](../scam-bot-backend/tests/test_url_routing.py) |
| ดาวน์โหลดรูปและ OCR | [test_image_content.py](../scam-bot-backend/tests/test_image_content.py), [test_image_ocr.py](../scam-bot-backend/tests/test_image_ocr.py) |
| แชตส่วนตัว การ์ด บทเรียน และเมนู | [test_private_chat.py](../scam-bot-backend/tests/test_private_chat.py), [test_flex_cards.py](../scam-bot-backend/tests/test_flex_cards.py), [test_learning.py](../scam-bot-backend/tests/test_learning.py), [test_rich_menu.py](../scam-bot-backend/tests/test_rich_menu.py) |
| ประวัติและสิทธิ์ Mini App | [test_detection_history.py](../scam-bot-backend/tests/test_detection_history.py), [test_mini_history.py](../scam-bot-backend/tests/test_mini_history.py), [test_mini_api.py](../scam-bot-backend/tests/test_mini_api.py) |
| เข้ากลุ่ม ออกจากกลุ่ม และจำนวนสมาชิก | [test_group_join.py](../scam-bot-backend/tests/test_group_join.py), [test_group_leave.py](../scam-bot-backend/tests/test_group_leave.py), [test_group_members.py](../scam-bot-backend/tests/test_group_members.py) |
| จับเวลาและซ่อนรายละเอียดลับใน log | [test_observability.py](../scam-bot-backend/tests/test_observability.py), [test_observability_errors.py](../scam-bot-backend/tests/test_observability_errors.py) |
| เตรียมและอัปโหลด Dataset | [test_script_safety.py](../scam-ai-engine/tests/test_script_safety.py), [test_upload_selection.py](../scam-ai-engine/tests/test_upload_selection.py) |

รันจากโฟลเดอร์ `linebot` ใน PowerShell โดยใช้ environment ที่ติดตั้งไว้แล้ว:

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s scam-bot-backend/tests -p "test_*.py" -q
.\scam-ai-engine\venv\Scripts\python.exe -X utf8 -B -m unittest discover -s scam-ai-engine/tests -p "test_*.py" -q
```

Tests ใช้บริการจำลองและบางกรณีเขียนไฟล์ชั่วคราว ไม่ใช่การเขียนฐานข้อมูลจริงหรือการยืนยันความแม่นยำ AI
อย่ารัน `smoke_history.py` หรือ uploader รวมกับชุดทดสอบจำลอง เพราะมีผลต่อบริการจริง

## การดูแลไฟล์

- ลบได้เมื่อเลิกใช้งานชั่วคราว: `__pycache__` และ `.pyc` ของโค้ดเรา Python สร้างใหม่ได้
- เก็บ SQL, ชุดข้อมูล, tests และภาพ Rich Menu ที่ยังมีการอ้างอิงไว้
- [archive](archive/README.md) เก็บเอกสารเดิมที่อาจมีชื่อไฟล์หรือขั้นตอนล้าสมัย ใช้ดูที่มา ไม่ใช่สั่งรันซ้ำ
- ไม่ย้าย `.env`, environment หรือ dependency โดยไม่ตรวจคำสั่งรันและโปรแกรมที่กำลังใช้งาน
