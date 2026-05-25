import pytest
from unittest.mock import AsyncMock, patch, call

from crawler.errors import TransientError, PermanentError, NetworkError, ParseError
from crawler.retry_strategy import RetryStats, RetryStrategy, RetryTypeConfig


# ---------------------------------------------------------------------------
# Init / validation
# ---------------------------------------------------------------------------


def test_default_values() -> None:
    s = RetryStrategy()
    assert s.max_retries == 3
    assert s.backoff_factor == 2.0
    assert s.base_delay == 1.0
    assert s.retry_on == (TransientError, NetworkError)


def test_retry_on_none_uses_defaults() -> None:
    assert RetryStrategy(retry_on=None).retry_on == RetryStrategy().retry_on


def test_retry_on_stored_as_tuple() -> None:
    s = RetryStrategy(retry_on=[TransientError])
    assert isinstance(s.retry_on, tuple)
    assert s.retry_on == (TransientError,)


def test_retry_on_empty_list_stored_as_empty_tuple() -> None:
    assert RetryStrategy(retry_on=[]).retry_on == ()


def test_negative_max_retries_raises() -> None:
    with pytest.raises(ValueError, match="max_retries"):
        RetryStrategy(max_retries=-1)


def test_zero_backoff_factor_raises() -> None:
    with pytest.raises(ValueError, match="backoff_factor"):
        RetryStrategy(backoff_factor=0.0)


def test_negative_backoff_factor_raises() -> None:
    with pytest.raises(ValueError, match="backoff_factor"):
        RetryStrategy(backoff_factor=-1.0)


def test_negative_base_delay_raises() -> None:
    with pytest.raises(ValueError, match="base_delay"):
        RetryStrategy(base_delay=-0.1)


def test_zero_base_delay_is_valid() -> None:
    RetryStrategy(base_delay=0.0)


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_on_first_attempt() -> None:
    mock_func = AsyncMock(return_value="ok")
    with patch("crawler.retry_strategy.asyncio.sleep") as mock_sleep:
        result = await RetryStrategy().execute_with_retry(mock_func)
    assert result == "ok"
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_return_value_is_passed_through() -> None:
    sentinel = object()
    mock_func = AsyncMock(return_value=sentinel)
    result = await RetryStrategy(base_delay=0).execute_with_retry(mock_func)
    assert result is sentinel


@pytest.mark.asyncio
async def test_args_and_kwargs_are_forwarded() -> None:
    mock_func = AsyncMock(return_value="ok")
    await RetryStrategy(base_delay=0).execute_with_retry(mock_func, "a", key="b")
    mock_func.assert_called_once_with("a", key="b")


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retries_on_transient_error() -> None:
    mock_func = AsyncMock(side_effect=[TransientError("fail"), "ok"])
    with patch("crawler.retry_strategy.asyncio.sleep"):
        result = await RetryStrategy().execute_with_retry(mock_func)
    assert result == "ok"
    assert mock_func.call_count == 2


@pytest.mark.asyncio
async def test_retries_on_network_error() -> None:
    mock_func = AsyncMock(side_effect=[NetworkError("conn refused"), "ok"])
    with patch("crawler.retry_strategy.asyncio.sleep"):
        result = await RetryStrategy().execute_with_retry(mock_func)
    assert result == "ok"


@pytest.mark.asyncio
async def test_exhausts_retries_then_raises() -> None:
    mock_func = AsyncMock(side_effect=TransientError("always"))
    with patch("crawler.retry_strategy.asyncio.sleep"):
        with pytest.raises(TransientError):
            await RetryStrategy(max_retries=2).execute_with_retry(mock_func)
    assert mock_func.call_count == 3


@pytest.mark.asyncio
async def test_call_count_equals_max_retries_plus_one() -> None:
    mock_func = AsyncMock(side_effect=TransientError("always"))
    with patch("crawler.retry_strategy.asyncio.sleep"):
        with pytest.raises(TransientError):
            await RetryStrategy(max_retries=3).execute_with_retry(mock_func)
    assert mock_func.call_count == 4


@pytest.mark.asyncio
async def test_last_exception_is_reraised_not_wrapped() -> None:
    exc = TransientError("original")
    mock_func = AsyncMock(side_effect=exc)
    with patch("crawler.retry_strategy.asyncio.sleep"):
        with pytest.raises(TransientError) as exc_info:
            await RetryStrategy(max_retries=1).execute_with_retry(mock_func)
    assert exc_info.value is exc


@pytest.mark.asyncio
async def test_permanent_error_not_retried() -> None:
    mock_func = AsyncMock(side_effect=PermanentError("404"))
    with patch("crawler.retry_strategy.asyncio.sleep") as mock_sleep:
        with pytest.raises(PermanentError):
            await RetryStrategy().execute_with_retry(mock_func)
    assert mock_func.call_count == 1
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_parse_error_not_retried() -> None:
    mock_func = AsyncMock(side_effect=ParseError("bad html"))
    with patch("crawler.retry_strategy.asyncio.sleep") as mock_sleep:
        with pytest.raises(ParseError):
            await RetryStrategy().execute_with_retry(mock_func)
    assert mock_func.call_count == 1
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_arbitrary_exception_not_retried() -> None:
    mock_func = AsyncMock(side_effect=ValueError("unexpected"))
    with patch("crawler.retry_strategy.asyncio.sleep") as mock_sleep:
        with pytest.raises(ValueError):
            await RetryStrategy().execute_with_retry(mock_func)
    assert mock_func.call_count == 1
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Boundary: max_retries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_retries_zero_success() -> None:
    mock_func = AsyncMock(return_value="ok")
    result = await RetryStrategy(max_retries=0).execute_with_retry(mock_func)
    assert result == "ok"
    assert mock_func.call_count == 1


@pytest.mark.asyncio
async def test_max_retries_zero_raises_immediately() -> None:
    mock_func = AsyncMock(side_effect=TransientError("fail"))
    with patch("crawler.retry_strategy.asyncio.sleep") as mock_sleep:
        with pytest.raises(TransientError):
            await RetryStrategy(max_retries=0).execute_with_retry(mock_func)
    assert mock_func.call_count == 1
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_max_retries_one_calls_func_exactly_twice() -> None:
    mock_func = AsyncMock(side_effect=TransientError("fail"))
    with patch("crawler.retry_strategy.asyncio.sleep"):
        with pytest.raises(TransientError):
            await RetryStrategy(max_retries=1, base_delay=0).execute_with_retry(
                mock_func
            )
    assert mock_func.call_count == 2


# ---------------------------------------------------------------------------
# Boundary: retry_on
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_retry_on_never_retries() -> None:
    mock_func = AsyncMock(side_effect=TransientError("fail"))
    with patch("crawler.retry_strategy.asyncio.sleep") as mock_sleep:
        with pytest.raises(TransientError):
            await RetryStrategy(retry_on=[]).execute_with_retry(mock_func)
    assert mock_func.call_count == 1
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_custom_retry_on_retries_only_specified_type() -> None:
    mock_func = AsyncMock(side_effect=[PermanentError("403"), "ok"])
    with patch("crawler.retry_strategy.asyncio.sleep"):
        result = await RetryStrategy(retry_on=[PermanentError]).execute_with_retry(
            mock_func
        )
    assert result == "ok"


# ---------------------------------------------------------------------------
# Backoff timing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backoff_delay_first_retry() -> None:
    mock_func = AsyncMock(side_effect=[TransientError("fail"), "ok"])
    with patch("crawler.retry_strategy.asyncio.sleep") as mock_sleep:
        await RetryStrategy(
            max_retries=3, base_delay=1.0, backoff_factor=2.0
        ).execute_with_retry(mock_func)
    mock_sleep.assert_called_once_with(1.0)


@pytest.mark.asyncio
async def test_backoff_delay_increases_exponentially() -> None:
    mock_func = AsyncMock(
        side_effect=[TransientError(), TransientError(), TransientError(), "ok"]
    )
    with patch("crawler.retry_strategy.asyncio.sleep") as mock_sleep:
        await RetryStrategy(
            max_retries=3, base_delay=1.0, backoff_factor=2.0
        ).execute_with_retry(mock_func)
    assert mock_sleep.call_args_list == [call(1.0), call(2.0), call(4.0)]


@pytest.mark.asyncio
async def test_sleep_not_called_after_final_failure() -> None:
    mock_func = AsyncMock(side_effect=TransientError("always"))
    with patch("crawler.retry_strategy.asyncio.sleep") as mock_sleep:
        with pytest.raises(TransientError):
            await RetryStrategy(max_retries=2, base_delay=1.0).execute_with_retry(
                mock_func
            )
    # 3 calls total (0, 1, 2 attempts): sleep only between attempts 0→1 and 1→2
    assert mock_sleep.call_count == 2


@pytest.mark.asyncio
async def test_backoff_factor_one_produces_constant_delay() -> None:
    mock_func = AsyncMock(side_effect=[TransientError(), TransientError(), "ok"])
    with patch("crawler.retry_strategy.asyncio.sleep") as mock_sleep:
        await RetryStrategy(
            max_retries=2, base_delay=0.5, backoff_factor=1.0
        ).execute_with_retry(mock_func)
    assert mock_sleep.call_args_list == [call(0.5), call(0.5)]


@pytest.mark.asyncio
async def test_custom_base_delay_and_factor() -> None:
    mock_func = AsyncMock(side_effect=[TransientError(), TransientError(), "ok"])
    with patch("crawler.retry_strategy.asyncio.sleep") as mock_sleep:
        await RetryStrategy(
            max_retries=2, base_delay=0.5, backoff_factor=3.0
        ).execute_with_retry(mock_func)
    assert mock_sleep.call_args_list == [call(0.5), call(1.5)]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warning_logged_on_retry(caplog) -> None:
    import logging

    mock_func = AsyncMock(side_effect=[TransientError("boom"), "ok"])
    with patch("crawler.retry_strategy.asyncio.sleep"):
        with caplog.at_level(logging.WARNING, logger="crawler.retry_strategy"):
            await RetryStrategy(max_retries=1).execute_with_retry(mock_func)
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert "TransientError" in record.message
    assert "1/1" in record.message


@pytest.mark.asyncio
async def test_no_log_on_success(caplog) -> None:
    import logging

    mock_func = AsyncMock(return_value="ok")
    with caplog.at_level(logging.WARNING, logger="crawler.retry_strategy"):
        await RetryStrategy().execute_with_retry(mock_func)
    assert len(caplog.records) == 0


@pytest.mark.asyncio
async def test_no_log_on_non_retryable_exception(caplog) -> None:
    import logging

    mock_func = AsyncMock(side_effect=PermanentError("403"))
    with patch("crawler.retry_strategy.asyncio.sleep"):
        with caplog.at_level(logging.WARNING, logger="crawler.retry_strategy"):
            with pytest.raises(PermanentError):
                await RetryStrategy().execute_with_retry(mock_func)
    assert len(caplog.records) == 0


# ---------------------------------------------------------------------------
# Per-type config
# ---------------------------------------------------------------------------


def test_retry_type_config_stores_values() -> None:
    cfg = RetryTypeConfig(max_retries=2, backoff_factor=3.0, base_delay=0.5)
    assert cfg.max_retries == 2
    assert cfg.backoff_factor == 3.0
    assert cfg.base_delay == 0.5


def test_retry_type_config_default_backoff_and_delay() -> None:
    cfg = RetryTypeConfig(max_retries=1)
    assert cfg.backoff_factor == 2.0
    assert cfg.base_delay == 1.0


@pytest.mark.asyncio
async def test_per_type_config_applies_different_backoff() -> None:
    mock_func = AsyncMock(side_effect=[TransientError(), NetworkError(), "ok"])
    strategy = RetryStrategy(
        max_retries=3,
        retry_on=[TransientError, NetworkError],
        per_type_config={
            TransientError: RetryTypeConfig(max_retries=3, backoff_factor=2.0, base_delay=1.0),
            NetworkError: RetryTypeConfig(max_retries=3, backoff_factor=3.0, base_delay=0.5),
        },
    )
    with patch("crawler.retry_strategy.asyncio.sleep") as mock_sleep:
        result = await strategy.execute_with_retry(mock_func)
    assert result == "ok"
    delays = [c.args[0] for c in mock_sleep.call_args_list]
    # TransientError: base_delay=1.0, backoff_factor=2.0, type_attempt=0 → 1.0 * 2.0**0 = 1.0
    # NetworkError:  base_delay=0.5, backoff_factor=3.0, type_attempt=0 → 0.5 * 3.0**0 = 0.5
    assert delays == [1.0, 0.5]


@pytest.mark.asyncio
async def test_per_type_max_retries_limits_that_type() -> None:
    # TransientError has max_retries=1 in per_type_config — stops after 2 calls
    mock_func = AsyncMock(side_effect=TransientError("always"))
    strategy = RetryStrategy(
        max_retries=10,
        retry_on=[TransientError],
        per_type_config={
            TransientError: RetryTypeConfig(max_retries=1, base_delay=0),
        },
    )
    with patch("crawler.retry_strategy.asyncio.sleep"):
        with pytest.raises(TransientError):
            await strategy.execute_with_retry(mock_func)
    assert mock_func.call_count == 2  # 1 initial + 1 retry


@pytest.mark.asyncio
async def test_type_without_per_type_config_uses_global() -> None:
    # NetworkError has no per_type_config entry → uses global settings
    mock_func = AsyncMock(side_effect=[NetworkError(), NetworkError(), "ok"])
    strategy = RetryStrategy(
        max_retries=3,
        base_delay=1.0,
        backoff_factor=2.0,
        retry_on=[NetworkError],
        per_type_config={
            TransientError: RetryTypeConfig(max_retries=1, backoff_factor=99.0, base_delay=99.0),
        },
    )
    with patch("crawler.retry_strategy.asyncio.sleep") as mock_sleep:
        result = await strategy.execute_with_retry(mock_func)
    assert result == "ok"
    delays = [c.args[0] for c in mock_sleep.call_args_list]
    # Uses global: base_delay=1.0, backoff_factor=2.0
    assert delays[0] == 1.0  # attempt 0 for NetworkError


@pytest.mark.asyncio
async def test_per_type_config_none_uses_global_settings() -> None:
    mock_func = AsyncMock(side_effect=[TransientError(), "ok"])
    with patch("crawler.retry_strategy.asyncio.sleep") as mock_sleep:
        await RetryStrategy(
            max_retries=1, base_delay=0.7, backoff_factor=1.0, per_type_config=None
        ).execute_with_retry(mock_func)
    mock_sleep.assert_called_once_with(0.7)


# ---------------------------------------------------------------------------
# RetryStats
# ---------------------------------------------------------------------------


def test_stats_initial_values() -> None:
    s = RetryStrategy()
    assert s.stats.total_calls == 0
    assert s.stats.total_retries == 0
    assert s.stats.successful_retries == 0
    assert s.stats.failed_calls == 0
    assert s.stats.errors_by_type == {}
    assert s.stats.total_delay_seconds == 0.0


@pytest.mark.asyncio
async def test_stats_counts_successful_call() -> None:
    s = RetryStrategy()
    await s.execute_with_retry(AsyncMock(return_value="ok"))
    assert s.stats.total_calls == 1
    assert s.stats.total_retries == 0
    assert s.stats.successful_retries == 0
    assert s.stats.failed_calls == 0


@pytest.mark.asyncio
async def test_stats_counts_successful_retry() -> None:
    s = RetryStrategy(base_delay=0)
    mock_func = AsyncMock(side_effect=[TransientError(), "ok"])
    await s.execute_with_retry(mock_func)
    assert s.stats.total_calls == 1
    assert s.stats.total_retries == 1
    assert s.stats.successful_retries == 1
    assert s.stats.failed_calls == 0
    assert s.stats.errors_by_type == {"TransientError": 1}


@pytest.mark.asyncio
async def test_stats_counts_failed_call() -> None:
    s = RetryStrategy(max_retries=2, base_delay=0)
    mock_func = AsyncMock(side_effect=TransientError())
    with pytest.raises(TransientError):
        await s.execute_with_retry(mock_func)
    assert s.stats.total_calls == 1
    assert s.stats.total_retries == 2
    assert s.stats.successful_retries == 0
    assert s.stats.failed_calls == 1
    assert s.stats.errors_by_type == {"TransientError": 3}


@pytest.mark.asyncio
async def test_stats_counts_non_retryable_as_failed() -> None:
    s = RetryStrategy()
    with pytest.raises(PermanentError):
        await s.execute_with_retry(AsyncMock(side_effect=PermanentError()))
    assert s.stats.total_calls == 1
    assert s.stats.total_retries == 0
    assert s.stats.failed_calls == 1
    assert s.stats.errors_by_type == {"PermanentError": 1}


@pytest.mark.asyncio
async def test_stats_accumulates_across_multiple_calls() -> None:
    s = RetryStrategy(base_delay=0)
    await s.execute_with_retry(AsyncMock(return_value="ok"))
    await s.execute_with_retry(AsyncMock(side_effect=[TransientError(), "ok"]))
    assert s.stats.total_calls == 2
    assert s.stats.successful_retries == 1


@pytest.mark.asyncio
async def test_stats_tracks_errors_by_type() -> None:
    s = RetryStrategy(base_delay=0, max_retries=2)
    mock_func = AsyncMock(side_effect=[TransientError(), NetworkError(), "ok"])
    with patch("crawler.retry_strategy.asyncio.sleep"):
        await s.execute_with_retry(mock_func)
    assert s.stats.errors_by_type.get("TransientError", 0) == 1
    assert s.stats.errors_by_type.get("NetworkError", 0) == 1


@pytest.mark.asyncio
async def test_stats_tracks_total_delay() -> None:
    s = RetryStrategy(base_delay=1.0, backoff_factor=1.0, max_retries=2)
    mock_func = AsyncMock(side_effect=[TransientError(), TransientError(), "ok"])
    with patch("crawler.retry_strategy.asyncio.sleep"):
        await s.execute_with_retry(mock_func)
    assert s.stats.total_delay_seconds == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_stats_avg_delay_per_retry() -> None:
    s = RetryStrategy(base_delay=1.0, backoff_factor=1.0, max_retries=2)
    mock_func = AsyncMock(side_effect=[TransientError(), TransientError(), "ok"])
    with patch("crawler.retry_strategy.asyncio.sleep"):
        await s.execute_with_retry(mock_func)
    assert s.stats.avg_delay_per_retry == pytest.approx(1.0)


def test_stats_avg_delay_zero_when_no_retries() -> None:
    assert RetryStrategy().stats.avg_delay_per_retry == 0.0


# ---------------------------------------------------------------------------
# context logging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_in_retry_warning(caplog) -> None:
    import logging

    mock_func = AsyncMock(side_effect=[TransientError(), "ok"])
    with patch("crawler.retry_strategy.asyncio.sleep"):
        with caplog.at_level(logging.WARNING, logger="crawler.retry_strategy"):
            await RetryStrategy(max_retries=1, base_delay=0).execute_with_retry(
                mock_func, context="https://example.com"
            )
    assert "https://example.com" in caplog.text


@pytest.mark.asyncio
async def test_context_in_exhaustion_warning(caplog) -> None:
    import logging

    mock_func = AsyncMock(side_effect=[TransientError(), TransientError()])
    with patch("crawler.retry_strategy.asyncio.sleep"):
        with caplog.at_level(logging.WARNING, logger="crawler.retry_strategy"):
            with pytest.raises(TransientError):
                await RetryStrategy(max_retries=1, base_delay=0).execute_with_retry(
                    mock_func, context="https://example.com"
                )
    assert "https://example.com" in caplog.text
    assert "exhausted" in caplog.text


@pytest.mark.asyncio
async def test_context_in_recovery_log(caplog) -> None:
    import logging

    mock_func = AsyncMock(side_effect=[TransientError(), "ok"])
    with patch("crawler.retry_strategy.asyncio.sleep"):
        with caplog.at_level(logging.INFO, logger="crawler.retry_strategy"):
            await RetryStrategy(max_retries=1, base_delay=0).execute_with_retry(
                mock_func, context="https://example.com"
            )
    assert "https://example.com" in caplog.text
    assert "recovered" in caplog.text


@pytest.mark.asyncio
async def test_no_context_uses_call_label(caplog) -> None:
    import logging

    mock_func = AsyncMock(side_effect=[TransientError(), TransientError()])
    with patch("crawler.retry_strategy.asyncio.sleep"):
        with caplog.at_level(logging.WARNING, logger="crawler.retry_strategy"):
            with pytest.raises(TransientError):
                await RetryStrategy(max_retries=1, base_delay=0).execute_with_retry(
                    mock_func
                )
    assert "call" in caplog.text
