import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles

from crawler.storage.base import DataStorage


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class JSONStorage(DataStorage):
    """Stores crawled pages as JSON Lines — one JSON object per line.

    Chosen format rationale: JSON Lines supports append-only writes without reading
    the existing file. A standard JSON array would require reading and rewriting the
    entire file on every save, which breaks for large crawls.

    Idempotency: re-running the crawler on the same path appends duplicate lines.
    This is intentional and documented — callers control file lifecycle.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def save(self, data: dict[str, Any]) -> None:
        line = json.dumps(data, default=_json_default, ensure_ascii=False)
        async with aiofiles.open(self._path, mode="a", encoding="utf-8") as f:
            await f.write(line + "\n")

    async def close(self) -> None:
        pass
