# Data Model

The project revolves around a small number of core concepts.

## Portfolio

A complete body of work being analyzed.

A portfolio may originate from any supported source.

## Gallery

A logical grouping of assets.

Examples include albums, folders, collections, or events.

## Asset

A single photograph.

An asset contains:

- metadata
- derived measurements
- references to its source

The project should avoid storing the original image whenever practical.

## Measurement

An objective value extracted from an asset.

Examples:

- focal length
- brightness
- dominant colors
- number of faces

Measurements should be reproducible.

## Observation

A qualitative statement derived from one or more measurements.

Examples:

- The photographer frequently uses environmental portraits.
- Humor appears throughout the portfolio.

Observations should always reference supporting evidence.

## Finding

A conclusion supported by one or more measurements or observations.

Every finding should include an indication of confidence.

## Initial Representation

The normalized model is implemented as immutable, typed dataclasses.

- Source identities are strings and are interpreted within a source namespace.
- Flexible metadata and EXIF fields must contain JSON-compatible values.
- Measurements record a name, value, and optional unit and method.
- Observations and findings carry explicit evidence references.
- Finding confidence is a value from `0.0` to `1.0`.

Source and preview URLs are references. They do not imply that image content is retained.
The initial SQLite representation stores the complete normalized dataset and has an
explicit schema version for future migration work.

SmugMug calls both photographs and videos "images." The source adapter excludes records
explicitly marked as video. Baseline analysis also detects non-photo formats in previously
stored datasets, discloses their count, and excludes them from photographic measurements.

## Enrichment State

EXIF is stored as JSON-compatible values on each normalized asset. A separate operational
record tracks whether public EXIF enrichment for a unique source asset is completed or
failed, along with attempt count, last error, and update time.

An empty EXIF object can still be a completed enrichment: it means the source returned no
public metadata. This distinction prevents repeated requests for photographs that simply
have no available EXIF.
