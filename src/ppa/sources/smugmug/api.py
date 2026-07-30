"""Small client for the public, read-only SmugMug API."""

import json
import logging
import time
from collections.abc import Callable, Iterator
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from ppa.sources.base import (
    SourceAuthenticationError,
    SourceAuthorizationError,
    SourceError,
    SourceNotFoundError,
    SourceRateLimitError,
    SourceTransientError,
)

JsonObject = dict[str, Any]
logger = logging.getLogger(__name__)


class JsonTransport(Protocol):
    """Retrieve a JSON object from a URL."""

    def get_json(self, url: str) -> JsonObject:
        """Return the decoded JSON response."""
        ...


class UrlLibJsonTransport:
    """Standard-library HTTPS JSON transport."""

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def get_json(self, url: str) -> JsonObject:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "photography-portfolio-analysis/0.1",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                value = json.load(response)
        except HTTPError as error:
            if error.code == 401:
                raise SourceAuthenticationError("The source rejected the credentials.") from error
            elif error.code == 403:
                raise SourceAuthorizationError(
                    "The source forbids access to this resource."
                ) from error
            elif error.code == 404:
                raise SourceNotFoundError("The source resource was not found.") from error
            elif error.code == 429:
                retry_after = error.headers.get("Retry-After")
                try:
                    seconds = int(retry_after) if retry_after else None
                except ValueError:
                    seconds = None
                raise SourceRateLimitError(seconds) from error
            elif error.code >= 500:
                raise SourceTransientError(
                    f"SmugMug returned temporary HTTP {error.code}."
                ) from error
            else:
                message = f"SmugMug returned HTTP {error.code}."
            raise SourceError(message) from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise SourceTransientError("Could not read a valid response from SmugMug.") from error
        if not isinstance(value, dict):
            raise SourceError("SmugMug returned an unexpected response.")
        return value


class SmugMugApiClient:
    """Navigate public SmugMug API resources without fetching image media."""

    def __init__(
        self,
        site_url: str,
        api_key: str,
        transport: JsonTransport | None = None,
        *,
        max_attempts: int = 3,
        max_retry_delay: float = 30.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        parsed = urlsplit(site_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("portfolio_url must be an absolute HTTP or HTTPS URL")
        if not api_key.strip():
            raise ValueError("api_key must not be empty")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if max_retry_delay < 0:
            raise ValueError("max_retry_delay must not be negative")
        self.site_origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        self.api_key = api_key
        self.transport = transport or UrlLibJsonTransport()
        self.max_attempts = max_attempts
        self.max_retry_delay = max_retry_delay
        self.sleeper = sleeper

    def get_response(self, uri: str) -> JsonObject:
        """Get and validate a SmugMug API response object."""
        url = self._request_url(uri)
        document = self._get_json_with_retry(url)
        code = document.get("Code")
        if isinstance(code, int) and code >= 400:
            if code == 401:
                raise SourceAuthenticationError("The source rejected the credentials.")
            if code == 403:
                raise SourceAuthorizationError("The source forbids access to this resource.")
            if code == 404:
                raise SourceNotFoundError("The source resource was not found.")
            if code == 429:
                raise SourceRateLimitError()
            if code >= 500:
                raise SourceTransientError(f"SmugMug API error {code}.")
            raise SourceError(f"SmugMug API error {code}.")
        response = document.get("Response")
        if not isinstance(response, dict):
            raise SourceError("SmugMug returned a response without normalized API data.")
        return response

    def _get_json_with_retry(self, url: str) -> JsonObject:
        for attempt in range(1, self.max_attempts + 1):
            try:
                document = self.transport.get_json(url)
                code = document.get("Code")
                if code == 429:
                    raise SourceRateLimitError()
                if isinstance(code, int) and code >= 500:
                    raise SourceTransientError(f"SmugMug API error {code}.")
                return document
            except (SourceRateLimitError, SourceTransientError) as error:
                if attempt == self.max_attempts:
                    raise
                requested_delay = (
                    float(error.retry_after)
                    if isinstance(error, SourceRateLimitError) and error.retry_after is not None
                    else float(2 ** (attempt - 1))
                )
                delay = min(requested_delay, self.max_retry_delay)
                logger.warning(
                    "smugmug_request_retry",
                    extra={
                        "attempt": attempt,
                        "max_attempts": self.max_attempts,
                        "retry_delay_seconds": delay,
                        "reason": str(error),
                    },
                )
                self.sleeper(delay)
        raise AssertionError("retry loop exhausted without returning or raising")

    def iter_objects(self, uri: str, object_name: str) -> Iterator[JsonObject]:
        """Yield every object from a paginated endpoint."""
        next_uri: str | None = self._with_query(uri, {"count": "100", "_verbosity": "1"})
        seen: set[str] = set()
        while next_uri:
            if next_uri in seen:
                raise SourceError("SmugMug returned a repeated pagination link.")
            seen.add(next_uri)
            response = self.get_response(next_uri)
            objects = response.get(object_name, [])
            if not isinstance(objects, list):
                raise SourceError(f"SmugMug returned an invalid {object_name} collection.")
            for item in objects:
                if isinstance(item, dict):
                    yield item
            pages = response.get("Pages", {})
            candidate = pages.get("NextPage") if isinstance(pages, dict) else None
            next_uri = candidate if isinstance(candidate, str) and candidate else None

    def _request_url(self, uri: str) -> str:
        absolute = urljoin(f"{self.site_origin}/", uri)
        return self._with_query(absolute, {"APIKey": self.api_key})

    @staticmethod
    def _with_query(uri: str, values: dict[str, str]) -> str:
        parsed = urlsplit(uri)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.update(values)
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
        )
