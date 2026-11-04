"""The build itself: the artifacts must contain what they claim.

The build re-opens what it wrote, so these tests are about the *whole*
pipeline: one temp build is shared by every test in the module (it takes a few
seconds), and each test then asserts one property of the result.
"""

from __future__ import annotations

import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from sovngarde import glyphs
from sovngarde.build import MOVIES, build
from sovngarde.swf import Movie
from sovngarde.targets import SwfTarget, TtfTarget
from tests.conftest import Artifacts

ADDED = sorted(cp for cp, _ in glyphs.RECIPES.items())


def test_build_reports_every_expected_target(artifacts: Artifacts) -> None:
    reports = artifacts.reports
    assert len(reports) == len(MOVIES) + 4, sorted(reports)


def test_every_movie_gains_every_missing_recipe(artifacts: Artifacts, upstream: Path) -> None:
    out = artifacts.out
    for filename, _name in MOVIES:
        source = SwfTarget.load(
            str(upstream / "mod" / "Data" / "Interface" / filename), "src", 20482.4
        )
        patched = SwfTarget.load(str(out / "mod" / "Data" / "Interface" / filename), "dst", 20482.4)
        for codepoint in ADDED:
            assert patched.has(codepoint) == (source.has(codepoint) or codepoint in ADDED), (
                f"{filename}: U+{codepoint:04X}"
            )
        for codepoint in source.codes():
            assert source.glyph(codepoint) == patched.glyph(codepoint), (
                f"{filename}: existing U+{codepoint:04X} was modified"
            )


def test_movies_only_change_inside_the_font_tag(artifacts: Artifacts, upstream: Path) -> None:
    out = artifacts.out
    for filename, _name in MOVIES:
        source = Movie.load((upstream / "mod" / "Data" / "Interface" / filename).read_bytes())
        patched = Movie.load((out / "mod" / "Data" / "Interface" / filename).read_bytes())
        old_tag = source.fonts()[0][0]
        prefix = source.body[: old_tag.offset]
        tail = source.body[old_tag.offset + old_tag.size :]
        assert patched.body[: len(prefix)] == prefix, filename
        assert patched.body[-len(tail) :] == tail, filename
        new_tag = patched.fonts()[0][0]
        assert new_tag.offset == old_tag.offset, filename
        assert new_tag.code == old_tag.code, filename


def test_patched_movies_re_parse_byte_identically(artifacts: Artifacts) -> None:
    """A codec that cannot reproduce its own output is not understood."""
    out = artifacts.out
    for filename, _name in MOVIES:
        from sovngarde.swf import encode_define_font

        movie = Movie.load((out / "mod" / "Data" / "Interface" / filename).read_bytes())
        tag, font = movie.fonts()[0]
        assert encode_define_font(font, []) == tag.data, filename


def test_desktop_fonts_gain_the_glyphs_with_an_advance(artifacts: Artifacts) -> None:
    out = artifacts.out
    for path in sorted(out.glob("desktop/**/*.ttf")):
        font = TTFont(str(path))
        cmap = font.getBestCmap()
        assert cmap is not None
        added = [cp for cp in ADDED if cp in cmap]
        assert len(added) >= len(ADDED) - 3, f"{path.name}: only {len(added)} added"
        for codepoint in added:
            name = cmap[codepoint]
            assert font["hmtx"][name][0] > 0, f"{path.name}: U+{codepoint:04X} has no advance"
            glyph = font["glyf"][name]
            glyph.expand(font["glyf"])
            assert glyph.numberOfContours > 0, f"{path.name}: U+{codepoint:04X} is empty"
        assert len(font.getGlyphOrder()) == font["maxp"].numGlyphs, path.name


def test_desktop_fonts_kept_their_original_glyphs(artifacts: Artifacts, upstream: Path) -> None:
    out = artifacts.out
    source = TTFont(str(upstream / "desktop" / "Sovngarde" / "Sovngarde Bold.ttf"))
    patched = TTFont(str(out / "desktop" / "Sovngarde" / "Sovngarde Bold.ttf"))
    source_cmap = source.getBestCmap()
    patched_cmap = patched.getBestCmap()
    assert source_cmap is not None and patched_cmap is not None
    for codepoint, name in source_cmap.items():
        assert patched_cmap.get(codepoint) == name, hex(codepoint)
        original = source["glyf"][name]
        original.expand(source["glyf"])
        current = patched["glyf"][name]
        current.expand(patched["glyf"])
        if original.numberOfContours > 0:  # empty glyphs (space) carry no outlines
            assert list(original.coordinates) == list(current.coordinates), hex(codepoint)
            assert list(original.flags) == list(current.flags), hex(codepoint)
        assert source["hmtx"][name] == patched["hmtx"][name], hex(codepoint)


def test_building_twice_is_idempotent(artifacts: Artifacts, upstream: Path, tmp_path: Path) -> None:
    """Rebuilding from the same upstream must reproduce the same bytes."""
    out = artifacts.out
    again = tmp_path / "again"
    build(upstream, again)
    for path in sorted(out.rglob("*")):
        if path.is_file():
            other = again / path.relative_to(out)
            assert path.read_bytes() == other.read_bytes(), path.name


def test_fomod_preview_is_packaged_and_referenced() -> None:
    """The wizard's image must be inside the zip: the shared gate cannot see it.

    moduleImage and the plugin's <image> are read by the installer from the
    archive, so a path that is not in the spec's file list means a wizard with a
    broken picture - exactly what a hand-written ModuleConfig gets wrong.
    """
    data = tomllib.loads((ROOT / "fomod-package.toml").read_text())
    packaged = {entry["dest"] for entry in data["files"]}
    tree = ET.parse(ROOT / "fomod" / "ModuleConfig.xml")
    images = [node.get("path") for node in tree.findall(".//moduleImage")]
    images += [node.get("path") for node in tree.findall(".//plugin//image")]
    assert images, "the wizard references no preview image"
    assert len(images) == 2, images  # the module banner and the option's image
    for path in images:
        assert path, "an empty image path renders nothing"
        assert path in packaged, f"{path!r} is referenced but not packaged"
        assert (ROOT / path).is_file(), f"{path!r} is packaged but missing on disk"


def test_add_refuses_to_overwrite_an_existing_glyph(upstream: Path) -> None:
    target = TtfTarget.load(str(upstream / "desktop" / "Sovngarde" / "Sovngarde Bold.ttf"), "bold")
    with pytest.raises(ValueError, match="already exists"):
        target.add(0x41, [[(0.0, 0.0, True)]], 0.5)


SPECS = ("fomod-package.toml", "fomod-package-desktop.toml")
ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("spec", SPECS)
def test_package_spec_points_at_files_the_build_writes(artifacts: Artifacts, spec: str) -> None:
    """The packager only takes an explicit file list, so every entry must exist.

    This is the drift check for the packaging convention: a renamed build output
    or a typo in the spec must fail here rather than in CI's packaging step.
    """
    data = tomllib.loads((ROOT / spec).read_text())
    for entry in data["files"]:
        source = entry["src"]
        if source.startswith("dist/"):
            candidate = artifacts.out / Path(source).relative_to("dist")
        else:
            candidate = ROOT / source
        assert candidate.is_file(), f"{spec}: {source} is missing"
    version = (ROOT / data["version"]["file"]).read_text().strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version
    assert data["zip_name"].format(version=version).endswith(".zip")


def test_fomod_moduleconfig_yields_a_plugin() -> None:
    """Mirror of the shared gate's rule, so a local run catches it first.

    An <optionalFileGroups> with no <plugin> makes Amethyst's wizard resolve
    `selected_plugin or first_plugin` to None and crash on .description.
    """
    tree = ET.parse(ROOT / "fomod" / "ModuleConfig.xml")
    plugins = tree.findall(".//optionalFileGroups//plugin")
    assert plugins, "the FOMOD wizard needs at least one <plugin>"
    assert plugins[0].findtext("description", "").strip(), "the plugin needs a description"
    sources = {node.get("name") for node in tree.findall(".//sourceFiles/source")}
    assert sources, "no pattern would copy anything"
