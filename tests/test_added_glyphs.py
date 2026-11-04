"""Acceptance tests for the glyphs this project adds.

The rest of the suite checks the codec and the build mechanics; these check the
*content* the user gets.  They exist because a review showed that seven
mutations of the added geometry - wrong scale, zero advance, wrong fill index,
wrong hmtx side bearing, wrong cmap subtable, a translated dash - all passed the
earlier suite: everything only asserted that a glyph was "present and
non-empty".

Two families of assertion:

* per-recipe geometry (the em dash is the hyphen's bar at the hyphen's height,
  the ellipsis is three periods at the period's own pitch, the superscripts
  reach the cap height, ...);
* cross-target agreement: the same codepoint must have the same outline and the
  same advance in the game's movie and in the desktop face, in em units, which
  is what catches a scale applied twice in one of the two writers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fontTools.ttLib import TTFont

from sovngarde import glyphs
from sovngarde.geometry import Glyph, glyph_bbox
from sovngarde.swf import Movie
from sovngarde.targets import SwfTarget, TtfTarget
from tests.conftest import Artifacts

#: the movies this project patches, with the em size measured for each
MOVIES = {"fonts_sovngarde.swf": 20482.4, "fonts_sovngardeconsole.swf": 28658.9}
#: codepoints this project adds (the two "already present" recipes are excluded)
ADDED = sorted(cp for cp in glyphs.RECIPES if cp not in (0x00B1, 0x00F7))

movie_names = pytest.mark.parametrize("filename", sorted(MOVIES))


@pytest.fixture
def movie(artifacts: Artifacts, filename: str) -> SwfTarget:
    return SwfTarget.load(str(artifacts.movie(filename)), filename, MOVIES[filename])


@pytest.fixture(scope="module")
def desktop(artifacts: Artifacts) -> TtfTarget:
    path = artifacts.out / "desktop" / "Sovngarde" / "Sovngarde Bold.ttf"
    return TtfTarget.load(str(path), "Bold")


@movie_names
def test_dashes_are_the_hyphen_bar_at_the_hyphen_height(movie: SwfTarget) -> None:
    hyphen = movie.glyph(0x2D)
    hx0, hy0, _, hy1 = glyph_bbox(hyphen)
    assert hx0 > 0, "the hyphen must keep a side bearing for this test to mean anything"
    for codepoint, advance in ((0x2013, 0.5), (0x2014, 1.0)):
        x0, y0, x1, y1 = glyph_bbox(movie.glyph(codepoint))
        assert movie.advance(codepoint) == pytest.approx(advance, abs=0.005)
        assert x0 == pytest.approx(hx0, abs=0.005), "left bearing must match the hyphen"
        assert x1 == pytest.approx(advance - hx0, abs=0.01), "right bearing must mirror it"
        assert y0 == pytest.approx(hy0, abs=0.003), "bar must stay at the hyphen's height"
        assert y1 == pytest.approx(hy1, abs=0.003), "bar must keep the hyphen's thickness"


@movie_names
def test_ellipsis_is_three_periods_at_the_period_pitch(movie: SwfTarget) -> None:
    period = movie.glyph(0x2E)
    pitch = movie.advance(0x2E)
    px0, py0, px1, py1 = glyph_bbox(period)
    glyph = movie.glyph(0x2026)
    assert len(glyph) == 3, "the ellipsis must be three separate dots"
    assert movie.advance(0x2026) == pytest.approx(3 * pitch, abs=0.005)
    for index, contour in enumerate(glyph):
        x0, y0, x1, y1 = glyph_bbox([contour])
        offset = index * pitch
        assert x0 == pytest.approx(px0 + offset, abs=0.005), f"dot {index}"
        assert x1 == pytest.approx(px1 + offset, abs=0.005), f"dot {index}"
        assert y0 == pytest.approx(py0, abs=0.003), f"dot {index}"
        assert y1 == pytest.approx(py1, abs=0.003), f"dot {index}"


@movie_names
def test_superscripts_reach_the_cap_height(movie: SwfTarget, desktop: TtfTarget) -> None:
    cap_height = desktop.font["OS/2"].sCapHeight / desktop.em
    for codepoint in (0x00B9, 0x00B2, 0x00B3):
        _, y0, _, y1 = glyph_bbox(movie.glyph(codepoint))
        assert y1 == pytest.approx(cap_height, abs=0.02), hex(codepoint)
        assert y1 - y0 == pytest.approx(glyphs.SUPERSCRIPT_HEIGHT, abs=0.02), hex(codepoint)
        assert movie.advance(codepoint) > 0.1


@movie_names
def test_circled_marks_are_rings_of_the_reference_size(movie: SwfTarget) -> None:
    for codepoint in (0x00A9, 0x00AE):
        contours = movie.glyph(codepoint)
        assert len(contours) >= 3, "ring (outer + counter) plus the letter"
        x0, y0, x1, y1 = glyph_bbox([contours[0]])
        assert x1 - x0 == pytest.approx(glyphs.CIRCLED_DIAMETER, abs=0.02), hex(codepoint)
        assert y1 - y0 == pytest.approx(glyphs.CIRCLED_DIAMETER, abs=0.02), hex(codepoint)
        assert (y0 + y1) / 2 == pytest.approx(0.35, abs=0.03), hex(codepoint)


@movie_names
def test_multiply_matches_the_plus_box(movie: SwfTarget) -> None:
    plus = glyph_bbox(movie.glyph(0x2B))
    times = glyph_bbox(movie.glyph(0x00D7))
    assert (times[2] - times[0]) == pytest.approx(times[3] - times[1], abs=0.02), "square"
    assert 0.30 <= times[2] - times[0] <= 0.50, "a cross the size of the font's '+'"
    assert (times[1] + times[3]) / 2 == pytest.approx(glyphs.MATH_AXIS, abs=0.03)
    assert times[2] - times[0] <= (plus[2] - plus[0]) + 0.12


@movie_names
def test_relational_signs_extend_their_base_glyph(movie: SwfTarget) -> None:
    for codepoint, base in ((0x2260, 0x3D), (0x2264, 0x3C), (0x2265, 0x3E)):
        assert len(movie.glyph(codepoint)) > len(movie.glyph(base)), hex(codepoint)
        assert movie.advance(codepoint) == pytest.approx(movie.advance(base), abs=0.005)


def test_every_added_glyph_agrees_between_movie_and_desktop(
    artifacts: Artifacts, desktop: TtfTarget
) -> None:
    """The same codepoint must be the same shape in both targets, in em units.

    A scale applied twice in one of the two writers, a missing advance, or a
    glyph written into the wrong table all show up here.
    """
    for filename, em in MOVIES.items():
        movie = SwfTarget.load(str(artifacts.movie(filename)), filename, em)
        for codepoint in ADDED:
            expected = glyph_bbox(desktop.glyph(codepoint))
            got = glyph_bbox(movie.glyph(codepoint))
            for index in range(4):
                assert got[index] == pytest.approx(expected[index], abs=0.015), (
                    f"{filename} U+{codepoint:04X}"
                )
            assert movie.advance(codepoint) == pytest.approx(
                desktop.advance(codepoint), abs=0.01
            ), f"{filename} U+{codepoint:04X}"


@movie_names
def test_added_movie_glyphs_use_the_shipped_fill_convention(movie: SwfTarget) -> None:
    for codepoint in ADDED:
        index = movie.font.glyph_by_code(codepoint)
        assert index is not None
        shape = movie.font.decode_shape(index)
        assert (shape.num_fill_bits, shape.num_line_bits) == (1, 0), hex(codepoint)
        styles = [op for op in shape.ops if op[0] == "style"]
        assert styles, hex(codepoint)
        for style in styles:
            assert style[1] == 1, f"U+{codepoint:04X}: fill index must be 1"
            assert style[2] is None and style[3] is None, hex(codepoint)


@movie_names
def test_added_movie_glyphs_keep_the_code_table_sorted(movie: SwfTarget) -> None:
    table = movie.font.code_table
    assert table == sorted(table), "Scaleform looks characters up in this table"
    assert len(set(table)) == len(table), "duplicate codes would orphan a glyph"


def test_added_desktop_glyphs_have_a_consistent_side_bearing(artifacts: Artifacts) -> None:
    for path in sorted(artifacts.out.glob("desktop/**/*.ttf")):
        font = TTFont(str(path))
        cmap = font.getBestCmap()
        assert cmap is not None
        for codepoint in ADDED:
            if codepoint not in cmap:
                continue
            name = cmap[codepoint]
            glyph = font["glyf"][name]
            glyph.expand(font["glyf"])
            advance, lsb = font["hmtx"][name]
            assert lsb == glyph.xMin, (
                f"{path.name} U+{codepoint:04X}: lsb {lsb} != xMin {glyph.xMin}"
            )
            assert advance > 0, hex(codepoint)


def test_added_codepoints_reach_every_subtable_that_can_hold_them(artifacts: Artifacts) -> None:
    """Not just the (3,1) subtable fontTools prefers: every unicode one."""
    for path in sorted(artifacts.out.glob("desktop/**/*.ttf")):
        font = TTFont(str(path))
        for subtable in font["cmap"].tables:
            encoding = (subtable.platformID, subtable.platEncID)
            if encoding not in {(0, 3), (3, 1), (3, 10)} or subtable.format not in (4, 12):
                continue
            for codepoint in ADDED:
                assert codepoint in subtable.cmap, (
                    f"{path.name} {encoding}: U+{codepoint:04X} missing from subtable"
                )


def test_legacy_macintosh_subtable_is_kept_in_sync(artifacts: Artifacts, upstream: Path) -> None:
    """The (1,0) subtable must follow, where Mac Roman can express the character.

    It is a legacy table, but leaving it stale is exactly the kind of silent
    half-update this project avoids; the rule is "add when Mac Roman can encode
    it, the code is inside the subtable's range and nothing is there yet".
    """
    for path in sorted(artifacts.out.glob("desktop/**/*.ttf")):
        relative = path.relative_to(artifacts.out / "desktop")
        source = TTFont(str(upstream / "desktop" / relative))
        patched = TTFont(str(path))
        before = _mac_subtable(source)
        after = _mac_subtable(patched)
        if before is None or after is None:  # pragma: no cover - defensive
            continue
        codes = list(before.cmap)
        for codepoint in ADDED:
            try:
                encoded = chr(codepoint).encode("mac_roman")
            except UnicodeEncodeError:
                continue
            if len(encoded) != 1:
                continue
            code = encoded[0]
            if not min(codes) <= code <= max(codes):
                continue
            expected = after.cmap.get(code)
            assert expected is not None, f"{path.name}: Mac code {code:#04x} vanished"
            if code not in before.cmap:
                wanted = patched.getBestCmap().get(codepoint)
                assert expected == wanted, (
                    f"{path.name}: Mac code {code:#04x} should carry U+{codepoint:04X} "
                    f"({wanted}), got {expected}"
                )


def _mac_subtable(font: TTFont) -> Any:
    for subtable in font["cmap"].tables:
        if (subtable.platformID, subtable.platEncID) == (1, 0):
            return subtable
    return None


@movie_names
def test_existing_glyphs_are_untouched_byte_for_byte(
    artifacts: Artifacts, upstream: Path, filename: str
) -> None:
    """Reordering the table must move glyphs without altering a single byte."""
    before = Movie.load((upstream / "mod" / "Data" / "Interface" / filename).read_bytes()).fonts()[
        0
    ][1]
    after = Movie.load(artifacts.movie(filename).read_bytes()).fonts()[0][1]
    assert after.num_glyphs == before.num_glyphs + len(ADDED)
    for code in before.code_table:
        index_before = before.glyph_by_code(code)
        index_after = after.glyph_by_code(code)
        assert index_before is not None and index_after is not None, hex(code)
        assert after.shape_bytes(index_after) == before.shape_bytes(index_before), hex(code)
        assert after.advances[index_after] == before.advances[index_before], hex(code)
        assert after.bounds[index_after] == before.bounds[index_before], hex(code)


def test_nothing_is_written_outside_the_font_tag(artifacts: Artifacts, upstream: Path) -> None:
    for filename in MOVIES:
        before = Movie.load((upstream / "mod" / "Data" / "Interface" / filename).read_bytes())
        after = Movie.load(artifacts.movie(filename).read_bytes())
        old_tag = before.fonts()[0][0]
        assert after.body[: old_tag.offset] == before.body[: old_tag.offset], filename
        tail = len(before.body) - (old_tag.offset + old_tag.size)
        assert after.body[-tail:] == before.body[-tail:], filename


def test_glyph_bbox_helper_is_not_confused_by_curves() -> None:
    """Sanity check on the helper every assertion above relies on."""
    glyph: Glyph = [[(0.0, 0.0, True), (1.0, 0.0, True), (0.5, 2.0, False)]]
    assert glyph_bbox(glyph) == (0.0, 0.0, 1.0, 2.0)
