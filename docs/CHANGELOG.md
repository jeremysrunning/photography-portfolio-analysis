# Changelog

All notable changes to this project will be documented in this file.

The format is intentionally simple. This project values documenting the evolution of ideas as much as the implementation of code.

---

## [Unreleased]

### Added

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
- Schema-versioned SQLite normalized dataset storage.
- Structured JSON logging.
- Pytest test suite and Ruff configuration.

### Changed

- Expanded the `GallerySource` contract to cover discovery, gallery and asset enumeration,
  metadata enrichment, normalized failures, and source-owned temporary preview access.
- Moved normalized portfolio composition from source adapters into a shared,
  provider-agnostic loader.

### Fixed

- Nothing yet.

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

#### New Questions

- How accurately can subject placement be measured?
- Can a photographer's style be inferred from portfolio statistics alone?

#### Discoveries

- TBD

#### Decisions

- Do not permanently store original images.
- Separate portfolio sources from analysis modules.
