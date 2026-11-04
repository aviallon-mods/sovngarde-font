#!/usr/bin/env python3
"""Render a preview sheet of font glyphs to PNG.

Examples::

    # every glyph a target already has, one line per 32 codepoints
    nix develop -c python3 tools/preview.py --ttf "Sovngarde Bold.ttf" --all

    # the glyphs this project adds, plus a DejaVu row for comparison
    nix develop -c python3 tools/preview.py --ttf new.ttf --text "— – … • × ÷ ± ² ™ ©"

The preview draws from the same canonical contours the build writes, so what
is rendered is exactly the geometry that goes into the font.  ``--freetype``
additionally renders the TTF with Pillow's own renderer, independently of this
project's rasteriser.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sovngarde.geometry import Glyph, render_line, write_png
from sovngarde.targets import SwfTarget, Target, TtfTarget

DEFAULT_SAMPLE = (
    "— The quick brown fox — jumps over… «quoted» “quoted” "
    "• bullet × ÷ ± ¹ ² ³ ™ © ® ‹x› † ‡ ≠ ≤ ≥ ¼ ½ ¾ – -- --- …"
)


def load_target(args: argparse.Namespace) -> Target:
    if args.ttf:
        return TtfTarget.load(args.ttf, Path(args.ttf).stem)
    if args.swf:
        # the em size is derived from the companion TTF by the build; for a
        # preview, accept it explicitly
        if args.em is None:
            raise SystemExit("--swf needs --em (twips per em, e.g. 20482.4)")
        return SwfTarget.load(args.swf, Path(args.swf).stem, args.em)
    raise SystemExit("give --ttf or --swf")


def line_for(target: Target, chars: str) -> list[tuple[Glyph, float]]:
    items: list[tuple[Glyph, float]] = []
    for char in chars:
        codepoint = ord(char)
        if target.has(codepoint):
            items.append((target.glyph(codepoint), target.advance(codepoint)))
        else:
            items.append(([], 0.4))
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ttf")
    parser.add_argument("--swf")
    parser.add_argument("--em", type=float, help="em size in twips, for --swf")
    parser.add_argument("--text", action="append", default=[])
    parser.add_argument("--all", action="store_true", help="render every glyph the target has")
    parser.add_argument("--size", type=int, default=40)
    parser.add_argument("--out", default="preview.png")
    parser.add_argument("--freetype", action="store_true", help="also render the TTF with Pillow")
    args = parser.parse_args()

    target = load_target(args)
    lines = list(args.text) or [DEFAULT_SAMPLE]
    if args.all:
        codes = sorted(cp for cp in range(0x20, 0x3000) if target.has(cp))
        lines = ["".join(chr(cp) for cp in codes[i : i + 32]) for i in range(0, len(codes), 32)]

    rendered = [render_line(line_for(target, text), args.size) for text in lines]
    width = max(r[0] for r in rendered)
    height = sum(r[1] for r in rendered) + 4 * len(rendered)
    canvas = bytearray(b"\xff" * (width * height * 3))
    offset = 0
    for w, h, pixels in rendered:
        for row in range(h):
            start = (row * w) * 3
            dest = ((offset + row) * width) * 3
            canvas[dest : dest + w * 3] = pixels[start : start + w * 3]
        offset += h + 4
    write_png(args.out, width, height, bytes(canvas))
    print(f"wrote {args.out} ({width}x{height}), {len(lines)} line(s)")

    if args.freetype:
        if not args.ttf:
            raise SystemExit("--freetype needs --ttf")
        from PIL import Image, ImageDraw, ImageFont

        font = ImageFont.truetype(args.ttf, args.size)
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        y = 0
        for text in lines:
            draw.text((4, y), text, font=font, fill="black")
            y += args.size + 12
        out = str(Path(args.out).with_suffix(".freetype.png"))
        image.save(out)
        print(f"wrote {out} (rendered by FreeType, not by this project)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
