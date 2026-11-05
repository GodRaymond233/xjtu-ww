# Agent Instructions

## Python

- When running Python commands in this repository, use the local virtual environment if it exists.
- On Windows/PowerShell, prefer `.\.venv\Scripts\python.exe` when present.
- On POSIX shells, prefer `./.venv/bin/python` when present.
- Fall back to `python` only when no local `.venv` interpreter exists.
- Prefer invoking the interpreter directly, for example `.\.venv\Scripts\python.exe -m pytest`, instead of relying on shell activation.

## Builds

- Use GitHub Actions for full portable builds by default. Run focused tests and UI checks locally.
- Build a complete package locally only when explicitly requested or when diagnosing a packaging issue that needs local reproduction.
- Pushes to `workshop-preserved` and pull requests run tests. Dispatch `Windows Portable` for a preview ZIP; manual runs do not publish releases.
- Create and push a version tag only when the user requests a release. Tag builds must pass tests and the portable startup check before publishing.
