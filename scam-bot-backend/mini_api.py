"""API ของ Mini App: อ่าน/ลบประวัติของเจ้าของ หลังตรวจ ID token กับ LINE แล้วเท่านั้น."""
import math
import os
import re
import time
from urllib.parse import urlsplit

import requests
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse


PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


# get_mini_case_url: ตรวจ LIFF ID, channel ID และรหัสเคสก่อนคืนลิงก์รายละเอียดที่ไม่มีข้อมูลผู้ใช้; ค่าผิดคืน None
def get_mini_case_url(case_id: str) -> str | None:
    liff_id = os.getenv("MINI_LIFF_ID", "").strip()
    channel_id = os.getenv("LINE_LOGIN_CHANNEL_ID", "").strip()
    if (re.fullmatch(r"[0-9]+-[A-Za-z0-9]+", liff_id)
            and re.fullmatch(r"[0-9]+", channel_id)
            and re.fullmatch(r"[0-9a-f]{32}", case_id)):
        # URL มีแค่รหัสสุ่ม ไม่มีข้อความ ผู้ใช้ หรือ token
        return f"https://liff.line.me/{liff_id}?case={case_id}"
    return None


# mini_web_origins: อ่าน origin ที่อนุญาตให้เรียก Mini API; คืนรายการว่างเมื่อไม่ตั้งค่า และยก ValueError เมื่อรูปแบบผิด
def mini_web_origins() -> list[str]:
    origin = os.getenv("MINI_WEB_ORIGIN", "").strip().rstrip("/")
    if not origin:
        return []
    parts = urlsplit(origin)
    local_http = parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1"}
    if (not parts.hostname or (parts.scheme != "https" and not local_http)
            or parts.username or parts.password or parts.path or parts.query or parts.fragment):
        raise ValueError("MINI_WEB_ORIGIN must be one HTTPS origin (localhost HTTP is allowed)")
    return [origin]


# mini_error: สร้าง HTTPException พร้อม header ห้าม cache และห้ามส่ง referrer สำหรับข้อมูลส่วนตัว
def mini_error(code: int, message: str) -> HTTPException:
    return HTTPException(code, message, headers=PRIVATE_HEADERS)


# verify_line_owner: ส่ง ID token ให้ LINE ยืนยันและตรวจผู้ให้บริการ ช่องทาง กับอายุ; คืน owner หรือปฏิเสธด้วย 401/503
def verify_line_owner(authorization: str) -> str:
    channel_id = os.getenv("LINE_LOGIN_CHANNEL_ID", "").strip()
    if not re.fullmatch(r"[0-9]+", channel_id):
        raise mini_error(503, "ยังไม่ได้ตั้งค่าการเชื่อมต่อ LINE ของ Mini App")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 8192 or any(c.isspace() for c in token):
        raise mini_error(401, "กรุณาเปิดผลตรวจจาก LINE และเข้าสู่ระบบใหม่")
    try:
        response = requests.post(
            "https://api.line.me/oauth2/v2.1/verify",
            data={"id_token": token, "client_id": channel_id}, timeout=10,
            allow_redirects=False,
        )
        if response.status_code in {400, 401, 403}:
            raise mini_error(401, "การเข้าสู่ระบบหมดอายุหรือไม่ถูกต้อง กรุณาเปิดจาก LINE ใหม่")
        if response.status_code != 200:
            raise mini_error(503, "LINE ยังยืนยันการเข้าสู่ระบบไม่ได้ กรุณาลองใหม่")
        identity = response.json()
    except (requests.RequestException, ValueError):
        # ห้ามส่ง exception ดิบกลับ เพราะอาจมี token หรือข้อมูลผู้ใช้
        raise mini_error(503, "ติดต่อระบบยืนยันตัวตน LINE ไม่สำเร็จ กรุณาลองใหม่") from None
    if not isinstance(identity, dict):
        raise mini_error(503, "ข้อมูลยืนยันตัวตนจาก LINE ไม่สมบูรณ์")
    owner = identity.get("sub")
    expires = identity.get("exp")
    if (identity.get("iss") != "https://access.line.me" or identity.get("aud") != channel_id
            or not isinstance(owner, str) or not owner.strip() or len(owner) > 128
            or type(expires) not in (int, float) or not math.isfinite(expires) or expires <= time.time()):
        raise mini_error(401, "การเข้าสู่ระบบหมดอายุหรือไม่ถูกต้อง กรุณาเปิดจาก LINE ใหม่")
    return owner


NOT_FOUND_MESSAGE = "เปิดผลตรวจนี้ไม่ได้ เคสอาจถูกลบหรือไม่ใช่เคสของคุณ"
UNAVAILABLE_MESSAGE = "ระบบประวัติขัดข้อง กรุณาลองใหม่ภายหลัง"


# create_mini_router: สร้าง API /api/mini ให้ Mini App: ดูประวัติ ลบประวัติ ดูเคส
def create_mini_router(history) -> APIRouter:
    """history: โมดูล mini_history หรือของจำลองที่มี list_cases/get_case/delete_all."""
    router = APIRouter(prefix="/api/mini", tags=["Mini App"])

    # ask_history: เรียกงานประวัติแล้วคืนผลเดิม; แปลง HistoryUnavailable เป็น 503 โดยซ่อน error ดิบ
    def ask_history(action):
        # ระบบประวัติล่มตอบ 503 ข้อความกลาง ไม่ส่งรายละเอียด error กลับ
        try:
            return action()
        except history.HistoryUnavailable:
            raise mini_error(503, UNAVAILABLE_MESSAGE) from None

    # read_history: ยืนยันเจ้าของด้วย token แล้วคืนรายการประวัติของคนนั้นพร้อม header ห้าม cache
    @router.get("/history")
    def read_history(authorization: str = Header(default="")):
        owner = verify_line_owner(authorization)
        cases = ask_history(lambda: history.list_cases(owner))
        return JSONResponse({"cases": cases}, headers=PRIVATE_HEADERS)

    # delete_history: ยืนยันเจ้าของก่อนลบประวัติส่วนตัวของคนนั้น แล้วคืนจำนวนรายการที่ผู้ใช้มองเห็นและถูกลบ
    @router.delete("/history")
    def delete_history(authorization: str = Header(default="")):
        owner = verify_line_owner(authorization)
        deleted = ask_history(lambda: history.delete_all(owner))
        return JSONResponse({"deleted": deleted}, headers=PRIVATE_HEADERS)

    # read_case: ยืนยันเจ้าของและรหัสเคสก่อนคืนรายละเอียด; เคสหายหรือผิดเจ้าของตอบ 404 แบบเดียวกัน
    @router.get("/cases/{case_id}")
    def read_case(case_id: str, authorization: str = Header(default="")):
        owner = verify_line_owner(authorization)
        if not re.fullmatch(r"[0-9a-f]{32}", case_id):
            raise mini_error(404, NOT_FOUND_MESSAGE)
        detail = ask_history(lambda: history.get_case(case_id, owner))
        if detail is None:
            # คำตอบเหมือนกันสำหรับรหัสที่ไม่มี ถูกลบ หรือผิดเจ้าของ
            raise mini_error(404, NOT_FOUND_MESSAGE)
        return JSONResponse(detail, headers=PRIVATE_HEADERS)

    return router
