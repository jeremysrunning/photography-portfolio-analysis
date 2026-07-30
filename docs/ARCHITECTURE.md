# Architecture

The system is divided into four layers.

```
Portfolio Source
        │
        ▼
    Ingestion
        │
        ▼
 Normalized Dataset
        │
        ▼
     Analysis
        │
        ▼
      Reports
```

## Portfolio Sources

Sources provide access to a photographer's portfolio.

Examples:

- SmugMug
- Lightroom
- Flickr
- Local Folder

Sources should expose a common interface and should never contain analysis logic.

### Gallery Source Contract

Every gallery source exposes the same typed operations:

- discover portfolio identity and metadata without enumerating children
- enumerate normalized galleries for that portfolio
- enumerate normalized assets for each gallery
- enrich one normalized asset with available source metadata
- open a temporary preview through a context manager

Metadata enrichment returns a new normalized asset and preserves unavailable fields as
missing. Source adapters translate provider failures into the shared `SourceError`
hierarchy so callers do not depend on provider-specific exceptions.

The provider-agnostic `load_portfolio` service composes discovery and enumeration into
the immutable normalized object graph. Composition lives outside source adapters so every
provider constructs portfolios, galleries, and assets through the same implementation.
Metadata enrichment remains a separate operation so ingestion behavior and resumable
enrichment do not become coupled.

The source owns every preview lifecycle. A caller supplies a source-agnostic
`PreviewRequest` containing a maximum longest edge, byte allowance, accepted content
types, and memory or temporary-file storage mode. The source returns a context-managed
`PreviewResource` with immutable `PreviewMetadata`.

Memory mode owns one decoded image and deliberately releases encoded bytes before return.
This keeps a single decoded preview shareable by compatible analyzers during one asset
pass without retaining both encoded and decoded representations. Temporary-file mode is
explicit and owns only a neutral OS-generated path for a file-path-only consumer. The
source writes the orientation-applied decoded raster as PNG, so storage mode does not
change pixel dimensions or the visual coordinate system. Metadata distinguishes the
downloaded content type and byte count from the exposed file content type and re-encoded
file byte count. Closing the resource closes its image or deletes its path idempotently.
Network responses never escape the source lifecycle.

The contract caps production previews at a 1,024-pixel longest edge and 8,000,000 encoded
bytes. Sources must select a non-original candidate at or below the request, validate
redirects and content, decode and verify actual dimensions, and reject material
provider/decoded disagreement. Cooperative cancellation uses only an optional callback;
orchestration policy remains outside the source layer.

Preview metadata and resources are operational, source-level types rather than normalized
domain entities. Preview bytes, decoded images, temporary paths, and provider media URLs
never cross the SQLite boundary. Normal metadata ingestion never opens a preview.

## Ingestion

Responsible for:

- discovering galleries
- indexing assets
- extracting metadata
- preparing images for analysis

Ingestion should never perform analysis.

## Normalized Dataset

All analysis operates on a common representation regardless of the original source.

The normalized dataset is the contract between ingestion and analysis.

## Analysis

Analyzers are independent modules.

Each analyzer answers one question.

Examples:

- Equipment Habits
- Color Signature
- Subject Placement
- Time of Day
- Visual Complexity

Analyzers should not depend on the original portfolio source.

## Reports

Reports transform findings into something meaningful for photographers.

The goal is insight, not statistics for their own sake.

## Current Implementation

The reusable engine lives in the `ppa` package and has no user-interface dependency.

- `ppa.models` defines the normalized dataset.
- `ppa.sources` defines the source contract and contains source-specific adapters.
- `ppa.storage` defines persistence contracts and a schema-versioned SQLite implementation.
- `ppa.analysis` contains source-agnostic analyzers, beginning with a metadata baseline.
- `ppa.reports` renders analyzer results without reaching into source-specific data.
- `ppa.cli` is a thin adapter over the library.
- `ppa.core.workflows` composes inspection, persistence, and enrichment operations into
  typed application-level results shared by standalone and end-to-end CLI commands.

Portfolio, gallery, and asset identities are scoped by their source. The SQLite store
persists source URLs and preview references, but never image bytes.

The normalized portfolio owns each unique asset once. Galleries contain ordered
`GalleryPlacement` references to those assets, so ingestion, persistence, and analyzers
share the same object graph. `SourceReference` retains provider identifiers and URLs
without exposing provider behavior, while explicit media types prevent unknown media
from being treated as photographs.

## SQLite Persistence

The ingestion boundary passes complete normalized `Portfolio` models to a source-agnostic
repository. SQLite has no knowledge of SmugMug, and analyzers have no knowledge of the
relational schema.

Schema version 5 stores portfolios, galleries, and unique assets in explicit relational
tables. A gallery-placement table records the many-to-many relationship between galleries
and assets, including stable placement order. Source identifiers and URLs are explicit
columns, as are media type, optional capture timestamp, and independently normalized native
and 35 mm-equivalent focal lengths. Flexible normalized metadata, EXIF, measurements,
observations, and findings use small JSON columns because their keys are intentionally
extensible. No table accepts image bytes.

Saves transactionally upsert records by source-scoped identity. The first normalized
occurrence of a repeated asset supplies its canonical fields, matching analyzer
deduplication. Records missing from later crawls are retained unless a future explicit
synchronization operation is introduced. Empty incoming EXIF or measurements do not erase
previous enrichment. Version-2, version-3, and version-4 databases migrate in place, and
unsupported schema versions fail without being rewritten.

The SmugMug adapter uses the supported public API with an API key and no OAuth. It follows
the linked user root node, recursively traverses paginated child-node collections, follows
album and album-image links, and retains empty public albums. Explicitly private, unlisted,
or password-protected nodes are not traversed. Rate limits and transient transport failures
use bounded retries with capped delays. Discovery and retry progress is emitted through
structured logging. The adapter does not call raw image-size endpoints or download
previews during discovery or enrichment. Explicit preview requests follow the official
`ImageSizeDetails` link, select a bounded non-original resource, and use a separate media
transport whose response is closed before returning an owned resource. This keeps
public-site discovery source-specific while producing the same normalized dataset
expected by future sources.

## Temporary Preview Failures

The source exception hierarchy distinguishes retryable rate-limit, server, timeout, and
transport failures from asset-local missing, unsupported, corrupt, oversized,
original-rejected, and dimension-mismatch failures. Authentication and authorization are
configuration/access failures. Cooperative cancellation has its own sanitized category.
Issue #36 may use these categories for retry policy; Issue #18 performs no retries,
orchestration, or persistence.

The baseline analyzer operates only on normalized models. It measures dataset shape,
duplicate gallery placements, metadata coverage, capture range, orientation, formats, and
available equipment fields. It excludes video records and keeps missing evidence explicit.

## Incremental Enrichment

Source metadata enrichment is separate from initial ingestion. The SmugMug EXIF enricher
derives public image-metadata URIs from normalized source identifiers and uses API
multi-get batches. It never requests image bytes.

SQLite schema version 2 adds per-asset enrichment state. Each unique source asset is
recorded as completed or failed independently of its gallery placements. Successful
metadata and state updates occur in one transaction, so interruption cannot mark an asset
complete without saving its metadata. Rate-limited batches remain pending and reruns skip
completed assets.

This state is operational evidence, not a photographic measurement. Analysis continues to
read EXIF only through normalized `Asset` models.

The application import workflow preserves the same boundaries: it first obtains a complete
normalized `Portfolio`, then passes that model to the repository's transactional save,
and only starts per-asset enrichment after persistence succeeds. A failed save rolls back
as a unit and leaves an existing usable database state intact. Enrichment remains
incremental: each successful asset is committed independently so partial and rate-limited
runs can resume without repeating completed work.

SmugMug enrichment normalizes the confirmed `FocalLength` and `FocalLength35mm` fields at
the source boundary. SQLite receives provider-independent typed millimeter values alongside
the original EXIF mapping. Invalid values remain missing, and neither persistence nor
analysis infers one focal length from the other.

## Equipment Analysis

The equipment analyzer operates entirely below the normalized dataset boundary. It
deduplicates source assets, excludes non-photo media, measures EXIF coverage, and produces
counts for camera models, lenses, focal lengths, apertures, exposure times, ISO values, and
capture-year camera usage.

Equipment categories are descriptive ranges with explicit numeric boundaries. Reports use
available-field counts as distribution denominators and always show coverage against the
complete unique-photograph count.

## Timeline Analysis

The timeline analyzer operates only on normalized capture timestamps and camera metadata.
It measures yearly and year-month capture counts, recorded clock hours, and the same
distributions segmented by camera and gallery. Each result includes its photograph sample
size and capture-timestamp coverage.

Timestamp calendar fields are not converted or assigned a location. Hour distributions
remain separated into UTC, explicit UTC offsets, and timezone-unknown values so the
analyzer never presents UTC as inferred local time. Counts describe available metadata
and do not measure productivity or infer intent.

The default text report summarizes deterministic timeline measurements, the five most
represented recorded camera models, and the ten largest galleries. Complete global,
camera, and gallery distributions remain available through independent CLI detail flags.

## Focal-Length Analysis

The focal-length analyzer reads only the normalized typed native and 35 mm-equivalent
fields. It does not inspect provider EXIF keys or persistence tables. The field with
greater usable portfolio coverage becomes the primary basis; a nonzero tie selects
35 mm equivalent. One distribution never combines bases, and lens summaries independently
use native measurements.

Continuous measurements retain their normalized values for medians, limits, and range
classification. Frequency buckets use deterministic whole-millimeter half-up grouping to
avoid overstating small representation differences. Named photographic ranges apply only
to 35 mm-equivalent measurements. Segment summaries disclose sample size and coverage,
and the default report excludes small segments using documented thresholds.
