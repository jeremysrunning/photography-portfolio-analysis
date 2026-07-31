"""Persistence privacy regression for people-placement evidence."""

import sqlite3
from datetime import UTC, datetime

import numpy as np
from PIL import Image

from ppa.models import Asset, AssetMetadata, MediaType, Portfolio, SourceReference
from ppa.storage import SQLitePortfolioRepository
from research.people_face_calibration.analysis import ANALYZER_IDENTITY, PeoplePlacementAnalyzer
from research.people_face_calibration.detectors import extract_yunet_detections


class EmptyAdapter:
    def infer(self, rgb):
        return ()


class FaceAdapter:
    def __init__(self, output):
        self.output = output

    def infer(self, rgb):
        return self.output


def test_yunet_landmark_sentinels_never_reach_sqlite(tmp_path) -> None:
    sentinel = 9876.543
    raw = np.array([[1, 2, 3, 4, *([sentinel] * 10), 0.75]], dtype=np.float32)
    narrowed = extract_yunet_detections(raw)
    analyzer = PeoplePlacementAnalyzer(lambda: EmptyAdapter(), lambda: FaceAdapter(narrowed))
    asset = Asset(
        SourceReference("asset", "https://example.test/asset"),
        AssetMetadata(MediaType.PHOTOGRAPH),
    )
    portfolio = Portfolio(
        "test",
        SourceReference("portfolio", "https://example.test/portfolio"),
        "Portfolio",
        assets=(asset,),
    )
    database = tmp_path / "portfolio.sqlite3"
    with SQLitePortfolioRepository(database) as repository:
        repository.save(portfolio)
        assert repository.claim_visual_analysis("test", "portfolio", "asset", ANALYZER_IDENTITY)
        results = analyzer.analyze(asset, Image.new("RGB", (100, 100)), None)  # type: ignore[arg-type]
        repository.complete_visual_analysis(
            "test",
            "portfolio",
            "asset",
            ANALYZER_IDENTITY,
            results,
            at=datetime(2026, 7, 30, tzinfo=UTC),
        )
        loaded = repository.visual_analysis_snapshot(
            "test", "portfolio", "asset", ANALYZER_IDENTITY
        )

    with sqlite3.connect(database) as connection:
        persisted_json = "\n".join(
            str(row[0])
            for row in connection.execute("SELECT value_json FROM visual_analysis_results")
        ).lower()
    assert str(sentinel) not in persisted_json
    forbidden = (
        b"landmark",
        b"keypoint",
        b"embedding",
        b"descriptor",
        b"identity",
        b"tracking",
        b"demographic",
        b"emotion",
    )
    assert all(term.decode() not in persisted_json for term in forbidden)
    assert loaded.results
