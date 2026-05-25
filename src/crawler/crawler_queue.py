import asyncio
from itertools import count

from crawler.models import CrawlTask


class CrawlerQueue:
    """Async priority queue that tracks URL lifecycle: pending → active → done/failed.

    Deduplicates across all lifecycle stages so a URL is never enqueued twice,
    regardless of whether it is waiting, being fetched, already processed, or failed.
    """

    def __init__(self) -> None:
        self.queue: asyncio.PriorityQueue[tuple[int, int, CrawlTask]] = (
            asyncio.PriorityQueue()
        )
        self._sequence = count()
        self._queued_urls: set[str] = set()
        self._active_urls: set[str] = set()

        self.processed_urls: set[str] = set()
        self.failed_urls: dict[str, str] = {}

    def add_url(
        self,
        url: str,
        priority: int = 0,
        depth: int = 0,
    ) -> None:
        """Enqueue a URL if it has not been seen in any lifecycle stage.

        Args:
            url: Absolute URL to crawl.
            priority: Lower value means higher priority (min-heap ordering).
            depth: Crawl depth of this URL relative to the seed.
        """
        if not self._can_enqueue(url):
            return

        task = CrawlTask(
            url=url,
            priority=priority,
            depth=depth,
        )

        sequence = next(self._sequence)

        self.queue.put_nowait((priority, sequence, task))
        self._queued_urls.add(url)

    async def get_next(self) -> CrawlTask | None:
        if self.queue.empty():
            return None

        _, _, task = await self.queue.get()
        self._queued_urls.discard(task.url)
        self._active_urls.add(task.url)

        return task

    def mark_processed(self, url: str) -> None:
        self._active_urls.discard(url)
        self.processed_urls.add(url)

    def mark_failed(self, url: str, error: str) -> None:
        self._active_urls.discard(url)
        self.failed_urls[url] = error

    def get_stats(self) -> dict[str, int]:
        return {
            "queued": len(self._queued_urls),
            "processed": len(self.processed_urls),
            "failed": len(self.failed_urls),
        }

    def _can_enqueue(self, url: str) -> bool:
        return (
            url not in self._queued_urls
            and url not in self._active_urls
            and url not in self.processed_urls
            and url not in self.failed_urls
        )
