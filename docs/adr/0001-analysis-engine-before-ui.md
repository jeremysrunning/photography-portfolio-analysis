# ADR 0001: Build the Analysis Engine Before a User Interface

- Status: Accepted
- Date: 2026-07-27

## Context

The project may eventually support a desktop application or integration with other photography software. Building a UI first would couple early design decisions to one presentation layer.

## Decision

Build a reusable Python analysis engine first, exposed through a small CLI.

Do not build a web application or desktop GUI during the initial phases.

## Consequences

- Core behavior remains testable without a UI.
- Future interfaces can reuse the same engine.
- Early work focuses on ingestion, normalization, analysis, and reporting.
