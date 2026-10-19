import pytest

from caracole.normalize import (
    KEY_VERSION,
    clean_title,
    compact,
    display_key,
    fold,
    has_han,
    identity_key,
    name_forms,
    romanize,
    slug_key,
    split_variant,
    title_variant,
    ug_slug_key,
)


def test_fold_strips_accents_and_transliterates():
    assert fold("De Música Ligera") == "de musica ligera"
    assert fold("Señorita") == "senorita"
    assert fold("Ærøskøbing Straße") == "aeroskobing strasse"


@pytest.mark.parametrize(
    "raw,clean",
    [
        ("Wonderwall - Remastered", "Wonderwall"),
        ("Let It Be - Remastered 2009", "Let It Be"),
        ("Song (feat. X)", "Song"),
        ("Song [feat. X]", "Song"),
        ("Song (Live at Wembley)", "Song"),
        ("Song - Live", "Song"),
        ("Song - Live at the BBC", "Song"),
        ("Song - Radio Edit", "Song"),
        ("Persiana Americana - Remasterizado 2007", "Persiana Americana"),
        ("Song - 2011 Remaster", "Song"),
        ("Song - Remastered Version", "Song"),
        ("Song (with Y)", "Song"),
        ("Creep - Acoustic", "Creep"),
        ("Song - Mono", "Song"),
        ("Song - 2015 Stereo Mix", "Song"),
        ("Sin Documentos", "Sin Documentos"),
        ("Live and Let Die", "Live and Let Die"),
        ("斑马，斑马", "斑马，斑马"),
    ],
)
def test_clean_title(raw, clean):
    assert clean_title(raw) == clean


TEARS_IN_HEAVEN_UNPLUGGED = (
    "Tears in Heaven - Acoustic; Live at MTV Unplugged, Bray Film Studios, Windsor, England, UK, "
    "1/16/1992; 2013 Remaster"
)


@pytest.mark.parametrize(
    "raw,clean",
    [
        # Spanish and Portuguese live and acoustic versions: a ranking preference, not a song.
        ("Persiana Americana - En Vivo", "Persiana Americana"),
        ("Lamento Boliviano (En Vivo)", "Lamento Boliviano"),
        ("De Música Ligera - En Vivo en el Estadio River Plate", "De Música Ligera"),
        ("Song - En Directo", "Song"),
        ("Song (En Directo)", "Song"),
        ("Song (Acústico)", "Song"),
        ("Song - Acústica", "Song"),
        ("Song - Acústico MTV", "Song"),
        ("La Flaca - Versión Acústica", "La Flaca"),
        ("Song (Versión Acústica)", "Song"),
        ("Song (Ao Vivo)", "Song"),
        ("Song - Ao Vivo No Rio", "Song"),
        # Spotify's mixes, edits and session recordings.
        ("Here Comes The Sun - 2019 Mix", "Here Comes The Sun"),
        ("Song - 2018 Mix", "Song"),
        ("Song (2019 Mix)", "Song"),
        ("Song - Single Edit", "Song"),
        ("Song - Demo Version", "Song"),
        ("Song - Radio Version", "Song"),
        ("Song - Recorded at Spotify Studios NYC", "Song"),
        ("Song - Spotify Sessions", "Song"),
        ("Song - Part 2 - BBC Session", "Song - Part 2"),
        ('Lose Yourself - From "8 Mile" Soundtrack', "Lose Yourself"),
        # Unplugged suffixes run on after a ";".
        (TEARS_IN_HEAVEN_UNPLUGGED, "Tears in Heaven"),
        ("Song - Live; 2013 Remaster", "Song"),
    ],
)
def test_clean_title_spanish_live_acoustic_and_mix_suffixes(raw, clean):
    assert clean_title(raw) == clean


@pytest.mark.parametrize(
    "title",
    ["En Vivo", "Vivo Por Ella", "Directo al Corazón", "Acústico", "Session Man", "Mix Tape",
     "Song - Vivo", "From Me to You", "Song - From Me to You"],
)
def test_clean_title_keeps_titles_that_only_look_like_suffixes(title):
    assert clean_title(title) == title


def test_title_variant():
    assert title_variant("Creep - Acoustic") == "acoustic"
    assert title_variant("Song (Live at Wembley)") == "live"
    assert title_variant("Song - Live") == "live"
    assert title_variant("Creep") is None
    assert title_variant("Live and Let Die") is None


@pytest.mark.parametrize(
    "title,variant",
    [
        ("Persiana Americana - En Vivo", "live"),
        ("Lamento Boliviano (En Vivo)", "live"),
        ("Song (Ao Vivo)", "live"),
        ("Song - En Directo", "live"),
        ("Song (Acústico)", "acoustic"),
        ("La Flaca - Versión Acústica", "acoustic"),
        (TEARS_IN_HEAVEN_UNPLUGGED, "acoustic"),
        ("Here Comes The Sun - 2019 Mix", None),
        ("Song - Recorded at Spotify Studios NYC", None),
    ],
)
def test_title_variant_reads_spanish_and_portuguese(title, variant):
    assert title_variant(title) == variant


def test_a_live_version_shares_the_studio_versions_identity():
    live = identity_key("Soda Stereo", "De Música Ligera - En Vivo")
    acoustic = identity_key("Jarabe de Palo", "La Flaca - Versión Acústica")
    assert (live, acoustic) == ("soda-stereo/de-musica-ligera", "jarabe-de-palo/la-flaca")


@pytest.mark.parametrize(
    "raw,key",
    [
        ("Soda Stereo", "soda-stereo"),
        ("The Beatles", "beatles"),
        ("Simon & Garfunkel", "simon-garfunkel"),
        ("Simon and Garfunkel", "simon-garfunkel"),
        ("I'll Be Yours", "ill-be-yours"),
        ("Don’t Look Back in Anger", "dont-look-back-in-anger"),
        ("Fontaines D.C.", "fontaines-d-c"),
        ("19 Días y 500 Noches", "19-dias-y-500-noches"),
        ("Señorita", "senorita"),
        ("Guns N' Roses", "guns-n-roses"),
        ("AC/DC", "ac-dc"),
        ("The The", "the"),
    ],
)
def test_slug_key(raw, key):
    assert slug_key(raw) == key


def test_ug_slug_key_matches_source_side():
    assert ug_slug_key("the-rifles") == "rifles"
    assert ug_slug_key("fontaines-d-c-") == "fontaines-d-c"
    assert ug_slug_key("adam-and-the-ants") == slug_key("Adam & the Ants") == "adam-the-ants"
    assert ug_slug_key("-feast") == "feast"
    assert ug_slug_key("armokto-") == "armokto"


def test_compact():
    assert compact("ac-dc") == "acdc"
    assert compact("song-dongye") == compact(slug_key("song dong ye")) == "songdongye"


def test_split_variant():
    assert split_variant("froggy-went-a-courtin-intro") == ("froggy-went-a-courtin", "intro")
    assert split_variant("wonderwall-acoustic") == ("wonderwall", "acoustic")
    assert split_variant("wonderwall") == ("wonderwall", None)
    assert split_variant("live") == ("live", None)


def test_identity_key():
    assert identity_key("Soda Stereo", "De Música Ligera - Remastered 2007") == "soda-stereo/de-musica-ligera"
    assert identity_key("The Beatles", "Let It Be - Remastered 2009") == "beatles/let-it-be"


@pytest.mark.parametrize(
    "one,other",
    [
        # Traditional and Simplified Han: Spotify's Taiwanese releases use Traditional.
        (("宋冬野", "斑馬斑馬"), ("宋冬野", "斑马斑马")),
        (("周杰倫", "告白氣球"), ("周杰伦", "告白气球")),
        # A leading Spanish article on the artist, as the matcher tries it both ways.
        (("Los Enanitos Verdes", "Lamento Boliviano"), ("Enanitos Verdes", "Lamento Boliviano")),
        # An artist's "y" and "&", as "and" and "&" already are.
        (("Fito y Fitipaldis", "Soldadito Marinero"), ("Fito & Fitipaldis", "Soldadito Marinero")),
        # Number words and digits.
        (("Soda Stereo", "Té Para Tres"), ("Soda Stereo", "Té para 3")),
        (("The Jackson Five", "ABC"), ("The Jackson 5", "ABC")),
    ],
)
def test_one_song_written_two_ways_has_one_identity(one, other):
    assert identity_key(*one) == identity_key(*other)


def test_identity_keys_of_already_canonical_names_stay_as_they_were():
    assert identity_key("宋冬野", "斑马斑马") == "宋冬野/斑马斑马"
    assert identity_key("Enanitos Verdes", "Lamento") == "enanitos-verdes/lamento"
    assert identity_key("Soda Stereo", "De Música Ligera") == "soda-stereo/de-musica-ligera"
    # An article that is the whole name, or leads a title, stays; so does a title's "y".
    assert identity_key("La", "La Flaca") == "la/la-flaca"
    assert identity_key("Joaquín Sabina", "19 Días y 500 Noches") == "joaquin-sabina/19-dias-y-500-noches"


def test_slug_keys_still_meet_ugs_slugs():
    # The matcher and the stored index compare slug keys: identity's folding stays out of them.
    assert slug_key("Fito y Fitipaldis") == "fito-y-fitipaldis"
    assert slug_key("Los Enanitos Verdes") == "los-enanitos-verdes"
    assert slug_key("Té Para Tres") == "te-para-tres"
    assert slug_key("斑馬斑馬") == "斑馬斑馬"


def test_display_key():
    assert display_key("Soda Stereo", "De Música Ligera - Remastered 2007") == "Soda Stereo - De Música Ligera"


def test_cjk_keys_survive_and_ignore_punctuation():
    # Spotify writes the title with a full-width comma; LRCLIB and hand-typed lists often omit it.
    assert slug_key("斑马，斑马") == slug_key("斑马斑马") == "斑马斑马"
    assert identity_key("宋冬野", "斑马，斑马") == identity_key("宋冬野", "斑马斑马") == "宋冬野/斑马斑马"


def test_non_latin_titles_keep_distinct_keys():
    assert slug_key("さくら") != slug_key("ひまわり")
    assert slug_key("さくら") != ""


def test_han_detection_and_romanization():
    assert has_han("斑马斑马") and has_han("宋冬野")
    assert not has_han("Soda Stereo")
    assert romanize("斑马，斑马") == "ban ma ban ma"
    assert romanize("宋冬野") == "song dong ye"
    assert romanize("Soda Stereo") == "Soda Stereo"
    assert compact(slug_key(romanize("宋冬野"))) == compact(ug_slug_key("song-dongye"))


def test_names_made_only_of_and_keep_a_key():
    # 32 real UG URLs have artist or song slugs that are only "and" tokens (the band "And And And").
    assert slug_key("And And And") == ug_slug_key("and-and-and") == "and-and-and"
    assert ug_slug_key("and") == "and"


# --- a name's forms: how UG writes non-Latin names --------------------------------------------


def shares_a_form(one: str, other: str) -> bool:
    """Whether two names have a form in common, hyphens aside, as the artist-page fetch compares them."""
    return bool({compact(f) for f in name_forms(one)} & {compact(f) for f in name_forms(other)})


# The forms UG gave the live case (2026-10-19): the song, and its artist.
BANMA_UG = "斑马 斑马 Banma Banma Zebra Zebra"
SONG_DONGYE_UG = "Song Dongye (宋冬野)"


@pytest.mark.parametrize("wanted", ["斑马斑马", "斑馬斑馬", "Banma Banma", "Ban Ma Ban Ma", "斑马，斑马"])
def test_original_romanization_and_translation_unseparated(wanted):
    assert shares_a_form(BANMA_UG, wanted)


def test_the_translation_after_a_romanization_is_a_form_of_its_own():
    assert shares_a_form(BANMA_UG, "Zebra Zebra")
    assert {"banma-banma", "zebra-zebra"} <= set(name_forms(BANMA_UG))


@pytest.mark.parametrize("ug,wanted", [
    ("莉莉安 Lilian", "莉莉安"),
    ("莉莉安 Lilian", "Lilian"),
    ("与我交谈 Speak With Me", "与我交谈"),
    ("与我交谈 Speak With Me", "Speak With Me"),
])
def test_original_and_translation(ug, wanted):
    assert shares_a_form(ug, wanted)


@pytest.mark.parametrize("wanted", ["宋冬野", "Song Dongye", "宋冬野 (Song Dongye)", "Song Dong Ye", "song-dongye"])
def test_romanization_and_original_in_brackets(wanted):
    assert shares_a_form(SONG_DONGYE_UG, wanted)


@pytest.mark.parametrize("ug,wanted", [
    ("打上花火 (Uchiage Hanabi)", "打上花火"),  # Japanese kanji, which no romanizer here reads
    ("打上花火 (Uchiage Hanabi)", "Uchiage Hanabi"),
    ("さくら (Sakura)", "さくら"),  # kana
    ("Lemon (レモン)", "レモン"),
    ("봄날 (Spring Day)", "봄날"),  # Hangul
    ("봄날 (Spring Day)", "Spring Day"),
    ("Кино (Kino)", "Кино"),  # Cyrillic
    ("Кино (Kino)", "Kino"),
    ("Группа крови / Gruppa Krovi", "Группа крови"),
])
def test_other_scripts_in_the_same_patterns(ug, wanted):
    assert shares_a_form(ug, wanted)


@pytest.mark.parametrize("ug", [
    "斑马，斑马", "斑马·斑马", "斑马・斑马", "「斑马斑马」", "『斑马斑马』", "斑马斑马（Banma Banma）",
    "【斑马斑马】Zebra Zebra", "《斑马斑马》 Banma Banma",
])
def test_fullwidth_and_cjk_punctuation_between_the_parts(ug):
    assert shares_a_form(ug, "斑马斑马")


@pytest.mark.parametrize("ug,wanted", [
    ("斑马斑马 / Zebra Zebra", "斑马斑马"),
    ("斑马斑马 / Zebra Zebra", "Zebra Zebra"),
    ("斑马斑马 - Banma Banma", "斑马斑马"),
    ("Song Dongye - 宋冬野", "宋冬野"),
    ("宋冬野 / Song Dongye", "Song Dongye"),
    ("斑马斑马 Banma Banma - Zebra Zebra", "Zebra Zebra"),
])
def test_separators_between_the_parts(ug, wanted):
    assert shares_a_form(ug, wanted)


@pytest.mark.parametrize("ug", ["董小姐", "郭源潮", "莉莉安 Lilian", "与我交谈 Speak With Me"])
def test_another_song_of_the_artist_never_shares_a_form(ug):
    assert not shares_a_form(ug, "斑马斑马")
    assert not shares_a_form(ug, BANMA_UG)


@pytest.mark.parametrize("ug,generic,own", [
    ("斑马斑马 Live", "Live", "斑马斑马"),
    ("斑马斑马 (Acoustic)", "Acoustic", "斑马斑马"),
    ("斑马斑马 Remix", "Remix", "斑马斑马"),
    ("斑马斑马 (Intro)", "Intro", "斑马斑马"),
    ("斑马斑马 (Live Version)", "Live Version", "斑马斑马"),
    ("斑马斑马 2", "2", "斑马斑马 2"),
    ("斑马斑马 B", "B", "斑马斑马"),
    ("爱 Ai", "Ai", "爱"),  # under three Latin letters
    ("Кино (Live)", "Live", "Кино"),
])
def test_a_generic_part_never_makes_a_match_on_its_own(ug, generic, own):
    assert not shares_a_form(ug, generic)
    assert shares_a_form(ug, own)  # the rest of the name still matches


def test_two_names_with_their_own_scripts_are_no_bilingual_name():
    # A duet written "A (甲) & B (乙)" is neither of its singers.
    duet = "Joey Yung (容祖儿) & Eason Chan (陈奕迅)"
    assert not shares_a_form(duet, "陈奕迅") and not shares_a_form(duet, "Joey Yung")


@pytest.mark.parametrize("name", [
    "Soda Stereo", "Paranoid / War Pigs", "Creep (Acoustic)", "Live and Let Die", "Wonderwall - Remix",
    "De Música Ligera", "AC/DC", "The The", "Mötley Crüe",
    "Ŋoma Band", "Mələk Live",  # Latin letters that fold to no ASCII one are Latin all the same
])
def test_latin_names_have_their_slug_key_alone(name):
    assert name_forms(name) == (slug_key(name),)


def test_chinese_names_lead_with_their_keys_and_pinyin():
    assert name_forms("斑马斑马") == ("斑马斑马", "ban-ma-ban-ma")
    assert name_forms("斑馬斑馬") == ("斑馬斑馬", "ban-ma-ban-ma", "斑马斑马")  # Traditional, then Simplified
    assert name_forms(SONG_DONGYE_UG)[:2] == (slug_key(SONG_DONGYE_UG), slug_key(romanize(SONG_DONGYE_UG)))
    assert name_forms(BANMA_UG)[0] == slug_key(BANMA_UG) == "斑马斑马-banma-banma-zebra-zebra"


def test_forms_are_for_comparing_and_keys_stay_as_they_were():
    # Forms never change a song's key, so no re-keying (KEY_VERSION) comes with them.
    assert KEY_VERSION == 2
    assert identity_key(SONG_DONGYE_UG, BANMA_UG) == "song-dongye-宋冬野/斑马斑马-banma-banma-zebra-zebra"
