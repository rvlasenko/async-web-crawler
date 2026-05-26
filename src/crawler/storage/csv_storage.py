import csv
import json
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

import aiofiles

from crawler.storage.base import DataStorage


def _serialize_value(value: Any) -> str:
    """Convert a field value to a CSV-safe string.

    - datetime  → ISO 8601 string
    - list/dict → JSON string (preserves structure, readable back with json.loads)
    - None      → empty string (CSV convention; distinguishable from the string "None")
    - anything else → str()
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return str(value)


class CSVStorage(DataStorage):
    """Stores crawled pages as rows in a CSV file.

    Header strategy: tracked via an in-memory flag (_header_written) initialised
    from the file state at construction time. The flag is set to True before the
    first await so concurrent save() calls cannot both decide to write the header —
    there is no yield point between the flag check and the flag set.

    A file-size check on every save() would have a race condition: two coroutines
    could both see an empty file before either writes, producing two header rows.

    Type note: CSV has no type system. Numeric fields like status_code are written
    as strings and read back as strings. Callers must cast explicitly, e.g.
    int(row["status_code"]).

    Complex fields (links, metadata) are JSON-encoded into a single cell.
    Read them back with json.loads().
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._header_written: bool = self._path.exists() and self._path.stat().st_size > 0

    async def save(self, data: dict[str, Any]) -> None:
        write_header = not self._header_written
        if write_header:
            self._header_written = True  # set before await — no yield point before this line

        row = [_serialize_value(v) for v in data.values()]

        buf = StringIO()
        writer = csv.writer(buf)
        if write_header:
            writer.writerow(list(data.keys()))
        writer.writerow(row)

        async with aiofiles.open(self._path, mode="a", encoding="utf-8", newline="") as f:
            await f.write(buf.getvalue())

    async def close(self) -> None:
        pass
