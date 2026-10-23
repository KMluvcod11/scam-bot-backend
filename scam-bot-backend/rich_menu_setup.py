"""เตรียม/ติดตั้ง Rich Menu; ค่าเริ่มต้นตรวจไฟล์ในเครื่อง ไม่เปลี่ยนบัญชี LINE."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys

from dotenv import load_dotenv
import requests


ROOT = Path(__file__).resolve().parent
IMAGE_PATH = ROOT / "rich_menu" / "menu.png"
STATE_PATH = ROOT / "rich_menu" / "deployment.local.json"


def build_rich_menu(liff_id):
    if not isinstance(liff_id, str) or not re.fullmatch(r"[0-9]+-[A-Za-z0-9]+", liff_id):
        raise ValueError("MINI_LIFF_ID is missing or invalid")
    liff_url = f"https://liff.line.me/{liff_id}"
    return {
        "size": {"width": 2500, "height": 843},
        "selected": True,
        "name": "EhBot three actions v1",
        "chatBarText": "เมนู Eh?Bot",
        "areas": [
            {"bounds": {"x": 0, "y": 0, "width": 1000, "height": 843},
             # เปิด Mini App หน้าประวัติ; main.py ยังรับ menu:check ไว้สำหรับเมนูเก่าที่ยังค้างในเครื่องผู้ใช้
             "action": {"type": "uri", "label": "ตรวจข้อความ", "uri": liff_url + "/history"}},
            {"bounds": {"x": 1000, "y": 0, "width": 740, "height": 843},
             "action": {"type": "uri", "label": "เรียนรู้กลโกง", "uri": liff_url + "/lessons"}},
            {"bounds": {"x": 1740, "y": 0, "width": 760, "height": 843},
             "action": {"type": "uri", "label": "วิธีใช้งาน", "uri": liff_url + "/help"}},
        ],
    }


def validate_menu_image(image_path):
    image = image_path.read_bytes()
    if len(image) > 1_000_000 or image[:8] != b"\x89PNG\r\n\x1a\n" or len(image) < 24:
        raise ValueError("Rich menu must be a PNG no larger than 1 MB")
    if struct.unpack(">II", image[16:24]) != (2500, 843):
        raise ValueError("Rich menu image must be 2500x843")
    return image


def line_call(method, path, token, *, payload=None, image=None, allow_missing=False):
    base = "https://api-data.line.me" if image is not None else "https://api.line.me"
    headers = {"Authorization": f"Bearer {token}"}
    if image is not None:
        headers["Content-Type"] = "image/png"
    try:
        response = requests.request(method, base + path, headers=headers,
                                    json=payload, data=image, timeout=(5, 20), allow_redirects=False)
    except requests.RequestException:
        raise RuntimeError("Cannot reach LINE API; no automatic retry was made") from None
    if allow_missing and response.status_code == 404:
        return None
    if response.status_code != 200:
        # ไม่พิมพ์ response หรือ exception ดิบที่อาจมีข้อมูลบัญชีหรือ token
        raise RuntimeError(f"LINE API returned HTTP {response.status_code}")
    try:
        return response.json() if response.content else {}
    except ValueError:
        raise RuntimeError("LINE API returned invalid JSON") from None


def get_default_menu(token):
    result = line_call("GET", "/v2/bot/user/all/richmenu", token, allow_missing=True)
    if result is None:
        return None
    menu_id = result.get("richMenuId") if isinstance(result, dict) else None
    if not valid_menu_id(menu_id):
        raise RuntimeError("LINE API returned an invalid default menu ID")
    return menu_id


def valid_menu_id(menu_id):
    return isinstance(menu_id, str) and re.fullmatch(r"richmenu-[A-Za-z0-9]+", menu_id) is not None


def write_state(state_path, state):
    temporary_path = state_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(state_path)


def publish_menu(token, definition, image_path=IMAGE_PATH, state_path=STATE_PATH):
    image = validate_menu_image(image_path)
    fingerprint = hashlib.sha256(image + json.dumps(definition, sort_keys=True).encode()).hexdigest()
    previous_id = get_default_menu(token)
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("phase") != "restored":
            if previous_id == state.get("new_menu_id") and fingerprint == state.get("fingerprint"):
                return {"status": "already_active", "richMenuId": previous_id}
            raise RuntimeError("A deployment record exists; restore or review it before publishing again")
    line_call("POST", "/v2/bot/richmenu/validate", token, payload=definition)
    created = line_call("POST", "/v2/bot/richmenu", token, payload=definition)
    menu_id = created.get("richMenuId", "") if isinstance(created, dict) else ""
    if not valid_menu_id(menu_id):
        raise RuntimeError("LINE API returned an invalid rich menu ID")
    state = {"previous_menu_id": previous_id, "new_menu_id": menu_id,
             "fingerprint": fingerprint, "phase": "created"}
    # เก็บทางย้อนกลับก่อนอัปโหลดหรือเปลี่ยนเมนูเดิม; ไฟล์นี้ไม่มี token
    write_state(state_path, state)
    line_call("POST", f"/v2/bot/richmenu/{menu_id}/content", token, image=image)
    line_call("POST", f"/v2/bot/user/all/richmenu/{menu_id}", token)
    if get_default_menu(token) != menu_id:
        raise RuntimeError("Cannot confirm the active menu; keep the deployment record for restore")
    state["phase"] = "active"
    write_state(state_path, state)
    return {"status": "active", "richMenuId": menu_id}


def restore_menu(token, state_path=STATE_PATH):
    state = json.loads(state_path.read_text(encoding="utf-8"))
    previous = state["previous_menu_id"]
    if not valid_menu_id(state.get("new_menu_id")) or (previous is not None and not valid_menu_id(previous)):
        raise ValueError("Invalid deployment record")
    current = get_default_menu(token)
    if current != previous:
        # ไม่ทับเมนูที่คนอื่นอาจเปลี่ยนไว้หลังจากเรา deploy
        if current != state["new_menu_id"]:
            raise RuntimeError("The active menu was changed elsewhere; restore was stopped")
        if previous:
            line_call("POST", f"/v2/bot/user/all/richmenu/{previous}", token)
        else:
            line_call("DELETE", "/v2/bot/user/all/richmenu", token)
        if get_default_menu(token) != previous:
            raise RuntimeError("Cannot confirm the restored menu")
    state["phase"] = "restored"
    write_state(state_path, state)
    return {"status": "restored", "richMenuId": previous}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="plan", choices=["plan", "status", "validate", "publish", "restore"])
    parser.add_argument("--apply", action="store_true", help="Required for changes to LINE")
    args = parser.parse_args()
    if args.command in {"publish", "restore"} and not args.apply:
        parser.error("No changes made. Add --apply only after reviewing the menu")
    load_dotenv(ROOT / ".env")
    try:
        if args.command == "plan":
            validate_menu_image(IMAGE_PATH)
            result = build_rich_menu(os.getenv("MINI_LIFF_ID", "").strip())
        else:
            token = os.getenv("CHANNEL_ACCESS_TOKEN", "").strip()
            if not token:
                raise ValueError("CHANNEL_ACCESS_TOKEN is missing")
            if args.command == "status":
                result = {"apiDefaultRichMenuId": get_default_menu(token)}
            elif args.command == "validate":
                image = validate_menu_image(IMAGE_PATH)
                definition = build_rich_menu(os.getenv("MINI_LIFF_ID", "").strip())
                line_call("POST", "/v2/bot/richmenu/validate", token, payload=definition)
                result = {"valid": True, "imageBytes": len(image)}
            elif args.command == "publish":
                definition = build_rich_menu(os.getenv("MINI_LIFF_ID", "").strip())
                result = publish_menu(token, definition)
            else:
                result = restore_menu(token)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, RuntimeError, OSError, KeyError):
        # ข้อความจาก requests/ไฟล์ตั้งค่าอาจมีค่าลับ จึงคืนเฉพาะชนิดเหตุการณ์
        print("Rich menu command failed. Check configuration, image, LINE permissions, and deployment record.")
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
