import logging
from collections.abc import Iterator
from dataclasses import replace
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image

from ppa.models import (
    Asset,
    AssetMetadata,
    Gallery,
    MediaType,
    Portfolio,
    RationalValue,
    SourceReference,
)
from ppa.sources import (
    GallerySource,
    PreviewMetadata,
    PreviewRequest,
    PreviewResource,
    PreviewStorageMode,
    SourceAuthorizationError,
    SourceError,
    SourcePreviewUnavailableError,
    SourceRateLimitError,
    SourceTransientError,
    load_portfolio,
)
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
        return Portfolio(
            "fake",
            SourceReference("portfolio", "https://example.test"),
            "Fake portfolio",
        )

    def iter_galleries(self, portfolio: Portfolio) -> Iterator[Gallery]:
        assert portfolio.source_name == self.source_name
        yield Gallery(
            SourceReference("gallery", "https://example.test/gallery"),
            "Fake gallery",
        )

    def iter_assets(self, gallery: Gallery) -> Iterator[Asset]:
        yield Asset(
            SourceReference("asset", "https://example.test/asset"),
            AssetMetadata(MediaType.PHOTOGRAPH),
            preview_url="https://example.test/preview.jpg",
        )

    def enrich_asset_metadata(self, asset: Asset) -> Asset:
        return replace(
            asset,
            metadata=replace(asset.metadata, exif={**asset.exif, "Model": "Fake camera"}),
        )

    def open_preview(
        self,
        asset: Asset,
        request: PreviewRequest,
        *,
        is_cancelled=None,
    ) -> PreviewResource:
        if not asset.preview_url:
            raise SourcePreviewUnavailableError("Preview is unavailable.")
        self.preview_stream = BytesIO(b"preview")
        image = Image.new("RGB", (64, 48))
        return PreviewResource.memory(
            PreviewMetadata(
                requested_maximum_edge=request.maximum_edge,
                width=64,
                height=48,
                content_type="image/jpeg",
                downloaded_content_type="image/jpeg",
                downloaded_encoded_byte_count=7,
                provenance="fake",
                storage_mode=PreviewStorageMode.MEMORY,
            ),
            image,
        )


def test_fake_source_exercises_complete_gallery_source_contract() -> None:
    source = FakeGallerySource()

    assert isinstance(source, GallerySource)
    discovered = source.discover_portfolio()
    assert discovered.galleries == ()
    gallery = next(source.iter_galleries(discovered))
    asset = next(source.iter_assets(gallery))
    assert source.enrich_asset_metadata(asset).exif == {"Model": "Fake camera"}

    with source.open_preview(asset, PreviewRequest(128)) as preview:
        assert preview.image.size == (64, 48)
        assert not preview.closed
    assert preview.closed

    loaded = load_portfolio(source)
    assert loaded.assets == (asset,)
    assert loaded.gallery_assets(loaded.galleries[0]) == (asset,)


def test_shared_loader_preserves_source_exceptions() -> None:
    failure = SourceError("Source enumeration failed.")

    class FailingGallerySource(FakeGallerySource):
        def iter_galleries(self, portfolio: Portfolio) -> Iterator[Gallery]:
            raise failure

    with pytest.raises(SourceError) as raised:
        load_portfolio(FailingGallerySource())

    assert raised.value is failure


def test_fake_source_normalizes_unavailable_preview() -> None:
    source = FakeGallerySource()
    asset = Asset(SourceReference("missing", "https://example.test/missing"))

    with (
        pytest.raises(SourcePreviewUnavailableError, match="unavailable"),
        source.open_preview(asset, PreviewRequest(128)),
    ):
        pass


def test_smugmug_source_discovers_nested_and_empty_galleries(caplog) -> None:
    responses = {
        "/api/v2!siteuser": {
            "Code": 200,
            "Response": {
                "User": {
                    "Name": "Example Photographer",
                    "NickName": "example",
                    "WebUri": "https://example.smugmug.com",
                    "Uris": {"Node": {"Uri": "/api/v2/node/root"}},
                }
            },
        },
        "/api/v2/node/root": {
            "Code": 200,
            "Response": {
                "Node": {
                    "Uri": "/api/v2/node/root",
                    "Type": "Folder",
                    "Uris": {"ChildNodes": {"Uri": "/api/v2/node/root!children"}},
                }
            },
        },
        "/api/v2/node/root!children": {
            "Code": 200,
            "Response": {
                "Node": [
                    {
                        "Uri": "/api/v2/node/folder-1",
                        "Type": "Folder",
                        "Privacy": "Public",
                        "Uris": {"ChildNodes": {"Uri": "/api/v2/node/folder-1!children"}},
                    }
                ],
                "Pages": {"NextPage": "/api/v2/node/root!children?start=2"},
            },
        },
        "/api/v2/node/root!children?start=2&APIKey=secret": {
            "Code": 200,
            "Response": {
                "Node": [
                    {
                        "Uri": "/api/v2/node/album-node-1",
                        "Type": "Album",
                        "Privacy": "Public",
                        "Uris": {"Album": {"Uri": "/api/v2/album/album-1"}},
                    },
                    {
                        "Uri": "/api/v2/node/private",
                        "Type": "Album",
                        "Privacy": "Private",
                        "Uris": {"Album": {"Uri": "/api/v2/album/private"}},
                    },
                ],
                "Pages": {},
            },
        },
        "/api/v2/node/folder-1!children": {
            "Code": 200,
            "Response": {
                "Node": [
                    {
                        "Uri": "/api/v2/node/empty-node",
                        "Type": "Album",
                        "Privacy": "Public",
                        "Uris": {"Album": {"Uri": "/api/v2/album/empty"}},
                    }
                ],
                "Pages": {},
            },
        },
        "/api/v2/album/album-1": {
            "Code": 200,
            "Response": {
                "Album": {
                    "Name": "People",
                    "Uri": "/api/v2/album/album-1",
                    "WebUri": "https://example.smugmug.com/People",
                    "Description": "Portrait work",
                    "Privacy": "Public",
                    "Uris": {"AlbumImages": {"Uri": "/api/v2/album/album-1!images"}},
                }
            },
        },
        "/api/v2/album/empty": {
            "Code": 200,
            "Response": {
                "Album": {
                    "Name": "Empty",
                    "Uri": "/api/v2/album/empty",
                    "WebUri": "https://example.smugmug.com/Empty",
                    "Privacy": "Public",
                    "Uris": {"AlbumImages": {"Uri": "/api/v2/album/empty!images"}},
                }
            },
        },
        "/api/v2/album/empty!images": {
            "Code": 200,
            "Response": {"AlbumImage": [], "Pages": {}},
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
                        "OriginalWidth": 6000,
                        "OriginalHeight": 4000,
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
                        "Width": 3000,
                        "Height": 2000,
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
                    "FocalLength": "105/2 mm",
                    "FocalLength35mm": "78.75 mm",
                    "Aperture": "2.8",
                    "Exposure": "1/250",
                    "ISO": 400,
                    "ExposureCompensation": "+1/3",
                    "Flash": "On, Fired",
                }
            },
        },
    }
    transport = FakeTransport(responses)
    client = SmugMugApiClient("https://example.smugmug.com", "secret", transport)
    source = SmugMugSource("https://example.smugmug.com", "secret", client)

    with caplog.at_level(logging.INFO):
        portfolio = load_portfolio(source)

    assert isinstance(source, GallerySource)
    assert portfolio.title == "Example Photographer"
    assert portfolio.source_id == "example"
    assert [gallery.title for gallery in portfolio.galleries] == ["Empty", "People"]
    assert portfolio.galleries[0].parent_source_id == "folder-1"
    assert portfolio.galleries[0].placements == ()
    assert portfolio.galleries[1].metadata["Description"] == "Portrait work"
    assert [asset.source_id for asset in portfolio.assets] == [
        "image-1",
        "image-2",
        "video-1",
    ]
    assert portfolio.assets[0].preview_url is None
    assert portfolio.assets[0].metadata.width_px == 6000
    assert portfolio.assets[0].metadata.height_px == 4000
    assert portfolio.assets[0].values["OriginalWidth"] == 6000
    assert portfolio.assets[1].metadata.width_px is None
    assert portfolio.assets[1].metadata.height_px is None
    assert portfolio.assets[2].media_type is MediaType.NON_PHOTO
    assert "smugmug_gallery_discovery_completed" in caplog.messages
    completed = next(
        record
        for record in caplog.records
        if record.message == "smugmug_gallery_discovery_completed"
    )
    assert completed.folders_discovered == 1
    assert completed.galleries_discovered == 2
    assert completed.restricted_nodes_skipped == 1
    assert all(parse_qs(urlsplit(url).query)["APIKey"] == ["secret"] for url in transport.urls)
    assert all("sizedetails" not in url.casefold() for url in transport.urls)

    asset = portfolio.assets[0]
    enriched = source.enrich_asset_metadata(asset)
    assert asset.exif == {}
    assert enriched.exif == {
        "Model": "Camera A",
        "FocalLength": "105/2 mm",
        "FocalLength35mm": "78.75 mm",
        "Aperture": "2.8",
        "Exposure": "1/250",
        "ISO": 400,
        "ExposureCompensation": "+1/3",
        "Flash": "On, Fired",
    }
    assert enriched.metadata.focal_length_mm == 52.5
    assert enriched.metadata.focal_length_35mm == 78.75
    assert enriched.metadata.aperture_f_number == 2.8
    assert enriched.metadata.exposure_time == RationalValue(1, 250)
    assert enriched.metadata.iso == 400
    assert enriched.metadata.exposure_compensation_ev == RationalValue(1, 3)
    assert enriched.metadata.flash_fired is True
    assert enriched.metadata.width_px == 6000
    assert enriched.metadata.height_px == 4000


def test_smugmug_mapping_uses_only_confirmed_tags_and_observed_formats() -> None:
    class AliasClient:
        def get_response(self, uri):
            return {
                "ImageMetadata": {
                    "Uri": uri,
                    "FNumber": "2.8",
                    "ExposureTime": "1/250",
                    "ISOSpeedRatings": 400,
                    "aperture": "4",
                    "exposure": "1/100",
                    "iso": 800,
                }
            }

    asset = Asset(
        SourceReference("image-1", "https://example.smugmug.com/image-1"),
        AssetMetadata(MediaType.PHOTOGRAPH),
    )
    enriched = SmugMugSource(
        "https://example.smugmug.com", "secret", AliasClient()
    ).enrich_asset_metadata(asset)

    assert enriched.metadata.aperture_f_number is None
    assert enriched.metadata.exposure_time is None
    assert enriched.metadata.iso is None
    assert set(enriched.exif) == {
        "FNumber",
        "ExposureTime",
        "ISOSpeedRatings",
        "aperture",
        "exposure",
        "iso",
    }


def test_partial_enrichment_preserves_existing_typed_focal_lengths() -> None:
    class PartialMetadataClient:
        def get_response(self, uri):
            assert uri == "/api/v2/image/image-1!metadata"
            return {
                "ImageMetadata": {
                    "Uri": uri,
                    "Model": "Camera B",
                }
            }

    asset = Asset(
        SourceReference("image-1", "https://example.smugmug.com/image-1"),
        AssetMetadata(
            MediaType.PHOTOGRAPH,
            exif={
                "FocalLength": "70.0 mm",
                "FocalLength35mm": "98.0 mm",
                "Aperture": "2.8",
                "Exposure": "1/200",
                "ISO": 800,
                "ExposureCompensation": "-1/3",
                "Flash": "No Flash",
            },
            focal_length_mm=70.0,
            focal_length_35mm=98.0,
            aperture_f_number=2.8,
            exposure_time=RationalValue(1, 200),
            iso=800,
            exposure_compensation_ev=RationalValue(-1, 3),
            flash_fired=False,
        ),
    )
    source = SmugMugSource(
        "https://example.smugmug.com",
        "secret",
        PartialMetadataClient(),
    )

    enriched = source.enrich_asset_metadata(asset)

    assert enriched.exif == {
        "FocalLength": "70.0 mm",
        "FocalLength35mm": "98.0 mm",
        "Aperture": "2.8",
        "Exposure": "1/200",
        "ISO": 800,
        "ExposureCompensation": "-1/3",
        "Flash": "No Flash",
        "Model": "Camera B",
    }
    assert enriched.metadata.focal_length_mm == 70.0
    assert enriched.metadata.focal_length_35mm == 98.0
    assert enriched.metadata.aperture_f_number == 2.8
    assert enriched.metadata.exposure_time == RationalValue(1, 200)
    assert enriched.metadata.iso == 800
    assert enriched.metadata.exposure_compensation_ev == RationalValue(-1, 3)
    assert enriched.metadata.flash_fired is False


def test_smugmug_client_retries_transient_and_rate_limited_requests(caplog) -> None:
    class RetryingTransport:
        def __init__(self) -> None:
            self.calls = 0

        def get_json(self, url):
            self.calls += 1
            if self.calls == 1:
                raise SourceTransientError("temporary")
            if self.calls == 2:
                raise SourceRateLimitError(90)
            return {"Code": 200, "Response": {"Value": "ready"}}

    delays = []
    transport = RetryingTransport()
    client = SmugMugApiClient(
        "https://example.smugmug.com",
        "secret",
        transport,
        max_attempts=3,
        max_retry_delay=5,
        sleeper=delays.append,
    )

    with caplog.at_level(logging.WARNING):
        assert client.get_response("/resource") == {"Value": "ready"}

    assert transport.calls == 3
    assert delays == [1.0, 5]
    assert caplog.messages.count("smugmug_request_retry") == 2


def test_smugmug_client_stops_after_bounded_retries() -> None:
    class FailingTransport:
        def __init__(self) -> None:
            self.calls = 0

        def get_json(self, url):
            self.calls += 1
            raise SourceTransientError("still unavailable")

    transport = FailingTransport()
    client = SmugMugApiClient(
        "https://example.smugmug.com",
        "secret",
        transport,
        max_attempts=2,
        sleeper=lambda _: None,
    )

    with pytest.raises(SourceTransientError, match="still unavailable"):
        client.get_response("/resource")
    assert transport.calls == 2


def test_smugmug_api_forbidden_error_is_classified_and_sanitized() -> None:
    transport = FakeTransport(
        {
            "/resource": {
                "Code": 403,
                "Message": "Forbidden https://cdn.example.test/image.jpg?token=secret",
                "Response": {},
            }
        }
    )
    client = SmugMugApiClient("https://example.smugmug.com", "secret", transport)

    with pytest.raises(SourceAuthorizationError) as raised:
        client.get_response("/resource")

    assert "token=secret" not in str(raised.value)


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
