"""Tools to extend the Sovngarde font with the usual missing UTF-8 symbols.

The package reads the fonts as shipped by the mod (Skyrim Scaleform movies and
the desktop TrueType faces), adds a curated set of glyphs (see
:mod:`sovngarde.glyphs`) and writes installable artifacts, verifying every one
of them afterwards.
"""

__all__ = ["build", "geometry", "glyphs", "swf", "targets"]
