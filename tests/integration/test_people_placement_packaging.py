"""Distribution and offline inference checks for bundled detector artifacts."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from importlib import resources

from PIL import Image

from research.people_face_calibration.analysis import PeoplePlacementAnalyzer
from research.people_face_calibration.detectors import (
    MODEL_PACKAGE,
    NANODET_FILE,
    NANODET_SHA256,
    YUNET_FILE,
    YUNET_SHA256,
)


def test_bundled_model_resources_have_exact_identity_and_licenses() -> None:
    package = resources.files(MODEL_PACKAGE)
    expected = {
        NANODET_FILE: (3_800_954, NANODET_SHA256),
        YUNET_FILE: (232_589, YUNET_SHA256),
    }
    for name, (size, digest) in expected.items():
        content = package.joinpath(name).read_bytes()
        assert len(content) == size
        assert hashlib.sha256(content).hexdigest() == digest
        assert not content.startswith(b"version https://git-lfs.github.com/spec/v1")
    assert "Apache License" in package.joinpath("NANODET-LICENSE.txt").read_text()
    assert "MIT License" in package.joinpath("YUNET-LICENSE.txt").read_text()


def test_research_models_run_offline_without_a_separate_cache(tmp_path) -> None:
    results = PeoplePlacementAnalyzer().analyze(
        None,
        Image.new("RGB", (64, 48), "white"),
        None,  # type: ignore[arg-type]
    )

    assert {result.name: result.value for result in results}["person_count"] == 0
    assert not (tmp_path / "model_cache").exists()


def test_production_wheel_excludes_experimental_models(tmp_path) -> None:
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheel_dir.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        for filename in (
            NANODET_FILE,
            YUNET_FILE,
            "NANODET-LICENSE.txt",
            "YUNET-LICENSE.txt",
            "MODEL-PROVENANCE.md",
        ):
            assert not any(name.endswith(filename) for name in names)
