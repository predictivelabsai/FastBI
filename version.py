"""App version from the root VERSION file (semver + optional release date)."""
from pathlib import Path

_ROOT = Path(__file__).parent


def read_version() -> tuple[str, str]:
    lines = [ln.strip() for ln in (_ROOT / "VERSION").read_text(encoding="utf-8").splitlines() if ln.strip()]
    version = lines[0] if lines else "0.0.0"
    date = lines[1] if len(lines) > 1 else ""
    return version, date


def version_label() -> str:
    version, date = read_version()
    return f"v{version} · {date}" if date else f"v{version}"
