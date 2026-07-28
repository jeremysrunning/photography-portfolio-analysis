"""Public SmugMug portfolio source."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from ppa.models import Asset, Gallery, Portfolio
from ppa.sources.base import SourceError
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

    def load_portfolio(self) -> Portfolio:
        client = self.client or SmugMugApiClient(self.portfolio_url, self.api_key)
        site_user = client.get_response("/api/v2!siteuser")
        user = _object(site_user, "User")
        nickname = _required_string(user, "NickName")
        albums_uri = _linked_uri(user, "UserAlbums")

        galleries = tuple(
            self._load_gallery(client, album) for album in client.iter_objects(albums_uri, "Album")
        )
        return Portfolio(
            source=self.source_name,
            source_id=nickname,
            title=_string(user, "Name") or nickname,
            source_url=_absolute_web_url(
                _string(user, "WebUri") or self.portfolio_url, self.portfolio_url
            ),
            metadata=_metadata(user, {"Name", "NickName", "Uri", "Uris", "WebUri"}),
            galleries=galleries,
        )

    def _load_gallery(
        self,
        client: SmugMugApiClient,
        album: dict[str, Any],
    ) -> Gallery:
        album_id = _resource_id(_required_string(album, "Uri"))
        images_uri = _linked_uri(album, "AlbumImages")
        assets = tuple(
            _asset(image, album_id, self.portfolio_url)
            for image in client.iter_objects(images_uri, "AlbumImage")
            if image.get("IsVideo") is not True
        )
        return Gallery(
            source_id=album_id,
            title=_string(album, "Name") or album_id,
            source_url=_absolute_web_url(_required_string(album, "WebUri"), self.portfolio_url),
            metadata=_metadata(
                album,
                {"Name", "Uri", "Uris", "WebUri"},
            ),
            assets=assets,
        )


def _asset(image: dict[str, Any], gallery_id: str, site_url: str) -> Asset:
    uri = _required_string(image, "Uri")
    captured_at = _datetime(image.get("DateTimeOriginal") or image.get("Date"))
    return Asset(
        source_id=_resource_id(uri),
        source_url=_absolute_web_url(_required_string(image, "WebUri"), site_url),
        gallery_source_id=gallery_id,
        captured_at=captured_at,
        metadata=_metadata(
            image,
            {"Uri", "Uris", "WebUri", "DateTimeOriginal"},
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


def _is_json_value(value: Any) -> bool:
    if value is None or isinstance(value, bool | int | float | str):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False
