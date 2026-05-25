from dataclasses import dataclass


@dataclass(frozen=True)
class CrawlTask:
    """Immutable unit of work passed through the crawl queue.

    Attributes:
        url: Absolute URL of the page to fetch.
        priority: Scheduling priority; lower values are dequeued first (min-heap).
        depth: Number of hops from the nearest seed URL.
    """

    url: str
    priority: int = 0
    depth: int = 0
