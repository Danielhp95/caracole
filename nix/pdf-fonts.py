"""Static instances of Adwaita Sans for caracole's PDFs (./pdf-fonts.nix): its Regular, Bold and Italic, made
from the variable fonts nixpkgs' adwaita-fonts installs, as ChordPro 6.050.7 draws them right.

ChordPro's PDF library (PDF::API2 2.045) draws a variable font as its default instance alone, so the Bold is
an instance of its own; and it corrupts the subsets it embeds of a TrueType font whose glyph records have odd
lengths, as Adwaita Sans's have, so each record is padded to an even length (src/caracole/render.py
``_font_problem`` refuses any other). The optical size stays at its default, 14, the text's. Each is named as
the static font it is ("Adwaita Sans Bold", PostScript "AdwaitaSans-Bold"), so a PDF names its fonts apart.

    python3 pdf-fonts.py SOURCE_FOLDER OUT_FOLDER   # writes regular.ttf, bold.ttf and italic.ttf
"""

import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

INSTANCES = (
    ("regular", "AdwaitaSans-Regular.ttf", 400, "Regular"),
    ("bold", "AdwaitaSans-Regular.ttf", 700, "Bold"),
    ("italic", "AdwaitaSans-Italic.ttf", 400, "Italic"),
)
# The name records of a variable font's typographic family and its instances, which a static font has none of.
_VARIABLE_NAMES = (16, 17, 21, 22, 25)


def main(source: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for role, variable, weight, style in INSTANCES:
        font = instantiateVariableFont(TTFont(source / variable, recalcTimestamp=False),
                                       {"wght": weight, "opsz": 14}, static=True)
        _name(font, style)
        font["glyf"].padding = 2
        font.recalcTimestamp = False
        font.save(out / f"{role}.ttf")


def _name(font: TTFont, style: str) -> None:
    names = font["name"]
    postscript = f"AdwaitaSans-{style}"
    values = {1: "Adwaita Sans", 2: style, 3: postscript, 4: "Adwaita Sans" if style == "Regular" else
              f"Adwaita Sans {style}", 6: postscript}
    names.names = [record for record in names.names if record.nameID not in _VARIABLE_NAMES]
    for record in names.names:
        if record.nameID in values:
            record.string = values[record.nameID]


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
