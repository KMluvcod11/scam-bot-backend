"""สร้างการ์ดผลตรวจ (LINE Flex Message) จากผลเดิม ไม่เรียก AI และไม่ส่ง LINE เอง.

การ์ดไม่แสดงระดับความเสี่ยง (risk_level) ค่านั้นยังอยู่ในผลตรวจและประวัติให้ Dashboard ใช้ตามเดิม
"""
import re

from learning import LESSON_TOPICS
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
LONG_QUOTE = "ข้อความยาวเกินพื้นที่การ์ด"
LONG_REASON = "ยังมีเหตุผลเพิ่มเติมที่ไม่ได้แสดงในการ์ด"
FULL_TEXT_HINT = "ดูฉบับเต็มได้ที่ปุ่ม “ดูรายละเอียด”"


# reason_items: แยกเหตุผลจากผลตรวจเป็นรายการทีละข้อ สำหรับแสดงในการ์ด
def reason_items(reason) -> list[str]:
    """แยกเหตุผลเป็นข้อ ๆ ตามขึ้นบรรทัดใหม่หรือ • ที่มากับผลตรวจ ไม่มีก็เป็นข้อเดียว."""
    if not isinstance(reason, str) or not reason.strip():
        return ["ไม่มีเหตุผลเพิ่มเติมจากผลตรวจ"]
    parts = [part.strip(" -–•\t") for part in re.split(r"[\r\n•]+", reason)]
    parts = [part for part in parts if part] or [reason.strip()]
    shown = []
    used = 0
    for part in parts[:REASON_ITEMS]:
        if used + len(part) > REASON_LIMIT:
            break
        shown.append(part)
        used += len(part)
    if len(shown) < len(parts):
        shown.append(LONG_REASON)
    return shown


# defang_links: ทำลิงก์ให้กดไม่ได้ https://a.com → hxxps://a[.]com
def defang_links(text: str) -> str:
    """ทำลิงก์ให้อ่านออกแต่กดไม่ได้ เช่น https://a.com → hxxps://a[.]com.

    ข้อความธรรมดาที่บอตส่ง LINE เปลี่ยนลิงก์ให้กดได้อัตโนมัติ
    บอตจึงต้องไม่ส่งลิงก์จากข้อความมิจฉาชีพกลับเข้าแชตในสภาพที่กดได้
    """
    text = re.sub(r"\b(h)tt(ps?)://", r"\1xx\2://", text, flags=re.IGNORECASE)
    # จุดที่ตามด้วยตัวอักษรอังกฤษคือจุดในชื่อโดเมน; จุดทศนิยมเช่น 1.5 ไม่ถูกแก้
    return re.sub(r"(?<=[A-Za-z0-9-])\.(?=[A-Za-z])", "[.]", text)


# join_words: ต่อคำตามตำแหน่งที่เลือก ใส่ … ตรงช่วงที่ข้ามไป
def join_words(words: list[str], chosen: set[int]) -> str:
    pieces = []
    previous = -1
    for index in sorted(chosen):
        if index != previous + 1:
            pieces.append("…")
        pieces.append(words[index])
        previous = index
    if previous != len(words) - 1:
        pieces.append("…")
    return " ".join(pieces)


# important_text: เลือกช่วงสำคัญของข้อความยาวมาแสดงในการ์ด
def important_text(quote: str) -> str:
    """รับข้อความที่ปกปิดเบอร์แล้ว คืนช่วงที่มีคำค้นและช่วงข้างเคียง ยาวไม่เกิน QUOTE_LIMIT; ไม่เรียก AI.

    แบ่งตรงช่องว่างเท่านั้นเพื่อไม่ตัดกลางคำไทย; ไม่พบคำค้นใช้ช่วงต้น; ใส่ไม่ได้เลยคืน ""
    """
    words = quote.split()
    # ค้นคำจากข้อความเดิม เพราะหลัง defang แล้ว https:// จะกลายเป็น hxxps://
    matches = []
    for keywords, *_ in LESSON_TOPICS:
        for index, word in enumerate(words):
            if any(keyword in word.lower() for keyword in keywords):
                matches.append(index)
                break
    safe_words = [defang_links(word) for word in words]
    chosen = set()

    # add: เลือกคำเพิ่มเมื่อผลรวมยังไม่เกินพื้นที่; คืน False เมื่อใส่ไม่ได้
    def add(index: int) -> bool:
        if len(join_words(safe_words, chosen | {index})) > QUOTE_LIMIT:
            return False
        chosen.add(index)
        return True

    # ใส่คำที่ตรงของทุกหัวข้อก่อน แล้วค่อยเติมบริบทข้างเคียง
    for index in matches:
        add(index)
    if chosen:
        for index in sorted(chosen):
            for neighbor in (index - 1, index + 1):
                if 0 <= neighbor < len(words):
                    add(neighbor)
    else:
        for index in range(len(words)):
            if not add(index):
                break
    return join_words(safe_words, chosen) if chosen else ""


# asset_url: สร้าง URL รูปไอคอนจากเว็บ Mini App (ต้องเป็น HTTPS)
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


# note_heading: สร้างหัวกรอบคำเตือน/คำแนะนำในการ์ด
def note_heading(style: dict) -> dict:
    """หัวกรอบคำเตือน/คำแนะนำ; มีไอคอนเมื่อโหลดรูปได้ ไม่งั้นเป็นตัวหนังสืออย่างเดียว."""
    text = {"type": "text", "text": style["note_title"], "weight": "bold", "size": "md",
            "color": style["note_color"]}
    icon = asset_url(style["note_icon"]) if style.get("note_icon") else None
    if not icon:
        return text
    # layout baseline วางไอคอนลอยสูงกว่าตัวหนังสือ จึงใช้ horizontal จัดกึ่งกลางแนวตั้ง
    image = {"type": "image", "url": icon, "size": "20px", "aspectRatio": "1:1", "flex": 0}
    text.update({"flex": 1, "gravity": "center"})
    return {"type": "box", "layout": "horizontal", "spacing": "sm", "alignItems": "center",
            "contents": [image, text]}


# detail_action: สร้างปุ่ม 'ดูรายละเอียด' ในการ์ด (เปิด Mini App หรือ postback)
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


# card_style: เลือกสี/ข้อความของการ์ดตามสถานะผลตรวจ
def card_style(result: dict) -> dict | None:
    """เลือกแบบการ์ดจากสถานะ; ผลที่เตือน (is_scam=True เช่นกฎสำรองในกลุ่ม) ใช้แบบพบสัญญาณเสี่ยงเสมอ."""
    status = result.get("status")
    if result.get("is_scam") is True:
        status = "risk_found"
    return STATUS_STYLES.get(status)


# build_result_card: สร้างการ์ด Flex ผลตรวจ 1 ใบ
# build_help_card: การ์ดทักทาย/วิธีใช้ในแชตส่วนตัว เนื้อหาเดียวกับ main.PRIVATE_HELP ที่เป็นข้อความสำรอง
def build_help_card() -> dict:
    greeting = [{"type": "text", "text": "สวัสดีครับ", "weight": "bold", "size": "xl",
                 "color": TEXT_STRONG, "flex": 1, "gravity": "center"}]
    image = mascot_url("calm")
    if image:
        greeting.insert(0, {"type": "image", "url": image, "size": "72px",
                            "aspectRatio": "1:1", "aspectMode": "fit", "flex": 0})
    body = [
        {"type": "box", "layout": "horizontal", "spacing": "md", "alignItems": "center", "contents": greeting},
        {"type": "text", "text": "ผมช่วยประเมินข้อความที่อาจเสี่ยงต่อการหลอกลวง ส่งข้อความที่สงสัยมาได้เลยครับ",
         "size": "md", "color": TEXT_BODY, "wrap": True},
        section_title("ส่งอะไรได้บ้าง"),
        {"type": "box", "layout": "vertical", "spacing": "xs", "contents": [
            bullet("ข้อความที่สงสัย คัดลอกมาวางได้เลย"),
            bullet("รูปแคปหน้าจอแชตหรือ SMS")]},
        {"type": "box", "layout": "vertical", "spacing": "xs", "backgroundColor": "#FFF4DE",
         "cornerRadius": "12px", "paddingAll": "12px", "contents": [
             {"type": "text", "text": "คำแนะนำ", "weight": "bold", "size": "md", "color": "#92600A"},
             {"type": "text", "text": "ปิดบังข้อมูลส่วนตัว และอย่าส่ง OTP หรือรหัสผ่าน", "size": "sm",
              "color": TEXT_BODY, "wrap": True},
             {"type": "text", "text": "หากส่งลิงก์ ผมยังไม่ได้เปิดตรวจเว็บไซต์ปลายทาง", "size": "sm",
              "color": TEXT_BODY, "wrap": True}]},
    ]
    bubble = {
        "type": "bubble",
        "header": {"type": "box", "layout": "vertical", "backgroundColor": "#BDF3D8", "paddingAll": "16px",
                   "contents": [{"type": "text", "text": "Eh?Bot ผู้ช่วยเช็กข้อความ", "weight": "bold",
                                 "size": "md", "color": TEXT_STRONG, "wrap": True, "align": "center"}]},
        "body": {"type": "box", "layout": "vertical", "spacing": "lg", "paddingAll": "20px",
                 "backgroundColor": "#FFFFFF", "contents": body},
    }
    return {"type": "flex", "altText": "สวัสดีครับ ส่งข้อความที่สงสัยมาให้ Eh?Bot ช่วยดูได้เลย", "contents": bubble}


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

    quote_is_long = len(quote) > QUOTE_LIMIT
    if quote_is_long:
        quote_title = "ข้อความสำคัญ"
        quote_text = important_text(quote) or LONG_QUOTE
    else:
        quote_title = "ข้อความที่พบ"
        quote_text = f"“{quote}”"
    reasons_box = {"type": "box", "layout": "vertical", "spacing": "xs",
                   "contents": [bullet(item) for item in reasons]}

    body = [
        {"type": "box", "layout": "horizontal", "spacing": "md", "alignItems": "center",
         "contents": status_contents},
        section_title(quote_title),
        {"type": "box", "layout": "vertical", "backgroundColor": QUOTE_BACKGROUND,
         "cornerRadius": "12px", "paddingAll": "12px", "contents": [
             {"type": "text", "text": quote_text, "size": "sm",
              "color": TEXT_BODY, "wrap": True}]},
        section_title("เหตุผล"),
        reasons_box,
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
    # ชี้ไปฉบับเต็มเฉพาะปุ่มที่เปิด Mini App; ปุ่ม postback เปิดแค่บทเรียน
    shortened = quote_is_long or LONG_REASON in reasons
    if shortened and action and action["type"] == "uri":
        hint = {"type": "text", "text": FULL_TEXT_HINT, "size": "xs", "color": TEXT_MUTED, "wrap": True}
        body.insert(body.index(reasons_box) + 1, hint)
    if action:
        bubble["footer"] = {"type": "box", "layout": "vertical", "paddingAll": "12px",
                            "paddingTop": "0px", "contents": [
            {"type": "button", "style": "primary", "height": "md", "color": BUTTON_COLOR, "action": action}]}

    # altText แสดงในรายการแชต/แจ้งเตือน LINE จำกัด 400 ตัวอักษร
    alt_text = f"{kicker}: {style['title']}"
    return {"type": "flex", "altText": alt_text, "contents": bubble}
