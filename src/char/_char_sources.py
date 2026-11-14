"""Resolve current checkout sources, falling back to bundled build snapshots."""

from pathlib import Path

CHAR_SOURCES_DIR = Path(__file__).resolve().parent.parent.parent / "char_sources"
CHAR_SOURCE_DIR = Path(__file__).resolve().parent


def char_source_path(class_name):
    """Prefer the actual source module over a possibly stale bundled snapshot."""
    candidate = CHAR_SOURCE_DIR / f"{class_name}.py"
    if candidate.is_file():
        return candidate
    candidate = CHAR_SOURCES_DIR / f"{class_name}.py"
    return candidate if candidate.is_file() else None


def read_char_source(class_name):
    path = char_source_path(class_name)
    if path is None:
        return None
    return path.read_text(encoding="utf-8")
