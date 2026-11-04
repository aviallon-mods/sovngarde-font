# The Scaleform font format this mod's `.swf` files use

Findings needed to add a glyph to `Interface/fonts_sovngarde.swf`. The public
summary is in the README; this is the evidence, so the next person (or the next
version of the mod) does not have to rediscover it.

Everything below was measured on the three movies the mod ships
(`fonts_sovngarde.swf`, `fonts_sovngardeconsole.swf`, `fonts_drukaatieburti.swf`,
mod version 8.9), not read off a specification that does not describe them.

## Facts that differ from the `DefineFont2/3` documentation

**1. Offset table base.** `OffsetTable[i]` and `CodeTableOffset` are relative to
the **start of the OffsetTable field**, not to the start of the tag data:
`absolute(glyph i) == header_len + offsets[i]`, where `header_len` is the size of
the font header (FontID .. NumGlyphs). Checked on all three movies: with
`header_len` 16 (Sovngarde), 23 (SovngardeConsole) and 22 (Drukaatie Burti),
`offsets[0]` is 1276, 1276 and 2192 respectively — that is
`num_glyphs * 4 + 4` from the table's own start, and the first shape starts
exactly there. Ruffle's reader uses the same reference, so this is the
authoring tool's convention rather than a quirk of one file.

**2. `MoveTo` is absolute.** A contour's `StyleChange` move carries an absolute
position, not a delta from the pen's current position. The oracle is the file's
own `BoundsTable`: with a *delta* reading, every contour after the first lands
outside the rectangle the movie stores for that glyph. With the absolute
reading, **1171 of 1171 non-empty glyphs across the three movies fit their own
bounds rectangle within 1 twip** (the 1 twip is the rounding of the on-curve
bounding box).

**3. BoundsTable = on-curve bounding box.** The stored rectangle bounds the
on-curve points; a quadratic bulging past them legitimately sticks out of it
(measured maximum over the three movies: 188 twips, on the console movie). A
rewritten glyph must therefore compute its rectangle from its on-curve points,
not from its control points.

**4. The advance table is UI16 even with `WideOffsets`**, and the tag does not
end with the code table: `FontAscent/Descent/Leading` (UI16 ×3), the
`AdvanceTable` (UI16 per glyph), the `BoundsTable` (one RECT per glyph, byte
aligned) and a kerning table whose record count is a leading UI16 all follow.

**5. `FileLength` is the uncompressed size**, header included — it is not the
size of the file on disk. The three movies declare 102213 / 112920 / 250139
while their compressed sizes are 72697 / 83794 / 177476.

**6. Glyphs carry no style array.** All 865 glyphs of the two Sovngarde movies
(and all 547 of the Drukaatie Burti one) use exactly one convention: one
`StyleChange` per contour that moves to its start point and sets fill style 1
(`NumFillBits` 1, `NumLineBits` 0, no `StateNewStyles`, no `DefineFontInfo`):
Scaleform only uses the fill index as an on/off flag for font glyphs. None of
the three movies has a `DefineFontAlignZones` (tag 73) or `CSMTextSettings`
(tag 74) — which is why the codec refuses to append glyphs to a movie that has
one: those tables are indexed per glyph and would need extending.

**7. The code table is ascending.** All three movies store it in ascending
character-code order. Glyphs are therefore stored in that order too: the
encoder sorts, and the test suite asserts the result stays sorted.

## Verification

* **Byte-exact glyph round trip**: decode then re-encode every glyph of the
  three movies → 1183/1183 identical to the original bytes, and re-encoding a
  whole `DefineFont3` tag with no new glyph reproduces the tag byte for byte.
* **Geometric exactness**: SWF → canonical → SWF renders pixel-identically for
  all 1423 glyphs (own rasteriser).
* **Cross-convention**: the movies and the desktop face describe the same
  design (the SWF is the TTF at 20.4824 twips per unit for the UI movie and
  28.6589 for the console one — advance ratios uniform to 0.045 % and 0.34 %,
  measured with a guard that refuses a mismatched pair).
* **Mutation testing** of the build gate: ten deliberate mutations of the
  shipped behaviour, each asserted to apply and each run against the full
  suite. All ten are caught (mutation → the test that fails):

  | mutation | caught by |
  | --- | --- |
  | new movie glyphs scaled twice | `test_dashes_are_the_hyphen_bar_at_the_hyphen_height` |
  | new desktop glyphs scaled twice | `test_every_added_glyph_agrees_between_movie_and_desktop` |
  | new advances zeroed | `test_dashes_are_the_hyphen_bar_at_the_hyphen_height` |
  | em dash translated by 0.2 em | `test_dashes_are_the_hyphen_bar_at_the_hyphen_height` |
  | fill index 1 → 0 | `test_added_movie_glyphs_use_the_shipped_fill_convention` |
  | `hmtx` side bearing zeroed | `test_added_desktop_glyphs_have_a_consistent_side_bearing` |
  | code table left unsorted | `test_added_movie_glyphs_keep_the_code_table_sorted` |
  | `FileLength` written compressed | `test_saving_a_movie_keeps_the_header_consistent` |
  | ellipsis pitch doubled | `test_ellipsis_is_three_periods_at_the_period_pitch` |
  | superscripts not raised | `test_superscripts_reach_the_cap_height` |

  Before those tests existed, seven of these mutations passed the whole suite:
  it only asserted that a glyph was "present and non-empty".
