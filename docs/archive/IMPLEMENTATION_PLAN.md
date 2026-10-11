# Implementation Plan — FactGuard
## WhatsApp AI Fact-Checking System — Ignite 8.0 CivicFix
> **Team:** Appsolutely | **Duration:** 24 hours  
> Every hour is accounted for. Read before writing any code.  
> Adjust phase boundaries if your hackathon is 18 or 20 hours (see §6).

---

## §1 — Timeline Overview

| Phase | Hours | Focus | Definition of Done |
|---|---|---|---|
| **Documentation & Setup** | 0–1 | All docs read, env provisioned, repos created | Every member has their .env working; ngrok tunnel live |
| **Foundation** | 1–3 | FastAPI skeleton, Twilio webhook, Redis connected | Twilio sends a message → FastAPI receives it and replies with acknowledgment |
| **Input Preprocessing** | 3–8 | All 4 extractors (OCR, ASR, PDF, URL, text) | Each extractor converts its input type to plain text |
| **NLP Pipeline** | 5–11 | Language detect → translate → extract claim → filter | Given English or Hindi text, `extract_claim()` returns a single verifiable claim |
| **Evidence Retrieval** | 8–14 | Fact Check API + Bing + Wikipedia | Given a claim, at least 3 evidence snippets with source URLs are returned |
| **AI Verification** | 11–17 | DeBERTa NLI + Sentence-BERT + XGBoost verdict | Given claim + evidence, `aggregate_verdict()` returns a label + confidence score |
| **Explainer + Response** | 15–19 | Gemini explanation + WhatsApp message formatter | Full pipeline: input → verdict → WhatsApp reply with explanation and sources |
| **Admin Dashboard** | 16–20 | Next.js stats page with claim logs | Dashboard loads verdict distribution, claim table, low-confidence queue |
| **Integration & Polish** | 18–22 | End-to-end test, error states, demo caching | All 4 input types produce a correct verdict on production |
| **Demo Prep** | 22–24 | Pre-cache, rehearsal, checklist | Demo runs 3× clean end-to-end from a real WhatsApp number |

> Phases overlap — backend members can start NLP (Phase 4) while the input extractors (Phase 3) are still being completed by Member 1.

---

## §2 — Hour-by-Hour Breakdown

### Hours 0–1: Documentation & Environment Sprint

**All members**
- [ ] Everyone reads their role's document set (see Reading Order in TEAM_BRIEF.md)
- [ ] Git monorepo created: `/backend`, `/frontend`, `/notebooks`, `/scripts`, `/models`
- [ ] `.env.example` committed; everyone copies to `.env` and fills their keys
- [ ] Twilio WhatsApp Sandbox activated — all members send "join `<sandbox-code>`" from their phones
- [ ] Upstash Redis provisioned; connection string tested with `redis.set("test", "ok")`
- [ ] ngrok installed and auth token configured (`ngrok config add-authtoken <token>`)
- [ ] Python virtual environment created: `python -m venv venv && pip install -r requirements.txt`
- [ ] Render project created, GitHub auto-deploy linked to `main` branch
- [ ] Vercel project created for admin frontend

**Deliverable**: `GET /health` returns `{"status": "ok"}` from localhost AND from Render.

---

### Hours 1–3: Foundation — FastAPI Skeleton + Twilio Handshake

**Member 1 (Ingestion)**
- [ ] `main.py` — FastAPI app with lifespan, CORS, middleware stack mounted
- [ ] `routers/webhook.py` — `POST /webhook/twilio` receives Twilio payload
- [ ] Instant acknowledgement: TwiML response `"⏳ Checking this for you..."` returned within 2 seconds
- [ ] Background task queued for full pipeline (use `BackgroundTasks` or Celery stub)
- [ ] `routers/health.py` — `GET /health` returns timestamp + version
- [ ] `middleware/twilio_validator.py` — HMAC signature verification (skip path: `/health`, `/verify`)
- [ ] `middleware/rate_limiter.py` — 10 requests / 10 minutes per phone number (Redis-backed)
- [ ] `lib/redis_client.py` — Upstash Redis singleton, connection tested
- [ ] `lib/config.py` — pydantic-settings reads `.env`

**Member 2 (NLP)**
- [ ] `models/request_models.py` — `WebhookPayload`, `VerifyRequest` Pydantic v2 models
- [ ] `models/response_models.py` — `VerdictData`, `APIResponse`, `EvidenceItem` models
- [ ] `lib/db.py` — SQLAlchemy setup; `ClaimLog` table created via `Base.metadata.create_all()`
- [ ] `schemas/claim_log.py` — SQLAlchemy ORM model

**Checkpoint**: Send a WhatsApp message to Twilio sandbox → see `"⏳ Checking this for you..."` reply in under 3 seconds. Rate limit blocks the 11th message.

---

### Hours 3–8: Input Preprocessing (Member 1 leads, Member 3 assists)

**All four extractors must return `str` — empty string on failure, never an exception.**

#### Text (trivial — do first)
- [ ] `services/input/` init — `detect_input_type(body, media_url, media_content_type) → InputType`
- [ ] Plain text passthrough confirmed: `Body` field from Twilio → raw text string

#### Image / Screenshot (EasyOCR)
- [ ] `services/input/ocr_service.py` — `load_ocr()` loads reader at startup; `['en', 'hi']`
- [ ] `extract_text_from_image(image_bytes) → str` with confidence filter (≥ 0.6)
- [ ] Image preprocessing: resize to max 800px width, convert to grayscale before OCR
- [ ] Media download function: `requests.get(url, auth=(SID, TOKEN), timeout=10)` → bytes
- [ ] Failure fallback: blurry/empty → `""` → send user `"I couldn't read that image clearly..."`

#### Voice Note (Whisper ASR)
- [ ] `services/input/asr_service.py` — `load_whisper()` loads `whisper.load_model("base")` at startup
- [ ] `transcribe_audio(audio_bytes) → str` — writes temp `.ogg`, transcribes, deletes temp file
- [ ] Note: Whisper accepts `.ogg` natively — no pydub conversion needed
- [ ] Detected language from `result["language"]` passed forward (skip LID step)

#### PDF
- [ ] `services/input/pdf_service.py` — `extract_text_from_pdf(pdf_bytes) → str`
- [ ] PyMuPDF text extraction; cap at 10,000 chars
- [ ] Fallback for scanned PDFs: detect empty text → attempt OCR on first page image

#### URL / Article
- [ ] `services/input/url_service.py` — `extract_text_from_url(url) → str`
- [ ] newspaper3k: download + parse + return `title + " " + text`, capped at 10,000 chars
- [ ] Fallback: 403/paywall → return Open Graph meta description

#### Master Preprocessor
- [ ] `preprocess_input(body, media_url, media_content_type) → tuple[str, InputType, str]`
  - Returns: `(extracted_text, input_type, detected_lang_or_empty)`
- [ ] All extractors called through this single function

**Checkpoint**: Test each extractor in isolation using `test_member1.py`. All 5 input types → plain text string.

---

### Hours 5–11: NLP Pipeline (Member 2 leads)

*Start at hour 5 — runs in parallel with late input preprocessing work.*

#### Language Detection
- [ ] `services/nlp/lang_detect.py` — `load_lid()` downloads and loads fastText `lid.176.bin` at startup
- [ ] `detect_language(text) → str` — returns ISO code (`"hi"`, `"mr"`, `"en"`, etc.)
- [ ] Skip if Whisper already detected language (voice path)

#### Translation
- [ ] `services/nlp/translate.py` — `load_translator()` loads IndicTrans2 distilled model at startup
- [ ] `translate_to_english(text, src_lang) → str` — passthrough if `src_lang == "en"`
- [ ] Fallback: if IndicTrans2 fails → `googletrans` library (Google Translate API)
- [ ] Supported langs: `{"hi", "mr", "bn", "pa", "gu", "ta", "te", "kn", "ur"}`

#### Claim Extraction
- [ ] `services/nlp/claim_extract.py` — `load_extractor()` loads spaCy `en_core_web_sm` + KeyBERT
- [ ] `extract_claim(text) → str` — split into sentences → score by keyword overlap → return best sentence
- [ ] Minimum sentence length filter: skip sentences < 20 chars

#### Claim Filter (ClaimBuster)
- [ ] `services/nlp/claim_filter.py` — `is_check_worthy(claim, api_key) → tuple[bool, float]`
- [ ] CFS threshold: < 0.30 → return `UNVERIFIABLE` immediately, skip evidence retrieval
- [ ] Fallback if ClaimBuster API unavailable: always return `(True, 0.5)` — continue pipeline

**Checkpoint**: Given Hindi text `"नई सरकारी योजना – गैस सिलेंडर अब मुफ्त"` → English claim `"government scheme providing free gas cylinders"` with `is_check_worthy = True`.

---

### Hours 8–14: Evidence Retrieval (Member 3 leads)

*Start at hour 8 — runs in parallel with late NLP work.*

#### Google Fact Check API
- [ ] `services/retrieval/fact_check_api.py` — `search_fact_checks(claim, api_key) → list[EvidenceItem]`
- [ ] Query: `claim` text; return top 3 results with `source_name`, `source_url`, `rating`, `snippet`
- [ ] Fallback: API unavailable → return `[]` (not a crash — evidence list is just shorter)

#### Bing Search API
- [ ] `services/retrieval/web_search.py` — `search_web(claim, api_key) → list[EvidenceItem]`
- [ ] Query: `claim + " fact check"`, `mkt="en-IN"`, `count=5`
- [ ] Return top 3: `title`, `url`, `snippet`

#### Wikipedia
- [ ] `services/retrieval/wikipedia.py` — `search_wikipedia(claim) → list[EvidenceItem]`
- [ ] Use `wikipedia-api` library; return first 3 relevant paragraphs as snippets
- [ ] Key-term extraction: pull named entities from claim → use as Wikipedia search query

#### Evidence Combiner
- [ ] Merge results from all 3 sources; deduplicate by URL
- [ ] Rank by: Fact Check results first, then Bing, then Wikipedia
- [ ] Return top 5 unique evidence items

**Checkpoint**: Given claim `"5G towers cause cancer"` → returns at least 3 evidence items with source URLs and snippets.

---

### Hours 11–17: AI Verification (Member 3 leads, Member 2 assists)

*Start at hour 11 — NLP pipeline should be mostly done.*

#### DeBERTa NLI
- [ ] `services/verification/nli_service.py` — `load_deberta()` loads `cross-encoder/nli-deberta-v3-small`
- [ ] `get_nli_scores(claim, evidence_snippet) → dict[str, float]`
  - Returns: `{"entailment": float, "neutral": float, "contradiction": float}`
- [ ] Run on each evidence item; collect list of score dicts

#### Sentence-BERT Similarity
- [ ] `services/verification/similarity_service.py` — `load_sbert()` loads multilingual MiniLM
- [ ] `get_similarity(claim, evidence) → float` — cosine similarity of sentence embeddings
- [ ] Run on each evidence item; collect list of float scores

#### XGBoost Verdict Aggregator
- [ ] `services/verification/verdict_service.py` — `load_verdict_model()` loads `models/verdict_xgb.pkl`
- [ ] `aggregate_verdict(nli_scores_list, similarity_scores, fact_check_found) → tuple[str, float]`
- [ ] Feature vector: `[avg_entailment, avg_contradiction, avg_neutral, avg_similarity, fact_check_found, 0.0]`
- [ ] Output: `(label, confidence)` where label ∈ `{"VERIFIED", "FALSE", "OUTDATED", "PARTIAL", "UNVERIFIABLE"}`

#### Rule-Based Fallback (if XGBoost pkl missing)
- [ ] `rule_based_verdict(avg_entailment, avg_contradiction, fact_check_found) → tuple[str, float]`
- [ ] Implement thresholds from AI_ML_GUIDANCE.md §6 — commit this before XGBoost model is ready

#### XGBoost Training (Member 3 offline task)
- [ ] `notebooks/train_verdict_model.ipynb` — synthetic training data + model training
- [ ] Commit trained `models/verdict_xgb.pkl` to repo by hour 16

**Checkpoint**: Given claim `"Drinking hot water kills coronavirus"` + 3 evidence snippets → verdict `FALSE`, confidence ≥ 0.75.

---

### Hours 15–19: Explainer + Response Formatter (Member 2 leads)

#### Gemini Flash Explainer
- [ ] `services/explainer/explain_service.py` — `generate_explanation(claim, verdict, evidence_summary, language) → str`
- [ ] Prompt: 2-sentence, plain language, in detected user language
- [ ] Redis cache for explanations: key `"explain:{claim_hash}"`, TTL 86400
- [ ] RPM guard: Redis counter `"gemini:rpm:{minute_bucket}"` — if > 10, use template fallback
- [ ] Template fallback for all 5 verdicts (see AI_ML_GUIDANCE.md §7)

#### WhatsApp Response Formatter
- [ ] `services/twilio_service.py` — `format_whatsapp_response(verdict_response) → str`
- [ ] Format: verdict emoji → Hindi label → claim → explanation → sources (max 2)
- [ ] Cache hit badge: `"⚡ Instant result (cached)"` appended when `cache_hit = True`
- [ ] Twilio send: `client.messages.create(body=formatted_str, from_=TWILIO_NUMBER, to=user_phone)`

#### Full Pipeline Orchestrator
- [ ] `pipelines/verify_pipeline.py` — `run_pipeline(text, input_type, detected_lang) → VerdictResponse`
- [ ] Step 1: Cache check — return immediately on hit
- [ ] Step 2: NLP (detect lang → translate → extract claim → filter)
- [ ] Step 3: Evidence retrieval (parallel calls to all 3 sources)
- [ ] Step 4: AI verification (NLI + SBERT → XGBoost)
- [ ] Step 5: Explanation (Gemini → cached)
- [ ] Step 6: Cache full result (Redis SET, TTL 86400)
- [ ] Step 7: Return `VerdictResponse`
- [ ] `routers/verify.py` — `POST /verify` — internal test endpoint (API key auth, no Twilio needed)

**Checkpoint**: `POST /verify {"text": "5G towers cause cancer", "type": "text"}` → full JSON verdict with explanation and source URLs, in under 15 seconds.

---

### Hours 16–20: Admin Dashboard (Member 4 leads)

*Frontend work — runs in parallel with pipeline polish.*

#### Next.js Setup
- [ ] `npx create-next-app@latest frontend --typescript --tailwind`
- [ ] Axios API client configured to point at backend URL
- [ ] JWT auth: login with admin key → store token in Zustand memory

#### Pages
- [ ] `/` → redirects to `/dashboard`
- [ ] `/login` → admin API key input → stores token
- [ ] `/dashboard` → stats + claim table (main page)

#### Dashboard Components
- [ ] `StatsRow` — 4 cards: Total claims today / Verdict distribution / Avg processing time / Low-confidence count
- [ ] `VerdictPieChart` — recharts PieChart with 5 verdict colors
- [ ] `ClaimsTable` — paginated table: claim text, verdict badge, confidence bar, input type, timestamp
- [ ] `LowConfidenceQueue` — filtered view: confidence < 0.65, with override button

#### Backend Admin Endpoints (Member 1 adds)
- [ ] `GET /admin/stats` — total today, verdict distribution, avg time, low-confidence count
- [ ] `GET /admin/claims` — paginated; filters: verdict, date, input_type
- [ ] `PATCH /admin/claims/{id}/override` — admin sets manual verdict with reason

**Checkpoint**: Admin dashboard loads in browser with real data from the claim log.

---

### Hours 18–22: Integration & Polish

**All members together**

- [ ] End-to-end test — all 4 input types from a real WhatsApp number on production
  - Text: `"सरकार दे रही है मुफ्त राशन..."` → `FALSE` verdict in Hindi
  - Screenshot: image of a fake scheme → `FALSE` verdict
  - Voice note: Hindi voice claim → transcript + verdict
  - URL: news article URL → claim extracted + verdict
- [ ] Cache verification: send same text twice → second response in < 2 seconds with `⚡`
- [ ] Rate limit verification: 11th message → `"⏳ You've sent too many messages..."`
- [ ] All error states handled:
  - Blurry image → friendly message, not crash
  - Whisper fails → friendly message, not crash
  - Gemini quota → template fallback, not crash
  - Fact Check API down → pipeline continues with Bing + Wikipedia only
- [ ] `middleware/error_handler.py` — global exception → JSON error, no stack trace exposed
- [ ] No `console.log` / `print` of phone numbers or tokens in production code
- [ ] `scripts/precache_demo.py` — run against production to cache all 4 demo claims
- [ ] UptimeRobot set to ping `GET /health` every 10 minutes

---

### Hours 22–24: Demo Prep

- [ ] Run `scripts/precache_demo.py` on production
- [ ] Full demo script rehearsed 3× end-to-end from a real WhatsApp number
- [ ] All team members know their section
- [ ] Backup: Postman collection ready if Twilio webhook fails during demo
- [ ] Admin dashboard open in browser tab: `https://admin.factguard.vercel.app`
- [ ] Backend warmed up: ping `/health` 5 minutes before judges arrive
- [ ] Twilio sandbox still joined: test join message from all demo phones
- [ ] README.md updated: problem, architecture diagram, setup, team

---

## §3 — Member Ownership Map

| Member | Role | Primary Phases | Files Owned |
|---|---|---|---|
| **Member 1** (Tejas) | Backend Lead / Ingestion | Phase 2, 3 | `main.py`, `routers/webhook.py`, `services/input/*`, `middleware/*`, `lib/*` |
| **Member 2** (NLP) | NLP Lead | Phase 4, 6 | `services/nlp/*`, `services/explainer/*`, `pipelines/verify_pipeline.py`, `models/*` |
| **Member 3** (ML/Evidence) | ML + Retrieval Lead | Phase 5, 6 | `services/retrieval/*`, `services/verification/*`, `notebooks/train_verdict_model.ipynb` |
| **Member 4** (Frontend) | Dashboard Lead | Phase 7 | `frontend/*`, admin UI components |

**Shared responsibility**:
- Integration testing (Hours 18–22): all members
- Demo prep (Hours 22–24): all members
- Error handling: each member owns error states for their module

---

## §4 — Parallel Work Streams

```
Hour →  0    2    4    6    8    10   12   14   16   18   20   22   24
        │    │    │    │    │    │    │    │    │    │    │    │    │
M1:     ├─Docs─┤├─Foundation─┤├──────Preprocessing──────┤├──Admin Routes─┤
M2:     ├─Docs─┤├─Models─┤├────────NLP Pipeline─────┤├──Explainer────┤
M3:     ├─Docs─┤├─Models─┤       ├────Evidence────┤├──Verification──┤
M4:     ├─Docs─┤              ├───────────Dashboard──────────┤
All:                                              ├──Integration──┤├Demo─┤
```

> **Integration point (Hour 18)**: All modules must expose their function signatures by Hour 10, even if implementation is partial, so parallel work doesn't block.

---

## §5 — Scope Freeze Protocol

At **Hour 18**, scope is frozen.

| After Hour 18 | Allowed | Not Allowed |
|---|---|---|
| Bug fixes | ✅ | — |
| Error state improvements | ✅ | — |
| Demo caching | ✅ | — |
| New features | — | ❌ |
| New API endpoints | — | ❌ |
| Schema changes | — | ❌ |
| New ML models | — | ❌ |

Anything not built → PRD §8 (Future Roadmap). Mention it in demo as "next phase".

---

## §6 — Adjusted Timelines

### 18-Hour Hack
| Phase | Hours |
|---|---|
| Docs + Setup | 0–0.5 |
| Foundation | 0.5–2 |
| Preprocessing | 2–6 |
| NLP Pipeline | 4–8 |
| Evidence Retrieval | 6–10 |
| AI Verification | 8–13 |
| Explainer + Response | 11–15 |
| Admin Dashboard | 12–16 |
| Integration + Polish | 15–17 |
| Demo Prep | 17–18 |

> For 18-hour hacks: drop the Admin Dashboard to "show data in Postman" and use the saved time for integration. Reinstate frontend if you finish early.

### 20-Hour Hack
Add 2 hours to integration phase (Hours 18–20 → 18–22 equivalent). All other phases same as 24-hour plan.

---

## §7 — Critical Numbers — Memorize These

| Value | What It Is |
|---|---|
| `10 / 10 min` | Rate limit per WhatsApp number |
| `86400` | Redis cache TTL in seconds (24 hours) |
| `0.30` | ClaimBuster CFS threshold — below this → UNVERIFIABLE immediately |
| `0.60` | DeBERTa entailment/contradiction threshold for verdict decisions |
| `0.65` | Confidence threshold for low-confidence queue in admin dashboard |
| `10` | Gemini RPM limit (free tier) — above this → template fallback |
| `10,000` | Max character limit for PDF/URL extracted text |
| `2 MB` | Max file size accepted (reject larger with friendly message) |
| `gemini-2.0-flash` | Exact model string for Gemini |
| `cross-encoder/nli-deberta-v3-small` | DeBERTa model name |
| `paraphrase-multilingual-MiniLM-L12-v2` | Sentence-BERT model name |
| `ai4bharat/indictrans2-indic-en-dist-200M` | IndicTrans2 model name |
| `base` | Whisper model size for demo |
| `['en', 'hi']` | EasyOCR language list |

---

## §8 — Definition of Done

A module is complete when ALL of these are true:

- [ ] Function returns the correct type (typed return annotations pass mypy)
- [ ] try/except on every external call — never crashes on bad input
- [ ] Fallback path returns a safe default, not an exception
- [ ] Tested with at least one real input of the expected type
- [ ] Redis cache check comes before any model inference (for pipeline steps)
- [ ] No phone numbers or tokens printed / logged in plaintext
- [ ] Committed to `main` and deployed to Render

---

## §9 — Pre-Demo Checklist (1 Hour Before Judging)

Run every item. Every ❌ must be fixed before entering the judging room.

### Production Checks
- [ ] `GET https://your-backend.onrender.com/health` → `200 OK`
- [ ] Admin dashboard loads: `https://admin.factguard.vercel.app`
- [ ] Admin login works with admin credentials
- [ ] Twilio sandbox still active — send "join `<code>`" test from demo phone
- [ ] Pre-cache script ran on production: all 4 demo claims in Redis

### Demo Flow (run all 4 — from a real phone)
- [ ] **Text**: Send `"नई सरकारी योजना – गैस सिलेंडर अब मुफ्त"` → `❌ गलत` verdict in Hindi within 15s
- [ ] **Text (cache)**: Send same message again → instant `⚡` reply within 2 seconds
- [ ] **Screenshot**: Send the demo screenshot → OCR extracted + verdict returned
- [ ] **Voice**: Send pre-recorded Hindi voice note → transcript + verdict returned
- [ ] **URL**: Send `https://[demo-article-url]` → extracted claim + verdict returned

### Security Checks
- [ ] `.env` NOT in git repo — `git log --oneline -- .env` returns nothing
- [ ] All env vars set in Render dashboard
- [ ] Twilio HMAC validation ON for production (skip paths: `/health`, `/verify`)
- [ ] No `print(phone_number)` anywhere in production code

### Device Checks
- [ ] Laptop charged / plugged in
- [ ] Mobile hotspot ready (backup if venue WiFi fails)
- [ ] Demo phone with Twilio sandbox joined
- [ ] Postman collection open as fallback if WhatsApp demo fails
- [ ] Admin dashboard tab open and logged in
- [ ] All team members know their section of the demo script

---

## §10 — Demo Script (3 Minutes)

```
00:00 – 00:30  Problem framing
               "487 million Indians use WhatsApp. Forwarded health tips, fake
               government schemes, fabricated news spread faster than corrections.
               Manual fact-checking needs 5+ steps and requires English literacy.
               We built FactGuard — fact-check any forwarded message from inside
               WhatsApp, in your own language, in under 15 seconds."

00:30 – 01:30  Core demo — text + cache
               1. Send the Hindi fake gas scheme message from phone → show reply
               2. Send same message again → ⚡ instant cached reply
               Talk: "The same viral forward is seen by thousands. After the first
               check, every subsequent user gets the answer in under 2 seconds."

01:30 – 02:15  Multimodal demo
               Send the screenshot → show OCR extraction + verdict
               OR Send voice note → show transcript + verdict
               Talk: "Users don't need to type anything. They forward what they
               received — screenshot, voice note, PDF, or link — and get a sourced
               verdict back."

02:15 – 02:45  Admin dashboard
               Show verdict distribution, claim log, low-confidence queue
               Talk: "NGOs and moderators can audit every claim the bot checked,
               manually override uncertain verdicts, and export flagged claims for
               journalist review."

02:45 – 03:00  Architecture + roadmap
               "7-layer AI pipeline: OCR/ASR/PDF/URL → NLP → Evidence retrieval
               from Fact Check API + Bing → DeBERTa NLI verification → XGBoost
               verdict → Gemini explanation in the user's language.
               Next: real-time WhatsApp group monitoring and video deepfake detection."
```

**Demo Red Lines — Never let these happen:**
- ❌ Twilio sandbox expired → Join sandbox 1 hour before demo. Have Postman backup.
- ❌ AI too slow → Pre-cache all demo claims. Cold queries should not appear in demo.
- ❌ Pipeline crashes on bad input → Every extractor returns `""` on failure, not an exception.
- ❌ Gemini quota hit → Template fallback returns explanation without Gemini.
- ❌ Can't explain the architecture → Every member reads BACKEND_ARCHITECTURE.md §8 before demo.
