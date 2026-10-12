"""
WhatsApp reply formatter (Wave 7 / Simplified Card Layout).

Converts CheckResponse into a clean, human-readable WhatsApp message:
- One verdict word, truth score (0-10), one claim line, 1-2 sentence why, at most two source domains.
- Total length under 600 characters.
- Multi-lingual localization via labels.yaml.
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
    """Return localized canonical verdict label."""
    labels = _load_labels()
    lang_code = lang.split("-")[0].lower() if lang else "en"
    lang_dict = labels.get(lang_code, labels.get("en", {}))
    verdicts = lang_dict.get("verdicts", {})
    return verdicts.get(verdict.value, VERDICT_LABEL.get(verdict, verdict.value))


def get_plain_verdict_label(verdict: Verdict, lang: str = "en") -> str:
    """Return plain-language verdict word (e.g. Fake, True, Half true)."""
    labels = _load_labels()
    lang_code = lang.split("-")[0].lower() if lang else "en"
    lang_dict = labels.get(lang_code, labels.get("en", {}))
    plain_verdicts = lang_dict.get("plain_verdicts", {})
    return plain_verdicts.get(verdict.value, PLAIN_VERDICT_LABEL.get(verdict, verdict.value))


def get_ui_string(key: str, lang: str = "en") -> str:
    """Return localized UI string from labels.yaml."""
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

PLAIN_VERDICT_LABEL: dict = {
    Verdict.SUPPORTED: "True",
    Verdict.REFUTED: "Fake",
    Verdict.PARTIALLY_SUPPORTED: "Half true",
    Verdict.OUTDATED: "Old news",
    Verdict.UNVERIFIABLE: "Can't confirm",
}

MAX_REPLY_LEN = 1200
WHATSAPP_HARD_CAP = 4096


def compute_truth_score(verdict: Verdict, confidence: float = 0.85) -> Optional[int]:
    """
    Compute deterministic truth score (0 to 10):
    | REFUTED | round((1 - confidence) * 10), clamped to 0 to 2 |
    | SUPPORTED | round(confidence * 10), clamped to 8 to 10 |
    | PARTIALLY_SUPPORTED | 5 |
    | OUTDATED | 3 |
    | UNVERIFIABLE | None |
    """
    if verdict == Verdict.REFUTED:
        raw = round((1.0 - confidence) * 10)
        return max(0, min(2, raw))
    elif verdict == Verdict.SUPPORTED:
        raw = round(confidence * 10)
        return max(8, min(10, raw))
    elif verdict == Verdict.PARTIALLY_SUPPORTED:
        return 5
    elif verdict == Verdict.OUTDATED:
        return 3
    elif verdict == Verdict.UNVERIFIABLE:
        return None
    return None


def compute_evidence_strength(evidence: List[Any]) -> tuple[str, str]:
    """
    Computes (strength_label, detail_str) based on evidence tiers and count.
    Preserved for web API backwards compatibility.
    """
    from app.core.constants import Tier

    if not evidence:
        return "Insufficient", "No decisive sources found"

    tier1_3_domains = set()
    tier4_domains = set()
    tier5_domains = set()

    for item in evidence:
        domain = getattr(item, "source_domain", "") or ""
        tier = getattr(item, "tier", None)
        if tier in (Tier.TIER_1_IFCN, Tier.TIER_2_GOV_PIB, Tier.TIER_3_MAINSTREAM):
            if domain:
                tier1_3_domains.add(domain)
        elif tier == Tier.TIER_4_WIKIPEDIA:
            if domain:
                tier4_domains.add(domain)
        elif tier == Tier.TIER_5_GENERAL_WEB:
            if domain:
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


def format_whatsapp_reply(response: CheckResponse) -> str:
    """
    Build concise WhatsApp reply (under 600 chars in standard cases).

    Example layout:
    ❌ *Fake*   Truth score: 1/10

    *Claim:* Lemon juice cures cancer in 48 hours

    *Why:* No study shows this. Skipping real treatment can be dangerous.

    *Check:* boomlive.in, who.int

    _Send this to whoever forwarded it._
    """
    lang = (getattr(response, "language", "") or "en").split("-")[0].lower()
    verdict = response.overall_verdict
    emoji = VERDICT_EMOJI.get(verdict, "❓")
    plain_label = get_plain_verdict_label(verdict, lang)

    # Calculate truth score from primary claim result
    confidence = 0.85
    if response.claim_results:
        confidence = response.claim_results[0].confidence

    score = compute_truth_score(verdict, confidence)

    # 1. Header line: Verdict + Score
    if score is not None:
        score_text = f"{get_ui_string('truth_score', lang)}: {score}/10"
    else:
        score_text = get_ui_string("no_score", lang)

    header = f"{emoji} *{plain_label}*   {score_text}"

    # 2. Claim block
    claim_label = get_ui_string("claim", lang)
    why_label = get_ui_string("why", lang)
    check_label = get_ui_string("check", lang)
    forward_hint = get_ui_string("forward_hint", lang)

    lines = [header, ""]

    # Multi-claim handling or single claim
    if len(response.claim_results) > 1:
        lines.append(f"*{claim_label}:* {response.claim_results[0].claim[:120].strip()}")
        for idx, cr in enumerate(response.claim_results[:2], 1):
            cr_emoji = VERDICT_EMOJI.get(cr.verdict, "❓")
            cr_plain = get_plain_verdict_label(cr.verdict, lang)
            lines.append(f"• {cr.claim[:70].strip()} ({cr_emoji} {cr_plain})")
    elif response.claim_results:
        lines.append(f"*{claim_label}:* {response.claim_results[0].claim[:140].strip()}")
    else:
        echo_label = get_ui_string("claim_echo", lang)
        lines.append(f"*{echo_label}:* \"{response.explanation[:120]}\"")

    lines.append("")

    # 3. Why (concise reason)
    reason = response.explanation.strip()
    # Strip any residual verbose prefixes
    for prefix in ["Verdict:", "Evidence strength:", "Evidence summary:"]:
        if prefix in reason:
            reason = reason.split("\n")[-1].strip()
    if not reason:
        reason = get_ui_string("no_score", lang)
    lines.append(f"*{why_label}:* {reason}")

    # 4. Check (domains)
    domains: List[str] = []
    seen = set()
    for cr in response.claim_results:
        for ev in cr.evidence:
            domain = ev.source_domain or ""
            if domain and domain.lower() not in seen:
                seen.add(domain.lower())
                domains.append(domain)
            if len(domains) >= 2:
                break
        if len(domains) >= 2:
            break

    if domains:
        lines.append("")
        lines.append(f"*{check_label}:* {', '.join(domains)}")

    # 5. Footer
    lines.append("")
    lines.append(f"_{forward_hint}_")

    reply = "\n".join(lines)

    # WhatsApp hard cap guard
    if len(reply) > WHATSAPP_HARD_CAP:
        reply = reply[:WHATSAPP_HARD_CAP - 3] + "…"

    return reply


def translate_reply_back(
    english_reply: str,
    target_lang: str,
) -> str:
    """
    Translate a formatted reply back to the user's source language.
    WhatsApp bold markers (*word*) and URLs are preserved.
    """
    if not target_lang or target_lang.startswith("en"):
        return english_reply

    if not english_reply.strip():
        return english_reply

    try:
        from app.core.config import settings as cfg

        if not cfg.gemini_api_key:
            return english_reply

        from google import genai
        from app.core.redaction import redact_for_external

        redacted_reply = redact_for_external(english_reply)
        client = genai.Client(api_key=cfg.gemini_api_key)
        prompt = (
            f"Translate the following WhatsApp fact-check reply into language code '{target_lang}'. "
            "Keep the reply concise, natural, and under 500 characters. "
            "Preserve all *bold* markers, emojis, domain names, and URLs exactly as-is. "
            "Output ONLY the translated text:\n\n"
            f"{redacted_reply}"
        )
        response = client.models.generate_content(
            model=cfg.gemini_model,
            contents=prompt,
        )
        if response and response.text:
            translated = response.text.strip()
            if len(translated) > WHATSAPP_HARD_CAP:
                translated = translated[:WHATSAPP_HARD_CAP - 3] + "…"
            return translated

    except Exception as exc:
        logger.warning("Reply back-translation to '%s' failed: %s", target_lang, exc)

    return english_reply
