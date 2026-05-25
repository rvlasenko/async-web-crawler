import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from crawler.errors import NetworkError, TransientError

logger = logging.getLogger(__name__)

T = TypeVar("T")

_DEFAULT_RETRY_ON: tuple[type[Exception], ...] = (TransientError, NetworkError)


class RetryStrategy:
    """Executes an async callable with automatic retries and exponential backoff.

    Retries are attempted only for exception types listed in `retry_on`. All
    other exceptions propagate immediately. On exhaustion, the last exception
    is re-raised with its original traceback — no wrapper is added.

    Backoff formula: base_delay * (backoff_factor ** attempt), where attempt
    is zero-indexed (0 for the first retry, 1 for the second, and so on).

    Args:
        max_retries: Maximum number of retry attempts after the initial call.
            0 means a single attempt with no retries.
        backoff_factor: Multiplier applied to the delay on each successive retry.
            Must be positive. Use 1.0 for a constant delay.
        base_delay: Initial delay in seconds before the first retry. 0.0 is
            valid and useful in tests.
        retry_on: Exception types that trigger a retry. None uses the default
            [TransientError, NetworkError]. Pass [] to disable all retries.
    """

    def __init__(
        self,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        base_delay: float = 1.0,
        retry_on: list[type[Exception]] | None = None,
    ) -> None:
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.base_delay = base_delay
        self.retry_on: tuple[type[Exception], ...] = (
            tuple(retry_on) if retry_on is not None else _DEFAULT_RETRY_ON
        )
        self._validate_params()

    async def execute_with_retry(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Call func(*args, **kwargs) with automatic retries on configured exceptions.

        Raises:
            The last caught retryable exception when retries are exhausted.
            Any non-retryable exception immediately, without delay.
        """
        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as exc:
                if not self.retry_on or not isinstance(exc, self.retry_on):
                    raise

                if attempt == self.max_retries:
                    raise

                delay = self.base_delay * (self.backoff_factor ** attempt)
                logger.warning(
                    "%s on attempt %d/%d — retrying in %.2fs",
                    type(exc).__name__,
                    attempt + 1,
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
