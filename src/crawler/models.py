from dataclasses import dataclass


@dataclass(frozen=True)
class CrawlTask:
    url: str
    priority: int = 0
    depth: int = 0
