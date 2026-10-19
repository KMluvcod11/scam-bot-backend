"""รันด้วยตนเอง: เรียก Gemini จริง 6 รอบ (อาจมี failover) ไม่เรียกค้นหา DB หรือส่ง LINE."""
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile


INPUTS = {
    "text": (
        "ตอนแรกนึกว่าปลอม 😂 แต่ได้ ฿3,000 จริง ๆ นะ ลองดู!  "
        "https://xahjv.buzz/qHxfHNqx/th-th?1018824739549816126&s=ln&"
    ),
    "ocr": (
        "ตอนแรกนึกว่าปลอม 😅 แต่ได้\n"
        "฿3,000 จริง ๆ นะ ลองดู!\n"
        "https://xahjv.buzz/qHxfHNqx/th-\nth?\n"
        "1018824739549816126&s=ln&\n"
        "🎉 โลตัส - ของขวัญวันออก...\n"
        "🎉 เพื่อร่วมฉลองวันออกพรรษา\n"
        "กับทุกคน เราได้เตรียมของขวัญ..."
    ),
}


def compare_inputs(analyze):
    """ใช้ตัววิเคราะห์เดิมกับข้อมูลสองชุด โดยตรึงข้อมูลประกอบให้เท่ากัน."""
    report = {
        "similarity_percent": 80.85,
        "matched_label": "spam",
        "private": True,
        "text_source": "Reconstructed from user message; raw LINE payload unavailable",
        "ocr_source": "OCR DEBUG trace=f51c065d",
        "inputs": INPUTS,
        "runs": [],
    }
    for repeat in range(1, 4):
        for name, text in INPUTS.items():
            print(f"[COMPARE] input={name} chars={len(text)} repeat={repeat}", flush=True)
            result = analyze(text, 80.85, "spam", private=True)
            report["runs"].append({"input": name, "repeat": repeat, "result": result})
            print(json.dumps(result, ensure_ascii=False), flush=True)
    return report


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        from detector import analyze_with_llm

        report = compare_inputs(analyze_with_llm)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        output = Path(tempfile.gettempdir()) / f"linebot-input-comparison-{timestamp}.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report: {output}")
        return int(any(run["result"].get("status") == "error" for run in report["runs"]))
    except Exception as error:
        print(f"Comparison failed: {type(error).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
