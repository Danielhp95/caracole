"""The sheet viewer: ``sheet.html`` beside ``sheet.pdf``, a phone-friendly page for each sheet.

- page.py builds the page (``build_viewer``) from the song's own ChordPro file;
- sheet.py reads that file back; theory.py names chords and keys, changes modes
  and finds alternatives; harmony.py, on top of it, tells what each chord does in its key
  (numerals, relations, progressions, scales); voicings.py holds the fingerings (chords-db, MIT);
  instruments.py, the instruments the viewer draws chords for (guitar, ukuleles, piano) and their shapes;
- version.py applies a version of the page (its key, capo, mode, shapes and swaps) to the
  sheet in Python, for a PDF of what the page shows;
- pinyin.py reads each Chinese character's pinyin in context, for the page's Pinyin; hanzi.py writes the sheet's
  Chinese in Simplified and in Traditional characters, word by word (OpenCC), for its Chinese characters;
- harp.py and winds.py hold the harmonica and the flute and recorder: harp layouts, positions, the chords a
  harp plays and the harps for a song; fingerings and the notes a wind player reads off a sheet;
- viewer.js and viewer.css are the page's script and stylesheet, inlined; strum.js, inlined before
  viewer.js, strums the shape a chord's card shows in Web Audio (``window.caracoleSound``: a chord,
  or a progression at a tempo, on the instrument chosen), only on a tap; instruments.js, inlined after
  it, draws a chord's box on any fretted instrument and a piano's keyboard, and is where another
  instrument's script registers its drawing (``window.caracoleInstruments``); winds.js, inlined after it,
  registers the harmonica, the flute and the recorder, drawn from harp.py's and winds.py's tables;
- book.py builds ``songbook.html``, a songbook's songs in one page, from page.py's pieces, with
  book.js and book.css beside the viewer's own;
- harptab_page.py builds ``harmonica-N.html``, a harmonica tab kept from harptabs.com as a page in the
  viewer's look (``build_harmonica_viewer``), from page.py's pieces, with harptab.js and harptab.css
  beside the viewer's stylesheet and strum.js: harptab.py reads the tab (holes over syllables),
  harpfit.py chooses the harp it plays on (with the record, from the song's chord sheet).

What a page is made from is ``page.BUILD_FILES`` (and ``book.BOOK_FILES``), whose hash
(``page.build_version``) tells a page made by another caracole: a module the viewer comes to
import goes there.
"""

from caracole.viewer.page import build_viewer, viewer_csp

__all__ = ["build_viewer", "viewer_csp"]
