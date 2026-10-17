"""อ่านเคสชั่วคราวของเจ้าของ หลังตรวจ ID token กับ LINE แล้วเท่านั้น."""
import math
import os
import re
import time
from urllib.parse import urlsplit

import requests
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse


PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def get_mini_case_url(case_id: str) -> str | None:
    liff_id = os.getenv("MINI_LIFF_ID", "").strip()
    channel_id = os.getenv("LINE_LOGIN_CHANNEL_ID", "").strip()
    if (re.fullmatch(r"[0-9]+-[A-Za-z0-9]+", liff_id)
            and re.fullmatch(r"[0-9]+", channel_id)
            and re.fullmatch(r"[0-9a-f]{32}", case_id)):
        # URL มีแค่รหัสสุ่ม ไม่มีข้อความ ผู้ใช้ หรือ token
        return f"https://liff.line.me/{liff_id}?case={case_id}"
    return None


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


def mini_error(code: int, message: str) -> HTTPException:
    return HTTPException(code, message, headers=PRIVATE_HEADERS)


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


def create_mini_router(get_store) -> APIRouter:
    router = APIRouter(prefix="/api/mini", tags=["Mini App"])

    @router.get("/cases/{case_id}")
    def read_case(case_id: str, authorization: str = Header(default="")):
        owner = verify_line_owner(authorization)
        if not re.fullmatch(r"[0-9a-f]{32}", case_id):
            raise mini_error(404, "เปิดผลตรวจนี้ไม่ได้ เคสอาจหมดอายุหรือไม่ใช่เคสของคุณ")
        detail = get_store().get_detail(case_id, owner)
        if detail is None:
            # คำตอบเหมือนกันสำหรับรหัสผิด หมดอายุ รีสตาร์ต หรือผิดเจ้าของ
            raise mini_error(404, "เปิดผลตรวจนี้ไม่ได้ เคสอาจหมดอายุหรือไม่ใช่เคสของคุณ")
        return JSONResponse(detail, headers=PRIVATE_HEADERS)

    return router
