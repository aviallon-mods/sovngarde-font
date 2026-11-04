"""Shared fixtures: the upstream fonts the whole test suite is written against."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sovngarde.build import BuildReport, build

UPSTREAM = Path(__file__).resolve().parent.parent / "upstream"

MOVIES = (
    "fonts_sovngarde.swf",
    "fonts_sovngardeconsole.swf",
    "fonts_drukaatieburti.swf",
)


@dataclass
class Artifacts:
    """What a full build produced: the output tree and the per-target reports."""

    out: Path
    reports: dict[str, BuildReport] = field(default_factory=dict)

    def movie(self, filename: str) -> Path:
        return self.out / "mod" / "Data" / "Interface" / filename


@pytest.fixture(scope="session")
def upstream() -> Path:
    if not UPSTREAM.is_dir():  # pragma: no cover - defensive
        pytest.skip(f"upstream fonts are missing at {UPSTREAM}")
    return UPSTREAM


@pytest.fixture(scope="session")
def movie_paths(upstream: Path) -> list[Path]:
    return [upstream / "mod" / "Data" / "Interface" / name for name in MOVIES]


@pytest.fixture(scope="session")
def bold_ttf(upstream: Path) -> Path:
    return upstream / "desktop" / "Sovngarde" / "Sovngarde Bold.ttf"


@pytest.fixture(scope="session")
def artifacts(upstream: Path, tmp_path_factory: pytest.TempPathFactory) -> Artifacts:
    """One full build, shared by every test module (it takes a few seconds)."""
    out = tmp_path_factory.mktemp("dist")
    reports = build(upstream, out)
    return Artifacts(out, {report.artifact: report for report in reports})
