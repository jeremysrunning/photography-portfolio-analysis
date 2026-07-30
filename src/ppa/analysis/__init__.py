"""Source-agnostic portfolio analysis."""

from ppa.analysis.baseline import BaselineReport, Coverage, analyze_baseline
from ppa.analysis.color_luminance import ColorLuminanceAnalyzer
from ppa.analysis.equipment import EquipmentReport, YearlyCamera, analyze_equipment
from ppa.analysis.focal_length import (
    FocalLengthBasis,
    FocalLengthReport,
    FocalLengthSegment,
    FocalLengthSummary,
    FocalLengthYearChange,
    analyze_focal_lengths,
)
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

__all__ = [
    "BaselineReport",
    "CameraEra",
    "CaptureGap",
    "ColorLuminanceAnalyzer",
    "Coverage",
    "EquipmentReport",
    "FocalLengthBasis",
    "FocalLengthReport",
    "FocalLengthSegment",
    "FocalLengthSummary",
    "FocalLengthYearChange",
    "PeriodCount",
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
