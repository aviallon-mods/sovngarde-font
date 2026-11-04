"""The SWF font codec, checked against the shipped movies.

These are the checks that made the format claims falsifiable: a byte-exact
glyph round trip proves the shape encoding, and the BoundsTable oracle (every
glyph must fit the rectangle the file itself carries) is what exposed the
``MoveTo`` records being absolute rather than relative.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sovngarde.swf import (
    TAG_DEFINEFONT3,
    DefineFont,
    Movie,
    encode_define_font,
    iter_tags,
)


def load_font(path: Path) -> tuple[Movie, DefineFont]:
    movie = Movie.load(path.read_bytes())
    fonts = movie.fonts()
    assert len(fonts) == 1, f"{path.name}: expected exactly one font tag"
    return movie, fonts[0][1]


def test_movies_are_compressed_definefont3(movie_paths: list[Path]) -> None:
    for path in movie_paths:
        movie = Movie.load(path.read_bytes())
        assert movie.signature == b"CWS", path.name
        tags = iter_tags(movie.body)
        assert any(tag.code == TAG_DEFINEFONT3 for tag in tags), path.name


def test_shipped_movies_declare_their_uncompressed_length(movie_paths: list[Path]) -> None:
    """FileLength is the decompressed size, header included - and we must keep it."""
    for path in movie_paths:
        movie = Movie.load(path.read_bytes())
        assert movie.declared_length == 8 + len(movie.body), path.name


def test_saving_a_movie_keeps_the_header_consistent(movie_paths: list[Path]) -> None:
    for path in movie_paths:
        movie = Movie.load(path.read_bytes())
        saved = Movie.load(movie.save())
        assert saved.declared_length == movie.declared_length, path.name
        assert saved.body == movie.body, path.name
        # the field written into the file is the *uncompressed* length, so it
        # must not be the length of the compressed file we just produced
        (written,) = struct.unpack_from("<I", movie.save(), 4)
        assert written == 8 + len(movie.body), path.name
        assert written != len(movie.save()) or movie.signature == b"FWS", path.name


def test_every_glyph_re_encodes_byte_for_byte(movie_paths: list[Path]) -> None:
    """read -> write must reproduce the shipped bytes for every single glyph."""
    for path in movie_paths:
        _, font = load_font(path)
        identical = 0
        for index in range(font.num_glyphs):
            shape = font.decode_shape(index)
            if shape.to_bytes() == font.shape_bytes(index):
                identical += 1
        assert identical == font.num_glyphs, f"{path.name}: {identical}/{font.num_glyphs}"


def test_font_tag_re_encodes_byte_for_byte(movie_paths: list[Path]) -> None:
    """The whole DefineFont3 tag, rebuilt with no new glyph, must be identical."""
    for path in movie_paths:
        movie = Movie.load(path.read_bytes())
        tag, font = movie.fonts()[0]
        assert encode_define_font(font, []) == tag.data, path.name


def test_every_glyph_fits_its_bounds_rectangle(movie_paths: list[Path]) -> None:
    """The BoundsTable is an independent oracle for the shape interpretation.

    An on-curve bounding box outside the rectangle the file carries for that
    glyph means the outlines were decoded with the wrong convention (a delta
    read as an absolute position, or a flipped axis).
    """
    tolerance = 2.0  # twips
    checked = 0
    for path in movie_paths:
        _, font = load_font(path)
        for index in range(font.num_glyphs):
            xmin, xmax, ymin, ymax = font.bounds[index]
            points = [
                (x, y)
                for x, y, kind in font.decode_shape(index).absolute_points()
                if kind != "ctrl"
            ]
            if not points:
                continue
            checked += 1
            assert min(p[0] for p in points) >= xmin - tolerance, (path.name, index)
            assert max(p[0] for p in points) <= xmax + tolerance, (path.name, index)
            assert min(p[1] for p in points) >= ymin - tolerance, (path.name, index)
            assert max(p[1] for p in points) <= ymax + tolerance, (path.name, index)
    assert checked > 1000, "the oracle must actually have looked at the glyphs"


def test_adding_a_glyph_shifts_every_offset(movie_paths: list[Path]) -> None:
    """Appending a glyph grows the offset table, so old offsets must move."""
    movie = Movie.load(movie_paths[0].read_bytes())
    tag, font = movie.fonts()[0]
    from sovngarde.geometry import to_swf

    shape = to_swf([[(-0.1, -0.1, True), (0.1, -0.1, True), (0.1, 0.1, True)]], 20482.4)
    data = encode_define_font(font, [(0x2E5C, shape, 500)])
    reparsed = Movie.load(movie.save(movie.replace_tag(tag, data)))
    _, patched = reparsed.fonts()[0]
    assert patched.num_glyphs == font.num_glyphs + 1
    # the old glyphs must still decode to the same shapes
    for index in range(font.num_glyphs):
        assert patched.decode_shape(index).to_bytes() == font.shape_bytes(index), index


@pytest.mark.parametrize("codepoint", [0x41, 0x2D, 0x20, 0x2019, 0x401])
def test_real_glyphs_decode_to_non_empty_shapes(movie_paths: list[Path], codepoint: int) -> None:
    _, font = load_font(movie_paths[0])
    index = font.glyph_by_code(codepoint)
    assert index is not None, f"U+{codepoint:04X} missing from the shipped font"
    shape = font.decode_shape(index)
    if codepoint != 0x20:  # space is genuinely empty
        assert shape.ops
        x0, y0, x1, y1 = shape.bbox()
        assert x1 > x0 and y1 > y0
