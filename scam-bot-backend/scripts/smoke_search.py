"""รันด้วยตนเองเท่านั้น: ใช้ Gemini/Supabase จริงและอาจใช้โควตา."""
import os
from pathlib import Path
from google import genai
from google.genai import types
from supabase import create_client
from dotenv import load_dotenv


def main():
    try:
        load_dotenv(Path(__file__).resolve().parents[1] / '.env')
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        db = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
        text = "ยินดีด้วยครับ คุณได้รับสิทธิ์กู้เงินฉุกเฉิน 50,000 บาท คลิกลิงก์เพื่อรับสิทธิ์ด่วน"
        response = client.models.embed_content(
            model="gemini-embedding-001",
            contents=text,
            config=types.EmbedContentConfig(task_type="retrieval_document", output_dimensionality=768),
        )
        matches = db.rpc('match_scam', {
            'query_embedding': response.embeddings[0].values,
            'match_threshold': 0.7,
            'match_count': 3,
        }).execute()
        if not matches.data:
            print("ไม่พบข้อความผ่านเกณฑ์ความคล้าย; ไม่ใช่การยืนยันความปลอดภัย")
        for item in matches.data:
            print(f"ความคล้าย: {item['similarity'] * 100:.2f}% | label={item['label']}")
        return 0
    except Exception as error:
        print(f"ค้นหาไม่สำเร็จ: {type(error).__name__}")
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
