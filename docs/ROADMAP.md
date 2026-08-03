# Roadmap

The goal of this project is not to score photographs.

The goal is to help photographers discover patterns within their own body of work.

---

# Phase 1 — Website Gallery Crawler

Build a source capable of analyzing public photography galleries.

### Foundation status

Completed:

- Python package and CLI foundation
- normalized portfolio data model
- gallery source abstraction
- public SmugMug album and image-reference discovery
- SQLite storage abstraction and implementation
- structured logging and automated tests
- saved-dataset inspection command
- source-agnostic metadata baseline report
- resumable, batched public EXIF enrichment
- source-agnostic equipment and exposure report
- source-agnostic timeline habits report
- bounded production preview lifecycle
- resumable visual-analysis persistence and orchestration
- deterministic color and luminance visual analysis
- deterministic composition and saliency visual analysis
- deterministic preview-structure visual analysis
- deterministic visual-habits reporting over persisted production measurements
- normalized and persisted typed aperture, exact exposure time, ISO, exact exposure
  compensation, and flash evidence
- bounded NanoDet/YuNet calibration research and replacement-detector documentary research

Next:

- Issue #8: measure explicit EXIF missingness after typed exposure metadata is available
- Issue #12: normalize source-reported dimensions and report recorded orientation and
  exact aspect ratios
- Issue #14: extend equipment reporting with explicit aliases and deterministic segments
- Issue #16: compose and render the existing report models as unified Markdown
- Issue #17: render that approved composition as self-contained accessible HTML

Deferred:

- Issue #20 photographer self-assessment remains deferred until Issues #13, #12, and #16
  provide a concrete, evidence-aware comparison consumer.

Blocked:

- Issue #38 people and subject-placement analysis has no approved production detector.
  Issue #49 rejected the evaluated NanoDet/YuNet configurations against the declared
  production gates, and Issue #51 found no replacement candidate that cleared documentary
  licensing and project requirements. Resume only after a newly approved candidate passes
  licensing, provenance, reproducibility, packaging, privacy, and blind technical gates.
- Issue #40 scene and environment classification has no approved model artifact. The
  reviewed candidates stopped at the model-weight license gate; no later governance or
  technical gate has been evaluated.

Issues #39, #41, and #42 completed independently of the blocked semantic analyzers. The
visual-habits report explicitly presents people/face and scene/environment families as
unavailable rather than inferring negative classifications.

### Goals

- Crawl gallery structure
- Discover albums and images
- Extract available metadata
- Analyze web-sized previews in memory
- Store normalized metadata and derived measurements
- Generate an initial portfolio report

### Principles

- Do not permanently store original images.
- Store metadata and derived measurements only.
- Keep source-specific logic isolated from analysis.

---

# Phase 2 — Core Analytics

Generate reports describing measurable characteristics of a portfolio.

Examples include:

- Equipment habits
- Lens usage
- Exposure habits
- Time-of-day trends
- Orientation preferences
- Color signature
- Subject placement

---

# Phase 3 — Computer Vision

Expand analysis using computer vision techniques.

Potential areas include:

- Face detection
- People counting
- Visual complexity
- Scene classification
- Composition analysis
- Motion estimation

People counting and face detection remain research questions, not planned production
capabilities, until Issue #38's blocker is resolved.

---

# Phase 4 — Portfolio Insights

Combine measurements into meaningful findings.

Examples:

- How has the photographer's style evolved?
- What habits appear consistently?
- Which assumptions about their work are confirmed or challenged?
- How does their self-perception compare to the evidence?

---

# Future Sources

The analysis engine should remain independent of portfolio source.

Potential sources include:

- SmugMug
- Lightroom Classic
- Flickr
- Local folders
- Capture One
- Google Photos

---

# Long-Term Vision

A photographer should finish reading their report having learned something genuinely new about their own work.

The project succeeds when it encourages self-discovery rather than evaluation.
