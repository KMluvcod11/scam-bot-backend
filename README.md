# Scam Detector LINE Bot

LINE Bot สำหรับตรวจจับข้อความหลอกลวงภาษาไทย โดยใช้ Gemini embeddings, Supabase pgvector และ Gemini LLM

## สถาปัตยกรรมที่ใช้งานจริง

```text
LINE webhook -> FastAPI -> Gemini embedding -> Supabase match_scam
                                              -> Gemini LLM (กรณีที่กำกวม)
                                              -> LINE warning reply
```

ระบบหลักคือ `scam-bot-backend/main.py` เท่านั้น

## โครงสร้าง

- `scam-bot-backend/main.py` - จุดเริ่มต้น FastAPI และรับ LINE webhook
- `scam-bot-backend/config.py` - โหลด .env และรวมค่าตั้งต้น/กฎกรองข้อความ
- `scam-bot-backend/detector.py` - กรองข้อความ ค้นหาเวกเตอร์ และเรียก LLM
- `scam-bot-backend/messaging.py` - ส่งคำเตือนกลับ LINE และรายงานผลการส่ง
- `scam-bot-backend/requirements.txt` - Python dependencies สำหรับระบบหลัก
- `scam-bot-backend/.env.example` - ตัวอย่าง environment variables ที่จำเป็น
- `scam-ai-engine/upload_to_supabase.py` - สร้าง embeddings และอัปโหลดชุดข้อมูลไป Supabase
- `scam-ai-engine/master_thai_dataset.csv` - ชุดข้อมูลสำหรับ vector database

## การติดตั้งและรันบน Windows PowerShell

จากโฟลเดอร์รากของโปรเจกต์:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\scam-bot-backend\requirements.txt
Set-Location .\scam-bot-backend
$env:PYTHONUTF8 = "1"
..\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
```

คัดลอก `.env.example` เป็น `.env` ในโฟลเดอร์ `scam-bot-backend` แล้วใส่ค่าจริงก่อนรัน ห้าม commit ไฟล์ `.env`

## LINE Webhook

เปิด public tunnel ให้ port 8000 แล้วตั้ง URL ใน LINE Developers Console เป็น:

```text
https://your-public-domain/webhook
```

หากใช้ไฟล์ `cloudflared.exe` ที่อยู่ในโฟลเดอร์ราก ให้รันจากอีกหน้าต่าง terminal:

```powershell
.\cloudflared.exe tunnel --url http://localhost:8000
```

## กฎการวิเคราะห์

- ข้อความสั้นมากหรืออยู่ใน safe words จะไม่วิเคราะห์
- Similarity ตั้งแต่ 92% จะเตือนทันที
- ข้อความที่มี scam trigger และ similarity ตั้งแต่ 65% จะส่ง Gemini LLM วิเคราะห์
- ข้อความที่ไม่มี trigger แต่ similarity ตั้งแต่ 85% จะส่ง Gemini LLM วิเคราะห์ เพื่อลดโอกาสพลาด scam รูปแบบใหม่

## การทดสอบที่ยืนยันแล้ว

ทดสอบสำเร็จ: LINE -> FastAPI -> Gemini embedding -> Supabase `match_scam` -> LINE reply
