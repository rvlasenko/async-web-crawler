import logging
import logging.handlers
import sys
from pathlib import Path


def setup_logging(
    level: str | int = "INFO",
    log_file: str | Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Configure root logger with a StreamHandler and optional RotatingFileHandler.

    Sets the root logger level so all crawler.* child loggers inherit it.
    Safe to call once at process startup. Avoid calling multiple times — each
    call appends new handlers to the root logger without removing existing ones.

    Args:
        level: Logging level name ("DEBUG", "INFO", ...) or integer constant.
        log_file: Optional path for rotating file output. Parent directory is
            created automatically if it does not exist.
        max_bytes: Maximum size in bytes before the log file is rotated.
        backup_count: Number of rotated backup files to keep.
    """
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    root.addHandler(console)

    if log_file is not None:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        rotating = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        rotating.setFormatter(fmt)
        root.addHandler(rotating)
