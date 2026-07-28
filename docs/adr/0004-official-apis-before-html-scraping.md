# ADR 0004: Prefer Official APIs Over HTML Scraping

- Status: Accepted
- Date: 2026-07-27

## Context

Gallery websites may expose both public web pages and official APIs.

## Decision

Use an official supported API whenever it provides the required data.

HTML crawling may be considered only for data that is public, permitted, unavailable through the API, and obtainable without bypassing access controls.

## Consequences

- Integrations should be more stable and respectful of provider terms.
- API credentials must never be committed.
- Rate limiting and API errors must be handled explicitly.
