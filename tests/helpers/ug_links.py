"""Ultimate Guitar links as a search box may be given them, and what each is: one list of shapes.

``SHAPES`` pairs a text with what ``caracole.ug_urls.read_link`` reads of it: ``(kind, url, tab_id, type)``, or None for
a text that is no UG link (words to search). tests/test_ug_urls.py holds Python to it, test_web_page_ug_link.py the
library page's ``ugLink`` (library.js), and test_conformance_ug_link.py writes it for the phone::

    from helpers.ug_links import SHAPES
"""

from __future__ import annotations

TAB = "https://tabs.ultimate-guitar.com/tab/"
WWW = "https://www.ultimate-guitar.com"
BANMA = f"{TAB}4180894"  # the page the owner found on UG: 宋冬野's 斑马斑马
SONG_DONGYE = f"{WWW}/artist/634073"
SODA = f"{TAB}soda-stereo/de-musica-ligera-chords-85053"

SHAPES: list[tuple[str, tuple[str, str, int | None, str | None] | None]] = [
    # a bare tab page, as an address bar shows it
    (BANMA, ("tab", BANMA, 4180894, None)),
    ("tabs.ultimate-guitar.com/tab/4180894", ("tab", BANMA, 4180894, None)),
    ("http://tabs.ultimate-guitar.com/tab/4180894", ("tab", BANMA, 4180894, None)),
    ("HTTPS://TABS.ULTIMATE-GUITAR.COM/tab/4180894", ("tab", BANMA, 4180894, None)),
    (f"{BANMA}?ref=share&utm_source=app#comments", ("tab", BANMA, 4180894, None)),
    (f"{BANMA}/", ("tab", BANMA, 4180894, None)),
    (f"  {BANMA}　", ("tab", BANMA, 4180894, None)),
    (f"\t{BANMA}\n", ("tab", BANMA, 4180894, None)),
    ("https://ultimate-guitar.com/tab/4180894", ("tab", BANMA, 4180894, None)),
    ("https://www.ultimate-guitar.com/tab/4180894", ("tab", BANMA, 4180894, None)),
    ("https://es.ultimate-guitar.com/tab/4180894", ("tab", BANMA, 4180894, None)),
    # a slugged tab page, its type named
    (SODA, ("tab", SODA, 85053, "chords")),
    ("ultimate-guitar.com/tab/soda-stereo/de-musica-ligera-chords-85053?app=1",
     ("tab", SODA, 85053, "chords")),
    (f"{TAB}radiohead/creep-tabs-4169", ("tab", f"{TAB}radiohead/creep-tabs-4169", 4169, "tabs")),
    (f"{TAB}vance-joy/riptide-ukulele-1237247",
     ("tab", f"{TAB}vance-joy/riptide-ukulele-1237247", 1237247, "ukulele")),
    (f"{TAB}metallica/one-guitar-pro-225441", ("tab", f"{TAB}metallica/one-guitar-pro-225441", 225441, "guitar-pro")),
    (f"{TAB}metallica/one-power-71542", ("tab", f"{TAB}metallica/one-power-71542", 71542, "power")),
    (f"{TAB}oasis/wonderwall-official-1956589",
     ("tab", f"{TAB}oasis/wonderwall-official-1956589", 1956589, "official")),
    (f"{TAB}muse/hysteria-bass-91003", ("tab", f"{TAB}muse/hysteria-bass-91003", 91003, "bass")),
    (f"{TAB}toto/rosanna-drums-850391", ("tab", f"{TAB}toto/rosanna-drums-850391", 850391, "drums")),
    (f"{TAB}a/song-2-tabs-chords-77", ("tab", f"{TAB}a/song-2-tabs-chords-77", 77, "chords")),
    (f"{TAB}a/b-77", ("tab", f"{TAB}a/b-77", 77, None)),
    (f"{TAB}a/77", ("tab", f"{TAB}a/77", 77, None)),
    (f"{TAB}b-chords-77", ("tab", f"{TAB}b-chords-77", 77, None)),
    (f"{TAB}%E5%AE%8B/%E6%96%91-chords-77", ("tab", f"{TAB}%E5%AE%8B/%E6%96%91-chords-77", 77, "chords")),
    (f"{TAB}宋冬野/斑马-chords-77", ("tab", f"{TAB}宋冬野/斑马-chords-77", 77, "chords")),
    (f"{TAB}٣٤", ("tab", f"{TAB}٣٤", 34, None)),  # Unicode's digits, as overrides.toml reads them
    # an artist page
    (SONG_DONGYE, ("artist", SONG_DONGYE, None, None)),
    (f"{SONG_DONGYE}?filter=chords&page=2", ("artist", SONG_DONGYE, None, None)),
    ("ultimate-guitar.com/artist/soda_stereo_2946", ("artist", f"{WWW}/artist/soda_stereo_2946", None, None)),
    ("https://tabs.ultimate-guitar.com/artist/soda_stereo_2946/",
     ("artist", f"{WWW}/artist/soda_stereo_2946", None, None)),
    (f"{WWW}/artist/٣", ("artist", f"{WWW}/artist/٣", None, None)),
    # no UG link: words to search
    (f"{WWW}/artist/soda_stereo", None),
    (WWW, None),
    (f"{WWW}/", None),
    (f"{WWW}/explore?type[]=Chords", None),
    (f"{WWW}/search.php?search_type=title&value=banma", None),
    (f"{WWW}/forum/showthread.php?t=1", None),
    (f"{TAB}download?id=4180894", None),
    (f"{TAB}print?id=4180894", None),
    (f"{TAB}", None),
    (f"{TAB}4180894x", None),
    (f"{TAB}4180894;x", None),
    (f"宋冬野 {BANMA}", None),
    (f"{BANMA} chords", None),
    (f"{BANMA} x", None),
    (f"{BANMA}\x1cx", None),
    ("4180894", None),
    ("ultimate guitar banma", None),
    ("song dongye 斑马斑马", None),
    ("https://ultimate-guitar.com.evil.example/tab/4180894", None),
    ("https://evil.example/tabs.ultimate-guitar.com/tab/4180894", None),
    ("https://m.ultimate-guitar.com/tab/4180894", None),
    ("ftp://tabs.ultimate-guitar.com/tab/4180894", None),
    ("https:/tabs.ultimate-guitar.com/tab/4180894", None),
    ("https:///tabs.ultimate-guitar.com/tab/4180894", None),
    ("//tabs.ultimate-guitar.com/tab/4180894", None),
    ("https://tabs.ultimate-guitar.com:443/tab/4180894", None),
    ("tabs.ultimate-guitar.com:443/tab/4180894", None),
    ("https://user@tabs.ultimate-guitar.com/tab/4180894", None),
    ("https://[tabs.ultimate-guitar.com/tab/4180894", None),
    ("mailto:tabs.ultimate-guitar.com/tab/4180894", None),
    ("httpſ://tabs.ultimate-guitar.com/tab/4180894", None),
    ("https://tabs.ultimate-guitar.com?x=/tab/4180894", None),
    ("https://tabs.ultimate-guitar.com#/tab/4180894", None),
    ("https://www.youtube.com/watch?v=lzN7Thn3FV4", None),
    ("", None),
    ("   ", None),
]
