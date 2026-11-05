"""สร้างการ์ดผลตรวจ (LINE Flex Message) จากผลเดิม ไม่เรียก AI และไม่ส่ง LINE เอง.

การ์ดไม่แสดงระดับความเสี่ยง (risk_level) ค่านั้นยังอยู่ในผลตรวจและประวัติให้ Dashboard ใช้ตามเดิม
"""
import re
import unicodedata

from mini_api import get_mini_case_url, mini_web_origins
from privacy import redact_phone


# สีหัวการ์ดตามสถานะ: แดงอ่อน = พบสัญญาณเสี่ยง, เหลืองอ่อน = ควรตรวจเพิ่ม, เขียวอ่อน = ยังไม่พบ
STATUS_STYLES = {
    "risk_found": {"title": "พบสัญญาณเสี่ยง", "pose": "alert", "header": "#FFB9C0",
                   "note_title": "คำเตือน", "note_icon": "icons/warning.png", "note_color": "#B42336", "note_background": "#FFE3E9",
                   "advice": "อย่าเพิ่งกดลิงก์ โอนเงิน หรือเปิดเผย OTP "
                             "ตรวจสอบผ่านช่องทางทางการก่อน"},
    "uncertain": {"title": "ยังประเมินไม่ได้", "pose": "inspect", "header": "#FFF0B3",
                  "note_title": "คำแนะนำ", "note_color": "#9A5B00", "note_background": "#FDF3E1",
                  "advice": "ข้อมูลยังไม่พอที่จะสรุป ตรวจผ่านช่องทางทางการก่อนทำตาม"},
    "no_risk_found": {"title": "ยังไม่พบสัญญาณเสี่ยง", "pose": "calm", "header": "#BDF3D8",
                      "note_title": "คำแนะนำ", "note_color": "#0F6E56", "note_background": "#DCFFF0",
                      "advice": "ผลนี้ไม่รับรองว่าปลอดภัย และไม่ได้ตรวจเว็บไซต์ปลายทาง"},
}
TEXT_STRONG = "#241A24"
TEXT_BODY = "#352B35"
TEXT_MUTED = "#62606A"
QUOTE_BACKGROUND = "#F1F3F5"
BULLET_COLOR = "#2BB58A"
BUTTON_COLOR = "#ED0961"
DISCLAIMER = "เป็นผลประเมินจากข้อความ ไม่ยืนยันตัวตนหรือข้อเท็จจริงของผู้ส่ง"
QUOTE_LIMIT = 150
REASON_LIMIT = 400
REASON_ITEMS = 5
LONG_QUOTE = "ข้อความยาว อ่านฉบับเต็มในข้อความถัดจากการ์ด"
LONG_REASON = "เหตุผลมีรายละเอียดเพิ่มเติม อ่านฉบับเต็มในข้อความถัดจากการ์ด"
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
    parts = [part for part in parts if part] or [reason.strip()]
    if len(parts) > REASON_ITEMS or sum(map(len, parts)) > REASON_LIMIT:
        return [LONG_REASON]
    return parts


def build_result_continuation(result: dict, *, source: str, quote: str) -> str:
    """คืนผลฉบับเต็มที่ปกปิดเบอร์แล้ว เมื่อเนื้อหาไม่พอดีการ์ด; ไม่เรียก AI."""
    style = card_style(result)
    if style is None:
        return ""
    quote = redact_phone(str(quote)) or ""
    reason = result.get("reason")
    reason = redact_phone(reason) if isinstance(reason, str) else ""
    reason = reason or "ไม่มีเหตุผลเพิ่มเติมจากผลตรวจ"
    if len(quote) <= QUOTE_LIMIT and reason_items(reason) != [LONG_REASON]:
        return ""
    title = "ผลตรวจข้อความจากรูปภาพ" if source == "image" else "ผลตรวจข้อความ"
    return (f"{title} — ฉบับเต็ม\n{style['title']}\n\nข้อความที่พบ\n{quote}"
            f"\n\nเหตุผล\n{reason}\n\n{style['note_title']}\n{style['advice']}"
            f"\n\n{DISCLAIMER}")


def asset_url(path: str) -> str | None:
    """รูปอยู่ใน public/ ของเว็บ Mini App; LINE ดึงรูปได้เฉพาะ HTTPS."""
    try:
        origins = mini_web_origins()
    except ValueError:
        return None
    if not origins or not origins[0].startswith("https://"):
        return None
    return f"{origins[0]}/{path}"


# mascot_url: คืน URL รูปมาสคอตตามชื่อท่าทาง หรือ None เมื่อยังไม่มีต้นทาง HTTPS ที่ใช้ได้
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


# section_title: แปลงข้อความหัวข้อเป็นองค์ประกอบ Flex แบบตัวหนา โดยใช้สีและขนาดร่วมของการ์ด
def section_title(text: str) -> dict:
    return {"type": "text", "text": text, "weight": "bold", "size": "md", "color": TEXT_STRONG}


# bullet: จัดข้อความหนึ่งข้อเป็นแถว Flex พร้อมจุดนำหน้าและเปิดการตัดบรรทัด
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

    # ปกปิดเบอร์แบบเดียวกับที่บันทึกประวัติ ก่อนตัดความยาว (ไม่ให้ตัดกลางเบอร์แล้วหลุดการปกปิด)
    quote = redact_phone(str(quote)) or ""
    reason = result.get("reason")
    reasons = reason_items(redact_phone(reason) if isinstance(reason, str) else reason)
    kicker = "ผลตรวจข้อความจากรูปภาพ" if source == "image" else "ผลตรวจข้อความ"

    status_contents = []
    image = mascot_url(style["pose"])
    if image:
        status_contents.append({"type": "image", "url": image, "size": "72px",
                                "aspectRatio": "1:1", "aspectMode": "fit", "flex": 0})
    status_contents.append({"type": "text", "text": style["title"], "weight": "bold",
                            "size": "lg", "color": style["note_color"], "wrap": True,
                            "flex": 1, "gravity": "center"})

    body = [
        {"type": "box", "layout": "horizontal", "spacing": "md", "alignItems": "center",
         "contents": status_contents},
        section_title("ข้อความที่พบ"),
        {"type": "box", "layout": "vertical", "backgroundColor": QUOTE_BACKGROUND,
         "cornerRadius": "12px", "paddingAll": "12px", "contents": [
             {"type": "text", "text": f"“{quote}”" if len(quote) <= QUOTE_LIMIT else LONG_QUOTE, "size": "sm",
              "color": TEXT_BODY, "wrap": True}]},
        section_title("เหตุผล"),
        {"type": "box", "layout": "vertical", "spacing": "xs",
         "contents": [bullet(item) for item in reasons]},
        {"type": "box", "layout": "vertical", "spacing": "xs", "backgroundColor": style["note_background"],
         "cornerRadius": "12px", "paddingAll": "12px", "contents": [
             note_heading(style),
             {"type": "text", "text": style["advice"], "size": "sm", "color": TEXT_BODY, "wrap": True}]},
        {"type": "text", "text": DISCLAIMER, "size": "xs", "color": TEXT_MUTED, "wrap": True},
    ]

    bubble = {
        "type": "bubble",
        "header": {"type": "box", "layout": "vertical",
                   "backgroundColor": style["header"], "paddingAll": "16px",
                   "contents": [{"type": "text", "text": kicker, "weight": "bold", "size": "md",
                                 "color": TEXT_STRONG, "wrap": True, "align": "center"}]},
        "body": {"type": "box", "layout": "vertical", "spacing": "lg", "paddingAll": "20px",
                 "backgroundColor": "#FFFFFF", "contents": body},
    }
    action = None if group else detail_action(case_id, allow_postback)
    if action:
        bubble["footer"] = {"type": "box", "layout": "vertical", "paddingAll": "12px",
                            "paddingTop": "0px", "contents": [
            {"type": "button", "style": "primary", "height": "md", "color": BUTTON_COLOR, "action": action}]}

    # altText แสดงในรายการแชต/แจ้งเตือน LINE จำกัด 400 ตัวอักษร
    alt_text = f"{kicker}: {style['title']}"
    return {"type": "flex", "altText": alt_text, "contents": bubble}
