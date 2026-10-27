import math
import re
import requests
from copy import deepcopy
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit, urlunsplit
from config import SAFE_BROWSING_API_KEY
from safe_browsing_proto import decode_safe_browsing_response


# shortcut: cache อยู่ใน process เดียว, ใช้ที่เก็บร่วมเมื่อรันหลาย worker
_url_cache = {}
_url_cache_lock = Lock()
_URL_CACHE_MAX_ENTRIES = 1000


def extract_urls(text: str) -> list[str]:
    """ดึงลิงก์ HTTP/HTTPS ที่ไม่ซ้ำ โดยรักษาลำดับเดิม."""
    if not isinstance(text, str):
        raise ValueError("Text must be a string")

    urls = []
    # shortcut: ใช้ช่องว่างและอัญประกาศเป็นตัวคั่น, ขยายเมื่อรองรับวงเล็บและ URL จาก OCR หลายบรรทัด
    pattern = r'https?://[^\s<>"“”]+'

    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        url = match.group(0)
        if url not in urls:
            urls.append(url)

    return urls

def validate_url(url: str) -> str:
    if not isinstance(url,str):
        raise ValueError("URL must be a string")

    url = url.strip()

    # จำกัดขนาดข้อมูลที่บอทรับตรวจต่อหนึ่งลิงก์
    if not url or len(url) > 4096:
        raise ValueError("Invalid URL length")

    # กรองช่องว่างและอักขระควบคุมที่มองไม่เห็น
    has_invalid_character = any(
        character.isspace()
        or ord(character) < 32
        or ord(character) == 127
        for character in url
    )

    if has_invalid_character or "\\" in url:
        raise ValueError("Invalid URL characters")

    try:
        parsed =  urlsplit(url)
        port = parsed.port
    except ValueError:
        raise ValueError("Invalid URL format") from None

    if parsed.scheme not in {"http",  "https"} or not parsed.hostname:
        raise ValueError("URL must use HTTP or HTTPS and have a host")

    if parsed.username is not  None or parsed.password is not None:
        raise ValueError("URL must not contain creddentials")

    if port == 0:
        raise ValueError("Invalid URL port")
        
    # ส่วนหลัง # ไม่จำเป็นสำหรับการตรวจ URL ปลายทาง
    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.query,
        "",
    ))

def parse_safe_browsing_response(data: object) -> tuple[dict, float]:
    """แปลงผลจาก Google เป็นผลตรวจและอายุ cache หน่วยวินาที."""
    if not isinstance(data, dict):
        raise ValueError("Invalid response format")

    cache_duration = data.get("cacheDuration")
    if (
        not isinstance(cache_duration, str)
        or re.fullmatch(r"[0-9]+(?:\.[0-9]{1,9})?s", cache_duration) is None
    ):
        raise ValueError("Invalid cache duration")

    cache_seconds = float(cache_duration[:-1])
    if not math.isfinite(cache_seconds):
        raise ValueError("Invalid cache duration")

    threats = data.get("threats", [])
    if not isinstance(threats, list):
        raise ValueError("Invalid threats list")

    threat_types = set()
    for threat in threats:
        if not isinstance(threat, dict):
            raise ValueError("Invalid threat entry")

        matched_url = threat.get("url")
        if not isinstance(matched_url, str) or not matched_url.strip():
            raise ValueError("Missing matched URL")

        types = threat.get("threatTypes")
        if not isinstance(types, list) or not types:
            raise ValueError("Missing threat types")

        for threat_type in types:
            if (
                not isinstance(threat_type, str)
                or re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", threat_type) is None
            ):
                raise ValueError("Invalid threat type")
            threat_types.add(threat_type)

    result = {
        "status": "matched" if threats else "not_found",
        "threat_types": sorted(threat_types),
    }
    return result, cache_seconds



def  _request_safe_browsing(url: str) -> tuple[dict, float]:
    """เรียก Google แล้วคืนผลตรวจพร้อมอายุ cache."""
    checked_url = validate_url(url)

    if not SAFE_BROWSING_API_KEY:
        raise ValueError("Missing Safe Browing API key")

    with requests.get(
        "https://safebrowsing.googleapis.com/v5/urls:search",
        params={
            "key": SAFE_BROWSING_API_KEY,
            "urls": checked_url,
        },
        timeout=(5,10),
        allow_redirects=False,
    ) as response:
        if response.status_code !=200:
            raise ValueError(
                f"Safe  Browsing HTTP {response.status_code}"
            )
        data = decode_safe_browsing_response(response.content)
        return parse_safe_browsing_response(data)



def check_url(url: str) -> dict:
    """ตรวจหนึ่ง URL; คืน matched, not_found หรือ error."""
    try:
        checked_url = validate_url(url)

        with _url_cache_lock:
            now = monotonic()
            expired_urls = [
                cached_url
                for cached_url, (expires_at, _) in _url_cache.items()
                if expires_at <= now
            ]
            for cached_url in expired_urls:
                del _url_cache[cached_url]

            cached = _url_cache.get(checked_url)
            if cached is not None:
                return deepcopy(cached[1])

        result, cache_seconds = _request_safe_browsing(checked_url)

        if cache_seconds > 0:
            with _url_cache_lock:
                if (
                    checked_url not in _url_cache
                    and len(_url_cache) >= _URL_CACHE_MAX_ENTRIES
                ):
                    oldest_url = next(iter(_url_cache))
                    del _url_cache[oldest_url]

                _url_cache[checked_url] = (
                    monotonic() + cache_seconds,
                    deepcopy(result),
                )

        return result

    except (ValueError, requests.RequestException) as error:
        print(f"[URL ERROR] type={type(error).__name__}")
        return {"status": "error", "threat_types": []}