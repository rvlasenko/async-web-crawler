import json
from pathlib import Path

import pytest

from crawler.config import CrawlerConfig


# ---------------------------------------------------------------------------
# load() — YAML
# ---------------------------------------------------------------------------


def test_load_yaml_file(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "start_urls:\n  - https://example.com\nmax_pages: 42\n",
        encoding="utf-8",
    )

    config = CrawlerConfig.load(cfg_file)

    assert config.start_urls == ["https://example.com"]
    assert config.max_pages == 42


def test_load_yml_extension(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yml"
    cfg_file.write_text("start_urls:\n  - https://example.com\n", encoding="utf-8")

    config = CrawlerConfig.load(cfg_file)

    assert config.start_urls == ["https://example.com"]


def test_load_json_file(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps({"start_urls": ["https://example.com"], "max_pages": 10}),
        encoding="utf-8",
    )

    config = CrawlerConfig.load(cfg_file)

    assert config.start_urls == ["https://example.com"]
    assert config.max_pages == 10


def test_load_unsupported_extension_raises(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[crawler]\nmax_pages = 10\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported config file format"):
        CrawlerConfig.load(cfg_file)


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        CrawlerConfig.load(tmp_path / "does_not_exist.yaml")


# ---------------------------------------------------------------------------
# from_dict()
# ---------------------------------------------------------------------------


def test_from_dict_sets_fields() -> None:
    config = CrawlerConfig.from_dict(
        {"start_urls": ["https://a.com", "https://b.com"], "max_pages": 77}
    )

    assert config.start_urls == ["https://a.com", "https://b.com"]
    assert config.max_pages == 77


def test_from_dict_uses_defaults_for_missing_keys() -> None:
    config = CrawlerConfig.from_dict({"start_urls": ["https://a.com"]})

    assert config.max_pages == 100
    assert config.max_concurrent == 5
    assert config.log_level == "INFO"


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------


def test_validate_raises_if_no_urls() -> None:
    config = CrawlerConfig()

    with pytest.raises(ValueError, match="start_urls or sitemap_urls"):
        config.validate()


def test_validate_raises_if_json_storage_without_path() -> None:
    config = CrawlerConfig(start_urls=["https://a.com"], storage_type="json")

    with pytest.raises(ValueError, match="storage_path"):
        config.validate()


def test_validate_raises_if_csv_storage_without_path() -> None:
    config = CrawlerConfig(start_urls=["https://a.com"], storage_type="csv")

    with pytest.raises(ValueError, match="storage_path"):
        config.validate()


def test_validate_raises_if_postgres_without_dsn() -> None:
    config = CrawlerConfig(start_urls=["https://a.com"], storage_type="postgres")

    with pytest.raises(ValueError, match="postgres_dsn"):
        config.validate()


def test_validate_passes_with_sitemap_only() -> None:
    config = CrawlerConfig(sitemap_urls=["https://a.com/sitemap.xml"])

    config.validate()  # must not raise


def test_validate_passes_with_start_urls_only() -> None:
    config = CrawlerConfig(start_urls=["https://a.com"])

    config.validate()  # must not raise


def test_validate_raises_if_invalid_log_level() -> None:
    config = CrawlerConfig(start_urls=["https://a.com"], log_level="VERBOSE")

    with pytest.raises(ValueError, match="log_level"):
        config.validate()


def test_validate_raises_if_max_pages_zero() -> None:
    config = CrawlerConfig(start_urls=["https://a.com"], max_pages=0)

    with pytest.raises(ValueError, match="max_pages"):
        config.validate()
