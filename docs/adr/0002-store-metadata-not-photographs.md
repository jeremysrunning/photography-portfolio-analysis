# ADR 0002: Store Metadata and Derived Features, Not Photographs

- Status: Accepted
- Date: 2026-07-27

## Context

Website gallery analysis requires temporary access to image data, but the project must not become a photo scraper or archival downloader.

## Decision

Do not permanently store original images or web previews by default.

Web-sized previews may be processed in memory or in a short-lived temporary cache. Persist only metadata, source references, and derived measurements.

## Consequences

- The project minimizes storage and privacy risk.
- Re-analysis may require fetching previews again.
- Temporary files must be cleaned up reliably.
- Original-resolution downloads remain out of scope.
