# Thai Scam Detection LINE Bot

A Thai-language LINE bot that combines rules, semantic search, and LLM analysis to flag potentially fraudulent messages. An AI application and backend development project.

**Stack:** Python · FastAPI · Gemini API · Supabase/PostgreSQL · pgvector · LINE Messaging API

## Highlights

- Hybrid detection with message rules, Gemini embeddings, vector search, and contextual LLM analysis.
- Separate handling for private requests and group conversations.
- Webhook signature and payload validation, duplicate-event handling, network timeouts, and error logging.
- Private-chat learning cards explaining warning signs without another AI request.
- Detection history stored for an administrator dashboard.
- Offline automated tests covering routing, validation, duplicate events, timeouts, and learning interactions.

## How it works

```text
LINE message -> FastAPI webhook -> signature / payload / duplicate checks
             -> rules + Gemini embedding -> Supabase vector search
             -> rule decision or LLM analysis -> LINE reply
             -> detection history for the dashboard
```

Group chats skip configured greetings and short messages without configured risk keywords. Short messages with risk keywords (including OTP/password/transfer terms) use contextual LLM analysis after retrieval, even at low scores; keywords alone never force a warning on this path. Longer group messages retain score-based routing, including direct warnings for strong spam matches. Private requests use contextual analysis after retrieval, with separate handling for greetings and empty input. Contextual analysis here means the submitted message, not conversation memory or website inspection.

Similarity thresholds are routing rules, not measured accuracy or probabilities of fraud. A non-warning result does not guarantee safety.

## Run locally

Requirements: Python, a LINE Messaging API channel, Gemini API access, and a Supabase project configured with pgvector, the `scam_dataset` table, and the `match_scam` RPC. Review the [dashboard data contract](supabase/DATA_CONTRACT.md) and [dashboard schema](supabase/dashboard_schema.sql) for history storage. These dashboard tables do not replace the vector-search setup.

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\scam-bot-backend\requirements.txt
```

Copy `scam-bot-backend/.env.example` to `scam-bot-backend/.env` if you do not already have a local configuration. Fill in the variables listed in the example. Configure `SUPABASE_HISTORY_KEY` on the backend as described in the data contract. Never commit credentials or put privileged keys in frontend code.

```powershell
Set-Location .\scam-bot-backend
$env:PYTHONUTF8 = "1"
..\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Expose port 8000 through an HTTPS tunnel and set the LINE webhook to `https://your-public-domain/webhook`. If Cloudflare Tunnel is installed:

```powershell
cloudflared tunnel --url http://localhost:8000
```

Use one worker: event guards and learning-card state are held in process memory.

## Automated tests

From the repository root:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s scam-bot-backend/tests -p "test_*.py" -q
```

The suite uses mocked external services. It checks application behavior, not real-world scam-detection accuracy. A live LINE demo also requires configured API credentials and database access.

Dataset-script tests are separate and require the engine environment (including pandas):

```powershell
.\scam-ai-engine\venv\Scripts\python.exe -B -m unittest discover -s scam-ai-engine/tests -q
```

Manual live checks are in `scam-bot-backend/scripts/`, outside test discovery. `smoke_search.py` calls Gemini/Supabase and uses quota; `smoke_history.py` writes a synthetic history record. Run them only deliberately with the backend Python environment. Importing these scripts does not start work.

## Dataset scripts

- `upload_to_supabase.py`: running it reads `linebot_1000word.csv` next to the script, selects new texts, creates embeddings, and inserts batches of up to 50. `--limit 5` limits a run. Run one uploader at a time. On failure it stops without automatic insert retries; check the database before rerunning. Pending in-memory rows are not saved on interruption.
- `translate_phishing.py`: running it reads `phishing_sampled_1500.csv` next to the script. Successful rows go to `translated_phishing_line_1500.csv`; failed source row numbers (1-based excluding header) and error types go to `translated_phishing_line_1500_failed.csv`. It saves every 50 processed rows and on Ctrl+C. Existing output files block a new run to avoid accidental overwriting; this is not automatic resume.
- Translation keeps source labels (`Phishing Email` / `Safe Email`). Review translated content and map labels to `spam` / `ham` before creating an upload dataset. These scripts are not an automatic end-to-end pipeline.
- Both scripts load their own adjacent `.env` only when run. Translation retains its existing legacy SDK/model; live availability has not been verified.

## Code guide

- `scam-bot-backend/main.py`: webhook entry point and event routing.
- `scam-bot-backend/detector.py`: vector retrieval, decision rules, and LLM response validation.
- `scam-bot-backend/event_guard.py`: duplicate-event protection.
- `scam-bot-backend/learning.py`: temporary, user-bound learning cases.
- `scam-bot-backend/detection_history.py`: history persistence.
- `scam-bot-backend/tests/`: offline tests.
- `scam-ai-engine/`: dataset preparation and embedding upload scripts. Upload scripts write to the database and use external APIs; they are not required to start the webhook.

## Limitations and data handling

- False positives and false negatives are possible; no benchmark accuracy is claimed.
- Text analysis does not inspect the contents of linked websites.
- In-memory event and learning state is lost on restart and is not shared between workers.
- Detection history includes message text and source identifiers. Restrict access according to the data contract and use synthetic data in public demos.
- Application logs keep trace IDs, timings, status, similarity and labels, but no longer print submitted messages, matched dataset text or LLM reasons. This does not redact existing logs or database history.

Implementation notes in Thai: [Webhook stability](scam-bot-backend/STABILITY.md) · [Learning cards](scam-bot-backend/LEARNING.md).
