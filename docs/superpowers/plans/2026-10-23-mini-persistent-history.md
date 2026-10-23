# Mini App: ประวัติจริงและดูเคสได้ตลอด Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** หน้า Mini App อ่านประวัติและรายละเอียดเคสจาก `detection_logs` ใน Supabase แทน RAM เปิดได้ตลอด และให้เจ้าของลบประวัติของตัวเองได้

**Architecture:** บอตสร้าง `case_id` (uuid) ก่อนตอบ ใส่ในลิงก์การ์ดและเป็น `id` ของแถวที่ `save_detection()` บันทึก โมดูลใหม่ `mini_history.py` อ่าน/ลบแถวตาม `sub` ที่ `verify_line_owner()` ยืนยันแล้ว `mini_api.py` เปิด 3 endpoint ส่วนหน้าเว็บโหลดประวัติผ่าน `useMiniSession()`

**Tech Stack:** Python 3.12, FastAPI, supabase-py, unittest · React + TypeScript + Vite, node:test

**Spec:** `docs/superpowers/specs/2026-10-23-mini-persistent-history-design.md`

## Global Constraints

- ห้าม commit/push จนกว่าผู้ใช้สั่ง (ผู้ใช้สั่งไว้ชัดเจน) — ขั้น "Commit" ในทุก task ให้ข้าม
- ไม่แก้ schema หรือ RLS ของ Supabase
- อ่านเฉพาะ `source_type = 'user'` และ `detection_status in ('risk_found','uncertain','no_risk_found')`; ลบทุกสถานะของ `sender_user_id = sub` ที่ `source_type = 'user'`
- รายการประวัติสูงสุด 50 รายการ เรียง `received_at desc`; `title` = 60 ตัวอักษรแรก (รวมช่องว่าง); `category` = `"message"`
- รหัสเคสใน URL = 32 ตัวฐานสิบหกไม่มีขีด (`uuid.hex`)
- ทุกคำตอบ API ใช้ `PRIVATE_HEADERS`; 404 ตอบเหมือนกันสำหรับไม่มี/ไม่ใช่เจ้าของ; 503 ข้อความ "ระบบประวัติขัดข้อง กรุณาลองใหม่ภายหลัง"; ห้ามส่ง/พิมพ์ exception ดิบ
- รูปภาพบันทึก `"[รูปภาพ] " + image_text` (ไม่มีข้อความใช้ `"[รูปภาพ]"`)
- `fetchMiniCase()` 404 ครั้งแรก รอ 1500 ms แล้วลองใหม่ 1 ครั้ง
- คอมเมนต์ภาษาไทยเฉพาะเหตุผลสำคัญ ตาม `AGENTS.md`
- Backend เทสต์รันจากโฟลเดอร์ `scam-bot-backend/scam-bot-backend`: `python -m unittest discover -s tests`

## Review Focus

1. ผู้ใช้ใหม่ที่ไม่มีประวัติเลย → API คืน `{"cases": []}` และหน้าเว็บแสดง empty state ไม่ใช่ error (Task 2, Task 5)
2. แถวเก่าที่ `reason` เป็น null หรือ `message_text` เป็น `"[รูปภาพ]"` → รายละเอียดยังเปิดได้ เหตุผลใช้ค่าสำรองจาก `build_case_detail()` (Task 1)
3. Supabase คืน `id` แบบมีขีด → แปลงเป็น hex ก่อนส่งให้หน้าเว็บ ไม่งั้นหน้าเว็บตัดรายการทิ้งเพราะผิดรูปแบบ (Task 1)
4. กด "ยืนยันลบ" ซ้ำเร็วๆ หรือระหว่างกำลังลบ → เรียก API ครั้งเดียว ปุ่มปิดระหว่างลบ (Task 6)
5. LINE ส่ง event ซ้ำ (redelivery) → `upsert ignore_duplicates` ไม่สร้างแถวที่สองด้วย `case_id` ใหม่ (Task 3)

---

### Task 1: `mini_history.py` อ่าน/ลบประวัติ

**Files:**
- Create: `scam-bot-backend/mini_history.py`
- Test: `scam-bot-backend/tests/test_mini_history.py`

**Interfaces:**
- Consumes: `detection_history._history_client()`, `learning.build_case_detail(text, result, received_at)`
- Produces:
  - `class HistoryUnavailable(Exception)`
  - `list_cases(owner: str, limit: int = 50) -> list[dict]` — แต่ละรายการ `{"id": hex32, "title": str, "category": "message", "receivedAt": iso str, "status": str}`
  - `get_case(case_hex: str, owner: str) -> dict | None` — รูปแบบ `MiniCaseData` + `"id": case_hex`
  - `delete_all(owner: str) -> int`

- [ ] **Step 1: เขียนเทสต์ (Supabase จำลองด้วย `Mock` แบบ chain `.table().select().eq()...execute()`)**

```python
def test_list_filters_owner_private_three_statuses_newest_first_limit_50(self): ...
    # assert eq("sender_user_id","U1"), eq("source_type","user"),
    # in_("detection_status",["risk_found","uncertain","no_risk_found"]),
    # order("received_at", desc=True), limit(50)
def test_list_converts_dashed_uuid_to_hex_and_shortens_title(self): ...
    # id "0f8f...-..." -> "0f8f..."(32), title == 60 chars of " ".join(text.split())
def test_get_case_rebuilds_detail_and_falls_back_for_null_reason(self): ...
    # reason None -> detail["reason"] == "ไม่มีเหตุผลเพิ่มเติมจากผลตรวจ"; nextSteps non-empty; id == case_hex
def test_get_case_bad_hex_returns_none_without_query(self): ...  # "xyz", "a"*31
def test_get_case_other_owner_returns_none(self): ...            # data == []
def test_delete_all_targets_owner_private_rows_only(self): ...   # eq sender + eq source_type, no status filter; returns len(data)
def test_supabase_error_becomes_history_unavailable_without_message(self): ...
    # side_effect=RuntimeError("SECRET") -> raises HistoryUnavailable; "SECRET" not in str(exc)
```

- [ ] **Step 2: รัน `python -m unittest discover -s tests -p test_mini_history.py` — Expected: FAIL (ModuleNotFoundError)**
- [ ] **Step 3: เขียน `mini_history.py`** — select คอลัมน์ `id,message_text,detection_status,reason,received_at`; แปลงรหัสด้วย `uuid.UUID(case_hex)` (จับ `ValueError` → `None`, ต้อง `len==32`); ห่อทุก exception จาก client เป็น `HistoryUnavailable() from None`
- [ ] **Step 4: รันเทสต์ — Expected: PASS ทั้ง 7**
- [ ] **Step 5: Commit — ข้าม (ผู้ใช้ยังไม่ให้ commit)**

### Task 2: API 3 endpoint ใน `mini_api.py` + ต่อใน `main.py`

**Files:**
- Modify: `scam-bot-backend/mini_api.py` (`create_mini_router`)
- Modify: `scam-bot-backend/main.py:41-43` (CORS + router)
- Test: `scam-bot-backend/tests/test_mini_api.py`

**Interfaces:**
- Consumes: Task 1 (`list_cases`, `get_case`, `delete_all`, `HistoryUnavailable`)
- Produces: `create_mini_router(history) -> APIRouter` โดย `history` คือ object/โมดูลที่มี 3 ฟังก์ชันของ Task 1
  - `GET /api/mini/history` → `{"cases": [...]}`
  - `GET /api/mini/cases/{case_id}` → รายละเอียด
  - `DELETE /api/mini/history` → `{"deleted": int}`

- [ ] **Step 1: แก้/เพิ่มเทสต์** — เทสต์เดิมที่อิง `LessonStore` (`test_reads_exact_original_case...`, `test_wrong_owner_unknown_expired_and_restart...`, `test_store_copies_detail...`) เปลี่ยนให้ใช้ history จำลอง; เพิ่ม:

```python
async def test_history_lists_only_verified_owner_cases(self): ...      # history.list_cases called with sub, not query param
async def test_history_empty_returns_empty_list(self): ...             # {"cases": []}, 200
async def test_case_other_owner_and_unknown_both_404_same_body(self): ...
async def test_delete_removes_verified_owner_and_is_repeatable(self): ...  # {"deleted": 3} then {"deleted": 0}
async def test_all_endpoints_401_without_token_and_never_touch_history(self): ...
async def test_history_unavailable_is_503_without_raw_error(self): ... # body has "ระบบประวัติขัดข้อง"
async def test_every_response_has_no_store_header(self): ...
async def test_cors_allows_delete_from_configured_origin(self): ...
```

- [ ] **Step 2: รัน `-p test_mini_api.py` — Expected: FAIL**
- [ ] **Step 3: แก้ `create_mini_router(history)`** — เพิ่ม route ตามตาราง แปลง `HistoryUnavailable` → `mini_error(503, ...)`; ใน `main.py` `allow_methods=["GET", "DELETE"]` และ `create_mini_router(mini_history)`
- [ ] **Step 4: รันเทสต์ทั้งหมดของ backend — Expected: PASS**
- [ ] **Step 5: Commit — ข้าม**

### Task 3: บันทึกแถวด้วย `case_id` และข้อความ OCR

**Files:**
- Modify: `scam-bot-backend/detection_history.py` (`save_detection`)
- Modify: `scam-bot-backend/main.py` (`open_result_case`, `process_private_event`, ส่วนรูปภาพใน `_process_text_event`)
- Test: `scam-bot-backend/tests/test_learning.py` (`ResultCardWebhookTests`), `tests/test_detection_history*.py` (ไฟล์เทสต์ของ `save_detection` ที่มีอยู่ — หาได้ด้วย `grep -l save_detection tests/`)

**Interfaces:**
- Consumes: `flex_cards.build_result_card(result, *, source, quote, case_id, allow_postback)`
- Produces:
  - `save_detection(event, result, *, warning_attempted=False, warning_sent=None, case_id: str | None = None, image_text: str | None = None) -> bool`
  - `open_result_case(event, text, result, *, source) -> tuple[str | None, dict | None, bool]` — `case_id` = `uuid4().hex`; ยังเพิ่มลง `lesson_store` เฉพาะเมื่อมีบทเรียน (ใช้รหัสเดียวกัน — ต้องเพิ่มพารามิเตอร์ `case_id` ให้ `LessonStore.add` หรือเก็บ map แยก; เลือก `LessonStore.add(owner, lesson, *, detail=None, case_id=None)`)

- [ ] **Step 1: เขียนเทสต์**

```python
async def test_card_link_and_saved_row_share_case_id(self): ...
    # card footer uri endswith "case=" + kwargs case_id; save_detection.call_args.kwargs["case_id"] == same
async def test_private_image_saves_ocr_text_with_prefix(self): ...
    # save_detection kwargs image_text == OCR text
def test_save_detection_uses_case_id_as_row_id(self): ...          # row["id"] == str(uuid.UUID(hex))
def test_save_detection_image_prefix_and_fallback(self): ...       # "[รูปภาพ] abc" / "[รูปภาพ]"
def test_redelivery_keeps_ignore_duplicates(self): ...             # upsert(on_conflict="line_event_id", ignore_duplicates=True)
async def test_no_case_id_for_group_messages(self): ...            # group save has no case_id kwarg
```

- [ ] **Step 2: รันเทสต์ — Expected: FAIL**
- [ ] **Step 3: แก้ `save_detection` และ `main.py`** — `open_result_case` ไม่ต้องรอ owner ใน `lesson_store` อีกต่อไปเพื่อสร้าง `case_id` (ยังต้องมี `user_id`; ไม่มี → `case_id=None` และการ์ดไม่มีปุ่ม); ส่ง `case_id`/`image_text` ต่อให้ `save_detection`
- [ ] **Step 4: รันเทสต์ทั้งหมดของ backend — Expected: PASS (เทสต์เดิม 230 + ใหม่)**
- [ ] **Step 5: Commit — ข้าม**

### Task 4: `miniApi.ts` ประวัติ ลบ และลองใหม่เมื่อ 404

**Files:**
- Modify: `Scam-bot-frontend/src/mini/services/miniApi.ts`
- Test: `Scam-bot-frontend/tests/mini.test.mjs`

**Interfaces:**
- Produces:
  - `type MiniHistoryItem = { id: string; title: string; category: 'message' | 'link' | 'gift'; receivedAt: string; status: DetectionStatus }`
  - `fetchMiniHistory(token: string, signal: AbortSignal): Promise<MiniHistoryItem[]>` — `GET /api/mini/history`
  - `deleteMiniHistory(token: string): Promise<number>` — `DELETE /api/mini/history`
  - `fetchMiniCase` เดิม + ลองใหม่ 1 ครั้งหลัง 404 (รอ 1500 ms, เคารพ `signal`)

- [ ] **Step 1: เขียนเทสต์**

```js
test('ประวัติส่ง token ใน header และตัดรายการผิดรูปแบบทิ้ง', ...)
  // response cases: [valid, {id:'bad'}] -> length 1; options เหมือน fetchMiniCase (no-store, omit, error, no-referrer)
test('ประวัติว่างคืน array ว่าง', ...)
test('ลบประวัติใช้ DELETE และคืนจำนวน', ...)            // {deleted: 3} -> 3
test('ลบหรือโหลดประวัติล้มเหลวใช้ข้อความผู้ใช้เข้าใจ', ...)  // 503 -> /ลองใหม่/, no raw body
test('เปิดเคสได้ 404 แล้วลองใหม่หนึ่งครั้ง', ...)          // fetch calls: [404, 200] -> detail; mock timers
test('404 สองครั้งจึงแสดงว่าเปิดไม่ได้', ...)              // fetch called exactly 2 times
```

- [ ] **Step 2: รัน `node --test tests/mini.test.mjs` — Expected: FAIL**
- [ ] **Step 3: เขียนโค้ด** — ใช้ฟังก์ชันตรวจรูปแบบแยก `isHistoryItem()` ในไฟล์เดียวกัน
- [ ] **Step 4: รันเทสต์ — Expected: PASS**
- [ ] **Step 5: Commit — ข้าม**

### Task 5: `useMiniSession` + หน้าประวัติจริง

**Files:**
- Modify: `Scam-bot-frontend/src/mini/services/useMiniSession.ts`
- Modify: `Scam-bot-frontend/src/mini/pages/MiniHistory.tsx`
- Modify: `Scam-bot-frontend/src/mini/sampleCases.ts` (type `MiniLayoutContext`)
- Test: `Scam-bot-frontend/tests/mini.test.mjs`

**Interfaces:**
- Consumes: Task 4
- Produces (ผ่าน Outlet context): `history: MiniHistoryItem[]`, `historyLoading: boolean`, `historyError: string`, `reloadHistory(): void`, `deleteHistory(): Promise<number>`, `miniHref(page, caseId?: string)`

- [ ] **Step 1: เขียนเทสต์**

```js
test('หน้าประวัติจริงแสดงหลายเคสและลิงก์ไปเคสของแต่ละรายการ', ...)
  // render MiniHistory with context {live:true, history:[a,b]} -> href /mini/result?case=<a.id> and <b.id>
test('หน้าประวัติจริงไม่มีหมายเหตุ 15 นาที', ...)          // doesNotMatch /15 นาที|เคสที่เปิดครั้งนี้/
test('ไม่มีประวัติแสดงชวนส่งข้อความ', ...)                 // match /ยังไม่มีประวัติการตรวจ/, inspect.png
test('miniHref detail ใช้รหัสที่ส่งมา', ...)
```

- [ ] **Step 2: รันเทสต์ — Expected: FAIL**
- [ ] **Step 3: เขียนโค้ด** — โหลดประวัติหลัง login เฉพาะ `live` (ใช้ token และ `AbortController` แบบเดียวกับ `load()` เดิม); `MiniHistory` ใช้ `session.history` เมื่อ `live`; ข้อความว่าง: "ยังไม่มีประวัติการตรวจ ส่งข้อความที่สงสัยในแชตเพื่อเริ่มตรวจ"
- [ ] **Step 4: รันเทสต์ + `npm run build` — Expected: PASS / build สำเร็จ**
- [ ] **Step 5: Commit — ข้าม**

### Task 6: ปุ่มลบในหน้าบัญชี + ข้อความให้ตรงความจริง

**Files:**
- Modify: `Scam-bot-frontend/src/mini/pages/MiniSettings.tsx`, `src/mini/pages/MiniHelp.tsx`
- Modify docs: `src/mini/README.md`, `src/mini/LIVE_CASES.md`, `scam-bot-backend/MINI_SETUP.md`
- Test: `Scam-bot-frontend/tests/mini.test.mjs`

**Interfaces:**
- Consumes: Task 5 `deleteHistory()`

- [ ] **Step 1: เขียนเทสต์**

```js
test('ลบต้องกดยืนยันก่อนเรียก API', ...)        // click "ลบประวัติทั้งหมด" -> deleteHistory not called; shows "ลบแล้วกู้คืนไม่ได้"
test('กดยกเลิกแล้วไม่ลบ', ...)
test('กดยืนยันซ้ำระหว่างกำลังลบเรียก API ครั้งเดียว', ...)   // button disabled while pending
test('ลบสำเร็จแสดงจำนวน', ...)                    // "ลบประวัติแล้ว 3 รายการ"
test('FAQ และหน้าบัญชีไม่อ้าง 15 นาทีแล้ว', ...)     // /mini/result/help, /settings doesNotMatch /15 นาที/
```

(การคลิกใน node:test: render ด้วย `react-dom/client` + jsdom ถ้ามีในโปรเจกต์ ถ้าไม่มี แยก state การยืนยันเป็นฟังก์ชันล้วน `nextDeleteStep(state, action)` ใน `MiniSettings.tsx` แล้วเทสต์ฟังก์ชันนั้นแทน — ห้ามติดตั้ง dependency ใหม่)

- [ ] **Step 2: รันเทสต์ — Expected: FAIL**
- [ ] **Step 3: เขียนโค้ดและแก้ข้อความ** — หน้าบัญชีส่วนความเป็นส่วนตัว: "เก็บประวัติการตรวจในแชตส่วนตัวไว้ให้ดูย้อนหลัง ลบได้เองในหน้านี้"; FAQ "ทำไมเปิดผลเก่าไม่ได้?": "ต้องใช้บัญชี LINE เดียวกับที่ส่งตรวจ หรือเคสอาจถูกลบไปแล้วจากหน้าบัญชี"
- [ ] **Step 4: รันเทสต์ + build + `npx eslint src/mini` — Expected: PASS**
- [ ] **Step 5: Commit — ข้าม**

### Task 7: ตรวจทั้งระบบและบนมือถือ

- [ ] **Step 1:** backend `python -m unittest discover -s tests` — Expected: OK ทั้งหมด
- [ ] **Step 2:** frontend `node --test tests/mini.test.mjs`, `npm run build`, `npx eslint src/mini` — Expected: ผ่าน
- [ ] **Step 3:** รีสตาร์ตบอตในแท็บ `line bot`
- [ ] **Step 4 (ผู้ใช้):** ส่งข้อความ 2 + รูป 1 → หน้าประวัติเห็น 3 เคส; log มี `GET /api/mini/history 200`
- [ ] **Step 5 (ผู้ใช้):** รีสตาร์ตบอต → เปิดประวัติและรายละเอียดเดิมได้ 200
- [ ] **Step 6 (ผู้ใช้ ยืนยันก่อนเพราะลบข้อมูลจริง):** กดลบ → log `DELETE /api/mini/history 200`, หน้าประวัติว่าง, ลิงก์เดิม 404
