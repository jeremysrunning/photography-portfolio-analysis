"""Source-agnostic portfolio analysis."""

from ppa.analysis.baseline import BaselineReport, Coverage, analyze_baseline
from ppa.analysis.equipment import EquipmentReport, YearlyCamera, analyze_equipment
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
    "PeriodCount",
    "TimelineReport",
    "TimelineSegment",
    "YearChange",
    "YearlyCamera",
    "analyze_baseline",
    "analyze_equipment",
    "analyze_timeline",
]
