from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    tomllib = None  # type: ignore[assignment]



def _read_pyproject_version(pyproject_path: Path) -> str | None:
    if tomllib is not None:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        version = data.get("project", {}).get("version")
        return str(version) if version else None

    in_project_section = False
    for line in pyproject_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "[project]":
            in_project_section = True
            continue
        if in_project_section and stripped.startswith("["):
            return None
        if in_project_section and stripped.startswith("version"):
            _key, _separator, raw_value = stripped.partition("=")
            return raw_value.strip().strip('"') or None
    return None


def get_app_version() -> str:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    version = _read_pyproject_version(pyproject_path)
    if version:
        return version
    return "0.0.0+unknown"


APP_VERSION = get_app_version()
APP_VERSION_LABEL = f"v{APP_VERSION}"


__all__ = ["APP_VERSION", "APP_VERSION_LABEL", "get_app_version"]
