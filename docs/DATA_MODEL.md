# Data Model

The normalized data model is the authoritative boundary between portfolio sources,
persistence, and analyzers. It is implemented as immutable, typed dataclasses in
`ppa.models`; it contains no SmugMug- or SQLite-specific behavior.

## Ownership

A `Portfolio` owns:

- one source namespace name and one `SourceReference`
- zero or more unique `Asset` records
- zero or more `Gallery` records
- existing portfolio-level observations and findings

A `Gallery` does not own copies of assets. It owns an ordered tuple of
`GalleryPlacement` records. Each placement references one asset owned by the same
portfolio. The model rejects placements whose asset identity is absent from the
portfolio.

This shape distinguishes media identity from gallery membership:

```text
Portfolio
├── Assets
│   └── Asset "photo-1"
└── Galleries
    ├── Gallery A ── placement → "photo-1"
    └── Gallery B ── placement → "photo-1"
```

`photo-1` is one unique asset with two gallery placements.

## SourceReference

`SourceReference` contains a stable source identifier and an absolute HTTP or HTTPS
source URL. The portfolio carries the source namespace, such as `smugmug`; child
references are interpreted within that namespace. This avoids repeating the namespace
on every child while retaining every entity's stable provider identity and URL.

Source references identify remote records. They never imply that media content is
stored locally.

## Portfolio

`Portfolio` represents one normalized body of work. Asset and gallery source identities
must each be unique within it. Empty portfolios are valid.

## Gallery

`Gallery` represents an album, folder, collection, or equivalent logical grouping. It
contains metadata and ordered placements. Empty galleries are valid. Duplicate
placements of the same asset within one gallery are rejected because placement identity
is the pair of gallery identity and asset identity.

## GalleryPlacement

`GalleryPlacement` records the presence of one unique asset in one gallery. Its order in
the gallery's placement tuple is its presentation order. The same asset may be placed in
multiple galleries.

## Asset

`Asset` represents one unique media item. It owns:

- a `SourceReference`
- `AssetMetadata`
- an optional preview URL
- existing derived `Measurement` records

Preview URLs remain source references. Preview and original image bytes are not part of
the normalized model and are never persisted.

## AssetMetadata

`AssetMetadata` contains:

- an explicit `MediaType`
- an optional capture timestamp
- JSON-compatible normalized source values
- JSON-compatible EXIF values

Missing capture timestamps and preview URLs use `None`. Missing metadata keys remain
absent, and explicitly supplied JSON `null` values remain `None`. The model does not use
empty strings, zeroes, sentinel dates, or inferred values in place of missing evidence.

Capture timestamps preserve their recorded timezone information. Naive timestamps remain
timezone-unknown; the model does not infer a timezone.

## MediaType

Every asset is explicitly one of:

- `photograph`
- `non_photo`
- `unknown`

Unknown media is not silently treated as a photograph. Source adapters map provider
evidence into this shared enum. SmugMug records explicitly marked as video remain
representable as `non_photo` assets and are excluded from photographic analysis.

## Validation

Construction fails clearly for invalid source identifiers or URLs, non-JSON metadata,
duplicate portfolio identities, duplicate gallery placements, or placements that
reference unknown assets. Validation uses standard-library dataclasses and does not
introduce a validation framework.

## Persistence Round Trips

SQLite schema version 4 mirrors the normalized graph:

- portfolios and source references use explicit columns
- galleries are stored independently from assets
- assets are unique by source-scoped portfolio identity
- gallery placements preserve the many-to-many relationship and ordering
- media type and nullable capture timestamps use explicit columns
- extensible metadata, EXIF, measurements, observations, and findings use scoped JSON

Saving and loading preserves semantic equality, including empty collections, missing
values, non-photo and unknown media, source references, EXIF, timezone-aware timestamps,
and one asset placed in multiple galleries. Version-2 and version-3 databases migrate
forward without silently dropping records.

## Existing Analytical Records

`Measurement`, `Observation`, and `Finding` predate finalization of this foundation issue.
They remain for compatibility with existing persisted datasets and reports. This issue
does not expand those concepts.
