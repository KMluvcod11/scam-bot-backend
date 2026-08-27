import pandas as pd
import google.generativeai as genai
import time
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

model = genai.GenerativeModel('gemini-flash-lite-latest')

print("1. กำลังประกอบร่างข้อความอังกฤษต้นฉบับ กับ คำแปลที่ทำสำเร็จแล้ว...")
# ดึงข้อความต้นฉบับจาก spam.csv
df_orig = pd.read_csv('spam.csv', encoding='latin-1')
df_orig = df_orig[['v1', 'v2']].rename(columns={'v1': 'label', 'v2': 'text'})
df_spam = df_orig[df_orig['label'] == 'spam'].copy()
df_ham = df_orig[df_orig['label'] == 'ham'].head(len(df_spam)).copy()
df_combined = pd.concat([df_spam, df_ham], ignore_index=True)

# ดึงผลลัพธ์จากไฟล์ที่แปลค้างไว้
df_translated = pd.read_csv('translated_spam_fixed.csv', encoding='utf-8-sig')

# นำมาประกบกัน (ตอนนี้เราจะมีทั้ง text อังกฤษ และ thai_text ที่แปลค้างไว้)
df_combined['thai_text'] = df_translated['thai_text']

# หาว่ามีแถวไหนบ้างที่ 'แปลไม่สำเร็จ'
failed_indices = df_combined[df_combined['thai_text'] == 'แปลไม่สำเร็จ'].index
total_failed = len(failed_indices)

print(f" ประกอบร่างสำเร็จ! เจอข้อความที่ต้องแปลซ่อมทั้งหมด {total_failed} แถว")

if total_failed == 0:
    print("ไม่มีอะไรต้องซ่อมแล้วครับ ข้อมูลสมบูรณ์ 100%")
    exit()

# ปิดระบบเซ็นเซอร์ เผื่อมีคำหยาบ/สแลง จะได้แปลผ่าน
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
]

def re_translate(label, text):
    if label == 'spam':
        prompt = f"""
        จงแปลและดัดแปลงข้อความสแปมภาษาอังกฤษนี้ ให้กลายเป็นข้อความหลอกลวงภาษาไทยที่ 'สแกมเมอร์ชอบส่งเข้าในกลุ่ม LINE'
        เช่น การเป็นหน้าม้าชวนลงทุน, ชวนทำงานออนไลน์/กดรับออเดอร์, แจกเงินฟรีแล้วให้แอดไลน์ส่วนตัว, หรืออ้างเป็นแอดมินกลุ่ม
        ข้อความต้นฉบับ: "{text}"
        ตอบกลับมาเฉพาะข้อความภาษาไทยที่แต่งใหม่แล้วเท่านั้น ห้ามมีคำอธิบายเพิ่ม:
        """
    else:
        prompt = f"""
        จงแปลข้อความภาษาอังกฤษนี้ เป็นข้อความแชทภาษาไทยที่เป็นธรรมชาติ คุยกันในชีวิตประจำวันทั่วไป (ไม่หลอกลวง)
        ข้อความต้นฉบับ: "{text}"
        ตอบกลับมาเฉพาะข้อความภาษาไทยที่เป็นธรรมชาติเท่านั้น:
        """
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt, safety_settings=safety_settings)
            time.sleep(5) 
            return response.text.strip()
        except Exception as e:
            if "429" in str(e):
                print(f" โควตาอาจจะเต็ม (รอ 30 วิ): {e}")
                time.sleep(30)
            else:
                time.sleep(5)
            if attempt == max_retries - 1:
                return "แปลไม่สำเร็จ"

print("2. เริ่มกระบวนการแปลซ่อมแซม...")
count = 1
for idx in failed_indices:
    label = df_combined.loc[idx, 'label']
    text = df_combined.loc[idx, 'text']
    
    result = re_translate(label, text)
    df_combined.loc[idx, 'thai_text'] = result
    
    status = " สำเร็จ" if result != "แปลไม่สำเร็จ" else " ล้มเหลว"
    print(f"[{count}/{total_failed}] ซ่อมแซม {label.upper()} -> {status}")
    count += 1
    
    # เซฟทับทุกๆ 50 แถว เผื่อไฟดับจะได้ไม่หาย
    if count % 50 == 0:
        df_combined[['label', 'text', 'thai_text']].to_csv('translated_spam_fixed.csv', index=False, encoding='utf-8-sig')

# เซฟไฟล์ขั้นสุดท้าย (คราวนี้เก็บข้อความอังกฤษ 'text' ไว้ด้วยเลย ดีต่อระบบ Database ครับ)
df_combined[['label', 'text', 'thai_text']].to_csv('translated_spam_fixed.csv', index=False, encoding='utf-8-sig')

print(" ซ่อมแซมเสร็จสิ้น! บันทึกไฟล์ที่สมบูรณ์ไว้ที่ 'translated_spam_fixed.csv'")