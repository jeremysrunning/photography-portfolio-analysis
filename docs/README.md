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

Metadata analyzers, reports, visual-analysis persistence and orchestration, and the
`color-luminance`, `composition-saliency`, and `preview-structure` visual analyzers are
implemented. People and face detection is not a production capability: Issue #38 remains
blocked after Issues #49 and #51 found no detector strategy that satisfies the approved
evidence and distribution requirements.
The NanoDet and YuNet implementations under `research/` are calibration evidence only;
they are not registered production analyzers.

## Development

Python 3.12 or newer is required.

```console
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
```

The optional visual-preview research tools require:

```console
python -m pip install -e ".[dev,research]"
```

They are isolated under `research/` and are not part of the production `ppa` command
surface. See `docs/research/VISUAL_PREVIEW_REQUIREMENTS.md` for the bounded local command,
privacy rules, aggregate-only result policy, and current unverified findings.

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

SQLite stores normalized portfolio, gallery, unique-asset, gallery-placement, and
source-agnostic visual-analysis records.
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

The database carries an explicit schema version. This release creates version 6 and
migrates version-2 through version-5 databases in place; unsupported versions fail with a
clear error rather than being overwritten. SQLite foreign keys and transactions protect
relationships and roll back an incomplete save.

Inspect a saved dataset without contacting SmugMug:

```console
ppa show portfolio.sqlite3
```

Generate the source-agnostic metadata baseline:

```console
ppa report baseline portfolio.sqlite3
```

Run one registered visual analyzer resumably over persisted photographs:

```powershell
$env:PPA_SMUGMUG_API_KEY = "your-api-key"
ppa analyze visual portfolio.sqlite3 --analyzer ANALYZER_NAME
```

The first production analyzer is `color-luminance`:

```powershell
ppa analyze visual portfolio.sqlite3 --analyzer color-luminance
```

It requests a bounded 768 px memory preview and records deterministic relative-luminance,
encoded-sRGB saturation, direct Hasler–Süsstrunk colorfulness, luminance-tail, dominant
palette, and palette-entropy measurements. Use
`ppa analyze visual portfolio.sqlite3 --list-analyzers` for deterministic availability.
The command processes one analyzer/configuration identity at a time, defaults to one
worker, and accepts an explicit range of one through four. `--limit`, exact `--gallery`
source ID, and recorded `--year` filters are applied after deterministic asset sorting.
Progress uses the work items selected by the command's run-state mode as its denominator.
The final summary separately reports eligible photographs, asset-filter matches, selected
and processed work, state-excluded identities, and remaining work within that invocation.
In particular, ordinary pending identities excluded by `--only-failed` are not reported
as remaining failed-only work.

The deterministic composition and saliency analyzer is `composition-saliency`:

```powershell
ppa analyze visual portfolio.sqlite3 --analyzer composition-saliency
```

It requests a bounded 512 px memory preview and calculates a spectral-residual map on a
fixed 128×128 encoded-sRGB luminance representation. It records whether the map has
enough relative spatial variation under the versioned evidence rule, then conditionally
records a normalized centroid, normalized spread, and neutral distances to frame center
and rule-of-thirds geometry. A fixed row-major 3×3 result records regional saliency mass
when the map has normalizable mass.

Uniform and weak-evidence images complete successfully. They do not receive a fabricated
centroid or centroid-dependent distances. The analyzer does not identify a subject,
person, object, scene, human attention, photographer intent, compositional compliance,
or image quality. Preview pixels and transient saliency maps are never persisted.

The deterministic preview-structure analyzer is `preview-structure`:

```powershell
ppa analyze visual portfolio.sqlite3 --analyzer preview-structure
```

It requests a bounded 1,024 px memory preview, preserves its aspect ratio, and analyzes
every returned pixel without cropping, stretching, internal downsampling, or upscaling.
It records whether both decoded dimensions provide the configured minimum 16-pixel
measurement support. Smaller valid previews complete successfully with support false and
no fabricated numeric measurements.

Supported previews produce compact deterministic measurements for normalized Laplacian
sharpness, gradient-directional evidence and anisotropy, Sobel edge density, local
luminance contrast, spatial sharpness variation, edge-suppressed Haar residual evidence,
and the 95th-to-5th-percentile luminance span. These values describe provider-rendered
preview structure only. They do not establish original-file sharpness, focus accuracy,
depth of field, motion, lens behavior, sensor noise, scene content, intent, or quality.
The proposed texture-density measurement was rejected by generated preview-size validation
and is not part of the production catalog.

Generate the deterministic portfolio visual-habits report from persisted results:

```console
ppa report visual-habits portfolio.sqlite3
```

The report selects the exact identities currently registered for `color-luminance`,
`composition-saliency`, and `preview-structure`. It never falls back to or combines older
analyzer/configuration versions. Current attempt states and retained last-successful
snapshots are disclosed separately, and every measurement uses its documented conditional
denominator. Missing, failed, skipped, pending, running, weak-evidence, and unsupported
results are not converted to false or zero.

The concise report includes evidence and coverage, composition and saliency, color and
luminance, preview structure, conservative adjacent-year median differences, and methods
and limitations. Request independent optional sections with:

```console
ppa report visual-habits portfolio.sqlite3 --details
ppa report visual-habits portfolio.sqlite3 --gallery-breakdown
ppa report visual-habits portfolio.sqlite3 --year-breakdown
ppa report visual-habits portfolio.sqlite3 --camera-breakdown
ppa report visual-habits portfolio.sqlite3 --lens-breakdown
ppa report visual-habits portfolio.sqlite3 --orientation-breakdown
```

`--details` expands measurement evidence and provenance without enabling segmentation.
Flags can be combined without duplicate headings. Gallery, year, camera, lens, and
orientation measurements require at least 20 usable photographs; galleries also require
at least 50% successful-snapshot coverage for the selected identity.

Reporting reads SQLite and normalized metadata only. It requires no SmugMug key, fetches
no preview, invokes no analyzer or model, and does not modify visual-analysis state.
People/face and scene/environment findings remain unavailable while Issues #38 and #40
are blocked and are not presented as negative classifications.

Completed work is skipped unless `--refresh` is supplied. `--retry-failed` includes durable
failures and cancellation-interrupted pending work; `--only-failed` includes only durable
failures. Existing `running` work is never reclaimed automatically and is reported as
running elsewhere or left running. Preview data remains temporary, while each completed
asset result set is committed incrementally.

Analyzers must normally emit at least one result. An analyzer may explicitly declare that
an empty result set is a valid success; otherwise empty output is recorded as a failed
analyzer-output attempt. Future detection analyzers should generally emit explicit zero
counts rather than use empty output to mean that nothing was detected.

Color measurements describe the provider-rendered preview, not the original file. Version
1 assumes the decoded channels represent sRGB, performs no ICC conversion, composites
alpha against neutral mid-gray, and does not infer original-file clipping, available
headroom, color intent, mood, or quality. The colorfulness value is the finite,
nonnegative direct formula output for normalized-sRGB input; it is not a proportion,
percentage, score, or universal perceptual scale and should be compared only within the
same method version.

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

## Temporary previews

Production preview access is an opt-in library operation on `GallerySource`; normal
inspection, import, enrichment, analysis, and reporting commands do not fetch image
content. Callers provide a `PreviewRequest` with a maximum longest edge, encoded-byte
limit, accepted image content types, and storage mode. The production hard limits are
1,024 pixels and 8,000,000 encoded bytes.

Memory mode is the default. The source downloads into a bounded internal buffer, closes
the network response, decodes and validates the image, releases the encoded bytes, and
returns a context-managed `PreviewResource` that owns only the decoded Pillow image and
immutable metadata. Compatible future analyzers may share that image only while the
resource context is open:

```python
from ppa.sources import PreviewRequest

with source.open_preview(asset, PreviewRequest(maximum_edge=512)) as preview:
    width, height = preview.image.size
```

Temporary-file mode must be requested explicitly with
`PreviewStorageMode.TEMPORARY_FILE`. It returns an owned OS-managed path for a
file-path-only library and does not retain a decoded image. The validated,
EXIF-orientation-applied raster is encoded as PNG so file and memory modes expose the same
pixel dimensions and coordinate orientation. `content_type` describes the exposed
resource, while `downloaded_content_type`, `downloaded_encoded_byte_count`, and the
optional `temporary_file_byte_count` keep transfer and re-encoded file facts distinct.
The neutral random filename contains no source identifier, title, URL, or credential.
Closing the resource deletes the path; cleanup is also performed for exceptions and
cooperative cancellation. Cleanup cannot be guaranteed after forcible process termination.

SmugMug preview access uses official image-size metadata, selects the closest supported
non-original preview at or below the request, and never upscales or silently resizes.
Original, download, archive, and ambiguous largest resources are rejected. HTTPS,
redirect, content-type, byte, reported-dimension, and decoded-dimension limits are
validated before a resource is returned. Reported and decoded dimensions currently must
match exactly after allowing an exact EXIF-orientation width/height swap. This conservative
consistency rule is not yet validated against a bounded real SmugMug sample and may be
narrowed only with evidence; requested-edge and production ceilings will remain strict.

Preview failures are source-agnostic. Rate limiting, temporary server responses, timeouts,
and transport failures are retryable by a future orchestrator. Missing, unsupported,
corrupt, original-like, oversized, or dimension-mismatched previews are permanent for the
current asset unless its provider metadata changes. Authentication and authorization
failures require configuration or access changes. Cancellation is reported separately.
Preview access itself performs no retry and does not persist bytes, decoded images,
temporary paths, provider media URLs, thumbnails, or analysis results.

Run the aggregate-only bounded production validation locally against 12 photographs after
setting the API key:

```powershell
$env:PPA_SMUGMUG_API_KEY = "your-api-key"
python scripts/validate_preview_lifecycle.py jrp-import-test.sqlite3 --sample-size 12
```

The command rotates 256, 512, and 1,024 px requests, exercises both storage modes, emits
only non-identifying aggregate counts, and writes no result file.
