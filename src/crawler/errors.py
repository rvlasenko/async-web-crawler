class CrawlerError(Exception):
    """Base exception for all crawler errors."""

    def __init__(self, message: str = "", status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class TransientError(CrawlerError):
    """Temporary failure that may succeed on retry: HTTP 429, 500, 503, timeouts."""


class PermanentError(CrawlerError):
    """Terminal failure that will not succeed on retry: HTTP 401, 403, 404."""


class NetworkError(CrawlerError):
    """Low-level connectivity failure: connection refused, DNS resolution error."""


class ParseError(CrawlerError):
    """Failure to parse response content."""


def classify_status_code(status: int) -> type[TransientError | PermanentError]:
    """Map an HTTP status code to a CrawlerError subclass.

    429 (Too Many Requests) is treated as transient despite being a 4xx —
    its semantics are "wait and retry", not a permanent refusal.
    All other 4xx codes are permanent. All 5xx codes are transient.
    """
    if status == 429 or status >= 500:
        return TransientError
    return PermanentError
