"""Experimental SmugMug size resolution isolated from production source code."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ppa.sources import (
    SourceAuthenticationError,
    SourceError,
    SourcePreviewUnavailableError,
    SourceTransientError,
)
from ppa.sources.smugmug import SmugMugApiClient

_DIMENSIONS = re.compile(r"(?P<width>\d+)\s*[xX]\s*(?P<height>\d+)")
_FORBIDDEN_LABELS = {"archive", "download", "largest", "original"}


@dataclass(frozen=True, slots=True)
class PreviewCandidate:
    """One provider-reported bounded media size."""

    label: str
    width: int
    height: int
    content_url: str = field(repr=False)

    @property
    def longest_edge(self) -> int:
        return max(self.width, self.height)


@dataclass(frozen=True, slots=True)
class PreviewPayload:
    """Bounded preview bytes and non-secret transport observations."""

    content: bytes = field(repr=False)
    content_type: str
    reported_width: int
    reported_height: int
    bytes_transferred: int
    redirect_count: int


class ExperimentalSmugMugSizeResolver:
    """Resolve official size details without changing the production contract."""

    def __init__(
        self,
        site_url: str,
        api_key: str,
        *,
        maximum_edge: int = 1280,
        maximum_bytes: int = 8_000_000,
        timeout: float = 30.0,
        maximum_redirects: int = 3,
    ) -> None:
        if not 1 <= maximum_edge <= 2048:
            raise ValueError("maximum_edge must be between 1 and 2048")
        if maximum_bytes < 1:
            raise ValueError("maximum_bytes must be positive")
        self.client = SmugMugApiClient(site_url, api_key)
        self.maximum_edge = maximum_edge
        self.maximum_bytes = maximum_bytes
        self.timeout = timeout
        self.redirect_handler = _BoundedRedirectHandler(maximum_redirects)

    def candidates(self, asset_source_id: str) -> tuple[PreviewCandidate, ...]:
        """Return non-original provider sizes within the experimental bound."""
        image_response = self.client.get_response(f"/api/v2/image/{asset_source_id}")
        image = _object(image_response, "Image")
        details_uri = _linked_uri(image, "ImageSizeDetails")
        details_response = self.client.get_response(details_uri)
        found = _extract_candidates(details_response)
        bounded = tuple(
            candidate
            for candidate in found
            if candidate.longest_edge <= self.maximum_edge and not _forbidden_label(candidate.label)
        )
        if not bounded:
            raise SourcePreviewUnavailableError(
                "SmugMug did not report a non-original preview within the configured bound."
            )
        return tuple(
            sorted(
                set(bounded),
                key=lambda item: (item.longest_edge, item.width, item.height, item.label),
            )
        )

    def resolve(
        self,
        asset_source_id: str,
        requested_edge: int,
    ) -> PreviewCandidate:
        """Select the closest provider-reported size without exceeding the request."""
        if not 1 <= requested_edge <= self.maximum_edge:
            raise ValueError("requested_edge exceeds the experimental maximum")
        candidates = self.candidates(asset_source_id)
        within_request = tuple(
            candidate for candidate in candidates if candidate.longest_edge <= requested_edge
        )
        if within_request:
            return max(within_request, key=lambda item: item.longest_edge)
        raise SourcePreviewUnavailableError(
            "SmugMug did not report a preview within the requested maximum edge."
        )

    def fetch(self, candidate: PreviewCandidate) -> PreviewPayload:
        """Fetch one preview with HTTPS, redirect, and byte limits."""
        _validate_public_https(candidate.content_url)
        self.redirect_handler.reset()
        opener = build_opener(self.redirect_handler)
        request = Request(
            candidate.content_url,
            headers={
                "Accept": "image/*",
                "User-Agent": "photography-portfolio-analysis-research/0.1",
            },
        )
        try:
            with opener.open(request, timeout=self.timeout) as response:
                final_url = response.geturl()
                _validate_public_https(final_url)
                content_type = response.headers.get_content_type()
                if not content_type.startswith("image/"):
                    raise SourcePreviewUnavailableError(
                        "Preview response did not use an image content type."
                    )
                declared_length = response.headers.get("Content-Length")
                if declared_length and int(declared_length) > self.maximum_bytes:
                    raise SourcePreviewUnavailableError(
                        "Preview exceeded the experimental byte allowance."
                    )
                content = response.read(self.maximum_bytes + 1)
        except HTTPError as error:
            if error.code in {401, 403}:
                raise SourceAuthenticationError(
                    "The source rejected experimental preview access."
                ) from error
            if error.code == 404:
                raise SourcePreviewUnavailableError(
                    "The experimental preview was unavailable."
                ) from error
            if error.code == 429 or error.code >= 500:
                raise SourceTransientError(
                    f"Experimental preview request returned HTTP {error.code}."
                ) from error
            raise SourceError(
                f"Experimental preview request returned HTTP {error.code}."
            ) from error
        except (URLError, TimeoutError) as error:
            raise SourceTransientError("Could not fetch the experimental preview.") from error
        if len(content) > self.maximum_bytes:
            raise SourcePreviewUnavailableError("Preview exceeded the experimental byte allowance.")
        return PreviewPayload(
            content=content,
            content_type=content_type,
            reported_width=candidate.width,
            reported_height=candidate.height,
            bytes_transferred=len(content),
            redirect_count=self.redirect_handler.redirect_count,
        )


class _BoundedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, maximum_redirects: int) -> None:
        self.maximum_redirects = maximum_redirects
        self.redirect_count = 0

    def reset(self) -> None:
        self.redirect_count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.redirect_count += 1
        if self.redirect_count > self.maximum_redirects:
            raise SourcePreviewUnavailableError("Preview exceeded the experimental redirect limit.")
        resolved = urljoin(req.full_url, newurl)
        _validate_public_https(resolved)
        return super().redirect_request(req, fp, code, msg, headers, resolved)


def _extract_candidates(value: Any, path: str = "response") -> tuple[PreviewCandidate, ...]:
    candidates: list[PreviewCandidate] = []
    if isinstance(value, dict):
        direct = _direct_candidate(value, path)
        if direct is not None:
            candidates.append(direct)
        for key, item in value.items():
            if isinstance(item, str) and key.casefold().endswith("url"):
                prefixed = _prefixed_candidate(value, key, item, f"{path}.{key}")
                if prefixed is not None:
                    candidates.append(prefixed)
            candidates.extend(_extract_candidates(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            candidates.extend(_extract_candidates(item, f"{path}[{index}]"))
    return tuple(candidates)


def _direct_candidate(value: dict[str, Any], label: str) -> PreviewCandidate | None:
    url = _casefold_value(value, "url")
    width = _integer(_casefold_value(value, "width"))
    height = _integer(_casefold_value(value, "height"))
    if isinstance(url, str) and width and height:
        return PreviewCandidate(label, width, height, url)
    return None


def _prefixed_candidate(
    value: dict[str, Any],
    url_key: str,
    url: str,
    label: str,
) -> PreviewCandidate | None:
    prefix = url_key[:-3]
    width = _integer(_casefold_value(value, f"{prefix}width"))
    height = _integer(_casefold_value(value, f"{prefix}height"))
    if width and height:
        return PreviewCandidate(label, width, height, url)
    size = _casefold_value(value, f"{prefix}size")
    match = _DIMENSIONS.search(str(size)) if size is not None else None
    if match:
        return PreviewCandidate(
            label,
            int(match.group("width")),
            int(match.group("height")),
            url,
        )
    return None


def _casefold_value(value: dict[str, Any], name: str) -> Any:
    target = name.casefold()
    for key, item in value.items():
        if key.casefold() == target:
            return item
    return None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    return None


def _forbidden_label(label: str) -> bool:
    normalized = label.casefold()
    return any(word in normalized for word in _FORBIDDEN_LABELS)


def _validate_public_https(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SourcePreviewUnavailableError(
            "Experimental previews require credential-free HTTPS URLs."
        )
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return
    if not address.is_global:
        raise SourcePreviewUnavailableError(
            "Experimental preview URL did not identify a public host."
        )


def _object(response: dict[str, Any], name: str) -> dict[str, Any]:
    value = response.get(name)
    if not isinstance(value, dict):
        raise SourceError(f"SmugMug response did not include {name}.")
    return value


def _linked_uri(value: dict[str, Any], name: str) -> str:
    uris = value.get("Uris")
    if not isinstance(uris, dict):
        raise SourcePreviewUnavailableError(
            "SmugMug did not link to experimental preview size details."
        )
    linked = uris.get(name)
    if isinstance(linked, str):
        return linked
    if isinstance(linked, dict) and isinstance(linked.get("Uri"), str):
        return linked["Uri"]
    raise SourcePreviewUnavailableError(
        "SmugMug did not link to experimental preview size details."
    )
