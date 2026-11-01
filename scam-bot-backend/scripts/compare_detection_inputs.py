"""เคสเดิม: ค้น 2 / วิเคราะห์ 12 ครั้ง; --evaluation: ค้น 12 / วิเคราะห์ 24 ครั้ง (อาจมี failover). ไม่ส่ง LINE."""
from datetime import datetime
import argparse
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


def compare_inputs(analyze, find_match, *, cases=None, repeats=3):
    """เทียบส่ง/ไม่ส่งตัวอย่าง โดยคงคะแนนและ label เดียวกันภายในคู่ของแต่ละชุดข้อความ."""
    inputs = INPUTS if cases is None else {name: case["text"] for name, case in cases.items()}
    report = {
        "matches":{},
        "private": True,
        "text_source": "Reconstructed from user message; raw LINE payload unavailable",
        "ocr_source": "OCR DEBUG trace=f51c065d",
        "inputs": inputs,
        "runs": [],
    }

    if cases is not None:
        report.pop("text_source")
        report.pop("ocr_source")
        report["cases"] = cases
        report["scope"] = "Effect of example text only; both modes retain similarity and label. Synthetic pilot, not overall bot accuracy."

    for name, text in inputs.items():
        try:
            similarity_percent, matched_label, matched_text = find_match(text)
        except Exception as error:
            report["matches"][name] = {"error_type": type(error).__name__}
            continue
        report["matches"][name] = {
            "similarity_percent": similarity_percent,
            "matched_label": matched_label,
            "matched_text": matched_text
        }

    for repeat in range(1, repeats + 1):
        for name, text in inputs.items():
            print(f"[COMPARE] input={name} chars={len(text)} repeat={repeat}", flush=True)
            match = report["matches"][name]
            for mode in ("without_example", "with_example"):
                if "error_type" in match:
                    result = {"status": "error", "is_scam": None, "error_stage": "retrieval",
                              "error_type": match["error_type"]}
                    report["runs"].append({"input": name, "repeat": repeat, "result": result, "mode": mode})
                    continue
                example_text = ""
                if mode == "with_example":
                    example_text = match["matched_text"]
                try:
                    result = analyze(
                        text,
                        match["similarity_percent"],
                        match["matched_label"],
                        matched_text=example_text,
                        private=True,
                    )
                except Exception as error:
                    result = {"status": "error", "is_scam": None, "error_stage": "analysis",
                              "error_type": type(error).__name__}
                report["runs"].append({"input": name, "repeat": repeat, "result": result, "mode": mode})
                print(json.dumps(result, ensure_ascii=False), flush=True)
    if cases is not None:
        report["summary"] = summarize(report)
    return report


def summarize(report):
    """แยกผลไม่แน่ใจ/ตรวจไม่ได้ออกจากผลปลอดภัย เพื่อไม่ทำให้คะแนนดูดีเกินจริง."""
    summary = {}
    for mode in ("without_example", "with_example"):
        counts = {"total": 0, "false_alarms": 0, "missed_risks": 0,
                  "uncertain": 0, "error": 0, "fallback": 0, "invalid": 0,
                  "no_example": 0, "matrix": {}}
        for run in report["runs"]:
            if run["mode"] != mode:
                continue
            expected = report["cases"][run["input"]]["expected"]
            result = run["result"]
            status = result.get("status")
            if status == "conversation":
                status = "no_risk_found"
            if status not in {"risk_found", "no_risk_found", "uncertain", "error", "fallback"}:
                status = "invalid"
            if status in {"risk_found", "no_risk_found", "uncertain"}:
                if result.get("is_scam") is not (status == "risk_found"):
                    status = "invalid"
            counts["total"] += 1
            if status in {"uncertain", "error", "fallback", "invalid"}:
                counts[status] += 1
            counts["false_alarms"] += int(expected == "no_risk_found" and status == "risk_found")
            counts["missed_risks"] += int(expected == "risk_found" and status == "no_risk_found")
            counts["no_example"] += int(not report["matches"][run["input"]].get("matched_text"))
            matrix_row = counts["matrix"].setdefault(expected, {})
            matrix_row[status] = matrix_row.get(status, 0) + 1
        summary[mode] = counts
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", action="store_true",
                        help="Synthetic 12-case pilot: 12 retrievals, 24 analyses plus possible failover")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        cases = None
        if args.evaluation:
            cases = json.loads(Path(__file__).with_name("rag_evaluation_cases.json").read_text(encoding="utf-8"))
            if not isinstance(cases, dict) or len(cases) != 12:
                raise ValueError("Expected 12 cases")
            for case in cases.values():
                if (not isinstance(case, dict) or not isinstance(case.get("text"), str)
                        or not case["text"].strip()
                        or case.get("expected") not in {"risk_found", "no_risk_found", "uncertain"}):
                    raise ValueError("Invalid evaluation case")
        from detector import analyze_with_llm, find_similarity

        report = compare_inputs(analyze_with_llm, find_similarity, cases=cases,
                                repeats=1 if args.evaluation else 3)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        output = Path(tempfile.gettempdir()) / f"linebot-input-comparison-{timestamp}.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report: {output}")
        if "summary" in report:
            print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        return int(any(run["result"].get("status") == "error" for run in report["runs"]))
    except Exception as error:
        print(f"Comparison failed: {type(error).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
