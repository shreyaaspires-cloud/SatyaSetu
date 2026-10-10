"""
WhatsApp reply formatter (Wave 7).

Converts the overall CheckResponse data into a tightly-formatted WhatsApp
message string, then translates it back to the user's source language.

WhatsApp character limit: 4096 chars per message (hard cap respected here).
Max safe reply length we target: 1500 chars (comfortable on mobile screens).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

from app.contracts.models import CheckResponse, ClaimResult
from app.core.config import settings
from app.core.constants import Verdict

logger = logging.getLogger(__name__)

# ── Labels Cache (from config/labels.yaml) ────────────────────────────────────

_LABELS_CACHE: Dict[str, Any] = {}


def _load_labels() -> Dict[str, Any]:
    """Load config/labels.yaml into memory with caching."""
    global _LABELS_CACHE
    if not _LABELS_CACHE:
        labels_file = Path("config/labels.yaml")
        if labels_file.exists():
            with open(labels_file, "r", encoding="utf-8") as f:
                _LABELS_CACHE = yaml.safe_load(f) or {}
    return _LABELS_CACHE


def get_verdict_label(verdict: Verdict, lang: str = "en") -> str:
    """Return hardcoded localized verdict label from labels.yaml."""
    labels = _load_labels()
    lang_code = lang.split("-")[0].lower() if lang else "en"
    lang_dict = labels.get(lang_code, labels.get("en", {}))
    verdicts = lang_dict.get("verdicts", {})
    return verdicts.get(verdict.value, VERDICT_LABEL.get(verdict, verdict.value))


def get_ui_string(key: str, lang: str = "en") -> str:
    """Return hardcoded localized UI phrase from labels.yaml."""
    labels = _load_labels()
    lang_code = lang.split("-")[0].lower() if lang else "en"
    lang_dict = labels.get(lang_code, labels.get("en", {}))
    ui = lang_dict.get("ui", {})
    default_ui = labels.get("en", {}).get("ui", {})
    return ui.get(key, default_ui.get(key, key))


# ── Constants ──────────────────────────────────────────────────────────────────

VERDICT_EMOJI: dict = {
    Verdict.SUPPORTED: "✅",
    Verdict.REFUTED: "❌",
    Verdict.PARTIALLY_SUPPORTED: "⚠️",
    Verdict.OUTDATED: "⏳",
    Verdict.UNVERIFIABLE: "❓",
}

VERDICT_LABEL: dict = {
    Verdict.SUPPORTED: "SUPPORTED",
    Verdict.REFUTED: "REFUTED",
    Verdict.PARTIALLY_SUPPORTED: "PARTIALLY_SUPPORTED",
    Verdict.OUTDATED: "OUTDATED",
    Verdict.UNVERIFIABLE: "UNVERIFIABLE",
}

MAX_REPLY_LEN = 1400          # Soft cap — trim if exceeded
WHATSAPP_HARD_CAP = 4096      # Hard WhatsApp limit


def compute_evidence_strength(evidence: List[Any]) -> tuple[str, str]:
    """
    Computes (strength_label, detail_str) based on evidence tiers and count.

    | Label | Condition |
    | Strong | >= 2 independent Tier 1-3 sources agree |
    | Moderate | 1 Tier 1-3 source, or >= 2 Tier 4 sources |
    | Limited | Only Tier 4-5 sources, or 1 source total |
    | Insufficient | No decisive sources found |
    """
    from app.core.constants import Tier

    if not evidence:
        return "Insufficient", "No decisive sources found"

    tier1_3_domains = set()
    tier4_domains = set()
    tier5_domains = set()

    for item in evidence:
        domain = getattr(item, "source_domain", "") or getattr(item, "url", "")
        if not domain:
            continue
        tier = getattr(item, "tier", None)
        if tier in (Tier.TIER_1_IFCN, Tier.TIER_2_GOV_PIB, Tier.TIER_3_MAINSTREAM):
            tier1_3_domains.add(domain)
        elif tier == Tier.TIER_4_WIKIPEDIA:
            tier4_domains.add(domain)
        else:
            tier5_domains.add(domain)

    t13_count = len(tier1_3_domains)
    t4_count = len(tier4_domains)
    total_sources = len(tier1_3_domains | tier4_domains | tier5_domains)

    if t13_count >= 2:
        return "Strong", f"{t13_count} official sources agree"
    elif t13_count == 1:
        return "Moderate", "1 official source found"
    elif t4_count >= 2:
        return "Moderate", f"{t4_count} reference sources agree"
    elif total_sources == 1:
        return "Limited", "1 source found"
    elif total_sources > 1 and (tier4_domains or tier5_domains):
        return "Limited", f"{total_sources} web sources found"
    else:
        return "Insufficient", "No decisive sources found"


def _format_single_claim(result: ClaimResult, idx: int, total: int, lang: str = "en") -> str:
    """Format one ClaimResult as a readable block using fixed labels."""
    emoji = VERDICT_EMOJI.get(result.verdict, "❓")
    label = get_verdict_label(result.verdict, lang)
    strength_label, strength_detail = compute_evidence_strength(result.evidence)
    ev_strength_prefix = get_ui_string("evidence_strength", lang)

    header = f"*Claim {idx}/{total}:* {result.claim[:120].strip()}"
    verdict_line = f"{emoji} *{label}*"
    strength_line = f"{ev_strength_prefix}: {strength_label} · {strength_detail}"

    # Pick the top evidence items as source cites
    sources: List[str] = []
    if result.evidence:
        top = sorted(result.evidence, key=lambda e: -e.score)
        for ev in top[:2]:
            if ev.url and ev.source_domain:
                sources.append(f"• {ev.source_domain}: {ev.url[:80]}")

    source_block = "\n".join(sources) if sources else f"• {get_ui_string('sources', lang)}: N/A"

    parts = [header, verdict_line, strength_line, source_block]
    return "\n".join(parts)


def translate_explanation_paragraph(text: str, target_lang: str) -> str:
    """
    Translate only the free-text explanation paragraph using Gemini.
    Verdict labels, fixed phrases, and citations NEVER pass through machine translation.
    """
    if not target_lang or target_lang.startswith("en") or not text.strip():
        return text

    if not settings.gemini_api_key:
        return text

    try:
        from google import genai
        from app.core.redaction import redact_for_external

        client = genai.Client(api_key=settings.gemini_api_key)
        prompt = (
            f"Translate the following fact-check explanation into language '{target_lang}'. "
            "Output ONLY the translated paragraph text without commentary or markdown headers:\n\n"
            f"{redact_for_external(text)}"
        )
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )
        if response and response.text:
            return response.text.strip()
    except Exception as exc:
        logger.warning("Explanation paragraph translation failed for '%s': %s", target_lang, exc)

    return text


def format_whatsapp_reply(response: CheckResponse) -> str:
    """
    Build a complete WhatsApp reply string from a CheckResponse.
    Uses hardcoded labels from labels.yaml and provides honest translation fallback.
    """
    lang = (getattr(response, "language", "") or "en").split("-")[0].lower()
    divider = "─" * 25

    header_parts = [
        "🔍 *SatyaSetu Fact Check*",
        divider,
    ]

    # Claim echo line
    if response.claim_results:
        echo_label = get_ui_string("claim_echo", lang)
        claim_snippet = response.claim_results[0].claim[:120].strip()
        header_parts.append(f"*{echo_label}:* \"{claim_snippet}\"")
        header_parts.append(divider)

    claim_blocks: List[str] = []
    total = len(response.claim_results)
    for idx, result in enumerate(response.claim_results, 1):
        claim_blocks.append(_format_single_claim(result, idx, total, lang=lang))

    overall_emoji = VERDICT_EMOJI.get(response.overall_verdict, "❓")
    overall_label = get_verdict_label(response.overall_verdict, lang)

    # Free-text explanation handling (allow up to 1000 chars without mid-word truncation)
    explanation_raw = response.explanation[:1000].strip()
    if len(response.explanation) > 1000:
        explanation_raw += "…"

    translation_unavailable_line: Optional[str] = None
    if lang != "en":
        if settings.gemini_api_key:
            explanation_excerpt = translate_explanation_paragraph(explanation_raw, lang)
        else:
            explanation_excerpt = explanation_raw
            translation_unavailable_line = get_ui_string("translation_unavailable", lang)
    else:
        explanation_excerpt = explanation_raw

    footer_parts = [
        divider,
        f"*Overall:* {overall_emoji} {overall_label}",
        explanation_excerpt,
    ]

    if translation_unavailable_line:
        footer_parts.append(f"ℹ️ {translation_unavailable_line}")

    footer_parts.extend([
        divider,
        "_SatyaSetu — AI-powered multilingual fact checking_",
    ])

    # BUG-17: was wrapping claim_blocks in a list which caused no leading/trailing
    # newlines around the claim section, making it run into dividers.
    claim_section = ("\n\n" + divider + "\n\n").join(claim_blocks)
    all_lines = header_parts + [claim_section] + footer_parts
    reply = "\n".join(all_lines)

    # Safety trim
    if len(reply) > MAX_REPLY_LEN:
        reply = reply[:MAX_REPLY_LEN - 3] + "…"

    if len(reply) > WHATSAPP_HARD_CAP:
        reply = reply[:WHATSAPP_HARD_CAP - 3] + "…"

    return reply


def translate_reply_back(
    english_reply: str,
    target_lang: str,
) -> str:
    """
    Translate a formatted English reply back to the user's source language.

    Only structural text (non-URL, non-emoji, non-domain lines) is translated.
    WhatsApp bold markers (*word*) are preserved.

    Falls back to the English reply if translation is unavailable.

    Args:
        english_reply: The English-formatted reply string.
        target_lang:   BCP-47 language code (e.g. 'hi', 'mr', 'ta').

    Returns:
        Translated reply string, or the original English if translation fails.
    """
    if not target_lang or target_lang.startswith("en"):
        return english_reply

    if not english_reply.strip():
        return english_reply

    try:
        # English → Indic translation uses Gemini only (M2M100 is Indic→English only)
        from app.core.config import settings as cfg

        if not cfg.gemini_api_key:
            logger.info("No Gemini key — returning English reply.")
            return english_reply

        from google import genai
        from app.core.redaction import redact_for_external

        redacted_reply = redact_for_external(english_reply)
        client = genai.Client(api_key=cfg.gemini_api_key)
        prompt = (
            f"Translate the following WhatsApp fact-check reply into language code '{target_lang}'. "
            "Preserve all *bold* markers, emojis, and URLs exactly as-is. "
            "Output ONLY the translated text:\n\n"
            f"{redacted_reply}"
        )
        response = client.models.generate_content(
            model=cfg.gemini_model,
            contents=prompt,
        )
        if response and response.text:
            translated = response.text.strip()
            # Respect WhatsApp hard cap after translation
            if len(translated) > WHATSAPP_HARD_CAP:
                translated = translated[:WHATSAPP_HARD_CAP - 3] + "…"
            return translated

    except Exception as exc:
        logger.warning("Reply back-translation to '%s' failed: %s", target_lang, exc)

    return english_reply
