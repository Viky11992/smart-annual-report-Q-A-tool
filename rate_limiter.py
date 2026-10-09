"""
rate_limiter.py
Token-per-minute (TPM) rate limiter using a sliding 60-second window.
Keeps LLM token usage strictly below the configured threshold (default: 7500 TPM).
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque


class TokenRateLimiter:
    """
    Thread-safe sliding window token rate limiter.
    Ensures that total tokens used in any rolling 60-second window
    never exceeds `max_tpm` (default: 7500).
    """

    def __init__(self, max_tpm: int = 7500, window_seconds: float = 60.0):
        self.max_tpm = max_tpm
        self.window_seconds = window_seconds
        self._history: deque[tuple[float, int]] = deque()
        self._lock = threading.Lock()

    def _purge_old_entries(self, now: float) -> None:
        """Remove entries older than the rolling window."""
        cutoff = now - self.window_seconds
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

    def get_current_window_tokens(self) -> int:
        """Return total tokens consumed in the current rolling window."""
        now = time.time()
        with self._lock:
            self._purge_old_entries(now)
            return sum(tokens for _, tokens in self._history)

    def wait_for_capacity(self, estimated_tokens: int) -> None:
        """
        Block/sleep until there is enough capacity in the rolling window
        to accommodate `estimated_tokens` without exceeding `max_tpm`.
        If estimated_tokens alone is larger than max_tpm, wait until the
        current window is completely drained so it executes cleanly.
        """
        # Clamp target check so single-call overhead doesn't deadlock
        target_tokens = min(estimated_tokens, self.max_tpm)

        while True:
            with self._lock:
                now = time.time()
                self._purge_old_entries(now)
                current_tokens = sum(tokens for _, tokens in self._history)

                # If window has space for this request, allow immediately
                if current_tokens + target_tokens <= self.max_tpm:
                    return

                # If window is full, wait until oldest entry drops out
                if self._history:
                    oldest_ts, _ = self._history[0]
                    sleep_time = (oldest_ts + self.window_seconds) - now + 0.1
                else:
                    # Window is already empty, proceed
                    return

            if sleep_time > 0:
                time.sleep(sleep_time)

    def record_usage(self, tokens_used: int) -> None:
        """Record the actual tokens used by an API call."""
        now = time.time()
        with self._lock:
            self._purge_old_entries(now)
            self._history.append((now, tokens_used))


# Global rate limiter instance configured to stay strictly under 7500 TPM
# (Configurable via MAX_TPM env var, defaults to 7500)
_DEFAULT_MAX_TPM = int(os.environ.get("MAX_TPM", "7500"))
limiter = TokenRateLimiter(max_tpm=_DEFAULT_MAX_TPM)


def estimate_prompt_tokens(prompt: str, extra_overhead: int = 500) -> int:
    """
    Approximation of tokens (~4 chars per token + modest system/output buffer).
    """
    approx_input_tokens = int(len(prompt) / 4.0) + 50
    return approx_input_tokens + extra_overhead

