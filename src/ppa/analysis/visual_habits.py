"""Pure aggregation for the deterministic portfolio visual-habits report."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from math import isfinite
from statistics import median

from ppa.analysis.assets import asset_value, camera_name, text_value
from ppa.analysis.color_luminance import ANALYZER_IDENTITY as COLOR_IDENTITY
from ppa.analysis.composition_saliency import (
    ANALYZER_IDENTITY as SALIENCY_IDENTITY,
)
from ppa.analysis.composition_saliency import (
    GRID_REGION_ORDER,
)
from ppa.analysis.preview_structure import ANALYZER_IDENTITY as STRUCTURE_IDENTITY
from ppa.models import Asset, MediaType, Portfolio
from ppa.storage import VisualAnalysisRecord
from ppa.visual import AnalyzerIdentity, VisualResult, VisualResultKind, VisualRunStatus

MIN_SEGMENT_SAMPLE = 20
MIN_GALLERY_SNAPSHOT_COVERAGE = 0.5
DISPLAY_SCALAR_DIGITS = 6

PRODUCTION_IDENTITIES = (COLOR_IDENTITY, SALIENCY_IDENTITY, STRUCTURE_IDENTITY)


class CatalogStatus(StrEnum):
    """Validation outcome for one retained successful snapshot."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    MALFORMED = "malformed"
    COMPLETE_WITH_EXTRAS = "complete_with_extras"


@dataclass(frozen=True, slots=True)
class VisualAnalyzerDataset:
    """Transient normalized assets and snapshots for one exact identity."""

    identity: AnalyzerIdentity
    records: tuple[VisualAnalysisRecord, ...]


@dataclass(frozen=True, slots=True)
class ResultAvailability:
    """Availability of one validated result under an explicit denominator."""

    name: str
    available: int
    denominator: int
    denominator_description: str
    unit: str | None
    method_name: str
    method_version: str

    @property
    def percent(self) -> float:
        return self.available / self.denominator * 100 if self.denominator else 0.0


@dataclass(frozen=True, slots=True)
class ScalarSummary:
    """Compact distribution of one deterministic scalar measurement."""

    name: str
    unit: str
    count: int
    denominator: int
    minimum: float
    median: float
    maximum: float

    @property
    def percent(self) -> float:
        return self.count / self.denominator * 100 if self.denominator else 0.0


@dataclass(frozen=True, slots=True)
class BooleanSummary:
    """True-value count for one deterministic evidence or support result."""

    name: str
    true_count: int
    count: int

    @property
    def percent(self) -> float:
        return self.true_count / self.count * 100 if self.count else 0.0


@dataclass(frozen=True, slots=True)
class PointSummary:
    """Median normalized coordinates for validated points."""

    name: str
    count: int
    denominator: int
    median_x: float
    median_y: float

    @property
    def percent(self) -> float:
        return self.count / self.denominator * 100 if self.denominator else 0.0


@dataclass(frozen=True, slots=True)
class RegionalMassSummary:
    """Mean row-major mass for validated 3-by-3 saliency grids."""

    count: int
    denominator: int
    order: tuple[str, ...]
    masses: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class PaletteBinSummary:
    """Photograph recurrence for one persisted quantized sRGB center."""

    rgb: tuple[int, int, int]
    photograph_count: int
    denominator: int

    @property
    def percent(self) -> float:
        return self.photograph_count / self.denominator * 100 if self.denominator else 0.0


@dataclass(frozen=True, slots=True)
class AnalyzerEvidence:
    """Current state and retained-snapshot evidence for one exact identity."""

    identity: AnalyzerIdentity
    historical_identities: tuple[AnalyzerIdentity, ...]
    eligible_photographs: int
    pending: int
    cancellation_interrupted_pending: int
    running: int
    completed: int
    failed: int
    skipped: int
    successful_snapshots: int
    retained_under_noncompleted_state: int
    complete_expected_snapshots: int
    incomplete_expected_snapshots: int
    malformed_snapshots: int
    snapshots_with_unexpected_entries: int
    unexpected_entry_count: int
    measurement_results: int
    classification_results: int
    result_availability: tuple[ResultAvailability, ...]


@dataclass(frozen=True, slots=True)
class AnalyzerHabits:
    """Validated aggregate measurements for one analyzer family."""

    evidence: AnalyzerEvidence
    scalars: tuple[ScalarSummary, ...]
    booleans: tuple[BooleanSummary, ...]
    point: PointSummary | None = None
    regional_mass: RegionalMassSummary | None = None
    palette_bins: tuple[PaletteBinSummary, ...] = ()


@dataclass(frozen=True, slots=True)
class SegmentMeasurement:
    """One qualifying scalar distribution within a metadata segment."""

    analyzer_name: str
    successful_snapshots: int
    summary: ScalarSummary


@dataclass(frozen=True, slots=True)
class SegmentSummary:
    """Qualifying visual measurements for one identity-free display segment."""

    label: str
    eligible_photographs: int
    measurements: tuple[SegmentMeasurement, ...]


@dataclass(frozen=True, slots=True)
class SegmentSection:
    """One deterministic segment family and its omitted-segment count."""

    kind: str
    segments: tuple[SegmentSummary, ...]
    omitted_segments: int


@dataclass(frozen=True, slots=True)
class YearlyScalarSummary:
    """One qualifying scalar measurement in one recorded capture year."""

    year: int
    analyzer_name: str
    summary: ScalarSummary


@dataclass(frozen=True, slots=True)
class ConsecutiveYearDifference:
    """Largest qualifying adjacent-year median difference for one measurement."""

    name: str
    analyzer_name: str
    from_year: int
    to_year: int
    from_count: int
    to_count: int
    from_median: float
    to_median: float
    difference: float
    unit: str


@dataclass(frozen=True, slots=True)
class UnavailableAnalyzerFamily:
    """A deliberately unavailable semantic analyzer family."""

    family: str
    reason: str
    issue: int


@dataclass(frozen=True, slots=True)
class VisualHabitsReport:
    """Complete immutable source-agnostic visual-habits result."""

    title: str
    eligible_photographs: int
    analyzers: tuple[AnalyzerHabits, ...]
    yearly_summaries: tuple[YearlyScalarSummary, ...]
    yearly_differences: tuple[ConsecutiveYearDifference, ...]
    gallery_segments: SegmentSection
    year_segments: SegmentSection
    camera_segments: SegmentSection
    lens_segments: SegmentSection
    orientation_segments: SegmentSection
    unavailable_families: tuple[UnavailableAnalyzerFamily, ...]


@dataclass(frozen=True, slots=True)
class _ValidatedRecord:
    asset: Asset
    results: Mapping[str, VisualResult]
    status: CatalogStatus
    extras: int


@dataclass(frozen=True, slots=True)
class _Catalog:
    names: tuple[str, ...]
    scalar_units: Mapping[str, str]


_COLOR_CATALOG = _Catalog(
    (
        "luminance_mean",
        "luminance_median",
        "shadow_luminance_tail_proportion",
        "highlight_luminance_tail_proportion",
        "saturation_mean",
        "saturation_median",
        "colorfulness",
        "dominant_palette",
        "palette_entropy",
    ),
    {
        "luminance_mean": "relative_linear_luminance",
        "luminance_median": "relative_linear_luminance",
        "shadow_luminance_tail_proportion": "proportion",
        "highlight_luminance_tail_proportion": "proportion",
        "saturation_mean": "proportion",
        "saturation_median": "proportion",
        "colorfulness": "normalized_srgb_formula_output",
        "palette_entropy": "normalized_entropy",
    },
)
_SALIENCY_CATALOG = _Catalog(
    (
        "saliency_evidence",
        "saliency_centroid",
        "saliency_spread",
        "saliency_grid_3x3",
        "saliency_center_distance",
        "saliency_thirds_line_distance",
        "saliency_thirds_intersection_distance",
    ),
    {
        "saliency_spread": "frame_diagonal_fraction",
        "saliency_center_distance": "normalized_distance",
        "saliency_thirds_line_distance": "normalized_distance",
        "saliency_thirds_intersection_distance": "normalized_distance",
    },
)
_STRUCTURE_CATALOG = _Catalog(
    (
        "structure_measurement_support",
        "global_sharpness_proxy",
        "gradient_directional_evidence",
        "gradient_directional_anisotropy",
        "edge_density",
        "local_luminance_contrast",
        "spatial_sharpness_variation",
        "noise_proxy_evidence",
        "noise_residual_mad",
        "luminance_p95_p05_span",
    ),
    {
        "global_sharpness_proxy": "normalized_laplacian_variance",
        "gradient_directional_anisotropy": "proportion",
        "edge_density": "proportion",
        "local_luminance_contrast": "normalized_local_rms_contrast",
        "spatial_sharpness_variation": "normalized_spatial_variation",
        "noise_residual_mad": "relative_linear_luminance",
        "luminance_p95_p05_span": "relative_linear_luminance_span",
    },
)
_CATALOGS = {
    COLOR_IDENTITY.name: _COLOR_CATALOG,
    SALIENCY_IDENTITY.name: _SALIENCY_CATALOG,
    STRUCTURE_IDENTITY.name: _STRUCTURE_CATALOG,
}
_EXPECTED_PROVENANCE = {
    "luminance_mean": ("relative_linear_luminance", "srgb-relative-luminance", "1"),
    "luminance_median": ("relative_linear_luminance", "srgb-relative-luminance", "1"),
    "shadow_luminance_tail_proportion": ("proportion", "relative-luminance-tail", "1"),
    "highlight_luminance_tail_proportion": ("proportion", "relative-luminance-tail", "1"),
    "saturation_mean": ("proportion", "srgb-hsv-saturation", "1"),
    "saturation_median": ("proportion", "srgb-hsv-saturation", "1"),
    "colorfulness": (
        "normalized_srgb_formula_output",
        "hasler-susstrunk-colorfulness",
        "1",
    ),
    "dominant_palette": ("encoded_srgb", "srgb-histogram-palette", "1"),
    "palette_entropy": ("normalized_entropy", "srgb-histogram-entropy", "1"),
    "saliency_evidence": ("boolean", "spectral-residual-evidence", "1"),
    "saliency_centroid": (
        "normalized_frame_coordinate",
        "spectral-residual-centroid",
        "1",
    ),
    "saliency_spread": ("frame_diagonal_fraction", "spectral-residual-spread", "1"),
    "saliency_grid_3x3": ("proportion", "spectral-residual-grid-mass", "1"),
    "saliency_center_distance": (
        "normalized_distance",
        "saliency-centroid-frame-center-distance",
        "1",
    ),
    "saliency_thirds_line_distance": (
        "normalized_distance",
        "saliency-centroid-thirds-line-distance",
        "1",
    ),
    "saliency_thirds_intersection_distance": (
        "normalized_distance",
        "saliency-centroid-thirds-intersection-distance",
        "1",
    ),
    **{
        name: (unit, name.replace("_", "-"), "1")
        for name, unit in {
            "structure_measurement_support": "boolean",
            "global_sharpness_proxy": "normalized_laplacian_variance",
            "gradient_directional_evidence": "boolean",
            "gradient_directional_anisotropy": "proportion",
            "edge_density": "proportion",
            "local_luminance_contrast": "normalized_local_rms_contrast",
            "spatial_sharpness_variation": "normalized_spatial_variation",
            "noise_proxy_evidence": "boolean",
            "noise_residual_mad": "relative_linear_luminance",
            "luminance_p95_p05_span": "relative_linear_luminance_span",
        }.items()
    },
}


def analyze_visual_habits(
    portfolio: Portfolio,
    datasets: tuple[VisualAnalyzerDataset, ...],
    persisted_identities: tuple[AnalyzerIdentity, ...],
) -> VisualHabitsReport:
    """Aggregate exact-identity persisted measurements without source access."""
    photographs = tuple(
        asset for asset in portfolio.assets if asset.media_type is MediaType.PHOTOGRAPH
    )
    supplied = {dataset.identity: dataset for dataset in datasets}
    analyzer_habits: list[AnalyzerHabits] = []
    valid_by_analyzer: dict[str, tuple[_ValidatedRecord, ...]] = {}
    successful_by_analyzer: dict[str, frozenset[int]] = {}
    for identity in PRODUCTION_IDENTITIES:
        dataset = supplied.get(identity, VisualAnalyzerDataset(identity, ()))
        records = tuple(
            record for record in dataset.records if record.asset.media_type is MediaType.PHOTOGRAPH
        )
        by_asset = {id(record.asset): record for record in records}
        completed_records = tuple(
            by_asset.get(
                id(asset),
                VisualAnalysisRecord(
                    asset,
                    _pending_snapshot(identity),
                ),
            )
            for asset in photographs
        )
        habits, validated = _analyze_identity(
            identity,
            completed_records,
            tuple(
                item
                for item in persisted_identities
                if item.name == identity.name and item != identity
            ),
        )
        analyzer_habits.append(habits)
        valid_by_analyzer[identity.name] = validated
        successful_by_analyzer[identity.name] = frozenset(
            id(record.asset)
            for record in completed_records
            if record.snapshot.state.has_successful_snapshot
        )

    sections = _segment_sections(
        portfolio,
        photographs,
        valid_by_analyzer,
        successful_by_analyzer,
    )
    yearly = _yearly_summaries(photographs, valid_by_analyzer)
    return VisualHabitsReport(
        title=portfolio.title,
        eligible_photographs=len(photographs),
        analyzers=tuple(analyzer_habits),
        yearly_summaries=yearly,
        yearly_differences=_yearly_differences(yearly),
        gallery_segments=sections["gallery"],
        year_segments=sections["year"],
        camera_segments=sections["camera"],
        lens_segments=sections["lens"],
        orientation_segments=sections["orientation"],
        unavailable_families=(
            UnavailableAnalyzerFamily(
                "People and face analysis",
                "No production detector has passed the approved governance and validation gates.",
                38,
            ),
            UnavailableAnalyzerFamily(
                "Scene and environment analysis",
                "No production model has passed the approved governance and validation gates.",
                40,
            ),
        ),
    )


def _pending_snapshot(identity: AnalyzerIdentity):
    from ppa.visual import VisualAnalysisSnapshot, VisualRunState

    return VisualAnalysisSnapshot(
        identity,
        VisualRunState(VisualRunStatus.PENDING, 0, None),
    )


def _analyze_identity(
    identity: AnalyzerIdentity,
    records: tuple[VisualAnalysisRecord, ...],
    historical: tuple[AnalyzerIdentity, ...],
) -> tuple[AnalyzerHabits, tuple[_ValidatedRecord, ...]]:
    states = Counter(record.snapshot.state.status for record in records)
    interrupted = sum(
        record.snapshot.state.status is VisualRunStatus.PENDING
        and record.snapshot.state.interruption_category is not None
        for record in records
    )
    successful = tuple(
        record for record in records if record.snapshot.state.has_successful_snapshot
    )
    validated = tuple(_validate_record(record, _CATALOGS[identity.name]) for record in successful)
    complete = tuple(
        item
        for item in validated
        if item.status in {CatalogStatus.COMPLETE, CatalogStatus.COMPLETE_WITH_EXTRAS}
    )
    availability = _availability(identity.name, complete)
    evidence = AnalyzerEvidence(
        identity=identity,
        historical_identities=tuple(sorted(historical, key=_identity_key)),
        eligible_photographs=len(records),
        pending=states[VisualRunStatus.PENDING],
        cancellation_interrupted_pending=interrupted,
        running=states[VisualRunStatus.RUNNING],
        completed=states[VisualRunStatus.COMPLETED],
        failed=states[VisualRunStatus.FAILED],
        skipped=states[VisualRunStatus.SKIPPED],
        successful_snapshots=len(successful),
        retained_under_noncompleted_state=sum(
            record.snapshot.state.status is not VisualRunStatus.COMPLETED for record in successful
        ),
        complete_expected_snapshots=len(complete),
        incomplete_expected_snapshots=sum(
            item.status is CatalogStatus.INCOMPLETE for item in validated
        ),
        malformed_snapshots=sum(item.status is CatalogStatus.MALFORMED for item in validated),
        snapshots_with_unexpected_entries=sum(
            item.status is CatalogStatus.COMPLETE_WITH_EXTRAS for item in validated
        ),
        unexpected_entry_count=sum(
            item.extras for item in validated if item.status is CatalogStatus.COMPLETE_WITH_EXTRAS
        ),
        measurement_results=sum(
            result.kind is VisualResultKind.MEASUREMENT
            for item in complete
            for result in item.results.values()
        ),
        classification_results=sum(
            result.kind is VisualResultKind.CLASSIFICATION
            for item in complete
            for result in item.results.values()
        ),
        result_availability=availability,
    )
    return (
        AnalyzerHabits(
            evidence=evidence,
            scalars=_scalar_summaries(identity.name, complete),
            booleans=_boolean_summaries(complete),
            point=_point_summary(complete) if identity.name == SALIENCY_IDENTITY.name else None,
            regional_mass=(
                _regional_mass_summary(complete)
                if identity.name == SALIENCY_IDENTITY.name
                else None
            ),
            palette_bins=(
                _palette_summaries(complete) if identity.name == COLOR_IDENTITY.name else ()
            ),
        ),
        complete,
    )


def _validate_record(record: VisualAnalysisRecord, catalog: _Catalog) -> _ValidatedRecord:
    results: dict[str, VisualResult] = {}
    duplicate = False
    for result in record.snapshot.results:
        if result.name in results:
            duplicate = True
        results[result.name] = result
    extras = len(set(results) - set(catalog.names))
    expected = {name: results[name] for name in catalog.names if name in results}
    if duplicate or any(not _valid_expected(name, result) for name, result in expected.items()):
        return _ValidatedRecord(record.asset, expected, CatalogStatus.MALFORMED, extras)
    required, forbidden = _required_and_forbidden(record.snapshot.identity.name, expected)
    if forbidden & expected.keys():
        return _ValidatedRecord(record.asset, expected, CatalogStatus.MALFORMED, extras)
    if not required <= expected.keys():
        return _ValidatedRecord(record.asset, expected, CatalogStatus.INCOMPLETE, extras)
    status = CatalogStatus.COMPLETE_WITH_EXTRAS if extras else CatalogStatus.COMPLETE
    return _ValidatedRecord(record.asset, expected, status, extras)


def _required_and_forbidden(
    analyzer_name: str,
    results: Mapping[str, VisualResult],
) -> tuple[set[str], set[str]]:
    if analyzer_name == COLOR_IDENTITY.name:
        return set(_COLOR_CATALOG.names), set()
    if analyzer_name == SALIENCY_IDENTITY.name:
        if "saliency_evidence" not in results:
            return {"saliency_evidence"}, set()
        evidence = _boolean_value(results.get("saliency_evidence"))
        assert evidence is not None
        geometry = {
            "saliency_centroid",
            "saliency_spread",
            "saliency_center_distance",
            "saliency_thirds_line_distance",
            "saliency_thirds_intersection_distance",
        }
        if evidence:
            return {"saliency_evidence", "saliency_grid_3x3", *geometry}, set()
        return {"saliency_evidence"}, geometry
    if "structure_measurement_support" not in results:
        return {"structure_measurement_support"}, set()
    support = _boolean_value(results.get("structure_measurement_support"))
    assert support is not None
    remaining = set(_STRUCTURE_CATALOG.names) - {"structure_measurement_support"}
    if not support:
        return {"structure_measurement_support"}, remaining
    directional = _boolean_value(results.get("gradient_directional_evidence"))
    noise = _boolean_value(results.get("noise_proxy_evidence"))
    if directional is None or noise is None:
        return {
            "structure_measurement_support",
            "global_sharpness_proxy",
            "gradient_directional_evidence",
            "edge_density",
            "local_luminance_contrast",
            "spatial_sharpness_variation",
            "noise_proxy_evidence",
            "luminance_p95_p05_span",
        }, set()
    required = remaining - {"gradient_directional_anisotropy", "noise_residual_mad"}
    forbidden: set[str] = set()
    if directional:
        required.add("gradient_directional_anisotropy")
    else:
        forbidden.add("gradient_directional_anisotropy")
    if noise:
        required.add("noise_residual_mad")
    else:
        forbidden.add("noise_residual_mad")
    required.add("structure_measurement_support")
    return required, forbidden


def _valid_expected(name: str, result: VisualResult) -> bool:
    if result.kind is not VisualResultKind.MEASUREMENT:
        return False
    unit, _, _ = _EXPECTED_PROVENANCE[name]
    if result.unit != unit:
        return False
    if name in {
        "saliency_evidence",
        "structure_measurement_support",
        "gradient_directional_evidence",
        "noise_proxy_evidence",
    }:
        return isinstance(result.value, bool)
    if name == "saliency_centroid":
        return _valid_point(result.value)
    if name == "saliency_grid_3x3":
        return _valid_grid(result.value)
    if name == "dominant_palette":
        return _valid_palette(result.value)
    if not _finite_number(result.value):
        return False
    numeric = float(result.value)
    if name == "colorfulness":
        return numeric >= 0
    if name == "noise_residual_mad":
        return 0 <= numeric <= 2.9653
    return 0 <= numeric <= 1


def _valid_point(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("type") == "point"
        and _unit_number(value.get("x"))
        and _unit_number(value.get("y"))
    )


def _valid_grid(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    order = value.get("order")
    masses = value.get("masses")
    return (
        isinstance(order, tuple | list)
        and tuple(order) == GRID_REGION_ORDER
        and isinstance(masses, tuple | list)
        and len(masses) == 9
        and all(_unit_number(item) for item in masses)
        and abs(sum(float(item) for item in masses) - 1.0) <= 1e-8
    )


def _valid_palette(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("color_space") != "srgb" or value.get("quantization") != "4bit_per_channel":
        return False
    colors = value.get("colors")
    coverage = value.get("covered_pixel_proportion")
    if (
        not isinstance(colors, tuple | list)
        or not 1 <= len(colors) <= 5
        or not _unit_number(coverage)
    ):
        return False
    for item in colors:
        if not isinstance(item, Mapping):
            return False
        rgb = item.get("rgb")
        if (
            not isinstance(rgb, tuple | list)
            or len(rgb) != 3
            or any(
                isinstance(channel, bool)
                or not isinstance(channel, int)
                or channel not in range(8, 256, 16)
                for channel in rgb
            )
            or not _unit_number(item.get("proportion"))
        ):
            return False
    return abs(sum(float(item["proportion"]) for item in colors) - 1.0) <= 1e-8


def _finite_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float) and isfinite(float(value))


def _unit_number(value: object) -> bool:
    return _finite_number(value) and 0 <= float(value) <= 1


def _boolean_value(result: VisualResult | None) -> bool | None:
    return result.value if result is not None and isinstance(result.value, bool) else None


def _availability(
    analyzer_name: str,
    records: tuple[_ValidatedRecord, ...],
) -> tuple[ResultAvailability, ...]:
    catalog = _CATALOGS[analyzer_name]
    output = []
    for name in catalog.names:
        eligible, description = _conditional_records(analyzer_name, name, records)
        available = sum(name in item.results for item in eligible)
        unit, method_name, method_version = _EXPECTED_PROVENANCE[name]
        output.append(
            ResultAvailability(
                name,
                available,
                len(eligible),
                description,
                unit,
                method_name,
                method_version,
            )
        )
    return tuple(output)


def _conditional_records(
    analyzer_name: str,
    name: str,
    records: tuple[_ValidatedRecord, ...],
) -> tuple[tuple[_ValidatedRecord, ...], str]:
    if name in {
        "saliency_centroid",
        "saliency_spread",
        "saliency_center_distance",
        "saliency_thirds_line_distance",
        "saliency_thirds_intersection_distance",
    }:
        return (
            tuple(item for item in records if item.results["saliency_evidence"].value is True),
            "complete snapshots with saliency evidence",
        )
    if name == "saliency_grid_3x3":
        return records, "complete saliency snapshots"
    if analyzer_name == STRUCTURE_IDENTITY.name and name != "structure_measurement_support":
        supported = tuple(
            item for item in records if item.results["structure_measurement_support"].value is True
        )
        if name == "gradient_directional_anisotropy":
            return (
                tuple(
                    item
                    for item in supported
                    if item.results["gradient_directional_evidence"].value is True
                ),
                "supported snapshots with directional evidence",
            )
        if name == "noise_residual_mad":
            return (
                tuple(
                    item for item in supported if item.results["noise_proxy_evidence"].value is True
                ),
                "supported snapshots with noise-proxy evidence",
            )
        return supported, "snapshots with structure measurement support"
    return records, "complete expected snapshots"


def _scalar_summaries(
    analyzer_name: str,
    records: tuple[_ValidatedRecord, ...],
) -> tuple[ScalarSummary, ...]:
    output = []
    for name, unit in _CATALOGS[analyzer_name].scalar_units.items():
        eligible, _ = _conditional_records(analyzer_name, name, records)
        values = [float(item.results[name].value) for item in eligible if name in item.results]
        if values:
            output.append(_summary(name, unit, values, len(eligible)))
    return tuple(output)


def _boolean_summaries(records: tuple[_ValidatedRecord, ...]) -> tuple[BooleanSummary, ...]:
    names = (
        "saliency_evidence",
        "structure_measurement_support",
        "gradient_directional_evidence",
        "noise_proxy_evidence",
    )
    output = []
    for name in names:
        values = [item.results[name].value for item in records if name in item.results]
        if values:
            output.append(BooleanSummary(name, sum(value is True for value in values), len(values)))
    return tuple(output)


def _summary(name: str, unit: str, values: list[float], denominator: int) -> ScalarSummary:
    return ScalarSummary(
        name,
        unit,
        len(values),
        denominator,
        min(values),
        float(median(values)),
        max(values),
    )


def _point_summary(records: tuple[_ValidatedRecord, ...]) -> PointSummary | None:
    eligible, _ = _conditional_records(SALIENCY_IDENTITY.name, "saliency_centroid", records)
    points = [item.results["saliency_centroid"].value for item in eligible]
    if not points:
        return None
    return PointSummary(
        "saliency_centroid",
        len(points),
        len(eligible),
        float(median(float(point["x"]) for point in points)),  # type: ignore[index]
        float(median(float(point["y"]) for point in points)),  # type: ignore[index]
    )


def _regional_mass_summary(
    records: tuple[_ValidatedRecord, ...],
) -> RegionalMassSummary | None:
    grids = [
        item.results["saliency_grid_3x3"].value
        for item in records
        if "saliency_grid_3x3" in item.results
    ]
    if not grids:
        return None
    means = [
        sum(float(grid["masses"][index]) for grid in grids) / len(grids)  # type: ignore[index]
        for index in range(9)
    ]
    quantum = Decimal("0.00000001")
    rounded = [
        Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_EVEN) for value in means[:8]
    ]
    rounded.append(Decimal("1.00000000") - sum(rounded, Decimal(0)))
    return RegionalMassSummary(
        len(grids),
        len(records),
        GRID_REGION_ORDER,
        tuple(float(value) for value in rounded),
    )


def _palette_summaries(records: tuple[_ValidatedRecord, ...]) -> tuple[PaletteBinSummary, ...]:
    palettes = [
        item.results["dominant_palette"].value
        for item in records
        if "dominant_palette" in item.results
    ]
    counts: Counter[tuple[int, int, int]] = Counter()
    for palette in palettes:
        represented = {
            tuple(int(channel) for channel in color["rgb"])  # type: ignore[index]
            for color in palette["colors"]  # type: ignore[index]
        }
        counts.update(represented)
    return tuple(
        PaletteBinSummary(rgb, count, len(palettes))
        for rgb, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )


def _yearly_summaries(
    photographs: tuple[Asset, ...],
    valid: Mapping[str, tuple[_ValidatedRecord, ...]],
) -> tuple[YearlyScalarSummary, ...]:
    by_asset = {
        analyzer: {id(item.asset): item for item in records} for analyzer, records in valid.items()
    }
    years = sorted(
        {asset.captured_at.year for asset in photographs if asset.captured_at is not None}
    )
    output = []
    for year in years:
        assets = tuple(
            asset
            for asset in photographs
            if asset.captured_at is not None and asset.captured_at.year == year
        )
        for identity in PRODUCTION_IDENTITIES:
            records = tuple(
                by_asset[identity.name][id(asset)]
                for asset in assets
                if id(asset) in by_asset[identity.name]
            )
            for summary in _scalar_summaries(identity.name, records):
                if summary.count >= MIN_SEGMENT_SAMPLE:
                    output.append(YearlyScalarSummary(year, identity.name, summary))
    return tuple(output)


def _yearly_differences(
    summaries: tuple[YearlyScalarSummary, ...],
) -> tuple[ConsecutiveYearDifference, ...]:
    selected = (
        (COLOR_IDENTITY.name, "luminance_median"),
        (SALIENCY_IDENTITY.name, "saliency_center_distance"),
        (STRUCTURE_IDENTITY.name, "edge_density"),
    )
    output = []
    for analyzer_name, name in selected:
        values = {
            item.year: item.summary
            for item in summaries
            if item.analyzer_name == analyzer_name and item.summary.name == name
        }
        candidates = []
        for year in sorted(values):
            following = values.get(year + 1)
            if following is None:
                continue
            current = values[year]
            difference = following.median - current.median
            candidates.append(
                (round(abs(difference), 12), -year, year, current, following, difference)
            )
        if not candidates:
            continue
        _, _, year, current, following, difference = max(candidates)
        output.append(
            ConsecutiveYearDifference(
                name,
                analyzer_name,
                year,
                year + 1,
                current.count,
                following.count,
                current.median,
                following.median,
                difference,
                current.unit,
            )
        )
    return tuple(output)


def _segment_sections(
    portfolio: Portfolio,
    photographs: tuple[Asset, ...],
    valid: Mapping[str, tuple[_ValidatedRecord, ...]],
    successful: Mapping[str, frozenset[int]],
) -> dict[str, SegmentSection]:
    groups: dict[str, list[tuple[str, tuple[Asset, ...]]]] = {
        "gallery": [
            (
                gallery.title,
                tuple(
                    asset
                    for asset in portfolio.gallery_assets(gallery)
                    if asset.media_type is MediaType.PHOTOGRAPH
                ),
            )
            for gallery in portfolio.galleries
        ],
        "year": [
            (
                str(year),
                tuple(
                    asset
                    for asset in photographs
                    if asset.captured_at is not None and asset.captured_at.year == year
                ),
            )
            for year in sorted(
                {asset.captured_at.year for asset in photographs if asset.captured_at is not None}
            )
        ],
        "camera": _metadata_groups(photographs, camera_name),
        "lens": _metadata_groups(
            photographs,
            lambda asset: text_value(asset, "Lens", "LensModel", "lens", "lens_model"),
        ),
        "orientation": [
            (label, tuple(asset for asset in photographs if _orientation(asset) == label))
            for label in ("landscape", "portrait", "square")
            if any(_orientation(asset) == label for asset in photographs)
        ],
    }
    valid_maps = {
        name: {id(item.asset): item for item in records} for name, records in valid.items()
    }
    output = {}
    for kind, candidates in groups.items():
        segments = []
        omitted = 0
        for label, assets in candidates:
            measurements = []
            for identity in PRODUCTION_IDENTITIES:
                records = tuple(
                    valid_maps[identity.name][id(asset)]
                    for asset in assets
                    if id(asset) in valid_maps[identity.name]
                )
                successful_count = sum(id(asset) in successful[identity.name] for asset in assets)
                snapshot_coverage = successful_count / len(assets) if assets else 0.0
                for summary in _scalar_summaries(identity.name, records):
                    qualifies = summary.count >= MIN_SEGMENT_SAMPLE
                    if kind == "gallery":
                        qualifies = qualifies and snapshot_coverage >= MIN_GALLERY_SNAPSHOT_COVERAGE
                    if qualifies:
                        measurements.append(
                            SegmentMeasurement(identity.name, successful_count, summary)
                        )
            if measurements:
                segments.append(
                    SegmentSummary(
                        label,
                        len(assets),
                        tuple(
                            sorted(
                                measurements,
                                key=lambda item: (item.analyzer_name, item.summary.name),
                            )
                        ),
                    )
                )
            else:
                omitted += 1
        if kind in {"gallery", "camera", "lens"}:
            segments.sort(key=lambda item: (-item.eligible_photographs, item.label.casefold()))
        output[kind] = SegmentSection(kind, tuple(segments), omitted)
    return output


def _metadata_groups(
    assets: tuple[Asset, ...],
    value,
) -> list[tuple[str, tuple[Asset, ...]]]:
    labels = sorted(
        {label for asset in assets if (label := value(asset)) is not None},
        key=str.casefold,
    )
    return [(label, tuple(asset for asset in assets if value(asset) == label)) for label in labels]


def _orientation(asset: Asset) -> str | None:
    width = _positive_number(asset, "OriginalWidth", "width", "Width")
    height = _positive_number(asset, "OriginalHeight", "height", "Height")
    if width is None or height is None:
        return None
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def _positive_number(asset: Asset, *names: str) -> float | None:
    value = asset_value(asset, *names)
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) and numeric > 0 else None


def _identity_key(identity: AnalyzerIdentity) -> tuple[str, str, str]:
    return identity.name, identity.version, identity.configuration_version
