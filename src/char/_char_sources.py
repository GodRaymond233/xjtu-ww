"""Build-time snapshot of built-in character sources.

The compiled portable build ships ``char_sources/<Class>.py`` data files next
to the executable instead of importable ``src/char/*.py`` modules. This module
resolves a bundled class name to its snapshot file. In a source checkout the
snapshot directory may be absent; callers fall back to ``inspect.getsourcefile``.
"""

from pathlib import Path

CHAR_SOURCES_DIR = Path(__file__).resolve().parent.parent.parent / "char_sources"


def char_source_path(class_name):
    """Return the bundled source snapshot for a character class, or None."""
    candidate = CHAR_SOURCES_DIR / f"{class_name}.py"
    return candidate if candidate.is_file() else None


def read_char_source(class_name):
    path = char_source_path(class_name)
    if path is None:
        return None
    return path.read_text(encoding="utf-8")
