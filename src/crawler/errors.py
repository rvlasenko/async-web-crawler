class CrawlerError(Exception):
    """Base exception for all crawler errors."""


class TransientError(CrawlerError):
    """Temporary failure that may succeed on retry: HTTP 429, 500, 503, timeouts."""


class PermanentError(CrawlerError):
    """Terminal failure that will not succeed on retry: HTTP 401, 403, 404."""


class NetworkError(CrawlerError):
    """Low-level connectivity failure: connection refused, DNS resolution error."""


class ParseError(CrawlerError):
    """Failure to parse response content."""
