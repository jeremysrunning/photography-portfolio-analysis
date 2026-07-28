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