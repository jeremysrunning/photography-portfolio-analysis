"""Source-agnostic portfolio analysis."""

from ppa.analysis.baseline import BaselineReport, Coverage, analyze_baseline
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

__all__ = [
    "BaselineReport",
    "CameraEra",
    "CaptureGap",
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
    "YearChange",
    "YearlyCamera",
    "analyze_baseline",
    "analyze_equipment",
    "analyze_focal_lengths",
    "analyze_timeline",
]
