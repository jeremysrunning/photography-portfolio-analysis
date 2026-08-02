"""Shared rendered-preview sRGB normalization for deterministic analyzers."""

from __future__ import annotations

import numpy as np
from PIL import Image


def normalized_srgb(image: Image.Image) -> np.ndarray:
    """Return an owned uint8 RGB array using the versioned preview convention."""
    if image.width < 1 or image.height < 1:
        raise ValueError("preview dimensions must be positive")
    if image.mode in {"I;16", "I;16L", "I;16B", "I;16N"}:
        values = np.asarray(image, dtype=np.float64)
        gray = np.rint(np.clip(values, 0, 65535) * (255 / 65535)).astype(np.uint8)
        return np.repeat(gray[..., None], 3, axis=2)
    if image.mode in {"I", "F"}:
        raise ValueError(f"unsupported preview numeric mode: {image.mode}")
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (128, 128, 128, 255))
        normalized = Image.alpha_composite(background, rgba).convert("RGB")
    else:
        normalized = image.convert("RGB")
    return np.asarray(normalized, dtype=np.uint8).copy()


def relative_linear_luminance(image: Image.Image) -> np.ndarray:
    """Return float64 linear-sRGB relative luminance in the inclusive unit interval."""
    encoded = normalized_srgb(image).astype(np.float64) / 255.0
    linear = np.where(
        encoded <= 0.04045,
        encoded / 12.92,
        ((encoded + 0.055) / 1.055) ** 2.4,
    )
    return linear[..., 0] * 0.2126 + linear[..., 1] * 0.7152 + linear[..., 2] * 0.0722
