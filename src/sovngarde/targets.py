"""Font targets: the objects a new glyph is installed into.

Two kinds of target exist:

* :class:`SwfTarget` - a Skyrim Scaleform movie (``fonts_sovngarde.swf``),
  which is what the game renders;
* :class:`TtfTarget` - a desktop TrueType font (the "Desktop Edition"), patched
  in place with fontTools.

Both expose the same minimal surface: the em size, the advance table, reading
an existing glyph as canonical em-unit contours, and appending new glyphs.
Working in em units means one glyph definition serves every target even though
the SWF stores twips (and at a different scale per movie).
"""

from __future__ import annotations

import os
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from fontTools.ttLib import TTFont

from .geometry import Glyph, from_swf, from_ttf, to_swf, to_ttf
from .swf import (
    TAG_CSMTEXTSETTINGS,
    TAG_DEFINEFONT3,
    TAG_DEFINEFONTALIGNZONES,
    DefineFont,
    Movie,
    Shape,
    encode_define_font,
    iter_tags,
)


class Target(Protocol):
    name: str
    em: float

    def has(self, codepoint: int) -> bool: ...
    def advance(self, codepoint: int) -> float: ...
    def glyph(self, codepoint: int) -> Glyph: ...
    def add(
        self, codepoint: int, glyph: Glyph, advance: float, name: str | None = None
    ) -> None: ...


# ---------------------------------------------------------------------------
# SWF (game) target
# ---------------------------------------------------------------------------


@dataclass
class SwfTarget:
    """A Skyrim Scaleform font movie."""

    name: str
    path: str
    movie: Movie
    tag: object  # swf.Tag, kept opaque to avoid a circular annotation
    font: DefineFont
    em: float
    _new: list[tuple[int, Shape, int]] = field(default_factory=list)

    @classmethod
    def load(cls, path: str, name: str, em: float) -> SwfTarget:
        movie = Movie.load(Path(path).read_bytes())
        fonts = movie.fonts()
        if len(fonts) != 1:
            raise ValueError(f"{path}: expected exactly one font tag, found {len(fonts)}")
        tag, font = fonts[0]
        if tag.code != TAG_DEFINEFONT3:
            raise ValueError(f"{path}: expected DefineFont3, found tag {tag.code}")
        return cls(name=name, path=path, movie=movie, tag=tag, font=font, em=em)

    def has(self, codepoint: int) -> bool:
        return self.font.glyph_by_code(codepoint) is not None

    def advance(self, codepoint: int) -> float:
        index = self.font.glyph_by_code(codepoint)
        if index is None:
            raise KeyError(f"{self.name}: U+{codepoint:04X} is not in the font")
        return self.font.advances[index] / self.em

    def glyph(self, codepoint: int) -> Glyph:
        index = self.font.glyph_by_code(codepoint)
        if index is None:
            raise KeyError(f"{self.name}: U+{codepoint:04X} is not in the font")
        return from_swf(self.font.decode_shape(index), self.em)

    def add(self, codepoint: int, glyph: Glyph, advance: float, name: str | None = None) -> None:
        if self.has(codepoint) or any(code == codepoint for code, _, _ in self._new):
            raise ValueError(f"{self.name}: U+{codepoint:04X} already exists")
        del name  # the SWF carries no glyph names beyond the font name
        self._guard_per_glyph_tables()
        self._new.append((codepoint, to_swf(glyph, self.em), round(advance * self.em)))

    def _guard_per_glyph_tables(self) -> None:
        """Refuse movies carrying tables indexed by glyph number.

        ``DefineFontAlignZones`` holds one entry per glyph: appending a glyph
        without extending it would leave the movie inconsistent, so it is
        refused rather than silently ignored.
        """
        for tag in iter_tags(self.movie.body):
            if tag.code in (TAG_DEFINEFONTALIGNZONES, TAG_CSMTEXTSETTINGS):
                raise NotImplementedError(
                    f"{self.name}: the movie has tag {tag.code}, which is indexed per glyph; "
                    "appending glyphs needs that table extended first"
                )

    def codes(self) -> list[int]:
        return list(self.font.code_table)

    def save(self, path: str) -> None:
        if not self._new:
            raise ValueError(f"{self.name}: nothing to add")
        data = encode_define_font(self.font, self._new)
        body = self.movie.replace_tag(self.tag, data)  # type: ignore[arg-type]
        Path(path).write_bytes(self.movie.save(body))


# ---------------------------------------------------------------------------
# TTF (desktop) target
# ---------------------------------------------------------------------------


#: appended to the name table's version string by :meth:`TtfTarget._mark_version`
VERSION_MARK = "(Sovngarde+ glyphes manquants)"

UNICODE_PLATFORM_ENCODINGS = {
    (0, 0),
    (0, 1),
    (0, 2),
    (0, 3),
    (0, 4),
    (0, 5),
    (0, 6),
    (3, 1),
    (3, 10),
}


@dataclass
class TtfTarget:
    name: str
    path: str
    font: TTFont
    em: float
    _added: list[str] = field(default_factory=list)
    _original_modified: int = 0

    @classmethod
    def load(cls, path: str, name: str) -> TtfTarget:
        font = TTFont(path)
        return cls(
            name=name,
            path=path,
            font=font,
            em=float(font["head"].unitsPerEm),
            _original_modified=int(font["head"].modified),
        )

    @property
    def cmap(self) -> dict[int, str]:
        table: dict[int, str] | None = self.font.getBestCmap()
        if table is None:  # pragma: no cover - defensive
            raise ValueError(f"{self.name}: no usable cmap")
        return table

    def has(self, codepoint: int) -> bool:
        return codepoint in self.cmap

    def advance(self, codepoint: int) -> float:
        name = self.cmap[codepoint]
        advance, _lsb = self.font["hmtx"][name]
        return float(advance) / self.em

    def glyph(self, codepoint: int) -> Glyph:
        return from_ttf(self.font, self.cmap[codepoint])

    def add(self, codepoint: int, glyph: Glyph, advance: float, name: str | None = None) -> None:
        if self.has(codepoint):
            raise ValueError(f"{self.name}: U+{codepoint:04X} already exists")
        if name and name.isascii() and name.replace("_", "").isalnum():
            glyph_name = name  # an Adobe Glyph List name
        else:
            glyph_name = f"uni{codepoint:04X}"
        base = glyph_name
        suffix = 1
        while glyph_name in self.font.getGlyphOrder():
            glyph_name = f"{base}.{suffix}"
            suffix += 1
        tt_glyph = to_ttf(glyph, int(self.em))
        tt_glyph.recalcBounds(self.font["glyf"])
        # the glyf table owns the glyph order and appends on assignment; the
        # font-level order (used by 'post' at compile time) is resynced below
        self.font["glyf"][glyph_name] = tt_glyph
        self.font["hmtx"][glyph_name] = (round(advance * self.em), tt_glyph.xMin)
        self.font.setGlyphOrder(list(self.font["glyf"].glyphOrder))
        self._added.append(glyph_name)
        for subtable in self.font["cmap"].tables:
            encoding = (subtable.platformID, subtable.platEncID)
            if encoding in UNICODE_PLATFORM_ENCODINGS:
                if subtable.format == 12 or (subtable.format == 4 and codepoint <= 0xFFFF):
                    subtable.cmap[codepoint] = glyph_name
            elif encoding == (1, 0):
                self._add_mac_roman(subtable, codepoint, glyph_name)

    @staticmethod
    def _add_mac_roman(subtable: Any, codepoint: int, glyph_name: str) -> None:
        """Mirror the character into the legacy Macintosh subtable when it fits.

        The shipped faces carry a format 6 ``(1, 0)`` subtable covering a fixed
        range of Mac Roman codes.  A character is only added when Mac Roman can
        encode it, the resulting code lies inside that range, and nothing is
        mapped there yet - so no existing mapping is ever shadowed.
        """
        try:
            encoded = chr(codepoint).encode("mac_roman")
        except UnicodeEncodeError:
            return
        if len(encoded) != 1:
            return
        code = encoded[0]
        codes = list(subtable.cmap)
        if not codes or not min(codes) <= code <= max(codes):
            return
        subtable.cmap.setdefault(code, glyph_name)

    def save(self, path: str) -> None:
        if not self._added:
            raise ValueError(f"{self.name}: nothing to add")
        # fontTools stamps head.modified with the current time, which makes two
        # builds of the same sources differ: honour SOURCE_DATE_EPOCH, otherwise
        # keep the original timestamp so the build is reproducible
        epoch = os.environ.get("SOURCE_DATE_EPOCH")
        self.font["head"].modified = int(epoch) if epoch else self._original_modified
        self._mark_version()
        self.font.save(path)

    def _mark_version(self) -> None:
        """Say in the name table that this is a modified version of the font.

        The original carries no Reserved Font Name, so keeping the family name
        is allowed; marking the version is what makes the patched file
        identifiable and honest about being a Modified Version.
        """
        for record in self.font["name"].names:
            if record.nameID == 5 and VERSION_MARK not in record.toUnicode():
                record.string = f"{record.toUnicode()} {VERSION_MARK}"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def measure_scale(swf_font: DefineFont, reference: TTFont, tolerance: float = 0.01) -> float:
    """Twips per reference-font unit, measured from the two advance tables.

    The shipped movies are the desktop design converted to Flash at one uniform
    scale, so the ratio of every common advance is the same number; anything
    else means the two files are not the same design and the build must stop.
    """
    cmap = reference.getBestCmap()
    if cmap is None:  # pragma: no cover - defensive
        raise ValueError("reference font has no cmap")
    hmtx = reference["hmtx"]
    ratios = []
    for index, codepoint in enumerate(swf_font.code_table):
        if codepoint not in cmap:
            continue
        advance, _lsb = hmtx[cmap[codepoint]]
        if advance:
            ratios.append(swf_font.advances[index] / float(advance))
    if len(ratios) < 50:  # pragma: no cover - defensive
        raise ValueError("too few common codepoints to measure the scale")
    median = statistics.median(ratios)
    worst = max(abs(ratio - median) / median for ratio in ratios)
    if worst > tolerance:
        raise ValueError(
            f"advance ratios are not uniform (worst deviation {worst:.2%} > {tolerance:.2%})"
        )
    return median
