"""
Execution timing utilities for monitoring pipeline stage latencies.
"""

import time
from typing import Optional


class StageTimer:
    """
    Context manager for measuring stage latency in milliseconds.

    Usage:
        with StageTimer("retrieval") as timer:
            perform_retrieval()
        print(timer.elapsed_ms)
    """

    def __init__(self, name: str = ""):
        self.name = name
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.elapsed_ms: float = 0.0

    def __enter__(self) -> "StageTimer":
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[object]) -> bool:
        self.end_time = time.perf_counter()
        self.elapsed_ms = round((self.end_time - self.start_time) * 1000.0, 2)
        return False
