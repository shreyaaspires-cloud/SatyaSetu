# Technical Requirements Document (TRD)
## WhatsApp AI Fact-Checking System — FactGuard
> Security, performance, architecture decisions, rate limiting, and reliability.  
> Read before writing any backend code.

---

## §1 — Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          FACTGUARD ARCHITECTURE                          │
│                                                                          │
│   WhatsApp User                                                          │
│        │  (forwards message)                                             │
│        ▼                                                                 │
│   ┌─────────────┐      webhook POST       ┌──────────────────────────┐  │
│   │   Twilio    │ ─────────────────────── │   FastAPI Backend         │  │
│   │  WhatsApp   │ ◀─────────────────────  │   (Python 3.11)           │  │
│   └─────────────┘      TwiML response     │                          │  │
│                                           │  ┌──────────────────────┐ │  │
│                                           │  │  Preprocessing Layer  │ │  │
│                                           │  │  EasyOCR / Whisper    │ │  │
│                                           │  │  PyMuPDF / newspaper3k│ │  │
│                                           │  └──────────┬───────────┘ │  │
│                                           │             │              │  │
│                                           │  ┌──────────▼───────────┐ │  │
│                                           │  │   NLP Pipeline        │ │  │
│                                           │  │  fastText LID         │ │  │
│                                           │  │  IndicTrans2          │ │  │
│                                           │  │  spaCy + KeyBERT      │ │  │
│                                           │  │  ClaimBuster          │ │  │
│                                           │  └──────────┬───────────┘ │  │
│                                           │             │              │  │
│                                           │  ┌──────────▼───────────┐ │  │
│  ┌────────────┐   ┌─────────────────┐     │  │  Evidence Retrieval   │ │  │
│  │  Redis     │◀──│  Cache Layer    │     │  │  Google FC API        │ │  │
│  │  (Upstash) │──▶│  SHA-256 keyed  │     │  │  Bing Search          │ │  │
│  └────────────┘   └─────────────────┘     │  │  Wikipedia API        │ │  │
│                                           │  └──────────┬───────────┘ │  │
│  ┌────────────┐                           │             │              │  │
│  │ PostgreSQL │◀─────────────────────────│  ┌──────────▼───────────┐ │  │
│  │ (Supabase) │                          │  │  AI Verification      │ │  │
│  └────────────┘                          │  │  DeBERTa NLI          │ │  │
│                                           │  │  Sentence-BERT        │ │  │
│  ┌────────────┐                           │  │  XGBoost Aggregator   │ │  │
│  │  Cloudinary│◀─────────────────────────│  └──────────┬───────────┘ │  │
│  │(media store│                          │             │              │  │
│  └────────────┘                          │  ┌──────────▼───────────┐ │  │
│                                           │  │  Explainer LLM        │ │  │
│                                           │  │  Gemini 2.0 Flash     │ │  │
│                                           │  └──────────────────────┘ │  │
│                                           └──────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## §2 — Technology Stack

| Layer                    | Technology                        | Version       | Notes |
|--------------------------|-----------------------------------|---------------|-------|
| **API Framework**        | FastAPI                           | 0.111.x       | Async-first; ideal for ML I/O-bound operations |
| **Language**             | Python                            | 3.11.x        | Type hints; asyncio support |
| **Task Queue**           | Celery + Redis                    | 5.4.x         | Background AI processing; avoids Twilio 5s timeout |
| **OCR**                  | EasyOCR                           | 1.7.x         | Hindi + English; GPU optional |
| **ASR (Voice)**          | OpenAI Whisper                    | `whisper-tiny` demo / `whisper-medium` prod | HuggingFace Transformers or `openai-whisper` |
| **PDF Extraction**       | PyMuPDF (fitz)                    | 1.24.x        | Fast; no Java dependency |
| **Web Scraping**         | newspaper3k                       | 0.2.8         | Article extraction from URLs |
| **Language Detection**   | fastText LID                      | 0.9.2         | lid.176.ftz model; < 1ms per detection |
| **Translation**          | IndicTrans2 (AI4Bharat)           | HuggingFace   | Hindi/Marathi → English; fallback: Google Translate API |
| **Claim Extraction**     | spaCy + KeyBERT                   | 3.7.x / 0.3.x | NER + key phrase extraction |
| **Claim Filtering**      | ClaimBuster API                   | REST API      | Check-Worthiness Filter — drop non-factual sentences |
| **NLI Verification**     | DeBERTa-v3-large-mnli             | HuggingFace   | Entailment / contradiction scoring |
| **Semantic Similarity**  | Sentence-BERT (`all-MiniLM-L6`)   | HuggingFace   | Cosine similarity: claim ↔ evidence |
| **Verdict Aggregation**  | XGBoost                           | 2.0.x         | Combines NLI + similarity + source scores |
| **Explainer LLM**        | Gemini 2.0 Flash                  | `@google/generativeai` | 2-line plain-language explanation |
| **Evidence: Fact-Check** | Google Fact Check Tools API       | v1            | Journalist-verified existing checks |
| **Evidence: Web**        | Bing Web Search API               | v7            | Live web evidence retrieval |
| **Evidence: Knowledge**  | Wikipedia API                     | REST          | Background knowledge; always available |
| **Database**             | PostgreSQL via Supabase           | 15.x          | Claims, verdicts, user interactions |
| **ORM**                  | SQLAlchemy + Alembic              | 2.0.x / 1.13.x | Async ORM; migrations |
| **Cache**                | Redis via Upstash                 | SDK 1.x       | Claim cache; Celery broker |
| **Messaging Gateway**    | Twilio WhatsApp API               | twilio 9.x    | Webhook ingestion; TwiML response |
| **Media Storage**        | Cloudinary                        | cloudinary 1.x| Store voice notes, screenshots temporarily |
| **Deployment — Backend** | Render                            | —             | Free tier; set UptimeRobot ping |
| **Deployment — DB**      | Supabase                          | —             | ⚠️ Pauses after 7 days — set UptimeRobot |
| **Admin Frontend**       | Next.js 15 on Vercel              | 15.x          | Admin dashboard only |
| **Input Validation**     | Pydantic v2                       | 2.7.x         | Validates all incoming webhook payloads |
| **Testing**              | pytest + httpx                    | 8.x / 0.27.x  | Async endpoint testing |

---

## §3 — Security Requirements

### §3.1 — Twilio Webhook Security

```python
# Every webhook request MUST be validated with Twilio HMAC signature
# middleware/twilio_auth.py

from twilio.request_validator import RequestValidator
from fastapi import Request, HTTPException

async def validate_twilio_signature(request: Request):
    validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
    form_data = await request.form()
    url = str(request.url)
    signature = request.headers.get("X-Twilio-Signature", "")

    if not validator.validate(url, dict(form_data), signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")
```

### §3.2 — Auth & Session

| Requirement              | Specification                         | Notes |
|--------------------------|---------------------------------------|-------|
| Admin auth               | JWT, HS256, access = 15m, refresh = 7d | Same pattern as PART 1 |
| Password hashing         | bcrypt, saltRounds = 10               | Admin login only |
| WhatsApp user identity   | Phone number hashed (SHA-256) in DB   | Never store raw phone number |
| Twilio webhook auth      | HMAC-SHA1 signature on every request  | `X-Twilio-Signature` header |
| API key storage          | `.env` only; never in code or logs    | |

### §3.3 — Security Essentials

| Threat                    | Mitigation |
|---------------------------|------------|
| Webhook replay attacks    | Twilio signature validation; idempotency key per message SID |
| Phone number harvesting   | Hash phone numbers with SHA-256 before storage |
| Prompt injection via input| Input sanitized before feeding to Gemini; max 10,000 chars |
| API key exposure          | `.env` file; Render/Vercel environment variables |
| Rate abuse per number     | 10 checks / 10 minutes per hashed phone number |
| Log exposure              | Never log raw phone numbers, message bodies, or API keys |
| SQL injection             | SQLAlchemy ORM; parameterized queries only |

### §3.4 — Input Sanitization

```python
def sanitize_input(text: str, max_chars: int = 10_000) -> str:
    """Strip control characters, limit length, prevent prompt injection attempts."""
    # Remove null bytes and control chars
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")
    # Truncate
    text = text[:max_chars]
    # Remove prompt injection markers
    for marker in ["IGNORE PREVIOUS", "### SYSTEM", "<|im_start|>", "[INST]"]:
        text = text.replace(marker, "")
    return text.strip()
```

---

## §4 — Performance Requirements

### §4.1 — Response Time Targets

| Stage                                      | Target   | Max     |
|--------------------------------------------|----------|---------|
| Twilio webhook acknowledgment (async hand-off) | < 3s  | < 5s    |
| Text input → verdict (cache hit)           | < 2s     | < 3s    |
| Text input → verdict (cache miss)          | < 12s    | < 15s   |
| Screenshot OCR → verdict                   | < 20s    | < 30s   |
| Voice note transcription → verdict         | < 25s    | < 40s   |
| PDF extraction → verdict                   | < 20s    | < 30s   |
| URL scrape → verdict                       | < 15s    | < 25s   |
| Gemini explanation (cache hit)             | < 50ms   | < 150ms |
| Gemini explanation (cache miss)            | < 3s     | < 5s    |

### §4.2 — Rate Limiting

| Endpoint / Scope                          | Limit         | Window |
|-------------------------------------------|---------------|--------|
| Per phone number (hashed)                 | 10 requests   | 10 minutes |
| Gemini API calls                          | 10 calls      | 1 minute |
| ClaimBuster API calls                     | 10 calls      | 1 minute |
| Bing Search API calls                     | 50 calls      | 1 day (free tier) |
| Google Fact Check API calls               | 100 calls     | 1 day |
| Admin API endpoints                       | 60 requests   | 1 minute |

---

## §5 — Architecture Decisions (ADRs)

### ADR-001: FastAPI (not Flask / Django)
**Why**: Async-native; Pydantic integration; automatic OpenAPI docs; best for ML I/O-bound pipelines with many concurrent requests.

### ADR-002: Celery + Redis for Background Processing
**Why**: Twilio has a 5-second webhook timeout — synchronous ML inference takes 10–30s. Accept webhook immediately, process in Celery worker, deliver result via Twilio REST API. Prevents all timeout failures.

### ADR-003: PostgreSQL via Supabase
**Why**: Relational structure suits `claim → verdict → evidence` relationships well. Audit trail with timestamps. Complex admin queries.  
**Risk**: 7-day inactivity pause. Mitigation: UptimeRobot ping every 6 days.

### ADR-004: Upstash Redis (dual role)
**Why**: (1) AI result cache — deduplication of viral claims; (2) Celery message broker. One service, two roles. TTL = 86400s (24h).

### ADR-005: Gemini 2.0 Flash as Explainer (not GPT-4)
**Why**: Free tier covers all hackathon needs; no credit card; lowest latency for 2-line explanation task. NLI/verification done by DeBERTa — Gemini only writes the explanation.

### ADR-006: DeBERTa-v3-large-mnli for NLI (not GPT)
**Why**: Purpose-built for Natural Language Inference; faster and more accurate than prompting an LLM for entailment; deterministic scoring.

### ADR-007: XGBoost for Verdict Aggregation
**Why**: Interpretable, fast, handles sparse features from multiple sources (NLI score, similarity score, fact-check match, source count). Trained on pre-labeled claim-evidence pairs.

### ADR-008: whisper-tiny for Demo
**Why**: Runs on CPU in ~3s per 30s audio. Model accuracy trade-off noted — `whisper-medium` recommended for production with GPU.

### ADR-009: IndicTrans2 as Primary Translation (Google Translate as Fallback)
**Why**: State-of-the-art accuracy on Indic languages; open-source. Fallback to Google Translate API when model unavailable.

---

## §6 — Reliability & Disaster Recovery

| Service Fails           | Mitigation                                          | Recovery |
|-------------------------|-----------------------------------------------------|----------|
| Twilio cold start       | Pre-warm sandbox 10 min before demo                 | Immediate |
| Gemini quota            | Redis cache covers all pre-run demo queries         | Automatic |
| ClaimBuster API         | Skip filtering; send all extracted claims to NLI    | Transparent |
| Google Fact Check API   | Fall through to Bing → Wikipedia                    | Transparent |
| Bing Search API         | Wikipedia-only fallback; reduced evidence           | Degraded |
| DeBERTa OOM             | Reduce batch size; return `UNVERIFIABLE` gracefully | 1-step fallback |
| IndicTrans2 load fail   | Google Translate API fallback                       | Transparent |
| Supabase DB pause       | UptimeRobot ping; 30s manual resume                 | Prevented |
| Render backend cold start | UptimeRobot; self-ping on Celery worker start      | < 30s |
| Redis unavailable       | Bypass cache; process live                          | Slower |

### Demo Venue Contingencies
| Scenario             | Response |
|----------------------|----------|
| No WiFi              | Mobile hotspot; ngrok tunnel to local server |
| Twilio sandbox expired | Re-join sandbox 1h before demo; document join step |
| Whisper too slow     | Pre-transcribe audio; show text path in demo |
| Gemini quota hit     | All demo queries pre-cached; instant response |
| Supabase paused      | Pre-warm 1 hour before; UptimeRobot active |

---

## §7 — Pre-Demo Checklist

Run 1 hour before judging. Every item must be ✅.

**Twilio**
- [ ] WhatsApp sandbox not expired — join link tested
- [ ] Webhook URL set to production Render URL (`/api/webhook/whatsapp`)
- [ ] Twilio signature validation tested — reject unsigned request returns 403

**Models**
- [ ] All HuggingFace models loaded at server start (not lazy)
- [ ] Whisper model size confirmed: `tiny` for demo
- [ ] IndicTrans2 loaded OR Google Translate fallback configured

**APIs**
- [ ] Google Fact Check API key set in Render env vars
- [ ] Bing Search API key set in Render env vars
- [ ] Gemini API key set in Render env vars
- [ ] All demo queries pre-cached in production Redis

**Database**
- [ ] Supabase project active (last pinged < 1 hour ago)
- [ ] Alembic migrations applied: `alembic upgrade head`
- [ ] Demo admin credentials seeded: `python -m scripts.seed`
- [ ] UptimeRobot active for both backend (Render) and DB (Supabase)

**Security**
- [ ] `.env` NOT in git repo: `git log --oneline -- .env`
- [ ] No `print(phone_number)` or `print(api_key)` in production
- [ ] CORS configured to production admin frontend URL only
- [ ] Rate limiting verified: 11th message in 10 min → rate limit warning

**Demo Flow**
- [ ] All 4 input types tested end-to-end on production URL
- [ ] Admin dashboard accessible and shows real data
- [ ] Same text message sent twice → second is instant
- [ ] Hindi voice note processed correctly
- [ ] Demo script rehearsed 3 times

---

## §8 — Environment Variables

```bash
# Application
ENV=production
PORT=8000
FRONTEND_URL=https://your-admin.vercel.app

# Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886   # Sandbox number

# Database
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname
DIRECT_URL=postgresql://user:password@host:5432/dbname

# Cache & Task Queue
UPSTASH_REDIS_URL=https://xxx.upstash.io
UPSTASH_REDIS_TOKEN=your-token
CELERY_BROKER_URL=redis://xxx.upstash.io:6379/0

# AI / ML APIs
GEMINI_API_KEY=your-gemini-key
GOOGLE_FACT_CHECK_API_KEY=your-fc-key
BING_SEARCH_API_KEY=your-bing-key
CLAIMBUSTER_API_KEY=your-claimbuster-key
GOOGLE_TRANSLATE_API_KEY=your-translate-key   # Fallback only

# Media Storage
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret

# Auth (Admin Dashboard)
JWT_SECRET=your-jwt-secret-min-32-chars
JWT_ACCESS_EXPIRES_IN=15m
JWT_REFRESH_EXPIRES_IN=7d

# Model Paths (or HuggingFace model IDs)
WHISPER_MODEL_SIZE=tiny
LID_MODEL_PATH=./models/lid.176.ftz
INDIC_TRANS_MODEL_ID=ai4bharat/indictrans2-indic-en-1B
DEBERTA_MODEL_ID=cross-encoder/nli-deberta-v3-large
SBERT_MODEL_ID=sentence-transformers/all-MiniLM-L6-v2
```

---

## §9 — API Contract — Standard Response Shape

```python
# All endpoints return this envelope
class APIResponse(BaseModel, Generic[T]):
    success: bool
    data: Optional[T]
    message: Optional[str]
    error: Optional[str]
    code: Optional[str]   # e.g. "RATE_LIMITED", "UNSUPPORTED_TYPE", "UNVERIFIABLE"

# Verdict Response Shape
class VerdictResponse(BaseModel):
    verdict: Literal["VERIFIED", "FALSE", "OUTDATED", "PARTIAL", "UNVERIFIABLE"]
    confidence: float          # 0.0 – 1.0
    claim_extracted: str       # English-normalized claim
    explanation: str           # In user's detected language
    explanation_lang: str      # "hi", "mr", "en"
    evidence: List[EvidenceItem]
    cache_hit: bool
    processing_time_ms: int

class EvidenceItem(BaseModel):
    source_url: str
    source_name: str
    snippet: str               # Short excerpt (< 300 chars)
    relevance_score: float     # Sentence-BERT cosine similarity
```
