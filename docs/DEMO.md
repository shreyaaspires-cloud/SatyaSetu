# SatyaSetu Demo & Evaluation Guide

This guide describes how judges and evaluators can verify claims using SatyaSetu via the web UI, the direct REST API, or WhatsApp.

---

## 1. Web Demo Interface (No Twilio Sandbox Required)

For live evaluation and judges without access to the WhatsApp sandbox:
1. Start the server:
   ```bash
   uvicorn main:app --port 8000
   ```
2. Open your browser and navigate to:
   - **`http://localhost:8000/demo`** (or `http://localhost:8000/check`)
3. Paste any forwarded claim or news snippet into the input area.
4. Click **"Verify Claim"**.
5. The UI displays the categorized verdict badge (`SUPPORTED`, `REFUTED`, `PARTIALLY_SUPPORTED`, `OUTDATED`, `UNVERIFIABLE`) and the formatted multilingual response preview.

---

## 2. Programmatic API Endpoint (`POST /api/check`)

Judges and benchmark scripts can programmatically verify claims via JSON:

### Request
```http
POST /api/check HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "text": "Drinking lemon water cures cancer completely in 5 days."
}
```

### Response
```json
{
  "verdict": "REFUTED",
  "explanation": "Scientific evidence and health organizations show lemon water does not cure cancer.",
  "formatted_reply": "*VERDICT: REFUTED*\n\nDrinking lemon water does not cure cancer...",
  "claim_results": [...],
  "flags": [],
  "timings_ms": {
    "total_ms": 320.5
  }
}
```

---

## 3. WhatsApp Twilio Webhook (`POST /webhook/twilio`)

Inbound WhatsApp messages are received via Twilio:
- **Immediate Acknowledgement:** Returns `<Response><Message>Checking this, one moment...</Message></Response>` in < 2 seconds to comply with Twilio's webhook timeout (15s limit).
- **Background Pipeline:** Processes the multi-source verification asynchronously and sends the final answer via Twilio REST API.
- **Deduplication:** Automatic `MessageSid` deduplication ensures retried webhooks do not trigger duplicate LLM / retrieval pipeline runs.
