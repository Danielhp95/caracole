"""song_names.py: the artist and the title a text names, the one parser every path that turns free text into a song's
name uses (the request forms' prefill, Make the sheet, a pasted link's guess, /request and /lookup given one text,
``caracole add`` and ``get`` given one text).

A rule a test, and the cases collected on 2026-10-29, the day "silvana estrada que problema" came out as a song
"Estrada" by "Silvana" and that one-word artist then cut later queries at their first space. The video titles are
real-world shapes: an artist's own upload, a VEVO or "- Topic" channel, Spanish words of the same noise, a fan's
upload whose title names the song first.
"""

import pytest

from caracole.song_names import clean, clean_channel, read_names
from caracole.songs import list_songs

from conftest import add_song
from test_search import gtptabs_pages, harptabs_index, index, keep_sheet, lacuerda, songs_of

SILVANA = [*songs_of("silvana-estrada", 6, 65000), *songs_of("silvanas", 6, 65100),
           (65200, "que", "algo", "chords"), (65201, "estrada", "otra", "chords")]
SILVANA_VIDEO = ("Silvana Estrada — Qué Problema (Visualizer)", "Silvana Estrada")  # her own upload
VIKINGOS_VIDEO = ("Somos vikingos veganos - Hyperfanes", "kintanedu")  # a fan's: the song first, the band after


# --- the text, cleaned first ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,cleaned", [
    ("Estopa - Como Camarón [Videoclip Oficial] HD", "Estopa - Como Camarón"),
    ("Oasis - Wonderwall (Official Video)", "Oasis - Wonderwall"),
    ("Queen – Bohemian Rhapsody (Official Video Remastered)", "Queen – Bohemian Rhapsody"),
    ("Manu Chao | Clandestino (Letra)", "Manu Chao | Clandestino"),
    ("Manu Chao | Clandestino | Official Video", "Manu Chao | Clandestino"),
    ("Me Gustas Tú Con Letra", "Me Gustas Tú"),
    ("“Bohemian Rhapsody” (Official Lyric Video)", "Bohemian Rhapsody"),
    ("Silvana Estrada — Qué Problema (Visualizer)", "Silvana Estrada — Qué Problema"),
    # The song's own words stay: a version, a guest, a title that ends with such a word alone.
    ("Los Prisioneros - El Baile de los que Sobran (En Vivo)",
     "Los Prisioneros - El Baile de los que Sobran (En Vivo)"),
    ("Daft Punk - Get Lucky (feat. Pharrell Williams) [Official Audio]",
     "Daft Punk - Get Lucky (feat. Pharrell Williams)"),
    ("System of a Down Radio Video", "System of a Down Radio Video"),
    ("Radiohead - Creep | Pablo Honey", "Radiohead - Creep | Pablo Honey"),  # the marks as written
    ("  silvana  estrada   qué problema ", "silvana estrada qué problema"),  # spaces folded
    ("(Official Video)", ""),
    ("Song (Official Video (HD))", "Song (Official Video)"),  # the inner group goes with the spaces before it
])
def test_a_text_loses_what_a_videos_title_adds_to_a_songs_name(text, cleaned):
    assert clean(text) == cleaned


# The owner's 野人 of 2026-11-25 and its kin: titles of Chinese, Japanese and Korean lyric channels, which put their
# own words and a line of the song's lyrics in brackets around its name.
@pytest.mark.parametrize("text,cleaned", [
    ("孟维来 - 野人『不再借世人的手 替我开脱，遍野的花骨朵 也能够耐住寂寞。』『动态歌词MV』", "孟维来 - 野人"),
    ("毛不易 - 消愁「当你走进这欢乐场 背上所有的梦与想」【動態歌詞Lyrics】", "毛不易 - 消愁"),
    ("【抖音】海来阿木 - 别知己【动态歌词】", "海来阿木 - 别知己"),
    ("【純音樂】久石讓 - Summer", "久石讓 - Summer"),
    ("林俊傑 JJ Lin - 修煉愛情 Practice Love (華納 official 高畫質 HD 官方完整版MV)", "林俊傑 JJ Lin - 修煉愛情 Practice Love"),
    ("周杰倫 Jay Chou【告白氣球 Love Confession】Official MV", "周杰倫 Jay Chou【告白氣球 Love Confession】"),
    ("告五人 Accusefive【愛人錯過 Somewhere in Time】Official Music Video", "告五人 Accusefive【愛人錯過 Somewhere in Time】"),
    ("薛之谦 Joker Xue【演员】官方完整版 MV", "薛之谦 Joker Xue【演员】"),
    ("《起风了》买辣椒也用券【动态歌词/Pinyin Lyrics】", "《起风了》买辣椒也用券"),
    ("《孤勇者》陈奕迅 (动态歌词版)", "《孤勇者》陈奕迅"),
    ("周深 Zhou Shen《大鱼》Big Fish「动态歌词Lyrics」", "周深 Zhou Shen《大鱼》Big Fish"),
    ("G.E.M.【光年之外 LIGHT YEARS AWAY】MV (電影《太空潛航者 Passengers》中文主題曲)[HD] 鄧紫棋",
     "G.E.M.【光年之外 LIGHT YEARS AWAY】MV (電影《太空潛航者 Passengers》中文主題曲) 鄧紫棋"),
    ("YOASOBI「夜に駆ける」Official Music Video", "YOASOBI「夜に駆ける」"),
    ("米津玄師 MV「Lemon」", "米津玄師 MV「Lemon」"),
    ("宋冬野「斑马，斑马」", "宋冬野「斑马，斑马」"),
    ("野人『不再借世人的手 替我开脱，遍野的花骨朵 也能够耐住寂寞。』", "野人"),
    ("[MV] IU(아이유) _ Blueming(블루밍)", "IU(아이유) _ Blueming(블루밍)"),
    ("[MV] BTS(방탄소년단) _ Dynamite", "BTS(방탄소년단) _ Dynamite"),
])
def test_a_cjk_lyric_videos_title_loses_its_channels_words_and_its_quoted_lyrics(text, cleaned):
    assert clean(text) == cleaned


@pytest.mark.parametrize("text,cleaned", [
    # A sentence: it ends as one (。！？…), a space parts two CJK characters in it, or it is longer than LYRIC_CHARS.
    ("野人『不再借世人的手 替我开脱，遍野的花骨朵 也能够耐住寂寞。』", "野人"),
    ("消愁「当你走进这欢乐场 背上所有的梦与想」", "消愁"),
    ("海阔天空「原谅我这一生不羁放纵爱自由！」", "海阔天空"),
    ("晴天「为什么？」", "晴天"),
    ("晴天「我想你…」", "晴天"),
    ("消愁「当你走进这欢乐场背上所有的梦与想啊」", "消愁"),  # 17 characters
    ("消愁「当你走进这欢乐场背上所有的梦与想」", "消愁「当你走进这欢乐场背上所有的梦与想」"),  # 16: a title's length
    # Wherever it is: before the song's name, between it and a word of the song's own.
    ("『不再借世人的手 替我开脱。』孟维来 - 野人", "孟维来 - 野人"),
    ("孟维来 - 野人『不再借世人的手 替我开脱。』 Live", "孟维来 - 野人 Live"),
    # A short quote is a title; so is a quote of the whole text; a space beside a Latin word parts no sentence.
    ("宋冬野「斑马，斑马」", "宋冬野「斑马，斑马」"),
    ("YOASOBI「夜に駆ける」", "YOASOBI「夜に駆ける」"),
    ("周杰倫「告白 Love」", "周杰倫「告白 Love」"),
    ("『不再借世人的手 替我开脱，遍野的花骨朵 也能够耐住寂寞。』", "不再借世人的手 替我开脱，遍野的花骨朵 也能够耐住寂寞。"),
    # Only 「」 and 『』 quote a lyric.
    ("消愁《当你走进这欢乐场 背上所有的梦与想》", "消愁《当你走进这欢乐场 背上所有的梦与想》"),
    ("消愁 (当你走进这欢乐场 背上所有的梦与想)", "消愁 (当你走进这欢乐场 背上所有的梦与想)"),
])
def test_a_quoted_lyric_goes_wherever_it_is_but_a_short_quote_is_a_title(text, cleaned):
    assert clean(text) == cleaned


@pytest.mark.parametrize("text,cleaned", [
    # A group holding CJK goes once noise covers two thirds of its letters (CJK characters and Latin letters).
    ("林俊傑 JJ Lin - 修煉愛情 Practice Love (華納 official 高畫質 HD 官方完整版MV)",
     "林俊傑 JJ Lin - 修煉愛情 Practice Love"),  # 20 of 22
    ("《孤勇者》陈奕迅 (动态歌词版)", "《孤勇者》陈奕迅"),
    ("野人『动态歌词MV』", "野人"),
    ("消愁【動態歌詞Lyrics】", "消愁"),
    ("【抖音】别知己", "别知己"),
    ("【純音樂】Summer", "Summer"),
    ("晴天 (官方 MV 现场)", "晴天"),  # 4 of 6: two thirds
    ("晴天 (官方 现场版)", "晴天 (官方 现场版)"),  # 3 of 5
    ("一点点 (Cover 葛東琪)", "一点点 (Cover 葛東琪)"),  # none of it
    ("夜に駆ける (公式 歌詞付き)", "夜に駆ける"),
    ("夜に駆ける [フル]", "夜に駆ける"),
    ("밤편지 [가사]", "밤편지"),
    ("Dynamite (공식 뮤직비디오)", "Dynamite"),
    # A group of Latin words alone: every word a video's, one strong among them, a lyric channel's beside them too.
    ("Bohemian Rhapsody (Karaoke Version)", "Bohemian Rhapsody"),
    ("Creep [8D Audio]", "Creep"),
    ("起风了 (Pinyin Lyrics)", "起风了"),
    ("晴天 [KTV]", "晴天"),
    ("Creep (Live Version)", "Creep (Live Version)"),
    # CJK is Hangul, kana and Han alone, as normalize.py's _CJK: a letter just outside them is no CJK, so its group is
    # read by the Latin rule (written as escapes: a source that is NFC-normalized turns U+F900 into U+8C48).
    ("Song (Official Video \uf900)", "Song"),
    ("Song (Official Video \uf8ff)", "Song (Official Video \uf8ff)"),
    ("Song (Official Video \ua000)", "Song (Official Video \ua000)"),
    ("Song (Official Video \ud7b0)", "Song (Official Video \ud7b0)"),
    ("Song (Official MV \ua731)", "Song (Official MV \ua731)"),
])
def test_cjk_noise_goes_by_its_share_of_the_group(text, cleaned):
    assert clean(text) == cleaned


@pytest.mark.parametrize("text,cleaned", [
    ("Song （Official Video）", "Song"),
    ("Song ［Official Audio］", "Song"),
    ("晴天〈官方MV〉", "晴天"),
    ("晴天〖动态歌词〗", "晴天"),
    ("晴天〔高清〕", "晴天"),
    ("晴天《动态歌词》", "晴天"),
    ("南山南（feat. 宋冬野）", "南山南（feat. 宋冬野）"),  # as written
    ("Song (Official Video】", "Song (Official Video】"),  # "(" closes on ")" alone
])
def test_each_bracket_closes_on_its_own_mark(text, cleaned):
    assert clean(text) == cleaned


@pytest.mark.parametrize("text,cleaned", [
    # A group's edges are word edges for the words loose at the end: "Official MV" after "】" goes, as after a space.
    ("周杰倫 Jay Chou【告白氣球 Love Confession】Official MV", "周杰倫 Jay Chou【告白氣球 Love Confession】"),
    ("Hysteria [Live]HD", "Hysteria [Live]"),
    # A lyric channel's words are a video's there too: 官方完整版 is made of them alone.
    ("薛之谦 Joker Xue【演员】官方完整版 MV", "薛之谦 Joker Xue【演员】"),
    ("薛之谦 - 演员 官方完整版 MV", "薛之谦 - 演员"),
    ("周杰倫 - 晴天 高清 HD", "周杰倫 - 晴天"),
])
def test_words_glued_to_a_bracket_are_words(text, cleaned):
    assert clean(text) == cleaned


@pytest.mark.parametrize("channel,expected", [
    ("Radiohead - Topic", "Radiohead"), ("AdeleVEVO", "Adele"), ("EstopaVEVO", "Estopa"), ("Queen Official", "Queen"),
    ("Shakira Oficial", "Shakira"), ("Nick Cani", "Nick Cani"), ("VEVO", "VEVO"), ("", ""),
])
def test_a_channels_name_loses_its_label_words(channel, expected):
    assert clean_channel(channel) == expected


# --- rule 1: two parts ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Silvana Estrada - Que problema", "Silvana Estrada – Que problema",
                                  "Silvana Estrada — Que problema", "Silvana Estrada | Que problema"])
def test_two_parts_are_the_artist_and_the_title_whoever_they_are(conn, text):
    # A dash with a space on each side (an en or em dash, "|", "~" or "//" too), known to no one or not.
    assert read_names(conn, text) == ("Silvana Estrada", "Que problema")


def test_two_parts_split_at_the_first_mark_with_a_word_on_each_side(conn):
    assert read_names(conn, "Muse - Hysteria - Live") == ("Muse", "Hysteria - Live")
    assert read_names(conn, "Nick Cani – Vikingos veganos") == ("Nick Cani", "Vikingos veganos")
    assert read_names(conn, "宋冬野 - 斑马斑马") == ("宋冬野", "斑马斑马")
    assert read_names(conn, "Sílvana Éstrada - Qué problema") == ("Sílvana Éstrada", "Qué problema")  # as written
    for nobody in (" - Creep", "Radiohead - ", "!! - Creep", "-", ""):
        assert read_names(conn, nobody) is None, nobody


def test_a_videos_title_noise_goes_before_its_parts_are_read(conn):
    # The owner's Estopa video, read as its pasted link's panel reads it, and as the same words typed as a query.
    assert read_names(conn, "Estopa - Como Camarón [Videoclip Oficial] HD", channel="EstopaVEVO") == (
        "Estopa", "Como Camarón")
    assert read_names(conn, "Estopa - Como Camarón [Videoclip Oficial] HD") == ("Estopa", "Como Camarón")
    assert read_names(conn, "“Bohemian Rhapsody” (Official Lyric Video)", channel="Queen Official") == (
        "Queen", "Bohemian Rhapsody")


@pytest.mark.parametrize("title,channel,expected", [
    ("Radiohead - Creep", "Radiohead", ("Radiohead", "Creep")),
    ("Oasis - Wonderwall (Official Video)", "Oasis", ("Oasis", "Wonderwall")),
    ("Queen – Bohemian Rhapsody (Official Video Remastered)", "Queen Official", ("Queen", "Bohemian Rhapsody")),
    ("Soda Stereo - De Música Ligera (Video Oficial)", "Soda Stereo", ("Soda Stereo", "De Música Ligera")),
    ("Estopa - Como Camarón [Videoclip Oficial] HD", "EstopaVEVO", ("Estopa", "Como Camarón")),
    ("Manu Chao | Clandestino (Letra)", "Manu Chao Official", ("Manu Chao", "Clandestino")),
    ("Rosalía - DESPECHÁ (Official Video)", "RosaliaVEVO", ("Rosalía", "DESPECHÁ")),
    ("宋冬野 - 斑马斑马", "宋冬野", ("宋冬野", "斑马斑马")),
    ("Los Prisioneros - El Baile de los que Sobran (En Vivo)", "Los Prisioneros",
     ("Los Prisioneros", "El Baile de los que Sobran (En Vivo)")),  # a version of the song: kept
    ("Daft Punk - Get Lucky (feat. Pharrell Williams) [Official Audio]", "Daft Punk",
     ("Daft Punk", "Get Lucky (feat. Pharrell Williams)")),
    ("Queen - “Bohemian Rhapsody”", "Queen Official", ("Queen", "Bohemian Rhapsody")),
    # The owner's second example: the artist's own upload, an em dash, a Visualizer: never "Silvana" and "Estrada".
    ("Silvana Estrada — Qué Problema (Visualizer)", "Silvana Estrada", ("Silvana Estrada", "Qué Problema")),
    # Lyric channels' uploads: their words and a line of the lyrics in brackets, never the song's.
    ("孟维来 - 野人『不再借世人的手 替我开脱，遍野的花骨朵 也能够耐住寂寞。』『动态歌词MV』", "雲夢music", ("孟维来", "野人")),
    ("毛不易 - 消愁「当你走进这欢乐场 背上所有的梦与想」【動態歌詞Lyrics】", "火星電台", ("毛不易", "消愁")),
    ("【抖音】海来阿木 - 别知己【动态歌词】", "抖音", ("海来阿木", "别知己")),
    ("【純音樂】久石讓 - Summer", "純音樂", ("久石讓", "Summer")),
    ("林俊傑 JJ Lin - 修煉愛情 Practice Love (華納 official 高畫質 HD 官方完整版MV)", "華納音樂 Warner Music Taiwan",
     ("林俊傑 JJ Lin", "修煉愛情 Practice Love")),
])
def test_a_videos_title_of_two_parts_is_its_artist_and_its_song(conn, title, channel, expected):
    assert read_names(conn, title, channel=channel) == expected


@pytest.mark.parametrize("title,channel,expected", [
    ("[MV] IU(아이유) _ Blueming(블루밍)", "1theK (원더케이)", ("IU(아이유)", "Blueming(블루밍)")),
    ("[MV] BTS(방탄소년단) _ Dynamite", "1theK (원더케이)", ("BTS(방탄소년단)", "Dynamite")),
    ("Hot_Chip - Over and Over", "Hot Chip", ("Hot_Chip", "Over and Over")),  # one inside a word parts nothing
])
def test_an_underscore_between_spaces_parts_the_text(conn, title, channel, expected):
    # 1theK's uploads: " _ " is a mark, as " | " is.
    assert read_names(conn, title, channel=channel) == expected


def test_two_parts_are_turned_round_when_the_second_is_a_known_artist_and_the_first_isnt(conn):
    # The owner's fan upload, "Somos vikingos veganos - Hyperfanes" by kintanedu: as written while no one knows the
    # band, turned round once an index does.
    title, channel = VIKINGOS_VIDEO
    assert read_names(conn, title, channel=channel) == ("Somos vikingos veganos", "Hyperfanes")
    assert read_names(conn, title) == ("Somos vikingos veganos", "Hyperfanes")
    index(conn, songs_of("hyperfanes", 5, 70000))
    assert read_names(conn, title, channel=channel) == ("Hyperfanes", "Somos vikingos veganos")
    assert read_names(conn, title) == ("Hyperfanes", "Somos vikingos veganos")
    # A first part that is a known artist stays first; so does one when neither is known.
    assert read_names(conn, "Hyperfanes - Vikingos") == ("Hyperfanes", "Vikingos")
    # The channel of the video the text is the title of is known too.
    assert read_names(conn, "Wonderwall - Oasis", channel="Oasis") == ("Oasis", "Wonderwall")
    assert read_names(conn, "Oasis - Wonderwall (Official Video)", channel="Oasis") == ("Oasis", "Wonderwall")


# --- rule 2: a known artist first, or after " by " ----------------------------------------------------------------

def test_title_by_a_known_artist(conn):
    index(conn, [*SILVANA, *songs_of("ben-e-king", 6, 67000), (67100, "ben-e-king", "stand-by-me", "chords")])
    assert read_names(conn, "Que problema by Silvana Estrada") == ("Silvana Estrada", "Que problema")
    assert read_names(conn, "Stand by Me by Ben E King") == ("Ben E King", "Stand by Me")  # the last " by "
    assert read_names(conn, "Que problema BY silvana estrada") == ("silvana estrada", "Que problema")
    assert read_names(conn, "Que problema by Nick Cani") is None  # no one known


def test_stand_by_me_is_a_title(conn):
    # No artist "Me"; and the title whole is Ben E. King's song, which no rule cuts.
    assert read_names(conn, "Stand by Me") is None
    index(conn, [*songs_of("ben-e-king", 6, 67000), (67100, "ben-e-king", "stand-by-me", "chords"),
                 *songs_of("me", 6, 67200), *songs_of("stand", 6, 67300)])
    assert read_names(conn, "Stand by Me") is None
    assert read_names(conn, "Ben E King Stand by Me") == ("Ben E King", "Stand by Me")


def test_a_known_artist_starting_a_query_is_its_artist_and_the_rest_its_title(conn):
    # "Silvana Estrada Que problema": the longest run of first words an index knows as an artist's whole name, never
    # the query cut at its first space ("Silvana" and "Estrada").
    index(conn, SILVANA)
    assert read_names(conn, "Silvana Estrada Que problema") == ("Silvana Estrada", "Que problema")
    assert read_names(conn, "silvana estrada que problema") == ("silvana estrada", "que problema")
    # As typed: its case, its accents, its spaces folded.
    assert read_names(conn, "Silvana Estrada Qué problema") == ("Silvana Estrada", "Qué problema")
    assert read_names(conn, "silvana  estrada   qué problema") == ("silvana estrada", "qué problema")
    assert read_names(conn, "Sílvana Estrada Que problema") == ("Sílvana Estrada", "Que problema")
    # A title of one word, of words of any length.
    assert read_names(conn, "Silvana Estrada Tregua") == ("Silvana Estrada", "Tregua")
    assert read_names(conn, "Silvana Estrada Y") == ("Silvana Estrada", "Y")


def test_silvana_estrada_que_problema_with_no_index_is_the_title_alone(conn):
    # The owner's query with an empty Ultimate Guitar index: nothing knows her, so nothing says where the artist ends.
    assert read_names(conn, "silvana estrada que problema") is None


def test_a_query_no_known_artist_starts_names_no_artist(conn):
    # A word an index knows as a small artist's name (Que, Estrada: one song each) is no proof: "Que problema" is a
    # title. A one-word name with ONE_WORD_ARTIST songs is an artist.
    index(conn, SILVANA)
    for query in ("Que problema", "Estrada de tierra", "Nick Cani Vikingos veganos", "Silvana", "Silvana Estrada",
                  "Silvana Estrada !!", "", "   "):
        assert read_names(conn, query) is None, query
    assert read_names(conn, "Silvanas Adio Maria") == ("Silvanas", "Adio Maria")  # one word, six songs: an artist


def test_que_problema_is_a_title(conn):
    assert read_names(conn, "Que problema") is None
    index(conn, SILVANA)  # "Que", an artist of one song on Ultimate Guitar
    assert read_names(conn, "Que problema") is None


def test_love_me_tender_is_a_title_whole(conn):
    # Elvis's song, not "Me Tender" by Love, the band of many songs its first word names.
    assert read_names(conn, "Love Me Tender") is None
    index(conn, [*songs_of("love", 8, 66000), (66100, "elvis-presley", "love-me-tender", "chords")])
    assert read_names(conn, "Love Me Tender") is None
    assert read_names(conn, "Love Alone Again Or") == ("Love", "Alone Again Or")


def test_accents_and_case_are_kept_as_typed_but_a_library_artist_is_as_the_library_writes_them(conn):
    add_song(conn, "Natalia Lafourcade", "Hasta la Raíz")
    add_song(conn, "Björk", "Jóga")
    add_song(conn, "Björk", "Hyperballad")
    lacuerda(conn)
    assert read_names(conn, "natalia lafourcade Nunca es suficiente") == ("Natalia Lafourcade", "Nunca es suficiente")
    assert read_names(conn, "bjork army of me") == ("Björk", "army of me")
    assert read_names(conn, "bjork army of me", songs=()) is None  # without your songs, no one knows Björk here
    assert read_names(conn, "Joaquín Sabina 19 días y 500 noches") == ("Joaquín Sabina", "19 días y 500 noches")
    assert read_names(conn, "joaquin sabina y nos dieron las diez") == ("joaquin sabina", "y nos dieron las diez")
    assert read_names(conn, "Estopa La raja de tu falda") == ("Estopa", "La raja de tu falda")
    assert read_names(conn, "Hasta la Raíz") is None  # your song's title, whole


def test_gtptabs_and_harptabs_artists_are_known_too(conn):
    gtptabs_pages(conn, "https://gtptabs.com/tabs/1/silvana-estrada/tregua.html")
    harptabs_index(conn)
    assert read_names(conn, "Silvana Estrada Que problema") == ("Silvana Estrada", "Que problema")
    assert read_names(conn, "Billy Joel Uptown girl") == ("Billy Joel", "Uptown girl")


# --- one-word artists of your library -------------------------------------------------------------------------------

def test_a_mistaken_line_makes_no_one_word_artist_for_later_queries(conn):
    # The owner's mistake: wanted.txt got "Silvana - Estrada". One line, no sheet, no index that knows "Silvana": no
    # artist "Silvana", so the next "silvana estrada que problema" isn't cut at its first space either.
    add_song(conn, "Silvana", "Estrada")
    assert read_names(conn, "silvana estrada que problema") is None
    assert read_names(conn, "Silvana Tregua") is None
    # The video suggested for it, her own channel's: her whole name, never the mistaken one-word artist.
    assert read_names(conn, "silvana estrada que problema", video=SILVANA_VIDEO) == ("Silvana Estrada", "que problema")
    index(conn, SILVANA)
    assert read_names(conn, "silvana estrada que problema") == ("silvana estrada", "que problema")


def test_a_one_word_artist_of_yours_is_known_once_its_credible(conn, cfg):
    # Credible: a sheet from a site for one of their songs, two songs or more of theirs, or an index that knows them.
    lone = add_song(conn, "Silvana", "Estrada")
    assert read_names(conn, "Silvana Tregua") is None
    keep_sheet(conn, cfg.library_dir, lone, "[Am]la", tab_id=1)
    assert read_names(conn, "silvana tregua") == ("Silvana", "tregua")


def test_two_songs_of_a_one_word_artist_make_them_known(conn):
    add_song(conn, "Hyperfanes", "Otra")
    assert read_names(conn, "Hyperfanes Somos vikingos veganos") is None
    add_song(conn, "Hyperfanes", "Una más")
    assert read_names(conn, "hyperfanes Somos vikingos veganos") == ("Hyperfanes", "Somos vikingos veganos")


def test_an_index_that_knows_a_one_word_artist_of_yours_makes_them_known(conn):
    add_song(conn, "Hyperfanes", "Otra")
    index(conn, [(70000, "hyperfanes", "otra", "chords")])  # one song there: too few alone, enough with yours
    assert read_names(conn, "Hyperfanes Somos vikingos veganos") == ("Hyperfanes", "Somos vikingos veganos")


def test_an_artist_of_yours_of_two_words_or_more_is_known_however_few_their_songs(conn):
    add_song(conn, "Nick Cani", "Vegan Vikings")
    assert read_names(conn, "nick cani vikingos veganos") == ("Nick Cani", "vikingos veganos")
    assert read_names(conn, "nick cani vikingos veganos", songs=list_songs(conn)) == ("Nick Cani", "vikingos veganos")


# --- rule 3: a video's channel --------------------------------------------------------------------------------------

@pytest.mark.parametrize("title,channel,expected", [
    ("Creep", "Radiohead - Topic", ("Radiohead", "Creep")),
    ("Hello", "AdeleVEVO", ("Adele", "Hello")),
    ("Me Gustas Tú (Con Letra)", "Manu Chao", ("Manu Chao", "Me Gustas Tú")),
    ("Vegan Vikings", "Nick Cani", ("Nick Cani", "Vegan Vikings")),
    ("宋冬野 - 斑马斑马", "宋冬野", ("宋冬野", "斑马斑马")),
    ("Silvana Estrada — Qué Problema (Visualizer)", "Silvana Estrada", ("Silvana Estrada", "Qué Problema")),
    ("Rosalía - DESPECHÁ (Official Video)", "RosaliaVEVO", ("Rosalía", "DESPECHÁ")),
    ("Soda Stereo - De Música Ligera (Video Oficial)", "Soda Stereo", ("Soda Stereo", "De Música Ligera")),
    ("Stand by Me", "Ben E. King - Topic", ("Ben E. King", "Stand by Me")),
    ("野人『不再借世人的手 替我开脱，遍野的花骨朵 也能够耐住寂寞。』", "孟维来", ("孟维来", "野人")),  # a lyric quoted goes
    ("", "", ("", "")),
    ("(Official Video)", "Oasis", ("Oasis", "")),
])
def test_a_videos_title_none_of_the_rules_reads_is_its_channels_song(conn, title, channel, expected):
    assert read_names(conn, title, channel=channel) == expected


def test_a_videos_title_a_rule_reads_is_read_so_before_its_channel_counts(conn):
    # A fan's channel: the title's own known artist first; a title whole is its channel's song ("Love Me Tender").
    index(conn, [*SILVANA, *songs_of("love", 8, 66000), (66100, "elvis-presley", "love-me-tender", "chords")])
    assert read_names(conn, "Silvana Estrada Que problema", channel="kintanedu") == ("Silvana Estrada", "Que problema")
    assert read_names(conn, "Love Me Tender", channel="Elvis Presley - Topic") == ("Elvis Presley", "Love Me Tender")


# --- rule 4: the suggested video's song -----------------------------------------------------------------------------

def test_the_channel_of_the_video_suggested_for_a_query_is_a_known_artist_for_it(conn):
    # The owner's "silvana estrada que problema" with an empty index: YouTube's first video is Silvana Estrada's own,
    # so the query's first two words are its artist, as the channel writes them.
    assert read_names(conn, "silvana estrada que problema", video=SILVANA_VIDEO) == ("Silvana Estrada", "que problema")
    assert read_names(conn, "que problema by silvana estrada", video=SILVANA_VIDEO) == (
        "Silvana Estrada", "que problema")


def test_a_query_that_is_the_suggested_videos_song_names_its_artist(conn):
    # "creep": YouTube's first video is Radiohead's "Creep", from "Radiohead - Topic"; "que problema", her own upload.
    assert read_names(conn, "creep", video=("Creep", "Radiohead - Topic")) == ("Radiohead", "creep")
    assert read_names(conn, "que problema", video=SILVANA_VIDEO) == ("Silvana Estrada", "que problema")


def test_a_suggested_video_of_another_song_names_no_artist(conn):
    # A channel that names no run of the query's first words, its video another song: no artist of the query.
    assert read_names(conn, "que problema", video=("Tregua", "Silvana Estrada")) is None
    assert read_names(conn, "vikingos veganos", video=VIKINGOS_VIDEO) is None
    assert read_names(conn, "Somos vikingos veganos", video=VIKINGOS_VIDEO) is None  # the fan's first part: no artist
    assert read_names(conn, "creep") is None
