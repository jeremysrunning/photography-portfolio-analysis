# Changelog

All notable changes to this project will be documented in this file.

The format is intentionally simple. This project values documenting the evolution of ideas as much as the implementation of code.

---

## [Unreleased]

### Added

- The first production visual analyzer, `color-luminance`, with deterministic bounded
  relative-luminance, saturation, colorfulness, luminance-tail, dominant-palette, and
  palette-entropy measurements plus explicit rendered-preview limitations.
- Resumable `ppa analyze visual` orchestration with deterministic photograph targeting,
  exact analyzer/configuration claims, bounded preview retries, incremental persistence,
  graceful cancellation, bounded one-to-four-worker execution, and aggregate progress.
- A source-agnostic visual analyzer protocol and deterministic production registry,
  intentionally empty until the first analyzer is implemented, with explicit opt-in
  semantics for analyzers whose successful result set may be empty.
- Source-agnostic visual measurement and model-classification persistence with immutable
  analyzer/configuration identities, provenance, optional confidence, normalized geometry,
  transactional result snapshots, and durable per-asset run state.
- Additive SQLite schema version 6 migration with concurrency-safe visual-analysis claims,
  explicit retry and refresh behavior, and retained older analyzer versions.
- Source-agnostic bounded preview requests, immutable preview metadata, memory-first
  decoded-image ownership, explicit temporary-file fallback, cooperative cancellation,
  and idempotent lifecycle cleanup.
- Production SmugMug preview resolution through official image-size metadata with
  non-original selection, HTTPS and redirect checks, encoded-byte and content-type
  enforcement, decoded-dimension validation, and sanitized failure categories.
- Finalized normalized `SourceReference`, `AssetMetadata`, `MediaType`, and
  `GalleryPlacement` models with validated unique-asset ownership and explicit placement
  relationships.
- Deeply immutable normalized metadata mappings with defensive copying of caller-owned
  JSON-compatible structures.
- Recursive SmugMug node discovery with linked-resource traversal, empty-gallery retention,
  public-boundary filtering, bounded retries, and structured progress logging.
- SQLite schema version 4 with explicit media-type persistence and version-2/version-3
  migration compatibility.
- Typed native and 35 mm-equivalent focal-length metadata with evidence-based SmugMug
  normalization, SQLite schema version 5 persistence, migration backfill, and baseline
  coverage reporting.
- Source-agnostic focal-length habits analysis with coverage-selected measurement basis,
  deterministic whole-millimeter frequency grouping, practical equivalent ranges, camera,
  native-lens, gallery, and yearly summaries, and optional CLI detail modes.
- Resumable `ppa import` workflow that inspects a public portfolio, transactionally
  persists normalized metadata, enriches EXIF, and reports precise staged outcomes.
- Initial project vision and documentation.
- Project roadmap.
- Guiding principles.
- Architecture overview.
- Core data model.
- Python 3.12 package foundation and command-line interface.
- Typed normalized portfolio models.
- Generic gallery source contract.
- Public SmugMug API inspection with pagination and metadata-only ingestion.
- CLI inspection summaries with optional SQLite persistence.
- Saved-dataset `show` command.
- Source-agnostic baseline metadata analysis and neutral text report.
- Explicit distinction between media references, unique photographs, gallery placements,
  and excluded non-photo media.
- Schema-versioned, per-asset enrichment state.
- Resumable SmugMug EXIF enrichment using API multi-get batches.
- Rate-limit-aware progress preservation and explicit failed-item retries.
- Source-agnostic equipment and exposure analysis.
- Equipment report covering evidence, camera and lens use, focal length, aperture, exposure,
  ISO, and capture-year camera patterns.
- Source-agnostic timeline habits analysis with yearly, monthly, recorded-hour, camera,
  and gallery distributions plus explicit timezone limitations.
- Schema-versioned SQLite normalized dataset storage.
- Relational SQLite gallery placements with unique-asset persistence, transactional
  idempotent updates, conservative record retention, and version-2 migration support.
- Structured JSON logging.
- Pytest test suite and Ruff configuration.

### Changed

- Separated SmugMug authentication and authorization failures and removed
  provider-supplied text from normalized API errors.
- Aligned shared ingestion, SQLite loading, and analyzers on portfolio-owned unique assets
  and gallery-owned ordered placements; unknown media is no longer treated as photography.
- Counted additional gallery placements relative only to distinct placed assets, so
  unplaced portfolio assets do not produce negative counts.
- Expanded the `GallerySource` contract to cover discovery, gallery and asset enumeration,
  metadata enrichment, normalized failures, and source-owned temporary preview access.
- Moved normalized portfolio composition from source adapters into a shared,
  provider-agnostic loader.
- Made the default timeline report concise, with deterministic summary measurements,
  five recorded camera-use summaries, ten top galleries, and optional exhaustive detail
  sections.

### Fixed

- Scoped visual-analysis progress and remaining-work summaries to the work identities
  selected by the command's run-state mode, while separately disclosing asset-filter
  matches and intentionally excluded states.
- Kept temporary-file and memory-backed previews in the same EXIF-orientation-applied
  pixel coordinate system, with explicit downloaded-versus-file encoding metadata.

---

## [0.1.0] - TBD

### Added

- Website gallery crawler.
- Gallery source abstraction.
- Normalized portfolio data model.
- Initial portfolio report.

### Changed

-

### Fixed

-

### Research

- Added an isolated visual-preview requirements benchmark with deterministic metadata
  sampling, bounded experimental SmugMug size access, in-memory deterministic statistics,
  spectral-residual saliency, aggregate-only synthetic results, and explicit guidance for
  temporary preview lifecycle and later visual-analysis issues.

#### New Questions

- How accurately can subject placement be measured?
- Can a photographer's style be inferred from portfolio statistics alone?

#### Discoveries

- TBD

#### Decisions

- Do not permanently store original images.
- Separate portfolio sources from analysis modules.
