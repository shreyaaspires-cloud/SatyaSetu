# System Flow Document
## WhatsApp AI Fact-Checking System — FactGuard
> End-to-end data flow for all 4 input types, AI pipeline, caching, and response delivery.

---

## §1 — Master Flow: From WhatsApp to Verdict

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         MASTER MESSAGE FLOW                                     │
│                                                                                 │
│  User on WhatsApp                                                               │
│       │  forwards suspicious message                                            │
│       ▼                                                                         │
│  Twilio WhatsApp Sandbox                                                        │
│       │  POST /api/webhook/whatsapp                                             │
│       │  { Body, MediaUrl0, MediaContentType0, From, MessageSid }              │
│       ▼                                                                         │
│  FastAPI Webhook Handler (< 3 seconds)                                          │
│       │  1. Validate Twilio HMAC signature                                      │
│       │  2. Hash phone number (SHA-256)                                         │
│       │  3. Check rate limit (10/10min per number)                              │
│       │  4. Detect input type (text / image / audio / pdf / url)                │
│       │  5. Enqueue Celery task                                                 │
│       │  6. Return TwiML: "⏳ Checking your message..."                         │
│       ▼                                                                         │
│  Celery Worker (async, no timeout pressure)                                     │
│       │                                                                         │
│       ├─ [text]  → TEXT PIPELINE                                                │
│       ├─ [image] → OCR PIPELINE                                                 │
│       ├─ [audio] → ASR PIPELINE                                                 │
│       ├─ [pdf]   → PDF PIPELINE                                                 │
│       └─ [url]   → URL PIPELINE                                                 │
│                         │                                                       │
│                         ▼  (all pipelines converge to plain text)              │
│                    NLP + VERIFICATION PIPELINE                                  │
│                         │                                                       │
│                         ▼                                                       │
│                    RESPONSE FORMATTER                                           │
│                         │                                                       │
│                         ▼                                                       │
│                    Twilio REST API → WhatsApp user gets verdict                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## §2 — Input Type Detection

```python
# In webhook handler, immediately after receiving the Twilio payload

def detect_input_type(body: str, media_url: str, media_content_type: str) -> InputType:
    if media_url:
        if "image" in media_content_type:
            return InputType.IMAGE        # → OCR pipeline
        if "audio" in media_content_type or "ogg" in media_content_type:
            return InputType.AUDIO        # → ASR pipeline
        if "pdf" in media_content_type:
            return InputType.PDF          # → PDF pipeline
    if body:
        if re.match(r"https?://", body.strip()):
            return InputType.URL          # → URL pipeline
        return InputType.TEXT             # → Text pipeline
    return InputType.UNKNOWN
```

---

## §3 — Pipeline 1: Text Message

```
User sends: "नई सरकारी योजना – गैस सिलेंडर अब मुफ्त! आगे फॉरवर्ड करें"
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │  STEP 1: Cache Check                                  │
        │  normalized = text.strip().lower()                    │
        │  cache_key = "claim:" + sha256(normalized)            │
        │  Redis GET cache_key                                  │
        │       ├── HIT  → skip to STEP 6 (< 2 seconds)        │
        │       └── MISS → continue pipeline                    │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │  STEP 2: Language Detection                           │
        │  fastText LID model                                   │
        │  detected_lang = "hi" (Hindi)                        │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │  STEP 3: Translation to English                       │
        │  IndicTrans2: "hi" → "en"                            │
        │  translated = "New government scheme – gas cylinder   │
        │  now free! Forward this."                             │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │  STEP 4: Claim Extraction                             │
        │  spaCy: tokenize, NER (ORG, GOV, DATE entities)      │
        │  KeyBERT: extract key phrases                         │
        │  core_claim = "government scheme providing free gas   │
        │               cylinders to citizens"                  │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │  STEP 5: Check-Worthiness Filter                      │
        │  ClaimBuster API: CFS score = 0.87 (high)             │
        │  (If CFS < 0.30: return UNVERIFIABLE immediately)     │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼ (enters shared verification pipeline →  §5)
```

---

## §4 — Pipeline 2: Screenshot (Image / OCR)

```
User sends: [screenshot image of WhatsApp forward]
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │  STEP 1: Media Download                               │
        │  requests.get(MediaUrl0, auth=(SID, TOKEN))           │
        │  Save to /tmp/{message_sid}.jpg                       │
        │  Upload to Cloudinary (for audit trail)               │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │  STEP 2: OCR (EasyOCR)                                │
        │  reader = easyocr.Reader(['hi', 'en'])                │
        │  result = reader.readtext('/tmp/{sid}.jpg')           │
        │  extracted_text = " ".join([r[1] for r in result])   │
        │  Confidence filter: skip text blocks < 0.6 confidence │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼
                  → Feed extracted_text into TEXT PIPELINE (§3)
                    starting from STEP 2 (language detection)
```

---

## §5 — Pipeline 3: Voice Note (ASR)

```
User sends: [.ogg WhatsApp voice note in Hindi/Marathi]
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │  STEP 1: Media Download + Convert                     │
        │  Download .ogg from Twilio MediaUrl                   │
        │  pydub: convert .ogg → .wav (Whisper needs PCM)      │
        │  Upload original to Cloudinary                        │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │  STEP 2: Whisper ASR Transcription                    │
        │  model = whisper.load_model("tiny")                   │
        │  result = model.transcribe("/tmp/{sid}.wav",          │
        │                            language="hi")             │
        │  transcript = result["text"]                          │
        │  detected_lang = result["language"]  # hi / mr / en  │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼
                  → Feed transcript into TEXT PIPELINE (§3)
                    at STEP 3 if lang != "en", or STEP 4 if English
                    (skip LID — Whisper already detected language)
```

---

## §6 — Pipeline 4: PDF

```
User sends: [PDF file or URL to PDF]
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │  STEP 1: Fetch PDF                                    │
        │  If file: download from Twilio MediaUrl               │
        │  If URL: requests.get(url, timeout=10)                │
        │  Save to /tmp/{sid}.pdf                               │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │  STEP 2: Text Extraction (PyMuPDF)                    │
        │  doc = fitz.open("/tmp/{sid}.pdf")                    │
        │  text = ""                                            │
        │  for page in doc:                                     │
        │      text += page.get_text()                          │
        │  Truncate to first 5,000 chars for speed             │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼
                  → Feed extracted text into TEXT PIPELINE (§3)
                    starting from STEP 2 (language detection)
```

---

## §7 — Pipeline 5: URL / Article

```
User sends: https://example.com/article-about-scheme
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │  STEP 1: Article Scraping (newspaper3k)               │
        │  article = Article(url)                               │
        │  article.download()                                   │
        │  article.parse()                                      │
        │  title = article.title                                │
        │  body  = article.text[:5000]                          │
        │  combined = title + ". " + body                       │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼
                  → Feed combined text into TEXT PIPELINE (§3)
                    starting from STEP 2 (language detection)
```

---

## §8 — Shared Verification Pipeline (All Input Types Converge Here)

```
INPUT: English claim string (from any of the 5 pipelines above)

        ┌───────────────────────────────────────────────────────┐
        │  STEP A: Evidence Retrieval (3 parallel API calls)    │
        │                                                       │
        │  await asyncio.gather(                                │
        │      google_fact_check(claim),    # journalist checks │
        │      bing_search(claim),          # live web evidence │
        │      wikipedia_search(claim)      # background facts  │
        │  )                                                    │
        │  → Collect top 5 evidence snippets total              │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │  STEP B: NLI Scoring (DeBERTa-v3-large-mnli)         │
        │                                                       │
        │  For each evidence snippet:                           │
        │    input = f"{evidence} [SEP] {claim}"               │
        │    scores = deberta_model(input)                      │
        │    → {"entailment": 0.78, "neutral": 0.15,           │
        │        "contradiction": 0.07}                         │
        │                                                       │
        │  nli_scores = average across all evidence snippets    │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │  STEP C: Semantic Similarity (Sentence-BERT)          │
        │                                                       │
        │  claim_embedding = sbert.encode(claim)                │
        │  for evidence in evidence_list:                       │
        │      ev_embedding = sbert.encode(evidence.snippet)    │
        │      similarity = cosine_similarity(claim, ev)        │
        │  avg_similarity = mean(similarities)                  │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │  STEP D: Verdict Aggregation (XGBoost)                │
        │                                                       │
        │  features = {                                         │
        │      "entailment_score": nli_scores["entailment"],    │
        │      "contradiction_score": nli_scores["contradiction"]│
        │      "avg_similarity": avg_similarity,                │
        │      "fact_check_match": bool(google_fc_results),     │
        │      "source_count": len(evidence_list),              │
        │      "fact_check_verdict": fc_verdict_encoded,        │
        │  }                                                    │
        │                                                       │
        │  verdict_proba = xgb_model.predict_proba(features)   │
        │  verdict = argmax(verdict_proba)                      │
        │  # → "VERIFIED" / "FALSE" / "OUTDATED"               │
        │  #   "PARTIAL" / "UNVERIFIABLE"                       │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │  STEP E: Explanation Generation (Gemini 2.0 Flash)    │
        │                                                       │
        │  Cache check first:                                   │
        │  explanation_key = "explain:" + sha256(claim+verdict) │
        │                                                       │
        │  prompt = f"""                                        │
        │  Claim: {claim}                                       │
        │  Verdict: {verdict}                                   │
        │  Key evidence: {top_evidence_snippet}                 │
        │  Write a 2-sentence explanation in {lang}             │
        │  that a non-English user can understand.              │
        │  No jargon. Active voice.                             │
        │  """                                                  │
        │  explanation = gemini.generate(prompt)                │
        │  Redis SET explanation_key explanation EX 86400       │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │  STEP F: Cache Full Result                            │
        │  Redis SET cache_key VerdictResponse EX 86400         │
        └───────────────────────────────────────────────────────┘
                                │
                                ▼
                    RESPONSE FORMATTER (§9)
```

---

## §9 — Response Formatter & WhatsApp Delivery

```python
def format_whatsapp_response(verdict: VerdictResponse) -> str:
    """Format verdict into a readable WhatsApp message."""

    VERDICT_EMOJI = {
        "VERIFIED":      "✅",
        "FALSE":         "❌",
        "OUTDATED":      "⏰",
        "PARTIAL":       "⚠️",
        "UNVERIFIABLE":  "❓",
    }

    VERDICT_LABEL_HI = {
        "VERIFIED":      "सत्यापित (सच)",
        "FALSE":         "गलत (झूठ)",
        "OUTDATED":      "पुरानी जानकारी",
        "PARTIAL":       "आंशिक रूप से सही",
        "UNVERIFIABLE":  "सत्यापित नहीं हो सका",
    }

    emoji = VERDICT_EMOJI[verdict.verdict]
    label = VERDICT_LABEL_HI.get(verdict.verdict, verdict.verdict)

    lines = [
        f"{emoji} *{label}*",
        "",
        f"📋 *दावा:* _{verdict.claim_extracted}_",
        "",
        f"💬 *क्यों:* {verdict.explanation}",
        "",
    ]

    if verdict.evidence:
        lines.append("📚 *स्रोत (Sources):*")
        for i, ev in enumerate(verdict.evidence[:2], 1):
            lines.append(f"{i}. {ev.source_name} — {ev.source_url}")

    if verdict.cache_hit:
        lines.append("\n⚡ _Instant result (cached)_")

    return "\n".join(lines)
```

### WhatsApp Message Examples

**FALSE Verdict (Hindi):**
```
❌ *गलत (झूठ)*

📋 *दावा:* _government scheme providing free gas cylinders to citizens_

💬 *क्यों:* सरकार ने ऐसी कोई नई योजना घोषित नहीं की है। यह संदेश 2021 से फर्जी तरीके से प्रसारित हो रहा है।

📚 *स्रोत (Sources):*
1. AltNews — https://altnews.in/...
2. PIB Fact Check — https://pib.gov.in/...
```

**VERIFIED Verdict (English):**
```
✅ *VERIFIED*

📋 *Claim:* _PM Kisan Samman Nidhi provides ₹6000/year to farmers_

💬 *Why:* This is confirmed by the official government website and verified by multiple fact-checking organizations.

📚 *Sources:*
1. pmkisan.gov.in — https://pmkisan.gov.in/
2. PIB India — https://pib.gov.in/...
```

---

## §10 — Caching Strategy

```
┌─────────────────────────────────────────────────────────┐
│                  CACHE FLOW                              │
│                                                         │
│  Incoming message text                                  │
│         │                                               │
│         ▼                                               │
│  normalize: strip().lower().replace double-spaces       │
│         │                                               │
│         ▼                                               │
│  cache_key = "claim:" + sha256(normalized_text)         │
│         │                                               │
│         ├──── Redis GET(cache_key)                      │
│         │          │                                    │
│         │     ┌────┴───────────────────────────────┐   │
│         │     │  HIT (< 2s)                         │   │
│         │     │  Deserialize VerdictResponse JSON   │   │
│         │     │  Set cache_hit = True               │   │
│         │     │  Skip all ML processing              │   │
│         │     └────────────────────────────────────┘   │
│         │                                               │
│         └──── MISS → run full pipeline                  │
│                   → Redis SET(cache_key, result,        │
│                               ex=86400)                 │
│                                                         │
│  TTL: 86400 seconds (24 hours)                          │
│  Key prefixes:                                          │
│    "claim:{hash}"    → full VerdictResponse             │
│    "explain:{hash}"  → Gemini explanation string        │
│    "rate:{phone}"    → rate limit counter               │
└─────────────────────────────────────────────────────────┘
```

---

## §11 — Unsupported Input Handling

```
Input Type          | Handler
────────────────────|────────────────────────────────────────────────
Video (.mp4)        | "We currently support text, images, voice notes, PDFs, and article links. Videos are not yet supported."
Sticker             | Treat as image; if OCR returns empty → "No text found in this image."
Contact card        | "Please send the message content you want checked, not a contact card."
Too short (< 10ch)  | "Message too short to fact-check. Please forward the full text."
Too long (> 10,000ch)| Process first 10,000 chars; note truncation in response.
Unknown binary      | "This file type isn't supported yet. Try sending the text instead."
No text + no media  | "Please send a message, screenshot, voice note, PDF, or link to check."
```

---

## §12 — Admin Dashboard Flow

```
Admin opens dashboard: https://admin.factguard.vercel.app

          GET /api/admin/stats (JWT auth)
          ├── Total claims today
          ├── Verdict distribution (pie chart data)
          ├── Avg processing time
          └── Low-confidence queue count (confidence < 0.65)

          GET /api/admin/claims?page=1&verdict=UNVERIFIABLE
          ├── Paginated claim history
          ├── Filters: verdict, date, input_type, confidence
          └── Each row: claim, verdict, confidence, evidence URLs, timestamp

          GET /api/admin/claims/{id}
          └── Full claim detail: original input, extracted claim,
              all evidence, NLI scores, XGBoost probabilities,
              Gemini explanation, processing time breakdown

          PATCH /api/admin/claims/{id}/override
          └── Manual verdict override by admin (with reason)
              Stored for retraining dataset
```
