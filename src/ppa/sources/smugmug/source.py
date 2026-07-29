"""Public SmugMug portfolio source."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from ppa.models import (
    Asset,
    AssetMetadata,
    Gallery,
    MediaType,
    Portfolio,
    SourceReference,
)
from ppa.sources.base import (
    SourceAuthenticationError,
    SourceError,
    SourcePreviewUnavailableError,
)
from ppa.sources.smugmug.api import SmugMugApiClient


@dataclass(slots=True)
class SmugMugSource:
    """Inspect public SmugMug albums using metadata-only API calls."""

    portfolio_url: str
    api_key: str
    client: SmugMugApiClient | None = None

    @property
    def source_name(self) -> str:
        return "smugmug"

    def discover_portfolio(self) -> Portfolio:
        """Discover the public SmugMug account without enumerating galleries."""
        client = self.client or SmugMugApiClient(self.portfolio_url, self.api_key)
        site_user = client.get_response("/api/v2!siteuser")
        user = _object(site_user, "User")
        nickname = _required_string(user, "NickName")
        return Portfolio(
            source_name=self.source_name,
            source=SourceReference(
                nickname,
                _absolute_web_url(
                    _string(user, "WebUri") or self.portfolio_url, self.portfolio_url
                ),
            ),
            title=_string(user, "Name") or nickname,
            metadata=_metadata(user, {"Name", "NickName", "Uri", "Uris", "WebUri"}),
        )

    def iter_galleries(self, portfolio: Portfolio) -> Iterator[Gallery]:
        """Yield public SmugMug albums as normalized galleries."""
        if portfolio.source_name != self.source_name:
            raise SourceError(
                f"Cannot enumerate {portfolio.source_name!r} with the {self.source_name!r} source."
            )
        client = self.client or SmugMugApiClient(self.portfolio_url, self.api_key)
        albums_uri = f"/api/v2/user/{portfolio.source_id}!albums"
        for album in client.iter_objects(albums_uri, "Album"):
            yield self._gallery(album)

    def iter_assets(self, gallery: Gallery) -> Iterator[Asset]:
        """Yield public photographs in a normalized gallery."""
        client = self.client or SmugMugApiClient(self.portfolio_url, self.api_key)
        images_uri = f"/api/v2/album/{gallery.source_id}!images"
        for image in client.iter_objects(images_uri, "AlbumImage"):
            yield _asset(image, self.portfolio_url)

    def enrich_asset_metadata(self, asset: Asset) -> Asset:
        """Return an asset enriched with available public SmugMug metadata."""
        client = self.client or SmugMugApiClient(self.portfolio_url, self.api_key)
        response = client.get_response(f"/api/v2/image/{asset.source_id}!metadata")
        metadata = _object(response, "ImageMetadata")
        exif = _available_metadata(
            metadata,
            {"Uri", "Uris", "ResponseLevel", "UriDescription"},
        )
        return replace(
            asset,
            metadata=replace(asset.metadata, exif={**asset.exif, **exif}),
        )

    @contextmanager
    def open_preview(self, asset: Asset) -> Iterator[BinaryIO]:
        """Open a source-owned preview stream and close it on context exit."""
        if not asset.preview_url:
            raise SourcePreviewUnavailableError(
                f"Asset {asset.source_id!r} has no public preview URL."
            )
        request = Request(
            asset.preview_url,
            headers={"User-Agent": "photography-portfolio-analysis/0.1"},
        )
        try:
            with urlopen(request, timeout=30.0) as response:
                yield response
        except HTTPError as error:
            if error.code in {401, 403}:
                raise SourceAuthenticationError(
                    "The source rejected access to the temporary preview."
                ) from error
            if error.code == 404:
                raise SourcePreviewUnavailableError(
                    f"Asset {asset.source_id!r} preview was not found."
                ) from error
            raise SourceError(f"Preview request returned HTTP {error.code}.") from error
        except (URLError, TimeoutError) as error:
            raise SourceError("Could not open the temporary preview.") from error

    def _gallery(self, album: dict[str, Any]) -> Gallery:
        album_id = _resource_id(_required_string(album, "Uri"))
        return Gallery(
            source=SourceReference(
                album_id,
                _absolute_web_url(_required_string(album, "WebUri"), self.portfolio_url),
            ),
            title=_string(album, "Name") or album_id,
            metadata=_metadata(
                album,
                {"Name", "Uri", "Uris", "WebUri"},
            ),
        )


def _asset(image: dict[str, Any], site_url: str) -> Asset:
    uri = _required_string(image, "Uri")
    captured_at = _datetime(image.get("DateTimeOriginal") or image.get("Date"))
    is_video = image.get("IsVideo")
    media_type = (
        MediaType.NON_PHOTO
        if is_video is True
        else MediaType.PHOTOGRAPH
        if is_video is False
        else MediaType.UNKNOWN
    )
    return Asset(
        source=SourceReference(
            _resource_id(uri),
            _absolute_web_url(_required_string(image, "WebUri"), site_url),
        ),
        metadata=AssetMetadata(
            media_type=media_type,
            captured_at=captured_at,
            values=_metadata(
                image,
                {"Uri", "Uris", "WebUri", "DateTimeOriginal"},
            ),
        ),
    )


def _object(response: dict[str, Any], name: str) -> dict[str, Any]:
    value = response.get(name)
    if not isinstance(value, dict):
        raise SourceError(f"SmugMug response did not include {name}.")
    return value


def _linked_uri(value: dict[str, Any], name: str) -> str:
    uris = value.get("Uris")
    if not isinstance(uris, dict):
        raise SourceError(f"SmugMug response did not link to {name}.")
    linked = uris.get(name)
    if isinstance(linked, str):
        return linked
    if isinstance(linked, dict) and isinstance(linked.get("Uri"), str):
        return linked["Uri"]
    raise SourceError(f"SmugMug response did not link to {name}.")


def _required_string(value: dict[str, Any], name: str) -> str:
    result = _string(value, name)
    if result is None:
        raise SourceError(f"SmugMug response did not include {name}.")
    return result


def _string(value: dict[str, Any], name: str) -> str | None:
    result = value.get(name)
    return result if isinstance(result, str) and result else None


def _resource_id(uri: str) -> str:
    path = urlsplit(uri).path.rstrip("/")
    resource_id = path.rsplit("/", 1)[-1]
    if not resource_id:
        raise SourceError("SmugMug returned a resource without an identifier.")
    return resource_id


def _absolute_web_url(web_uri: str, site_url: str) -> str:
    if web_uri.startswith(("https://", "http://")):
        return web_uri
    origin = urlsplit(site_url)
    return f"{origin.scheme}://{origin.netloc}/{web_uri.lstrip('/')}"


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _metadata(value: dict[str, Any], excluded: set[str]) -> dict[str, Any]:
    return {
        key: item for key, item in value.items() if key not in excluded and _is_json_value(item)
    }


def _available_metadata(value: dict[str, Any], excluded: set[str]) -> dict[str, Any]:
    return {
        key: item
        for key, item in _metadata(value, excluded).items()
        if item not in (None, "", [], {})
    }


def _is_json_value(value: Any) -> bool:
    if value is None or isinstance(value, bool | int | float | str):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False
