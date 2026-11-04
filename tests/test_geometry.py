"""Geometry: the two coordinate systems must agree, and be cross-checked.

A sign or scale error is invisible to a round trip inside one convention (the
code is self-consistent), so the tests below compare the *SWF* rendering with
the *TTF* rendering of the same design, and the TTF round trip by pixels.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from sovngarde.geometry import (
    flatten,
    from_swf,
    from_ttf,
    from_ttf_glyph,
    glyph_bbox,
    normalize,
    rasterize,
    to_ttf,
)
from sovngarde.targets import SwfTarget, TtfTarget, measure_scale

#: measured once from the shipped UI movie against the desktop design
UI_EM = 20.4824 * 1000


@pytest.fixture(scope="module")
def targets(upstream: Path) -> tuple[SwfTarget, TtfTarget]:
    swf = SwfTarget.load(
        str(upstream / "mod" / "Data" / "Interface" / "fonts_sovngarde.swf"), "ui", UI_EM
    )
    ttf = TtfTarget.load(str(upstream / "desktop" / "Sovngarde" / "Sovngarde Bold.ttf"), "bold")
    return swf, ttf


def test_measure_scale_is_uniform(upstream: Path) -> None:
    movie = SwfTarget.load(
        str(upstream / "mod" / "Data" / "Interface" / "fonts_sovngarde.swf"), "ui", UI_EM
    )
    reference = TTFont(str(upstream / "desktop" / "Sovngarde" / "Sovngarde Bold.ttf"))
    scale = measure_scale(movie.font, reference)
    assert 20.4 < scale < 20.6, scale


def test_measure_scale_refuses_a_mismatched_pair(upstream: Path) -> None:
    """The guard must actually fire: break the reference and watch it refuse.

    This is the mutation test for the scale guard - without it, a wrong
    reference font would be silently scaled and every new glyph would be
    placed at the wrong size.
    """
    movie = SwfTarget.load(
        str(upstream / "mod" / "Data" / "Interface" / "fonts_sovngarde.swf"), "ui", UI_EM
    )
    reference = TTFont(str(upstream / "desktop" / "Sovngarde" / "Sovngarde Bold.ttf"))
    for i, name in enumerate(reference.getGlyphOrder()):
        if i % 3 == 0:
            advance, lsb = reference["hmtx"][name]
            reference["hmtx"][name] = (int(advance * 1.3), lsb)
    with pytest.raises(ValueError, match="not uniform"):
        measure_scale(movie.font, reference, tolerance=0.01)


def test_swf_and_ttf_describe_the_same_design(targets: tuple[SwfTarget, TtfTarget]) -> None:
    """The movie and the desktop face must be the same design.

    Pixel-exact equality is not the criterion: the movie was produced by Flash
    re-encoding the outlines, so curves carry slightly different control points
    and antialiasing differs by a few percent of the pixels.  What must hold is
    that the outlines cover the same box and the same amount of ink - a
    coordinate convention error moves the box, which is exactly how the
    flipped-axis and relative-move bugs were caught.
    """
    swf, ttf = targets
    compared = 0
    for codepoint in sorted(ttf.cmap):
        if not swf.has(codepoint):
            continue
        one, other = swf.glyph(codepoint), ttf.glyph(codepoint)
        box_one, box_other = glyph_bbox(one), glyph_bbox(other)
        compared += 1
        for index in range(4):
            assert abs(box_one[index] - box_other[index]) < 0.012, (
                f"U+{codepoint:04X}: bounding box differs ({box_one} vs {box_other})"
            )
        raster_one = rasterize(one, 40)
        raster_other = rasterize(other, 40)
        ink_one = sum(1 for p in raster_one.pixels if p > 127)
        ink_other = sum(1 for p in raster_other.pixels if p > 127)
        if max(ink_one, ink_other) > 20:
            ratio = abs(ink_one - ink_other) / max(ink_one, ink_other)
            assert ratio < 0.2, f"U+{codepoint:04X}: ink differs by {ratio:.0%}"
    assert compared > 250, compared


@pytest.mark.parametrize("face", ["Sovngarde Bold", "Sovngarde Light"])
def test_ttf_round_trip_by_pixels(upstream: Path, face: str) -> None:
    """read -> write -> read must render the same glyphs, in both weights.

    Six glyphs (the ones FontForge wrote as implied circles, where a midpoint
    can land on a half unit) change by one to three pixels because their implied
    on-curve points become explicit.  Anything beyond that means the writer is
    moving outlines.
    """
    ttf = TtfTarget.load(str(upstream / "desktop" / "Sovngarde" / f"{face}.ttf"), face)
    assert ttf.font["head"].unitsPerEm == 1000
    identical = 0
    different: list[str] = []
    for codepoint in sorted(ttf.cmap):
        glyph = from_ttf(ttf.font, ttf.cmap[codepoint])
        back = from_ttf_glyph(to_ttf(glyph, 1000), 1000)
        a = rasterize(glyph, 48)
        b = rasterize(back, 48)
        if (a.width, a.height) == (b.width, b.height) and a.pixels == b.pixels:
            identical += 1
            continue
        if (a.width, a.height) != (b.width, b.height):
            different.append(f"{hex(codepoint)} (size)")
            continue
        pixels = sum(1 for p, q in zip(a.pixels, b.pixels, strict=False) if p != q)
        # a sub-unit rounding shift touches proportionally more pixels on a
        # small glyph (the degree sign is ~10x10 at this size), so allow a
        # handful outright and 2% beyond that
        allowed = max(4, 0.02 * a.width * a.height)
        assert pixels <= allowed, f"{hex(codepoint)}: {pixels} pixels differ (> {allowed:.0f})"
        different.append(hex(codepoint))
    assert len(different) <= 8, different
    assert identical >= len(ttf.cmap) - 8, different


def test_normalize_is_idempotent(targets: tuple[SwfTarget, TtfTarget]) -> None:
    _, ttf = targets
    for codepoint in (0x41, 0x6F, 0x25, 0xB0, 0x2E):
        glyph = from_ttf(ttf.font, ttf.cmap[codepoint])
        once = normalize(glyph)
        assert normalize(once) == once, hex(codepoint)


def test_flattened_curves_stay_inside_the_control_hull(
    targets: tuple[SwfTarget, TtfTarget],
) -> None:
    swf, _ = targets
    glyph = swf.glyph(0x6F)  # 'o' is all curves
    hull = glyph_bbox(glyph)
    flat = glyph_bbox([[(*point, True) for point in poly] for poly in flatten(glyph)])
    assert hull[0] <= flat[0] <= flat[2] <= hull[2]
    assert hull[1] <= flat[1] <= flat[3] <= hull[3]


def test_from_swf_reads_absolute_moves(upstream: Path) -> None:
    """Regression: a contour's move is an absolute position, not a delta."""
    movie = SwfTarget.load(
        str(upstream / "mod" / "Data" / "Interface" / "fonts_sovngarde.swf"), "ui", UI_EM
    )
    for codepoint in (0x25, 0x41, 0x21, 0x6D):
        index = movie.font.glyph_by_code(codepoint)
        assert index is not None
        shape = movie.font.decode_shape(index)
        glyph = from_swf(shape, movie.em)
        assert len(glyph) >= 2, "this regression needs a multi-contour glyph"
        xmin, xmax, ymin, ymax = movie.font.bounds[index]
        for contour in glyph:
            x, y = contour[0][0] * movie.em, -contour[0][1] * movie.em
            assert xmin - 2 <= x <= xmax + 2, (hex(codepoint), x)
            assert ymin - 2 <= y <= ymax + 2, (hex(codepoint), y)
