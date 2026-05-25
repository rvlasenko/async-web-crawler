import pytest

from crawler.errors import (
    CrawlerError,
    NetworkError,
    ParseError,
    PermanentError,
    TransientError,
    classify_status_code,
)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


def test_transient_error_is_crawler_error() -> None:
    assert issubclass(TransientError, CrawlerError)


def test_permanent_error_is_crawler_error() -> None:
    assert issubclass(PermanentError, CrawlerError)


def test_network_error_is_crawler_error() -> None:
    assert issubclass(NetworkError, CrawlerError)


def test_parse_error_is_crawler_error() -> None:
    assert issubclass(ParseError, CrawlerError)


def test_catch_all_via_crawler_error() -> None:
    with pytest.raises(CrawlerError):
        raise TransientError("server busy")


def test_crawler_error_stores_status() -> None:
    exc = CrawlerError("fail", status=503)
    assert exc.status == 503


def test_crawler_error_status_defaults_to_none() -> None:
    exc = CrawlerError("fail")
    assert exc.status is None


def test_subclass_inherits_status_field() -> None:
    exc = TransientError("timeout", status=429)
    assert exc.status == 429
    assert str(exc) == "timeout"


def test_subclass_without_status_defaults_to_none() -> None:
    exc = PermanentError("not found")
    assert exc.status is None


# ---------------------------------------------------------------------------
# classify_status_code — known transient
# ---------------------------------------------------------------------------


def test_429_is_transient() -> None:
    assert classify_status_code(429) is TransientError


def test_500_is_transient() -> None:
    assert classify_status_code(500) is TransientError


def test_502_is_transient() -> None:
    assert classify_status_code(502) is TransientError


def test_503_is_transient() -> None:
    assert classify_status_code(503) is TransientError


def test_504_is_transient() -> None:
    assert classify_status_code(504) is TransientError


# ---------------------------------------------------------------------------
# classify_status_code — known permanent
# ---------------------------------------------------------------------------


def test_401_is_permanent() -> None:
    assert classify_status_code(401) is PermanentError


def test_403_is_permanent() -> None:
    assert classify_status_code(403) is PermanentError


def test_404_is_permanent() -> None:
    assert classify_status_code(404) is PermanentError


# ---------------------------------------------------------------------------
# classify_status_code — unknown codes
# ---------------------------------------------------------------------------


def test_unknown_5xx_is_transient() -> None:
    assert classify_status_code(599) is TransientError


def test_unknown_4xx_is_permanent() -> None:
    assert classify_status_code(422) is PermanentError


def test_410_is_permanent() -> None:
    assert classify_status_code(410) is PermanentError


# ---------------------------------------------------------------------------
# classify_status_code — boundary 4xx / 5xx
# ---------------------------------------------------------------------------


def test_499_is_permanent() -> None:
    assert classify_status_code(499) is PermanentError


def test_500_boundary_is_transient() -> None:
    assert classify_status_code(500) is TransientError


def test_400_is_permanent() -> None:
    assert classify_status_code(400) is PermanentError


# ---------------------------------------------------------------------------
# classify_status_code — return type is usable
# ---------------------------------------------------------------------------


def test_result_is_subclass_of_crawler_error() -> None:
    assert issubclass(classify_status_code(503), CrawlerError)


def test_result_can_be_instantiated() -> None:
    cls = classify_status_code(503)
    exc = cls("server down", status=503)
    assert isinstance(exc, CrawlerError)
    assert exc.status == 503
