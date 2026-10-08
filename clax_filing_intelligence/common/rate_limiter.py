"""
Global SEC Token-Bucket Rate Limiter (§3, Parallelization & SEC Fair-Access Compliance)

Thread-safe process-wide token bucket rate limiter to guarantee that combined requests across all worker threads
never exceed the SEC EDGAR fair-access limit (10 requests/second per IP).

Target default rate ceiling: 8.0 requests/second with a burst capacity of 8 tokens.
"""

import time
import threading
import logging

log = logging.getLogger("clax.ratelimit")


class TokenBucket:
    """
    Thread-safe Token Bucket Rate Limiter.
    
    Guarantees process-wide request throttling across concurrent worker threads.
    """
    def __init__(self, rate_per_sec: float = 8.0, burst: int = 8):
        self._rate = rate_per_sec
        self._capacity = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tag: str = "") -> None:
        """
        Blocks until a token is available.
        Logs a DEBUG line if the thread had to wait longer than 50 ms.
        """
        waited = 0.0
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                self._last = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    if waited > 0.05:
                        log.debug(f"rate-limit wait {waited:.3f}s tag={tag}")
                    return
                
                # Calculate sleep required for 1.0 token
                sleep_for = (1.0 - self._tokens) / self._rate

            time.sleep(sleep_for)
            waited += sleep_for


# Process-wide singleton instance shared across all worker threads
SEC_LIMITER = TokenBucket(rate_per_sec=8.0, burst=8)
