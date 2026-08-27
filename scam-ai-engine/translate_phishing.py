import pandas as pd
import google.generativeai as genai
import time
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

model = genai.GenerativeModel('gemini-flash-lite-latest')

input_file = 'phishing_sampled_1500.csv'
output_file = 'translated_phishing_line_1500.csv'

print(f"1. กำลังอ่านไฟล์ {input_file}...")

try:
    df = pd.read_csv(input_file, encoding='utf-8-sig')
    total_rows = len(df)
    print(f"เจอข้อมูลทั้งหมด {total_rows} แถว พร้อมลุย!")
except Exception as e:
    print(f"อ่านไฟล์ไม่สำเร็จ: {e}")
    exit()

def translate_to_line(row, index):
    label = str(row['label']) 
    text = str(row['text'])
    
    # Prompt: แปลง Email ให้เป็นแชท LINE
    if label == 'Phishing Email': 
        prompt = f"""
        จงแปลและดัดแปลงเนื้อหาจากอีเมล Phishing ภาษาอังกฤษนี้ ให้กลายเป็น 'ข้อความหลอกลวงภาษาไทยที่มิจฉาชีพส่งทาง LINE'
        (ปรับภาษาจากการส่งอีเมล ให้กลายเป็นการส่งแชท LINE หรือประกาศในกลุ่ม LINE)
        เช่น อ้างเป็นธนาคารแจ้งบัญชีมีปัญหา, อ้างเป็นตำรวจ/หน่วยงานรัฐ, บริษัทขนส่ง, หรือส่งลิงก์อันตรายให้กด
        ข้อความต้นฉบับ: "{text}"
        ตอบกลับมาเฉพาะข้อความแชทภาษาไทยที่แต่งใหม่แล้วเท่านั้น ห้ามมีคำอธิบายเพิ่ม:
        """
    else:
        prompt = f"""
        จงแปลเนื้อหาจากอีเมลภาษาอังกฤษนี้ ให้กลายเป็น 'ข้อความแชทภาษาไทยที่เป็นธรรมชาติ คุยกันเรื่องงานหรือเรื่องทั่วไปผ่าน LINE'
        (ปลอดภัย ไม่หลอกลวง ปรับภาษาให้เข้ากับการแชท)
        ข้อความต้นฉบับ: "{text}"
        ตอบกลับมาเฉพาะข้อความแชทภาษาไทยเท่านั้น:
        """
        
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
    ]

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt, safety_settings=safety_settings)
            time.sleep(5) 
            print(f"[{index+1}/{total_rows}] {label.upper()} -> LINE -  สำเร็จ")
            return response.text.strip()
        except Exception as e:
            if "429" in str(e):
                print(f"[{index+1}/{total_rows}]  โควตาเต็ม (รอ 30 วิ)...")
                time.sleep(30)
            else:
                print(f"[{index+1}/{total_rows}]  Error: {e} (ลองใหม่...)")
                time.sleep(5)
            if attempt == max_retries - 1:
                return "แปลไม่สำเร็จ"

print(f"\n2. เริ่มกระบวนการแปลงร่างข้อมูลเป็นแชท LINE ทั้งหมด {total_rows} ข้อความ...")

translated_texts = []
try:
    for index, row in df.iterrows():
        result = translate_to_line(row, index)
        translated_texts.append(result)
        
        # เซฟไฟล์สำรองทุก 50 แถว
        if (index + 1) % 50 == 0:
            temp_df = df.iloc[:index+1].copy()
            temp_df['thai_text'] = translated_texts
            temp_df[['label', 'thai_text']].to_csv('temp_phishing_line_backup.csv', index=False, encoding='utf-8-sig')

except KeyboardInterrupt:
    print("\n หยุดการทำงานชั่วคราว! กำลังบันทึกข้อมูลที่ทำเสร็จแล้ว...")

# บันทึกไฟล์ขั้นตอนสุดท้าย (เซฟเฉพาะ label กับ thai_text)
df_final = df.iloc[:len(translated_texts)].copy()
df_final['thai_text'] = translated_texts
df_final[['label', 'thai_text']].to_csv(output_file, index=False, encoding='utf-8-sig')

print(f"\n บันทึกไฟล์ {output_file} สำเร็จเรียบร้อยแล้ว!")