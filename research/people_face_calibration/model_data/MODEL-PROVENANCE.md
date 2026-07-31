# Research-only people-placement model artifacts

These artifacts reproduce Issue #49 calibration. That research rejected both evaluated
detector strategies for production. They are not expected production dependencies or an
approved Issue #38 configuration.

These artifacts are package resources. They are loaded locally, require no network access,
and are verified by SHA-256 before OpenCV initializes a network.

## NanoDet-m-plus-1.5x 416

- File: `object_detection_nanodet_2022nov.onnx`
- Size: 3,800,954 bytes
- SHA-256: `4b82da9944b88577175ee23a459dce2e26e6e4be573def65b1055dc2d9720186`
- Immutable source commit:
  `opencv/opencv_zoo@510899a2a0adb8c25957915fd030d66dbd553919`
- Source path: `models/object_detection_nanodet/object_detection_nanodet_2022nov.onnx`
- License: Apache-2.0; the full text is in `NANODET-LICENSE.txt`
- Disclosed training/evaluation basis: COCO object classes; this application reads only
  class index 0 (`person`)

OpenCV Zoo permits use and redistribution under Apache-2.0, including commercial use
subject to that license. The model produces class scores and boxes; the application does
not load tracking, pose, segmentation, or recognition models.

## YuNet 2023 March

- File: `face_detection_yunet_2023mar.onnx`
- Size: 232,589 bytes
- SHA-256: `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`
- Immutable source commit:
  `opencv/opencv_zoo@f12e12798e8314f7c074a6656816c048dcc95b7a`
- Source path: `models/face_detection_yunet/face_detection_yunet_2023mar.onnx`
- License: MIT; the full text is in `YUNET-LICENSE.txt`
- Disclosed training/evaluation basis: WIDER Face

The MIT terms permit use and redistribution, including commercial use. YuNet emits five
landmark pairs internally. The adapter copies only box coordinates and score into its
narrow output and releases the raw matrix; landmarks never enter the analyzer or durable
result contract. No SFace or other identity-capable model is packaged.

The source datasets' own terms govern acquisition and redistribution of those datasets.
No training images or dataset records are included here.
