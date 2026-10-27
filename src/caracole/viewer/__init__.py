"""The sheet viewer: ``sheet.html`` beside ``sheet.pdf``, a phone-friendly page for each sheet.

- page.py builds the page (``build_viewer``) from the song's own ChordPro file;
- sheet.py reads that file back; theory.py names chords and keys, changes modes
  and finds alternatives; harmony.py, on top of it, tells what each chord does in its key
  (numerals, relations, progressions, scales); voicings.py holds the fingerings (chords-db, MIT);
- version.py applies a version of the page (its key, capo, mode, shapes and swaps) to the
  sheet in Python, for a PDF of what the page shows;
- pinyin.py reads each Chinese character's pinyin in context, for the page's Pinyin;
- harp.py and winds.py hold the harmonica and the flute and recorder: harp layouts, positions, the chords a
  harp plays and the harps for a song; fingerings and the notes a wind player reads off a sheet;
- viewer.js and viewer.css are the page's script and stylesheet, inlined; strum.js, inlined before
  viewer.js, strums the shape a chord's card shows in Web Audio (``window.caracoleSound``: a chord,
  or a progression at a tempo), only on a tap;
- book.py builds ``songbook.html``, a songbook's songs in one page, from page.py's pieces, with
  book.js and book.css beside the viewer's own.

What a page is made from is ``page.BUILD_FILES`` (and ``book.BOOK_FILES``), whose hash
(``page.build_version``) tells a page made by another caracole: a module the viewer comes to
import goes there.
"""

from caracole.viewer.page import build_viewer, viewer_csp

__all__ = ["build_viewer", "viewer_csp"]
