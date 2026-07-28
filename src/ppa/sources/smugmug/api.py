"""Small client for the public, read-only SmugMug API."""

import json
from collections.abc import Iterator
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from ppa.sources.base import SourceError

JsonObject = dict[str, Any]


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
            if error.code in {401, 403}:
                message = "SmugMug rejected the API key or the requested portfolio is not public."
            elif error.code == 404:
                message = "SmugMug could not find the requested portfolio resource."
            elif error.code == 429:
                message = "SmugMug rate-limited the inspection; try again later."
            else:
                message = f"SmugMug returned HTTP {error.code}."
            raise SourceError(message) from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise SourceError("Could not read a valid response from SmugMug.") from error
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
    ) -> None:
        parsed = urlsplit(site_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("portfolio_url must be an absolute HTTP or HTTPS URL")
        if not api_key.strip():
            raise ValueError("api_key must not be empty")
        self.site_origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        self.api_key = api_key
        self.transport = transport or UrlLibJsonTransport()

    def get_response(self, uri: str) -> JsonObject:
        """Get and validate a SmugMug API response object."""
        url = self._request_url(uri)
        document = self.transport.get_json(url)
        code = document.get("Code")
        if isinstance(code, int) and code >= 400:
            raise SourceError(str(document.get("Message") or f"SmugMug API error {code}."))
        response = document.get("Response")
        if not isinstance(response, dict):
            raise SourceError("SmugMug returned a response without normalized API data.")
        return response

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
