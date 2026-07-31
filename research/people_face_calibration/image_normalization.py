"""Shared deterministic conversion of decoded previews to encoded-sRGB arrays."""

from __future__ import annotations

import numpy as np
from PIL import Image


def normalized_srgb_array(image: Image.Image) -> np.ndarray:
    """Return an owned uint8 RGB array using the production preview conventions."""
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
