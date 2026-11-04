#!/usr/bin/env python3
"""Report which "usual" characters each shipped font lacks.

Reads every font in ``upstream/`` and compares its coverage with a list of
characters that actually turn up in game text and mod UIs, grouped by Unicode
block, so the missing ones can be prioritised.

    nix develop -c python3 tools/coverage.py            # human report
    nix develop -c python3 tools/coverage.py --markdown > docs/coverage.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fontTools.ttLib import TTFont

from sovngarde.swf import Movie
from sovngarde.targets import measure_scale

REPO = Path(__file__).resolve().parent.parent
UPSTREAM = REPO / "upstream"

#: characters that are common in localised game text, mod descriptions and UIs.
#: The keys are the block names used in the report.
CANDIDATES: dict[str, str] = {
    "Latin-1 punctuation and signs": "\u00a0\u00a1\u00a2\u00a3\u00a4\u00a5\u00a6\u00a7\u00a8\u00a9"
    "\u00aa\u00ab\u00ac\u00ad\u00ae\u00af\u00b0\u00b1\u00b2\u00b3\u00b4\u00b5\u00b6\u00b7\u00b8\u00b9"
    "\u00ba\u00bb\u00bc\u00bd\u00be\u00bf\u00d7\u00f7",
    "Latin Extended-A (Central-European)": "\u0152\u0153\u0160\u0161\u0178\u0179\u017a\u017b\u017c"
    "\u017d\u017e\u0104\u0105\u0106\u0107\u0118\u0119\u0141\u0142\u0143\u0144\u015a\u015b",
    "Spacing modifiers and superscripts": "\u02c6\u02c7\u02d8\u02d9\u02da\u02db\u02dc\u02dd"
    "\u02c9\u02ba\u02b9\u2032\u2033\u2070\u2074\u2075\u2076\u2077\u2078\u2079",
    "General punctuation": "\u2010\u2011\u2012\u2013\u2014\u2015\u2018\u2019\u201a\u201b"
    "\u201c\u201d\u201e\u201f\u2020\u2021\u2022\u2023\u2024\u2025\u2026\u2027"
    "\u2030\u2039\u203a\u203d\u2044",
    "Currency": "\u20a3\u20a4\u20a6\u20a7\u20a9\u20aa\u20ab\u20b1\u20b4\u20bd\u20bf",
    "Letterlike symbols": "\u2103\u2109\u2116\u2117\u211e\u2120\u2122\u2126\u212b\u212e\u2135",
    "Arrows": "\u2190\u2191\u2192\u2193\u2194\u2195\u2196\u2197\u2198\u2199"
    "\u21a9\u21aa\u21d0\u21d2\u21d4",
    "Mathematical operators": "\u2200\u2202\u2203\u2205\u2207\u2208\u2209\u220b\u220f\u2211\u2212"
    "\u2213\u2217\u221a\u221d\u221e\u2220\u2223\u2225\u2228\u2229\u222a\u222b\u222e\u2234\u2235"
    "\u2237\u2248\u2249\u2260\u2261\u2262\u2264\u2265\u226a\u226b\u226e\u226f\u2282\u2283\u2295"
    "\u2297\u22a2\u22a3\u22c5\u22c6\u22ee\u22ef\u22f1\u2308\u2309\u230a\u230b\u2320\u2321\u2393",
    "Miscellaneous technical / symbols": "\u2423\u25a0\u25a1\u25aa\u25ab\u25b2\u25b3\u25b6\u25b7"
    "\u25bc\u25bd\u25c0\u25c1\u25ca\u25cb\u25cf\u25d0\u25d1\u2605\u2606\u260e\u2610\u2611\u2612"
    "\u261b\u261e\u263a\u263b\u263c\u2660\u2663\u2665\u2666\u266a\u266b\u2691\u2699\u26a0\u26a1",
    "Dingbats": "\u2713\u2714\u2717\u2718\u2726\u2730\u2756\u2762\u2794\u27a1\u27b0\u2b05\u2b06"
    "\u2b07\u2b1b\u2b1c\u2b50\u2b55",
    "Greek and Cyrillic extras": "\u0384\u0385\u0386\u0388\u0389\u038a\u038c\u038e\u038f\u0390"
    "\u03aa\u03ab\u03b0\u03ac\u03ad\u03ae\u03af\u03b1\u03b2\u03b3\u03b4\u03c0\u03c3\u03c4\u03c6"
    "\u03c9\u0400\u0403\u0409\u040a\u040c\u040f\u0452\u0455\u0459\u045a\u045b\u045f\u0490\u0491"
    "\u20b4",
}


def swf_coverage(path: Path, reference: Path) -> set[int]:
    movie = Movie.load(path.read_bytes())
    tag, font = movie.fonts()[0]
    del tag
    try:
        measure_scale(font, TTFont(str(reference)))
    except ValueError as error:  # pragma: no cover - defensive
        print(f"warning: {path.name}: {error}", file=sys.stderr)
    return set(font.code_table)


def ttf_coverage(path: Path) -> set[int]:
    cmap = TTFont(str(path)).getBestCmap()
    return set(cmap or {})


def collect() -> dict[str, set[int]]:
    fonts: dict[str, set[int]] = {}
    interface = UPSTREAM / "mod" / "Data" / "Interface"
    reference = UPSTREAM / "desktop" / "Sovngarde" / "Sovngarde Bold.ttf"
    for name in ("fonts_sovngarde.swf", "fonts_sovngardeconsole.swf", "fonts_drukaatieburti.swf"):
        fonts[name] = swf_coverage(interface / name, reference)
    for path in sorted((UPSTREAM / "desktop").rglob("*.ttf")):
        fonts[path.name] = ttf_coverage(path)
    return fonts


def dedupe() -> None:
    """One entry per character: two blocks naming the same code would inflate
    the counts and print it twice in the "already covered" line."""
    seen: set[str] = set()
    for block, characters in list(CANDIDATES.items()):
        unique = "".join(c for c in dict.fromkeys(characters) if c not in seen)
        seen.update(unique)
        CANDIDATES[block] = unique


def report(coverages: dict[str, set[int]], markdown: bool) -> None:
    def heading(level: int, text: str) -> None:
        print(f"{'#' * level} {text}\n" if markdown else f"\n=== {text} ===")

    def bullet(text: str) -> None:
        print(("- " if markdown else "  ") + text)

    heading(1 if markdown else 0, "Sovngarde font — character coverage")
    bullet(
        "Measured on the files under `upstream/` (the mod as shipped). To see what "
        "a build adds on top, run `tools/coverage.py` against a built tree - the "
        '"still missing" list below is therefore a pre-patch baseline.'
    )
    for name, covered in coverages.items():
        bullet(f"{name}: {len(covered)} codepoints")
    ui = coverages["fonts_sovngarde.swf"]
    books = coverages["fonts_drukaatieburti.swf"]
    desktops = sorted(name for name in coverages if name.endswith(".ttf"))
    heading(2 if markdown else 0, "Already covered by the UI font")
    for block, characters in CANDIDATES.items():
        present = [c for c in characters if ord(c) in ui]
        if present:
            bullet(f"{block}: " + " ".join(present))
    heading(2 if markdown else 0, "Still missing, by block")
    for block, characters in CANDIDATES.items():
        missing = [c for c in characters if ord(c) not in ui]
        if not missing:
            continue
        elsewhere = "".join(c for c in missing if ord(c) in books)
        line = f"{block}: " + " ".join(f"{c} U+{ord(c):04X}" for c in missing)
        if elsewhere:
            line += f"   [in the book font: {elsewhere}]"
        bullet(line)
    heading(2 if markdown else 0, "Summary")
    total = sum(len(characters) for characters in CANDIDATES.values())
    total_missing = sum(1 for chars in CANDIDATES.values() for c in chars if ord(c) not in ui)
    bullet(f"{total - total_missing}/{total} of the candidates are in the UI font")
    bullet(f"{len(desktops)} desktop faces checked: {', '.join(desktops)}")
    only_light = [
        hex(cp)
        for cp in sorted(coverages.get("Sovngarde Light.ttf", set()))
        if cp not in coverages.get("Sovngarde Bold.ttf", set())
    ]
    if only_light:
        bullet(
            "present in the Light face but not the Bold one (so the Bold is the "
            f"incomplete one): {' '.join(only_light)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    dedupe()
    report(collect(), args.markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
