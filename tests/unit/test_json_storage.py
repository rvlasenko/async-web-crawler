import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from crawler.storage.json_storage import JSONStorage


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


def read_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# --- basic write ---


@pytest.mark.asyncio
async def test_save_single_record(tmp_path: Path) -> None:
    storage = JSONStorage(tmp_path / "results.jsonl")
    await storage.save(make_page())
    records = read_records(tmp_path / "results.jsonl")
    assert len(records) == 1
    assert records[0]["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_save_multiple_records(tmp_path: Path) -> None:
    storage = JSONStorage(tmp_path / "results.jsonl")
    await storage.save(make_page(url="https://example.com/1"))
    await storage.save(make_page(url="https://example.com/2"))
    await storage.save(make_page(url="https://example.com/3"))
    records = read_records(tmp_path / "results.jsonl")
    assert len(records) == 3
    assert [r["url"] for r in records] == [
        "https://example.com/1",
        "https://example.com/2",
        "https://example.com/3",
    ]


# --- serialisation ---


@pytest.mark.asyncio
async def test_datetime_serialized_as_iso(tmp_path: Path) -> None:
    dt = datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
    storage = JSONStorage(tmp_path / "results.jsonl")
    await storage.save(make_page(crawled_at=dt))
    records = read_records(tmp_path / "results.jsonl")
    assert records[0]["crawled_at"] == "2024-06-15T10:30:00+00:00"
    assert isinstance(records[0]["crawled_at"], str)


@pytest.mark.asyncio
async def test_links_empty_list_preserved(tmp_path: Path) -> None:
    storage = JSONStorage(tmp_path / "results.jsonl")
    await storage.save(make_page(links=[]))
    records = read_records(tmp_path / "results.jsonl")
    assert records[0]["links"] == []


@pytest.mark.asyncio
async def test_links_nonempty_list_preserved(tmp_path: Path) -> None:
    storage = JSONStorage(tmp_path / "results.jsonl")
    await storage.save(make_page(links=["https://a.com", "https://b.com"]))
    records = read_records(tmp_path / "results.jsonl")
    assert records[0]["links"] == ["https://a.com", "https://b.com"]


@pytest.mark.asyncio
async def test_metadata_dict_preserved(tmp_path: Path) -> None:
    metadata = {"description": "A page", "keywords": "test, python", "nested": {"k": "v"}}
    storage = JSONStorage(tmp_path / "results.jsonl")
    await storage.save(make_page(metadata=metadata))
    records = read_records(tmp_path / "results.jsonl")
    assert records[0]["metadata"] == metadata


# --- None values ---


@pytest.mark.asyncio
async def test_none_title_serialized_as_null(tmp_path: Path) -> None:
    storage = JSONStorage(tmp_path / "results.jsonl")
    await storage.save(make_page(title=None))
    records = read_records(tmp_path / "results.jsonl")
    assert records[0]["title"] is None


@pytest.mark.asyncio
async def test_none_content_type_serialized_as_null(tmp_path: Path) -> None:
    storage = JSONStorage(tmp_path / "results.jsonl")
    await storage.save(make_page(content_type=None))
    records = read_records(tmp_path / "results.jsonl")
    assert records[0]["content_type"] is None


# --- edge cases ---


@pytest.mark.asyncio
async def test_empty_text_saved_without_error(tmp_path: Path) -> None:
    storage = JSONStorage(tmp_path / "results.jsonl")
    await storage.save(make_page(text=""))
    records = read_records(tmp_path / "results.jsonl")
    assert records[0]["text"] == ""


@pytest.mark.asyncio
async def test_file_created_if_not_exists(tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    assert not path.exists()
    storage = JSONStorage(path)
    await storage.save(make_page())
    assert path.exists()


@pytest.mark.asyncio
async def test_parent_directory_created_if_not_exists(tmp_path: Path) -> None:
    path = tmp_path / "subdir" / "nested" / "results.jsonl"
    JSONStorage(path)
    assert path.parent.exists()


@pytest.mark.asyncio
async def test_second_instance_appends_to_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    storage1 = JSONStorage(path)
    await storage1.save(make_page(url="https://first.com"))
    await storage1.close()

    storage2 = JSONStorage(path)
    await storage2.save(make_page(url="https://second.com"))
    await storage2.close()

    records = read_records(path)
    assert len(records) == 2
    assert records[0]["url"] == "https://first.com"
    assert records[1]["url"] == "https://second.com"


@pytest.mark.asyncio
async def test_close_is_idempotent(tmp_path: Path) -> None:
    storage = JSONStorage(tmp_path / "results.jsonl")
    await storage.close()
    await storage.close()


@pytest.mark.asyncio
async def test_context_manager_saves_and_closes(tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    async with JSONStorage(path) as storage:
        await storage.save(make_page())
    records = read_records(path)
    assert len(records) == 1
