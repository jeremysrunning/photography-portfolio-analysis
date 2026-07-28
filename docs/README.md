# Photography Portfolio Analysis

What defines a photographer's style?

Photographers spend years developing an artistic voice, yet most feedback focuses on individual images rather than the body of work as a whole. This project explores whether a photographer's unique visual style can be better understood through a combination of objective measurements, computer vision, and thoughtful observation.

## Vision

Every photographer has a visual fingerprint.

This project exists to help photographers discover it.

## Goals

- Analyze photographic portfolios at scale.
- Extract meaningful insights from image metadata and visual analysis.
- Identify recurring creative patterns and habits.
- Generate evidence-based reports that help photographers better understand their work.
- Build an open framework that can analyze portfolios from multiple sources.

## Guiding Principles

This project distinguishes between **measurement** and **observation**.

### Measurements

Objective, reproducible characteristics such as:

- Camera and lens usage
- Focal lengths
- Exposure settings
- Color palettes
- Subject placement
- Orientation
- Time of day
- Visual complexity

### Observations

Higher-level interpretations such as:

- Storytelling
- Humor
- Sense of place
- Community
- Emotional tone
- Artistic voice

Measurements provide evidence.

Observations provide context.

Together they help photographers better understand their own work.

## Project Status

This project is in its early foundation phase. It currently provides:

- source-agnostic normalized portfolio models
- a generic gallery source contract
- public SmugMug metadata inspection
- SQLite persistence for normalized datasets
- structured JSON logging
- a small command-line interface

Portfolio analysis and report generation are not implemented yet.

## Development

Python 3.12 or newer is required.

```console
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
```

Initialize an empty normalized dataset:

```console
ppa init-db portfolio.sqlite3
```

Inspect a public SmugMug portfolio and save its normalized metadata:

```powershell
$env:PPA_SMUGMUG_API_KEY = "your-api-key"
ppa inspect https://example.smugmug.com --database portfolio.sqlite3
```

[SmugMug requires an API key](https://api.smugmug.com/api/v2/doc/tutorial/api-key.html)
for public API requests. OAuth is not required for public data. The key can also be supplied
with `--api-key`, although the environment variable avoids placing it in shell history.

The command discovers all public albums, follows paginated album-image listings, prints
gallery and photograph-reference counts, and optionally saves the normalized dataset.
Password-protected, unlisted, and private content is outside this first slice.

Inspect a saved dataset without contacting SmugMug:

```console
ppa show portfolio.sqlite3
```

Generate the source-agnostic metadata baseline:

```console
ppa report baseline portfolio.sqlite3
```

Enrich the saved SmugMug dataset with public image metadata:

```powershell
$env:PPA_SMUGMUG_API_KEY = "your-api-key"
ppa enrich exif portfolio.sqlite3
```

EXIF enrichment uses SmugMug multi-get requests (25 images per request by default) and
commits each returned asset immediately. It can be interrupted and safely rerun: completed
assets are skipped, rate-limited requests remain pending, and failed assets are retried
only when `--retry-failed` is supplied.

Useful controls:

```console
ppa enrich exif portfolio.sqlite3 --limit 100
ppa enrich exif portfolio.sqlite3 --batch-size 10
ppa enrich exif portfolio.sqlite3 --retry-failed
```

Use `--limit` for a small initial validation run. Batch size must be between 1 and 100.
The command reports pending, completed, and failed unique-asset counts before and after
each run.

Generate an equipment and exposure report after enrichment:

```console
ppa report equipment portfolio.sqlite3
```

The equipment report starts with evidence coverage, then describes the most frequently
recorded camera and lens models, focal-length ranges and exact values, apertures, exposure
times, ISO ranges and exact values, and the most frequently recorded camera in each capture
year. Distribution percentages use only photographs where that EXIF field is available.

The baseline distinguishes gallery placements from unique image identities and reports
gallery-size distribution, capture range, orientation, file-format distribution, geotag
coverage, and camera/lens metadata coverage. Non-photo media already present in a dataset
is disclosed and excluded. Missing metadata is measured rather than interpreted.

The database contains metadata, source references, and derived data only. The current
storage API has no facility for persisting original image content. SmugMug inspection does
not call image-size or media-download endpoints.
