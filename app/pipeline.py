"""
End-to-end pipeline orchestrator (Wave 8).

Glues all seven layers together into a single synchronous function:
  IngestedMessage → NLPResult → ClaimResult[] → CheckResponse

Used by the FastAPI webhook handler to process an incoming WhatsApp message.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from app.contracts.models import CheckResponse, ClaimResult, IngestedMessage
from app.core.constants import Verdict
from app.core.config import settings
from app.core.timing import StageTimer
from app.core.cache import cache_get, cache_set
from app.features.explanation.formatter import format_whatsapp_reply, translate_reply_back
from app.features.explanation.generator import generate_explanation
from app.features.nlp.claims import extract_claims
from app.features.nlp.keywords import extract_keywords
from app.features.nlp.language import detect_language
from app.features.nlp.translation import translate_to_english
from app.features.nlp.worthiness import is_non_claim, score_check_worthiness
from app.features.verification.service import batch_verify_claims

logger = logging.getLogger(__name__)


def _derive_overall_verdict(claim_results: list[ClaimResult]) -> Verdict:
    """
    Combine per-claim verdicts into a single overall verdict.

    Rules (applied in priority order):
      - Any REFUTED claim             → overall REFUTED
      - Any OUTDATED claim            → overall OUTDATED
      - Any PARTIALLY_SUPPORTED claim → overall PARTIALLY_SUPPORTED
      - All SUPPORTED                 → overall SUPPORTED
      - Otherwise                     → UNVERIFIABLE
    """
    if not claim_results:
        return Verdict.UNVERIFIABLE

    verdicts = [r.verdict for r in claim_results]

    if Verdict.REFUTED in verdicts:
        return Verdict.REFUTED
    if Verdict.OUTDATED in verdicts:
        return Verdict.OUTDATED
    if Verdict.PARTIALLY_SUPPORTED in verdicts:
        return Verdict.PARTIALLY_SUPPORTED
    if all(v == Verdict.SUPPORTED for v in verdicts):
        return Verdict.SUPPORTED
    return Verdict.UNVERIFIABLE


def run_pipeline(message: IngestedMessage) -> CheckResponse:
    """
    Run the complete SatyaSetu fact-checking pipeline for one incoming message.

    Pipeline stages:
      1. Language detection
      2. Translation to English (if needed)
      3. Keyword extraction
      4. Claim extraction
      5. Check-worthiness scoring (filters low-signal inputs)
      6. Verification (retrieval + stance scoring + verdict)
      7. Explanation generation
      8. Reply formatting + back-translation

    Args:
        message: Validated IngestedMessage from the ingestion layer.

    Returns:
        CheckResponse ready to send back via Twilio.
    """
    t_start = time.monotonic()
    timings: dict[str, float] = {}

    # ── Stage 0: Cache Check (BUG-08) ────────────────────────────────────────────
    cached_data = cache_get(message.raw_text)
    if cached_data:
        try:
            cached_response = CheckResponse(**cached_data)
            cached_response.cached = True
            logger.info("Cache HIT for claim (%.60s)", message.raw_text)
            return cached_response
        except Exception as exc:
            logger.warning("Failed to deserialize cached response: %s", exc)

    # ── Stage 1: Language Detection ────────────────────────────────────────────
    with StageTimer("language_detection") as t:
        lang_code, lang_conf = detect_language(message.raw_text)
    timings["language_detection_ms"] = t.elapsed_ms
    logger.info("Detected language='%s' confidence=%.2f", lang_code, lang_conf)

    # ── Stage 2: Translation to English ────────────────────────────────────────
    with StageTimer("translation") as t:
        english_text, is_fallback = translate_to_english(
            text=message.raw_text,
            lang_code=lang_code,
        )
    timings["translation_ms"] = t.elapsed_ms
    if is_fallback:
        logger.info("Translation fallback — using original text for retrieval.")

    # ── Stage 3: Keyword Extraction ────────────────────────────────────────────
    with StageTimer("keyword_extraction") as t:
        keywords = extract_keywords(english_text)
    timings["keyword_extraction_ms"] = t.elapsed_ms

    # ── Stage 4: Claim Extraction ──────────────────────────────────────────────
    with StageTimer("claim_extraction") as t:
        raw_claims = extract_claims(english_text)
        claims = [c for c in raw_claims if not is_non_claim(c)][: settings.max_claims_per_message]
    timings["claim_extraction_ms"] = t.elapsed_ms
    logger.info("Extracted %d claims (capped at %d)", len(claims), settings.max_claims_per_message)

    # ── Stage 5: Check-Worthiness / Non-Claim Filtering ───────────────────────
    with StageTimer("worthiness_scoring") as t:
        worthiness_score = score_check_worthiness(english_text)
    timings["worthiness_ms"] = t.elapsed_ms

    # If the message is a greeting, opinion, pure question, or has no verifiable claims
    if not claims or is_non_claim(english_text):
        logger.info("Non-claim detected — returning standard prompt reply.")
        timings["total_ms"] = round((time.monotonic() - t_start) * 1000, 1)
        reply = "Only factual claims can be verified. Please share a forwarded message to check."
        return CheckResponse(
            claim_results=[],
            overall_verdict=Verdict.UNVERIFIABLE,
            explanation=reply,
            formatted_reply=reply,
            language=lang_code,
            timings_ms=timings,
            cached=False,
            flags=["non_claim"],
        )

    # BUG-09: worthiness gate — skip retrieval for very low-signal inputs
    if worthiness_score < 0.30 and not claims:
        logger.info("Low check-worthiness (%.2f) with no claims — short-circuiting.", worthiness_score)
        timings["total_ms"] = round((time.monotonic() - t_start) * 1000, 1)
        return CheckResponse(
            claim_results=[],
            overall_verdict=Verdict.UNVERIFIABLE,
            explanation="This message doesn't appear to contain a verifiable factual claim.",
            formatted_reply="❓ No verifiable claim found in this message. Please forward a factual claim to check.",
            language=lang_code,
            timings_ms=timings,
            cached=False,
            flags=["low_worthiness"],
        )

    # ── Stage 6: Verification ─────────────────────────────────────────────────
    with StageTimer("verification") as t:
        claim_results = batch_verify_claims(
            claims=claims,
            keywords=keywords,
            budget_ms=settings.retrieval_budget_ms,
        )
    timings["verification_ms"] = t.elapsed_ms

    overall_verdict = _derive_overall_verdict(claim_results)

    # ── Stage 7: Explanation Generation ───────────────────────────────────────
    with StageTimer("explanation") as t:
        # Use the most important (refuted/outdated/partially supported) claim result for explanation
        primary_result = (
            next(
                (r for r in claim_results if r.verdict in (Verdict.REFUTED, Verdict.OUTDATED, Verdict.PARTIALLY_SUPPORTED)),
                claim_results[0] if claim_results else None,
            )
        )
        if primary_result:
            explanation = generate_explanation(primary_result)
        else:
            explanation = "Unable to generate an explanation for this message."
    timings["explanation_ms"] = t.elapsed_ms

    all_flags = list(dict.fromkeys(f for r in claim_results for f in r.flags))

    # ── Stage 8: Formatting + Back-Translation ─────────────────────────────────
    with StageTimer("formatting") as t:
        draft_response = CheckResponse(
            claim_results=claim_results,
            overall_verdict=overall_verdict,
            explanation=explanation,
            formatted_reply="",  # filled below
            language=lang_code,
            timings_ms=timings,
            cached=False,
            flags=all_flags,
        )
        english_reply = format_whatsapp_reply(draft_response)
        final_reply = translate_reply_back(
            english_reply=english_reply,
            target_lang=lang_code,
        )
    timings["formatting_ms"] = t.elapsed_ms

    timings["total_ms"] = round((time.monotonic() - t_start) * 1000, 1)
    logger.info(
        "Pipeline complete: verdict=%s total_ms=%.0f claims=%d",
        overall_verdict,
        timings["total_ms"],
        len(claim_results),
    )

    final_response = CheckResponse(
        claim_results=claim_results,
        overall_verdict=overall_verdict,
        explanation=explanation,
        formatted_reply=final_reply,
        language=lang_code,
        timings_ms=timings,
        cached=False,
        flags=all_flags,
    )

    # BUG-08: persist to cache for subsequent identical claims
    try:
        cache_set(message.raw_text, final_response.model_dump())
    except Exception as exc:
        logger.warning("Failed to cache pipeline result: %s", exc)

    # MISSING-05: persist to SQLite claims log for admin dashboard
    try:
        from app.db.claims_db import log_claim
        log_claim(
            raw_text=message.raw_text,
            input_type=str(message.input_type.value if hasattr(message.input_type, "value") else message.input_type),
            from_number_hash=message.from_number,
            language=lang_code,
            overall_verdict=str(overall_verdict.value if hasattr(overall_verdict, "value") else overall_verdict),
            confidence=float(claim_results[0].confidence if claim_results else 0.0),
            explanation=explanation,
            claim_results=[c.model_dump() for c in claim_results],
            timings=timings,
            cached=False,
        )
    except Exception as exc:
        logger.warning("Failed to log claim to DB: %s", exc)

    return final_response
