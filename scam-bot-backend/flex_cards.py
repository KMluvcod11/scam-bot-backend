"""สร้างการ์ดผลตรวจ (LINE Flex Message) จากผลเดิม ไม่เรียก AI และไม่ส่ง LINE เอง.

การ์ดไม่แสดงระดับความเสี่ยง (risk_level) ค่านั้นยังอยู่ในผลตรวจและประวัติให้ Dashboard ใช้ตามเดิม
"""
import re
import unicodedata

from mini_api import get_mini_case_url, mini_web_origins


# สีหัวการ์ดตามสถานะ: แดงอ่อน = พบสัญญาณเสี่ยง, เหลืองอ่อน = ควรตรวจเพิ่ม, เขียวอ่อน = ยังไม่พบ
STATUS_STYLES = {
    "risk_found": {"title": "พบสัญญาณเสี่ยง", "pose": "alert", "header": "#FDE2E4",
                   "note_title": "คำเตือน", "note_icon": "icons/warning.png", "note_color": "#E5484D", "note_background": "#FDECEE",
                   "advice": "อย่าเพิ่งกดลิงก์ โอนเงิน หรือเปิดเผย OTP "
                             "ตรวจสอบผ่านช่องทางทางการก่อน"},
    "uncertain": {"title": "ควรตรวจเพิ่ม", "pose": "inspect", "header": "#FDF0D5",
                  "note_title": "คำแนะนำ", "note_color": "#9A5B00", "note_background": "#FDF3E1",
                  "advice": "ข้อมูลยังไม่พอที่จะสรุป ตรวจผ่านช่องทางทางการก่อนทำตาม"},
    "no_risk_found": {"title": "ยังไม่พบสัญญาณเสี่ยง", "pose": "calm", "header": "#E3F5EC",
                      "note_title": "คำแนะนำ", "note_color": "#0F6E56", "note_background": "#F1F3F5",
                      "advice": "ผลนี้ไม่รับรองว่าปลอดภัย และไม่ได้ตรวจเว็บไซต์ปลายทาง"},
}
TEXT_STRONG = "#16303A"
TEXT_BODY = "#2B3440"
TEXT_MUTED = "#7A8590"
QUOTE_BACKGROUND = "#F1F3F5"
BULLET_COLOR = "#2BB58A"
BUTTON_COLOR = "#1E5A5A"
DISCLAIMER = "เป็นผลประเมินจากข้อความ ไม่ยืนยันตัวตนหรือข้อเท็จจริงของผู้ส่ง"
QUOTE_LIMIT = 150
REASON_LIMIT = 400
REASON_ITEMS = 5
# สระหน้า: ถ้าตัดหลังตัวนี้ สระจะค้างโดยไม่มีพยัญชนะตาม
THAI_LEADING_VOWELS = set("เแโใไ")


def shorten(text: str, limit: int) -> str:
    """รวมช่องว่างให้เป็นบรรทัดเดียว แล้วตัดให้ไม่เกิน limit ตัวอักษร โดยไม่ตัดกลางพยางค์ไทย."""
    single_line = " ".join(str(text).split())
    if len(single_line) <= limit:
        return single_line
    cut = limit
    # ตัดตรงช่องว่างถ้าอยู่ใกล้ ๆ (ภาษาไทยเว้นวรรคระหว่างวลี)
    space = single_line.rfind(" ", 0, cut + 1)
    if space >= limit * 2 // 3:
        cut = space
    else:
        # ไม่ให้สระบน/ล่าง/วรรณยุกต์หลุดจากพยัญชนะ และไม่ให้สระหน้าค้างท้ายบรรทัด
        while cut > 0 and (unicodedata.category(single_line[cut]) == "Mn"
                           or single_line[cut - 1] in THAI_LEADING_VOWELS):
            cut -= 1
    return single_line[:cut].rstrip() + "…"


def reason_items(reason) -> list[str]:
    """แยกเหตุผลเป็นข้อ ๆ ตามขึ้นบรรทัดใหม่หรือ • ที่มากับผลตรวจ ไม่มีก็เป็นข้อเดียว."""
    if not isinstance(reason, str) or not reason.strip():
        return ["ไม่มีเหตุผลเพิ่มเติมจากผลตรวจ"]
    parts = [part.strip(" -–•\t") for part in re.split(r"[\r\n•]+", reason)]
    parts = [part for part in parts if part][:REASON_ITEMS] or [reason.strip()]
    items, used = [], 0
    for part in parts:
        room = REASON_LIMIT - used
        if room < 20:
            break
        item = shorten(part, room)
        items.append(item)
        used += len(item)
    return items


def asset_url(path: str) -> str | None:
    """รูปอยู่ใน public/ ของเว็บ Mini App; LINE ดึงรูปได้เฉพาะ HTTPS."""
    try:
        origins = mini_web_origins()
    except ValueError:
        return None
    if not origins or not origins[0].startswith("https://"):
        return None
    return f"{origins[0]}/{path}"


def mascot_url(pose: str) -> str | None:
    return asset_url(f"mascot/{pose}.png")


def note_heading(style: dict) -> dict:
    """หัวกรอบคำเตือน/คำแนะนำ; มีไอคอนเมื่อโหลดรูปได้ ไม่งั้นเป็นตัวหนังสืออย่างเดียว."""
    text = {"type": "text", "text": style["note_title"], "weight": "bold", "size": "md",
            "color": style["note_color"]}
    icon = asset_url(style["note_icon"]) if style.get("note_icon") else None
    if not icon:
        return text
    return {"type": "box", "layout": "baseline", "spacing": "sm", "contents": [
        {"type": "icon", "url": icon, "size": "lg"}, text]}


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


def section_title(text: str) -> dict:
    return {"type": "text", "text": text, "weight": "bold", "size": "md", "color": TEXT_STRONG}


def bullet(text: str) -> dict:
    return {"type": "box", "layout": "horizontal", "spacing": "sm", "contents": [
        {"type": "text", "text": "●", "size": "xs", "color": BULLET_COLOR, "flex": 0, "gravity": "top"},
        {"type": "text", "text": text, "size": "sm", "color": TEXT_BODY, "wrap": True, "flex": 1},
    ]}


def card_style(result: dict) -> dict | None:
    """เลือกแบบการ์ดจากสถานะ; ผลที่เตือน (is_scam=True เช่นกฎสำรองในกลุ่ม) ใช้แบบพบสัญญาณเสี่ยงเสมอ."""
    status = result.get("status")
    if result.get("is_scam") is True:
        status = "risk_found"
    return STATUS_STYLES.get(status)


def build_result_card(result: dict, *, source: str, quote: str, case_id: str | None,
                      allow_postback: bool = False, group: bool = False) -> dict | None:
    """รับผลตรวจ คืน Flex Message หนึ่งข้อความ หรือ None ถ้าสถานะนี้ไม่ใช้การ์ด.

    source: "text" หรือ "image" ใช้บอกที่มา; quote: ข้อความที่ตรวจ (จากรูปคือข้อความ OCR)
    group: การ์ดแชตกลุ่ม ไม่มีปุ่มรายละเอียดและไม่มีลิงก์ส่วนตัว
    """
    style = card_style(result)
    if style is None:
        return None

    reasons = reason_items(result.get("reason"))
    kicker = "ผลตรวจข้อความจากรูปภาพ" if source == "image" else "ผลตรวจข้อความ"

    header_contents = [{
        "type": "box", "layout": "vertical", "flex": 1, "justifyContent": "center", "spacing": "xs",
        "contents": [
            {"type": "text", "text": kicker, "size": "sm", "color": TEXT_STRONG, "wrap": True},
            {"type": "text", "text": style["title"], "weight": "bold", "size": "lg",
             "color": TEXT_STRONG, "wrap": True},
        ],
    }]
    image = mascot_url(style["pose"])
    if image:
        header_contents.append({"type": "image", "url": image, "size": "64px",
                                "aspectRatio": "1:1", "aspectMode": "fit", "flex": 0})

    body = [
        section_title("ข้อความที่พบ"),
        {"type": "box", "layout": "vertical", "backgroundColor": QUOTE_BACKGROUND,
         "cornerRadius": "12px", "paddingAll": "12px", "contents": [
             {"type": "text", "text": f"“{shorten(quote, QUOTE_LIMIT)}”", "size": "sm",
              "color": TEXT_BODY, "wrap": True}]},
        section_title("เหตุผล"),
        {"type": "box", "layout": "vertical", "spacing": "xs",
         "contents": [bullet(item) for item in reasons]},
        {"type": "box", "layout": "vertical", "spacing": "xs", "backgroundColor": style["note_background"],
         "cornerRadius": "12px", "paddingAll": "12px", "contents": [
             note_heading(style),
             {"type": "text", "text": style["advice"], "size": "sm", "color": TEXT_BODY, "wrap": True}]},
        {"type": "text", "text": DISCLAIMER, "size": "xxs", "color": TEXT_MUTED, "wrap": True},
    ]

    bubble = {
        "type": "bubble",
        "header": {"type": "box", "layout": "horizontal", "alignItems": "center", "spacing": "md",
                   "backgroundColor": style["header"], "paddingAll": "16px",
                   "contents": header_contents},
        "body": {"type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "16px",
                 "backgroundColor": "#FFFFFF", "contents": body},
    }
    action = None if group else detail_action(case_id, allow_postback)
    if action:
        bubble["footer"] = {"type": "box", "layout": "vertical", "paddingAll": "12px",
                            "paddingTop": "0px", "contents": [
            {"type": "button", "style": "primary", "height": "sm", "color": BUTTON_COLOR, "action": action}]}

    # altText แสดงในรายการแชต/แจ้งเตือน LINE จำกัด 400 ตัวอักษร
    alt_text = shorten(f"{style['title']}: {' '.join(reasons)}", 390)
    return {"type": "flex", "altText": alt_text, "contents": bubble}
