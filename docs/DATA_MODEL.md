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

`SourceReference` currently contains a stable source identifier and an absolute HTTP or
HTTPS source URL. This is an intentional Phase 1 constraint because every implemented
source is network-backed. The portfolio carries the source namespace, such as `smugmug`;
child references are interpreted within that namespace. This avoids repeating the
namespace on every child while retaining every entity's stable provider identity and URL.

A future local-folder source should extend this boundary to a validated URI/reference
representation (or a separate source-reference variant) rather than weakening URL
validation or placing filesystem behavior in analyzers. Local-folder support is not
introduced by the current model.

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
- optional normalized native and 35 mm-equivalent focal lengths in millimeters
- JSON-compatible normalized source values
- JSON-compatible EXIF values

Missing capture timestamps and preview URLs use `None`. Missing metadata keys remain
absent, and explicitly supplied JSON `null` values remain `None`. The model does not use
empty strings, zeroes, sentinel dates, or inferred values in place of missing evidence.
Normalized value, EXIF, gallery, and portfolio mappings are defensively copied and deeply
frozen during construction. Neither caller-owned input dictionaries nor nested lists and
mappings can mutate normalized model state afterward.

Capture timestamps preserve their recorded timezone information. Naive timestamps remain
timezone-unknown; the model does not infer a timezone.

Native focal length and 35 mm-equivalent focal length are independent, positive finite
numeric fields. They contain only measurements explicitly reported by the source. Integer,
decimal, and rational EXIF representations are normalized to millimeters. Missing,
zero, negative, non-finite, and malformed values remain `None`; one focal-length field is
never derived from the other. Reported teleconverter-adjusted focal lengths are preserved
without attempting to identify an underlying lens or infer a crop factor. The original
source representation remains available in the immutable EXIF mapping.

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

## Visual Analysis Results

Visual analysis uses a separate application-level contract and does not expand the legacy
`Measurement`, `Observation`, or `Finding` types. Each result belongs to an immutable
identity consisting of analyzer name, analyzer version, and configuration version. A
result has a unique name, a deterministic-measurement or model-classification kind, a
non-null JSON-compatible value, method provenance, a timezone-aware successful-completion
timestamp, and optional unit, model provenance, and classification confidence.

Confidence `0.0` is recorded evidence. `None` means the method did not provide confidence.
An absent result row means the measurement or classification is missing. Deterministic
measurements do not carry confidence. Normalized points and top-left-origin bounding boxes
use coordinates in `[0, 1]`; bounding boxes must remain within the image frame.

Each exact asset/analyzer/configuration identity has a current status: `pending`,
`running`, `completed`, `failed`, or `skipped`. `last_successful_completed_at` identifies
the stored result snapshot. Every result in that snapshot exposes the same timestamp;
snapshot construction rejects missing or inconsistent result provenance. During a
refresh, failure, or cancellation, readers can
therefore distinguish an older successful snapshot from the current incomplete attempt.
Cancellation returns the identity to `pending`, retains its incremented attempt count, and
records an interruption category and timestamp. Its next claim requires explicit retry.

### Color and luminance result catalog

Analyzer identity `color-luminance` / `1.0.0` /
`rendered-srgb-768-v1` stores nine deterministic measurements:

- mean and median linear-sRGB relative luminance in `[0, 1]`
- shadow and highlight relative-luminance tail proportions in `[0, 1]`, using inclusive
  thresholds derived from encoded-sRGB `5/255` and `250/255`
- mean and median encoded-sRGB HSV saturation proportions in `[0, 1]`
- direct Hasler–Süsstrunk colorfulness formula output from channels normalized to
  `[0, 1]`; it is finite and nonnegative but has no claimed universal perceptual range
- up to five dominant colors from a deterministic four-bit-per-channel RGB histogram,
  with selected-color proportions summing to one and separate total-pixel coverage
- three-bit-per-channel histogram Shannon entropy normalized to `[0, 1]`

Luminance-tail proportions describe occupancy near rendered-preview luminance boundaries.
They cannot establish clipping or available headroom in an original file. JPEG
compression, source rendering, provider processing, and the absence of a verified ICC
workflow can affect all preview measurements. Version 1 composites transparency against
encoded-sRGB `(128, 128, 128)`, applies no ICC conversion, samples every returned pixel,
and never silently resizes. Method or configuration semantics cannot change without an
identity version change.

### Composition and saliency result catalog

Analyzer identity `composition-saliency` / `1.0.0` /
`rendered-srgb-512-stretch128-bilinear-sr-box3-smooth5-logeps1e-9-masseps1e-12-rd005-grid3-round8-v1`
stores deterministic measurements from a transient spectral-residual saliency map:

- `saliency_evidence`: boolean; true exactly when map mean exceeds `1e-12` and population
  standard deviation divided by mean is at least `0.05`
- `saliency_centroid`: top-left-origin saliency-mass-weighted normalized point, emitted
  only when evidence exists
- `saliency_spread`: saliency-weighted root-mean-square centroid distance divided by the
  frame diagonal, emitted only when evidence exists
- `saliency_grid_3x3`: nine regional mass proportions in row-major order, emitted whenever
  total map mass exceeds `1e-12`
- `saliency_center_distance`: centroid-to-frame-center distance divided by `sqrt(2)/2`
- `saliency_thirds_line_distance`: minimum centroid distance to a vertical or horizontal
  thirds line divided by `1/3`
- `saliency_thirds_intersection_distance`: minimum centroid distance to a thirds
  intersection divided by `sqrt(2)/3`

The grid uses cell-center assignment with boundaries at one-third and two-thirds. Exact
boundary coordinates enter the later region. Its first eight masses use eight-decimal
half-even rounding, and the ninth is the remainder from `1.00000000`. Centroid-dependent
results are absent rather than null when evidence is weak. A zero-mass valid image still
completes with `saliency_evidence = false`.

These values describe only the configured saliency representation. They do not identify
subjects, people, objects, scenes, human attention, intent, quality, or compliance with a
compositional rule. No preview, map, array, image, or path is persisted.

## Persistence Round Trips

SQLite schema version 6 mirrors the normalized graph:

- portfolios and source references use explicit columns
- galleries are stored independently from assets
- assets are unique by source-scoped portfolio identity
- gallery placements preserve the many-to-many relationship and ordering
- media type, nullable capture timestamps, and nullable native and 35 mm-equivalent focal
  lengths use explicit columns
- extensible metadata, EXIF, measurements, observations, and findings use scoped JSON
- visual run state and successful result snapshots use separate relational tables

Saving and loading preserves semantic equality, including immutable metadata mappings,
empty collections, missing values, non-photo and unknown media, source references, EXIF,
timezone-aware timestamps, and one asset placed in multiple galleries. Version-2,
version-3, version-4, and version-5 databases migrate forward without silently dropping
records. Analyzer and configuration versions coexist without automatic pruning or
supersession.

## Existing Analytical Records

`Measurement`, `Observation`, and `Finding` predate finalization of this foundation issue.
They remain for compatibility with existing persisted datasets and reports. This issue
does not expand those concepts.
