import asyncio
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from crawler.storage.csv_storage import CSVStorage


def make_page(**overrides) -> dict:
    base = {
        "url": "https://example.com",
        "title": "Example Page",
        "text": "Hello world",
        "links": ["https://example.com/about"],
        "metadata": {"description": "A test page"},
        "crawled_at": datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
        "status_code": 200,
        "content_type": "text/html; charset=utf-8",
    }
    base.update(overrides)
    return base


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    """Returns (header_columns, list_of_row_dicts)."""
    reader = csv.DictReader(path.open(encoding="utf-8", newline=""))
    rows = list(reader)
    return list(reader.fieldnames or []), rows


def count_header_rows(path: Path) -> int:
    """Count how many lines look like the CSV header (contain 'url,title')."""
    content = path.read_text(encoding="utf-8")
    return sum(1 for line in content.splitlines() if line.startswith("url,"))


# --- basic write ---


@pytest.mark.asyncio
async def test_save_single_record(tmp_path: Path) -> None:
    storage = CSVStorage(tmp_path / "results.csv")
    await storage.save(make_page())
    _, rows = read_csv(tmp_path / "results.csv")
    assert len(rows) == 1
    assert rows[0]["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_save_multiple_records(tmp_path: Path) -> None:
    storage = CSVStorage(tmp_path / "results.csv")
    await storage.save(make_page(url="https://example.com/1"))
    await storage.save(make_page(url="https://example.com/2"))
    await storage.save(make_page(url="https://example.com/3"))
    _, rows = read_csv(tmp_path / "results.csv")
    assert len(rows) == 3
    assert [r["url"] for r in rows] == [
        "https://example.com/1",
        "https://example.com/2",
        "https://example.com/3",
    ]


# --- header ---


@pytest.mark.asyncio
async def test_header_written_once(tmp_path: Path) -> None:
    storage = CSVStorage(tmp_path / "results.csv")
    await storage.save(make_page())
    await storage.save(make_page())
    await storage.save(make_page())
    assert count_header_rows(tmp_path / "results.csv") == 1


@pytest.mark.asyncio
async def test_header_matches_dict_keys(tmp_path: Path) -> None:
    page = make_page()
    storage = CSVStorage(tmp_path / "results.csv")
    await storage.save(page)
    header, _ = read_csv(tmp_path / "results.csv")
    assert header == list(page.keys())


@pytest.mark.asyncio
async def test_existing_nonempty_file_gets_no_header(tmp_path: Path) -> None:
    path = tmp_path / "results.csv"
    storage1 = CSVStorage(path)
    await storage1.save(make_page(url="https://first.com"))
    await storage1.close()

    storage2 = CSVStorage(path)
    await storage2.save(make_page(url="https://second.com"))
    await storage2.close()

    assert count_header_rows(path) == 1
    _, rows = read_csv(path)
    assert len(rows) == 2


# --- serialisation ---


@pytest.mark.asyncio
async def test_links_json_roundtrip(tmp_path: Path) -> None:
    storage = CSVStorage(tmp_path / "results.csv")
    await storage.save(make_page(links=["https://a.com", "https://b.com"]))
    _, rows = read_csv(tmp_path / "results.csv")
    assert json.loads(rows[0]["links"]) == ["https://a.com", "https://b.com"]


@pytest.mark.asyncio
async def test_links_empty_list_roundtrip(tmp_path: Path) -> None:
    storage = CSVStorage(tmp_path / "results.csv")
    await storage.save(make_page(links=[]))
    _, rows = read_csv(tmp_path / "results.csv")
    assert json.loads(rows[0]["links"]) == []


@pytest.mark.asyncio
async def test_metadata_json_roundtrip(tmp_path: Path) -> None:
    metadata = {"description": "A page", "keywords": "test, python"}
    storage = CSVStorage(tmp_path / "results.csv")
    await storage.save(make_page(metadata=metadata))
    _, rows = read_csv(tmp_path / "results.csv")
    assert json.loads(rows[0]["metadata"]) == metadata


@pytest.mark.asyncio
async def test_datetime_serialized_as_iso(tmp_path: Path) -> None:
    dt = datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
    storage = CSVStorage(tmp_path / "results.csv")
    await storage.save(make_page(crawled_at=dt))
    _, rows = read_csv(tmp_path / "results.csv")
    assert rows[0]["crawled_at"] == "2024-06-15T10:30:00+00:00"


# --- special characters ---


@pytest.mark.asyncio
async def test_text_with_commas(tmp_path: Path) -> None:
    storage = CSVStorage(tmp_path / "results.csv")
    await storage.save(make_page(text="one, two, three"))
    _, rows = read_csv(tmp_path / "results.csv")
    assert rows[0]["text"] == "one, two, three"


@pytest.mark.asyncio
async def test_text_with_quotes(tmp_path: Path) -> None:
    storage = CSVStorage(tmp_path / "results.csv")
    await storage.save(make_page(text='say "hello"'))
    _, rows = read_csv(tmp_path / "results.csv")
    assert rows[0]["text"] == 'say "hello"'


@pytest.mark.asyncio
async def test_text_with_newlines(tmp_path: Path) -> None:
    storage = CSVStorage(tmp_path / "results.csv")
    await storage.save(make_page(text="line one\nline two"))
    _, rows = read_csv(tmp_path / "results.csv")
    assert rows[0]["text"] == "line one\nline two"


# --- None values ---


@pytest.mark.asyncio
async def test_none_title_becomes_empty_string(tmp_path: Path) -> None:
    storage = CSVStorage(tmp_path / "results.csv")
    await storage.save(make_page(title=None))
    _, rows = read_csv(tmp_path / "results.csv")
    assert rows[0]["title"] == ""


@pytest.mark.asyncio
async def test_none_content_type_becomes_empty_string(tmp_path: Path) -> None:
    storage = CSVStorage(tmp_path / "results.csv")
    await storage.save(make_page(content_type=None))
    _, rows = read_csv(tmp_path / "results.csv")
    assert rows[0]["content_type"] == ""


# --- lifecycle ---


@pytest.mark.asyncio
async def test_file_created_if_not_exists(tmp_path: Path) -> None:
    path = tmp_path / "results.csv"
    assert not path.exists()
    storage = CSVStorage(path)
    await storage.save(make_page())
    assert path.exists()


@pytest.mark.asyncio
async def test_parent_directory_created_if_not_exists(tmp_path: Path) -> None:
    path = tmp_path / "subdir" / "nested" / "results.csv"
    CSVStorage(path)
    assert path.parent.exists()


@pytest.mark.asyncio
async def test_concurrent_saves_produce_single_header(tmp_path: Path) -> None:
    path = tmp_path / "results.csv"
    storage = CSVStorage(path)
    await asyncio.gather(
        storage.save(make_page(url="https://a.com")),
        storage.save(make_page(url="https://b.com")),
        storage.save(make_page(url="https://c.com")),
    )
    assert count_header_rows(path) == 1
    _, rows = read_csv(path)
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_close_is_idempotent(tmp_path: Path) -> None:
    storage = CSVStorage(tmp_path / "results.csv")
    await storage.close()
    await storage.close()


@pytest.mark.asyncio
async def test_context_manager_saves_and_closes(tmp_path: Path) -> None:
    path = tmp_path / "results.csv"
    async with CSVStorage(path) as storage:
        await storage.save(make_page())
    _, rows = read_csv(path)
    assert len(rows) == 1
