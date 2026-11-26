"""Expected names of uploads' titles, for tests/test_song_names.py, kept here so that they cost the keys corpus nothing.

The keys corpus (tests/test_conformance_keys.py) takes every string literal written in test_song_names.py, about
1.2 KB each; it never reads this module. The names corpus (tests/test_conformance_search.py ``names_records``) reads
the tests these tables parametrize, so each case is a record of search/names.jsonl, which the phone's SongNamesTest
replays.

- ``READ``: (title, channel or None, the artist and title ``read_names`` gives, or None), with no library.
- ``KNOWN``: (title, an artist your library has two songs of, what ``read_names`` gives), no channel. The corpus has no
  fixture that knows these artists: the phone's SongNamesTest pins them by hand.
- ``CLEAN``: (text, what ``clean`` gives).
"""

from __future__ import annotations

READ: list[tuple[str, str | None, tuple[str, str] | None]] = [
    # A 「」 or 『』 quote of Latin words longer than LYRIC_CHARS is a lyric, but where the words before it are, whole,
    # the channel's name or a known artist: then it is the title.
    ("Live「Lightning Crashes」", "Live", ("Live", "Lightning Crashes")),
    ("LiSA「Rising Hope and Glory」", "LiSA", ("LiSA", "Rising Hope and Glory")),
    ("LiSA「Rising Hope and Glory」", None, None),
    ("Lemon「I still love you even now」", "米津玄師", ("米津玄師", "Lemon")),
    ("米津玄師 Lemon「I still love you even now」", "米津玄師", ("米津玄師", "Lemon")),
    ("米津玄師 Lemon「I still love you even now」", None, None),
    ("Lemon 『English Lyrics Romaji Translation』", "米津玄師", ("米津玄師", "Lemon")),
    ("Artist Song 『Official Lyric Video Full Version』", "Artist", ("Artist", "Artist Song")),
    ("Artist Song 『Official Lyric Video Full Version』", None, None),
    # With a mark, the quote goes, or follows the title, as before.
    ("米津玄師 - Lemon「I still love you even now」", None, ("米津玄師", "Lemon")),
    ("LiSA - 紅蓮華「Gurenge English Cover Version」", None, ("LiSA", "紅蓮華")),
    ("Aimer「残響散歌」『I will never forget this night』", None, ("Aimer", "残響散歌")),
    ("YOASOBI「夜に駆ける」Racing into the night", None, ("YOASOBI", "夜に駆ける")),
    # "by": stripped from an artist after the title bracket alone; a lone "by" is no words of a part's own.
    ("By Divine Right「Song」", None, ("By Divine Right", "Song")),
    ("By the Tree《Song》", None, ("By the Tree", "Song")),
    ("《孤勇者》 By 陈奕迅", None, ("陈奕迅", "孤勇者")),
    ("《Stand by Me》 by", "Ben E King", ("Ben E King", "Stand by Me")),
    ("Stand by Me《Ben E King》", None, ("Stand by Me", "Ben E King")),  # a "by" inside a title is a word
]

KNOWN: list[tuple[str, str, tuple[str, str] | None]] = [
    ("LiSA「Rising Hope and Glory」", "LiSA", ("LiSA", "Rising Hope and Glory")),
]

CLEAN: list[tuple[str, str]] = [
    # A lyric channel's group goes (two thirds of its letters its words).
    ("【抖音】别知己", "别知己"),
    ("【純音樂】Summer", "Summer"),
]
