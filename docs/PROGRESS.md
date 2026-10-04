# SatyaSetu Implementation Progress Log

## Summary of Waves

- [x] **Wave 0 (Phase 0): Safety Net, Environment, Git Hygiene, Characterisation Tests**
  - [x] W0-A: Aligned workspace root with git repo root (moved from nested folder)
  - [x] W0-B: Created and switched to branch `refactor/feature-layout`
  - [x] W0-C: Updated `.gitignore` to ignore secrets, caches, `claims.db`, and `lid.176.bin`
  - [x] W0-D: Updated `requirements.txt` (removed duplicate `httpx`, added missing dependencies), created `requirements-dev.txt`
  - [x] W0-E: Updated `.env.example` with modern settings (removed retired Bing, added Brave/Tavily, public URL, Gemini, timeouts)
  - [x] W0-F: Created characterisation test suite `tests/unit/test_characterisation.py` (8/8 tests passing)
  - [x] W0-G: Initialized documentation suite (`PROGRESS.md`, `DECISIONS.md`, `BUILD_STATUS.md`)
  - [x] W0-H: Created `scripts/gitingest_safe.sh` for safe repository packaging

- [x] **Wave 1 (Phase 1a): Contracts and Core Layer**
  - [x] W1-A: Define Pydantic v2 contract models (`app/contracts/models.py`)
  - [x] W1-B: Implement core settings (`app/core/config.py`)
  - [x] W1-C: Implement logging with RedactionFilter and request-id tracking (`app/core/logging.py`)
  - [x] W1-D: Implement redaction utility stripping phone numbers, emails, and digit runs (`app/core/redaction.py`)
  - [x] W1-E: Implement StageTimer context manager for latency tracking (`app/core/timing.py`)
  - [x] W1-F: Implement system enums and constants (`app/core/constants.py`)
  - [x] Unit test suite: `tests/unit/test_contracts.py` (12/12 passing; total 20/20 unit tests passing)

- [x] **Wave 2 (Phase 1b): Security Layer with SSRF Guard**
  - [x] W2-A: Implement `is_public_http_url`, `safe_get`, and `twilio_media_auth` (`app/core/security.py`)
  - [x] W2-B: Implement abuse test suite `tests/abuse/test_ssrf.py` (29/29 passing)
  - [x] Verified rejection of private IPs, loopback, cloud metadata (169.254.169.254), DNS rebinding, and redirect manipulation.

- [x] **Wave 3 (Phase 1c): Ingestion Feature Migration**
  - [x] W3-A: Migrated EasyOCR extractor with safe_get and configurable languages (`app/features/ingestion/ocr.py`)
  - [x] W3-B: Migrated Whisper ASR extractor with ffmpeg check and safe_get (`app/features/ingestion/asr.py`)
  - [x] W3-C: Migrated PyMuPDF PDF extractor with OCR fallback (`app/features/ingestion/pdf.py`)
  - [x] W3-D: Migrated newspaper3k URL scraper with SSRF protection and OG fallback (`app/features/ingestion/url.py`)
  - [x] W3-E: Extracted input type detector (`app/features/ingestion/detect.py`)
  - [x] W3-F: Extracted text sanitizer with Defect D6 fix (`app/features/ingestion/sanitize.py`)
  - [x] W3-G: Created ingestion orchestrator returning IngestedMessage (`app/features/ingestion/service.py`)
  - [x] W3-H: Created unit test suite `tests/unit/test_ingestion_detect.py` (7/7 passing; total 56/56 tests passing across repo)
- [x] **Wave 4 (Phase 1d + Phase 4): NLP Feature Split and Demo Hacks Removed**
  - [x] W4-A: Created language and script detector with Hinglish heuristic (`app/features/nlp/language.py`)
  - [x] W4-B: Migrated translation with Defect D7 demo hack removed and Hinglish support (`app/features/nlp/translation.py`)
  - [x] W4-C: Migrated KeyBERT keyphrase extraction (`app/features/nlp/keywords.py`)
  - [x] W4-D: Implemented sentence splitting, forward pressure detection, and claim extraction (`app/features/nlp/claims.py`)
  - [x] W4-E: Implemented check-worthiness scorer (`app/features/nlp/worthiness.py`)
  - [x] W4-F: Created test fixtures (`tests/fixtures/samples.yaml`, `tests/fixtures/worthiness.yaml`)
  - [x] W4-G: Created unit test suites `tests/unit/test_language.py`, `tests/unit/test_claims.py`, `tests/unit/test_worthiness.py` (13/13 passing; total 69/69 tests passing across repo)
- [x] **Wave 5: Evidence Retrieval Orchestrator (Google Fact Check, Web, Wiki)**
  - [x] W5-A: Google Fact Check Tools API client with rating normalisation (`app/features/retrieval/factcheck_google.py`)
  - [x] W5-B: Wikipedia API client (`app/features/retrieval/wikipedia.py`)
  - [x] W5-C: Web search fallback via Brave / Tavily (`app/features/retrieval/search_web.py`)
  - [x] W5-D: Claim rating normalisation (`app/features/retrieval/ratings.py`)
  - [x] W5-E: Multi-source evidence orchestrator with in-memory caching (`app/features/retrieval/orchestrator.py`)
  - [x] W5-F: Unit test suite for retrieval (`tests/unit/test_retrieval.py`) (13/13 passing)

- [x] **Wave 6: Verification and Stance Scoring Engine**
  - [x] W6-A: Stance detection with RoBERTa-large-MNLI and lexical fallback (`app/features/verification/stance.py`)
  - [x] W6-B: Overall verdict derivation and claim verification service (`app/features/verification/service.py`)
  - [x] W6-C: Unit test suite for verification (`tests/unit/test_verification.py`) (12/12 passing)

- [x] **Wave 7: Explanation Generator and WhatsApp Message Formatter**
  - [x] W7-A: Structured explanation generator with Gemini API and template fallback (`app/features/explanation/generator.py`)
  - [x] W7-B: User-facing WhatsApp message formatter with back-translation (`app/features/explanation/formatter.py`)
  - [x] W7-C: TwiML reply generator (`app/core/twiml.py`)
  - [x] W7-D: Unit test suite for explanation & formatting (`tests/unit/test_explanation.py`) (12/12 passing)

- [x] **Wave 8: Thin-Path Integration and End-to-End Orchestration**
  - [x] W8-A: Pipeline orchestrator `run_pipeline` connecting Ingestion -> NLP -> Retrieval -> Verification -> Explanation (`app/pipeline.py`)
  - [x] W8-B: FastAPI webhook router with in-memory sliding window rate limiter (`app/routers/webhook.py`)
  - [x] W8-C: FastAPI health check router with uptime & memory diagnostics (`app/routers/health.py`)
  - [x] W8-D: Clean application entry point (`app_main.py`)
  - [x] W8-E: Unit test suite for pipeline (`tests/unit/test_pipeline.py`) (9/9 passing)

- [x] **Wave 9: Evaluation Suite and Security Verification**
  - [x] W9-A: End-to-end integration smoke tests (`tests/integration/test_smoke.py`) (6/6 passing)
  - [x] W9-B: Rate-limiting abuse test suite (`tests/abuse/test_rate_limit.py`) (6/6 passing)
  - [x] W9-C: IP-based sliding window rate limiter middleware with graceful HTTP 429s (`app_main.py`)
  - [x] W9-D: Strict input validation and sanitization review (HTML/control characters stripping)
  - [x] W9-E: OWASP security verification (PII redaction, SSRF safe_get, zero hardcoded keys)

- [x] **Wave 10: Presentation Preparation and Demo Hardening**
  - [x] W10-A: Cloud deployment Procfile for Render / Railway / Heroku (`Procfile`)
  - [x] W10-B: Multi-stage, non-root Dockerfile with health checks (`Dockerfile`)
  - [x] W10-C: Interactive CLI demo tool with latency and stage breakdowns (`scripts/demo_cli.py`)
  - [x] W10-D: Updated documentation (`docs/PROGRESS.md`, `docs/BUILD_STATUS.md`)


