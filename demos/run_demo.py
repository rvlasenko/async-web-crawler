import argparse
import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from demos.day1_basic_client import main as run_day1
from demos.day2_html_parser import main as run_day2


DemoRunner = Callable[[], Coroutine[Any, Any, None]]


DEMOS: dict[str, DemoRunner] = {
    "day1": run_day1,
    "day2": run_day2,
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
