import asyncio
import time

import pytest

from crawler.rate_limiter import RateLimiter

# Fast tests use 10 rps → 100ms interval.
# Assertions use a 10ms tolerance below the theoretical minimum.
FAST_RPS = 10.0
FAST_INTERVAL = 1.0 / FAST_RPS
TOLERANCE = 0.01  # 10ms


# ---------------------------------------------------------------------------
# Structural / init
# ---------------------------------------------------------------------------


def test_default_values() -> None:
    rl = RateLimiter()
    assert rl.requests_per_second == 1.0
    assert rl.per_domain is True
    assert rl._min_interval == pytest.approx(1.0)


def test_custom_values() -> None:
    rl = RateLimiter(requests_per_second=5.0, per_domain=False)
    assert rl.requests_per_second == 5.0
    assert rl.per_domain is False
    assert rl._min_interval == pytest.approx(0.2)


@pytest.mark.parametrize("bad_rate", [0.0, -1.0, -0.001])
def test_invalid_rate_raises(bad_rate: float) -> None:
    with pytest.raises(ValueError, match="requests_per_second must be positive"):
        RateLimiter(requests_per_second=bad_rate)


# ---------------------------------------------------------------------------
# Single acquire — first call must not block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_acquire_no_delay_global() -> None:
    rl = RateLimiter(requests_per_second=1.0, per_domain=False)
    start = time.monotonic()
    await rl.acquire()
    assert time.monotonic() - start < 0.05


@pytest.mark.asyncio
async def test_first_acquire_no_delay_per_domain() -> None:
    rl = RateLimiter(requests_per_second=1.0, per_domain=True)
    start = time.monotonic()
    await rl.acquire("example.com")
    assert time.monotonic() - start < 0.05


# ---------------------------------------------------------------------------
# Rate enforcement — sequential calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_mode_enforces_gap() -> None:
    rl = RateLimiter(requests_per_second=FAST_RPS, per_domain=False)
    await rl.acquire()
    start = time.monotonic()
    await rl.acquire()
    assert time.monotonic() - start >= FAST_INTERVAL - TOLERANCE


@pytest.mark.asyncio
async def test_per_domain_same_domain_enforces_gap() -> None:
    rl = RateLimiter(requests_per_second=FAST_RPS, per_domain=True)
    await rl.acquire("example.com")
    start = time.monotonic()
    await rl.acquire("example.com")
    assert time.monotonic() - start >= FAST_INTERVAL - TOLERANCE


@pytest.mark.asyncio
async def test_per_domain_different_domains_do_not_block() -> None:
    rl = RateLimiter(requests_per_second=FAST_RPS, per_domain=True)
    await rl.acquire("a.com")
    start = time.monotonic()
    await rl.acquire("b.com")
    # Different domains must not wait for each other
    assert time.monotonic() - start < 0.05


@pytest.mark.asyncio
async def test_global_mode_blocks_across_domains() -> None:
    rl = RateLimiter(requests_per_second=FAST_RPS, per_domain=False)
    await rl.acquire("a.com")
    start = time.monotonic()
    await rl.acquire("b.com")
    # Global mode: domain argument is ignored, timing enforced globally
    assert time.monotonic() - start >= FAST_INTERVAL - TOLERANCE


# ---------------------------------------------------------------------------
# Domain key parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_url_is_parsed_to_domain() -> None:
    rl = RateLimiter(requests_per_second=FAST_RPS, per_domain=True)
    # Full URL and bare domain must share the same rate-limit bucket
    await rl.acquire("https://example.com/some/path")
    start = time.monotonic()
    await rl.acquire("example.com")
    assert time.monotonic() - start >= FAST_INTERVAL - TOLERANCE


@pytest.mark.asyncio
async def test_none_domain_per_domain_mode_uses_global_key() -> None:
    rl = RateLimiter(requests_per_second=FAST_RPS, per_domain=True)
    await rl.acquire(None)
    start = time.monotonic()
    await rl.acquire(None)
    assert time.monotonic() - start >= FAST_INTERVAL - TOLERANCE


@pytest.mark.asyncio
async def test_empty_domain_raises() -> None:
    rl = RateLimiter(per_domain=True)
    with pytest.raises(ValueError, match="domain must not be empty"):
        await rl.acquire("")


# ---------------------------------------------------------------------------
# Concurrency / lock correctness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_same_domain_serialized() -> None:
    rl = RateLimiter(requests_per_second=FAST_RPS, per_domain=True)

    timestamps: list[float] = []

    async def task() -> None:
        await rl.acquire("example.com")
        timestamps.append(time.monotonic())

    start = time.monotonic()
    await asyncio.gather(task(), task(), task())
    elapsed = time.monotonic() - start

    # 3 calls at 10 rps → minimum 200ms total (first is free, 2nd and 3rd wait)
    assert elapsed >= 2 * FAST_INTERVAL - TOLERANCE

    # Timestamps must be spaced at least (interval - tolerance) apart
    timestamps.sort()
    for i in range(1, len(timestamps)):
        assert timestamps[i] - timestamps[i - 1] >= FAST_INTERVAL - TOLERANCE


@pytest.mark.asyncio
async def test_concurrent_different_domains_run_in_parallel() -> None:
    rl = RateLimiter(requests_per_second=FAST_RPS, per_domain=True)

    start = time.monotonic()
    await asyncio.gather(rl.acquire("a.com"), rl.acquire("b.com"))
    elapsed = time.monotonic() - start

    # Both are first calls on their respective domains — must complete fast
    assert elapsed < 0.05


@pytest.mark.asyncio
async def test_no_lock_race_on_first_use() -> None:
    rl = RateLimiter(requests_per_second=FAST_RPS, per_domain=True)

    await asyncio.gather(*[rl.acquire("example.com") for _ in range(10)])

    # Exactly one lock must exist for the domain — no duplicate creation
    assert len(rl._locks) == 1
    assert "example.com" in rl._locks
