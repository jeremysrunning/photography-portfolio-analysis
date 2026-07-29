from datetime import UTC, datetime

import pytest

from ppa.models import (
    Asset,
    AssetMetadata,
    Finding,
    Gallery,
    GalleryPlacement,
    MediaType,
    Portfolio,
    SourceReference,
)


def _reference(source_id: str) -> SourceReference:
    return SourceReference(source_id, f"https://example.test/{source_id}")


def test_valid_normalized_graph_has_unique_assets_and_explicit_placements() -> None:
    asset = Asset(
        _reference("asset"),
        AssetMetadata(
            MediaType.PHOTOGRAPH,
            datetime(2024, 1, 2, tzinfo=UTC),
            {"caption": None},
            {"Model": "Camera"},
        ),
    )
    portfolio = Portfolio(
        "test",
        _reference("portfolio"),
        "Portfolio",
        assets=(asset,),
        galleries=(
            Gallery(
                _reference("one"),
                "One",
                placements=(GalleryPlacement("asset"),),
            ),
            Gallery(
                _reference("two"),
                "Two",
                placements=(GalleryPlacement("asset"),),
            ),
        ),
    )

    assert portfolio.assets == (asset,)
    assert portfolio.gallery_assets(portfolio.galleries[0]) == (asset,)
    assert portfolio.gallery_assets(portfolio.galleries[1]) == (asset,)
    assert asset.metadata.values["caption"] is None
    assert asset.media_type is MediaType.PHOTOGRAPH


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: SourceReference("", "https://example.test"), "source_id"),
        (lambda: SourceReference("asset", "relative"), "absolute"),
        (
            lambda: Gallery(
                _reference("gallery"),
                "Gallery",
                placements=(GalleryPlacement("asset"), GalleryPlacement("asset")),
            ),
            "placements must be unique",
        ),
        (
            lambda: Portfolio(
                "test",
                _reference("portfolio"),
                "Portfolio",
                assets=(Asset(_reference("asset")), Asset(_reference("asset"))),
            ),
            "asset source identities must be unique",
        ),
        (
            lambda: Portfolio(
                "test",
                _reference("portfolio"),
                "Portfolio",
                galleries=(
                    Gallery(
                        _reference("gallery"),
                        "Gallery",
                        placements=(GalleryPlacement("missing"),),
                    ),
                ),
            ),
            "unknown assets",
        ),
        (
            lambda: AssetMetadata(values={"invalid": object()}),
            "JSON-compatible",
        ),
    ],
)
def test_invalid_normalized_combinations_fail_clearly(factory, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_media_type_does_not_coerce_unknown_to_photograph() -> None:
    assert Asset(_reference("unknown")).media_type is MediaType.UNKNOWN
    assert (
        Asset(
            _reference("video"),
            AssetMetadata(media_type=MediaType.NON_PHOTO),
        ).media_type
        is MediaType.NON_PHOTO
    )


def test_normalized_metadata_is_deeply_copied_and_immutable() -> None:
    values = {
        "caption": "Original",
        "nested": {"keywords": ["one", {"label": "two"}]},
    }
    exif = {"camera": {"model": "A"}}
    gallery_metadata = {"nested": {"value": 1}}
    portfolio_metadata = {"tags": ["portfolio"]}
    asset = Asset(
        _reference("asset"),
        AssetMetadata(MediaType.PHOTOGRAPH, values=values, exif=exif),
    )
    gallery = Gallery(
        _reference("gallery"),
        "Gallery",
        metadata=gallery_metadata,
        placements=(GalleryPlacement("asset"),),
    )
    portfolio = Portfolio(
        "test",
        _reference("portfolio"),
        "Portfolio",
        metadata=portfolio_metadata,
        assets=(asset,),
        galleries=(gallery,),
    )

    values["caption"] = "Changed"
    values["nested"]["keywords"].append("three")
    exif["camera"]["model"] = "B"
    gallery_metadata["nested"]["value"] = 2
    portfolio_metadata["tags"].append("changed")

    assert asset.values["caption"] == "Original"
    assert asset.values["nested"]["keywords"] == ("one", {"label": "two"})
    assert asset.exif["camera"]["model"] == "A"
    assert gallery.metadata["nested"]["value"] == 1
    assert portfolio.metadata["tags"] == ("portfolio",)

    with pytest.raises(TypeError):
        asset.values["caption"] = "Mutation"
    with pytest.raises(AttributeError):
        asset.values["nested"]["keywords"].append("mutation")
    with pytest.raises(TypeError):
        asset.values["nested"]["keywords"][1]["label"] = "mutation"
    with pytest.raises(TypeError):
        asset.exif["camera"]["model"] = "mutation"
    with pytest.raises(TypeError):
        gallery.metadata["nested"]["value"] = 3
    with pytest.raises(AttributeError):
        portfolio.metadata["tags"].append("mutation")


def test_finding_accepts_bounded_confidence() -> None:
    finding = Finding("Centered compositions recur.", 0.75, ("measurement:placement",))
    assert finding.confidence == 0.75


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_finding_rejects_out_of_range_confidence(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        Finding("A neutral statement.", confidence, ())
