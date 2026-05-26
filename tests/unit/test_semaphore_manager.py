import asyncio

import pytest

from crawler.semaphore_manager import SemaphoreManager


def test_same_domain_returns_same_semaphore() -> None:
    manager = SemaphoreManager()

    first = manager.get_domain_semaphore("example.com")
    second = manager.get_domain_semaphore("example.com")

    assert first is second


def test_different_domains_return_different_semaphores() -> None:
    manager = SemaphoreManager()

    first = manager.get_domain_semaphore("example.com")
    second = manager.get_domain_semaphore("python.org")

    assert first is not second


def test_domain_lookup_is_case_insensitive() -> None:
    manager = SemaphoreManager()

    first = manager.get_domain_semaphore("Example.com")
    second = manager.get_domain_semaphore("example.com")

    assert first is second


@pytest.mark.asyncio
async def test_active_task_count_tracks_acquired_slots() -> None:
    manager = SemaphoreManager()

    assert manager.get_active_tasks_count() == 0

    async with manager.acquire("https://example.com/page"):
        assert manager.get_active_tasks_count() == 1

    assert manager.get_active_tasks_count() == 0


@pytest.mark.asyncio
async def test_same_domain_limit_blocks_extra_task() -> None:
    manager = SemaphoreManager(
        global_limit=5,
        per_domain_limit=2,
    )
    release_event = asyncio.Event()
    third_acquired = asyncio.Event()

    async def hold_slot() -> None:
        async with manager.acquire("https://example.com/page"):
            await release_event.wait()

    async def wait_for_slot() -> None:
        async with manager.acquire("https://example.com/other"):
            third_acquired.set()

    first_task = asyncio.create_task(hold_slot())
    second_task = asyncio.create_task(hold_slot())

    await asyncio.sleep(0)

    third_task = asyncio.create_task(wait_for_slot())

    await asyncio.sleep(0)

    assert third_acquired.is_set() is False

    release_event.set()

    await asyncio.wait_for(third_acquired.wait(), timeout=1)
    await asyncio.gather(first_task, second_task, third_task)


@pytest.mark.asyncio
async def test_global_limit_blocks_extra_task_across_domains() -> None:
    manager = SemaphoreManager(
        global_limit=2,
        per_domain_limit=2,
    )
    release_event = asyncio.Event()
    third_acquired = asyncio.Event()

    async def hold_slot(url: str) -> None:
        async with manager.acquire(url):
            await release_event.wait()

    async def wait_for_slot() -> None:
        async with manager.acquire("https://third.example/page"):
            third_acquired.set()

    first_task = asyncio.create_task(hold_slot("https://first.example/page"))
    second_task = asyncio.create_task(hold_slot("https://second.example/page"))

    await asyncio.sleep(0)

    third_task = asyncio.create_task(wait_for_slot())

    await asyncio.sleep(0)

    assert third_acquired.is_set() is False

    release_event.set()

    await asyncio.wait_for(third_acquired.wait(), timeout=1)
    await asyncio.gather(first_task, second_task, third_task)


def test_different_hosts_same_port_get_separate_semaphores() -> None:
    manager = SemaphoreManager(global_limit=10, per_domain_limit=2)

    sem_a = manager.get_domain_semaphore("site-a.com:8080")
    sem_b = manager.get_domain_semaphore("site-b.com:8080")

    assert sem_a is not sem_b, (
        "Hosts with the same port must not share a semaphore; "
        "sharing would allow site-a to consume site-b's concurrency slots"
    )
