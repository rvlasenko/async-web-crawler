import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Self

logger = logging.getLogger(__name__)


@dataclass
class CrawlerConfig:
    """Complete configuration for AdvancedCrawler.

    Load from a YAML or JSON file with CrawlerConfig.load(path), or construct
    directly. At least one of start_urls or sitemap_urls must be non-empty.

    Fields:
        start_urls: Seed URLs to begin crawling from.
        sitemap_urls: Sitemap URLs to fetch additional start URLs from.
        max_pages: Stop after processing this many pages. Must be positive.
        max_depth: Maximum link depth from seed URLs. None means unlimited.
        max_concurrent: Global limit on simultaneous HTTP requests.
        requests_per_second: Target request rate. None means no rate limit.
        rate_limit_per_domain: Apply rate limiting per domain vs globally.
        respect_robots: Fetch and respect robots.txt files.
        user_agent: User-Agent header sent with every request.
        same_domain_only: Only follow links whose domain matches the seed domain.
        include_patterns: Only enqueue URLs containing at least one of these.
        exclude_patterns: Skip URLs containing any of these substrings.
        storage_type: Backend for saving crawled pages.
        storage_path: File path for json/csv storage.
        postgres_dsn: PostgreSQL DSN for postgres storage.
        output_dir: Default output directory (used by CLI).
        log_file: Optional path to a rotating log file.
        log_level: Root logging level name (DEBUG/INFO/WARNING/ERROR).
    """

    start_urls: list[str] = field(default_factory=list)
    sitemap_urls: list[str] = field(default_factory=list)

    max_pages: int = 100
    max_depth: int | None = None
    max_concurrent: int = 5
    requests_per_second: float | None = None
    rate_limit_per_domain: bool = True
    respect_robots: bool = False
    user_agent: str = "AsyncCrawler/1.0"
    same_domain_only: bool = False
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)

    storage_type: Literal["json", "csv", "postgres", "none"] = "none"
    storage_path: str | None = None
    postgres_dsn: str | None = None

    output_dir: str = "output"
    log_file: str | None = None
    log_level: str = "INFO"

    @classmethod
    def load(cls, path: str | Path) -> Self:
        """Load config from a YAML (.yaml/.yml) or JSON (.json) file.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file extension is unsupported or the config is invalid.
            ImportError: If PyYAML is not installed and the file is YAML.
        """
        p = Path(path)
        suffix = p.suffix.lower()
        text = p.read_text(encoding="utf-8")

        if suffix in (".yaml", ".yml"):
            try:
                import yaml  # noqa: PLC0415
            except ImportError as exc:
                raise ImportError(
                    "PyYAML is required to load YAML config files. "
                    "Install it with: pip install pyyaml"
                ) from exc
            data = yaml.safe_load(text) or {}
        elif suffix == ".json":
            data = json.loads(text)
        else:
            raise ValueError(
                f"Unsupported config file format: '{suffix}'. "
                "Expected .yaml, .yml, or .json"
            )

        config = cls.from_dict(data)
        config.validate()
        return config

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Construct a CrawlerConfig from a plain dictionary.

        Unknown keys are logged at DEBUG level and ignored so that future
        config fields do not break older code reading the same file.
        """
        known = {
            "start_urls",
            "sitemap_urls",
            "max_pages",
            "max_depth",
            "max_concurrent",
            "requests_per_second",
            "rate_limit_per_domain",
            "respect_robots",
            "user_agent",
            "same_domain_only",
            "include_patterns",
            "exclude_patterns",
            "storage_type",
            "storage_path",
            "postgres_dsn",
            "output_dir",
            "log_file",
            "log_level",
        }
        unknown = set(data) - known
        if unknown:
            logger.debug("Ignoring unknown config keys: %s", sorted(unknown))

        def _list(key: str, default: list) -> list:
            v = data.get(key, default)
            return list(v) if v is not None else default

        def _opt_int(key: str) -> int | None:
            v = data.get(key)
            return int(v) if v is not None else None

        def _opt_float(key: str) -> float | None:
            v = data.get(key)
            return float(v) if v is not None else None

        return cls(
            start_urls=_list("start_urls", []),
            sitemap_urls=_list("sitemap_urls", []),
            max_pages=int(data.get("max_pages", 100)),
            max_depth=_opt_int("max_depth"),
            max_concurrent=int(data.get("max_concurrent", 5)),
            requests_per_second=_opt_float("requests_per_second"),
            rate_limit_per_domain=bool(data.get("rate_limit_per_domain", True)),
            respect_robots=bool(data.get("respect_robots", False)),
            user_agent=str(data.get("user_agent", "AsyncCrawler/1.0")),
            same_domain_only=bool(data.get("same_domain_only", False)),
            include_patterns=_list("include_patterns", []),
            exclude_patterns=_list("exclude_patterns", []),
            storage_type=data.get("storage_type", "none"),
            storage_path=data.get("storage_path"),
            postgres_dsn=data.get("postgres_dsn"),
            output_dir=str(data.get("output_dir", "output")),
            log_file=data.get("log_file"),
            log_level=str(data.get("log_level", "INFO")),
        )

    def validate(self) -> None:
        """Raise ValueError if any required constraint is violated."""
        if not self.start_urls and not self.sitemap_urls:
            raise ValueError(
                "At least one of start_urls or sitemap_urls must be provided."
            )

        if self.storage_type in ("json", "csv") and not self.storage_path:
            raise ValueError(
                f"storage_path is required when storage_type is '{self.storage_type}'."
            )

        if self.storage_type == "postgres" and not self.postgres_dsn:
            raise ValueError(
                "postgres_dsn is required when storage_type is 'postgres'."
            )

        if self.max_pages <= 0:
            raise ValueError(
                f"max_pages must be a positive integer, got {self.max_pages}."
            )

        if self.max_concurrent <= 0:
            raise ValueError(
                f"max_concurrent must be a positive integer, got {self.max_concurrent}."
            )

        if self.requests_per_second is not None and self.requests_per_second <= 0:
            raise ValueError(
                f"requests_per_second must be positive, got {self.requests_per_second}."
            )

        import logging as _logging  # noqa: PLC0415

        if isinstance(_logging.getLevelName(self.log_level.upper()), str):
            raise ValueError(
                f"Invalid log_level '{self.log_level}'. "
                "Expected one of: DEBUG, INFO, WARNING, ERROR, CRITICAL."
            )
