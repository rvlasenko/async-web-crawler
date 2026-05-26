from abc import ABC, abstractmethod
from typing import Any


class DataStorage(ABC):
    """Abstract base for all storage backends.

    Each backend must implement save() and close(). Supports async context manager
    so resources (file handles, DB connections) are always released::

        async with JSONStorage("results.jsonl") as storage:
            await storage.save(page_data)
    """

    @abstractmethod
    async def save(self, data: dict[str, Any]) -> None:
        """Persist one crawled page record."""

    @abstractmethod
    async def close(self) -> None:
        """Release any held resources (file handles, DB connections, flush buffers)."""

    async def __aenter__(self) -> "DataStorage":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()
