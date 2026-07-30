import io
import subprocess
import sys
import tempfile
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest
from PIL import Image

from ppa.models import Asset, SourceReference
from ppa.sources import (
    PRODUCTION_PREVIEW_MAXIMUM_BYTES,
    PreviewMetadata,
    PreviewRequest,
    PreviewStorageMode,
    SourceAuthenticationError,
    SourceAuthorizationError,
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
from ppa.sources.smugmug.preview import (
    SmugMugPreviewService,
    _BoundedRedirectHandler,
)


def _asset() -> Asset:
    return Asset(SourceReference("asset-1", "https://example.test/asset-1"))


def _image_bytes(
    size: tuple[int, int] = (256, 192),
    *,
    orientation: int | None = None,
) -> bytes:
    output = io.BytesIO()
    exif = Image.Exif()
    if orientation is not None:
        exif[274] = orientation
    Image.new("RGB", size, (20, 100, 180)).save(output, "JPEG", exif=exif)
    return output.getvalue()


class FakeClient:
    def __init__(self, sizes: dict | None = None) -> None:
        self.sizes = sizes or {
            "SmallImageUrl": "https://cdn.example.test/small.jpg",
            "SmallImageWidth": 256,
            "SmallImageHeight": 192,
        }
        self.calls: list[str] = []

    def get_response(self, uri: str):
        self.calls.append(uri)
        if uri == "/api/v2/image/asset-1":
            return {
                "Image": {
                    "Uris": {"ImageSizeDetails": {"Uri": "/api/v2/image/asset-1!sizedetails"}}
                }
            }
        if uri == "/api/v2/image/asset-1!sizedetails":
            return {"ImageSizeDetails": self.sizes}
        raise AssertionError(f"unexpected API URI: {uri}")


class FakeResponse:
    def __init__(
        self,
        content: bytes,
        *,
        content_type: str | None = "image/jpeg",
        content_length: str | None = None,
        final_url: str = "https://cdn.example.test/small.jpg",
        read_size: int | None = None,
    ) -> None:
        self._stream = io.BytesIO(content)
        self._read_size = read_size
        self.headers = Message()
        if content_type is not None:
            self.headers["Content-Type"] = content_type
        if content_length is not None:
            self.headers["Content-Length"] = content_length
        self.final_url = final_url
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if self._read_size is not None:
            size = min(size, self._read_size)
        return self._stream.read(size)

    def geturl(self) -> str:
        return self.final_url

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True
        self._stream.close()


class FakeTransport:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls = 0

    def open(self, url, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.response


def _service(
    *,
    sizes: dict | None = None,
    response: FakeResponse | None = None,
    error: Exception | None = None,
) -> tuple[SmugMugPreviewService, FakeClient, FakeTransport]:
    client = FakeClient(sizes)
    transport = FakeTransport(response or FakeResponse(_image_bytes()), error)
    return SmugMugPreviewService(client, transport), client, transport


def test_preview_request_enforces_production_bounds() -> None:
    request = PreviewRequest(512)

    assert request.maximum_bytes == PRODUCTION_PREVIEW_MAXIMUM_BYTES
    assert request.storage_mode is PreviewStorageMode.MEMORY
    with pytest.raises(ValueError, match="maximum_edge"):
        PreviewRequest(1025)
    with pytest.raises(ValueError, match="maximum_bytes"):
        PreviewRequest(256, maximum_bytes=PRODUCTION_PREVIEW_MAXIMUM_BYTES + 1)


def test_validation_script_runs_directly_without_research_package_import() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/validate_preview_lifecycle.py", "--help"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "sample-size" in result.stdout


def test_memory_resource_returns_metadata_and_releases_decoded_image() -> None:
    service, _, _ = _service()

    with service.open_preview(_asset(), PreviewRequest(256)) as resource:
        shared_image = resource.image
        assert shared_image is resource.image
        assert resource.metadata == PreviewMetadata(
            256,
            256,
            192,
            "image/jpeg",
            len(_image_bytes()),
            "smugmug_image_size_details",
            PreviewStorageMode.MEMORY,
            256,
            192,
            False,
        )
        assert not hasattr(resource, "encoded_bytes")
        assert not hasattr(resource, "encoded_stream")

    assert resource.closed
    with pytest.raises(RuntimeError, match="closed"):
        _ = resource.image
    with pytest.raises(ValueError):
        shared_image.getpixel((0, 0))
    resource.close()


def test_temporary_file_is_neutral_and_removed_after_success_and_consumer_failure() -> None:
    service, _, _ = _service()
    request = PreviewRequest(256, storage_mode=PreviewStorageMode.TEMPORARY_FILE)

    with (
        pytest.raises(RuntimeError, match="consumer"),
        service.open_preview(_asset(), request) as resource,
    ):
        path = resource.temporary_path
        assert path.is_file()
        assert path.parent == Path(tempfile.gettempdir())
        assert path.name.startswith("ppa-preview-")
        assert "asset" not in path.name
        assert "secret" not in path.name
        with pytest.raises(RuntimeError, match="temporary-file-backed"):
            _ = resource.image
        raise RuntimeError("consumer failed")

    assert not path.exists()
    resource.close()


def test_exact_dimensions_smaller_preview_and_no_upscaling() -> None:
    sizes = {
        "TinyImageUrl": "https://cdn.example.test/tiny.jpg",
        "TinyImageWidth": 128,
        "TinyImageHeight": 96,
        "LargeImageUrl": "https://cdn.example.test/large.jpg",
        "LargeImageWidth": 512,
        "LargeImageHeight": 384,
    }
    service, _, transport = _service(
        sizes=sizes,
        response=FakeResponse(
            _image_bytes((128, 96)),
            final_url="https://cdn.example.test/tiny.jpg",
        ),
    )

    with service.open_preview(_asset(), PreviewRequest(256)) as resource:
        assert resource.image.size == (128, 96)
        assert resource.metadata.provider_reported_width == 128
    assert transport.calls == 1


def test_no_candidate_at_or_below_request_is_unavailable() -> None:
    service, _, transport = _service(
        sizes={
            "LargeImageUrl": "https://cdn.example.test/large.jpg",
            "LargeImageWidth": 512,
            "LargeImageHeight": 384,
        }
    )

    with pytest.raises(SourcePreviewUnavailableError, match="requested maximum"):
        service.open_preview(_asset(), PreviewRequest(256))
    assert transport.calls == 0


def test_exif_orientation_width_height_swap_is_accepted() -> None:
    service, _, _ = _service(
        sizes={
            "SmallImageUrl": "https://cdn.example.test/small.jpg",
            "SmallImageWidth": 192,
            "SmallImageHeight": 256,
        },
        response=FakeResponse(_image_bytes((192, 256), orientation=6)),
    )

    with service.open_preview(_asset(), PreviewRequest(256)) as resource:
        assert resource.image.size == (256, 192)
        assert resource.metadata.orientation_swap_applied is True


@pytest.mark.parametrize(
    ("reported", "decoded", "requested_edge", "error_type"),
    [
        ((256, 192), (250, 180), 256, SourcePreviewDimensionMismatchError),
        ((256, 192), (512, 384), 256, SourcePreviewDimensionsTooLargeError),
        ((1024, 768), (1200, 900), 1024, SourcePreviewDimensionsTooLargeError),
    ],
)
def test_material_mismatch_and_oversized_decodes_are_rejected(
    reported,
    decoded,
    requested_edge,
    error_type,
) -> None:
    service, _, _ = _service(
        sizes={
            "PreviewImageUrl": "https://cdn.example.test/preview.jpg",
            "PreviewImageWidth": reported[0],
            "PreviewImageHeight": reported[1],
        },
        response=FakeResponse(
            _image_bytes(decoded),
            final_url="https://cdn.example.test/preview.jpg",
        ),
    )

    with pytest.raises(error_type):
        service.open_preview(_asset(), PreviewRequest(requested_edge))


@pytest.mark.parametrize("label", ["Original", "Download", "Archive", "Largest"])
def test_provider_original_like_labels_are_rejected(label: str) -> None:
    service, _, transport = _service(
        sizes={
            f"{label}ImageUrl": f"https://cdn.example.test/{label}.jpg",
            f"{label}ImageWidth": 256,
            f"{label}ImageHeight": 192,
        }
    )

    with pytest.raises(SourcePreviewOriginalRejectedError, match="original-like"):
        service.open_preview(_asset(), PreviewRequest(256))
    assert transport.calls == 0


def test_redirect_handler_rejects_original_limit_and_invalid_target() -> None:
    original = "https://cdn.example.test/original.jpg"
    request = Request("https://cdn.example.test/small.jpg")
    handler = _BoundedRedirectHandler(1, frozenset({original}))

    with pytest.raises(SourcePreviewOriginalRejectedError):
        handler.redirect_request(request, None, 302, "", {}, original)
    with pytest.raises(SourcePreviewUnavailableError, match="redirect limit"):
        handler.redirect_request(
            request,
            None,
            302,
            "",
            {},
            "https://cdn.example.test/other.jpg",
        )
    handler = _BoundedRedirectHandler(3, frozenset())
    with pytest.raises(SourcePreviewUnavailableError, match="HTTPS"):
        handler.redirect_request(request, None, 302, "", {}, "http://example.test/image.jpg")


@pytest.mark.parametrize(
    "url",
    [
        "http://cdn.example.test/small.jpg",
        "https://user:password@cdn.example.test/small.jpg",
        "https://cdn.example.test/small.jpg?token=secret",
        "https://127.0.0.1/small.jpg",
    ],
)
def test_insecure_or_credential_bearing_media_urls_are_rejected(url: str) -> None:
    service, _, transport = _service(
        sizes={
            "SmallImageUrl": url,
            "SmallImageWidth": 256,
            "SmallImageHeight": 192,
        }
    )

    with pytest.raises(SourcePreviewUnavailableError):
        service.open_preview(_asset(), PreviewRequest(256))
    assert transport.calls == 0


@pytest.mark.parametrize("content_type", [None, "text/html", "image/gif"])
def test_missing_or_unsupported_content_type_is_rejected(content_type) -> None:
    service, _, _ = _service(response=FakeResponse(_image_bytes(), content_type=content_type))

    with pytest.raises(SourcePreviewUnsupportedContentTypeError):
        service.open_preview(_asset(), PreviewRequest(256))


def test_missing_content_length_is_allowed_but_declared_and_streamed_oversize_are_not() -> None:
    service, _, _ = _service(response=FakeResponse(_image_bytes(), content_length=None))
    with service.open_preview(_asset(), PreviewRequest(256)) as resource:
        assert resource.image.size == (256, 192)

    service, _, _ = _service(response=FakeResponse(_image_bytes(), content_length="999999"))
    with pytest.raises(SourcePreviewPayloadTooLargeError):
        service.open_preview(_asset(), PreviewRequest(256, maximum_bytes=1000))

    service, _, _ = _service(
        response=FakeResponse(_image_bytes(), content_length=None, read_size=100)
    )
    with pytest.raises(SourcePreviewPayloadTooLargeError):
        service.open_preview(_asset(), PreviewRequest(256, maximum_bytes=1000))


def test_corrupt_preview_closes_network_response_and_creates_no_file(tmp_path) -> None:
    response = FakeResponse(b"not an image")
    service, _, _ = _service(response=response)
    before = tuple(tmp_path.iterdir())

    with pytest.raises(SourcePreviewDecodeError):
        service.open_preview(
            _asset(),
            PreviewRequest(256, storage_mode=PreviewStorageMode.TEMPORARY_FILE),
        )

    assert response.closed
    assert tuple(tmp_path.iterdir()) == before


def test_cancellation_before_resolution_and_during_download_closes_resources() -> None:
    service, client, transport = _service()
    with pytest.raises(SourcePreviewCancelledError):
        service.open_preview(_asset(), PreviewRequest(256), is_cancelled=lambda: True)
    assert client.calls == []
    assert transport.calls == 0

    response = FakeResponse(_image_bytes(), read_size=100)
    service, _, _ = _service(response=response)
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 4

    with pytest.raises(SourcePreviewCancelledError):
        service.open_preview(_asset(), PreviewRequest(256), is_cancelled=cancelled)
    assert response.closed


def test_cancellation_after_temporary_file_creation_removes_file(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    service, _, _ = _service()
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 8

    with pytest.raises(SourcePreviewCancelledError):
        service.open_preview(
            _asset(),
            PreviewRequest(256, storage_mode=PreviewStorageMode.TEMPORARY_FILE),
            is_cancelled=cancelled,
        )

    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, SourceAuthenticationError),
        (403, SourceAuthorizationError),
        (404, SourcePreviewUnavailableError),
        (429, SourceRateLimitError),
        (500, SourceTransientError),
    ],
)
def test_http_failures_are_classified_without_url_leakage(status, error_type) -> None:
    secret_url = "https://cdn.example.test/small.jpg?private=do-not-log"
    error = HTTPError(secret_url, status, "provider detail", {}, None)
    service, _, _ = _service(error=error)

    with pytest.raises(error_type) as raised:
        service.open_preview(_asset(), PreviewRequest(256))

    assert "do-not-log" not in str(raised.value)
    assert secret_url not in str(raised.value)


@pytest.mark.parametrize("error", [URLError("secret-url"), TimeoutError("secret-url")])
def test_network_failures_are_transient_and_sanitized(error) -> None:
    service, _, _ = _service(error=error)

    with pytest.raises(SourceTransientError) as raised:
        service.open_preview(_asset(), PreviewRequest(256))

    assert "secret-url" not in str(raised.value)
