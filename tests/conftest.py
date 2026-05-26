from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env.testing")


@pytest.fixture
def anyio_backend():
    return "asyncio"
