"""Persistence abstractions and implementations."""

from ppa.storage.base import (
    EnrichmentStatus,
    EnrichmentTarget,
    PortfolioRepository,
    VisualAnalysisClaim,
    VisualAnalysisOwnershipLostError,
    VisualAnalysisRecord,
    VisualAnalysisRecoveryResult,
    VisualAnalysisRepository,
)
from ppa.storage.sqlite import SQLitePortfolioRepository, UnsupportedSchemaVersionError

__all__ = [
    "EnrichmentStatus",
    "EnrichmentTarget",
    "PortfolioRepository",
    "SQLitePortfolioRepository",
    "UnsupportedSchemaVersionError",
    "VisualAnalysisClaim",
    "VisualAnalysisOwnershipLostError",
    "VisualAnalysisRecord",
    "VisualAnalysisRecoveryResult",
    "VisualAnalysisRepository",
]
