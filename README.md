# SatyaSetu Backend — Automated Fact-Checking Pipeline for WhatsApp

SatyaSetu is an AI-powered automated fact-checking backend pipeline designed to combat misinformation on WhatsApp in real time. It accepts multi-modal inputs (Text, Images, Audio/Voice notes, PDFs, URLs), extracts claims, performs multi-source evidence retrieval, evaluates claim validity using NLI and semantic models, and returns plain-language multi-lingual explanations back to the user via WhatsApp.

## 🚀 Features

- **Multi-modal Input Processing**: Supports Text, EasyOCR for images, Whisper for voice notes, PyMuPDF for documents, and web parsing for links.
- **Multilingual Support**: Supports language detection and translation for regional Indian languages.
- **Claim Extraction & Filtering**: Uses spaCy, KeyBERT, and ClaimBuster to isolate check-worthy claims.
- **Multi-Source Evidence Retrieval**: Integrates Google Fact Check Tools API, Bing Search, and Wikipedia API.
- **Verdict & NLI Classification**: Evaluates claim-evidence entailment and confidence scoring using DeBERTa, Sentence-BERT, and ensemble verdict aggregation.
- **Plain-Language Explanations**: Generates concise, understandable explanations via Gemini Flash.
- **Twilio WhatsApp Integration**: Webhook support for real-time verification directly inside WhatsApp chats.

## 🛠 Directory Structure

```
backend/
├── main.py                        # FastAPI app — mounts all routers, middleware, health check
├── routers/
│   ├── webhook.py                 # POST /webhook/twilio — entry point for all Twilio messages
│   ├── verify.py                  # POST /verify — internal trigger for manual testing
│   └── health.py                  # GET /health
├── services/                      # Input, NLP, Retrieval, Verification, and Twilio services
├── pipelines/                     # Verification orchestration pipeline
├── middleware/                    # Rate limiter, Twilio signature validator, error handling
├── models/                        # Pydantic request and response models
├── schemas/                       # Database / SQLAlchemy schemas
├── lib/                           # Configuration and DB/Redis clients
└── requirements.txt               # Dependencies
```

## 💻 Getting Started

### Prerequisites

- Python 3.10+
- Redis (for rate limiting and caching)
- API Keys configured in `.env` (Twilio, Google Fact Check, Bing Search, Gemini API)

### Installation

1. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Configure environment variables in `.env`.

### Running the Application

```bash
uvicorn main:app --reload --port 8000
```

## 🧪 Testing

Run test suite:
```bash
pytest
```

