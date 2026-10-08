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
from app.features.explanation.formatter import format_whatsapp_reply, translate_reply_back
from app.features.explanation.generator import generate_explanation
from app.features.nlp.claims import extract_claims
from app.features.nlp.keywords import extract_keywords
from app.features.nlp.language import detect_language
from app.features.nlp.translation import translate_to_english
from app.features.nlp.worthiness import score_check_worthiness
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
        # Cap at configured maximum
        claims = raw_claims[: settings.max_claims_per_message]
    timings["claim_extraction_ms"] = t.elapsed_ms
    logger.info("Extracted %d claims (capped at %d)", len(claims), settings.max_claims_per_message)

    # ── Stage 5: Check-Worthiness Filtering ───────────────────────────────────
    with StageTimer("worthiness_scoring") as t:
        worthiness_score = score_check_worthiness(english_text)
    timings["worthiness_ms"] = t.elapsed_ms

    # If the message is a greeting, question, or otherwise not fact-checkable
    if worthiness_score < 0.1 and not claims:
        logger.info("Low check-worthiness (%.2f) with no claims — short-circuit.", worthiness_score)
        reply = (
            "👋 *SatyaSetu* here!\n\n"
            "Please send me a claim, forward, or news item you'd like fact-checked."
        )
        return CheckResponse(
            claim_results=[],
            overall_verdict=Verdict.UNVERIFIABLE,
            explanation="No verifiable claims detected in this message.",
            formatted_reply=reply,
            language=lang_code,
            timings_ms=timings,
            cached=False,
        )

    # If no claims extracted but text is long enough, treat the full text as claim
    if not claims and english_text.strip():
        claims = [english_text.strip()[:300]]

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

    return CheckResponse(
        claim_results=claim_results,
        overall_verdict=overall_verdict,
        explanation=explanation,
        formatted_reply=final_reply,
        language=lang_code,
        timings_ms=timings,
        cached=False,
        flags=all_flags,
    )
