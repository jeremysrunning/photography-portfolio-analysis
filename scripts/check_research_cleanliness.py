"""Reject image content and identifying raw benchmark artifacts from Git."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES = {
    ".avif",
    ".bmp",
    ".db",
    ".gif",
    ".heic",
    ".heif",
    ".jpeg",
    ".jpg",
    ".png",
    ".sqlite",
    ".sqlite3",
    ".tif",
    ".tiff",
    ".webp",
}
MACHINE_READABLE = {".csv", ".json", ".jsonl", ".ndjson"}
IDENTIFYING_FIELDS = re.compile(
    r"\b(asset|gallery|source|file(?:name)?|preview)_?(id|key|name|url|uri)\b",
    re.IGNORECASE,
)
URL = re.compile(r"https?://", re.IGNORECASE)
CREDENTIAL = re.compile(
    r"(api[_-]?key|authorization|cookie|access[_-]?token|signed[_-]?url)",
    re.IGNORECASE,
)


def tracked_files() -> tuple[Path, ...]:
    """Return repository-relative files known to Git."""
    output = subprocess.check_output(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    )
    return tuple(Path(line) for line in output.splitlines() if line)


def violations(paths: tuple[Path, ...]) -> tuple[str, ...]:
    """Return deterministic cleanliness violations."""
    found: list[str] = []
    for relative in paths:
        suffix = relative.suffix.casefold()
        if suffix in FORBIDDEN_SUFFIXES:
            found.append(f"tracked image or database file: {relative.as_posix()}")
            continue
        if relative.parts[:2] == ("docs", "research") and suffix in MACHINE_READABLE:
            text = (ROOT / relative).read_text(encoding="utf-8")
            if URL.search(text):
                found.append(f"URL-bearing research data: {relative.as_posix()}")
            if IDENTIFYING_FIELDS.search(text):
                found.append(f"identifying research field: {relative.as_posix()}")
            if CREDENTIAL.search(text):
                found.append(f"credential-like research field: {relative.as_posix()}")
    return tuple(found)


def main() -> int:
    """Run the repository cleanliness check."""
    found = violations(tracked_files())
    if found:
        for item in found:
            print(item)
        return 1
    print("Research artifact cleanliness check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
