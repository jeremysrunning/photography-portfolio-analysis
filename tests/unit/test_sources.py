from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from io import BytesIO
from typing import BinaryIO
from urllib.parse import parse_qs, urlsplit

import pytest

from ppa.models import Asset, Gallery, Portfolio
from ppa.sources import GallerySource, SourceError, SourcePreviewUnavailableError
from ppa.sources.smugmug import SmugMugApiClient, SmugMugSource


class FakeTransport:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        parsed = urlsplit(url)
        key = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
        response = self.responses.get(key) or self.responses.get(parsed.path)
        if response is None:
            raise AssertionError(f"Unexpected URL: {url}")
        return response


class FakeGallerySource:
    """Small complete source used to exercise the public contract."""

    source_name = "fake"

    def __init__(self) -> None:
        self.preview_stream: BytesIO | None = None

    def discover_portfolio(self) -> Portfolio:
        return Portfolio("fake", "portfolio", "Fake portfolio", "https://example.test")

    def iter_galleries(self, portfolio: Portfolio) -> Iterator[Gallery]:
        assert portfolio.source == self.source_name
        yield Gallery("gallery", "Fake gallery", "https://example.test/gallery")

    def iter_assets(self, gallery: Gallery) -> Iterator[Asset]:
        yield Asset(
            "asset",
            "https://example.test/asset",
            gallery.source_id,
            preview_url="https://example.test/preview.jpg",
        )

    def enrich_asset_metadata(self, asset: Asset) -> Asset:
        return replace(asset, exif={**asset.exif, "Model": "Fake camera"})

    @contextmanager
    def open_preview(self, asset: Asset) -> Iterator[BinaryIO]:
        if not asset.preview_url:
            raise SourcePreviewUnavailableError("Preview is unavailable.")
        self.preview_stream = BytesIO(b"preview")
        with self.preview_stream:
            yield self.preview_stream

    def load_portfolio(self) -> Portfolio:
        portfolio = self.discover_portfolio()
        galleries = tuple(
            replace(gallery, assets=tuple(self.iter_assets(gallery)))
            for gallery in self.iter_galleries(portfolio)
        )
        return replace(portfolio, galleries=galleries)


def test_fake_source_exercises_complete_gallery_source_contract() -> None:
    source = FakeGallerySource()

    assert isinstance(source, GallerySource)
    discovered = source.discover_portfolio()
    assert discovered.galleries == ()
    gallery = next(source.iter_galleries(discovered))
    asset = next(source.iter_assets(gallery))
    assert source.enrich_asset_metadata(asset).exif == {"Model": "Fake camera"}

    with source.open_preview(asset) as preview:
        assert preview.read() == b"preview"
        assert not preview.closed
    assert source.preview_stream is not None
    assert source.preview_stream.closed

    loaded = source.load_portfolio()
    assert loaded.galleries[0].assets == (asset,)


def test_fake_source_normalizes_unavailable_preview() -> None:
    source = FakeGallerySource()
    asset = Asset("missing", "https://example.test/missing", "gallery")

    with (
        pytest.raises(SourcePreviewUnavailableError, match="unavailable"),
        source.open_preview(asset),
    ):
        pass


def test_smugmug_source_loads_public_metadata_and_paginates() -> None:
    responses = {
        "/api/v2!siteuser": {
            "Code": 200,
            "Response": {
                "User": {
                    "Name": "Example Photographer",
                    "NickName": "example",
                    "WebUri": "https://example.smugmug.com",
                    "Uris": {"UserAlbums": "/api/v2/user/example!albums"},
                }
            },
        },
        "/api/v2/user/example!albums": {
            "Code": 200,
            "Response": {
                "Album": [
                    {
                        "Name": "People",
                        "Uri": "/api/v2/album/album-1",
                        "WebUri": "https://example.smugmug.com/People",
                        "Description": "Portrait work",
                        "Uris": {"AlbumImages": "/api/v2/album/album-1!images"},
                    }
                ],
                "Pages": {},
            },
        },
        "/api/v2/album/album-1!images": {
            "Code": 200,
            "Response": {
                "AlbumImage": [
                    {
                        "Uri": "/api/v2/album/album-1/image/image-1",
                        "WebUri": "https://example.smugmug.com/People/i-image-1",
                        "Title": "A portrait",
                        "IsVideo": False,
                        "DateTimeOriginal": "2024-01-02T03:04:05+00:00",
                    }
                ],
                "Pages": {"NextPage": "/api/v2/album/album-1!images?count=100&start=101"},
            },
        },
        "/api/v2/album/album-1!images?count=100&start=101&APIKey=secret": {
            "Code": 200,
            "Response": {
                "AlbumImage": [
                    {
                        "Uri": "/api/v2/album/album-1/image/image-2",
                        "WebUri": "/People/i-image-2",
                        "IsVideo": False,
                    },
                    {
                        "Uri": "/api/v2/album/album-1/image/video-1",
                        "WebUri": "/People/i-video-1",
                        "IsVideo": True,
                    },
                ],
                "Pages": {},
            },
        },
        "/api/v2/image/image-1!metadata": {
            "Code": 200,
            "Response": {
                "ImageMetadata": {
                    "Uri": "/api/v2/image/image-1!metadata",
                    "Model": "Camera A",
                    "Lens": "",
                }
            },
        },
    }
    transport = FakeTransport(responses)
    client = SmugMugApiClient("https://example.smugmug.com", "secret", transport)
    source = SmugMugSource("https://example.smugmug.com", "secret", client)

    portfolio = source.load_portfolio()

    assert isinstance(source, GallerySource)
    assert portfolio.title == "Example Photographer"
    assert portfolio.source_id == "example"
    assert portfolio.galleries[0].metadata["Description"] == "Portrait work"
    assert [asset.source_id for asset in portfolio.galleries[0].assets] == [
        "image-1",
        "image-2",
    ]
    assert portfolio.galleries[0].assets[0].preview_url is None
    assert all(parse_qs(urlsplit(url).query)["APIKey"] == ["secret"] for url in transport.urls)

    asset = portfolio.galleries[0].assets[0]
    enriched = source.enrich_asset_metadata(asset)
    assert asset.exif == {}
    assert enriched.exif == {"Model": "Camera A"}
    with (
        pytest.raises(SourcePreviewUnavailableError, match="no public preview URL"),
        source.open_preview(asset),
    ):
        pass


def test_smugmug_client_rejects_repeated_pagination_link() -> None:
    transport = FakeTransport(
        {
            "/items": {
                "Code": 200,
                "Response": {
                    "Album": [],
                    "Pages": {"NextPage": "/items?count=100"},
                },
            },
            "/items?count=100&APIKey=secret": {
                "Code": 200,
                "Response": {
                    "Album": [],
                    "Pages": {"NextPage": "/items?count=100"},
                },
            },
        }
    )
    client = SmugMugApiClient("https://example.smugmug.com", "secret", transport)

    with pytest.raises(SourceError, match="repeated pagination"):
        list(client.iter_objects("/items", "Album"))
