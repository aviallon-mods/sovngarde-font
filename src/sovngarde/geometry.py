"""Canonical glyph geometry, plus conversions to/from TTF and SWF.

The canonical representation of a glyph is a list of contours of
``(x, y, on_curve)`` points expressed in **em units** (``1.0`` == one em, y
pointing up).  Both source formats can be read into it and written back from
it:

* TrueType ``glyf`` (integers, y up) - via fontTools;
* SWF ``DefineFont3`` glyph shapes (integer twips, glyphs above the baseline
  at negative y) - via :mod:`sovngarde.swf`;

The two renderings of the same glyph are cross-checked against each other in
the test suite, because a sign error is invisible to a round trip through a
single convention.

A tiny rasteriser lives here too, so a glyph can be previewed (and the two
round trips cross-checked) without a rendering dependency.
"""

from __future__ import annotations

import math
import struct
import zlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph as TTGlyph

from .swf import Op, Shape

Point = tuple[float, float, bool]
Contour = list[Point]
Glyph = list[Contour]

ON_CURVE = 0x01


# ---------------------------------------------------------------------------
# transforms
# ---------------------------------------------------------------------------


def glyph_bbox(glyph: Glyph) -> tuple[float, float, float, float]:
    """(xmin, ymin, xmax, ymax) of every point of the glyph (controls included)."""
    xs = [p[0] for contour in glyph for p in contour]
    ys = [p[1] for contour in glyph for p in contour]
    if not xs:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs), min(ys), max(xs), max(ys)


def transform(glyph: Glyph, fn: Callable[[float, float], tuple[float, float]]) -> Glyph:
    return [[(fn(x, y)[0], fn(x, y)[1], on) for x, y, on in contour] for contour in glyph]


def translate(glyph: Glyph, dx: float, dy: float) -> Glyph:
    return transform(glyph, lambda x, y: (x + dx, y + dy))


def scale_about(glyph: Glyph, factor: float, cx: float, cy: float) -> Glyph:
    return transform(glyph, lambda x, y: (cx + (x - cx) * factor, cy + (y - cy) * factor))


def stretched_x(glyph: Glyph, xmin: float, xmax: float) -> Glyph:
    """Stretch horizontally so the glyph's bbox spans exactly [xmin, xmax]."""
    cur_min, _, cur_max, _ = glyph_bbox(glyph)
    width = cur_max - cur_min
    if width <= 0:
        raise ValueError("cannot stretch an empty glyph")
    scale = (xmax - xmin) / width
    return transform(glyph, lambda x, y: (xmin + (x - cur_min) * scale, y))


def concatenate(*glyphs: Glyph) -> Glyph:
    out: Glyph = []
    for glyph in glyphs:
        out.extend(contour for contour in glyph)
    return out


# ---------------------------------------------------------------------------
# TTF <-> canonical
# ---------------------------------------------------------------------------


def from_ttf(font: TTFont, glyph_name: str) -> Glyph:
    """Read a glyph from a TTFont, in em units."""
    glyf = font["glyf"]
    tt_glyph = glyf[glyph_name]
    tt_glyph.expand(glyf)
    return from_ttf_glyph(tt_glyph, font["head"].unitsPerEm)


def from_ttf_glyph(tt_glyph: TTGlyph, upm: int) -> Glyph:
    """Read an expanded fontTools glyf Glyph, in em units."""
    if tt_glyph.numberOfContours <= 0:
        return []
    coords = list(tt_glyph.coordinates)
    flags = list(tt_glyph.flags)
    point = 0
    contours: Glyph = []
    for end in tt_glyph.endPtsOfContours:
        contour: Contour = []
        for i in range(point, end + 1):
            x, y = coords[i]
            contour.append((x / upm, y / upm, bool(flags[i] & ON_CURVE)))
        contours.append(contour)
        point = end + 1
    return contours


def to_ttf(glyph: Glyph, upm: int) -> TTGlyph:
    """Build a fontTools glyf Glyph, rounding to the font's integer grid."""

    def scale(point: Point) -> tuple[int, int]:
        return round(point[0] * upm), round(point[1] * upm)

    pen = TTGlyphPen(None)
    for contour in normalize(glyph):
        if not contour:
            continue
        pen.moveTo(scale(contour[0]))
        pending: list[tuple[int, int]] = []
        for point in contour[1:]:
            if point[2]:
                if pending:
                    pen.qCurveTo(*pending, scale(point))
                    pending = []
                else:
                    pen.lineTo(scale(point))
            else:
                pending.append(scale(point))
        if pending:
            # trailing off-curve points: the contour closes on its start point
            pen.qCurveTo(*pending, None)
        pen.closePath()
    tt_glyph: TTGlyph = pen.glyph()
    return tt_glyph


def normalize(glyph: Glyph) -> Glyph:
    """Rotate contours to start on an on-curve point and drop a repeated close.

    Both TrueType and the SWF represent a contour as a list of points whose
    first entry is the start of the outline; TrueType additionally implies an
    on-curve point between any two consecutive off-curve points, so a contour
    made only of off-curve points (an "implied circle", which the shipped TTF
    uses) has to gain its midpoints before it can be rotated at all.
    """
    out: Glyph = []
    for contour in glyph:
        if not contour:
            continue
        points = list(contour)
        if not any(p[2] for p in points):
            points = _with_implied_midpoints(points)
        index = next(i for i, p in enumerate(points) if p[2])
        points = points[index:] + points[:index]
        if len(points) > 1 and points[-1][2] and points[-1][:2] == points[0][:2]:
            points.pop()
        out.append(points)
    return out


# ---------------------------------------------------------------------------
# SWF <-> canonical
# ---------------------------------------------------------------------------


def from_swf(shape: Shape, em: float) -> Glyph:
    """Read an SWF font glyph outline (twips) into em units.

    Two conventions of these movies differ from plain ``DefineShape`` data:

    * outline coordinates run *above* the baseline as negative y (the SWF
      grid is y-down, but a font's glyphs are drawn upwards from y=0), so the
      canonical y is the negated SWF y: this is the mapping the movies were
      converted from the desktop design with,
      ``swf = (ttf_x * scale, -ttf_y * scale)``;
    * a contour's ``MoveTo`` is an **absolute** position, not a delta from the
      current pen position (the spec's wording, and the delta reading, put
      every contour after the first outside the glyph's own bounds rectangle -
      see the tests, which check every glyph against its ``BoundsTable``
      entry).
    """
    contours: Glyph = []
    current: Contour = []
    x = y = 0.0
    for op in shape.ops:
        if op[0] == "style":
            if op[4] is not None:
                if current:
                    contours.append(current)
                x, y = float(op[4][0]), float(op[4][1])
                current = [(x / em, -y / em, True)]
        elif op[0] == "line":
            x += op[1]
            y += op[2]
            current.append((x / em, -y / em, True))
        elif op[0] == "curve":
            cx, cy = x + op[1], y + op[2]
            x, y = cx + op[3], cy + op[4]
            current.append((cx / em, -cy / em, False))
            current.append((x / em, -y / em, True))
        elif op[0] != "rawbits":  # pragma: no cover - defensive
            raise ValueError(f"unknown shape op {op!r}")
    if current:
        contours.append(current)
    return normalize(contours)


def to_swf(glyph: Glyph, em: float) -> Shape:
    """Encode a glyph as an SWF font glyph shape.

    The Sovngarde/Drukaatie Burti movies use one convention everywhere: one
    ``StyleChange`` record per contour that moves to its start point and sets
    fill style 1, no fill/line style array at all (Scaleform only uses the fill
    index as an on/off flag for font glyphs), ``NumFillBits`` 1 and
    ``NumLineBits`` 0.
    """
    return Shape(_emit_contours(glyph, em), 1, 0)


def _twips(point: Point, em: float) -> tuple[int, int]:
    return round(point[0] * em), round(-point[1] * em)


def _delta(ops: Sequence[Op], point: Point, em: float) -> tuple[int, int]:
    x, y = _current_position(ops)
    tx, ty = _twips(point, em)
    return tx - x, ty - y


def _current_position(ops: Sequence[Op]) -> tuple[int, int]:
    """Pen position after the given ops, in twips (moves are absolute)."""
    x = y = 0
    for op in ops:
        if op[0] == "style":
            if op[4] is not None:
                x, y = op[4][0], op[4][1]
        elif op[0] == "line":
            x += op[1]
            y += op[2]
        elif op[0] == "curve":
            x += op[1] + op[3]
            y += op[2] + op[4]
    return x, y


def _emit_contours(glyph: Glyph, em: float) -> list[Op]:
    """Encode contours, splitting implied on-curve midpoints like Flash does."""
    ops: list[Op] = []
    for contour in normalize(glyph):
        points = _with_implied_midpoints(contour)
        if not points:
            continue
        start = points[0]
        # font glyph shapes carry an absolute position in their move record
        ops.append(("style", 1, None, None, _twips(start, em), None))
        control: Point | None = None
        index = 1
        while index <= len(points):
            point = points[index] if index < len(points) else start
            if not point[2]:
                control = point
            elif control is None:
                dx, dy = _delta(ops, point, em)
                variant = "general"
                if dx == 0 and dy != 0:
                    variant = "vertical"
                elif dy == 0 and dx != 0:
                    variant = "horizontal"
                ops.append(("line", dx, dy, variant, None))
            else:
                cx, cy = _delta(ops, control, em)
                ctrl = _twips(control, em)
                target = _twips(point, em)
                ops.append(("curve", cx, cy, target[0] - ctrl[0], target[1] - ctrl[1], None))
                control = None
            index += 1
    return ops


def _with_implied_midpoints(contour: Contour) -> Contour:
    """Insert the on-curve points implied between consecutive off-curve points."""
    out: Contour = []
    for i, point in enumerate(contour):
        out.append(point)
        nxt = contour[(i + 1) % len(contour)]
        if not point[2] and not nxt[2]:
            out.append(((point[0] + nxt[0]) / 2, (point[1] + nxt[1]) / 2, True))
    return out


# ---------------------------------------------------------------------------
# flattening + rasterising (previews only, no external dependency)
# ---------------------------------------------------------------------------


def _segments(glyph: Glyph) -> Iterable[tuple[Point, Point, Point | None]]:
    """Yield (start, end, control) segments; control is None for a line."""
    for contour in normalize(glyph):
        points = _with_implied_midpoints(contour)
        if len(points) < 2:
            continue
        current = points[0]
        control: Point | None = None
        for point in [*points[1:], points[0]]:
            if not point[2]:
                control = point
                continue
            yield current, point, control
            current = point
            control = None


def flatten(glyph: Glyph, steps: int = 12) -> list[list[tuple[float, float]]]:
    """Approximate every contour with polylines (no curves left)."""
    polylines: list[list[tuple[float, float]]] = []
    for start, end, control in _segments(glyph):
        poly = [(start[0], start[1])]
        if control is None:
            poly.append((end[0], end[1]))
        else:
            for i in range(1, steps + 1):
                t = i / steps
                mt = 1 - t
                poly.append(
                    (
                        mt * mt * start[0] + 2 * mt * t * control[0] + t * t * end[0],
                        mt * mt * start[1] + 2 * mt * t * control[1] + t * t * end[1],
                    )
                )
        if polylines and polylines[-1][-1] == poly[0]:
            polylines[-1].extend(poly[1:])
        else:
            polylines.append(poly)
    return polylines


@dataclass
class Raster:
    """A rendered glyph: gray pixels plus the em position of the top-left pixel."""

    width: int
    height: int
    pixels: bytearray
    origin_x: float  # em units at the left edge of pixel column 0
    origin_y: float  # em units at the top edge of pixel row 0
    size_px: int

    def canvas_position(self, pen_x: float, baseline_y: float) -> tuple[int, int]:
        """Top-left pixel position when drawn at ``pen_x`` on ``baseline_y``."""
        return (
            round((pen_x + self.origin_x) * self.size_px),
            round((baseline_y - self.origin_y) * self.size_px),
        )


def rasterize(
    glyph: Glyph,
    size_px: int,
    advance: float | None = None,
    supersample: int = 4,
) -> Raster:
    """Render a glyph to a grayscale bitmap, non-zero winding, y down.

    ``size_px`` is the em size in pixels.  The bitmap is padded by half a pixel
    on every side and :class:`Raster` records where that bitmap sits in em
    units, so callers can place it exactly.
    """
    xmin, ymin, xmax, ymax = glyph_bbox(glyph)
    if advance is not None:
        xmax = max(xmax, advance)
    if xmax <= xmin:
        xmax = xmin + 1e-3
    if ymax <= ymin:
        ymax = ymin + 1e-3
    pad = 0.5 / size_px
    origin_x = xmin - pad
    origin_y = ymax + pad
    scale = size_px * supersample
    width = max(1, math.ceil((xmax - xmin + 2 * pad) * size_px))
    height = max(1, math.ceil((ymax - ymin + 2 * pad) * size_px))

    # flip to a y-down supersampled space, one entry per polygon edge
    edges: list[tuple[float, float, float, float]] = []
    for poly in flatten(glyph):
        for i in range(len(poly) - 1):
            (ax, ay), (bx, by) = poly[i], poly[i + 1]
            edges.append(
                (
                    (ax - origin_x) * scale,
                    (origin_y - ay) * scale,
                    (bx - origin_x) * scale,
                    (origin_y - by) * scale,
                )
            )

    rows = height * supersample
    coverage = [0] * (width * height)
    for row in range(rows):
        y = row + 0.5  # the edge list is already y-down
        crossings: list[tuple[float, int]] = []
        for x0, y0, x1, y1 in edges:
            if (y0 <= y < y1) or (y1 <= y < y0):
                t = (y - y0) / (y1 - y0)
                crossings.append((x0 + t * (x1 - x0), 1 if y1 > y0 else -1))
        if not crossings:
            continue
        crossings.sort()
        winding = 0
        for i in range(len(crossings) - 1):
            winding += crossings[i][1]
            if winding == 0:
                continue
            start = max(0, int(crossings[i][0]))
            end = min(width * supersample, int(crossings[i + 1][0]) + 1)
            for column in range(start, end):
                coverage[(row // supersample) * width + column // supersample] += 1
    maxcov = supersample * supersample
    pixels = bytearray(min(value, maxcov) * 255 // maxcov for value in coverage)
    return Raster(width, height, pixels, origin_x, origin_y, size_px)


def render_line(
    items: Sequence[tuple[Glyph, float]],
    size_px: int,
    margin: int = 6,
) -> tuple[int, int, bytearray]:
    """Render (glyph, advance) pairs on one baseline, on a white canvas."""
    if not items:
        return 1, 1, bytearray(3)
    top = max((glyph_bbox(g)[3] for g, _ in items), default=0.1)
    bottom = min((glyph_bbox(g)[1] for g, _ in items), default=0.0)
    width = sum(advance for _, advance in items)
    height = top - bottom
    canvas_w = int((width + 0.04) * size_px) + 2 * margin
    canvas_h = int((height + 0.04) * size_px) + 2 * margin
    canvas = bytearray(b"\xff" * (canvas_w * canvas_h * 3))
    pen = 0.0
    for glyph, advance in items:
        if glyph_bbox(glyph)[2] > glyph_bbox(glyph)[0]:
            raster = rasterize(glyph, size_px)
            x, y = raster.canvas_position(pen + 0.02, top + 0.02)
            blit_grayscale(
                canvas,
                canvas_w,
                canvas_h,
                margin + x,
                margin + y,
                raster.width,
                raster.height,
                raster.pixels,
            )
        pen += advance
    return canvas_w, canvas_h, canvas


def write_png(path: str, width: int, height: int, rgb: bytes) -> None:
    """Minimal 8-bit RGB PNG writer (no dependency)."""
    raw = bytearray()
    stride = width * 3
    for row in range(height):
        raw.append(0)
        raw.extend(rgb[row * stride : (row + 1) * stride])

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    with Path(path).open("wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n")
        handle.write(chunk(b"IHDR", header))
        handle.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        handle.write(chunk(b"IEND", b""))


def blit_grayscale(
    canvas: bytearray, cw: int, ch: int, x: int, y: int, gw: int, gh: int, pixels: bytearray
) -> None:
    """Blit dark glyph coverage onto a light (RGB) canvas."""
    for row in range(gh):
        cy = y + row
        if not 0 <= cy < ch:
            continue
        for col in range(gw):
            cx = x + col
            if not 0 <= cx < cw:
                continue
            value = pixels[row * gw + col]
            base = (cy * cw + cx) * 3
            for i in range(3):
                canvas[base + i] = min(canvas[base + i], 255 - value)
