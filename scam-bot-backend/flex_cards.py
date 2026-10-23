"""สร้างการ์ดผลตรวจ (LINE Flex Message) จากผลเดิม ไม่เรียก AI และไม่ส่ง LINE เอง."""
from mini_api import get_mini_case_url, mini_web_origins


# สีชุดเดียวกับหน้า Mini App: พื้นหัวการ์ด / ตัวหนังสือหัว / สีรอง และปุ่ม
STATUS_STYLES = {
    "risk_found": {"title": "พบสัญญาณเสี่ยง", "pose": "alert", "background": "#FBEAF0",
                   "strong": "#72243E", "soft": "#993556",
                   "advice": "อย่าเพิ่งกดลิงก์ โอนเงิน หรือให้ OTP"},
    "uncertain": {"title": "ควรตรวจเพิ่ม", "pose": "inspect", "background": "#FAEEDA",
                  "strong": "#633806", "soft": "#854F0B",
                  "advice": "ตรวจผ่านช่องทางทางการก่อนทำตาม"},
    "no_risk_found": {"title": "ยังไม่พบสัญญาณเสี่ยง", "pose": "calm", "background": "#E1F5EE",
                      "strong": "#085041", "soft": "#0F6E56",
                      "advice": "ผลนี้ไม่รับรองว่าปลอดภัย 100%"},
}
QUOTE_LIMIT = 60
REASON_LIMIT = 120


def shorten(text: str, limit: int) -> str:
    """รวมช่องว่างให้เป็นบรรทัดเดียว แล้วตัดให้ไม่เกิน limit ตัวอักษร."""
    single_line = " ".join(str(text).split())
    if len(single_line) <= limit:
        return single_line
    return single_line[:limit] + "…"


def mascot_url(pose: str) -> str | None:
    """รูปมาสคอตอยู่ใน public/mascot ของเว็บ LINE ดึงรูปได้เฉพาะ HTTPS."""
    try:
        origins = mini_web_origins()
    except ValueError:
        return None
    if not origins or not origins[0].startswith("https://"):
        return None
    return f"{origins[0]}/mascot/{pose}.png"


def detail_action(case_id: str | None, allow_postback: bool) -> dict | None:
    """ปุ่มเปิด Mini App ถ้าตั้งค่าครบ; ไม่ครบใช้ postback บทเรียนในแชตแทน (ถ้าอนุญาต)."""
    if not case_id:
        return None
    url = get_mini_case_url(case_id)
    if url:
        return {"type": "uri", "label": "ดูรายละเอียด", "uri": url}
    if allow_postback:
        return {"type": "postback", "label": "ดูรายละเอียด",
                "data": f"learn:{case_id}", "displayText": "เรียนรู้จากข้อความนี้"}
    return None


def build_result_card(result: dict, *, source: str, quote: str, case_id: str | None,
                      allow_postback: bool = False) -> dict | None:
    """รับผลตรวจ คืน Flex Message หนึ่งข้อความ หรือ None ถ้าสถานะนี้ไม่ใช้การ์ด.

    source: "text" หรือ "image" ใช้บอกที่มา; quote: ข้อความที่ตรวจ (จากรูปคือข้อความ OCR)
    """
    style = STATUS_STYLES.get(result.get("status"))
    if style is None:
        return None

    reason = result.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        reason = "ไม่มีเหตุผลเพิ่มเติมจากผลตรวจ"
    reason = shorten(reason, REASON_LIMIT)
    quoted = f"“{shorten(quote, QUOTE_LIMIT)}”"
    if source == "image":
        quoted = f"ข้อความในรูป: {quoted}"
    source_label = "ตรวจจากรูปภาพ" if source == "image" else "ตรวจจากข้อความ"

    header_contents = [{
        "type": "box", "layout": "vertical", "flex": 1, "justifyContent": "center",
        "contents": [
            {"type": "text", "text": style["title"], "weight": "bold", "size": "lg",
             "color": style["strong"], "wrap": True},
            {"type": "text", "text": source_label, "size": "xs", "color": style["soft"]},
        ],
    }]
    image = mascot_url(style["pose"])
    if image:
        header_contents.append({"type": "image", "url": image, "size": "72px",
                                "aspectRatio": "1:1", "aspectMode": "fit", "flex": 0})

    bubble = {
        "type": "bubble",
        "header": {"type": "box", "layout": "horizontal", "alignItems": "center", "spacing": "md",
                   "backgroundColor": style["background"], "paddingAll": "14px",
                   "contents": header_contents},
        "body": {"type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "14px", "contents": [
            {"type": "box", "layout": "vertical", "backgroundColor": "#F5F2F4", "cornerRadius": "8px",
             "paddingAll": "8px", "contents": [
                 {"type": "text", "text": quoted, "size": "xs", "color": "#6B5B6B", "wrap": True}]},
            {"type": "text", "text": reason, "size": "sm", "color": "#392039", "wrap": True, "maxLines": 4},
            {"type": "text", "text": style["advice"], "size": "sm", "weight": "bold",
             "color": style["strong"], "wrap": True},
            {"type": "text", "text": "ผลประเมินจากข้อความ ไม่ยืนยันตัวตนผู้ส่ง",
             "size": "xxs", "color": "#9B919F", "wrap": True},
        ]},
    }
    action = detail_action(case_id, allow_postback)
    if action:
        bubble["footer"] = {"type": "box", "layout": "vertical", "paddingAll": "12px", "contents": [
            {"type": "button", "style": "primary", "height": "sm", "color": style["soft"], "action": action}]}

    # altText แสดงในรายการแชต/แจ้งเตือน LINE จำกัด 400 ตัวอักษร
    alt_text = shorten(f"{style['title']}: {reason}", 390)
    return {"type": "flex", "altText": alt_text, "contents": bubble}
