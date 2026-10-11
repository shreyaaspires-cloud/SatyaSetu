# AI/ML Guidance — Is This Forward True?
> Owner: Aaryan Rorane (ML Lead)  
> Covers every model, why it was chosen, how it's integrated, failure modes, and demo notes.  
> Feed §8 to AI at the start of every ML coding session.

---

## §1 — Pipeline Overview

```
Raw Input
    │
    ▼
[INPUT PROCESSING] ─── type-specific extractor → raw text
    │
    ▼
[NLP PIPELINE] ──────── detect language → translate → extract claim → filter
    │
    ▼
[EVIDENCE RETRIEVAL] ── Fact Check API + Bing Search + Wikipedia
    │
    ▼
[AI VERIFICATION] ───── DeBERTa NLI + Sentence-BERT + XGBoost
    │
    ▼
[EXPLAINER] ─────────── Gemini Flash → plain-language 2-line explanation
    │
    ▼
Verdict + Evidence + Explanation → Twilio → WhatsApp
```

---

## §2 — Layer 1: Input Processing

### 2.1 — EasyOCR (Screenshot → Text)

| Attribute | Value |
|---|---|
| Library | `easyocr` 1.7.x |
| Languages | `['en', 'hi']` — English + Hindi Devanagari |
| Model size | ~500 MB (loaded at startup) |
| Accuracy concern | Low-res WhatsApp screenshots; use `detail=0` for speed |

```python
# services/input/ocr_service.py
import easyocr

_reader = None

def load_ocr():
    global _reader
    _reader = easyocr.Reader(['en', 'hi'], gpu=False)
    return _reader

def extract_text_from_image(image_bytes: bytes) -> str:
    import numpy as np
    import cv2
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    results = _reader.readtext(img, detail=0, paragraph=True)
    return " ".join(results).strip()
```

**Failure mode**: Blurry image → empty string. Fallback: return `""` and send user message `"I couldn't read that image clearly. Please send the text directly."`

---

### 2.2 — Whisper ASR (Voice Note → Text)

| Attribute | Value |
|---|---|
| Library | `openai-whisper` or `faster-whisper` |
| Model size | `base` model (~140 MB) — best speed/accuracy tradeoff for hackathon |
| Languages | Auto-detected; handles Hindi, Marathi, Hinglish |
| Input format | `.ogg` (WhatsApp default) — Whisper accepts it natively |

```python
# services/input/asr_service.py
import whisper
import tempfile, os

_model = None

def load_whisper():
    global _model
    _model = whisper.load_model("base")
    return _model

def transcribe_audio(audio_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        result = _model.transcribe(tmp_path, task="transcribe")
        return result["text"].strip()
    finally:
        os.unlink(tmp_path)
```

**Failure mode**: Noisy audio, background music → garbled text. No retry — surface error to user.

---

### 2.3 — PyMuPDF (PDF → Text)

```python
# services/input/pdf_service.py
import fitz   # PyMuPDF

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text[:10000].strip()   # cap at 10k chars to fit NLP pipeline
```

**Limit**: Scanned PDFs (image-only) → zero text extracted. Fallback: detect empty text → run OCR on first page image.

---

### 2.4 — newspaper3k (URL → Article Text)

```python
# services/input/url_service.py
from newspaper import Article

def extract_text_from_url(url: str) -> str:
    article = Article(url)
    article.download()
    article.parse()
    return (article.title + " " + article.text)[:10000].strip()
```

**Failure mode**: Paywalled article → 403. Fallback: extract Open Graph meta description only.

---

## §3 — Layer 2: NLP Pipeline

### 3.1 — Language Detection (fastText LID)

```python
# services/nlp/lang_detect.py
import fasttext
import urllib.request, os

MODEL_PATH = "models/lid.176.bin"

def load_lid():
    if not os.path.exists(MODEL_PATH):
        urllib.request.urlretrieve(
            "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin",
            MODEL_PATH
        )
    return fasttext.load_model(MODEL_PATH)

_model = None

def detect_language(text: str) -> str:
    """Returns ISO 639-1 code: 'hi', 'mr', 'en', etc."""
    global _model
    predictions = _model.predict(text.replace("\n", " "), k=1)
    lang = predictions[0][0].replace("__label__", "")
    return lang
```

Languages handled: `hi` (Hindi), `mr` (Marathi), `en` (English), `ur` (Urdu), plus auto-passthrough for others.

---

### 3.2 — Translation (IndicTrans2)

> Translates Hindi / Marathi → English so all downstream models (trained on English data) work correctly.

```python
# services/nlp/translate.py
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

# Model: ai4bharat/indictrans2-indic-en-dist-200M
# Smaller distilled version — suitable for hackathon hardware constraints

SUPPORTED_LANGS = {"hi", "mr", "bn", "pa", "gu", "ta", "te", "kn", "ur"}

_model = None
_tokenizer = None

def load_translator():
    global _model, _tokenizer
    _tokenizer = AutoTokenizer.from_pretrained("ai4bharat/indictrans2-indic-en-dist-200M", trust_remote_code=True)
    _model = AutoModelForSeq2SeqLM.from_pretrained("ai4bharat/indictrans2-indic-en-dist-200M", trust_remote_code=True)
    return _model, _tokenizer

def translate_to_english(text: str, src_lang: str) -> str:
    if src_lang == "en" or src_lang not in SUPPORTED_LANGS:
        return text   # passthrough
    inputs = _tokenizer(text, return_tensors="pt", padding=True)
    outputs = _model.generate(**inputs, max_length=512)
    return _tokenizer.decode(outputs[0], skip_special_tokens=True)
```

**Fallback**: If IndicTrans2 fails (OOM, cold start), use Google Translate API as backup (`googletrans` library).

---

### 3.3 — Claim Extraction (spaCy + KeyBERT)

Two-step process:
1. **spaCy** → extract named entities and noun chunks to ground the claim
2. **KeyBERT** → extract the most semantically central sentence as the verifiable claim

```python
# services/nlp/claim_extract.py
import spacy
from keybert import KeyBERT

_nlp = None
_kw_model = None

def load_extractor():
    global _nlp, _kw_model
    _nlp = spacy.load("en_core_web_sm")
    _kw_model = KeyBERT()
    return _nlp, _kw_model

def extract_claim(text: str) -> str:
    """Returns the single most verifiable claim sentence."""
    # Split into sentences
    doc = _nlp(text)
    sentences = [sent.text.strip() for sent in doc.sents if len(sent.text.strip()) > 20]
    if not sentences:
        return text[:500]
    # Score each sentence by keyword density
    keywords = _kw_model.extract_keywords(text, keyphrase_ngram_range=(1, 2), top_n=5)
    kw_set = {kw[0].lower() for kw in keywords}
    scores = []
    for sent in sentences:
        score = sum(1 for kw in kw_set if kw in sent.lower())
        scores.append((score, sent))
    # Return highest-scoring sentence
    return max(scores, key=lambda x: x[0])[1]
```

---

### 3.4 — Claim Filtering (ClaimBuster)

ClaimBuster API filters out non-factual claims (opinions, questions, greetings) before sending to the expensive evidence retrieval step.

```python
# services/nlp/claim_filter.py
import httpx

CLAIMBUSTER_URL = "https://idir.uta.edu/claimbuster/api/v2/score/text/"

async def is_check_worthy(claim: str, api_key: str) -> tuple[bool, float]:
    """Returns (is_worthy, score). Score > 0.5 = check-worthy factual claim."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            CLAIMBUSTER_URL + claim,
            headers={"x-api-key": api_key}
        )
    data = r.json()
    score = data["results"][0]["score"]
    return score > 0.5, score
```

**Fallback**: If ClaimBuster API is down, default to `is_worthy=True` — process all claims.

---

## §4 — Layer 3: Evidence Retrieval

### 4.1 — Google Fact Check Tools API

```python
# services/retrieval/fact_check_api.py
import httpx

BASE_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

async def search_fact_checks(claim: str, api_key: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(BASE_URL, params={
            "query": claim,
            "key": api_key,
            "languageCode": "en"
        })
    data = r.json()
    results = []
    for item in data.get("claims", [])[:3]:
        review = item.get("claimReview", [{}])[0]
        results.append({
            "source": review.get("publisher", {}).get("name", "Unknown"),
            "url": review.get("url", ""),
            "rating": review.get("textualRating", ""),
            "snippet": item.get("text", "")
        })
    return results
```

---

### 4.2 — Bing Search API (Live Evidence)

```python
# services/retrieval/web_search.py
import httpx

BING_URL = "https://api.bing.microsoft.com/v7.0/search"

async def search_web(claim: str, api_key: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(BING_URL,
            headers={"Ocp-Apim-Subscription-Key": api_key},
            params={"q": claim + " fact check", "count": 5, "mkt": "en-IN"}
        )
    results = r.json().get("webPages", {}).get("value", [])
    return [{"title": r["name"], "url": r["url"], "snippet": r["snippet"]} for r in results[:3]]
```

---

## §5 — Layer 4: AI Verification

### 5.1 — DeBERTa NLI (Entailment / Contradiction)

Model: `cross-encoder/nli-deberta-v3-small` (lighter than v3-base, suitable for hackathon)

```python
# services/verification/nli_service.py
from transformers import pipeline

_nli = None

def load_deberta():
    global _nli
    _nli = pipeline("text-classification",
                    model="cross-encoder/nli-deberta-v3-small",
                    device=-1)   # CPU; set to 0 for GPU
    return _nli

def get_nli_scores(claim: str, evidence_snippet: str) -> dict:
    """Returns {'entailment': float, 'neutral': float, 'contradiction': float}"""
    result = _nli(f"{evidence_snippet} [SEP] {claim}", top_k=None)
    return {item["label"].lower(): item["score"] for item in result}
```

Interpretation:
- `entailment > 0.6` → evidence supports claim
- `contradiction > 0.6` → evidence refutes claim
- Otherwise → neutral / insufficient evidence

---

### 5.2 — Sentence-BERT (Semantic Similarity)

Model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
Multilingual → handles Hinglish claims after partial translation

```python
# services/verification/similarity_service.py
from sentence_transformers import SentenceTransformer, util

_model = None

def load_sbert():
    global _model
    _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return _model

def get_similarity(claim: str, evidence: str) -> float:
    emb_claim = _model.encode(claim, convert_to_tensor=True)
    emb_evid  = _model.encode(evidence, convert_to_tensor=True)
    return float(util.cos_sim(emb_claim, emb_evid))
```

---

### 5.3 — XGBoost Verdict Aggregator

Takes NLI scores + similarity + fact-check rating → outputs final verdict label.

**Feature vector** (per claim-evidence pair, averaged across top 3 evidence):
```
[entailment_score, contradiction_score, neutral_score,
 sbert_similarity, fact_check_found (0/1), fact_check_rating_encoded]
```

**Labels**: `0=VERIFIED, 1=FALSE, 2=OUTDATED, 3=PARTIAL, 4=UNVERIFIABLE`

```python
# services/verification/verdict_service.py
import xgboost as xgb
import numpy as np
import joblib

LABEL_MAP = {0: "VERIFIED", 1: "FALSE", 2: "OUTDATED", 3: "PARTIAL", 4: "UNVERIFIABLE"}
MODEL_PATH = "models/verdict_xgb.pkl"

_model = None

def load_verdict_model():
    global _model
    _model = joblib.load(MODEL_PATH)
    return _model

def aggregate_verdict(nli_scores_list: list[dict], similarity_scores: list[float],
                      fact_check_found: bool) -> tuple[str, float]:
    avg_entail = np.mean([s["entailment"] for s in nli_scores_list])
    avg_contra = np.mean([s["contradiction"] for s in nli_scores_list])
    avg_neutral = np.mean([s["neutral"] for s in nli_scores_list])
    avg_sim = np.mean(similarity_scores)
    features = np.array([[avg_entail, avg_contra, avg_neutral,
                          avg_sim, int(fact_check_found), 0.0]])
    pred = _model.predict(features)[0]
    prob = float(max(_model.predict_proba(features)[0]))
    return LABEL_MAP[pred], prob
```

> **Hackathon Note**: The XGBoost model must be pre-trained offline and committed as `models/verdict_xgb.pkl`. Use the synthetic training data in `notebooks/train_verdict_model.ipynb`. If the file is missing, fall back to a rule-based heuristic (see §6).

---

## §6 — Rule-Based Fallback (XGBoost unavailable)

If the XGBoost model file is missing or fails to load, use this deterministic fallback:

```python
def rule_based_verdict(avg_entailment: float, avg_contradiction: float,
                       fact_check_found: bool) -> tuple[str, float]:
    if fact_check_found and avg_entailment > 0.6:
        return "VERIFIED", avg_entailment
    if avg_contradiction > 0.6:
        return "FALSE", avg_contradiction
    if avg_entailment > 0.5:
        return "PARTIAL", avg_entailment
    if not fact_check_found and avg_entailment < 0.4:
        return "UNVERIFIABLE", 0.5
    return "PARTIAL", 0.4
```

---

## §7 — Layer 5: Explainer (Gemini Flash)

```python
# services/explainer/explain_service.py
import google.generativeai as genai

genai.configure(api_key=settings.GEMINI_API_KEY)
_model = genai.GenerativeModel("gemini-2.0-flash")

PROMPT_TEMPLATE = """
You are a fact-checking assistant for Indian WhatsApp users.
A forwarded message claims: "{claim}"
Our system found the verdict is: {verdict}
Top evidence: {evidence_summary}

Write a 2-line explanation in {language} that:
1. Clearly states whether the claim is true, false, or uncertain
2. Briefly says why, using the evidence above
3. Uses simple words — no jargon. No bullet points. Just 2 sentences.
"""

async def generate_explanation(claim: str, verdict: str,
                               evidence_summary: str, language: str = "English") -> str:
    prompt = PROMPT_TEMPLATE.format(
        claim=claim, verdict=verdict,
        evidence_summary=evidence_summary, language=language
    )
    response = await _model.generate_content_async(prompt)
    return response.text.strip()
```

**Gemini rate limit handling**: Counter in Redis. If RPM > 10, return a templated explanation instead:
```python
TEMPLATE_EXPLANATIONS = {
    "VERIFIED": "This claim appears to be true based on multiple reliable sources.",
    "FALSE": "This claim appears to be false. Reliable sources contradict it.",
    ...
}
```

---

## §8 — AI Prompt for ML Coding Sessions

> Copy and paste before every ML coding session.

```
You are building the ML pipeline for a WhatsApp misinformation detection system in Python.

STACK: FastAPI, Transformers (HuggingFace), sentence-transformers, XGBoost, EasyOCR, Whisper, IndicTrans2, spaCy, KeyBERT, fastText

STRICT RULES:
1. All HuggingFace models load at startup in a lifespan() context — never on first request.
2. Every external API call (Gemini, Bing, Fact Check, ClaimBuster) is in try/except.
   On failure: return None or a safe default — never crash the pipeline.
3. Redis cache check FIRST — before any model inference or API call.
   Cache key: "cache:" + sha256(claim.strip().lower())
4. All model functions are synchronous (def, not async def).
   Route handlers calling them use asyncio.run_in_executor() to avoid blocking.
5. Feature vectors for XGBoost must be numpy arrays — never Python lists.
6. Pydantic v2 for all data models — use model_config = ConfigDict(from_attributes=True).
7. No GPU assumptions — all models default to device=-1 (CPU).
   Add optional GPU path with try/except for torch.cuda.is_available().
8. Whisper transcription: always use a temp file + finally: os.unlink() for cleanup.
9. All text passed to models must be .strip() first.
10. Return typed dataclasses or Pydantic models — never raw dicts from service functions.

Now build: [your specific service / model integration]
```

---

## §9 — Model Sizes & Memory Budget (Render Free Tier: 512 MB RAM)

| Model | Size | Loaded At |
|---|---|---|
| EasyOCR (en+hi) | ~500 MB | Startup — only if GPU available; else lazy-load |
| Whisper base | 140 MB | Startup |
| fastText LID | 120 MB | Startup |
| IndicTrans2 distilled | ~400 MB | Startup |
| spaCy en_core_web_sm | 12 MB | Startup |
| KeyBERT (MiniLM) | ~90 MB | Startup |
| DeBERTa v3 small | 180 MB | Startup |
| Sentence-BERT MiniLM | 120 MB | Startup |
| XGBoost verdict | <1 MB | Startup |

> ⚠️ **Total: ~1.5 GB** — exceeds Render free tier (512 MB). Use Render Standard ($7/mo) for demo day, or run locally and tunnel with `ngrok`. EasyOCR can be lazy-loaded (only on screenshot inputs) to reduce baseline RAM by ~500 MB.

---

## §10 — Demo Pre-Caching

Before the demo, run these queries to pre-cache AI responses in Redis:

```python
# scripts/precache_demo.py
DEMO_CLAIMS = [
    "The government has announced free ration for all families until December 2025.",
    "Drinking hot water kills coronavirus.",
    "5G towers cause cancer.",
    "WhatsApp messages are now charged Rs 1 per message.",
]

for claim in DEMO_CLAIMS:
    result = run_pipeline_sync(claim, "text")
    print(f"Cached: {claim[:50]}... → {result.verdict}")
```

Run: `python scripts/precache_demo.py` on production before judges arrive.
