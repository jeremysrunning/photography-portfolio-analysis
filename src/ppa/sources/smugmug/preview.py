"""Bounded production preview access for SmugMug."""

from __future__ import annotations

import io
import ipaddress
import re
import tempfile
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image, ImageOps, UnidentifiedImageError

from ppa.models import Asset
from ppa.sources.base import (
    SourceAuthenticationError,
    SourceAuthorizationError,
    SourceError,
    SourcePreviewCancelledError,
    SourcePreviewDecodeError,
    SourcePreviewDimensionMismatchError,
    SourcePreviewDimensionsTooLargeError,
    SourcePreviewOriginalRejectedError,
    SourcePreviewPayloadTooLargeError,
    SourcePreviewUnavailableError,
    SourcePreviewUnsupportedContentTypeError,
    SourceRateLimitError,
    SourceTransientError,
)
from ppa.sources.preview import (
    PRODUCTION_PREVIEW_MAXIMUM_EDGE,
    CancellationCheck,
    PreviewMetadata,
    PreviewRequest,
    PreviewResource,
    PreviewStorageMode,
)
from ppa.sources.smugmug.api import SmugMugApiClient

_DIMENSIONS = re.compile(r"(?P<width>\d+)\s*[xX]\s*(?P<height>\d+)")
_FORBIDDEN_LABELS = {"archive", "download", "largest", "original"}
_CREDENTIAL_QUERY_NAMES = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "credential",
    "key",
    "password",
    "signature",
    "token",
}
_READ_SIZE = 64 * 1024


@dataclass(frozen=True, slots=True)
class _PreviewCandidate:
    label: str
    width: int
    height: int
    content_url: str = field(repr=False)

    @property
    def longest_edge(self) -> int:
        return max(self.width, self.height)


@dataclass(frozen=True, slots=True)
class _DownloadedPreview:
    content: bytes = field(repr=False)
    content_type: str
    redirect_count: int


class PreviewResponse(Protocol):
    """Minimum response surface consumed inside the transport lifecycle."""

    headers: Any

    def read(self, size: int = -1) -> bytes: ...

    def geturl(self) -> str: ...


class PreviewTransport(Protocol):
    """Open a media response without exposing it to preview callers."""

    def open(
        self,
        url: str,
        *,
        timeout: float,
        maximum_redirects: int,
        disallowed_urls: frozenset[str],
    ) -> AbstractContextManager[PreviewResponse]: ...


class UrlLibPreviewTransport:
    """HTTPS media transport with validation on every redirect."""

    def open(
        self,
        url: str,
        *,
        timeout: float,
        maximum_redirects: int,
        disallowed_urls: frozenset[str],
    ) -> AbstractContextManager[PreviewResponse]:
        handler = _BoundedRedirectHandler(maximum_redirects, disallowed_urls)
        request = Request(
            url,
            headers={
                "Accept": "image/*",
                "User-Agent": "photography-portfolio-analysis/0.1",
            },
        )
        return build_opener(handler).open(request, timeout=timeout)


class SmugMugPreviewService:
    """Resolve, fetch, validate, and own one temporary SmugMug preview."""

    def __init__(
        self,
        client: SmugMugApiClient,
        transport: PreviewTransport | None = None,
        *,
        timeout: float = 30.0,
        maximum_redirects: int = 3,
    ) -> None:
        self.client = client
        self.transport = transport or UrlLibPreviewTransport()
        self.timeout = timeout
        self.maximum_redirects = maximum_redirects

    def open_preview(
        self,
        asset: Asset,
        request: PreviewRequest,
        *,
        is_cancelled: CancellationCheck | None = None,
    ) -> PreviewResource:
        _raise_if_cancelled(is_cancelled)
        candidate, disallowed_urls = self._resolve(asset.source_id, request)
        _raise_if_cancelled(is_cancelled)
        downloaded = self._download(candidate, disallowed_urls, request, is_cancelled)
        _raise_if_cancelled(is_cancelled)

        image: Image.Image | None = None
        temporary_path: Path | None = None
        try:
            image, orientation_swap = _decode_and_validate(
                downloaded.content,
                request=request,
                reported_width=candidate.width,
                reported_height=candidate.height,
            )
            _raise_if_cancelled(is_cancelled)
            metadata = PreviewMetadata(
                requested_maximum_edge=request.maximum_edge,
                width=image.width,
                height=image.height,
                content_type=downloaded.content_type,
                encoded_byte_count=len(downloaded.content),
                provenance="smugmug_image_size_details",
                storage_mode=request.storage_mode,
                provider_reported_width=candidate.width,
                provider_reported_height=candidate.height,
                orientation_swap_applied=orientation_swap,
            )
            if request.storage_mode is PreviewStorageMode.MEMORY:
                _raise_if_cancelled(is_cancelled)
                resource = PreviewResource.memory(metadata, image)
                image = None
            else:
                temporary_path = _write_temporary_preview(
                    downloaded.content,
                    downloaded.content_type,
                )
                image.close()
                image = None
                _raise_if_cancelled(is_cancelled)
                resource = PreviewResource.temporary_file(metadata, temporary_path)
                temporary_path = None
            return resource
        finally:
            if image is not None:
                image.close()
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _resolve(
        self,
        asset_source_id: str,
        request: PreviewRequest,
    ) -> tuple[_PreviewCandidate, frozenset[str]]:
        image_response = self.client.get_response(f"/api/v2/image/{asset_source_id}")
        image = _object(image_response, "Image")
        details_uri = _linked_uri(image, "ImageSizeDetails")
        details = self.client.get_response(details_uri)
        candidates = _extract_candidates(details)
        if not candidates:
            raise SourcePreviewUnavailableError("The source did not report preview size metadata.")

        forbidden = tuple(item for item in candidates if _forbidden_label(item.label))
        disallowed_urls = frozenset(_normalized_url(item.content_url) for item in forbidden)
        allowed = tuple(
            item
            for item in candidates
            if not _forbidden_label(item.label)
            and item.longest_edge <= request.maximum_edge
            and item.longest_edge <= PRODUCTION_PREVIEW_MAXIMUM_EDGE
        )
        if not allowed:
            if forbidden and len(forbidden) == len(candidates):
                raise SourcePreviewOriginalRejectedError(
                    "The source offered only disallowed original-like resources."
                )
            raise SourcePreviewUnavailableError(
                "The source did not report a preview within the requested maximum edge."
            )
        candidate = max(
            allowed,
            key=lambda item: (item.longest_edge, item.width, item.height),
        )
        _validate_public_https(candidate.content_url)
        if _normalized_url(candidate.content_url) in disallowed_urls:
            raise SourcePreviewOriginalRejectedError(
                "The selected preview matched a disallowed original-like resource."
            )
        return candidate, disallowed_urls

    def _download(
        self,
        candidate: _PreviewCandidate,
        disallowed_urls: frozenset[str],
        request: PreviewRequest,
        is_cancelled: CancellationCheck | None,
    ) -> _DownloadedPreview:
        try:
            with self.transport.open(
                candidate.content_url,
                timeout=self.timeout,
                maximum_redirects=self.maximum_redirects,
                disallowed_urls=disallowed_urls,
            ) as response:
                _validate_public_https(response.geturl())
                if _normalized_url(response.geturl()) in disallowed_urls:
                    raise SourcePreviewOriginalRejectedError(
                        "The preview redirected to a disallowed original-like resource."
                    )
                content_type = _content_type(response)
                if content_type not in request.accepted_content_types:
                    raise SourcePreviewUnsupportedContentTypeError(
                        "The preview response used a missing or unsupported content type."
                    )
                declared_length = _content_length(response)
                if declared_length is not None and declared_length > request.maximum_bytes:
                    raise SourcePreviewPayloadTooLargeError(
                        "The preview exceeded the requested encoded-byte limit."
                    )
                content = bytearray()
                while True:
                    _raise_if_cancelled(is_cancelled)
                    chunk = response.read(min(_READ_SIZE, request.maximum_bytes - len(content) + 1))
                    if not chunk:
                        break
                    content.extend(chunk)
                    if len(content) > request.maximum_bytes:
                        raise SourcePreviewPayloadTooLargeError(
                            "The preview exceeded the requested encoded-byte limit."
                        )
                _raise_if_cancelled(is_cancelled)
                redirect_count = int(getattr(response, "redirect_count", 0))
        except HTTPError as error:
            if error.code == 401:
                raise SourceAuthenticationError(
                    "The source rejected preview authentication."
                ) from error
            if error.code == 403:
                raise SourceAuthorizationError(
                    "The source forbids access to this preview."
                ) from error
            if error.code == 404:
                raise SourcePreviewUnavailableError(
                    "The requested preview is unavailable."
                ) from error
            if error.code == 429:
                raise SourceRateLimitError(_retry_after(error)) from error
            if error.code >= 500:
                raise SourceTransientError(
                    f"The source returned temporary HTTP {error.code} for preview access."
                ) from error
            raise SourceError(
                f"The source returned HTTP {error.code} for preview access."
            ) from error
        except SourceError:
            raise
        except (URLError, TimeoutError) as error:
            raise SourceTransientError("Could not read the temporary preview.") from error
        return _DownloadedPreview(
            content=bytes(content),
            content_type=content_type,
            redirect_count=redirect_count,
        )


class _BoundedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, maximum_redirects: int, disallowed_urls: frozenset[str]) -> None:
        self.maximum_redirects = maximum_redirects
        self.disallowed_urls = disallowed_urls
        self.redirect_count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.redirect_count += 1
        if self.redirect_count > self.maximum_redirects:
            raise SourcePreviewUnavailableError("The preview exceeded the redirect limit.")
        resolved = urljoin(req.full_url, newurl)
        _validate_public_https(resolved)
        if _normalized_url(resolved) in self.disallowed_urls:
            raise SourcePreviewOriginalRejectedError(
                "The preview redirected to a disallowed original-like resource."
            )
        return super().redirect_request(req, fp, code, msg, headers, resolved)


def _decode_and_validate(
    content: bytes,
    *,
    request: PreviewRequest,
    reported_width: int,
    reported_height: int,
) -> tuple[Image.Image, bool]:
    if max(reported_width, reported_height) > request.maximum_edge:
        raise SourcePreviewDimensionsTooLargeError(
            "Provider-reported dimensions exceeded the requested maximum edge."
        )
    if max(reported_width, reported_height) > PRODUCTION_PREVIEW_MAXIMUM_EDGE:
        raise SourcePreviewDimensionsTooLargeError(
            "Provider-reported dimensions exceeded the production maximum edge."
        )
    try:
        with Image.open(io.BytesIO(content)) as opened:
            if max(opened.size) > request.maximum_edge:
                raise SourcePreviewDimensionsTooLargeError(
                    "Decoded preview dimensions exceeded the requested maximum edge."
                )
            if max(opened.size) > PRODUCTION_PREVIEW_MAXIMUM_EDGE:
                raise SourcePreviewDimensionsTooLargeError(
                    "Decoded preview dimensions exceeded the production maximum edge."
                )
            opened.load()
            decoded = ImageOps.exif_transpose(opened).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise SourcePreviewDecodeError(
            "The preview could not be decoded as a supported image."
        ) from error

    if max(decoded.size) > request.maximum_edge:
        decoded.close()
        raise SourcePreviewDimensionsTooLargeError(
            "Decoded preview dimensions exceeded the requested maximum edge."
        )
    if max(decoded.size) > PRODUCTION_PREVIEW_MAXIMUM_EDGE:
        decoded.close()
        raise SourcePreviewDimensionsTooLargeError(
            "Decoded preview dimensions exceeded the production maximum edge."
        )
    reported = (reported_width, reported_height)
    orientation_swap = (
        decoded.size == (reported_height, reported_width) and decoded.size != reported
    )
    if decoded.size != reported and not orientation_swap:
        decoded.close()
        raise SourcePreviewDimensionMismatchError(
            "Provider-reported and decoded preview dimensions materially disagreed."
        )
    return decoded, orientation_swap


def _write_temporary_preview(content: bytes, content_type: str) -> Path:
    suffixes = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix="ppa-preview-",
            suffix=suffixes.get(content_type, ".img"),
            delete=False,
        ) as handle:
            path = Path(handle.name)
            handle.write(content)
        return path
    except BaseException:
        if path is not None:
            path.unlink(missing_ok=True)
        raise


def _raise_if_cancelled(is_cancelled: CancellationCheck | None) -> None:
    if is_cancelled is not None and is_cancelled():
        raise SourcePreviewCancelledError("Temporary preview access was cancelled.")


def _content_type(response: PreviewResponse) -> str:
    headers = response.headers
    get_content_type = getattr(headers, "get_content_type", None)
    if callable(get_content_type):
        value = get_content_type()
    else:
        raw = headers.get("Content-Type")
        value = raw.split(";", 1)[0].strip() if isinstance(raw, str) else ""
    return value.casefold() if isinstance(value, str) else ""


def _content_length(response: PreviewResponse) -> int | None:
    raw = response.headers.get("Content-Length")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError) as error:
        raise SourcePreviewUnavailableError(
            "The preview response contained an invalid content length."
        ) from error
    if value < 0:
        raise SourcePreviewUnavailableError(
            "The preview response contained an invalid content length."
        )
    return value


def _retry_after(error: HTTPError) -> int | None:
    raw = error.headers.get("Retry-After")
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def _extract_candidates(value: Any, path: str = "response") -> tuple[_PreviewCandidate, ...]:
    candidates: list[_PreviewCandidate] = []
    if isinstance(value, dict):
        direct = _direct_candidate(value, path)
        if direct is not None:
            candidates.append(direct)
        for key, item in value.items():
            if isinstance(item, str) and key.casefold().endswith("url"):
                candidate = _prefixed_candidate(value, key, item, f"{path}.{key}")
                if candidate is not None:
                    candidates.append(candidate)
            candidates.extend(_extract_candidates(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            candidates.extend(_extract_candidates(item, f"{path}[{index}]"))
    return tuple(
        sorted(
            set(candidates),
            key=lambda item: (item.longest_edge, item.width, item.height, item.label),
        )
    )


def _direct_candidate(value: dict[str, Any], label: str) -> _PreviewCandidate | None:
    url = _casefold_value(value, "url")
    width = _integer(_casefold_value(value, "width"))
    height = _integer(_casefold_value(value, "height"))
    if isinstance(url, str) and width and height:
        return _PreviewCandidate(label, width, height, url)
    return None


def _prefixed_candidate(
    value: dict[str, Any],
    url_key: str,
    url: str,
    label: str,
) -> _PreviewCandidate | None:
    prefix = url_key[:-3]
    width = _integer(_casefold_value(value, f"{prefix}width"))
    height = _integer(_casefold_value(value, f"{prefix}height"))
    if width and height:
        return _PreviewCandidate(label, width, height, url)
    size = _casefold_value(value, f"{prefix}size")
    match = _DIMENSIONS.search(str(size)) if size is not None else None
    if match:
        return _PreviewCandidate(
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
    query_names = {name.casefold() for name, _ in parse_qsl(parsed.query)}
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or query_names.intersection(_CREDENTIAL_QUERY_NAMES)
    ):
        raise SourcePreviewUnavailableError(
            "Temporary previews require credential-free HTTPS URLs."
        )
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return
    if not address.is_global:
        raise SourcePreviewUnavailableError(
            "The temporary preview URL did not identify a public host."
        )


def _normalized_url(url: str) -> str:
    parsed = urlsplit(url)
    return parsed._replace(fragment="").geturl()


def _object(response: dict[str, Any], name: str) -> dict[str, Any]:
    value = response.get(name)
    if not isinstance(value, dict):
        raise SourceError(f"The source response did not include {name}.")
    return value


def _linked_uri(value: dict[str, Any], name: str) -> str:
    uris = value.get("Uris")
    if not isinstance(uris, dict):
        raise SourcePreviewUnavailableError("The source did not link to preview size details.")
    linked = uris.get(name)
    if isinstance(linked, str):
        return linked
    if isinstance(linked, dict) and isinstance(linked.get("Uri"), str):
        return linked["Uri"]
    raise SourcePreviewUnavailableError("The source did not link to preview size details.")
