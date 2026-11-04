"""Recipes for the glyphs missing from Sovngarde.

Every recipe is expressed in **em units** (1.0 == one em) and derives its
shapes from the target font's own glyphs wherever possible, so the additions
inherit the font's weight, thickness and vertical placement instead of
introducing a foreign style:

* the dashes are the font's own ``-`` stretched horizontally, keeping its side
  bearing (which is how DejaVu, Liberation and FreeSans build theirs: an em
  dash is 1 em of advance with a ~0.90 em bar);
* the ellipsis is the font's own ``.`` repeated at its own advance, so ``…``
  renders exactly like ``...``;
* the superscripts and the trademark are the font's digits / ``T`` / ``M``
  scaled and raised;
* the single guillemets are the font's own ``«`` ``»`` scaled down;
* the remaining symbols are built from primitives (bars, circles, strokes)
  using the hyphen's thickness and the font's x-height/cap-height.

Contour orientation follows the shipped font: clockwise for solids,
counter-clockwise for counters.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from .geometry import (
    Glyph,
    concatenate,
    glyph_bbox,
    scale_about,
    stretched_x,
    translate,
)
from .targets import Target

# Geometry constants measured on the shipped Sovngarde Bold (per 1000 units).
CAP_HEIGHT = 0.552
X_HEIGHT = 0.330
MATH_AXIS = 0.273  # the vertical centre of the '+' and '=' bars

Recipe = Callable[[Target], tuple[Glyph, float]]
RECIPES: dict[int, tuple[str, Recipe]] = {}


def recipe(codepoint: int, name: str) -> Callable[[Recipe], Recipe]:
    def register(fn: Recipe) -> Recipe:
        RECIPES[codepoint] = (name, fn)
        return fn

    return register


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------


def rect(x0: float, y0: float, x1: float, y1: float, clockwise: bool = True) -> Glyph:
    points: list[tuple[float, float, bool]] = [
        (x0, y0, True),
        (x0, y1, True),
        (x1, y1, True),
        (x1, y0, True),
    ]
    if not clockwise:
        points.reverse()
    return [points]


def circle(cx: float, cy: float, radius: float, clockwise: bool = True) -> Glyph:
    k = 0.5522847498307935 * radius
    points: list[tuple[float, float, bool]] = [
        (cx, cy + radius, True),
        (cx + k, cy + radius, False),
        (cx + radius, cy + k, True),
        (cx + radius, cy, False),
        (cx + radius, cy - k, True),
        (cx + k, cy - radius, False),
        (cx, cy - radius, True),
        (cx - k, cy - radius, False),
        (cx - radius, cy - k, True),
        (cx - radius, cy, False),
        (cx - radius, cy + k, True),
        (cx - k, cy + radius, False),
    ]
    if not clockwise:
        points.reverse()
    return [points]


def ring(cx: float, cy: float, outer: float, inner: float) -> Glyph:
    return concatenate(circle(cx, cy, outer), circle(cx, cy, inner, clockwise=False))


def thick_line(
    x0: float, y0: float, x1: float, y1: float, thickness: float, clockwise: bool = True
) -> Glyph:
    """A straight stroke of the given thickness, as a 4-point polygon."""
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError("a stroke needs two distinct points")
    nx, ny = -dy / length * thickness / 2, dx / length * thickness / 2
    points: list[tuple[float, float, bool]] = [
        (x0 + nx, y0 + ny, True),
        (x1 + nx, y1 + ny, True),
        (x1 - nx, y1 - ny, True),
        (x0 - nx, y0 - ny, True),
    ]
    if not clockwise:
        points.reverse()
    return [points]


def stroke_thickness(target: Target) -> float:
    """The font's own stroke weight: the hyphen's bar height."""
    _, y0, _, y1 = glyph_bbox(target.glyph(0x2D))
    return y1 - y0


def hyphen_bar(target: Target) -> tuple[float, float]:
    """(ymin, ymax) of the font's hyphen bar, i.e. where a dash belongs."""
    _, y0, _, y1 = glyph_bbox(target.glyph(0x2D))
    return y0, y1


# ---------------------------------------------------------------------------
# dashes and dots
# ---------------------------------------------------------------------------


@recipe(0x2010, "hyphen")
def hyphen_glyph(target: Target) -> tuple[Glyph, float]:
    """U+2010 HYPHEN: the same design as the ASCII hyphen, its own codepoint."""
    return target.glyph(0x2D), target.advance(0x2D)


@recipe(0x2011, "nonbreakinghyphen")
def nonbreaking_hyphen(target: Target) -> tuple[Glyph, float]:
    return target.glyph(0x2D), target.advance(0x2D)


@recipe(0x2013, "endash")
def en_dash(target: Target) -> tuple[Glyph, float]:
    hyphen = target.glyph(0x2D)
    bearing = glyph_bbox(hyphen)[0]
    return stretched_x(hyphen, bearing, 0.5 - bearing), 0.5


@recipe(0x2014, "emdash")
def em_dash(target: Target) -> tuple[Glyph, float]:
    hyphen = target.glyph(0x2D)
    bearing = glyph_bbox(hyphen)[0]
    return stretched_x(hyphen, bearing, 1.0 - bearing), 1.0


@recipe(0x2026, "ellipsis")
def ellipsis(target: Target) -> tuple[Glyph, float]:
    period = target.glyph(0x2E)
    step = target.advance(0x2E)
    dots = [translate(period, step * i, 0) for i in range(3)]
    return concatenate(*dots), step * 3


@recipe(0x2212, "minus")
def minus(target: Target) -> tuple[Glyph, float]:
    """U+2212 MINUS SIGN: the hyphen stretched to the '+' width, on the maths axis.

    The '+' of this font is a symmetric cross, so its own bounding box is its
    bar extent; measuring it that way is target-independent, unlike looking for
    the widest band of points.
    """
    hyphen = target.glyph(0x2D)
    x0, _, x1, _ = glyph_bbox(target.glyph(0x2B))
    bar = stretched_x(hyphen, x0, x1)
    _, y0, _, y1 = glyph_bbox(bar)
    return translate(bar, 0, MATH_AXIS - (y0 + y1) / 2), target.advance(0x2B)


# ---------------------------------------------------------------------------
# symbols built from primitives
# ---------------------------------------------------------------------------


@recipe(0x2022, "bullet")
def bullet(target: Target) -> tuple[Glyph, float]:
    advance = 0.40
    return circle(advance / 2, 0.30, 0.125), advance


@recipe(0x00D7, "multiply")
def multiply(target: Target) -> tuple[Glyph, float]:
    """U+00D7: a '+' turned 45 degrees - same box and thickness as the font's '+'."""
    advance = target.advance(0x2B)
    thickness = stroke_thickness(target)
    x0, _, x1, _ = glyph_bbox(target.glyph(0x2B))
    radius = min(x1 - x0, 0.36) / 2
    cx, cy = advance / 2, MATH_AXIS
    return (
        concatenate(
            thick_line(cx - radius, cy - radius, cx + radius, cy + radius, thickness),
            thick_line(cx - radius, cy + radius, cx + radius, cy - radius, thickness),
        ),
        advance,
    )


@recipe(0x00F7, "divide")
def divide(target: Target) -> tuple[Glyph, float]:
    advance = 0.44
    thickness = stroke_thickness(target)
    cx = advance / 2
    dot = 0.062
    return (
        concatenate(
            rect(0.048, MATH_AXIS - thickness / 2, advance - 0.048, MATH_AXIS + thickness / 2),
            circle(cx, MATH_AXIS + 0.175, dot),
            circle(cx, MATH_AXIS - 0.175, dot),
        ),
        advance,
    )


@recipe(0x00B1, "plusminus")
def plus_minus(target: Target) -> tuple[Glyph, float]:
    plus = target.glyph(0x2B)
    advance = target.advance(0x2B)
    bar = thick_line(0.048, 0.0, advance - 0.048, 0.0, stroke_thickness(target))
    return concatenate(translate(plus, 0, 0.105), translate(bar, 0, 0.075)), advance


@recipe(0x2260, "notequal")
def not_equal(target: Target) -> tuple[Glyph, float]:
    equal = target.glyph(0x3D)
    advance = target.advance(0x3D)
    x0, y0, x1, y1 = glyph_bbox(equal)
    slash = thick_line(x0 + 0.10, y0 - 0.055, x1 - 0.10, y1 + 0.055, stroke_thickness(target))
    return concatenate(equal, slash), advance


@recipe(0x2264, "lessequal")
def less_equal(target: Target) -> tuple[Glyph, float]:
    less = target.glyph(0x3C)
    advance = target.advance(0x3C)
    x0, _, x1, _ = glyph_bbox(less)
    bar = thick_line(x0, 0.0, x1, 0.0, stroke_thickness(target))
    return concatenate(translate(less, 0, 0.055), translate(bar, 0, 0.075)), advance


@recipe(0x2265, "greaterequal")
def greater_equal(target: Target) -> tuple[Glyph, float]:
    greater = target.glyph(0x3E)
    advance = target.advance(0x3E)
    x0, _, x1, _ = glyph_bbox(greater)
    bar = thick_line(x0, 0.0, x1, 0.0, stroke_thickness(target))
    return concatenate(translate(greater, 0, 0.055), translate(bar, 0, 0.075)), advance


#: reference proportions for a dagger (DejaVu/Liberation/FreeSans agree within 5%)
DAGGER_HEIGHT = 0.80
DAGGER_CROSSBAR = 0.40
DAGGER_TOP = 0.67


@recipe(0x2020, "dagger")
def dagger(target: Target) -> tuple[Glyph, float]:
    thickness = stroke_thickness(target)
    advance = 0.50
    cx = advance / 2
    bottom = DAGGER_TOP - DAGGER_HEIGHT
    half = DAGGER_CROSSBAR / 2
    y = bottom + DAGGER_HEIGHT * 0.74
    return (
        concatenate(
            thick_line(cx, bottom, cx, DAGGER_TOP, thickness),
            thick_line(cx - half, y, cx + half, y, thickness * 0.85),
        ),
        advance,
    )


@recipe(0x2021, "daggerdbl")
def double_dagger(target: Target) -> tuple[Glyph, float]:
    thickness = stroke_thickness(target)
    advance = 0.50
    cx = advance / 2
    bottom = DAGGER_TOP - DAGGER_HEIGHT
    half = DAGGER_CROSSBAR / 2
    y = bottom + DAGGER_HEIGHT * 0.74
    gap = DAGGER_HEIGHT * 0.16
    return (
        concatenate(
            thick_line(cx, bottom, cx, DAGGER_TOP, thickness),
            thick_line(cx - half, y + gap, cx + half, y + gap, thickness * 0.85),
            thick_line(cx - half, y - gap, cx + half, y - gap, thickness * 0.85),
        ),
        advance,
    )


# ---------------------------------------------------------------------------
# derived from existing glyphs (scaled copies / compositions)
# ---------------------------------------------------------------------------


#: reference proportion for superscripts: 0.42 em tall (DejaVu, Liberation),
#: top aligned with the cap height
SUPERSCRIPT_HEIGHT = 0.42


def _superscript(target: Target, digit: int, factor: float | None = None) -> tuple[Glyph, float]:
    glyph = target.glyph(digit)
    _, _, _, top = glyph_bbox(glyph)
    if factor is None:
        factor = SUPERSCRIPT_HEIGHT / top if top else 0.76
    scaled = scale_about(glyph, factor, 0, 0)
    _, _, _, scaled_top = glyph_bbox(scaled)
    # raise so that the superscript's top reaches the cap height
    return translate(scaled, 0, CAP_HEIGHT - scaled_top), target.advance(digit) * factor


@recipe(0x00B9, "onesuperior")
def one_superior(target: Target) -> tuple[Glyph, float]:
    return _superscript(target, 0x31)


@recipe(0x00B2, "twosuperior")
def two_superior(target: Target) -> tuple[Glyph, float]:
    return _superscript(target, 0x32)


@recipe(0x00B3, "threesuperior")
def three_superior(target: Target) -> tuple[Glyph, float]:
    return _superscript(target, 0x33)


@recipe(0x2122, "trademark")
def trademark(target: Target) -> tuple[Glyph, float]:
    """U+2122: the font's own T and M, shrunk and raised like a superscript."""
    t_factor = 0.60
    m_factor = 0.52
    t = scale_about(target.glyph(0x54), t_factor, 0, 0)
    m = scale_about(target.glyph(0x4D), m_factor, 0, 0)
    t_width = target.advance(0x54) * t_factor
    m_width = target.advance(0x4D) * m_factor
    _, _, _, t_top = glyph_bbox(t)
    return (
        concatenate(translate(t, 0, CAP_HEIGHT - t_top), translate(m, t_width, CAP_HEIGHT - t_top)),
        t_width + m_width + 0.04,
    )


#: reference proportion for a circled mark: ring 0.70 em across, centred at 0.35
CIRCLED_DIAMETER = 0.70
CIRCLED_RING = 0.055


def _circled(
    target: Target, letter: int, diameter: float = CIRCLED_DIAMETER
) -> tuple[Glyph, float]:
    radius = diameter / 2
    cx, cy = diameter / 2 + 0.04, 0.35
    glyph = target.glyph(letter)
    x0, y0, x1, y1 = glyph_bbox(glyph)
    inner = radius - CIRCLED_RING - 0.02
    scale = min(inner * 2 / (x1 - x0), inner * 1.5 / (y1 - y0))
    scaled = scale_about(glyph, scale, 0, 0)
    sx0, sy0, sx1, sy1 = glyph_bbox(scaled)
    placed = translate(scaled, cx - (sx0 + sx1) / 2, cy - (sy0 + sy1) / 2)
    return concatenate(ring(cx, cy, radius, radius - CIRCLED_RING), placed), cx + radius + 0.04


@recipe(0x00A9, "copyright")
def copyright_sign(target: Target) -> tuple[Glyph, float]:
    return _circled(target, 0x43)


@recipe(0x00AE, "registered")
def registered_sign(target: Target) -> tuple[Glyph, float]:
    return _circled(target, 0x52)


@recipe(0x2039, "guilsinglleft")
def single_guillemet_left(target: Target) -> tuple[Glyph, float]:
    glyph = target.glyph(0xAB)
    factor = 0.62
    scaled = scale_about(glyph, factor, 0, 0)
    _, y0, _, _ = glyph_bbox(scaled)
    return translate(scaled, 0, -y0), target.advance(0xAB) * factor


@recipe(0x203A, "guilsinglright")
def single_guillemet_right(target: Target) -> tuple[Glyph, float]:
    glyph = target.glyph(0xBB)
    factor = 0.62
    scaled = scale_about(glyph, factor, 0, 0)
    _, y0, _, _ = glyph_bbox(scaled)
    return translate(scaled, 0, -y0), target.advance(0xBB) * factor


def build(
    target: Target, codepoints: list[int] | None = None
) -> list[tuple[int, str, Glyph, float]]:
    """Evaluate every recipe (or the given ones) against a target font."""
    out = []
    for codepoint, (name, fn) in sorted(RECIPES.items()):
        if codepoints is not None and codepoint not in codepoints:
            continue
        glyph, advance = fn(target)
        out.append((codepoint, name, glyph, advance))
    return out
