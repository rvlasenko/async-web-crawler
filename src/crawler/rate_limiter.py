import asyncio
import logging
import random
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class RateLimiter:
    _GLOBAL_KEY = "__global__"

    def __init__(
        self,
        requests_per_second: float | None = 1.0,
        min_delay: float | None = None,
        jitter: float = 0.0,
        per_domain: bool = True,
    ) -> None:
        self.requests_per_second = requests_per_second
        self.min_delay = min_delay
        self.jitter = jitter
        self.per_domain = per_domain

        self._validate_params()

        if min_delay is not None:
            self._min_interval = min_delay
        elif requests_per_second is not None:
            self._min_interval = 1.0 / requests_per_second
        else:
            self._min_interval = 0.0

        self._last_times: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._domain_delays: dict[str, float] = {}

    def update_domain_delay(self, domain: str, min_delay: float) -> None:
        """Register a per-domain minimum delay (e.g. from robots.txt Crawl-delay).

        Only increases the delay — never lowers it below what was already set.
        The effective interval used in acquire() is max(_min_interval, domain delay).
        """
        key = self._resolve_key(domain)
        if min_delay > self._domain_delays.get(key, 0.0):
            self._domain_delays[key] = min_delay

    async def acquire(self, domain: str | None = None) -> None:
        key = self._resolve_key(domain)

        # Lazy lock creation is safe here: no `await` between the check and
        # the assignment, so no other coroutine can interleave in this window.
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()

        effective_interval = max(self._min_interval, self._domain_delays.get(key, 0.0))

        async with self._locks[key]:
            now = time.monotonic()
            last = self._last_times.get(key, 0.0)
            sleep_for = max(0.0, last + effective_interval - now)

            if self.jitter > 0:
                sleep_for += random.uniform(0, self.jitter)

            if sleep_for > 0:
                logger.debug("Rate limiting %s: sleeping %.3fs", key, sleep_for)
                await asyncio.sleep(sleep_for)

            self._last_times[key] = time.monotonic()

    def _validate_params(self) -> None:
        if self.requests_per_second is not None and self.min_delay is not None:
            raise ValueError(
                "Specify either requests_per_second or min_delay, not both"
            )
        if self.requests_per_second is not None and self.requests_per_second <= 0:
            raise ValueError(
                f"requests_per_second must be positive, got {self.requests_per_second}"
            )
        if self.min_delay is not None and self.min_delay <= 0:
            raise ValueError(f"min_delay must be positive, got {self.min_delay}")
        if self.jitter < 0:
            raise ValueError(f"jitter must be non-negative, got {self.jitter}")

    def _resolve_key(self, domain: str | None) -> str:
        if not self.per_domain or domain is None:
            return self._GLOBAL_KEY

        parsed = urlparse(domain)
        key = (parsed.netloc or parsed.path).lower().strip()

        if not key:
            raise ValueError("domain must not be empty")

        return key
