"""SWF container + DefineFont2/DefineFont3 reader/writer.

The Skyrim UI fonts shipped by the Sovngarde mod are Flash movies
(``Data/Interface/fonts_sovngarde.swf``) whose vector glyph outlines live in a
``DefineFont3`` tag.  This module locates those tags, decodes them (code table,
advance table, bounds table, glyph outlines) and can rewrite the movie with
modified font data while leaving every other byte of the movie untouched.

Layout notes discovered empirically on the Sovngarde / SovngardeConsole /
Drukaatie Burti movies of this mod (all three agree, and they match Ruffle's
reader):

* the movie is ``CWS`` (zlib);
* the font tag is ``DefineFont3`` (code 75) with ``HasLayout``, ``WideOffsets``
  and ``WideCodes`` set;
* the ``OffsetTable`` / ``CodeTableOffset`` values are relative to the **start of
  the OffsetTable field**, not to the start of the tag data.  That is what the
  Flash authoring tool wrote and what Scaleform GFx accepts:
  ``abs(glyph i) == header_len + offsets[i]``, where ``header_len`` is the size
  of the font header (FontID .. NumGlyphs), i.e. where the offset table starts;
* the tag does **not** end with the code table: after it come
  ``FontAscent/FontDescent/FontLeading`` (UI16 x3), the ``AdvanceTable``
  (UI16 per glyph, even with WideOffsets), the ``BoundsTable`` (one RECT per
  glyph) and a kerning table whose record count is a leading UI16;
* glyphs normally carry no style of their own: the shape starts with
  ``NumFillBits/NumLineBits`` and the fill/line styles are introduced by
  ``StateNewStyles`` records inside the outline.

Format reference: SWF File Format Specification v19, chapters "DefineFont2",
"Shape Data" and "Rect", cross-checked against Ruffle's ``swf/src/read.rs``.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Tag codes
# ---------------------------------------------------------------------------

TAG_END = 0
TAG_DEFINEFONTINFO = 13
TAG_DEFINEFONT2 = 48
TAG_DEFINEFONTINFO2 = 62
TAG_DEFINEFONTALIGNZONES = 73
TAG_CSMTEXTSETTINGS = 74
TAG_DEFINEFONT3 = 75
TAG_DEFINEFONTNAME = 88

#: A shape record.  The tuples are heterogeneous on purpose (their shape is
#: documented below); the codec validates them at write time.
#:
#:   ("style", fill0, fill1, line, move, move_bits)
#:   ("line", dx, dy, variant, nbits)
#:   ("curve", cx, cy, ax, ay, nbits)
#:   ("rawbits", raw, start_bit, end_bit, fill_bits, line_bits)
#:
#: ``None`` for a width means "let the encoder pick one".
Op = tuple[Any, ...]


# ---------------------------------------------------------------------------
# Bit level reader / writer (SWF packs fields MSB-first into bytes)
# ---------------------------------------------------------------------------


class BitReader:
    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos  # byte offset
        self.bit = 0  # bit offset inside current byte (0 = MSB)

    def read_ub(self, nbits: int) -> int:
        val = 0
        for _ in range(nbits):
            bit = (self.data[self.pos] >> (7 - self.bit)) & 1
            val = (val << 1) | bit
            self.bit += 1
            if self.bit == 8:
                self.bit = 0
                self.pos += 1
        return val

    def read_sb(self, nbits: int) -> int:
        if nbits == 0:
            return 0
        val = self.read_ub(nbits)
        if val & (1 << (nbits - 1)):
            val -= 1 << nbits
        return val

    def read_u8(self) -> int:
        return self.read_ub(8)

    def read_u16(self) -> int:
        """UI16: little endian, safe to call at any bit offset."""
        lo = self.read_u8()
        hi = self.read_u8()
        return lo | (hi << 8)

    def read_u32(self) -> int:
        lo = self.read_u16()
        hi = self.read_u16()
        return lo | (hi << 16)

    def skip(self, nbytes: int) -> None:
        assert self.bit == 0
        self.pos += nbytes

    def read_rect(self) -> tuple[int, int, int, int]:
        """RECT: nbits UB[5] then 4 x SB[nbits]. Returns (xmin, xmax, ymin, ymax)."""
        nbits = self.read_ub(5)
        xmin = self.read_sb(nbits)
        xmax = self.read_sb(nbits)
        ymin = self.read_sb(nbits)
        ymax = self.read_sb(nbits)
        return xmin, xmax, ymin, ymax

    def align(self) -> None:
        if self.bit:
            self.bit = 0
            self.pos += 1


class BitWriter:
    def __init__(self) -> None:
        self.buf = bytearray()
        self.bit = 0

    def write_ub(self, value: int, nbits: int) -> None:
        for i in range(nbits - 1, -1, -1):
            if self.bit == 0:
                self.buf.append(0)
            if (value >> i) & 1:
                self.buf[-1] |= 1 << (7 - self.bit)
            self.bit = (self.bit + 1) % 8

    def write_sb(self, value: int, nbits: int) -> None:
        if nbits == 0:
            return
        if value < 0:
            value += 1 << nbits
        self.write_ub(value, nbits)

    def write_raw_bits(self, raw: bytes, start_bit: int, end_bit: int) -> None:
        for i in range(start_bit, end_bit):
            self.write_ub((raw[i >> 3] >> (7 - (i & 7))) & 1, 1)

    def align(self) -> None:
        self.bit = 0

    def bit_offset(self) -> int:
        """Number of bits written so far."""
        if self.bit:
            return (len(self.buf) - 1) * 8 + self.bit
        return len(self.buf) * 8

    def getvalue(self) -> bytes:
        assert self.bit == 0
        return bytes(self.buf)


def minimal_signed_bits(*values: int) -> int:
    """Smallest two's-complement width able to hold every value (0 if all zero)."""
    if all(value == 0 for value in values):
        return 0
    nbits = 0
    for value in values:
        need = 1
        while not (-(1 << (need - 1)) <= value < (1 << (need - 1))):
            need += 1
            if need > 32:  # pragma: no cover - defensive
                raise ValueError(f"no signed field is wide enough for {value}")
        nbits = max(nbits, need)
    return nbits


def flash_signed_bits(*values: int) -> int:
    """Width the Flash authoring tool uses: unsigned magnitude width + sign bit.

    This is one bit wider than the minimal two's-complement width whenever the
    largest magnitude is exactly a power of two, which is what the shipped
    Sovngarde movie contains (e.g. a -512 delta is written with 11 bits).
    """
    largest = max((abs(v) for v in values), default=0)
    if largest == 0:
        return 0
    return largest.bit_length() + 1


def pick_width(*values: int, minimum: int = 0) -> int:
    """Width for a value written by this tool (Flash-compatible, minimal for 0)."""
    return max(flash_signed_bits(*values), minimum)


def nbits_for_index(value: int) -> int:
    nbits = 0
    while (1 << nbits) <= value:
        nbits += 1
    return nbits


# ---------------------------------------------------------------------------
# SHAPE records
# ---------------------------------------------------------------------------


@dataclass
class Shape:
    """Decoded glyph outline.  ``ops`` round-trips through :meth:`to_bytes`."""

    ops: list[Op] = field(default_factory=list)
    num_fill_bits: int = 0
    num_line_bits: int = 0

    # -- encoding ---------------------------------------------------------

    def write_ops(self, w: BitWriter, offsets: list[int] | None = None) -> None:
        """Write the header widths then every op (no end record).

        ``offsets``, when given, collects the bit offset of every op in the
        unaligned stream (the 8 header bits included).
        """
        fill_bits, line_bits = self.num_fill_bits, self.num_line_bits
        w.write_ub(fill_bits, 4)
        w.write_ub(line_bits, 4)
        for op in self.ops:
            if offsets is not None:
                offsets.append(w.bit_offset())
            if op[0] == "style":
                _, fill0, fill1, line, move, move_bits = op
                w.write_ub(0, 1)  # TypeFlag = 0 (non-edge)
                # StateNewStyles, StateLineStyle, StateFillStyle1,
                # StateFillStyle0, StateMoveTo - all clear means EndOfShape
                w.write_ub(0, 1)
                w.write_ub(1 if line is not None else 0, 1)
                w.write_ub(1 if fill1 is not None else 0, 1)
                w.write_ub(1 if fill0 is not None else 0, 1)
                w.write_ub(1 if move is not None else 0, 1)
                if move is not None:
                    dx, dy = move
                    nbits = pick_width(dx, dy) if move_bits is None else move_bits
                    w.write_ub(nbits, 5)
                    w.write_sb(dx, nbits)
                    w.write_sb(dy, nbits)
                if fill0 is not None:
                    w.write_ub(fill0, fill_bits)
                if fill1 is not None:
                    w.write_ub(fill1, fill_bits)
                if line is not None:
                    w.write_ub(line, line_bits)
            elif op[0] == "line":
                _, dx, dy, variant, nbits = op
                if variant == "general":
                    width = max(pick_width(dx, dy), 2) if nbits is None else nbits
                    w.write_ub(1, 1)  # TypeFlag = edge
                    w.write_ub(1, 1)  # StraightFlag
                    w.write_ub(width - 2, 4)
                    w.write_ub(1, 1)  # GeneralLineFlag
                    w.write_sb(dx, width)
                    w.write_sb(dy, width)
                elif variant == "vertical":
                    width = max(pick_width(dy), 2) if nbits is None else nbits
                    w.write_ub(1, 1)
                    w.write_ub(1, 1)
                    w.write_ub(width - 2, 4)
                    w.write_ub(0, 1)  # not general
                    w.write_ub(1, 1)  # vertical
                    w.write_sb(dy, width)
                else:  # horizontal
                    width = max(pick_width(dx), 2) if nbits is None else nbits
                    w.write_ub(1, 1)
                    w.write_ub(1, 1)
                    w.write_ub(width - 2, 4)
                    w.write_ub(0, 1)  # not general
                    w.write_ub(0, 1)  # not vertical
                    w.write_sb(dx, width)
            elif op[0] == "curve":
                _, cx, cy, ax, ay, nbits = op
                width = max(pick_width(cx, cy, ax, ay), 2) if nbits is None else nbits
                w.write_ub(1, 1)  # TypeFlag = edge
                w.write_ub(0, 1)  # CurvedFlag
                w.write_ub(width - 2, 4)
                w.write_sb(cx, width)
                w.write_sb(cy, width)
                w.write_sb(ax, width)
                w.write_sb(ay, width)
            else:  # pragma: no cover - defensive
                raise ValueError(f"unknown op {op!r}")

    def to_bytes(self) -> bytes:
        w = BitWriter()
        self.write_ops(w)
        w.write_ub(0, 1)  # TypeFlag = 0
        w.write_ub(0, 5)  # all state flags clear = EndOfShape
        w.align()
        return w.getvalue()

    def op_bit_offsets(self) -> list[int]:
        """Bit offset of each op in the unaligned stream (8 header bits included)."""
        w = BitWriter()
        offsets: list[int] = []
        self.write_ops(w, offsets)
        return offsets

    # -- geometry ---------------------------------------------------------

    def absolute_points(self) -> list[tuple[float, float, str]]:
        """Absolute (x, y, kind) points, kind in {move, line, ctrl, anchor}.

        A move record in a font glyph shape carries an absolute position (see
        :func:`sovngarde.geometry.from_swf` for the evidence).
        """
        x = y = 0.0
        pts: list[tuple[float, float, str]] = []
        for op in self.ops:
            if op[0] == "style":
                move = op[4]
                if move is not None:
                    x, y = float(move[0]), float(move[1])
                    pts.append((x, y, "move"))
            elif op[0] == "line":
                x += op[1]
                y += op[2]
                pts.append((x, y, "line"))
            elif op[0] == "curve":
                cx = x + op[1]
                cy = y + op[2]
                x = cx + op[3]
                y = cy + op[4]
                pts.append((cx, cy, "ctrl"))
                pts.append((x, y, "anchor"))
        return pts

    def bbox(self, on_curve_only: bool = False) -> tuple[float, float, float, float]:
        """(xmin, ymin, xmax, ymax); an empty shape (e.g. space) gives all zeros.

        ``on_curve_only`` reproduces what the Flash authoring tool put in the
        font's BoundsTable: that rectangle is the bounding box of the on-curve
        points, so a curve bulging past them legitimately sticks out of it
        (verified against all 1171 glyphs of the three shipped movies).
        """
        pts = [
            (x, y) for x, y, kind in self.absolute_points() if not on_curve_only or kind != "ctrl"
        ]
        if not pts:
            return 0.0, 0.0, 0.0, 0.0
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)


def read_matrix(br: BitReader) -> None:
    """Skip a MATRIX record: optional scale, optional rotate/skew, translate."""
    if br.read_ub(1):
        nbits = br.read_ub(5)
        br.read_sb(nbits)
        br.read_sb(nbits)
    if br.read_ub(1):
        nbits = br.read_ub(5)
        br.read_sb(nbits)
        br.read_sb(nbits)
    nbits = br.read_ub(5)
    br.read_sb(nbits)
    br.read_sb(nbits)


def read_fill_style_array(br: BitReader, color_bytes: int, extended_count: bool = False) -> None:
    """Skip a FILLSTYLEARRAY (only ``StateNewStyles`` needs this)."""
    count = br.read_u8()
    if count == 0xFF and extended_count:
        count = br.read_u16()
    for _ in range(count):
        fill_type = br.read_u8()
        if fill_type == 0x00:  # solid
            br.skip(color_bytes)
        elif fill_type in (0x10, 0x12, 0x13):  # linear / radial / focal radial
            read_matrix(br)
            if fill_type == 0x13:
                br.skip(4)  # FocalPoint, FIXED 16.16
            for _ in range(br.read_u8()):
                br.skip(1 + color_bytes)  # Ratio UI8 + Color
        elif fill_type in (0x40, 0x41, 0x42, 0x43):  # bitmap fills
            br.skip(2)  # BitmapId
            read_matrix(br)
        else:  # pragma: no cover - defensive
            raise ValueError(f"unknown fill style type {fill_type:#04x}")


def read_line_style_array(br: BitReader, color_bytes: int, extended_count: bool = False) -> None:
    """Skip a LINESTYLEARRAY: Width UI16 then a colour per style."""
    count = br.read_u8()
    if count == 0xFF and extended_count:
        count = br.read_u16()
    for _ in range(count):
        br.skip(2 + color_bytes)


def read_shape(br: BitReader, color_bytes: int = 3, extended_count: bool = False) -> Shape:
    """Decode one glyph outline.

    DefineFont2/3 shapes are "shape version 1" as far as colours are concerned
    (RGB) and no style counts are extended, hence the defaults.
    """
    num_fill_bits = br.read_ub(4)
    num_line_bits = br.read_ub(4)
    orig_fill_bits, orig_line_bits = num_fill_bits, num_line_bits
    ops: list[Op] = []
    while True:
        if br.read_ub(1) == 0:
            # the five state bits double as the EndOfShape marker when all clear
            new_styles = br.read_ub(1)
            line = br.read_ub(1)
            fill1 = br.read_ub(1)
            fill0 = br.read_ub(1)
            move = br.read_ub(1)
            if not (new_styles or line or fill1 or fill0 or move):
                break
            move_pair = None
            move_bits = None
            if move:
                move_bits = br.read_ub(5)
                move_pair = (br.read_sb(move_bits), br.read_sb(move_bits))
            f0 = br.read_ub(num_fill_bits) if fill0 else None
            f1 = br.read_ub(num_fill_bits) if fill1 else None
            ln = br.read_ub(num_line_bits) if line else None
            ops.append(("style", f0, f1, ln, move_pair, move_bits))
            if new_styles:
                first_byte, first_bit = br.pos, br.bit
                read_fill_style_array(br, color_bytes, extended_count)
                read_line_style_array(br, color_bytes, extended_count)
                num_fill_bits = br.read_ub(4)
                num_line_bits = br.read_ub(4)
                raw = br.data[first_byte : br.pos + (1 if br.bit else 0)]
                start_bit = first_bit
                end_bit = (br.pos - first_byte) * 8 + br.bit
                ops.append(("rawbits", raw, start_bit, end_bit, num_fill_bits, num_line_bits))
        else:
            is_straight = br.read_ub(1)
            # the 4-bit field encodes num_bits - 2 (so a 0 means two bits)
            nbits = br.read_ub(4) + 2
            if is_straight:
                general = br.read_ub(1)
                if general:
                    ops.append(("line", br.read_sb(nbits), br.read_sb(nbits), "general", nbits))
                elif br.read_ub(1):  # vertical
                    ops.append(("line", 0, br.read_sb(nbits), "vertical", nbits))
                else:
                    ops.append(("line", br.read_sb(nbits), 0, "horizontal", nbits))
            else:
                ops.append(
                    (
                        "curve",
                        br.read_sb(nbits),
                        br.read_sb(nbits),
                        br.read_sb(nbits),
                        br.read_sb(nbits),
                        nbits,
                    )
                )
    br.align()
    return Shape(ops, orig_fill_bits, orig_line_bits)


def encode_rect(xmin: int, xmax: int, ymin: int, ymax: int) -> bytes:
    """Encode a RECT with the smallest possible bit count."""
    nbits = minimal_signed_bits(xmin, xmax, ymin, ymax)
    w = BitWriter()
    w.write_ub(nbits, 5)
    w.write_sb(xmin, nbits)
    w.write_sb(xmax, nbits)
    w.write_sb(ymin, nbits)
    w.write_sb(ymax, nbits)
    w.align()
    return w.getvalue()


# ---------------------------------------------------------------------------
# DefineFont2 / DefineFont3
# ---------------------------------------------------------------------------


@dataclass
class DefineFont:
    tag_code: int
    font_id: int
    flags: int
    language_code: int | None
    font_name: str
    header_len: int
    shapes: bytes  # raw GlyphShapeTable bytes
    shape_offsets: list[int]  # as stored: relative to header_len
    shape_base: int  # == shape_offsets[0], offset of the shape table itself
    code_table: list[int]
    ascent: int
    descent: int
    leading: int
    advances: list[int]
    advance_size: int  # 2 or 4 bytes per AdvanceTable entry
    bounds_raw: bytes  # raw BoundsTable bytes
    bounds: list[tuple[int, int, int, int]]
    bounds_spans: list[tuple[int, int]]  # per glyph, byte range inside bounds_raw
    kerning_raw: bytes

    @property
    def num_glyphs(self) -> int:
        return len(self.code_table)

    @property
    def wide_offsets(self) -> bool:
        return bool(self.flags & 0x08)

    @property
    def wide_codes(self) -> bool:
        return bool(self.flags & 0x04)

    @property
    def has_layout(self) -> bool:
        return bool(self.flags & 0x80)

    def codes(self) -> dict[int, int]:
        """character code -> glyph index"""
        return {code: i for i, code in enumerate(self.code_table)}

    def glyph_by_code(self, code: int) -> int | None:
        return self.codes().get(code)

    def glyph_records(self) -> list[GlyphRecord]:
        """Per-glyph data, in the order the file stores it."""
        records = []
        for index in range(self.num_glyphs):
            start, end = self.bounds_spans[index]
            shape_start, shape_end = self.shape_slice(index)
            records.append(
                GlyphRecord(
                    code=self.code_table[index],
                    shape=self.shapes[shape_start:shape_end],
                    advance=self.advances[index],
                    bounds=self.bounds_raw[start:end],
                )
            )
        return records

    def shape_slice(self, index: int) -> tuple[int, int]:
        """(start, end) of glyph ``index``'s shape inside :attr:`shapes`."""
        start = self.shape_offsets[index] - self.shape_base
        if index + 1 < self.num_glyphs:
            end = self.shape_offsets[index + 1] - self.shape_base
        else:
            end = len(self.shapes)
        return start, end

    def decode_shape(self, index: int) -> Shape:
        start, _ = self.shape_slice(index)
        return read_shape(BitReader(self.shapes, start))

    def shape_bytes(self, index: int) -> bytes:
        start, end = self.shape_slice(index)
        return self.shapes[start:end]

    def decode_all_shapes(self) -> list[Shape]:
        out = []
        for i in range(self.num_glyphs):
            start, end = self.shape_slice(i)
            br = BitReader(self.shapes, start)
            shape = read_shape(br)
            if br.pos != end:  # pragma: no cover - defensive
                raise ValueError(f"glyph {i} does not end where its offset says")
            out.append(shape)
        return out


def _is_plausible_tail(data: bytes, pos: int, leftover: int, wide_codes: bool) -> bool:
    """Is what follows the BoundsTable a whole number of kerning records?

    The kerning table is a UI16 record count followed by records of (left code,
    right code, adjustment), the codes being UI8 or UI16 with the font's own
    code width.  Anything else means the tables above it were misread.
    """
    if leftover == 0:
        return True
    if leftover < 2:
        return False
    count = int(struct.unpack_from("<H", data, pos)[0])
    record = (2 if wide_codes else 1) * 2 + 2
    return leftover == 2 + count * record


def _read_define_font_name(data: bytes, pos: int, name_len: int) -> str:
    return data[pos : pos + name_len].decode("utf-8", errors="replace")


def parse_define_font(data: bytes, tag_code: int) -> DefineFont:
    br = BitReader(data)
    font_id = br.read_u16()
    flags = br.read_u8()
    has_layout = bool(flags & 0x80)
    wide_offsets = bool(flags & 0x08)
    wide_codes = bool(flags & 0x04)
    if not has_layout:
        raise NotImplementedError("DefineFont without layout is not supported")
    language_code = br.read_u8()
    name_len = br.read_u8()
    name = _read_define_font_name(data, br.pos, name_len)
    br.skip(name_len)
    num_glyphs = br.read_u16()
    header_len = br.pos

    if num_glyphs == 0:  # pragma: no cover - defensive
        raise NotImplementedError("empty fonts are not supported")

    shape_offsets = [br.read_u32() if wide_offsets else br.read_u16() for _ in range(num_glyphs)]
    code_table_offset = br.read_u32() if wide_offsets else br.read_u16()
    shapes_start = header_len + shape_offsets[0]
    code_table_start = header_len + code_table_offset

    shapes = data[shapes_start:code_table_start]
    code_size = 2 if wide_codes else 1
    code_fmt = "<H" if wide_codes else "<B"
    code_table = [
        struct.unpack_from(code_fmt, data, code_table_start + code_size * i)[0]
        for i in range(num_glyphs)
    ]
    pos = code_table_start + num_glyphs * (2 if wide_codes else 1)
    (ascent, descent, leading) = struct.unpack_from("<3H", data, pos)
    pos += 6

    # The AdvanceTable is UI16 even when WideOffsets is set (what the Flash
    # authoring tool wrote); accept either by keeping the candidate whose bounds
    # table consumes the tag exactly.
    chosen: (
        tuple[int, list[int], list[tuple[int, int, int, int]], list[tuple[int, int]], int] | None
    ) = None
    for advance_size in (2, 4):
        fmt = "<I" if advance_size == 4 else "<H"
        try:
            advances = [
                struct.unpack_from(fmt, data, pos + advance_size * i)[0] for i in range(num_glyphs)
            ]
            bounds_start_abs = pos + advance_size * num_glyphs
            bounds_br = BitReader(data, bounds_start_abs)
            bounds: list[tuple[int, int, int, int]] = []
            spans: list[tuple[int, int]] = []
            for _ in range(num_glyphs):
                rect_start = bounds_br.pos
                bounds.append(bounds_br.read_rect())
                bounds_br.align()
                spans.append((rect_start - bounds_start_abs, bounds_br.pos - bounds_start_abs))
        except (IndexError, struct.error):
            continue
        leftover = len(data) - bounds_br.pos
        if not _is_plausible_tail(data, bounds_br.pos, leftover, wide_codes):
            continue
        if chosen is None:
            chosen = (advance_size, advances, bounds, spans, bounds_br.pos)
    if chosen is None:
        raise ValueError("could not locate the AdvanceTable/BoundsTable (no size fits the tag)")
    advance_size, advances, bounds, spans, bounds_end = chosen
    bounds_start = pos + advance_size * num_glyphs
    bounds_raw = data[bounds_start:bounds_end]
    kerning_raw = data[bounds_end:]

    return DefineFont(
        tag_code=tag_code,
        font_id=font_id,
        flags=flags,
        language_code=language_code,
        font_name=name,
        header_len=header_len,
        shapes=shapes,
        shape_offsets=shape_offsets,
        shape_base=shape_offsets[0],
        code_table=code_table,
        ascent=ascent,
        descent=descent,
        leading=leading,
        advances=advances,
        advance_size=advance_size,
        bounds_raw=bounds_raw,
        bounds=bounds,
        bounds_spans=spans,
        kerning_raw=kerning_raw,
    )


def bbox_rect(shape: Shape) -> tuple[int, int, int, int]:
    """The BoundsTable rectangle for a glyph, following the shipped convention."""
    x0, y0, x1, y1 = shape.bbox(on_curve_only=True)
    return int(x0), int(x1), int(y0), int(y1)


@dataclass
class GlyphRecord:
    """Everything the tag stores per glyph, kept together so it can be reordered."""

    code: int
    shape: bytes
    advance: int
    bounds: bytes


def encode_define_font(font: DefineFont, new_glyphs: list[tuple[int, Shape, int]]) -> bytes:
    """Return tag data with ``new_glyphs`` added.

    ``new_glyphs`` is a list of ``(character_code, shape, advance)``.  Glyphs
    are stored in **ascending code order**, which is what every Flash-authored
    font does and what Scaleform's per-character lookup expects: appending codes
    at the end would leave the table unsorted and put an existing code (here the
    euro sign) out of order.
    """
    wide_offsets = font.wide_offsets
    wide_codes = font.wide_codes
    header_len = font.header_len

    records = list(font.glyph_records())
    known = {record.code for record in records}
    for code, shape, advance in new_glyphs:
        if code in known:
            raise ValueError(f"U+{code:04X} is already in the font")
        if not wide_codes and code > 0xFF:
            raise ValueError(
                f"U+{code:04X} does not fit this font's narrow code table (WideCodes is off)"
            )
        known.add(code)
        records.append(GlyphRecord(code, shape.to_bytes(), advance, encode_rect(*bbox_rect(shape))))
    records.sort(key=lambda record: record.code)

    table_size = 4 if wide_offsets else 2
    # offsets are relative to the start of the offset table, which holds one
    # entry per glyph plus the code table offset itself
    cursor = (len(records) + 1) * table_size
    offsets = []
    for record in records:
        offsets.append(cursor)
        cursor += len(record.shape)
    code_table_offset = cursor

    off_fmt = "<I" if wide_offsets else "<H"
    out = bytearray()
    out += struct.pack("<HB", font.font_id, font.flags)
    out += bytes([font.language_code or 0, len(font.font_name)])
    out += font.font_name.encode("utf-8")
    out += struct.pack("<H", len(records))
    if len(out) != header_len:  # pragma: no cover - defensive
        raise ValueError(f"header is {len(out)} bytes, expected {header_len}")
    for offset in offsets:
        out += struct.pack(off_fmt, offset)
    out += struct.pack(off_fmt, code_table_offset)
    if len(out) != header_len + offsets[0]:
        raise ValueError(f"shape table does not start where the first offset says ({len(out)})")
    for record in records:
        out += record.shape
    for record in records:
        out += struct.pack("<H", record.code) if wide_codes else bytes([record.code])
    out += struct.pack("<3H", font.ascent, font.descent, font.leading)
    adv_fmt = "<I" if font.advance_size == 4 else "<H"
    for record in records:
        out += struct.pack(adv_fmt, record.advance)
    for record in records:
        out += record.bounds
    out += font.kerning_raw
    return bytes(out)


# ---------------------------------------------------------------------------
# Tag stream / movie container
# ---------------------------------------------------------------------------


@dataclass
class Tag:
    code: int
    data: bytes
    offset: int  # offset of the TagCodeAndLength field inside the movie body
    size: int  # total size of the tag in the body, header included


def iter_tags(body: bytes) -> list[Tag]:
    br = BitReader(body)
    br.read_rect()
    br.align()
    pos = br.pos + 4  # FrameRate UI16 + FrameCount UI16
    tags: list[Tag] = []
    while pos < len(body):
        start = pos
        (code_and_len,) = struct.unpack_from("<H", body, pos)
        pos += 2
        code = code_and_len >> 6
        length = code_and_len & 0x3F
        if length == 0x3F:
            (length,) = struct.unpack_from("<I", body, pos)
            pos += 4
        tags.append(
            Tag(code=code, data=body[pos : pos + length], offset=start, size=pos - start + length)
        )
        pos += length
        if code == TAG_END:
            break
    return tags


def encode_tag(code: int, data: bytes) -> bytes:
    out = bytearray()
    if len(data) < 0x3F:
        out += struct.pack("<H", (code << 6) | len(data))
    else:
        out += struct.pack("<H", (code << 6) | 0x3F)
        out += struct.pack("<I", len(data))
    out += data
    return bytes(out)


@dataclass
class Movie:
    signature: bytes  # b'FWS', b'CWS' or b'ZWS'
    version: int
    body: bytes  # decompressed, starting at the FrameSize RECT
    declared_length: int

    @classmethod
    def load(cls, raw: bytes) -> Movie:
        signature = raw[:3]
        version = raw[3]
        (length,) = struct.unpack_from("<I", raw, 4)
        payload = raw[8:]
        if signature == b"CWS":
            body = zlib.decompress(payload)
        elif signature == b"FWS":
            body = payload
        else:
            raise NotImplementedError(f"compression not supported: {signature!r}")
        return cls(signature, version, body, length)

    def save(self, body: bytes | None = None) -> bytes:
        body = self.body if body is None else body
        payload = zlib.compress(body, 9) if self.signature == b"CWS" else body
        return (
            self.signature
            + bytes([self.version])
            # FileLength is the *uncompressed* size, header included
            + struct.pack("<I", 8 + len(body))
            + payload
        )

    def fonts(self) -> list[tuple[Tag, DefineFont]]:
        out = []
        for tag in iter_tags(self.body):
            if tag.code in (TAG_DEFINEFONT2, TAG_DEFINEFONT3):
                out.append((tag, parse_define_font(tag.data, tag.code)))
        return out

    def replace_tag(self, tag: Tag, data: bytes) -> bytes:
        return (
            self.body[: tag.offset]
            + encode_tag(tag.code, data)
            + self.body[tag.offset + tag.size :]
        )
