from urllib.parse import parse_qs, urlsplit

import pytest

from ppa.sources import GallerySource, SourceError
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
