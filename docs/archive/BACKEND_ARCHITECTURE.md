# Backend Architecture — Is This Forward True?
> Owner: Tejas Kute (Backend Lead)  
> Read before writing any backend code. Feed §8 to AI at the start of every backend session.

---

## §1 — Folder Layout

```
backend/
├── main.py                        # FastAPI app — mounts all routers, middleware, health check
├── routers/
│   ├── webhook.py                 # POST /webhook/twilio — entry point for all Twilio messages
│   ├── verify.py                  # POST /verify — internal trigger for manual testing
│   └── health.py                  # GET /health
├── services/
│   ├── input/
│   │   ├── ocr_service.py         # EasyOCR — screenshot → text
│   │   ├── asr_service.py         # Whisper — voice note .ogg → text
│   │   ├── pdf_service.py         # PyMuPDF — PDF → text
│   │   └── url_service.py         # newspaper3k — article URL → text
│   ├── nlp/
│   │   ├── lang_detect.py         # fastText LID — language identification
│   │   ├── translate.py           # IndicTrans2 — regional → English
│   │   ├── claim_extract.py       # spaCy + KeyBERT — extract main claim
│   │   └── claim_filter.py        # ClaimBuster API — filter check-worthy claims
│   ├── retrieval/
│   │   ├── fact_check_api.py      # Google Fact Check Tools API
│   │   ├── web_search.py          # Bing Search API — live evidence
│   │   └── wikipedia.py           # Wikipedia API — background knowledge
│   ├── verification/
│   │   ├── nli_service.py         # DeBERTa NLI — entailment / contradiction
│   │   ├── similarity_service.py  # Sentence-BERT — semantic similarity
│   │   └── verdict_service.py     # XGBoost aggregator → final label
│   ├── explainer/
│   │   └── explain_service.py     # Gemini Flash — 2-line plain-language explanation
│   └── twilio_service.py          # Twilio client — send WhatsApp reply
├── pipelines/
│   └── verify_pipeline.py         # Orchestrates all services end-to-end
├── middleware/
│   ├── rate_limiter.py            # Per-number rate limiting (Redis)
│   ├── twilio_validator.py        # Validates Twilio webhook signature
│   └── error_handler.py           # Global exception → JSON error response
├── models/
│   ├── request_models.py          # Pydantic input models
│   └── response_models.py         # Pydantic response models
├── lib/
│   ├── redis_client.py            # Upstash Redis singleton
│   ├── db.py                      # SQLite/PostgreSQL session (claim log)
│   └── config.py                  # Settings loaded from .env via pydantic-settings
├── schemas/
│   └── claim_log.py               # SQLAlchemy model for audit log
├── tests/
│   ├── test_pipeline.py
│   └── test_services.py
├── .env.example
├── requirements.txt
└── Dockerfile
```

---

## §2 — API Contract

Every response from the backend follows this envelope shape (except Twilio webhook which sends plain text back to WhatsApp):

```python
# Pydantic response model
class APIResponse(BaseModel):
    success: bool
    data: Optional[Any]
    message: Optional[str]
    error: Optional[str]
    code: Optional[str]    # "VALIDATION_ERROR", "PIPELINE_ERROR", "RATE_LIMITED"

# Verdict data shape
class VerdictData(BaseModel):
    verdict: Literal["VERIFIED", "FALSE", "OUTDATED", "PARTIAL", "UNVERIFIABLE"]
    confidence: float                  # 0.0 – 1.0
    claim_extracted: str               # the specific claim checked
    evidence: list[EvidenceItem]       # top 3 evidence snippets
    explanation: str                   # 2-line plain language explanation
    explanation_lang: str              # language code the explanation is in
    cache_hit: bool
    processing_time_ms: int
```

### Endpoint Reference

| Method | Route | Auth | Description |
|---|---|---|---|
| POST | `/webhook/twilio` | Twilio Signature | Main entry — all WhatsApp messages land here |
| POST | `/verify` | API Key | Internal — test pipeline directly without Twilio |
| GET | `/health` | None | Health check for UptimeRobot |
| GET | `/admin/logs` | API Key | List recent claim verifications (dashboard) |

---

## §3 — Middleware Stack

```python
# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from middleware.rate_limiter import RateLimitMiddleware
from middleware.twilio_validator import TwilioValidatorMiddleware
from middleware.error_handler import register_error_handlers

app = FastAPI(title="Is This Forward True?", version="1.0.0")

# 1. CORS (for dashboard frontend only)
app.add_middleware(CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# 2. Per-number rate limiter (Redis-backed)
app.add_middleware(RateLimitMiddleware,
    max_requests=5,
    window_seconds=60,
    key_func=lambda req: req.headers.get("X-Twilio-From", "unknown")
)

# 3. Twilio webhook signature validation
app.add_middleware(TwilioValidatorMiddleware,
    auth_token=settings.TWILIO_AUTH_TOKEN,
    skip_paths=["/health", "/verify"]
)

# 4. Global error handler
register_error_handlers(app)
```

---

## §4 — Rate Limiting Strategy

| Scope | Limit | Window | Store |
|---|---|---|---|
| Per WhatsApp number (webhook) | 5 requests | 60 seconds | Redis |
| `/verify` endpoint (testing) | 20 requests | 60 seconds | Redis |
| Gemini Flash calls | 10 RPM (per Gemini free tier) | 60 seconds | Redis counter |
| Bing Search API calls | 1000/month free tier | — | Upstash counter |

Rate limit response sent back to user:
```
⏳ You've sent too many messages. Please wait 60 seconds before trying again.
```

---

## §5 — Redis Usage

```python
# lib/redis_client.py
from upstash_redis import Redis

redis = Redis(url=settings.UPSTASH_REDIS_URL, token=settings.UPSTASH_REDIS_TOKEN)

# Key patterns:
# Cache: "cache:{sha256_of_normalized_claim}"  TTL: 86400s (24h)
# Rate limit: "rl:{phone_number}"              TTL: 60s
# Gemini RPM: "gemini:rpm:{minute_bucket}"     TTL: 60s
```

Cache hit path: normalized claim → sha256 key → Redis GET → return cached verdict (< 100ms)
Cache miss path: full pipeline → Redis SET with TTL → return fresh verdict

---

## §6 — Database Schema (Claim Audit Log)

```python
# schemas/claim_log.py — SQLAlchemy
class ClaimLog(Base):
    __tablename__ = "claim_logs"

    id            = Column(Integer, primary_key=True)
    phone_hash    = Column(String)         # SHA256 of phone number — no PII stored
    input_type    = Column(String)         # text | screenshot | voice | pdf | url
    language_raw  = Column(String)         # detected input language
    claim_text    = Column(Text)           # extracted claim (English)
    verdict       = Column(String)         # VERIFIED / FALSE / OUTDATED / PARTIAL / UNVERIFIABLE
    confidence    = Column(Float)
    cache_hit     = Column(Boolean)
    processing_ms = Column(Integer)
    created_at    = Column(DateTime, default=datetime.utcnow)
```

> No raw message content is stored. Only the extracted claim and verdict are logged.

---

## §7 — Environment Variables

```bash
# Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your-auth-token
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886

# Google
GEMINI_API_KEY=your-gemini-api-key
GOOGLE_FACT_CHECK_API_KEY=your-fact-check-key

# Microsoft
BING_SEARCH_API_KEY=your-bing-key

# Redis (Upstash)
UPSTASH_REDIS_URL=https://xxx.upstash.io
UPSTASH_REDIS_TOKEN=your-token

# Database
DATABASE_URL=sqlite:///./claims.db          # SQLite for hackathon; swap to PostgreSQL for prod

# App
FRONTEND_URL=http://localhost:3000
PORT=8000
NODE_ENV=development
```

---

## §8 — AI Prompt for Backend Coding Sessions

> Copy and paste this before every backend coding session.

```
You are building a FastAPI + Python backend for a WhatsApp fact-checking system.

STRICT RULES:
1. All route handlers use async def and are wrapped in try/except.
   Exceptions are raised as HTTPException or passed to the global error handler.
2. All request/response models use Pydantic v2 (model_config, not class Config).
3. All external API calls (Gemini, Bing, Wikipedia, Fact Check) are wrapped in
   try/except with a fallback return — the pipeline must never crash on a single
   service failure.
4. Redis cache check ALWAYS comes before any ML inference or external API call.
   Cache key: "cache:" + sha256(claim.strip().lower())
   TTL: 86400 seconds.
5. Never log raw phone numbers. Always hash with SHA256 before logging.
6. Twilio webhook validation middleware must run on all /webhook/* routes.
7. Rate limiting is in middleware — do NOT add it inside route handlers.
8. Pydantic settings via pydantic-settings — no hardcoded secrets anywhere.
9. All service functions return a typed dict or dataclass — never raw dicts.
10. Model loading (Whisper, DeBERTa, Sentence-BERT) happens at startup in a
    lifespan() context manager, not on first request — cold starts are too slow.

Stack: FastAPI, Pydantic v2, SQLAlchemy 2, Upstash Redis, Twilio, EasyOCR,
       Whisper, PyMuPDF, IndicTrans2, DeBERTa, Sentence-BERT, XGBoost, Gemini Flash

Now build: [your specific service / endpoint]
```

---

## §9 — Model Loading Strategy

All heavy models load once at startup using FastAPI's `lifespan` context:

```python
# main.py
from contextlib import asynccontextmanager
from services.verification.nli_service import load_deberta
from services.verification.similarity_service import load_sbert
from services.input.asr_service import load_whisper

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — load all models into memory
    app.state.deberta = load_deberta()
    app.state.sbert = load_sbert()
    app.state.whisper = load_whisper()
    yield
    # Shutdown — nothing to clean up

app = FastAPI(lifespan=lifespan)
```

> On Render free tier, this means the first request after a cold start takes 30–60s.
> Ping `/health` 2 minutes before the demo to warm up all models.
