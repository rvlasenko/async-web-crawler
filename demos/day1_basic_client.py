import asyncio
import time

from crawler.async_crawler import AsyncCrawler


URLS = [
    "https://example.com",
    "https://httpbin.org/delay/1",
    "https://httpbin.org/delay/2",
    "https://httpbin.org/status/404",
    "https://wrong-domain-example-12345.com",
]


def print_results(results: dict) -> None:
    print("\nRESULTS:\n")

    for url, result in results.items():
        print(
            url,
            "| success:",
            result["success"],
            "| status:",
            result["status"],
            "| error:",
            result["error"],
        )


async def fetch_sequentially() -> tuple[dict, float]:
    async with AsyncCrawler(
        max_concurrent=3,
        timeout_seconds=5,
    ) as crawler:
        start_time = time.perf_counter()

        results_list = []

        for url in URLS:
            result = await crawler.fetch_url(url)
            results_list.append(result)

        elapsed_time = time.perf_counter() - start_time

    results = {result["url"]: result for result in results_list}

    return results, elapsed_time


async def fetch_in_parallel() -> tuple[dict, float]:
    async with AsyncCrawler(
        max_concurrent=3,
        timeout_seconds=5,
    ) as crawler:
        start_time = time.perf_counter()

        results = await crawler.fetch_urls(URLS)

        elapsed_time = time.perf_counter() - start_time

    return results, elapsed_time


async def main():
    sequential_results, sequential_time = await fetch_sequentially()
    parallel_results, parallel_time = await fetch_in_parallel()

    print("\nSEQUENTIAL FETCH")
    print_results(sequential_results)
    print(f"\nSequential time: {sequential_time:.2f} seconds")

    print("\nPARALLEL FETCH")
    print_results(parallel_results)
    print(f"\nParallel time: {parallel_time:.2f} seconds")

    if parallel_time > 0:
        print(
            f"\nParallel is approximately {sequential_time / parallel_time:.2f}x faster"
        )


if __name__ == "__main__":
    asyncio.run(main())
