"""The sheet viewer: ``sheet.html`` beside ``sheet.pdf``, a phone-friendly page for each sheet.

- page.py builds the page (``build_viewer``) from the song's own ChordPro file;
- sheet.py reads that file back; theory.py names chords and keys, changes modes
  and finds alternatives; voicings.py holds the fingerings (chords-db, MIT);
- version.py applies a version of the page (its key, capo, mode, shapes and swaps) to the
  sheet in Python, for a PDF of what the page shows;
- viewer.js and viewer.css are the page's script and stylesheet, inlined.
"""

from caracole.viewer.page import build_viewer, viewer_csp

__all__ = ["build_viewer", "viewer_csp"]
