"""แปลชุดข้อมูลเมื่อสั่งรันเท่านั้น; import ไม่เรียก API หรือเขียน CSV."""
import os
import time
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv


def translate_to_line(row, model):
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

    for attempt in range(3):
        try:
            response = model.generate_content(prompt, safety_settings=safety_settings)
            text = response.text.strip()
            if not text or text == "แปลไม่สำเร็จ":
                raise ValueError("Empty translation")
            time.sleep(5)
            return text
        except Exception as error:
            if attempt == 2:
                raise
            print(f"ลองใหม่: {type(error).__name__}")
            time.sleep(30 if "429" in str(error) else 5)


def translate_rows(df, model, output_file, failed_file):
    successful, failed = [], []
    interrupted = False

    def save_progress():
        pd.DataFrame(successful, columns=['label', 'thai_text']).to_csv(output_file, index=False, encoding='utf-8-sig')
        pd.DataFrame(failed, columns=['source_row', 'error_type']).to_csv(failed_file, index=False, encoding='utf-8-sig')

    try:
        for number, (_, row) in enumerate(df.iterrows(), 1):
            try:
                text = translate_to_line(row, model)
                successful.append({'label': row['label'], 'thai_text': text})
            except Exception as error:
                failed.append({'source_row': number, 'error_type': type(error).__name__})
            print(f"[{number}/{len(df)}] สำเร็จ {len(successful)} / ไม่สำเร็จ {len(failed)}")
            if number % 50 == 0:
                save_progress()
    except KeyboardInterrupt:
        interrupted = True
    save_progress()
    return 130 if interrupted else (1 if failed else 0)


def main():
    folder = Path(__file__).resolve().parent
    output_file = folder / 'translated_phishing_line_1500.csv'
    failed_file = folder / 'translated_phishing_line_1500_failed.csv'
    if output_file.exists() or failed_file.exists():
        print('มีไฟล์ผลลัพธ์แล้ว กรุณาเก็บสำรองก่อนรันใหม่')
        return 1
    try:
        df = pd.read_csv(folder / 'phishing_sampled_1500.csv', encoding='utf-8-sig')
        if not {'label', 'text'}.issubset(df.columns) or df[['label', 'text']].isna().any().any():
            raise ValueError('Invalid CSV')
        if not df['label'].isin(['Phishing Email', 'Safe Email']).all():
            raise ValueError('Invalid label')
        import google.generativeai as genai
        load_dotenv(folder / '.env')
        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
        model = genai.GenerativeModel('gemini-flash-lite-latest')
        return translate_rows(df, model, output_file, failed_file)
    except Exception as error:
        print(f'หยุด: {type(error).__name__}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
