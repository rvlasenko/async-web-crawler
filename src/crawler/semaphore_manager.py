import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse


class SemaphoreManager:
    def __init__(
        self,
        global_limit: int = 10,
        per_domain_limit: int = 5,
    ) -> None:
        self.global_semaphore = asyncio.Semaphore(global_limit)
        self.domain_semaphores: dict[str, asyncio.Semaphore] = {}

        self.per_domain_limit = per_domain_limit
        self._active_tasks_count = 0

    @asynccontextmanager
    async def acquire(self, url: str) -> AsyncIterator[None]:
        domain = self._get_domain_key(url)
        domain_semaphore = self.get_domain_semaphore(domain)

        async with self.global_semaphore:
            async with domain_semaphore:
                self._active_tasks_count += 1

                try:
                    yield
                finally:
                    self._active_tasks_count -= 1

    def get_domain_semaphore(self, domain: str) -> asyncio.Semaphore:
        normalized_domain = self._get_domain_key(domain)

        if normalized_domain not in self.domain_semaphores:
            self.domain_semaphores[normalized_domain] = asyncio.Semaphore(
                self.per_domain_limit
            )

        return self.domain_semaphores[normalized_domain]

    def get_active_tasks_count(self) -> int:
        return self._active_tasks_count

    def _get_domain_key(self, url_or_domain: str) -> str:
        parsed_url = urlparse(url_or_domain)
        domain = parsed_url.netloc or parsed_url.path
        normalized_domain = domain.lower().strip()

        if not normalized_domain:
            raise ValueError("URL or domain must not be empty")

        return normalized_domain
