import argparse
import asyncio
import sys
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from demos.day1_basic_client import main as run_day1
from demos.day2_html_parser import main as run_day2
from demos.day3_crawler_queue import main as run_day3
from demos.day4_polite_crawler import main as run_day4


DemoRunner = Callable[[], Coroutine[Any, Any, None]]


DEMOS: dict[str, DemoRunner] = {
    "day1": run_day1,
    "day2": run_day2,
    "day3": run_day3,
    "day4": run_day4,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run async crawler demo scripts.")

    parser.add_argument(
        "demo",
        choices=tuple(DEMOS.keys()),
        help="Demo to run.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    demo_name: str = args.demo
    demo = DEMOS[demo_name]

    asyncio.run(demo())


if __name__ == "__main__":
    main()
