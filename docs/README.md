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

- source-agnostic normalized portfolio, unique-asset, and gallery-placement models
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

Pull requests targeting `main` run the same tests, lint, and formatting checks in GitHub
Actions on Python 3.12. The `CI / quality` check must pass before a pull request can merge.

Initialize an empty normalized dataset:

```console
ppa init-db portfolio.sqlite3
```

Inspect a public SmugMug portfolio and save its normalized metadata:

```powershell
$env:PPA_SMUGMUG_API_KEY = "your-api-key"
ppa inspect https://example.smugmug.com --database portfolio.sqlite3
```

Run the complete import workflow—inspection, transactional persistence, and resumable
EXIF enrichment—with one command:

```powershell
$env:PPA_SMUGMUG_API_KEY = "your-api-key"
ppa import https://example.smugmug.com --database portfolio.sqlite3
```

The database path is required. The command reports three visible stages and a final
summary that distinguishes photographs enriched during the run, photographs already
enriched, non-photo assets completed because EXIF is not applicable, failures, and
remaining work. A rerun safely skips completed work. Use `--retry-failed` to include
records whose earlier enrichment attempts failed.

Inspection or persistence failure exits with status 1 and enrichment does not start.
Partial item failure also exits with status 1; rate limiting exits with status 2.
In either partial case, successful enrichment remains committed and the database remains
usable and safe to resume.

[SmugMug requires an API key](https://api.smugmug.com/api/v2/doc/tutorial/api-key.html)
for public API requests. OAuth is not required for public data. The key can also be supplied
with `--api-key`, although the environment variable avoids placing it in shell history.

The command follows SmugMug's linked root-node hierarchy to discover nested public folders
and albums, including empty albums, then follows paginated album-image listings. Explicitly
private, unlisted, and password-protected nodes are skipped. Rate limits and transient
request failures use bounded retries with structured progress logging. The command prints
gallery and media-reference counts and optionally saves the normalized dataset.

SQLite stores normalized portfolio, gallery, unique-asset, and gallery-placement records.
Saving the same crawl again updates matching source-scoped identities without creating
duplicates. Assets encountered in more than one gallery are stored once and linked to
each gallery through placements. The first occurrence in normalized gallery order supplies
the canonical asset metadata, matching analyzer deduplication behavior.

Later saves update records present in the crawl but conservatively retain previously seen
galleries, assets, and placements that are absent. Automatic deletion synchronization is
not performed. Existing EXIF and derived measurements are retained when a later crawl has
no replacement enrichment data.

Media assets have an explicit `photograph`, `non_photo`, or `unknown` type. Unknown media
is not treated as photography, and SmugMug video records remain represented without being
included in photographic analysis.

The database carries an explicit schema version. This release creates version 5 and
migrates version-2, version-3, and version-4 databases in place; unsupported versions fail
with a clear error rather than being overwritten. SQLite foreign keys and transactions
protect relationships and roll back an incomplete save.

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

Native focal length and the independently reported 35 mm-equivalent focal length are
normalized into typed millimeter fields from SmugMug's confirmed `FocalLength` and
`FocalLength35mm` metadata. Integer, decimal, and rational representations are accepted.
Missing or malformed values remain missing, and no crop factor, effective focal length,
or underlying lens is inferred.

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

Generate the focal-length habits report:

```console
ppa report focal-length portfolio.sqlite3
```

The report compares usable native and 35 mm-equivalent coverage and selects one primary
portfolio-wide basis deterministically: greater coverage wins, and a nonzero tie prefers
35 mm equivalent. Native and equivalent measurements are never combined within one
distribution. Lens summaries always use native focal length.

Medians, minimums, maximums, and range classification use the unrounded normalized
measurements. Repeated-value frequencies and distinct-value counts group measurements to
the nearest whole millimeter using positive half-up rounding so small representation
differences do not create false precision around commonly recorded values.

Equivalent-based distributions use these inclusive-lower, exclusive-upper ranges:
Ultra-wide `[0, 24)`, Wide `[24, 35)`, Normal `[35, 50)`, Short telephoto `[50, 85)`,
Medium telephoto `[85, 200)`, and Super telephoto `[200, infinity)`. Native distributions
use the same numeric boundaries with neutral labels rather than full-frame-equivalent
category names.

The default report limits camera and lens summaries to five each and galleries to ten.
Default segments require at least 20 measured photographs; galleries also require at
least 50% focal-length coverage. Every displayed segment includes its sample size and
coverage. Request complete distributions or segment breakdowns independently:

```console
ppa report focal-length portfolio.sqlite3 --details
ppa report focal-length portfolio.sqlite3 --camera-breakdown
ppa report focal-length portfolio.sqlite3 --lens-breakdown
ppa report focal-length portfolio.sqlite3 --gallery-breakdown
ppa report focal-length portfolio.sqlite3 --year-breakdown
```

Flags can be combined without duplicating sections. Missing values remain missing; the
report does not infer focal length from camera models, lens names, crop factors, field of
view, filenames, or neighboring photographs.

Generate a timeline report:

```console
ppa report timeline portfolio.sqlite3
```

The timeline report describes yearly and monthly capture counts, recorded capture hours,
and camera and gallery segments with sample sizes and timestamp coverage. UTC, explicit
offsets, and timezone-unknown timestamps remain separate; the report does not infer a
local timezone or interpret capture volume as productivity.

The default output is a concise evidence and measurement summary with the five most
represented camera models and ten largest galleries. Request exhaustive sections
independently:

```console
ppa report timeline portfolio.sqlite3 --details
ppa report timeline portfolio.sqlite3 --camera-breakdown
ppa report timeline portfolio.sqlite3 --gallery-breakdown
```

`--details` adds complete yearly, monthly, and recorded-hour distributions. The camera
and gallery flags add their respective complete per-segment distributions. Flags can be
combined without duplicating sections.

The baseline distinguishes gallery placements from unique image identities and reports
gallery-size distribution, capture range, orientation, file-format distribution, geotag
coverage, and camera, lens, native focal-length, and 35 mm-equivalent focal-length metadata
coverage. Non-photo media already present in a dataset is disclosed and excluded. Missing
metadata is measured rather than interpreted.

The database contains metadata, source references, and derived data only. The current
storage API has no facility for persisting original image content. SmugMug inspection does
not call image-size or media-download endpoints.
