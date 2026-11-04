"""Build the patched fonts (Skyrim movies and desktop TTFs) from upstream.

The build never rewrites an existing glyph and never touches anything but the
font it adds to:

* for a movie, only the ``DefineFont3`` tag is re-encoded, every other byte of
  the SWF is copied through;
* for a TTF, fontTools recompiles the touched tables from the loaded objects.

Each artifact is re-opened and checked right after being written
(:func:`verify_movie`, :func:`verify_ttf`), because a font that "saved fine"
and a font that renders are different claims.  Packaging itself (the installable
zips) is not done here: aviallon-mods/modforge's shared pipeline assembles and
verifies them from ``fomod-package*.toml``, so there is exactly one packaging
path.
"""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path

from fontTools.ttLib import TTFont

from . import glyphs
from .geometry import Glyph, glyph_bbox
from .swf import Movie, Shape
from .targets import SwfTarget, Target, TtfTarget, measure_scale

#: the movies to patch, with the desktop TTF the scale is measured against
MOVIES = (
    ("fonts_sovngarde.swf", "Sovngarde UI"),
    ("fonts_sovngardeconsole.swf", "Sovngarde console"),
)
#: desktop faces to patch (all four shipped in the Desktop Edition)
DESKTOP = (
    "Sovngarde/Sovngarde Bold.ttf",
    "Sovngarde/Sovngarde Light.ttf",
    "Sovngarde Inverted Brackets/Sovngarde Bold Inverted Brackets.ttf",
    "Sovngarde Inverted Brackets/Sovngarde Light Inverted Brackets.ttf",
)
REFERENCE_TTF = "Sovngarde/Sovngarde Bold.ttf"


@dataclass
class BuildReport:
    artifact: str
    added: list[tuple[int, str]]
    skipped: list[tuple[int, str]]
    detail: str

    def __str__(self) -> str:
        codes = " ".join(f"U+{cp:04X}" for cp, _ in self.added)
        line = f"{self.artifact}: +{len(self.added)} glyphs ({codes})"
        if self.skipped:
            line += f"; {len(self.skipped)} already present"
        return f"{line}\n    {self.detail}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _add_recipes(target: Target) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Install every recipe the target does not have yet."""
    added: list[tuple[int, str]] = []
    skipped: list[tuple[int, str]] = []
    for codepoint, name, glyph, advance in glyphs.build(target):
        if target.has(codepoint):
            skipped.append((codepoint, name))
            continue
        target.add(codepoint, glyph, advance, name)
        added.append((codepoint, name))
    return added, skipped


def build_movie(source: Path, out: Path, name: str, reference: Path) -> BuildReport:
    reference_font = TTFont(reference)
    raw = source.read_bytes()
    movie = Movie.load(raw)
    fonts = movie.fonts()
    if len(fonts) != 1:
        raise ValueError(f"{source}: expected one font tag, found {len(fonts)}")
    _, font = fonts[0]
    scale = measure_scale(font, reference_font)
    # scale is twips per *reference font unit*, so the em is the reference's upm
    target = SwfTarget.load(str(source), name, scale * int(reference_font["head"].unitsPerEm))
    added, skipped = _add_recipes(target)
    if not added:
        raise ValueError(f"{source}: every recipe is already present")
    before = target.font.num_glyphs
    target.save(str(out))
    verify_movie(source, out, target.em, before, added)
    detail = f"em {target.em:.1f} twips (scale {scale:.4f} twips/unit)"
    return BuildReport(name, added, skipped, f"{detail}, glyphs {before} -> {before + len(added)}")


def build_ttf(source: Path, out: Path, name: str) -> BuildReport:
    target = TtfTarget.load(str(source), name)
    added, skipped = _add_recipes(target)
    if not added:
        raise ValueError(f"{source}: every recipe is already present")
    before = target.font["maxp"].numGlyphs
    target.save(str(out))
    verify_ttf(out, added, before)
    return BuildReport(
        name, added, skipped, f"upm {int(target.em)}, glyphs {before} -> {before + len(added)}"
    )


# ---------------------------------------------------------------------------
# verification - a font that saved is not yet a font that works
# ---------------------------------------------------------------------------


def verify_movie(
    source: Path, out: Path, em: float, before: int, added: list[tuple[int, str]]
) -> None:
    """Re-open the written movie and check it changed exactly as intended."""
    original = Movie.load(source.read_bytes())
    patched = Movie.load(out.read_bytes())
    source_fonts = original.fonts()
    patched_fonts = patched.fonts()
    if len(patched_fonts) != 1:
        raise ValueError(f"{out}: {len(patched_fonts)} font tags after patching")
    _tag, font = patched_fonts[0]
    if font.num_glyphs != before + len(added):
        raise ValueError(f"{out}: {font.num_glyphs} glyphs, expected {before + len(added)}")
    codes = font.codes()
    for codepoint, name in added:
        if codepoint not in codes:
            raise ValueError(f"{out}: U+{codepoint:04X} ({name}) missing from the code table")
        shape = font.decode_shape(codes[codepoint])
        if not shape.ops:
            raise ValueError(f"{out}: U+{codepoint:04X} ({name}) decoded to an empty shape")
        x0, y0, x1, y1 = glyph_bbox(_to_canonical(shape, em))
        if x1 <= x0 or y1 <= y0:
            raise ValueError(f"{out}: U+{codepoint:04X} ({name}) has an empty bounding box")
    # every glyph, old and new, must fit in the bounds rectangle the file
    # itself carries: the strongest check available without the game
    tolerance = 2.0
    for index in range(font.num_glyphs):
        xmin, xmax, ymin, ymax = font.bounds[index]
        contour_points = [
            (x, y) for x, y, kind in font.decode_shape(index).absolute_points() if kind != "ctrl"
        ]
        if not contour_points:
            continue
        # absolute_points() is in the file's own (twips, y-down) coordinates,
        # which is exactly what the BoundsTable is expressed in
        got = (
            min(p[0] for p in contour_points),
            max(p[0] for p in contour_points),
            min(p[1] for p in contour_points),
            max(p[1] for p in contour_points),
        )
        if (
            got[0] < xmin - tolerance
            or got[1] > xmax + tolerance
            or got[2] < ymin - tolerance
            or got[3] > ymax + tolerance
        ):
            raise ValueError(
                f"{out}: glyph {index} (U+{font.code_table[index]:04X}) does not fit its bounds "
                f"{got} vs {(xmin, xmax, ymin, ymax)}"
            )

    # everything outside the font tag must be untouched
    original_body = original.body
    patched_body = patched.body
    old_tag = source_fonts[0][0]
    prefix = original_body[: old_tag.offset]
    if patched_body[: len(prefix)] != prefix:
        raise ValueError(f"{out}: the movie changed before the font tag")
    tail = original_body[old_tag.offset + old_tag.size :]
    if patched_body[-len(tail) :] != tail:
        raise ValueError(f"{out}: the movie changed after the font tag")


def _to_canonical(shape: Shape, em: float) -> Glyph:
    from .geometry import from_swf

    return from_swf(shape, em)


def verify_ttf(out: Path, added: list[tuple[int, str]], before: int) -> None:
    """Re-open the written TTF and check the new glyphs are really there."""
    font = TTFont(out)
    if font["maxp"].numGlyphs != before + len(added):
        raise ValueError(f"{out}: {font['maxp'].numGlyphs} glyphs, expected {before + len(added)}")
    cmap = font.getBestCmap()
    glyf = font["glyf"]
    hmtx = font["hmtx"]
    for codepoint, name in added:
        if cmap is None or codepoint not in cmap:
            raise ValueError(f"{out}: U+{codepoint:04X} ({name}) missing from the cmap")
        glyph_name = cmap[codepoint]
        if glyph_name not in glyf:
            raise ValueError(f"{out}: glyph {glyph_name} missing from glyf")
        glyph = glyf[glyph_name]
        glyph.expand(glyf)
        if glyph.numberOfContours <= 0:
            raise ValueError(f"{out}: U+{codepoint:04X} ({name}) has no contours")
        if hmtx[glyph_name][0] <= 0:
            raise ValueError(f"{out}: U+{codepoint:04X} ({name}) has no advance")
    if len(font.getGlyphOrder()) != font["maxp"].numGlyphs:
        raise ValueError(f"{out}: glyph order length does not match numGlyphs")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build(upstream: Path, out: Path, only: list[int] | None = None) -> list[BuildReport]:
    out.mkdir(parents=True, exist_ok=True)
    reports = []
    for relative in DESKTOP:
        source = upstream / "desktop" / relative
        destination = out / "desktop" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        reports.append(build_ttf(source, destination, Path(relative).stem))

    reference = upstream / "desktop" / REFERENCE_TTF
    for filename, name in MOVIES:
        source = upstream / "mod" / "Data" / "Interface" / filename
        destination = out / "mod" / "Data" / "Interface" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        reports.append(build_movie(source, destination, name, reference))

    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, default=Path("upstream"))
    parser.add_argument("--out", type=Path, default=Path("dist"))
    args = parser.parse_args()
    for report in build(args.upstream, args.out):
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
