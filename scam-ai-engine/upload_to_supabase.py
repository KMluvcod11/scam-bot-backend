import pandas as pd
from google import genai
from google.genai import types
from supabase import create_client, Client
import time
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

df = pd.read_csv('master_thai_dataset.csv', encoding='utf-8-sig')
total_rows = len(df)
print(f"โหลดข้อมูลทั้งหมด {total_rows} แถว")

def get_embedding(text):
    response = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text,
        config=types.EmbedContentConfig(
            task_type="retrieval_document",
            output_dimensionality=768 
        )
    )
    return response.embeddings[0].values

batch_size = 50
records = []

for i, row in df.iterrows():
    text = str(row['thai_text'])
    label = str(row['label'])
    
    try:
        embedding = get_embedding(text)
        records.append({
            "label": label,
            "thai_text": text,
            "embedding": embedding
        })
        time.sleep(0.05)
    except Exception as e:
        print(f"Error แถวที่ {i+1}: {e}")
        time.sleep(2)
        continue

    if len(records) >= batch_size or (i + 1) == total_rows:
        try:
            supabase.table('scam_dataset').insert(records).execute()
            print(f"✅ อัปโหลดสำเร็จ [{i+1}/{total_rows}] แถว")
            records = []
        except Exception as e:
            print(f"Supabase Insert Error: {e}")

# อัปโหลดเศษที่เหลือ (ถ้ามี)
if records:
    try:
        supabase.table('scam_dataset').insert(records).execute()
        print(f"✅ อัปโหลดสำเร็จ [{total_rows}/{total_rows}] แถว")
    except Exception as e:
        print(f"Supabase Insert Error: {e}")

print("🎉 นำเข้าข้อมูลสู่ Supabase สำเร็จเรียบร้อย!")