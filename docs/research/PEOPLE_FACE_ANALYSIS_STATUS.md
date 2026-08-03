# People and Face Analysis Status

## Complete

- Issue #18 established bounded, temporary preview access and cleanup.
- Issues #35 and #36 established source-agnostic visual-result persistence and resumable
  analyzer orchestration.
- Issue #49 evaluated NanoDet and YuNet configurations on a bounded, manually reviewed
  sample. The evaluated configurations did not satisfy the approved production gates.
- Issue #51 defined an ordered replacement-detector preflight. None of its approved
  candidates cleared licensing requirements, so no candidate advanced to implementation.

## Blocked

Issue #38 remains open and blocked. No production person detector, face detector, preview
size, threshold, model artifact, runtime, or analyzer configuration is approved. NanoDet
and YuNet are retained only as research evidence and are not expected production detectors.

## Research remaining

A future, separately approved research issue would need to identify a candidate with
verified code and model-weight licensing, redistribution and commercial-use rights,
immutable provenance, reproducible offline packaging, acceptable privacy boundaries, and
bounded CPU behavior. A surviving candidate would then require calibration and one frozen
blind holdout against the existing accuracy and cross-resolution gates.

No additional detector search is authorized by the current issue state.

## Unblock event

Issue #38 may resume only after the project explicitly approves a detector candidate that
passes documentary preflight and blind technical validation without lowering the existing
production gates. Research code must remain isolated until that approval exists.

## Downstream dependencies

- Issue #39 completed independently and uses deterministic saliency measurements only. It
  consumes no people, face, object, or semantic-subject detections. Any future people-aware
  enhancement requires a separate issue after Issue #38 is unblocked.
- Issue #41 completed independently with deterministic preview-structure measurements.
- Issue #42 completed independently. Its visual-habits report presents people/face
  analysis as unavailable until persisted production results from Issue #38 exist.
- Issue #40 remains independently blocked by its own model-governance requirements.
