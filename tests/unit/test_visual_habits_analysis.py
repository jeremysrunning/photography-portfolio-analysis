from dataclasses import fields, is_dataclass
from datetime import UTC, datetime

from ppa.analysis.color_luminance import ANALYZER_IDENTITY as COLOR_IDENTITY
from ppa.analysis.composition_saliency import ANALYZER_IDENTITY as SALIENCY_IDENTITY
from ppa.analysis.preview_structure import ANALYZER_IDENTITY as STRUCTURE_IDENTITY
from ppa.analysis.visual_habits import (
    CatalogStatus,
    VisualAnalyzerDataset,
    analyze_visual_habits,
)
from ppa.models import (
    Asset,
    AssetMetadata,
    Gallery,
    GalleryPlacement,
    MediaType,
    Portfolio,
    SourceReference,
)
from ppa.reports import render_visual_habits
from ppa.storage import VisualAnalysisRecord
from ppa.visual import (
    AnalyzerIdentity,
    NormalizedPoint,
    VisualAnalysisSnapshot,
    VisualResult,
    VisualResultKind,
    VisualRunState,
    VisualRunStatus,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _asset(index: int, *, year: int = 2020, orientation: str = "landscape") -> Asset:
    dimensions = {
        "landscape": (6000, 4000),
        "portrait": (4000, 6000),
        "square": (4000, 4000),
    }[orientation]
    return Asset(
        SourceReference(f"asset-{index}", f"https://example.test/asset-{index}"),
        AssetMetadata(
            MediaType.PHOTOGRAPH,
            datetime(year, 1, 1, tzinfo=UTC),
            {
                "OriginalWidth": dimensions[0],
                "OriginalHeight": dimensions[1],
                "Model": "Camera A",
                "LensModel": "Lens A",
            },
            width_px=dimensions[0],
            height_px=dimensions[1],
        ),
    )


def _portfolio(count: int = 2) -> Portfolio:
    assets = tuple(_asset(index) for index in range(count))
    return Portfolio(
        "test",
        SourceReference("portfolio", "https://example.test/portfolio"),
        "Portfolio",
        assets=assets,
        galleries=(
            Gallery(
                SourceReference("gallery", "https://example.test/gallery"),
                "Gallery",
                placements=tuple(GalleryPlacement(asset.source_id) for asset in assets),
            ),
        ),
    )


def _result(name: str, value, unit: str) -> VisualResult:
    return VisualResult(
        name,
        VisualResultKind.MEASUREMENT,
        value,
        name.replace("_", "-"),
        "1",
        unit=unit,
        completed_at=T0,
    )


def _color_results(value: float, *, extra: bool = False) -> tuple[VisualResult, ...]:
    values = (
        _result("luminance_mean", value, "relative_linear_luminance"),
        _result("luminance_median", value, "relative_linear_luminance"),
        _result("shadow_luminance_tail_proportion", value, "proportion"),
        _result("highlight_luminance_tail_proportion", value, "proportion"),
        _result("saturation_mean", value, "proportion"),
        _result("saturation_median", value, "proportion"),
        _result("colorfulness", value, "normalized_srgb_formula_output"),
        _result(
            "dominant_palette",
            {
                "color_space": "srgb",
                "quantization": "4bit_per_channel",
                "colors": [
                    {"rgb": [8, 24, 40], "proportion": 0.6},
                    {"rgb": [56, 72, 88], "proportion": 0.4},
                ],
                "covered_pixel_proportion": 0.8,
            },
            "encoded_srgb",
        ),
        _result("palette_entropy", value, "normalized_entropy"),
    )
    return (*values, _result("future_result", 1.0, "future")) if extra else values


def _saliency_results(value: float, *, evidence: bool = True) -> tuple[VisualResult, ...]:
    output = [_result("saliency_evidence", evidence, "boolean")]
    if evidence:
        output.extend(
            (
                _result(
                    "saliency_centroid",
                    NormalizedPoint(value, value),
                    "normalized_frame_coordinate",
                ),
                _result("saliency_spread", value, "frame_diagonal_fraction"),
                _result("saliency_center_distance", value, "normalized_distance"),
                _result("saliency_thirds_line_distance", value, "normalized_distance"),
                _result(
                    "saliency_thirds_intersection_distance",
                    value,
                    "normalized_distance",
                ),
            )
        )
    output.append(
        _result(
            "saliency_grid_3x3",
            {
                "order": [
                    "top_left",
                    "top_center",
                    "top_right",
                    "middle_left",
                    "center",
                    "middle_right",
                    "bottom_left",
                    "bottom_center",
                    "bottom_right",
                ],
                "masses": [0.1, 0.1, 0.1, 0.1, 0.2, 0.1, 0.1, 0.1, 0.1],
            },
            "proportion",
        )
    )
    return tuple(output)


def _structure_results(value: float, *, support: bool = True) -> tuple[VisualResult, ...]:
    output = [_result("structure_measurement_support", support, "boolean")]
    if support:
        output.extend(
            (
                _result("global_sharpness_proxy", value, "normalized_laplacian_variance"),
                _result("gradient_directional_evidence", True, "boolean"),
                _result("gradient_directional_anisotropy", value, "proportion"),
                _result("edge_density", value, "proportion"),
                _result("local_luminance_contrast", value, "normalized_local_rms_contrast"),
                _result(
                    "spatial_sharpness_variation",
                    value,
                    "normalized_spatial_variation",
                ),
                _result("noise_proxy_evidence", True, "boolean"),
                _result("noise_residual_mad", value, "relative_linear_luminance"),
                _result("luminance_p95_p05_span", value, "relative_linear_luminance_span"),
            )
        )
    return tuple(output)


def _record(
    asset: Asset,
    identity: AnalyzerIdentity,
    results: tuple[VisualResult, ...],
    *,
    status: VisualRunStatus = VisualRunStatus.COMPLETED,
) -> VisualAnalysisRecord:
    return VisualAnalysisRecord(
        asset,
        VisualAnalysisSnapshot(
            identity,
            VisualRunState(status, 1, T0, last_successful_completed_at=T0),
            results,
        ),
    )


def _datasets(portfolio: Portfolio) -> tuple[VisualAnalyzerDataset, ...]:
    return (
        VisualAnalyzerDataset(
            COLOR_IDENTITY,
            tuple(
                _record(asset, COLOR_IDENTITY, _color_results((index % 9 + 1) / 10))
                for index, asset in enumerate(portfolio.assets)
            ),
        ),
        VisualAnalyzerDataset(
            SALIENCY_IDENTITY,
            tuple(
                _record(asset, SALIENCY_IDENTITY, _saliency_results((index % 9 + 1) / 10))
                for index, asset in enumerate(portfolio.assets)
            ),
        ),
        VisualAnalyzerDataset(
            STRUCTURE_IDENTITY,
            tuple(
                _record(asset, STRUCTURE_IDENTITY, _structure_results((index % 9 + 1) / 10))
                for index, asset in enumerate(portfolio.assets)
            ),
        ),
    )


def test_no_visual_rows_selects_current_identities_and_reports_pending() -> None:
    portfolio = _portfolio()
    report = analyze_visual_habits(portfolio, (), ())

    assert tuple(item.evidence.identity for item in report.analyzers) == (
        COLOR_IDENTITY,
        SALIENCY_IDENTITY,
        STRUCTURE_IDENTITY,
    )
    assert all(item.evidence.pending == 2 for item in report.analyzers)
    assert all(item.evidence.successful_snapshots == 0 for item in report.analyzers)
    assert report.yearly_differences == ()

    rendered = render_visual_habits(report, details=True)
    assert "0 / 0 (0.0%)" not in rendered
    assert (
        "Structure measurement support: unavailable (no completed selected-identity snapshots)"
    ) in rendered
    assert "No complete selected-identity measurement snapshots are available." in rendered


def test_complete_catalogs_produce_scalar_point_grid_and_palette_aggregates() -> None:
    portfolio = _portfolio()
    report = analyze_visual_habits(portfolio, _datasets(portfolio), ())
    color, saliency, structure = report.analyzers

    luminance = next(item for item in color.scalars if item.name == "luminance_median")
    assert (luminance.count, luminance.minimum, luminance.maximum) == (2, 0.1, 0.2)
    assert round(luminance.median, 12) == 0.15
    assert color.palette_bins[0].rgb == (8, 24, 40)
    assert color.palette_bins[0].photograph_count == 2
    assert saliency.point is not None
    assert round(saliency.point.median_x, 12) == 0.15
    assert saliency.regional_mass is not None
    assert sum(saliency.regional_mass.masses) == 1.0
    assert structure.evidence.complete_expected_snapshots == 2


def test_catalog_outcomes_distinguish_missing_malformed_and_ignored_extras() -> None:
    portfolio = _portfolio(3)
    malformed = list(_color_results(0.2))
    malformed[0] = _result("luminance_mean", 0.2, "wrong_unit")
    future_classification = VisualResult(
        "future_classification",
        VisualResultKind.CLASSIFICATION,
        "unknown",
        "future-model",
        "1",
        confidence=0.0,
        model_name="future-model",
        model_version="1",
        completed_at=T0,
    )
    records = (
        _record(
            portfolio.assets[0],
            COLOR_IDENTITY,
            (*_color_results(0.1), future_classification),
        ),
        _record(portfolio.assets[1], COLOR_IDENTITY, _color_results(0.2)[:-1]),
        _record(portfolio.assets[2], COLOR_IDENTITY, tuple(malformed)),
    )
    report = analyze_visual_habits(
        portfolio,
        (VisualAnalyzerDataset(COLOR_IDENTITY, records),),
        (),
    )
    evidence = report.analyzers[0].evidence
    assert evidence.complete_expected_snapshots == 1
    assert evidence.incomplete_expected_snapshots == 1
    assert evidence.malformed_snapshots == 1
    assert evidence.snapshots_with_unexpected_entries == 1
    assert evidence.unexpected_entry_count == 1
    assert evidence.classification_results == 0


def test_condition_inconsistent_results_are_malformed_and_missing_core_is_incomplete() -> None:
    portfolio = _portfolio(2)
    inconsistent = (
        *_saliency_results(0.2, evidence=False),
        _result(
            "saliency_centroid",
            NormalizedPoint(0.2, 0.2),
            "normalized_frame_coordinate",
        ),
    )
    missing_core = tuple(
        result
        for result in _structure_results(0.2)
        if result.name != "structure_measurement_support"
    )
    report = analyze_visual_habits(
        portfolio,
        (
            VisualAnalyzerDataset(
                SALIENCY_IDENTITY,
                (_record(portfolio.assets[0], SALIENCY_IDENTITY, inconsistent),),
            ),
            VisualAnalyzerDataset(
                STRUCTURE_IDENTITY,
                (_record(portfolio.assets[1], STRUCTURE_IDENTITY, missing_core),),
            ),
        ),
        (),
    )

    assert report.analyzers[1].evidence.malformed_snapshots == 1
    assert report.analyzers[2].evidence.incomplete_expected_snapshots == 1


def test_false_evidence_and_support_are_complete_without_fabricated_scalars() -> None:
    portfolio = _portfolio(1)
    report = analyze_visual_habits(
        portfolio,
        (
            VisualAnalyzerDataset(
                SALIENCY_IDENTITY,
                (
                    _record(
                        portfolio.assets[0],
                        SALIENCY_IDENTITY,
                        _saliency_results(0.2, evidence=False),
                    ),
                ),
            ),
            VisualAnalyzerDataset(
                STRUCTURE_IDENTITY,
                (
                    _record(
                        portfolio.assets[0],
                        STRUCTURE_IDENTITY,
                        _structure_results(0.2, support=False),
                    ),
                ),
            ),
        ),
        (),
    )
    saliency, structure = report.analyzers[1:]
    assert saliency.evidence.complete_expected_snapshots == 1
    assert saliency.point is None
    assert structure.evidence.complete_expected_snapshots == 1
    assert structure.scalars == ()


def test_retained_snapshot_state_and_historical_identity_are_disclosed() -> None:
    portfolio = _portfolio(1)
    historical = AnalyzerIdentity("color-luminance", "0.9.0", "old")
    record = _record(
        portfolio.assets[0],
        COLOR_IDENTITY,
        _color_results(0.3),
        status=VisualRunStatus.FAILED,
    )
    report = analyze_visual_habits(
        portfolio,
        (VisualAnalyzerDataset(COLOR_IDENTITY, (record,)),),
        (historical,),
    )
    evidence = report.analyzers[0].evidence
    assert evidence.failed == 1
    assert evidence.successful_snapshots == 1
    assert evidence.retained_under_noncompleted_state == 1
    assert evidence.historical_identities == (historical,)


def test_yearly_changes_use_adjacent_years_threshold_and_earliest_tie() -> None:
    assets = tuple(_asset(index, year=2020 + index // 20) for index in range(60))
    portfolio = Portfolio(
        "test",
        SourceReference("portfolio", "https://example.test/portfolio"),
        "Portfolio",
        assets=assets,
    )
    values = {2020: 0.1, 2021: 0.3, 2022: 0.5}
    datasets = (
        VisualAnalyzerDataset(
            COLOR_IDENTITY,
            tuple(
                _record(asset, COLOR_IDENTITY, _color_results(values[asset.captured_at.year]))
                for asset in assets
                if asset.captured_at is not None
            ),
        ),
        VisualAnalyzerDataset(
            SALIENCY_IDENTITY,
            tuple(
                _record(asset, SALIENCY_IDENTITY, _saliency_results(values[asset.captured_at.year]))
                for asset in assets
                if asset.captured_at is not None
            ),
        ),
        VisualAnalyzerDataset(
            STRUCTURE_IDENTITY,
            tuple(
                _record(
                    asset, STRUCTURE_IDENTITY, _structure_results(values[asset.captured_at.year])
                )
                for asset in assets
                if asset.captured_at is not None
            ),
        ),
    )
    report = analyze_visual_habits(portfolio, datasets, ())

    assert len(report.yearly_differences) == 3
    assert all(
        item.from_year == 2020 and item.to_year == 2021 for item in report.yearly_differences
    )
    assert all(item.from_count == 20 and item.to_count == 20 for item in report.yearly_differences)
    assert all(round(item.difference, 12) == 0.2 for item in report.yearly_differences)


def test_segments_require_twenty_measurements_and_preserve_exact_orientation() -> None:
    assets = tuple(
        _asset(index, orientation="square" if index < 20 else "portrait") for index in range(39)
    )
    portfolio = Portfolio(
        "test",
        SourceReference("portfolio", "https://example.test/portfolio"),
        "Portfolio",
        assets=assets,
    )
    records = tuple(_record(asset, COLOR_IDENTITY, _color_results(0.2)) for asset in assets)
    report = analyze_visual_habits(
        portfolio,
        (VisualAnalyzerDataset(COLOR_IDENTITY, records),),
        (),
    )
    assert [item.label for item in report.orientation_segments.segments] == ["square"]
    assert report.orientation_segments.omitted_segments == 1


def test_final_report_model_contains_no_per_image_identity() -> None:
    portfolio = _portfolio(1)
    report = analyze_visual_habits(portfolio, _datasets(portfolio), ())

    def values(value):
        if is_dataclass(value):
            for field in fields(value):
                yield from values(getattr(value, field.name))
        elif isinstance(value, tuple | list):
            for item in value:
                yield from values(item)
        elif isinstance(value, dict):
            for item in value.values():
                yield from values(item)
        else:
            yield value

    assert not any(
        isinstance(value, str) and ("asset-" in value or "https://" in value)
        for value in values(report)
    )
    assert CatalogStatus.COMPLETE.value == "complete"


def test_renderer_is_deterministic_neutral_and_contains_no_per_image_identity() -> None:
    portfolio = _portfolio(2)
    report = analyze_visual_habits(portfolio, _datasets(portfolio), ())

    first = render_visual_habits(report)
    second = render_visual_habits(report)

    assert first == second
    assert "Evidence and Coverage" in first
    assert "Composition and Saliency" in first
    assert "Color and Luminance" in first
    assert "Preview Structure" in first
    assert "Changes Over Time" in first
    assert "Methods and Limitations" in first
    assert "asset-" not in first
    assert "https://" not in first
    assert "\nPeople and" not in first
    assert "\nScene and" not in first
    for prohibited in ("should use", "better", "worse", "compliance", "preference"):
        assert prohibited not in first.casefold()


def test_combined_renderer_flags_add_each_optional_heading_once() -> None:
    portfolio = _portfolio(20)
    report = analyze_visual_habits(portfolio, _datasets(portfolio), ())
    rendered = render_visual_habits(
        report,
        details=True,
        gallery_breakdown=True,
        year_breakdown=True,
        camera_breakdown=True,
        lens_breakdown=True,
        orientation_breakdown=True,
    )

    for heading in (
        "Detailed Measurement Evidence",
        "Gallery Comparison",
        "Capture-Year Breakdown",
        "Camera Comparison",
        "Lens Comparison",
        "Orientation Comparison",
    ):
        assert rendered.count(heading) == 1
