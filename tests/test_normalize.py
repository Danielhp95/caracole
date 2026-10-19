import pytest

from tabarr.normalize import (
    clean_title,
    compact,
    display_key,
    fold,
    has_han,
    identity_key,
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
    assert identity_key("Soda Stereo", "De Música Ligera - En Vivo") == "soda-stereo/de-musica-ligera"
    assert identity_key("Jarabe de Palo", "La Flaca - Versión Acústica") == "jarabe-de-palo/la-flaca"


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
