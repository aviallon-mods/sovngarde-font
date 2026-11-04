# Sovngarde font — character coverage

- Measured on the files under `upstream/` (the mod as shipped). To see what a build adds on top, run `tools/coverage.py` against a built tree - the "still missing" list below is therefore a pre-patch baseline.
- fonts_sovngarde.swf: 318 codepoints
- fonts_sovngardeconsole.swf: 318 codepoints
- fonts_drukaatieburti.swf: 547 codepoints
- Sovngarde Bold.ttf: 318 codepoints
- Sovngarde Light.ttf: 327 codepoints
- Sovngarde Bold Inverted Brackets.ttf: 318 codepoints
- Sovngarde Light Inverted Brackets.ttf: 327 codepoints
## Already covered by the UI font

- Latin-1 punctuation and signs:   ¡ ¢ £ ¤ ¥ ¦ ª « ­ ¯ ° ± ´ · º » ¿ ÷
- Latin Extended-A (Central-European): Œ œ Š š Ÿ Ź ź Ż ż Ž ž Ą ą Ć ć Ę ę Ł ł Ń ń Ś ś
- General punctuation: ‘ ’ ‚ ‛ “ ” „ ‟
## Still missing, by block

- Latin-1 punctuation and signs: § U+00A7 ¨ U+00A8 © U+00A9 ¬ U+00AC ® U+00AE ² U+00B2 ³ U+00B3 µ U+00B5 ¶ U+00B6 ¸ U+00B8 ¹ U+00B9 ¼ U+00BC ½ U+00BD ¾ U+00BE × U+00D7   [in the book font: §¨©¬®²³µ¶¸¹¼½¾×]
- Spacing modifiers and superscripts: ˆ U+02C6 ˇ U+02C7 ˘ U+02D8 ˙ U+02D9 ˚ U+02DA ˛ U+02DB ˜ U+02DC ˝ U+02DD ˉ U+02C9 ʺ U+02BA ʹ U+02B9 ′ U+2032 ″ U+2033 ⁰ U+2070 ⁴ U+2074 ⁵ U+2075 ⁶ U+2076 ⁷ U+2077 ⁸ U+2078 ⁹ U+2079   [in the book font: ˆˇ˘˙˚˛˜˝ˉ]
- General punctuation: ‐ U+2010 ‑ U+2011 ‒ U+2012 – U+2013 — U+2014 ― U+2015 † U+2020 ‡ U+2021 • U+2022 ‣ U+2023 ․ U+2024 ‥ U+2025 … U+2026 ‧ U+2027 ‰ U+2030 ‹ U+2039 › U+203A ‽ U+203D ⁄ U+2044   [in the book font: ‒–—•․‥…‧]
- Currency: ₣ U+20A3 ₤ U+20A4 ₦ U+20A6 ₧ U+20A7 ₩ U+20A9 ₪ U+20AA ₫ U+20AB ₱ U+20B1 ₴ U+20B4 ₽ U+20BD ₿ U+20BF
- Letterlike symbols: ℃ U+2103 ℉ U+2109 № U+2116 ℗ U+2117 ℞ U+211E ℠ U+2120 ™ U+2122 Ω U+2126 Å U+212B ℮ U+212E ℵ U+2135   [in the book font: ™]
- Arrows: ← U+2190 ↑ U+2191 → U+2192 ↓ U+2193 ↔ U+2194 ↕ U+2195 ↖ U+2196 ↗ U+2197 ↘ U+2198 ↙ U+2199 ↩ U+21A9 ↪ U+21AA ⇐ U+21D0 ⇒ U+21D2 ⇔ U+21D4
- Mathematical operators: ∀ U+2200 ∂ U+2202 ∃ U+2203 ∅ U+2205 ∇ U+2207 ∈ U+2208 ∉ U+2209 ∋ U+220B ∏ U+220F ∑ U+2211 − U+2212 ∓ U+2213 ∗ U+2217 √ U+221A ∝ U+221D ∞ U+221E ∠ U+2220 ∣ U+2223 ∥ U+2225 ∨ U+2228 ∩ U+2229 ∪ U+222A ∫ U+222B ∮ U+222E ∴ U+2234 ∵ U+2235 ∷ U+2237 ≈ U+2248 ≉ U+2249 ≠ U+2260 ≡ U+2261 ≢ U+2262 ≤ U+2264 ≥ U+2265 ≪ U+226A ≫ U+226B ≮ U+226E ≯ U+226F ⊂ U+2282 ⊃ U+2283 ⊕ U+2295 ⊗ U+2297 ⊢ U+22A2 ⊣ U+22A3 ⋅ U+22C5 ⋆ U+22C6 ⋮ U+22EE ⋯ U+22EF ⋱ U+22F1 ⌈ U+2308 ⌉ U+2309 ⌊ U+230A ⌋ U+230B ⌠ U+2320 ⌡ U+2321 ⎓ U+2393
- Miscellaneous technical / symbols: ␣ U+2423 ■ U+25A0 □ U+25A1 ▪ U+25AA ▫ U+25AB ▲ U+25B2 △ U+25B3 ▶ U+25B6 ▷ U+25B7 ▼ U+25BC ▽ U+25BD ◀ U+25C0 ◁ U+25C1 ◊ U+25CA ○ U+25CB ● U+25CF ◐ U+25D0 ◑ U+25D1 ★ U+2605 ☆ U+2606 ☎ U+260E ☐ U+2610 ☑ U+2611 ☒ U+2612 ☛ U+261B ☞ U+261E ☺ U+263A ☻ U+263B ☼ U+263C ♠ U+2660 ♣ U+2663 ♥ U+2665 ♦ U+2666 ♪ U+266A ♫ U+266B ⚑ U+2691 ⚙ U+2699 ⚠ U+26A0 ⚡ U+26A1
- Dingbats: ✓ U+2713 ✔ U+2714 ✗ U+2717 ✘ U+2718 ✦ U+2726 ✰ U+2730 ❖ U+2756 ❢ U+2762 ➔ U+2794 ➡ U+27A1 ➰ U+27B0 ⬅ U+2B05 ⬆ U+2B06 ⬇ U+2B07 ⬛ U+2B1B ⬜ U+2B1C ⭐ U+2B50 ⭕ U+2B55
- Greek and Cyrillic extras: ΄ U+0384 ΅ U+0385 Ά U+0386 Έ U+0388 Ή U+0389 Ί U+038A Ό U+038C Ύ U+038E Ώ U+038F ΐ U+0390 Ϊ U+03AA Ϋ U+03AB ΰ U+03B0 ά U+03AC έ U+03AD ή U+03AE ί U+03AF α U+03B1 β U+03B2 γ U+03B3 δ U+03B4 π U+03C0 σ U+03C3 τ U+03C4 φ U+03C6 ω U+03C9 Ѐ U+0400 Ѓ U+0403 Љ U+0409 Њ U+040A Ќ U+040C Џ U+040F ђ U+0452 ѕ U+0455 љ U+0459 њ U+045A ћ U+045B џ U+045F Ґ U+0490 ґ U+0491   [in the book font: ЃЉЊЌЏђѕџ]
## Summary

- 50/294 of the candidates are in the UI font
- 4 desktop faces checked: Sovngarde Bold Inverted Brackets.ttf, Sovngarde Bold.ttf, Sovngarde Light Inverted Brackets.ttf, Sovngarde Light.ttf
- present in the Light face but not the Bold one (so the Bold is the incomplete one): 0x2dd 0x403 0x40a 0x40c 0x453 0x455 0x2032 0x2033 0x2212
