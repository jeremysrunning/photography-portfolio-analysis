# Visual Preview Requirements Research

## Executive summary

Issue #19 establishes an isolated, reproducible benchmark for bounded web previews without
adding a production visual analyzer or changing the `GallerySource` contract.

The repository currently has no usable typed SmugMug preview: `Asset.preview_url` is absent
for all 30,406 persisted assets. SmugMug's flexible metadata contains a `ThumbnailUrl` for
all 30,258 photographs, but a bounded in-memory probe measured that resource as a cropped
150 × 150 JPEG. It is unsuitable for the requested comparisons.

The experimental resolver therefore follows SmugMug's official `ImageSizeDetails` link,
accepts only provider-reported non-original HTTPS resources, enforces maximum dimensions
and bytes, and remains under `research/`. It is not a finished preview lifecycle.

Synthetic results support these provisional choices:

| Analyzer family | Provisional preview | Status |
| --- | ---: | --- |
| Scalar color and luminance | 512 px | Ready for bounded real validation |
| Quantized palettes | 768 px | Usable with caveats |
| Spectral-residual saliency | 512 px | Usable with caveats |
| Edge density and global contrast | 768 px | Usable with caveats |
| Sharpness, blur, noise, depth of field | Not selected | Deferred as resolution-sensitive |
| People and faces | Not selected | Not yet evaluated; candidate selection deferred |
| Broad scene classification/segmentation | Not selected | Not yet evaluated |

These are not final empirical portfolio recommendations. The real preview benchmark could
not run because no SmugMug API key was available in the process or Windows user
environment. The deterministic real-portfolio sample was selected successfully, while
all preview-size, network, real-image stability, manual category, concurrency, and cleanup
findings remain explicitly unverified.

## Scope and architectural boundary

The spike includes:

- deterministic metadata-stratified sampling
- experimental provider size discovery and bounded fetching
- in-memory Pillow decoding
- deterministic color, luminance, palette, edge, sharpness-proxy, and saliency calculations
- cross-size stability comparisons
- timing, transferred-byte, process-RSS, and cleanup measurements
- aggregate-only publication
- a people-detection evaluation protocol

It does not include production preview lifecycle management, persistence, analyzer run
state, orchestration, a normal `ppa` command, permanent caching, original downloads,
identity processing, model inference, or aesthetic scoring.

ADR 0001 is preserved because the work is an engine-side script with no UI. ADR 0002 is
preserved because image bytes remain in memory and no image artifact is written. ADR 0003
is preserved because provider behavior is isolated under the research boundary. ADR 0004
is preserved by using the official API rather than HTML. ADR 0005 is preserved through
descriptive measurements and explicit limitations.

## Existing preview behavior

The production source contract exposes:

```text
open_preview(asset) -> context-managed binary stream
```

It does not support a requested size, returned dimensions, content type, byte allowance,
redirect policy, or explicit original rejection. `SmugMugSource.open_preview()` closes its
network stream, but `_asset()` never populates `preview_url`.

Read-only aggregate inspection of `jrp-import-test.sqlite3` found:

- 30,406 assets
- 30,258 photographs
- zero typed `preview_url` values
- 30,258 `ThumbnailUrl` metadata values
- one public thumbnail probe: 25,681 bytes, JPEG, 150 × 150, decoded in memory

No URL or image bytes from that probe were retained.

The official SmugMug Image documentation identifies `ImageSizeDetails` as the supported
source of available media URLs and dimensions. SmugMug also documents custom-size
expansion requests. The research resolver navigates the size-details link dynamically and
does not rewrite thumbnail URLs.

- <https://api.smugmug.com/api/v2/doc/reference/image.html>
- <https://api.smugmug.com/api/v2/doc/advanced/config.html>

## Sample-selection method

Algorithm version: `issue-19-research-v1`

The sampler:

1. selects normalized photographs only
2. derives metadata strata for orientation, five-year capture band, recorded camera, and
   recorded native/35 mm-equivalent focal-length band
3. assigns stable SHA-256 ranks using seed `issue-19-v1`
4. round-robins across strata until 48 photographs are selected
5. uses the first normalized gallery placement only for aggregate gallery representation

The selected real-portfolio aggregate is:

- sample size: 48
- orientation: 27 landscape, 21 portrait, no square image selected
- galleries represented: 33
- five-year bands: 2005–2009 (10), 2010–2014 (5), 2015–2019 (9),
  2020–2024 (19), 2025–2029 (5)
- recorded cameras represented: 10
- focal bands: under 35 mm (10), 35–84 mm (11), 85–199 mm (9),
  200 mm or longer (12), focal length missing (6)

These strata make no claim about people, occlusion, brightness, scene, or complexity.
After previews are decoded, a bounded local-only rubric records those categories. At most
12 documented edge cases may be added if the deterministic sample lacks required
categories. Per-image annotations and selections remain local; only aggregate category
counts may be published.

## Preview sizes and limits

Requested longest edges are 256, 512, 768, and 1024 pixels. The resolver records both the
provider-reported and decoded width and height. After EXIF orientation is applied, the
decoded longest edge must not exceed the requested edge. Decoded width and height must
match the reported dimensions exactly; the only tolerance is an exact width/height swap
caused by EXIF orientation, which preserves the longest edge. There is no numeric pixel or
percentage tolerance.

A dimension mismatch is classified as either `decoded_exceeds_requested_edge` or
`reported_decoded_dimension_mismatch`. The local raw output retains both dimension pairs
and the classification. Aggregate output contains only mismatch counts by classification.
Any asset with a mismatched requested preview is excluded from measurements and all
cross-resolution stability calculations. The benchmark never silently resizes a provider
response to make it conform.

Experimental limits:

- HTTPS only
- credential-free media URLs only
- public literal IP addresses only when a literal address is used
- maximum requested experimental edge: 1280 px
- standard comparison maximum: 1024 px
- maximum encoded payload: 8,000,000 bytes
- maximum redirects: 3
- accepted response content types: `image/*`
- no originals, archives, downloads, or provider-labelled largest resources
- in-memory decoding only

The 1280 px ceiling exists only to observe a slightly larger provider web size if the
standard experiment later justifies it. It is not a production recommendation.

## Libraries and algorithms

### Pillow 12.3.0

- purpose: in-memory JPEG/PNG/WebP-compatible decoding, EXIF orientation, resizing,
  generated test fixtures
- license: HPND
- downloaded Windows wheel: approximately 7.2 MB
- installed footprint measured locally: 16,159,155 bytes
- runtime: local CPU
- inputs: streams and in-memory bytes
- determinism: decode depends on the encoded preview and Pillow/libjpeg build; exact
  package version is recorded

### NumPy 2.5.1

- purpose: arrays, histograms, gradients, FFT, deterministic statistics
- license: BSD-3-Clause with permissively licensed vendored components recorded by NumPy
- downloaded Windows wheel: approximately 12.4 MB
- installed footprint measured locally: 53,555,429 bytes
- runtime: local CPU
- inputs: in-memory arrays
- determinism: fixed algorithms, fixed quantization, and fixed random seed for synthetic
  fixtures

### psutil 7.2.2

- purpose: process RSS polling for native-library memory visibility
- license: BSD-3-Clause
- downloaded wheel: approximately 137 KB
- installed footprint measured locally: 835,826 bytes
- runtime: local CPU/process inspection
- inputs: process counters; no image access

No model weights are used. Saliency uses the spectral-residual method described by Xiaodi
Hou and Liqing Zhang, CVPR 2007, DOI `10.1109/CVPR.2007.383267`. The implementation uses a
64 × 64 luminance representation, FFT log-amplitude residual, and normalized spatial map.
It produces a centroid and spread, not a claim about human attention or composition quality.

No PyTorch, torchvision, Ultralytics, OpenCV, ONNX Runtime, MediaPipe, cloud service, or
external image-analysis API is included.

## Measurement methods

Deterministic scalar measurements use normalized RGB and Rec. 709 luminance:

- mean and median luminance
- luminance standard deviation
- 5th-to-95th-percentile global contrast
- mean and median HSV-style saturation
- Hasler–Süsstrunk-style colorfulness proxy
- mean red-minus-blue warmth proxy
- luminance fractions at or below 5/255 and at or above 250/255
- normalized 3-bit/channel palette entropy
- gradient edge-density fraction at the versioned threshold
- Laplacian-variance sharpness proxy

Palettes use deterministic 4-bit/channel quantization with the five most represented bins
and their proportions. They are compact derived values, not reconstructive histograms.

Saliency produces normalized centroid coordinates and normalized radial spread. Saliency
maps are used transiently and are never serialized.

Sharpness is deliberately labelled a preview-specific proxy. It is not evidence about
original-file focus or lens performance.

## Predeclared stability thresholds

These thresholds were defined before real-image results:

| Measurement | Absolute threshold |
| --- | ---: |
| Mean luminance | 0.02 |
| Median luminance | 0.03 |
| Luminance spread | 0.03 |
| Global contrast | 0.03 |
| Mean/median saturation | 0.03 |
| Colorfulness | 0.05 |
| Warmth proxy | 0.03 |
| Highlight/shadow clipping fraction | 0.02 |
| Palette diversity | 0.08 |
| Weighted normalized palette distance | 0.08 |
| Palette-proportion L1 difference | 0.15 |
| Edge density | 0.05 |
| Saliency-centroid distance | 0.05 frame diagonals |
| Saliency spread | 0.05 |

Sharpness, blur, noise, depth-of-field, and subject-background separation do not receive a
threshold before real evidence. No universal stability score is calculated.

## Synthetic stability findings

The committed aggregate uses eight generated, non-identifying fixtures: solid, gradient,
checkerboard, two-color, geometric, low-contrast, blurred, and seeded noise. Every fixture
was JPEG encoded and independently decoded at 256, 512, 768, and 1024 px.

Against 1024 px:

- mean and median luminance were within threshold for all fixtures at every size
- palette color distance and saliency centroid/spread were within threshold for all
  fixtures at every size
- palette-proportion stability was 62.5% at 256, 75% at 512, and 87.5% at 768
- edge-density stability was 75% at all three smaller sizes
- luminance-spread stability was 75% at 256/512 and 87.5% at 768
- colorfulness stability was 87.5% at 256/512 and 100% at 768
- contrast, clipping, and saturation each had at least one synthetic failure at every size

These findings support 512 px for scalar color/luminance and saliency experiments, while
palette proportions and structural measurements should begin at 768 px. They do not
establish real-image stability.

## Runtime and memory findings

Synthetic benchmark environment:

- Python 3.13 on Windows; CI compatibility remains Python 3.12
- eight fixtures × four sizes
- one worker
- total elapsed: 2.42 seconds
- per-fixture four-size decode median: 0.0077 seconds
- per-fixture four-size analysis median: 0.226 seconds
- observed process peak RSS: 134,393,856 bytes (128.2 MiB)
- temporary files created: zero
- temporary files remaining: zero

The four-size synthetic CPU extrapolation is approximately 7,216 seconds for 30,000
photographs. A one-size deterministic pass is roughly one quarter of that work—about
30 minutes—but this excludes network time, real compression, machine variation, retries,
and production persistence. It is a planning range, not a forecast.

Network throughput, real decode time, redirect behavior, real peak-memory increments, and
multi-worker throughput remain unverified.

## Cleanup and temporary-file findings

The prototype uses `BytesIO`, context-managed Pillow images, local arrays, and no temporary
files. Tests verify successful decode leaves no file, corrupt and oversized inputs fail
cleanly, and raw output is written only to the ignored `research-output/` directory.

The repository cleanliness check rejects tracked image/database extensions and scans
machine-readable research artifacts for URLs, identifying fields, and credential-like
fields. CI runs this check after tests.

Normal exceptions release in-memory objects. A forcefully terminated process relies on the
operating system to reclaim memory. Because this spike uses no temporary files, crash
cleanup is not otherwise required.

## People-detection decision and future protocol

People detection is **not yet evaluated**. It is not classified as unsuitable.

No candidate was adopted because this spike did not establish one that simultaneously had
verified package and weight licenses, weight provenance, bounded installed size,
reproducible versioning, local CPU execution, practical in-memory input, and acceptable
small/occluded-subject behavior. Adding a framework only to complete a phase would increase
dependency and privacy surface without trustworthy evidence.

A future candidate evaluation must:

1. record package, model, and weight licenses independently
2. record the immutable model source, checksum, model card, training provenance, and exact
   inference configuration
3. measure package and weight download/installed sizes
4. demonstrate network-disabled local inference and in-memory RGB-array input
5. test CPU execution at 512, 768, and 1024 px
6. manually annotate a bounded local subset for person count and normalized boxes
7. compare count agreement, confidence, box IoU, centroid distance, small-subject misses,
   partial occlusion, runtime, and process RSS
8. keep annotations, boxes, and detections local; publish aggregates only
9. reject identity, embeddings, demographics, emotion, and cross-image tracking

Issue #38 should remain blocked on that evidence rather than treating “not evaluated” as
“no person present” or selecting a model by popularity.

## Recommendations for Issue #18

The production contract should preserve source ownership while adding one bounded request
and one returned descriptor:

- requested maximum longest edge, with analyzer-family intent optional but not provider
  size names
- actual width and height
- content type
- encoded byte count when known
- stream valid only inside a context manager

Required lifecycle behavior:

- 512 px default for scalar color/luminance and saliency
- 768 px for palette/structural work
- 1024 px hard production ceiling until people-detection evidence justifies it
- 8 MB encoded-byte ceiling initially, configurable downward by source
- reject originals, archives, downloads, “largest” aliases, and decoded dimensions above
  the requested maximum
- require decoded dimensions to match provider-reported dimensions exactly after
  permitting only an EXIF-orientation width/height swap; classify and exclude mismatches
  from analysis
- HTTPS-only redirects, maximum three, with validation on every hop
- separate unavailable/permanent, authentication, rate-limit, and transient failures
- no URL, query, headers, cookies, credentials, or source identifiers in logs/errors
- in-memory stream ownership by default
- OS-managed temporary file only behind a context manager when a verified library requires
  a path
- delete temporary data before marking an asset complete
- allow a workflow to share one decoded preview among compatible analyzers during one
  asset pass, never across assets or runs by default

This is a recommendation, not a production implementation.

## Recommendations for Issue #35

Persist derived results using:

- scalar numeric: luminance, contrast, saturation, clipping, edge density, centroid,
  spread, and proxy values
- boolean: only deterministic threshold outcomes when the threshold/version is recorded
- text classification: model labels with explicit confidence and unknown handling
- structured JSON: compact palettes and normalized bounding boxes
- normalized coordinates in `[0, 1]`
- optional confidence only for probabilistic results
- method name/version and configuration version for every result
- model name/version/checksum/provenance for every model result
- analyzer version independent from model version

Do not persist raw histograms, saliency maps, segmentation maps, preview bytes, embeddings,
or per-pixel arrays. A compact palette of colors and proportions is sufficient.

## Recommendations for Issue #36

- conservative initial default: two workers
- explicit supported range: one to four until real RSS/network results exist
- progress: eligible, selected, completed, failed, unavailable, remaining, elapsed,
  per-asset rate, bytes transferred, and meaningful ETA
- retry transient network/rate-limit failures with bounded backoff
- do not automatically retry permanent missing/corrupt/original-rejected previews
- commit results and operational state at the asset boundary
- mark completion only after preview bytes and temporary resources are released
- share one decoded preview in a single asset pass for color, saliency, and compatible
  structural measurements
- run model analyzers separately when their preview size, dependency, or memory needs differ

Expected deterministic CPU throughput is provisionally 15–20 photographs/second for one
selected size on the benchmark machine. Real network throughput is unknown and will likely
set the end-to-end rate.

## Recommendations by analyzer issue

### Issue #37 — color and luminance

- preview: 512 px for scalar values; 768 px when palette proportions are required
- algorithm: Pillow + NumPy deterministic implementation
- memory: expected tens of MiB of transient arrays per worker; real increment unverified
- runtime: roughly 50–70 ms/image CPU from synthetic evidence
- readiness: ready for bounded real validation, then a focused first production analyzer
- failures: JPEG compression, tiny saturated regions, clipping thresholds, palette
  quantization, color-profile handling

### Issue #38 — people and subject placement

- preview: compare 512/768/1024; no selection yet
- model: none selected
- readiness: not yet evaluated
- failures to test: small/distant, occluded, edge-cropped, groups, faces without full-body
  detections, low confidence

### Issue #39 — composition and saliency

- preview: provisional 512 px for spectral-residual centroid/spread; 768 px for edge-based
  structure
- algorithm: deterministic spectral residual plus normalized geometry
- readiness: usable with caveats after real validation
- failures: uniform frames, repeated textures, bright borders, multiple salient regions,
  disagreement with human attention
- defer horizon, symmetry, negative space, leading lines, and visual-weight claims until
  individually validated

### Issue #40 — scene and environment

- preview: no empirical recommendation; begin future comparison at 512/768
- model: none selected
- readiness: not yet evaluated
- broad labels and segmentation coverage require confidence, provenance, and a small
  documented taxonomy

### Issue #41 — technical image structure

- preview: provisional 768 px for edge density and global contrast
- readiness: edge density/global contrast usable with caveats
- sharpness, motion blur, noise, depth of field, and subject-background separation:
  deferred because preview resizing/compression can dominate the signal
- never describe a preview proxy as original-file quality or focus diagnosis

## Measurements approved, caveated, and deferred

Ready for bounded real validation:

- mean/median luminance
- luminance spread and percentile contrast
- mean/median saturation
- colorfulness and warmth proxies
- highlight/shadow clipping estimates
- compact quantized palette and diversity

Usable only with caveats:

- spectral-residual saliency centroid/spread
- edge density
- preview-specific Laplacian sharpness proxy

Not yet evaluated:

- people/faces
- scene labels
- semantic segmentation/environment coverage

Deferred as currently unsuitable for production claims:

- original-file sharpness or autofocus diagnosis from a preview
- reliable motion-blur, noise, depth-of-field, and subject-background separation without
  stronger validation
- composition quality, aesthetic scores, mood, emotion, identity, and demographic inference

## Risks and limitations

- real preview-size stability is unverified
- exact SmugMug size-detail response shapes may require a narrow research-only parser update
- provider sizes may differ from requested edges
- embedded color profiles and provider processing may affect measurements
- RSS includes interpreter and loaded-library baseline, not only one image
- synthetic fixtures underrepresent photographic texture, compression, faces, crowds,
  low light, and complex scenes
- manual visual-category coverage is not yet recorded
- CPU and network extrapolations are machine- and source-dependent

## Reproduction

Install:

```console
python -m pip install -e ".[dev,research]"
```

Regenerate the committed aggregate-only synthetic result:

```console
python -m research.visual_preview.synthetic
```

Run the bounded real benchmark locally:

```powershell
$env:PPA_SMUGMUG_API_KEY = "your-api-key"
python -m research.visual_preview `
  --database jrp-import-test.sqlite3 `
  --sample-size 48 `
  --output research-output/visual-preview-raw-local.json `
  --aggregate-output research-output/visual-preview-aggregate.json
```

Both outputs are ignored. Review the local raw file, complete the local rubric, aggregate
manual category counts separately, and never add the raw file to Git.

Before committing:

```console
python scripts/check_research_cleanliness.py
python -m ruff check .
python -m ruff format --check .
python -m pytest
```

## Real execution status

Completed:

- deterministic selection of 48 real portfolio records
- aggregate metadata sample description
- one bounded 150 × 150 repository-thumbnail probe
- synthetic four-size benchmark
- cleanup and corrupt/oversized-input automated tests

Not completed because credentials were unavailable:

- official 256/512/768/1024 real preview resolution
- real bytes transferred and download/runtime measurements
- real-image stability
- redirect observations
- real peak-memory increment
- one/two/four-worker comparison
- local manual visual-category rubric

The reproduction command above is the remaining local validation step. Until its aggregate
results are reviewed, the recommendations in this note remain provisional.
