import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from crawler.errors import NetworkError, TransientError

logger = logging.getLogger(__name__)

T = TypeVar("T")

_DEFAULT_RETRY_ON: tuple[type[Exception], ...] = (TransientError, NetworkError)


@dataclass
class RetryStats:
    """Cumulative statistics collected across all execute_with_retry calls."""

    total_calls: int = 0
    total_retries: int = 0
    successful_retries: int = 0
    failed_calls: int = 0
    errors_by_type: dict[str, int] = field(default_factory=dict)
    total_delay_seconds: float = 0.0

    @property
    def avg_delay_per_retry(self) -> float:
        return self.total_delay_seconds / self.total_retries if self.total_retries > 0 else 0.0


@dataclass
class RetryTypeConfig:
    """Per-exception-type retry settings that override the global RetryStrategy defaults.

    Allows different backoff behaviour per error type — e.g. retry TransientErrors
    aggressively (high backoff_factor) while retrying NetworkErrors more gently.
    """

    max_retries: int
    backoff_factor: float = 2.0
    base_delay: float = 1.0


class RetryStrategy:
    """Executes an async callable with automatic retries and exponential backoff.

    Retries are attempted only for exception types listed in `retry_on`. All
    other exceptions propagate immediately. On exhaustion, the last exception
    is re-raised with its original traceback — no wrapper is added.

    Global backoff formula: base_delay * (backoff_factor ** type_attempt), where
    type_attempt is the zero-indexed retry count for that specific exception type.
    Per-type config overrides base_delay and backoff_factor for a given type.

    Args:
        max_retries: Maximum total retry attempts (global ceiling across all types).
        backoff_factor: Default multiplier applied to delay on each retry.
        base_delay: Default initial delay in seconds before the first retry.
        retry_on: Exception types that trigger a retry. None uses the default
            [TransientError, NetworkError]. Pass [] to disable all retries.
        per_type_config: Optional per-type overrides for max_retries, backoff_factor,
            and base_delay. Types not listed fall back to global settings.
    """

    def __init__(
        self,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        base_delay: float = 1.0,
        retry_on: list[type[Exception]] | None = None,
        per_type_config: dict[type[Exception], RetryTypeConfig] | None = None,
    ) -> None:
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.base_delay = base_delay
        self.retry_on: tuple[type[Exception], ...] = (
            tuple(retry_on) if retry_on is not None else _DEFAULT_RETRY_ON
        )
        self.per_type_config: dict[type[Exception], RetryTypeConfig] = per_type_config or {}
        self.stats = RetryStats()
        self._validate_params()

    async def execute_with_retry(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        context: str = "",
        **kwargs: Any,
    ) -> T:
        """Call func(*args, **kwargs) with automatic retries on configured exceptions.

        Args:
            func: Async callable to execute.
            *args: Positional arguments forwarded to func.
            context: Optional label included in log messages (e.g. the URL being fetched).
            **kwargs: Keyword arguments forwarded to func.

        Raises:
            The last caught retryable exception when retries are exhausted.
            Any non-retryable exception immediately, without delay.
        """
        type_counts: dict[type[Exception], int] = {}
        had_retries = False
        self.stats.total_calls += 1

        for global_attempt in range(self.max_retries + 1):
            try:
                result = await func(*args, **kwargs)
                if had_retries:
                    self.stats.successful_retries += 1
                    logger.info(
                        "%s — recovered after %d retry(s)",
                        context or "call",
                        sum(type_counts.values()),
                    )
                return result
            except Exception as exc:
                exc_type = type(exc)
                self.stats.errors_by_type[exc_type.__name__] = (
                    self.stats.errors_by_type.get(exc_type.__name__, 0) + 1
                )

                if not self.retry_on or not isinstance(exc, self.retry_on):
                    self.stats.failed_calls += 1
                    raise

                type_cfg = self.per_type_config.get(exc_type)
                type_counts[exc_type] = type_counts.get(exc_type, 0) + 1
                type_attempt = type_counts[exc_type]
                effective_max = type_cfg.max_retries if type_cfg else self.max_retries

                if type_attempt > effective_max or global_attempt == self.max_retries:
                    self.stats.failed_calls += 1
                    logger.warning(
                        "%s — %s retries exhausted (%d attempt(s))",
                        context or "call",
                        exc_type.__name__,
                        type_attempt,
                    )
                    raise

                backoff = type_cfg.backoff_factor if type_cfg else self.backoff_factor
                base = type_cfg.base_delay if type_cfg else self.base_delay
                delay = base * (backoff ** (type_attempt - 1))

                self.stats.total_retries += 1
                self.stats.total_delay_seconds += delay
                had_retries = True

                logger.warning(
                    "%s — %s on attempt %d/%d, retrying in %.2fs",
                    context or "call",
                    exc_type.__name__,
                    global_attempt + 1,
                    self.max_retries,
                    delay,
                )
                await asyncio.sleep(delay)

        raise AssertionError("unreachable")  # satisfies type checker

    def _validate_params(self) -> None:
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be non-negative, got {self.max_retries}")
        if self.backoff_factor <= 0:
            raise ValueError(f"backoff_factor must be positive, got {self.backoff_factor}")
        if self.base_delay < 0:
            raise ValueError(f"base_delay must be non-negative, got {self.base_delay}")
