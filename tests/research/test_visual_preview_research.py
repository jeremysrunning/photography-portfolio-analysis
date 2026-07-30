import json
from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image

from ppa.models import (
    Asset,
    AssetMetadata,
    Gallery,
    GalleryPlacement,
    MediaType,
    Portfolio,
    SourceReference,
)
from ppa.sources import SourcePreviewUnavailableError
from research.visual_preview.benchmark import decode_preview
from research.visual_preview.measurements import (
    bounding_box_iou,
    compare_measurements,
    measure_image,
    normalized_centroid_distance,
)
from research.visual_preview.sampling import sample_summary, select_sample
from research.visual_preview.smugmug_sizes import ExperimentalSmugMugSizeResolver


def _asset(
    source_id: str,
    width: int,
    height: int,
    *,
    camera: str,
) -> Asset:
    return Asset(
        SourceReference(source_id, f"https://example.test/{source_id}"),
        AssetMetadata(
            MediaType.PHOTOGRAPH,
            values={"OriginalWidth": width, "OriginalHeight": height},
            exif={"Model": camera},
        ),
    )


def _portfolio() -> Portfolio:
    assets = tuple(
        _asset(
            f"asset-{index}",
            6000 if index % 2 else 4000,
            4000 if index % 2 else 6000,
            camera=f"Camera {index % 3}",
        )
        for index in range(12)
    )
    galleries = tuple(
        Gallery(
            SourceReference(f"gallery-{index}", f"https://example.test/gallery-{index}"),
            f"Gallery {index}",
            placements=tuple(
                GalleryPlacement(asset.source_id) for asset in assets[index * 4 : (index + 1) * 4]
            ),
        )
        for index in range(3)
    )
    return Portfolio(
        "test",
        SourceReference("portfolio", "https://example.test"),
        "Portfolio",
        assets=assets,
        galleries=galleries,
    )


def _jpeg_bytes(size: tuple[int, int] = (64, 48)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, (32, 128, 224)).save(output, format="JPEG")
    return output.getvalue()


def test_sample_selection_is_deterministic_and_metadata_stratified() -> None:
    portfolio = _portfolio()

    first = select_sample(portfolio, 8, seed="fixed")
    second = select_sample(portfolio, 8, seed="fixed")

    assert [record.asset.source_id for record in first] == [
        record.asset.source_id for record in second
    ]
    summary = sample_summary(first)
    assert summary["sample_size"] == 8
    assert summary["orientations"] == {"landscape": 4, "portrait": 4}
    assert summary["camera_count"] == 3
    assert summary["gallery_count"] == 3


def test_preview_size_comparison_is_deterministic() -> None:
    large = Image.new("RGB", (1024, 768), (40, 120, 200))
    small = large.resize((256, 192), Image.Resampling.LANCZOS)

    large_result = measure_image(large)
    small_result = measure_image(small)

    assert measure_image(small) == small_result
    comparison = compare_measurements(small_result, large_result)
    assert comparison["luminance_mean_stable"] is True
    assert comparison["palette_distance_stable"] is True
    assert comparison["saliency_centroid_distance_stable"] is True


def test_normalized_coordinate_comparisons_and_box_iou() -> None:
    assert bounding_box_iou((0.1, 0.1, 0.4, 0.4), (0.1, 0.1, 0.4, 0.4)) == 1
    assert bounding_box_iou((0, 0, 0.25, 0.25), (0.75, 0.75, 0.25, 0.25)) == 0
    assert normalized_centroid_distance((0.5, 0.5), (0.5, 0.5)) == 0
    with pytest.raises(ValueError, match="within the frame"):
        bounding_box_iou((0.9, 0.9, 0.2, 0.2), (0, 0, 0.1, 0.1))


def test_decode_uses_memory_and_leaves_no_files(tmp_path) -> None:
    before = tuple(tmp_path.iterdir())
    image = decode_preview(_jpeg_bytes(), maximum_edge=128)

    assert image.size == (64, 48)
    assert tuple(tmp_path.iterdir()) == before


def test_corrupt_and_oversized_previews_are_rejected() -> None:
    with pytest.raises(SourcePreviewUnavailableError, match="could not be decoded"):
        decode_preview(b"not an image", maximum_edge=128)
    with pytest.raises(SourcePreviewUnavailableError, match="dimension limit"):
        decode_preview(_jpeg_bytes((256, 128)), maximum_edge=128)


def test_unavailable_size_details_fail_without_exposing_secret(caplog) -> None:
    class MissingDetailsClient:
        def get_response(self, uri):
            return {"Image": {"Uris": {}}}

    resolver = ExperimentalSmugMugSizeResolver(
        "https://example.test",
        "highly-secret-key",
    )
    resolver.client = MissingDetailsClient()

    with pytest.raises(SourcePreviewUnavailableError, match="size details"):
        resolver.candidates("asset")
    rendered_logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "highly-secret-key" not in rendered_logs


def test_measurement_serialization_is_deterministic_and_contains_no_url() -> None:
    result = measure_image(Image.new("RGB", (32, 32), (100, 100, 100)))

    first = json.dumps(result.serializable(), sort_keys=True)
    second = json.dumps(result.serializable(), sort_keys=True)

    assert first == second
    assert "http://" not in first
    assert "https://" not in first


def test_non_photo_assets_are_not_selected() -> None:
    portfolio = _portfolio()
    video = replace(
        portfolio.assets[0],
        metadata=replace(
            portfolio.assets[0].metadata,
            media_type=MediaType.NON_PHOTO,
        ),
    )
    changed = replace(portfolio, assets=(video, *portfolio.assets[1:]))

    selected = select_sample(changed, 20)

    assert all(record.asset.source_id != video.source_id for record in selected)
