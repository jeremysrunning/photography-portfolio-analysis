"""Source-agnostic portfolio analysis."""

from ppa.analysis.baseline import BaselineReport, Coverage, analyze_baseline
from ppa.analysis.color_luminance import ColorLuminanceAnalyzer
from ppa.analysis.composition_saliency import CompositionSaliencyAnalyzer
from ppa.analysis.equipment import EquipmentReport, YearlyCamera, analyze_equipment
from ppa.analysis.focal_length import (
    FocalLengthBasis,
    FocalLengthReport,
    FocalLengthSegment,
    FocalLengthSummary,
    FocalLengthYearChange,
    analyze_focal_lengths,
)
from ppa.analysis.preview_structure import PreviewStructureAnalyzer
from ppa.analysis.timeline import (
    CameraEra,
    CaptureGap,
    PeriodCount,
    TimelineReport,
    TimelineSegment,
    YearChange,
    analyze_timeline,
)
from ppa.analysis.visual import (
    VisualAnalyzer,
    allows_empty_results,
    get_visual_analyzer,
    list_visual_analyzers,
    register_visual_analyzer,
)

register_visual_analyzer(ColorLuminanceAnalyzer())
register_visual_analyzer(CompositionSaliencyAnalyzer())
register_visual_analyzer(PreviewStructureAnalyzer())

__all__ = [
    "BaselineReport",
    "CameraEra",
    "CaptureGap",
    "ColorLuminanceAnalyzer",
    "CompositionSaliencyAnalyzer",
    "Coverage",
    "EquipmentReport",
    "FocalLengthBasis",
    "FocalLengthReport",
    "FocalLengthSegment",
    "FocalLengthSummary",
    "FocalLengthYearChange",
    "PeriodCount",
    "PreviewStructureAnalyzer",
    "TimelineReport",
    "TimelineSegment",
    "VisualAnalyzer",
    "YearChange",
    "YearlyCamera",
    "allows_empty_results",
    "analyze_baseline",
    "analyze_equipment",
    "analyze_focal_lengths",
    "analyze_timeline",
    "get_visual_analyzer",
    "list_visual_analyzers",
    "register_visual_analyzer",
]
