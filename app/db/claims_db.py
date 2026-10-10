"""
SQLite claim logging storage using standard library sqlite3 (zero external dependencies).
Persists incoming claims and pipeline results for admin dashboard queries (MISSING-05 / BUG-18).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DB_PATH = Path("data/claims.db")
_lock = threading.Lock()


def init_db() -> None:
    """Initialize SQLite database and create claims table if not exists."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS claim_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    input_type TEXT NOT NULL,
                    from_number_hash TEXT NOT NULL,
                    language TEXT NOT NULL,
                    overall_verdict TEXT NOT NULL,
                    confidence REAL DEFAULT 0.0,
                    explanation TEXT,
                    claim_results_json TEXT,
                    timings_json TEXT,
                    cached INTEGER DEFAULT 0
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_verdict ON claim_logs(overall_verdict);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_created_at ON claim_logs(created_at);
                """
            )
            conn.commit()
            conn.close()
            logger.info("Initialized claims SQLite database at %s", DB_PATH)
        except Exception as exc:
            logger.warning("Failed to initialize SQLite database: %s", exc)


def log_claim(
    raw_text: str,
    input_type: str,
    from_number_hash: str,
    language: str,
    overall_verdict: str,
    confidence: float = 0.0,
    explanation: str = "",
    claim_results: Optional[List[Dict[str, Any]]] = None,
    timings: Optional[Dict[str, float]] = None,
    cached: bool = False,
) -> None:
    """Persist a processed claim to SQLite in a thread-safe manner."""
    now_iso = datetime.now(timezone.utc).isoformat()
    claim_results_str = json.dumps(claim_results or [])
    timings_str = json.dumps(timings or {})

    with _lock:
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO claim_logs (
                    created_at, raw_text, input_type, from_number_hash,
                    language, overall_verdict, confidence, explanation,
                    claim_results_json, timings_json, cached
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_iso,
                    raw_text,
                    input_type,
                    from_number_hash,
                    language,
                    overall_verdict,
                    confidence,
                    explanation,
                    claim_results_str,
                    timings_str,
                    1 if cached else 0,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("Failed to log claim to SQLite: %s", exc)


def query_stats() -> Dict[str, Any]:
    """Return claim volume, verdict breakdown, and avg processing time."""
    with _lock:
        try:
            if not DB_PATH.exists():
                return {"total_processed": 0, "verdict_distribution": {}, "avg_pipeline_ms": 0}

            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()

            cur.execute("SELECT COUNT(*) FROM claim_logs")
            total = cur.fetchone()[0]

            cur.execute("SELECT overall_verdict, COUNT(*) FROM claim_logs GROUP BY overall_verdict")
            verdicts = {row[0]: row[1] for row in cur.fetchall()}

            conn.close()
            return {
                "total_processed": total,
                "verdict_distribution": verdicts,
                "avg_pipeline_ms": 0,
            }
        except Exception as exc:
            logger.warning("Failed to query stats from SQLite: %s", exc)
            return {"total_processed": 0, "verdict_distribution": {}, "avg_pipeline_ms": 0}


def query_claims(
    page: int = 1,
    limit: int = 20,
    verdict: Optional[str] = None,
) -> Tuple[int, List[Dict[str, Any]]]:
    """Return paginated list of claim logs."""
    offset = (page - 1) * limit
    with _lock:
        try:
            if not DB_PATH.exists():
                return 0, []

            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            if verdict:
                cur.execute("SELECT COUNT(*) FROM claim_logs WHERE overall_verdict = ?", (verdict,))
                total = cur.fetchone()[0]
                cur.execute(
                    "SELECT * FROM claim_logs WHERE overall_verdict = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (verdict, limit, offset),
                )
            else:
                cur.execute("SELECT COUNT(*) FROM claim_logs")
                total = cur.fetchone()[0]
                cur.execute(
                    "SELECT * FROM claim_logs ORDER BY id DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )

            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return total, rows
        except Exception as exc:
            logger.warning("Failed to query claims from SQLite: %s", exc)
            return 0, []


def update_claim_verdict(claim_id: int, new_verdict: str) -> bool:
    """Update verdict of an existing claim log."""
    with _lock:
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                "UPDATE claim_logs SET overall_verdict = ? WHERE id = ?",
                (new_verdict, claim_id),
            )
            conn.commit()
            updated = cur.rowcount > 0
            conn.close()
            return updated
        except Exception as exc:
            logger.warning("Failed to update claim verdict in SQLite: %s", exc)
            return False
