import asyncio
import logging
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class RateLimiter:
    _GLOBAL_KEY = "__global__"

    def __init__(
        self,
        requests_per_second: float = 1.0,
        per_domain: bool = True,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError(
                f"requests_per_second must be positive, got {requests_per_second}"
            )

        self.requests_per_second = requests_per_second
        self.per_domain = per_domain
        self._min_interval = 1.0 / requests_per_second

        self._last_times: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def acquire(self, domain: str | None = None) -> None:
        key = self._resolve_key(domain)

        # Lazy lock creation is safe here: no `await` between the check and
        # the assignment, so no other coroutine can interleave in this window.
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()

        async with self._locks[key]:
            now = time.monotonic()
            last = self._last_times.get(key, 0.0)
            sleep_for = max(0.0, last + self._min_interval - now)

            if sleep_for > 0:
                logger.debug("Rate limiting %s: sleeping %.3fs", key, sleep_for)
                await asyncio.sleep(sleep_for)

            self._last_times[key] = time.monotonic()

    def _resolve_key(self, domain: str | None) -> str:
        if not self.per_domain or domain is None:
            return self._GLOBAL_KEY

        parsed = urlparse(domain)
        key = (parsed.netloc or parsed.path).lower().strip()

        if not key:
            raise ValueError("domain must not be empty")

        return key
