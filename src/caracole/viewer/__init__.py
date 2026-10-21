"""The sheet viewer: ``sheet.html`` beside ``sheet.pdf``, a phone-friendly page for each sheet.

- page.py builds the page (``build_viewer``) from the song's own ChordPro file;
- sheet.py reads that file back; theory.py names chords and keys, changes modes
  and finds alternatives; voicings.py holds the fingerings (chords-db, MIT);
- viewer.js and viewer.css are the page's script and stylesheet, inlined;
- book.py builds ``songbook.html``, a songbook's songs in one page, from page.py's pieces, with
  book.js and book.css beside the viewer's own.

What a page is made from is ``page.BUILD_FILES`` (and ``book.BOOK_FILES``), whose hash
(``page.build_version``) tells a page made by another caracole: a module the viewer comes to
import goes there.
"""

from caracole.viewer.page import build_viewer, viewer_csp

__all__ = ["build_viewer", "viewer_csp"]
