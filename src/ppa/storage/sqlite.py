"""SQLite persistence for normalized portfolio datasets."""

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ppa.models import (
    Asset,
    AssetMetadata,
    Finding,
    Gallery,
    GalleryPlacement,
    JsonValue,
    Measurement,
    MediaType,
    Observation,
    Portfolio,
    SourceReference,
    normalize_focal_length,
)
from ppa.storage.base import EnrichmentStatus, EnrichmentTarget
from ppa.visual import (
    AnalyzerIdentity,
    VisualAnalysisSnapshot,
    VisualResult,
    VisualResultKind,
    VisualRunState,
    VisualRunStatus,
)

SCHEMA_VERSION = 6

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS schema_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS portfolios (
        source TEXT NOT NULL,
        source_id TEXT NOT NULL,
        title TEXT NOT NULL,
        source_url TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        observations_json TEXT NOT NULL,
        findings_json TEXT NOT NULL,
        PRIMARY KEY (source, source_id)
    )
    """,
    """
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
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assets (
        source TEXT NOT NULL,
        portfolio_source_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_url TEXT NOT NULL,
        preview_url TEXT,
        captured_at TEXT,
        media_type TEXT NOT NULL CHECK (
            media_type IN ('photograph', 'non_photo', 'unknown')
        ),
        metadata_json TEXT NOT NULL,
        exif_json TEXT NOT NULL,
        focal_length_mm REAL,
        focal_length_35mm REAL,
        measurements_json TEXT NOT NULL,
        PRIMARY KEY (source, portfolio_source_id, source_id),
        FOREIGN KEY (source, portfolio_source_id)
            REFERENCES portfolios(source, source_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS gallery_placements (
        source TEXT NOT NULL,
        portfolio_source_id TEXT NOT NULL,
        gallery_source_id TEXT NOT NULL,
        asset_source_id TEXT NOT NULL,
        position INTEGER NOT NULL,
        PRIMARY KEY (
            source, portfolio_source_id, gallery_source_id, asset_source_id
        ),
        FOREIGN KEY (source, portfolio_source_id, gallery_source_id)
            REFERENCES galleries(source, portfolio_source_id, source_id) ON DELETE CASCADE,
        FOREIGN KEY (source, portfolio_source_id, asset_source_id)
            REFERENCES assets(source, portfolio_source_id, source_id) ON DELETE CASCADE
    )
    """,
    """
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
        FOREIGN KEY (source, portfolio_source_id, asset_source_id)
            REFERENCES assets(source, portfolio_source_id, source_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visual_analysis_runs (
        source TEXT NOT NULL,
        portfolio_source_id TEXT NOT NULL,
        asset_source_id TEXT NOT NULL,
        analyzer_name TEXT NOT NULL,
        analyzer_version TEXT NOT NULL,
        configuration_version TEXT NOT NULL,
        status TEXT NOT NULL CHECK (
            status IN ('pending', 'running', 'completed', 'failed', 'skipped')
        ),
        attempts INTEGER NOT NULL CHECK (attempts >= 0),
        started_at TEXT,
        updated_at TEXT NOT NULL,
        last_successful_completed_at TEXT,
        error_category TEXT,
        error_message TEXT,
        interruption_category TEXT,
        interrupted_at TEXT,
        skip_reason TEXT,
        PRIMARY KEY (
            source, portfolio_source_id, asset_source_id,
            analyzer_name, analyzer_version, configuration_version
        ),
        FOREIGN KEY (source, portfolio_source_id, asset_source_id)
            REFERENCES assets(source, portfolio_source_id, source_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visual_analysis_results (
        source TEXT NOT NULL,
        portfolio_source_id TEXT NOT NULL,
        asset_source_id TEXT NOT NULL,
        analyzer_name TEXT NOT NULL,
        analyzer_version TEXT NOT NULL,
        configuration_version TEXT NOT NULL,
        result_name TEXT NOT NULL,
        result_kind TEXT NOT NULL CHECK (
            result_kind IN ('measurement', 'classification')
        ),
        value_json TEXT NOT NULL,
        unit TEXT,
        confidence REAL CHECK (
            confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)
        ),
        method_name TEXT NOT NULL,
        method_version TEXT NOT NULL,
        model_name TEXT,
        model_version TEXT,
        completed_at TEXT NOT NULL,
        PRIMARY KEY (
            source, portfolio_source_id, asset_source_id,
            analyzer_name, analyzer_version, configuration_version, result_name
        ),
        FOREIGN KEY (
            source, portfolio_source_id, asset_source_id,
            analyzer_name, analyzer_version, configuration_version
        ) REFERENCES visual_analysis_runs(
            source, portfolio_source_id, asset_source_id,
            analyzer_name, analyzer_version, configuration_version
        ) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_galleries_portfolio_position
        ON galleries(source, portfolio_source_id, position)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_placements_gallery_position
        ON gallery_placements(
            source, portfolio_source_id, gallery_source_id, position
        )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_visual_runs_targeting
        ON visual_analysis_runs(
            source, portfolio_source_id, analyzer_name, analyzer_version,
            configuration_version, status
        )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_visual_results_identity
        ON visual_analysis_results(
            source, portfolio_source_id, analyzer_name, analyzer_version,
            configuration_version, result_name
        )
    """,
)


class UnsupportedSchemaVersionError(RuntimeError):
    """Raised when a database schema cannot be read or migrated safely."""


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

    @contextmanager
    def _immediate_transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialize a read/claim/write decision across repository connections."""
        connection = self._connect()
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()

    def close(self) -> None:
        """Close the SQLite connection if one is open."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
            self._initialized = False

    def initialize(self) -> None:
        """Create or migrate the schema and reject unsupported versions."""
        if self._initialized:
            return
        connection = self._connect()
        current_version = self._schema_version(connection)
        if current_version is None:
            with self._transaction() as transaction:
                self._create_schema(transaction)
                transaction.execute(
                    "INSERT INTO schema_metadata (key, value) VALUES ('version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            current_version = SCHEMA_VERSION
        if current_version == 2:
            self._migrate_v2_to_v3(connection)
            current_version = SCHEMA_VERSION
        if current_version == 3:
            self._migrate_v3_to_v4(connection)
            current_version = 4
        if current_version == 4:
            self._migrate_v4_to_v5(connection)
            current_version = 5
        if current_version == 5:
            self._migrate_v5_to_v6(connection)
            current_version = 6
        if current_version != SCHEMA_VERSION:
            raise UnsupportedSchemaVersionError(
                f"Unsupported SQLite schema version {current_version}; "
                f"this release supports version {SCHEMA_VERSION}."
            )
        self._initialized = True

    def save(self, portfolio: Portfolio) -> None:
        """Upsert a normalized portfolio without deleting previously seen records."""
        self.initialize()
        with self._transaction() as connection:
            key = (portfolio.source_name, portfolio.source_id)
            connection.execute(
                """
                INSERT INTO portfolios (
                    source, source_id, title, source_url, metadata_json,
                    observations_json, findings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (source, source_id) DO UPDATE SET
                    title = excluded.title,
                    source_url = excluded.source_url,
                    metadata_json = excluded.metadata_json,
                    observations_json = excluded.observations_json,
                    findings_json = excluded.findings_json
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
                self._upsert_gallery(connection, key, gallery, gallery_position)
            for asset in portfolio.assets:
                self._upsert_asset(connection, key, asset)
            for gallery in portfolio.galleries:
                for position, placement in enumerate(gallery.placements):
                    self._upsert_placement(
                        connection,
                        key,
                        gallery.source_id,
                        placement.asset_source_id,
                        position,
                    )

    def get(self, source: str, source_id: str) -> Portfolio | None:
        """Load a complete normalized portfolio by source-scoped identity."""
        self.initialize()
        connection = self._connect()
        row = connection.execute(
            "SELECT * FROM portfolios WHERE source = ? AND source_id = ?",
            (source, source_id),
        ).fetchone()
        if row is None:
            return None
        asset_rows = connection.execute(
            """
            SELECT * FROM assets
            WHERE source = ? AND portfolio_source_id = ?
            ORDER BY source_id
            """,
            (source, source_id),
        ).fetchall()
        gallery_rows = connection.execute(
            """
            SELECT * FROM galleries
            WHERE source = ? AND portfolio_source_id = ?
            ORDER BY position, source_id
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
            source_name=row["source"],
            source=SourceReference(row["source_id"], row["source_url"]),
            title=row["title"],
            metadata=json.loads(row["metadata_json"]),
            assets=tuple(self._read_asset(item) for item in asset_rows),
            galleries=galleries,
            observations=observations,
            findings=findings,
        )

    def exists(self, source: str, source_id: str) -> bool:
        """Return whether a source-scoped portfolio is stored."""
        self.initialize()
        row = (
            self._connect()
            .execute(
                """
            SELECT 1 FROM portfolios
            WHERE source = ? AND source_id = ?
            """,
                (source, source_id),
            )
            .fetchone()
        )
        return row is not None

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
            SELECT assets.source_id, assets.media_type, assets.metadata_json
            FROM assets
            LEFT JOIN asset_enrichments AS enrichment
              ON enrichment.source = assets.source
             AND enrichment.portfolio_source_id = assets.portfolio_source_id
             AND enrichment.asset_source_id = assets.source_id
             AND enrichment.kind = ?
            WHERE assets.source = ?
              AND assets.portfolio_source_id = ?
              AND {status_clause}
            ORDER BY assets.source_id
            {limit_clause}
            """,
            parameters,
        )
        return tuple(
            EnrichmentTarget(
                row["source_id"],
                MediaType(row["media_type"]),
                json.loads(row["metadata_json"]),
            )
            for row in rows
        )

    def save_asset_enrichment(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        kind: str,
        values: dict[str, JsonValue],
        *,
        focal_length_mm: float | None = None,
        focal_length_35mm: float | None = None,
    ) -> None:
        if kind != "exif":
            raise ValueError(f"unsupported enrichment kind: {kind}")
        self.initialize()
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE assets
                SET exif_json = ?,
                    focal_length_mm = ?,
                    focal_length_35mm = ?
                WHERE source = ? AND portfolio_source_id = ? AND source_id = ?
                """,
                (
                    _json(values),
                    focal_length_mm,
                    focal_length_35mm,
                    source,
                    portfolio_source_id,
                    asset_source_id,
                ),
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
                SELECT
                    SUM(CASE WHEN enrichment.status IS NULL THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN enrichment.status = 'completed' THEN 1 ELSE 0 END) AS completed,
                    SUM(CASE WHEN enrichment.status = 'failed' THEN 1 ELSE 0 END) AS failed
                FROM assets
                LEFT JOIN asset_enrichments AS enrichment
                  ON enrichment.source = assets.source
                 AND enrichment.portfolio_source_id = assets.portfolio_source_id
                 AND enrichment.asset_source_id = assets.source_id
                 AND enrichment.kind = ?
                WHERE assets.source = ? AND assets.portfolio_source_id = ?
                """,
                (kind, source, portfolio_source_id),
            )
            .fetchone()
        )
        return EnrichmentStatus(
            pending=int(row["pending"] or 0),
            completed=int(row["completed"] or 0),
            failed=int(row["failed"] or 0),
        )

    def visual_analysis_snapshot(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        identity: AnalyzerIdentity,
    ) -> VisualAnalysisSnapshot:
        """Return current state and results from the last successful completion."""
        self.initialize()
        connection = self._connect()
        self._require_asset(connection, source, portfolio_source_id, asset_source_id)
        key = self._visual_key(source, portfolio_source_id, asset_source_id, identity)
        row = connection.execute(
            """
            SELECT * FROM visual_analysis_runs
            WHERE source = ? AND portfolio_source_id = ? AND asset_source_id = ?
              AND analyzer_name = ? AND analyzer_version = ?
              AND configuration_version = ?
            """,
            key,
        ).fetchone()
        if row is None:
            return VisualAnalysisSnapshot(
                identity,
                VisualRunState(VisualRunStatus.PENDING, 0, None),
            )
        result_rows = connection.execute(
            """
            SELECT * FROM visual_analysis_results
            WHERE source = ? AND portfolio_source_id = ? AND asset_source_id = ?
              AND analyzer_name = ? AND analyzer_version = ?
              AND configuration_version = ?
            ORDER BY result_name
            """,
            key,
        ).fetchall()
        return VisualAnalysisSnapshot(
            identity,
            self._read_visual_state(row),
            tuple(self._read_visual_result(item) for item in result_rows),
        )

    def claim_visual_analysis(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        identity: AnalyzerIdentity,
        *,
        retry_failed: bool = False,
        refresh: bool = False,
        at: datetime | None = None,
    ) -> bool:
        """Atomically claim an eligible exact identity for one attempt."""
        self.initialize()
        timestamp = _timestamp(at)
        key = self._visual_key(source, portfolio_source_id, asset_source_id, identity)
        with self._immediate_transaction() as connection:
            self._require_asset(connection, source, portfolio_source_id, asset_source_id)
            row = connection.execute(
                """
                SELECT status, interruption_category
                FROM visual_analysis_runs
                WHERE source = ? AND portfolio_source_id = ? AND asset_source_id = ?
                  AND analyzer_name = ? AND analyzer_version = ?
                  AND configuration_version = ?
                """,
                key,
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO visual_analysis_runs (
                        source, portfolio_source_id, asset_source_id,
                        analyzer_name, analyzer_version, configuration_version,
                        status, attempts, started_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'running', 1, ?, ?)
                    """,
                    (*key, timestamp, timestamp),
                )
                return True
            status = VisualRunStatus(row["status"])
            eligible = (
                (status is VisualRunStatus.PENDING and row["interruption_category"] is None)
                or (status in {VisualRunStatus.PENDING, VisualRunStatus.FAILED} and retry_failed)
                or (status in {VisualRunStatus.COMPLETED, VisualRunStatus.SKIPPED} and refresh)
            )
            if not eligible:
                return False
            connection.execute(
                """
                UPDATE visual_analysis_runs
                SET status = 'running',
                    attempts = attempts + 1,
                    started_at = ?,
                    updated_at = ?,
                    error_category = NULL,
                    error_message = NULL,
                    interruption_category = NULL,
                    interrupted_at = NULL,
                    skip_reason = NULL
                WHERE source = ? AND portfolio_source_id = ? AND asset_source_id = ?
                  AND analyzer_name = ? AND analyzer_version = ?
                  AND configuration_version = ?
                """,
                (timestamp, timestamp, *key),
            )
            return True

    def complete_visual_analysis(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        identity: AnalyzerIdentity,
        results: tuple[VisualResult, ...],
        *,
        at: datetime | None = None,
    ) -> None:
        """Atomically replace exact-identity results and complete the attempt."""
        self.initialize()
        names = [result.name for result in results]
        if len(names) != len(set(names)):
            raise ValueError("visual result names must be unique within one completion")
        timestamp = _timestamp(at)
        completed_at = datetime.fromisoformat(timestamp)
        if any(
            result.completed_at is not None and result.completed_at != completed_at
            for result in results
        ):
            raise ValueError(
                "visual result completed_at must match the atomic completion timestamp"
            )
        key = self._visual_key(source, portfolio_source_id, asset_source_id, identity)
        with self._immediate_transaction() as connection:
            self._require_running(connection, key)
            connection.execute(
                """
                DELETE FROM visual_analysis_results
                WHERE source = ? AND portfolio_source_id = ? AND asset_source_id = ?
                  AND analyzer_name = ? AND analyzer_version = ?
                  AND configuration_version = ?
                """,
                key,
            )
            for result in results:
                connection.execute(
                    """
                    INSERT INTO visual_analysis_results (
                        source, portfolio_source_id, asset_source_id,
                        analyzer_name, analyzer_version, configuration_version,
                        result_name, result_kind, value_json, unit, confidence,
                        method_name, method_version, model_name, model_version,
                        completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        *key,
                        result.name,
                        result.kind.value,
                        _json(result.value),
                        result.unit,
                        result.confidence,
                        result.method_name,
                        result.method_version,
                        result.model_name,
                        result.model_version,
                        timestamp,
                    ),
                )
            connection.execute(
                """
                UPDATE visual_analysis_runs
                SET status = 'completed', updated_at = ?,
                    last_successful_completed_at = ?,
                    error_category = NULL, error_message = NULL,
                    interruption_category = NULL, interrupted_at = NULL,
                    skip_reason = NULL
                WHERE source = ? AND portfolio_source_id = ? AND asset_source_id = ?
                  AND analyzer_name = ? AND analyzer_version = ?
                  AND configuration_version = ?
                """,
                (timestamp, timestamp, *key),
            )

    def fail_visual_analysis(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        identity: AnalyzerIdentity,
        category: str,
        message: str,
        *,
        at: datetime | None = None,
    ) -> None:
        """Fail the current attempt while retaining any successful snapshot."""
        self._finish_visual_attempt(
            source,
            portfolio_source_id,
            asset_source_id,
            identity,
            VisualRunStatus.FAILED,
            at=at,
            category=category,
            message=message,
        )

    def cancel_visual_analysis(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        identity: AnalyzerIdentity,
        category: str = "cancelled",
        *,
        at: datetime | None = None,
    ) -> None:
        """Return a running attempt to pending while retaining interruption evidence."""
        self._finish_visual_attempt(
            source,
            portfolio_source_id,
            asset_source_id,
            identity,
            VisualRunStatus.PENDING,
            at=at,
            category=category,
        )

    def skip_visual_analysis(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        identity: AnalyzerIdentity,
        reason: str,
        *,
        at: datetime | None = None,
    ) -> None:
        """Mark the running attempt skipped without creating results."""
        self._finish_visual_attempt(
            source,
            portfolio_source_id,
            asset_source_id,
            identity,
            VisualRunStatus.SKIPPED,
            at=at,
            message=reason,
        )

    def _finish_visual_attempt(
        self,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        identity: AnalyzerIdentity,
        status: VisualRunStatus,
        *,
        at: datetime | None,
        category: str | None = None,
        message: str | None = None,
    ) -> None:
        timestamp = _timestamp(at)
        key = self._visual_key(source, portfolio_source_id, asset_source_id, identity)
        with self._immediate_transaction() as connection:
            self._require_running(connection, key)
            connection.execute(
                """
                UPDATE visual_analysis_runs
                SET status = ?, updated_at = ?,
                    error_category = ?, error_message = ?,
                    interruption_category = ?, interrupted_at = ?,
                    skip_reason = ?
                WHERE source = ? AND portfolio_source_id = ? AND asset_source_id = ?
                  AND analyzer_name = ? AND analyzer_version = ?
                  AND configuration_version = ?
                """,
                (
                    status.value,
                    timestamp,
                    category if status is VisualRunStatus.FAILED else None,
                    message[:1000] if status is VisualRunStatus.FAILED and message else None,
                    category if status is VisualRunStatus.PENDING else None,
                    timestamp if status is VisualRunStatus.PENDING else None,
                    message[:1000] if status is VisualRunStatus.SKIPPED and message else None,
                    *key,
                ),
            )

    @staticmethod
    def _visual_key(
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
        identity: AnalyzerIdentity,
    ) -> tuple[str, str, str, str, str, str]:
        return (
            source,
            portfolio_source_id,
            asset_source_id,
            identity.name,
            identity.version,
            identity.configuration_version,
        )

    @staticmethod
    def _require_asset(
        connection: sqlite3.Connection,
        source: str,
        portfolio_source_id: str,
        asset_source_id: str,
    ) -> None:
        row = connection.execute(
            """
            SELECT 1 FROM assets
            WHERE source = ? AND portfolio_source_id = ? AND source_id = ?
            """,
            (source, portfolio_source_id, asset_source_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"asset not found: {asset_source_id}")

    @staticmethod
    def _require_running(
        connection: sqlite3.Connection,
        key: tuple[str, str, str, str, str, str],
    ) -> None:
        row = connection.execute(
            """
            SELECT status FROM visual_analysis_runs
            WHERE source = ? AND portfolio_source_id = ? AND asset_source_id = ?
              AND analyzer_name = ? AND analyzer_version = ?
              AND configuration_version = ?
            """,
            key,
        ).fetchone()
        if row is None or row["status"] != VisualRunStatus.RUNNING.value:
            raise ValueError("visual analysis identity does not have a running attempt")

    @staticmethod
    def _read_visual_state(row: sqlite3.Row) -> VisualRunState:
        return VisualRunState(
            status=VisualRunStatus(row["status"]),
            attempts=row["attempts"],
            updated_at=_read_timestamp(row["updated_at"]),
            started_at=_read_timestamp(row["started_at"]),
            last_successful_completed_at=_read_timestamp(row["last_successful_completed_at"]),
            error_category=row["error_category"],
            error_message=row["error_message"],
            interruption_category=row["interruption_category"],
            interrupted_at=_read_timestamp(row["interrupted_at"]),
            skip_reason=row["skip_reason"],
        )

    @staticmethod
    def _read_visual_result(row: sqlite3.Row) -> VisualResult:
        return VisualResult(
            name=row["result_name"],
            kind=VisualResultKind(row["result_kind"]),
            value=json.loads(row["value_json"]),
            unit=row["unit"],
            confidence=row["confidence"],
            method_name=row["method_name"],
            method_version=row["method_version"],
            model_name=row["model_name"],
            model_version=row["model_version"],
            completed_at=_read_timestamp(row["completed_at"]),
        )

    @staticmethod
    def _upsert_gallery(
        connection: sqlite3.Connection,
        key: tuple[str, str],
        gallery: Gallery,
        position: int,
    ) -> None:
        connection.execute(
            """
            INSERT INTO galleries (
                source, portfolio_source_id, source_id, title, source_url,
                parent_source_id, metadata_json, position
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source, portfolio_source_id, source_id) DO UPDATE SET
                title = excluded.title,
                source_url = excluded.source_url,
                parent_source_id = excluded.parent_source_id,
                metadata_json = excluded.metadata_json,
                position = excluded.position
            """,
            (
                *key,
                gallery.source_id,
                gallery.title,
                gallery.source_url,
                gallery.parent_source_id,
                _json(gallery.metadata),
                position,
            ),
        )

    @staticmethod
    def _upsert_asset(
        connection: sqlite3.Connection,
        key: tuple[str, str],
        asset: Asset,
    ) -> None:
        connection.execute(
            """
            INSERT INTO assets (
                source, portfolio_source_id, source_id, source_url, preview_url,
                captured_at, media_type, metadata_json, exif_json,
                focal_length_mm, focal_length_35mm, measurements_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source, portfolio_source_id, source_id) DO UPDATE SET
                source_url = excluded.source_url,
                preview_url = excluded.preview_url,
                captured_at = excluded.captured_at,
                media_type = excluded.media_type,
                metadata_json = excluded.metadata_json,
                exif_json = CASE
                    WHEN excluded.exif_json = '{}' THEN assets.exif_json
                    ELSE excluded.exif_json
                END,
                focal_length_mm = CASE
                    WHEN excluded.exif_json = '{}' THEN assets.focal_length_mm
                    ELSE excluded.focal_length_mm
                END,
                focal_length_35mm = CASE
                    WHEN excluded.exif_json = '{}' THEN assets.focal_length_35mm
                    ELSE excluded.focal_length_35mm
                END,
                measurements_json = CASE
                    WHEN excluded.measurements_json = '[]' THEN assets.measurements_json
                    ELSE excluded.measurements_json
                END
            """,
            (
                *key,
                asset.source_id,
                asset.source_url,
                asset.preview_url,
                asset.captured_at.isoformat() if asset.captured_at else None,
                asset.media_type.value,
                _json(asset.values),
                _json(asset.exif),
                asset.metadata.focal_length_mm,
                asset.metadata.focal_length_35mm,
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
            ),
        )

    @staticmethod
    def _upsert_placement(
        connection: sqlite3.Connection,
        key: tuple[str, str],
        gallery_source_id: str,
        asset_source_id: str,
        position: int,
    ) -> None:
        connection.execute(
            """
            INSERT INTO gallery_placements (
                source, portfolio_source_id, gallery_source_id,
                asset_source_id, position
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (
                source, portfolio_source_id, gallery_source_id, asset_source_id
            ) DO UPDATE SET position = excluded.position
            """,
            (*key, gallery_source_id, asset_source_id, position),
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
        placement_rows = connection.execute(
            """
            SELECT asset_source_id
            FROM gallery_placements AS placements
            WHERE placements.source = ?
              AND placements.portfolio_source_id = ?
              AND placements.gallery_source_id = ?
            ORDER BY placements.position, placements.asset_source_id
            """,
            (source, portfolio_source_id, row["source_id"]),
        ).fetchall()
        return Gallery(
            source=SourceReference(row["source_id"], row["source_url"]),
            title=row["title"],
            parent_source_id=row["parent_source_id"],
            metadata=json.loads(row["metadata_json"]),
            placements=tuple(GalleryPlacement(item["asset_source_id"]) for item in placement_rows),
        )

    @staticmethod
    def _read_asset(row: sqlite3.Row) -> Asset:
        return Asset(
            source=SourceReference(row["source_id"], row["source_url"]),
            preview_url=row["preview_url"],
            metadata=AssetMetadata(
                media_type=MediaType(row["media_type"]),
                captured_at=(
                    datetime.fromisoformat(row["captured_at"]) if row["captured_at"] else None
                ),
                values=json.loads(row["metadata_json"]),
                exif=json.loads(row["exif_json"]),
                focal_length_mm=row["focal_length_mm"],
                focal_length_35mm=row["focal_length_35mm"],
            ),
            measurements=tuple(
                Measurement(
                    measurement["name"],
                    measurement["value"],
                    measurement["unit"],
                    measurement["method"],
                )
                for measurement in json.loads(row["measurements_json"])
            ),
        )

    @staticmethod
    def _schema_version(connection: sqlite3.Connection) -> int | None:
        table = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'schema_metadata'
            """
        ).fetchone()
        if table is None:
            return None
        row = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'version'"
        ).fetchone()
        if row is None:
            raise UnsupportedSchemaVersionError(
                "SQLite schema metadata does not contain a version."
            )
        try:
            return int(row["value"])
        except (TypeError, ValueError) as error:
            raise UnsupportedSchemaVersionError(
                f"SQLite schema version is invalid: {row['value']!r}."
            ) from error

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        for statement in _SCHEMA_STATEMENTS:
            connection.execute(statement)

    def _migrate_v2_to_v3(self, connection: sqlite3.Connection) -> None:
        with connection:
            connection.execute("ALTER TABLE assets RENAME TO assets_v2")
            connection.execute("ALTER TABLE asset_enrichments RENAME TO asset_enrichments_v2")
            self._create_schema(connection)
            connection.execute(
                """
                INSERT OR IGNORE INTO assets (
                    source, portfolio_source_id, source_id, source_url,
                    preview_url, captured_at, media_type, metadata_json, exif_json,
                    measurements_json
                )
                SELECT
                    legacy.source,
                    legacy.portfolio_source_id,
                    legacy.source_id,
                    legacy.source_url,
                    legacy.preview_url,
                    legacy.captured_at,
                    'unknown',
                    legacy.metadata_json,
                    legacy.exif_json,
                    legacy.measurements_json
                FROM assets_v2 AS legacy
                JOIN galleries
                  ON galleries.source = legacy.source
                 AND galleries.portfolio_source_id = legacy.portfolio_source_id
                 AND galleries.source_id = legacy.gallery_source_id
                ORDER BY galleries.position, legacy.position, legacy.source_id
                """
            )
            connection.execute(
                """
                INSERT INTO gallery_placements (
                    source, portfolio_source_id, gallery_source_id,
                    asset_source_id, position
                )
                SELECT
                    source, portfolio_source_id, gallery_source_id,
                    source_id, position
                FROM assets_v2
                """
            )
            connection.execute(
                """
                INSERT INTO asset_enrichments (
                    source, portfolio_source_id, asset_source_id, kind,
                    status, attempts, last_error, updated_at
                )
                SELECT
                    legacy.source,
                    legacy.portfolio_source_id,
                    legacy.asset_source_id,
                    legacy.kind,
                    legacy.status,
                    legacy.attempts,
                    legacy.last_error,
                    legacy.updated_at
                FROM asset_enrichments_v2 AS legacy
                JOIN assets
                  ON assets.source = legacy.source
                 AND assets.portfolio_source_id = legacy.portfolio_source_id
                 AND assets.source_id = legacy.asset_source_id
                """
            )
            connection.execute("DROP TABLE asset_enrichments_v2")
            connection.execute("DROP TABLE assets_v2")
            self._backfill_media_types(connection)
            connection.execute(
                "UPDATE schema_metadata SET value = ? WHERE key = 'version'",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
        with connection:
            connection.execute(
                "ALTER TABLE assets ADD COLUMN media_type TEXT NOT NULL DEFAULT 'unknown'"
            )
            SQLitePortfolioRepository._backfill_media_types(connection)
            connection.execute(
                "UPDATE schema_metadata SET value = ? WHERE key = 'version'",
                ("4",),
            )

    @staticmethod
    def _migrate_v4_to_v5(connection: sqlite3.Connection) -> None:
        with connection:
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(assets)").fetchall()
            }
            if "focal_length_mm" not in columns:
                connection.execute("ALTER TABLE assets ADD COLUMN focal_length_mm REAL")
            if "focal_length_35mm" not in columns:
                connection.execute("ALTER TABLE assets ADD COLUMN focal_length_35mm REAL")
            rows = connection.execute(
                """
                SELECT source, portfolio_source_id, source_id, exif_json
                FROM assets
                """
            ).fetchall()
            for row in rows:
                exif = json.loads(row["exif_json"])
                connection.execute(
                    """
                    UPDATE assets
                    SET focal_length_mm = ?, focal_length_35mm = ?
                    WHERE source = ? AND portfolio_source_id = ? AND source_id = ?
                    """,
                    (
                        normalize_focal_length(exif.get("FocalLength")),
                        normalize_focal_length(exif.get("FocalLength35mm")),
                        row["source"],
                        row["portfolio_source_id"],
                        row["source_id"],
                    ),
                )
            connection.execute(
                "UPDATE schema_metadata SET value = ? WHERE key = 'version'",
                ("5",),
            )

    @staticmethod
    def _migrate_v5_to_v6(connection: sqlite3.Connection) -> None:
        with connection:
            SQLitePortfolioRepository._create_schema(connection)
            connection.execute(
                "UPDATE schema_metadata SET value = ? WHERE key = 'version'",
                ("6",),
            )

    @staticmethod
    def _backfill_media_types(connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT source, portfolio_source_id, source_id, metadata_json FROM assets"
        ).fetchall()
        for row in rows:
            media_type = _legacy_media_type(json.loads(row["metadata_json"]))
            connection.execute(
                """
                UPDATE assets SET media_type = ?
                WHERE source = ? AND portfolio_source_id = ? AND source_id = ?
                """,
                (
                    media_type.value,
                    row["source"],
                    row["portfolio_source_id"],
                    row["source_id"],
                ),
            )


def _json(value: Any) -> str:
    return json.dumps(_mutable_json(value), separators=(",", ":"), sort_keys=True)


def _timestamp(value: datetime | None) -> str:
    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("visual-analysis timestamps must be timezone-aware")
    return timestamp.isoformat()


def _read_timestamp(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _mutable_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _mutable_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_mutable_json(item) for item in value]
    return value


def _legacy_media_type(metadata: dict[str, JsonValue]) -> MediaType:
    if metadata.get("IsVideo") is True:
        return MediaType.NON_PHOTO
    if metadata.get("IsVideo") is False:
        return MediaType.PHOTOGRAPH
    image_format = metadata.get("Format")
    if isinstance(image_format, str):
        normalized = image_format.upper()
        if normalized in {
            "3GP",
            "AVI",
            "M4V",
            "MOV",
            "MP4",
            "MPEG",
            "MPG",
            "WEBM",
            "WMV",
        }:
            return MediaType.NON_PHOTO
        if normalized in {
            "AVIF",
            "BMP",
            "GIF",
            "HEIC",
            "HEIF",
            "JPEG",
            "JPG",
            "PNG",
            "TIF",
            "TIFF",
            "WEBP",
        }:
            return MediaType.PHOTOGRAPH
    return MediaType.UNKNOWN
