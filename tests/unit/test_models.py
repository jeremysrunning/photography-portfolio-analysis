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
    RationalValue,
    SourceReference,
    normalize_aperture_f_number,
    normalize_exposure_compensation,
    normalize_exposure_time,
    normalize_flash_fired,
    normalize_focal_length,
    normalize_iso,
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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (35, 35.0),
        (35.5, 35.5),
        ("35.5 mm", 35.5),
        ("71/2", 35.5),
        (" 70 / 2 mm ", 35.0),
        (None, None),
        ("unknown", None),
        ("35 mm extra", None),
        ("1/0", None),
        (0, None),
        (-35, None),
        (True, None),
    ],
)
def test_focal_length_normalization(value: object, expected: float | None) -> None:
    assert normalize_focal_length(value) == expected


@pytest.mark.parametrize("field", ["focal_length_mm", "focal_length_35mm"])
def test_focal_length_fields_require_positive_finite_values(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        AssetMetadata(**{field: float("nan")})


def test_reported_teleconverter_adjusted_focal_length_is_not_reinterpreted() -> None:
    assert normalize_focal_length("700/10 mm") == 70.0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2.8, 2.8),
        (" 2.8 ", 2.8),
        ("f/2.8", 2.8),
        ("14/5", 2.8),
        (0, None),
        (-2.8, None),
        ("f/unknown", None),
        (float("inf"), None),
        (True, None),
    ],
)
def test_aperture_normalization(value: object, expected: float | None) -> None:
    assert normalize_aperture_f_number(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, RationalValue(1)),
        (0.5, RationalValue(1, 2)),
        ("1/250", RationalValue(1, 250)),
        (" 0.5 seconds ", RationalValue(1, 2)),
        ("120 sec", RationalValue(120)),
        ("2/4 s", RationalValue(1, 2)),
        (0, None),
        (-1, None),
        ("1/0", None),
        ("1/2/3", None),
        (float("nan"), None),
    ],
)
def test_exposure_time_normalization(value: object, expected: RationalValue | None) -> None:
    assert normalize_exposure_time(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (400, 400),
        (400.0, 400),
        ("400", 400),
        ("400.0", 400),
        ("400.5", None),
        ("100, 200", None),
        ("Auto", None),
        (0, None),
        (-100, None),
        (float("inf"), None),
        (True, None),
    ],
)
def test_iso_normalization(value: object, expected: int | None) -> None:
    assert normalize_iso(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("+1/3", RationalValue(1, 3)),
        ("+2/3 EV", RationalValue(2, 3)),
        ("-1/3", RationalValue(-1, 3)),
        ("-0.3 ev", RationalValue(-3, 10)),
        (0, RationalValue(0)),
        ("", None),
        ("unknown", None),
        (float("nan"), None),
    ],
)
def test_exposure_compensation_normalization(value: object, expected: RationalValue | None) -> None:
    assert normalize_exposure_compensation(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("On, Fired", True),
        (" off, DID NOT FIRE ", False),
        ("No Flash", False),
        ("On, did not fire", None),
        ("", None),
        (0, None),
        (False, None),
        (None, None),
    ],
)
def test_flash_fired_normalization(value: object, expected: bool | None) -> None:
    assert normalize_flash_fired(value) is expected


def test_rational_value_is_canonical_exact_and_immutable() -> None:
    value = RationalValue(-2, -6)

    assert value == RationalValue(1, 3)
    assert value.numerator == 1
    assert value.denominator == 3
    with pytest.raises(AttributeError):
        value.numerator = 2


def test_asset_metadata_validates_exposure_field_semantics() -> None:
    metadata = AssetMetadata(
        MediaType.PHOTOGRAPH,
        aperture_f_number=2.8,
        exposure_time=RationalValue(1, 250),
        iso=400,
        exposure_compensation_ev=RationalValue(-1, 3),
        flash_fired=False,
    )

    assert metadata.exposure_time == RationalValue(1, 250)
    assert metadata.exposure_compensation_ev == RationalValue(-1, 3)
    assert metadata.flash_fired is False
    with pytest.raises(ValueError, match="exposure_time"):
        AssetMetadata(exposure_time=RationalValue(-1, 250))
    with pytest.raises(ValueError, match="iso"):
        AssetMetadata(iso=0)
    with pytest.raises(ValueError, match="flash_fired"):
        AssetMetadata(flash_fired=1)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_finding_rejects_out_of_range_confidence(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        Finding("A neutral statement.", confidence, ())
