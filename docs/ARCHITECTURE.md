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

Portfolio, gallery, and asset identities are scoped by their source. The SQLite store
persists source URLs and preview references, but never image bytes.

The SmugMug adapter uses the supported public API with an API key and no OAuth. It follows
the site's user-to-albums-to-album-images links and API pagination. It does not call raw
image-size endpoints or download previews. This keeps public-site discovery source-specific
while producing the same normalized dataset expected by future sources.

The baseline analyzer operates only on normalized models. It measures dataset shape,
duplicate gallery placements, metadata coverage, capture range, orientation, formats, and
available equipment fields. It excludes video records and keeps missing evidence explicit.
