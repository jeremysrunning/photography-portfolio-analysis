# ADR 0003: Separate Portfolio Sources From Analyzers

- Status: Accepted
- Date: 2026-07-27

## Context

The first source is SmugMug, but future sources may include Lightroom Classic, Flickr, Capture One, and local folders.

## Decision

All source-specific behavior must terminate at a normalized data boundary.

Analyzers consume normalized portfolio records and must not depend on SmugMug or any other source implementation.

## Consequences

- Additional sources can be added without rewriting analyzers.
- The normalized model becomes a stable internal contract.
- Source-specific metadata must be mapped explicitly.
