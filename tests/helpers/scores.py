"""Synthetic MusicXML files, in the shape MuseScore 4 exports them: a header, then the parts.

No file here is anyone's score: each has a title, a creator and one empty measure.
"""

from __future__ import annotations

import io
import zipfile

DOCTYPE = ('<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
           '"http://www.musicxml.org/dtds/partwise.dtd">\n')
PARTS = ('<part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>'
         '<part id="P1"><measure number="1"/></part>')


def musicxml(title: str | None = "Wonderwall", creator: str | None = "Oasis", *, movement: str | None = None,
             parts: str = PARTS, doctype: str = DOCTYPE) -> bytes:
    """An uncompressed MusicXML file (.musicxml) with this work title, movement title and composer."""
    work = f"<work><work-title>{title}</work-title></work>" if title is not None else ""
    mov = f"<movement-title>{movement}</movement-title>" if movement is not None else ""
    ident = ""
    if creator is not None:
        ident = (f'<identification><creator type="composer">{creator}</creator>'
                 "<encoding><software>MuseScore 4.4.2</software></encoding></identification>")
    head = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n' + doctype
    return (head + f'<score-partwise version="4.0">{work}{mov}{ident}{parts}</score-partwise>\n').encode("utf-8")


def mxl(xml: bytes, *, container: bool = True, name: str = "score.musicxml") -> bytes:
    """A compressed MusicXML file (.mxl): a zip with META-INF/container.xml naming its root file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if container:
            z.writestr("META-INF/container.xml", (
                '<?xml version="1.0" encoding="UTF-8"?><container><rootfiles>'
                f'<rootfile full-path="{name}" media-type="application/vnd.recordare.musicxml+xml"/>'
                "</rootfiles></container>"))
        z.writestr(name, xml)
    return buf.getvalue()
