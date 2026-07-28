"""SQLite persistence for normalized portfolio datasets."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from ppa.models import Asset, Finding, Gallery, JsonValue, Measurement, Observation, Portfolio
from ppa.storage.base import EnrichmentStatus, EnrichmentTarget

SCHEMA_VERSION = 2
_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS portfolios (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    observations_json TEXT NOT NULL,
    findings_json TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);
CREATE TABLE IF NOT EXISTS galleries (
    source TEXT NOT NULL,
    portfolio_source_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    parent_source_id TEXT,
    metadata_json TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (source, portfolio_source_id, source_id),
    FOREIGN KEY (source, portfolio_source_id)
        REFERENCES portfolios(source, source_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS assets (
    source TEXT NOT NULL,
    portfolio_source_id TEXT NOT NULL,
    gallery_source_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    preview_url TEXT,
    captured_at TEXT,
    metadata_json TEXT NOT NULL,
    exif_json TEXT NOT NULL,
    measurements_json TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (source, portfolio_source_id, gallery_source_id, source_id),
    FOREIGN KEY (source, portfolio_source_id, gallery_source_id)
        REFERENCES galleries(source, portfolio_source_id, source_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS asset_enrichments (
    source TEXT NOT NULL,
    portfolio_source_id TEXT NOT NULL,
    asset_source_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
    attempts INTEGER NOT NULL,
    last_error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source, portfolio_source_id, asset_source_id, kind),
    FOREIGN KEY (source, portfolio_source_id)
        REFERENCES portfolios(source, source_id) ON DELETE CASCADE
);
"""


class SQLitePortfolioRepository:
    """Store normalized datasets in a local SQLite database."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._connection: sqlite3.Connection | None = None
        self._initialized = False

    def __enter__(self) -> "SQLitePortfolioRepository":
        self._connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.path)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
        return self._connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        with connection:
            yield connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
            self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._transaction() as connection:
            connection.executescript(_SCHEMA)
            connection.execute(
                "INSERT OR REPLACE INTO schema_metadata (key, value) VALUES ('version', ?)",
                (str(SCHEMA_VERSION),),
            )
        self._initialized = True

    def save(self, portfolio: Portfolio) -> None:
        self.initialize()
        with self._transaction() as connection:
            key = (portfolio.source, portfolio.source_id)
            connection.execute(
                "DELETE FROM portfolios WHERE source = ? AND source_id = ?",
                key,
            )
            connection.execute(
                """
                INSERT INTO portfolios VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    *key,
                    portfolio.title,
                    portfolio.source_url,
                    _json(portfolio.metadata),
                    _json(
                        [
                            {"statement": item.statement, "evidence": item.evidence}
                            for item in portfolio.observations
                        ]
                    ),
                    _json(
                        [
                            {
                                "statement": item.statement,
                                "confidence": item.confidence,
                                "evidence": item.evidence,
                            }
                            for item in portfolio.findings
                        ]
                    ),
                ),
            )
            for gallery_position, gallery in enumerate(portfolio.galleries):
                connection.execute(
                    "INSERT INTO galleries VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        *key,
                        gallery.source_id,
                        gallery.title,
                        gallery.source_url,
                        gallery.parent_source_id,
                        _json(gallery.metadata),
                        gallery_position,
                    ),
                )
                for asset_position, asset in enumerate(gallery.assets):
                    if asset.gallery_source_id != gallery.source_id:
                        raise ValueError("asset gallery_source_id does not match its gallery")
                    connection.execute(
                        "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            *key,
                            gallery.source_id,
                            asset.source_id,
                            asset.source_url,
                            asset.preview_url,
                            asset.captured_at.isoformat() if asset.captured_at else None,
                            _json(asset.metadata),
                            _json(asset.exif),
                            _json(
                                [
                                    {
                                        "name": item.name,
                                        "value": item.value,
                                        "unit": item.unit,
                                        "method": item.method,
                                    }
                                    for item in asset.measurements
                                ]
                            ),
                            asset_position,
                        ),
                    )

    def get(self, source: str, source_id: str) -> Portfolio | None:
        connection = self._connect()
        row = connection.execute(
            "SELECT * FROM portfolios WHERE source = ? AND source_id = ?",
            (source, source_id),
        ).fetchone()
        if row is None:
            return None
        gallery_rows = connection.execute(
            """
            SELECT * FROM galleries
            WHERE source = ? AND portfolio_source_id = ?
            ORDER BY position
            """,
            (source, source_id),
        ).fetchall()
        galleries = tuple(
            self._read_gallery(connection, source, source_id, gallery) for gallery in gallery_rows
        )
        observations = tuple(
            Observation(item["statement"], tuple(item["evidence"]))
            for item in json.loads(row["observations_json"])
        )
        findings = tuple(
            Finding(item["statement"], item["confidence"], tuple(item["evidence"]))
            for item in json.loads(row["findings_json"])
        )
        return Portfolio(
            source=row["source"],
            source_id=row["source_id"],
            title=row["title"],
            source_url=row["source_url"],
            metadata=json.loads(row["metadata_json"]),
            galleries=galleries,
            observations=observations,
            findings=findings,
        )

    def list_keys(self) -> tuple[tuple[str, str], ...]:
        self.initialize()
        rows = self._connect().execute(
            "SELECT source, source_id FROM portfolios ORDER BY source, source_id"
        )
        return tuple((row["source"], row["source_id"]) for row in rows)

    def list_enrichment_targets(
        self,
        source: str,
        portfolio_source_id: str,
        kind: str,
        *,
        retry_failed: bool = False,
        limit: int | None = None,
    ) -> tuple[EnrichmentTarget, ...]:
        self.initialize()
        status_clause = "(enrichment.status IS NULL OR enrichment.status = 'failed')"
        if not retry_failed:
            status_clause = "enrichment.status IS NULL"
        limit_clause = ""
        parameters: list[Any] = [kind, source, portfolio_source_id]
        if limit is not None:
            if limit < 1:
                return ()
            limit_clause = "LIMIT ?"
            parameters.append(limit)
        rows = self._connect().execute(
            f"""
            SELECT assets.source_id, MIN(assets.metadata_json) AS metadata_json
            FROM assets
            LEFT JOIN asset_enrichments AS enrichment
              ON enrichment.source = assets.source
             AND enrichment.portfolio_source_id = assets.portfolio_source_id
             AND enrichment.asset_source_id = assets.source_id
             AND enrichment.kind = ?
            WHERE assets.source = ?
              AND assets.portfolio_source_id = ?
              AND {status_clause}
            GROUP BY assets.source_id
            ORDER BY assets.source_id
            {limit_clause}
            """,
            parameters,
        )
        return tuple(
            EnrichmentTarget(row["source_id"], json.loads(row["metadata_json"])) for row in rows
        )

    def save_asset_enrichment(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        kind: str,
        values: dict[str, JsonValue],
    ) -> None:
        if kind != "exif":
            raise ValueError(f"unsupported enrichment kind: {kind}")
        self.initialize()
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE assets
                SET exif_json = ?
                WHERE source = ? AND portfolio_source_id = ? AND source_id = ?
                """,
                (_json(values), source, portfolio_source_id, asset_source_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"asset not found: {asset_source_id}")
            self._upsert_enrichment(
                connection,
                source,
                portfolio_source_id,
                asset_source_id,
                kind,
                "completed",
                None,
            )

    def fail_asset_enrichment(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        kind: str,
        error: str,
    ) -> None:
        self.initialize()
        with self._transaction() as connection:
            self._upsert_enrichment(
                connection,
                source,
                portfolio_source_id,
                asset_source_id,
                kind,
                "failed",
                error[:1000],
            )

    def enrichment_status(
        self,
        source: str,
        portfolio_source_id: str,
        kind: str,
    ) -> EnrichmentStatus:
        self.initialize()
        row = (
            self._connect()
            .execute(
                """
            WITH unique_assets AS (
                SELECT DISTINCT source_id
                FROM assets
                WHERE source = ? AND portfolio_source_id = ?
            )
            SELECT
                SUM(CASE WHEN enrichment.status IS NULL THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN enrichment.status = 'completed' THEN 1 ELSE 0 END) AS completed,
                SUM(CASE WHEN enrichment.status = 'failed' THEN 1 ELSE 0 END) AS failed
            FROM unique_assets
            LEFT JOIN asset_enrichments AS enrichment
              ON enrichment.source = ?
             AND enrichment.portfolio_source_id = ?
             AND enrichment.asset_source_id = unique_assets.source_id
             AND enrichment.kind = ?
            """,
                (source, portfolio_source_id, source, portfolio_source_id, kind),
            )
            .fetchone()
        )
        return EnrichmentStatus(
            pending=int(row["pending"] or 0),
            completed=int(row["completed"] or 0),
            failed=int(row["failed"] or 0),
        )

    @staticmethod
    def _upsert_enrichment(
        connection: sqlite3.Connection,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        kind: str,
        status: str,
        last_error: str | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO asset_enrichments (
                source, portfolio_source_id, asset_source_id, kind,
                status, attempts, last_error, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT (source, portfolio_source_id, asset_source_id, kind)
            DO UPDATE SET
                status = excluded.status,
                attempts = asset_enrichments.attempts + 1,
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
            """,
            (
                source,
                portfolio_source_id,
                asset_source_id,
                kind,
                status,
                last_error,
                datetime.now().astimezone().isoformat(),
            ),
        )

    def _read_gallery(
        self,
        connection: sqlite3.Connection,
        source: str,
        portfolio_source_id: str,
        row: sqlite3.Row,
    ) -> Gallery:
        asset_rows = connection.execute(
            """
            SELECT * FROM assets
            WHERE source = ? AND portfolio_source_id = ? AND gallery_source_id = ?
            ORDER BY position
            """,
            (source, portfolio_source_id, row["source_id"]),
        ).fetchall()
        assets = tuple(
            Asset(
                source_id=item["source_id"],
                source_url=item["source_url"],
                gallery_source_id=item["gallery_source_id"],
                preview_url=item["preview_url"],
                captured_at=(
                    datetime.fromisoformat(item["captured_at"]) if item["captured_at"] else None
                ),
                metadata=json.loads(item["metadata_json"]),
                exif=json.loads(item["exif_json"]),
                measurements=tuple(
                    Measurement(
                        measurement["name"],
                        measurement["value"],
                        measurement["unit"],
                        measurement["method"],
                    )
                    for measurement in json.loads(item["measurements_json"])
                ),
            )
            for item in asset_rows
        )
        return Gallery(
            source_id=row["source_id"],
            title=row["title"],
            source_url=row["source_url"],
            parent_source_id=row["parent_source_id"],
            metadata=json.loads(row["metadata_json"]),
            assets=assets,
        )


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)
