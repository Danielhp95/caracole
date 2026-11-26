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
    # After the title bracket, a tag's or a video's words alone name no artist: the channel does, or no one.
    ("《孤勇者》 Cover", "某up主", ("某up主", "孤勇者")),
    ("《孤勇者》 Cover", None, None),
    ("《孤勇者》 Lyrics", "陈奕迅", ("陈奕迅", "孤勇者")),
    ("《孤勇者》 Lyrics", None, None),
    ("《孤勇者》 動態歌詞", "陈奕迅", ("陈奕迅", "孤勇者")),
    ("《孤勇者》 動態歌詞", None, None),
    ("《大鱼》 现场版", "周深", ("周深", "大鱼")),
    ("《大鱼》 现场版", None, None),
    ("「Lemon」 Remix", "米津玄師", ("米津玄師", "Lemon")),
    ("「Lemon」 Remix", None, None),
    ("「Lemon」 Piano ver.", "米津玄師", ("米津玄師", "Lemon")),
    ("「Lemon」 Piano ver.", None, None),
    ("「Lemon」 Acoustic Version", "米津玄師", ("米津玄師", "Lemon")),
    ("「Lemon」 Acoustic Version", None, None),
    ("「Lemon」 Instrumental", "米津玄師", ("米津玄師", "Lemon")),
    ("「Lemon」 Instrumental", None, None),
    ("「夜に駆ける」 Live", "YOASOBI", ("YOASOBI", "夜に駆ける")),
    ("「夜に駆ける」 Live", None, None),
    ("《孤勇者》 by 陈奕迅", None, ("陈奕迅", "孤勇者")),
    # A quote that ends as a sentence is a lyric, but a title after an artist known whole, or alone once the noise
    # groups go.
    ("KOKIA「ありがとう…」", "KOKIA", ("KOKIA", "ありがとう…")),
    ("KOKIA「ありがとう…」", None, None),
    ("Aimer「どうして？」", "Aimer", ("Aimer", "どうして？")),
    ("ヨルシカ「言って。」", "ヨルシカ", ("ヨルシカ", "言って。")),
    ("五月天「倔強！」", "五月天", ("五月天", "倔強！")),
    ("宋冬野「斑马，斑马。」", "宋冬野", ("宋冬野", "斑马，斑马。")),
    ("KOKIA「さよなら、また明日。」", "KOKIA", ("KOKIA", "さよなら、また明日。")),  # "Artist" is a placeholder: no one
    ("「夜に駆ける。」(Official Video)", "YOASOBI", ("YOASOBI", "夜に駆ける。")),
    ("晴天「为什么？」", "周杰倫", ("周杰倫", "晴天")),
    ("晴天「为什么？」", None, None),
    ("晴天「为什么？」", "周杰倫 Jay Chou", ("周杰倫 Jay Chou", "晴天")),
    ("晴天「为什么？」 周杰倫", None, None),
    ("晴天「我想你…」", "周杰倫", ("周杰倫", "晴天")),
    ("晴天「我想你…」", None, None),
    ("海阔天空「原谅我这一生不羁放纵爱自由！」", "Beyond", ("Beyond", "海阔天空")),
    ("海阔天空「原谅我这一生不羁放纵爱自由！」", None, None),
    ("七里香「雨下整夜…」", "周杰倫", ("周杰倫", "七里香")),
    ("七里香「雨下整夜…」", None, None),
    ("孤勇者「爱你孤身走暗巷！」", "陈奕迅", ("陈奕迅", "孤勇者")),
    ("孤勇者「爱你孤身走暗巷！」", None, None),
    ("小幸运「原来你是我最想留住的幸运…」", "田馥甄", ("田馥甄", "小幸运")),
    ("小幸运「原来你是我最想留住的幸运…」", None, None),
    ("Lemon「夢ならばどれほど…」", "米津玄師", ("米津玄師", "Lemon")),
    ("Lemon「夢ならばどれほど…」", None, None),
    # After the title bracket, a tag's words then "by" and a name: the name.
    ("《孤勇者》 Cover by 某某", None, ("某某", "孤勇者")),
    ("《孤勇者》 Piano Cover by Jane", None, ("Jane", "孤勇者")),
    ("「Title」 Cover Me Band", None, ("Cover Me Band", "Title")),
]

KNOWN: list[tuple[str, str, tuple[str, str] | None]] = [
    ("LiSA「Rising Hope and Glory」", "LiSA", ("LiSA", "Rising Hope and Glory")),
]

CLEAN: list[tuple[str, str]] = [
    # A lyric channel's group goes (two thirds of its letters its words).
    ("【抖音】别知己", "别知己"),
    ("【純音樂】Summer", "Summer"),
    # A quote that ends as a sentence is a lyric, a pause in it (，、；) or not.
    ("晴天「故事的小黄花，从出生那年就飘着。」", "晴天"),
    ("晴天「为什么、为什么？」", "晴天"),
    ("晴天「为什么；为什么？」", "晴天"),
    # A Latin group inside the other Latin bracket kind goes, the outer one staying.
    ("Artist - Song (Official Video [4K])", "Artist - Song (Official Video)"),
    ("Artist - Song (Live [HD])", "Artist - Song (Live)"),
    ("Artist - Song [Lyrics (HD)]", "Artist - Song [Lyrics]"),
    ("Song [Official Video (HD)]", "Song [Official Video]"),
]
