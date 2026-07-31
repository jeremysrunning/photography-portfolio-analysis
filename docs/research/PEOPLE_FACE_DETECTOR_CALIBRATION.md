# People and Face Detector Calibration

## Executive summary

Issue #38 remains blocked and its analyzer is not registered for production. On a fresh
47-image manually reviewed sample, no person configuration met the 90% accepted-count
consistency gate. Person retained evidence also showed an unacceptable obvious
false-positive pattern. A face configuration at 768 px met the 85% consistency and 0.75
median-IoU gates, but its high-plus-medium count-derived recall-like rate was only 62.2%.

The defensible outcome is **defer both detectors and investigate a replacement or revised
model strategy**. No production preview edge or thresholds are approved. This conclusion
does not lower a predeclared gate or treat 1024 px as ground truth.

## Existing blocked Issue #38 evidence

All 20 photographs completed at 512, 768, and 1024 px without acquisition or analysis
failures. No raw records were retained.

| Comparison | People count agreement | People median IoU | Face count agreement | Face median IoU |
|---|---:|---:|---:|---:|
| 512 vs 1024 | 70% | 0.9329 | 55% | 0.8360 |
| 768 vs 1024 | 80% | 0.9686 | 75% | 0.8909 |

The declared agreement gates were 80%/90% for people and 70%/85% for faces at
512/768 respectively. The result is evidence of resolution-sensitive counts, not evidence
that 1024 px is accurate or ground truth.

## Sample-selection method

The calibration utility selects 48 photographs by default from a new deterministic seed.
It groups photographs by five-year capture band, hashed recorded-camera value, and hashed
gallery placement, then takes a deterministic round-robin sample across groups. Hashes
exist only to stratify local selection and are not written to raw or aggregate output.

After preview decoding, the local reviewer records portrait/landscape representation and
the visual conditions in the rubric. A supplement of no more than 12 photographs is
permitted only when the deterministic sample lacks a required condition. Supplements and
their reason remain local; aggregate condition counts may be reported.

The run requested 48 photographs and produced 47 complete triplets. One provider response
was excluded for a decoded/reported dimension mismatch before analyzer execution. The
selected sample represented five five-year capture bands, six recorded-camera groups, and
45 gallery groups. Manual confidence was high for 28 images, medium for 11, and low for 8.

## Manual CSV schema and annotation confidence

The local CSV contained visible person/face counts; obvious person/face false-positive and
false-negative counts; small-subject, occlusion, and edge-crop flags; and human annotation
confidence (`high`, `medium`, or `low`). No row was discarded. Findings are reported for
all 47 rows, high-only rows, and high-plus-medium rows.

Explicit obvious-error counts describe retained baseline overlay evidence, including
unstarred low-confidence boxes. Alternative accepted thresholds have no box-by-box manual
matching, so their precision-like and recall-like values are labeled count-derived bounds;
they cannot expose simultaneous false positives and false negatives.

## Manual annotation rubric

For each full 1024 px local preview, the reviewer records only:

- visible person and visible face counts
- obvious person and face false-positive and false-negative counts for the displayed
  baseline overlay
- small-subject, occlusion, and edge-crop flags

Names, identity, demographics, emotion, age, gender, race or ethnicity, relationship,
candid-versus-posed labels, and aesthetic judgments are prohibited. Full previews,
overlays, local tokens, and raw annotations remain outside the repository and are deleted
after aggregate findings are produced.

## Models and exact versions

- NanoDet-m-plus-1.5x-416, OpenCV Zoo November 2022 artifact, SHA-256
  `4b82da9944b88577175ee23a459dce2e26e6e4be573def65b1055dc2d9720186`,
  Apache-2.0
- YuNet March 2023 artifact, SHA-256
  `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`,
  MIT
- OpenCV headless `4.13.0.92`, local CPU, one internal OpenCV thread

YuNet landmark columns are discarded inside the adapter and never enter calibration raw
records. No recognition or identity-capable model is packaged or loaded.

## Preview sizes

Every complete sample is evaluated at 512, 768, and 1024 px through the production bounded
preview lifecycle. A sample contributes to cross-resolution comparisons only when all
three previews and both detectors complete. Originals are never requested.

## Threshold and NMS search strategy

The declared matrix is:

- person retention: 0.15, 0.20, 0.25
- person accepted: 0.30, 0.35, 0.40, 0.45
- person NMS IoU: 0.50, 0.60, 0.70
- face retention: 0.30, 0.40, 0.50
- face accepted: 0.50, 0.60, 0.70
- face NMS IoU: 0.20, 0.30, 0.40

Search proceeds in stages: confidence behavior at current NMS; narrowing to candidates
that meet manual-accuracy requirements; NMS comparison only within those bands; final
cross-resolution comparison. Retention must not exceed acceptance. No single aggregate
score chooses a candidate.

Threshold-crossing buckets are fixed as follows:

- people: below 0.20; 0.20–0.30; 0.30–0.35; 0.35–0.50; 0.50–0.75; above 0.75
- faces: below 0.40; 0.40–0.50; 0.50–0.60; 0.60–0.75; above 0.75

Normalized box-area buckets are below 0.1%, 0.1–0.5%, 0.5–2%, 2–10%, and above 10%.
Face findings additionally report approximate pixel dimensions by preview edge.

## Decision rules

A people configuration requires at least 90% accepted-count agreement against the highest
evaluated edge, median matched IoU at least 0.85, strong obvious-case manual accuracy, no
unacceptable false-positive pattern, stable runtime/memory, and documented small-subject
limits.

A face configuration requires at least 85% accepted-count agreement, median matched IoU
at least 0.75, strong accuracy on obvious visible faces, no unacceptable false-positive
pattern, stable runtime/memory, and documented small-face and edge-crop limits.

Manual accuracy and cross-resolution consistency remain separate. When they conflict,
accuracy takes precedence and resolution sensitivity is disclosed. The conclusion must be
exactly one of: combined 768; combined 1024; class-specific preview sizes; production
people with faces deferred; or defer both.

## Accuracy findings

Baseline retained person evidence contained 305 obvious false positives and 20 obvious
false negatives against 237 visible people across 47 images: bounded manual precision-like
41.6% and recall-like 91.6%. High-plus-medium rows contained 189 false positives and 9
false negatives against 148 people (42.4%, 93.9%). High-only rows remained weak: 106
false positives and one false negative against 41 people (27.4%, 97.6%). The
false-positive pattern is unacceptable regardless of ambiguous crowd rows.

Person NMS 0.50 improved high-plus-medium count-derived precision-like behavior at 768 px
to 92.7%, but recall-like behavior was 68.2% and exact visible-count agreement 48.7%.
Raising acceptance to 0.45 produced 96.5% precision-like and 56.1% recall-like behavior.
NMS 0.70 moved the opposite direction (80.7%, 76.4% at acceptance 0.35). These are
tradeoffs, not a production solution.

Baseline retained face evidence contained 24 obvious false positives and 20 obvious false
negatives against 153 visible faces (84.7%, 86.9%). High-plus-medium rows contained 20 and
11 errors against 98 faces (81.3%, 88.8%); high-only rows contained 15 and one against 30
faces (65.9%, 96.7%). Ambiguous scenes therefore do not solely drive face false positives.

At 1024, face acceptance 0.50 gave the strongest balanced high-plus-medium count-derived
result (83.9% precision-like, 79.6% recall-like), but high-only precision-like behavior was
69.1%. Acceptance 0.60 at 768 raised high-plus-medium precision-like behavior to 91.0%
while reducing recall-like behavior to 62.2%. No candidate combined strong manual behavior
with required consistency.

## Cross-resolution consistency findings

No person candidate reached 90% accepted-count agreement at 768 relative to 1024. The best
observed value was 85.1% (acceptance 0.45, NMS 0.70), while its high-plus-medium recall-like
rate was only 57.4%. Acceptance 0.35 configurations reached 76.6–80.9%. Person geometry
was stable: baseline 768 median matched IoU was 0.9685, centroid distance 0.0040,
largest-box area difference 0.0011, and union-coverage difference 0.0018. Count instability,
not coordinate mapping, is the blocker.

Face acceptance 0.60 at 768 reached 85.1% all-row agreement and 92.3% agreement on the
high-plus-medium subset. Median matched IoU was 0.8744, centroid distance 0.0062,
largest-area difference 0.0003, and union-coverage difference 0.0003. Acceptance 0.50
improved recall but reduced all-row agreement to 72.3%. No 512 px face candidate passed.

## Confidence-threshold crossing analysis

Matched 768/1024 person confidence differed by a median 0.0104 at baseline, yet 31 accepted
detections were unmatched and only 46.8% of retained counts agreed. Person NMS materially
changed totals without producing 90% agreement. The failure combines duplicate survival,
unmatched detections, and threshold crossings rather than a coordinate defect.

Matched face confidence differed by a median 0.0187 at acceptance 0.60. Moving acceptance
from 0.50 to 0.60 raised 768/1024 agreement from 72.3% to 85.1% but reduced
high-plus-medium recall-like behavior from 70.4% to 62.2%. Face NMS 0.20, 0.30, and 0.40
produced effectively identical accepted totals, so duplicate suppression was not the
principal face issue.

## Subject-size analysis

Ten small-subject images contained 101 visible people with 120 obvious false positives and
15 false negatives (41.8%, 85.2%), versus 136 people with 185 and 5 errors in the other 37
images (41.5%, 96.3%). Small subjects materially increased person misses.

The ten images contained 57 visible faces with 8 false positives and 10 false negatives
(85.5%, 82.5%), versus 96 faces with 16 and 10 errors elsewhere (84.3%, 89.6%). Accepted
face evidence below 0.1% box area rose from 6 boxes at 512 to 30 at 768 and 61 at 1024 for
acceptance 0.50. Median accepted face boxes were approximately 29×41 px, 31×58 px, and
32×58 px respectively; provider aspect ratios make these aggregate dimensions approximate.

## Occlusion and edge-crop findings

Twenty-seven occlusion-positive images contained 217 people with 263 false positives and
16 false negatives (43.3%, 92.6%); 20 other images contained 20 people with 42 and 4
(27.6%, 80.0%). For faces the groups were 140 visible with 20/19 errors (85.8%, 86.4%)
and 13 visible with 4/1 (75.0%, 92.3%). Occlusion co-occurs with event complexity and does
not establish causation.

Twenty-six edge-crop-positive images contained 215 people with 265 false positives and 15
false negatives (43.0%, 93.0%); 21 other images contained 22 with 40 and 5 (29.8%, 77.3%).
Faces were 140 with 17/19 (87.7%, 86.4%) versus 13 with 7/1 (63.2%, 92.3%). Group sizes
and scene types differ greatly, so these percentages remain descriptive.

## Duplicate-detection and detector differences

The 305 obvious person false positives, 672 retained baseline person boxes, and strong NMS
effect support fragmentation/duplicate survival as a major person failure mode. The CSV
does not classify each false positive as a duplicate, so the research does not claim all
are duplicates. The baseline had 1.29 obvious person false positives per visible person.

Face errors were much smaller and insensitive to tested NMS, consistent with isolated
object or partial-head false positives and resolution-sensitive small faces. Person and
face behavior is not combined into one score.

## Runtime and memory

The real collection averaged 1.151 s preview acquisition, 1.0 ms normalization, 62.0 ms
person inference, and 20.7 ms face inference per preview on one Windows machine. It
downloaded 19,707,286 bytes across 47 complete triplets plus one partial attempt
(approximately 139 KB per acquired preview). A generated benchmark measured about
100.5 MiB process RSS. OpenCV occupied approximately 108.3 MiB and the two weights about
3.85 MiB. These are bounded observations, not portable guarantees.

## Privacy verification

Automated tests verify YuNet sentinel landmarks do not enter adapter output, analyzer
results, JSON, SQLite, or logs. Calibration raw output contains only local sample tokens,
normalized boxes, confidence, and raw ordering indexes. The aggregate evaluator emits no
tokens, identifiers, URLs, filenames, per-image rows, images, or credentials.

## Recommended production configuration

**Outcome 5: neither detector is ready for production.** No preview edge, retention
threshold, acceptance threshold, or NMS threshold is approved. Person detection fails the
count-consistency gate and has an unacceptable duplicate/false-positive pattern. Face
detection has a promising geometry-stable 768 px configuration but cannot simultaneously
meet the consistency gate and demonstrate strong bounded manual recall.

The smallest next step is a focused replacement-model or detector-strategy investigation
using a separate sample. Recalibrating these models repeatedly against these 47 rows would
overfit the bounded review.

## Rejected configurations

The provisional combined 768 px configuration with person acceptance 0.35/NMS 0.60 and
face acceptance 0.60/NMS 0.30 is not production-ready based on the original count gate.
It remains a baseline for diagnosis, not an approved configuration.

Combined 1024 is rejected because person failures remain and larger previews do not cure
the duplicate pattern. Split sizes are rejected because no person configuration passes and
the face tradeoff remains unresolved. Person-only scope is rejected because NanoDet is the
less production-ready component.

## Decision for Issue #38 scope

Do not resume the experimental production implementation. Keep `people-placement`
unregistered. Issue #38 requires an approved model-strategy change before coding resumes;
threshold-only changes to the current NanoDet/YuNet pair are insufficient.

## Reproduction instructions

Create a disposable database copy and a local directory outside the repository:

```powershell
python scripts/calibrate_people_face_detectors.py collect temporary.sqlite3 `
  $env:TEMP\ppa-issue-49-calibration --sample-size 48
```

Review full previews and overlays locally, then complete `annotations.csv`. An asterisk
after an overlay confidence marks accepted baseline evidence. Evaluate all declared
candidates into a local aggregate file:

```powershell
python scripts/calibrate_people_face_detectors.py evaluate `
  $env:TEMP\ppa-issue-49-calibration `
  --output $env:TEMP\ppa-issue-49-calibration-aggregate.json
```

Only reviewed aggregate findings belong in this document. Delete both the disposable
database and local calibration directory after the conclusions are recorded.

## Known limitations

The local rubric is bounded and descriptive, not benchmark-grade ground truth. Box
detection does not establish identity, person–face pairing, pose, body framing, or
segmented pixel coverage. Provider rendering, small subjects, occlusion, edge crops, and
the selected sample can affect results.
