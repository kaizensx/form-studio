"""Rebuild form/fonts/FormMark-Bold.ttf: Instrument Sans at weight 700 as a static font with overlaps removed.

The kernel turns glyph outlines into faces, so overlapping contours (normal in a variable font) would give
invalid solids. Needs fontTools and skia-pathops (development only; the built font is committed).
    python scripts/make_mark_font.py
"""
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

f = TTFont("form/app/assets/fonts/InstrumentSans.ttf")
f = instancer.instantiateVariableFont(f, {"wght": 700}, overlap=instancer.OverlapMode.REMOVE)
for rec in f["name"].names:
    if rec.nameID in (1, 16):
        rec.string = "FORM Mark"
    elif rec.nameID in (2, 17):
        rec.string = "Bold"
    elif rec.nameID == 4:
        rec.string = "FORM Mark Bold"
    elif rec.nameID == 6:
        rec.string = "FORMMark-Bold"
    elif rec.nameID == 3:
        rec.string = "FORMMark-Bold;derived from Instrument Sans wght=700"
f.save("form/fonts/FormMark-Bold.ttf")
