# Product Requirements Document
## WhatsApp AI Fact-Checking System — FactGuard
> **Version**: 1.0 | **Hackathon Doc** | Complete all sections before coding begins.

---

## §1 — Problem Statement

```
Forwarded WhatsApp messages spread health misinformation, fake government schemes,
and fabricated news at scale — often in Hindi, Marathi, or Hinglish — embedded in
screenshots, voice notes, or PDFs that users cannot easily verify on their own.

Problem source:    Hackathon prompt — misinformation in regional-language messaging
Who experiences it: 500M+ Indian WhatsApp users, many with limited English literacy
```

---

## §2 — Problem Analysis

| Dimension           | Details |
|---------------------|---------|
| **Root cause**      | Forwarded messages bypass editorial filters; regional language and mixed media make manual verification difficult |
| **Who is affected** | Non-English-literate users in tier-2/3 cities, elderly users, rural communities — highest-trust populations for WhatsApp |
| **Scale of problem** | India has 487M WhatsApp users; WHO estimated 25× more COVID misinformation spread on messaging apps than on Twitter |
| **Current solutions** | Fact-checking websites (AltNews, BOOM), Google Reverse Image Search — all require English, require leaving the app |
| **Why current solutions fail** | Require the user to copy, switch app, paste, search — 5+ manual steps; no voice note support; no regional language output |
| **Our opportunity** | Meet users inside WhatsApp, in their language, supporting every media type they already receive |

---

## §3 — Solution Overview

**Paragraph 1 — What it does and for whom:**
FactGuard is a WhatsApp chatbot that lets any user forward a suspicious message — text, screenshot, voice note, PDF, or article link — and receive a plain-language verdict in seconds. It supports Hindi, Marathi, and Hinglish natively. A user who cannot read English can still get a clear `FALSE` or `VERIFIED` label with a short explanation in their own language, without leaving WhatsApp.

**Paragraph 2 — How it's different:**
Unlike web fact-checkers that require English literacy and app-switching, FactGuard works entirely inside WhatsApp and handles all four media types forwarded messages arrive in. Its multi-layer AI pipeline — OCR → ASR → NLP → NLI verification → explainer LLM — gives a sourced verdict with evidence snippets, not just a label. Responses are cached so repeat queries (the same viral message forwarded by many users) are instant.

---

## §4 — User Personas

### Persona 1 — Primary User: Pratibha (Everyday WhatsApp User)
| Field              | Detail |
|--------------------|--------|
| **Name**           | Pratibha Desai, 48 |
| **Role / Context** | Homemaker in Pune; receives 30–40 messages/day in family groups |
| **Tech literacy**  | Low — comfortable with WhatsApp, rarely uses browsers |
| **Main pain point** | Cannot tell if a "free government gas scheme" screenshot is real; trusts and forwards it anyway |
| **What success looks like** | Sends message to FactGuard, gets a Hindi reply in < 15 seconds: "यह संदेश गलत है — सरकार ने ऐसी कोई योजना घोषित नहीं की।" |
| **Primary device** | Android mobile |

### Persona 2 — Power User: Arjun (Community Journalist / Fact-Checker Volunteer)
| Field              | Detail |
|--------------------|--------|
| **Name**           | Arjun Rao, 26 |
| **Role / Context** | Student journalist; monitors local WhatsApp groups for misinformation |
| **Pain point**     | Spends 20–30 min manually verifying a single claim across 5 sources |
| **What success looks like** | Gets a sourced verdict with evidence URLs in under 10 seconds; can cite the bot's evidence in his own reporting |

### Persona 3 — Admin: Moderator / NGO Partner
| Field              | Detail |
|--------------------|--------|
| **Name**           | NGO content moderator |
| **Role / Context** | Reviews bot verdicts flagged as uncertain; adjusts confidence thresholds |
| **Pain point**     | No visibility into what the bot is being asked; cannot audit false-positive verdicts |
| **What success looks like** | Admin dashboard shows claim volume, verdict distribution, low-confidence flags for manual review |

---

## §5 — User Stories

| ID    | Persona       | Story                                                                                                   | Priority |
|-------|---------------|----------------------------------------------------------------------------------------------------------|----------|
| US-01 | Pratibha      | As a user, I want to forward a WhatsApp text message to the bot so that I get a verdict in Hindi         | **M**    |
| US-02 | Pratibha      | As a user, I want to send a screenshot of a forwarded message so that the bot reads and checks the text inside | **M** |
| US-03 | Pratibha      | As a user, I want to send a voice note in Hindi/Marathi so that the bot transcribes and fact-checks it  | **M**    |
| US-04 | Arjun         | As a user, I want to send a PDF document link so that the bot extracts and verifies specific claims in it | **M**    |
| US-05 | Arjun         | As a user, I want to send a news article URL so that the bot checks the factual claims in the article    | **M**    |
| US-06 | Pratibha      | As a user, I want the verdict explanation in my language (Hindi/Marathi) so that I understand it without needing English | **M** |
| US-07 | Arjun         | As a user, I want to see the source URLs used to verify the claim so that I can read the evidence myself | **S**    |
| US-08 | Moderator     | As an admin, I want to see a dashboard of all claims checked, verdicts given, and low-confidence results | **S**    |
| US-09 | Arjun         | As a user, I want to see if a claim is `OUTDATED` (was true but is no longer) so that I can flag stale info | **S**   |
| US-10 | Pratibha      | As a user, I want to be told when a claim cannot be verified so that I don't assume it is true            | **M**    |
| US-11 | All           | As a user, I want duplicate forwarded messages to get instant responses so that I don't wait for re-analysis | **S** |

---

## §6 — Functional Requirements

| ID    | Requirement                                                                                           | Verification in Demo |
|-------|-------------------------------------------------------------------------------------------------------|----------------------|
| FR-01 | System accepts plain text message via WhatsApp and returns a verdict                                  | Send text → show verdict in WhatsApp |
| FR-02 | System accepts image/screenshot, runs OCR, extracts text, and fact-checks it                          | Send screenshot of fake scheme → show FALSE verdict |
| FR-03 | System accepts voice note (`.ogg`), transcribes it using Whisper, and fact-checks the transcript      | Send Hindi voice note → show transcription + verdict |
| FR-04 | System accepts a PDF file or URL to a PDF, extracts text, and fact-checks claims within it            | Send PDF link → show extracted claim + verdict |
| FR-05 | System accepts a news article URL, scrapes the content, and verifies the lead claim                   | Send article URL → show verdict with evidence |
| FR-06 | System detects input language (Hindi / Marathi / Hinglish / English)                                  | Show detected language in response metadata |
| FR-07 | System translates non-English input to English for the NLP/verification pipeline                      | Hindi input → English claim in pipeline logs |
| FR-08 | System returns one of five verdict labels: `VERIFIED`, `FALSE`, `OUTDATED`, `PARTIAL`, `UNVERIFIABLE` | Each label shown in demo with correct claim |
| FR-09 | System returns plain-language explanation in user's detected language                                 | Hindi input → Hindi explanation in response |
| FR-10 | System returns at least one source URL with each `VERIFIED` or `FALSE` verdict                        | Source URL visible in WhatsApp reply |
| FR-11 | System caches results for identical or near-identical claims (Redis, 24h TTL)                         | Same message sent twice — second response is instant |
| FR-12 | System responds within 15 seconds for cache miss, < 2 seconds for cache hit                           | Time stamps shown in demo |
| FR-13 | Admin dashboard shows claim volume, verdict distribution, low-confidence flags                        | Open admin URL during demo |
| FR-14 | System rate-limits per phone number to prevent abuse (10 checks / 10 minutes)                         | 11th message in 10 min returns rate-limit warning |

---

## §7 — Non-Functional Requirements

| Category        | Requirement                                          | Target |
|-----------------|------------------------------------------------------|--------|
| **Performance** | Webhook response to Twilio (ack)                     | < 5 seconds (Twilio timeout) |
| **Performance** | End-to-end verdict delivery                          | < 15 seconds (cache miss), < 2s (cache hit) |
| **Availability** | Uptime during demo                                   | 99.9% |
| **Scalability** | Concurrent requests                                  | 50 simultaneous (hackathon scale) |
| **Accuracy**    | NLI verdict alignment with human judgment             | ≥ 80% on test set |
| **Language**    | Language detection accuracy                           | ≥ 95% on Hindi/Marathi/English |
| **Security**    | Twilio webhook validation                             | HMAC signature verified on every request |
| **Privacy**     | No user phone numbers logged to persistent storage    | Phone numbers hashed in DB |
| **Accessibility** | Response readable without English literacy          | All responses in detected user language |

---

## §8 — Feature Scope

### In Scope
- Text message fact-checking
- Screenshot OCR fact-checking (Hindi + English)
- Voice note transcription + fact-checking (Hindi, Marathi)
- PDF extraction + fact-checking (URL or file upload)
- News article URL fact-checking
- Multi-label verdict system (5 labels)
- Language-aware response generation (Hindi / Marathi / English)
- Redis caching for duplicate claims
- Admin dashboard (verdict stats, low-confidence queue)
- Rate limiting per phone number

### Out of Scope
- WhatsApp group moderation (requires WhatsApp Business API approval)
- Video fact-checking
- Real-time journalist alerts
- Browser extension
- Custom fine-tuning of models (use pre-trained)

### Future Roadmap
| Feature | Why Later |
|---------|-----------|
| Real-time group monitoring | Requires WhatsApp Business API Partner access (weeks) |
| Video + deepfake detection | Compute intensive; needs GPU cluster |
| Personalized trust scores per user | Needs longitudinal data collection |
| Browser extension | Out of WhatsApp scope; separate product track |
| Custom regional model fine-tuning | Needs labelled Indian misinformation dataset |

---

## §9 — Success Metrics

| Metric                             | Baseline (current)        | Target with FactGuard          | How shown in demo |
|------------------------------------|---------------------------|--------------------------------|-------------------|
| Time to verify a WhatsApp claim    | 5–20 min (manual search)  | < 15 seconds                   | Stopwatch in demo |
| Steps to verify                    | 5+ (copy, switch, search) | 1 (forward to bot)             | Live demo walkthrough |
| Language barrier removed           | English-only tools         | Hindi/Marathi responses        | Hindi voice note demo |
| Duplicate claim response time      | Same as new claim          | < 2 seconds (Redis cache hit)  | Send same message twice |
| Verdict confidence (NLI)           | None (no tool)             | ≥ 0.80 on labelled test set    | Show accuracy table |

---

## §10 — Dependencies

| Dependency                | Type            | Risk if unavailable                       | Mitigation |
|---------------------------|-----------------|-------------------------------------------|------------|
| Twilio WhatsApp Sandbox   | External API    | No message ingestion                       | Pre-configure sandbox; have Postman collection as fallback demo |
| Google Fact Check API     | External API    | Reduced evidence quality                  | Fall through to Bing Search + Wikipedia |
| Bing Search API           | External API    | Reduced evidence                          | Wikipedia fallback; cached results cover demo |
| Gemini 2.0 Flash          | External AI     | No explainer generation                   | Redis cache + templated fallback responses |
| Whisper (OpenAI / local)  | ML Model        | Voice notes not transcribed               | Show text/screenshot path in demo |
| IndicTrans2               | ML Model (HF)   | Hindi/Marathi not translated               | fallback: Google Translate API |
| DeBERTa NLI               | ML Model (HF)   | No NLI verification                       | Fallback to keyword matching heuristic |
| Upstash Redis             | Cache           | All queries slow; no dedup                | Bypass cache; still functional, slower |

---

## §11 — Risk Register

| Risk                                     | Likelihood | Impact | Mitigation |
|------------------------------------------|------------|--------|------------|
| Twilio webhook delivery delay at demo    | Medium     | High   | Pre-warm; use ngrok for local demo backup |
| Gemini quota exhausted                   | Medium     | High   | Pre-cache all demo queries in Redis |
| Whisper model too slow on CPU            | High       | Medium | Use `whisper-tiny` for demo; note `medium` for production |
| IndicTrans2 model load time > 30s        | High       | Medium | Pre-load models on server start, not per-request |
| Twilio sandbox expiry during demo        | Low        | High   | Verify sandbox 1 hour before demo; keep WhatsApp joined |
| False-negative on demo claim             | Medium     | High   | Pre-select 3 demo claims with verified correct outputs |
| Redis Upstash free tier limit            | Low        | Low    | 10k commands/day; well within demo budget |

---

## §12 — Hackathon Criteria Alignment

| Criterion              | How FactGuard Addresses It |
|------------------------|----------------------------|
| **Innovation**         | Multimodal pipeline (text + OCR + ASR + PDF + URL) inside WhatsApp; regional language–first design — no existing tool combines all these |
| **Technical Execution** | 7-layer AI pipeline with NLI verification, Redis caching, Twilio integration; fully deployed and live during demo |
| **Problem–Solution Fit** | 487M Indian WhatsApp users; misinformation highest where English literacy lowest; we remove both barriers |
| **Design / UX**        | Zero-UI — the interface IS WhatsApp; responses in user's language; 5-label verdict is readable at a glance |
| **Completeness**       | All 4 input types working; cache, rate limiting, admin dashboard in scope |
| **Presentation**       | 3-minute scripted demo; all demo queries pre-cached; backup Postman collection if Twilio fails |

---

## §13 — Glossary

| Term         | Definition |
|--------------|------------|
| NLI          | Natural Language Inference — classifying whether evidence *entails*, *contradicts*, or is *neutral* toward a claim |
| CFS          | Claim Feasibility Score — ClaimBuster's rating of whether a statement is worth fact-checking |
| ASR          | Automatic Speech Recognition — converting spoken audio to text (Whisper) |
| OCR          | Optical Character Recognition — extracting text from images (EasyOCR) |
| LID          | Language Identification — detecting the language of a text (fastText) |
| NLU          | Natural Language Understanding — extracting meaning/intent from text |
| Verdicts     | `VERIFIED` / `FALSE` / `OUTDATED` / `PARTIAL` / `UNVERIFIABLE` — the 5 output labels |
| RBAC         | Role-Based Access Control — admin vs public user access levels |
| Webhook      | HTTP callback URL Twilio hits when a WhatsApp message is received |
| Sandbox      | Twilio's test WhatsApp number for development (no approval needed) |
