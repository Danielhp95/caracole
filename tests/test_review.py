import pytest

from caracole.overrides import load_overrides, override_key
from caracole.review import ReviewIO, review_songs
from caracole.songs import get_song, update_song

from conftest import add_song


class Script:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.out: list[str] = []
        self.prompts: list[str] = []

    def io(self):
        return ReviewIO(read=self.read, write=self.out.append)

    def read(self, prompt):
        self.prompts.append(prompt)
        return self.answers.pop(0)


def review_song(conn, artist="Soda", title="Persiana Americana", cands=None):
    s = add_song(conn, artist, title)
    update_song(conn, s.id, review=True, match_decision="review", match_candidates=cands or [
        {"artist_key": "soda-stereo", "song_key": "persiana-americana", "score": 82.0, "step": "fuzzy_artist"},
        {"artist_key": "soda-stereo", "song_key": "persiana", "score": 76.0, "step": "fuzzy_artist"},
    ])
    return s


def test_accept_writes_match_and_alias(conn, cfg):
    s = review_song(conn)
    script = Script("1")
    rematched = []
    stats = review_songs(conn, cfg, script.io(), rematch=lambda: rematched.append(True))
    o = load_overrides(cfg.overrides_file)
    assert o.match["soda/persiana-americana"] == ("soda-stereo", "persiana-americana")
    assert o.alias["soda"] == ("soda-stereo",)
    assert stats.accepted == 1 and rematched == [True]
    assert get_song(conn, s.id).review is False
    assert any("Soda - Persiana Americana" in line for line in script.out)
    assert any("soda-stereo/persiana-americana" in line for line in script.out)


def test_accept_keeps_the_aliases_you_curated(conn, cfg):
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(
        '[alias]\n# UG files them under two names\n'
        '"Bob Marley & The Wailers" = ["bob-marley", "bob-marley-the-wailers"]\n', encoding="utf-8")
    review_song(conn, "Bob Marley & The Wailers", "Is This Love", cands=[
        {"artist_key": "bob-marley", "song_key": "is-this-love", "score": 88.0, "step": "fuzzy_title"}])
    stats = review_songs(conn, cfg, Script("1").io())
    o = load_overrides(cfg.overrides_file)
    assert stats.accepted == 1
    assert o.match[override_key("Bob Marley & The Wailers - Is This Love")] == ("bob-marley", "is-this-love")
    assert o.alias["bob-marley-the-wailers"] == ("bob-marley", "bob-marley-the-wailers")
    assert "# UG files them under two names" in cfg.overrides_file.read_text(encoding="utf-8")


def test_title_only_accept_writes_match_without_alias(conn, cfg):
    review_song(conn, "Someone", "Hallelujah", cands=[
        {"artist_key": "jeff-buckley", "song_key": "hallelujah", "score": 100.0, "step": "title_only"}])
    review_songs(conn, cfg, Script("1").io())
    o = load_overrides(cfg.overrides_file)
    assert o.match["someone/hallelujah"] == ("jeff-buckley", "hallelujah")
    assert not o.alias


def test_a_catch_all_accept_writes_match_without_alias(conn, cfg):
    # misc-musicals files every show's songs: an alias would make it the artist of all of epic's songs.
    review_song(conn, "epic", "I'm not sorry for loving you", cands=[
        {"artist_key": "misc-musicals", "song_key": "epic-the-musical-not-sorry-for-loving-you", "score": 94.1,
         "step": "catch_all"}])
    review_songs(conn, cfg, Script("1").io())
    o = load_overrides(cfg.overrides_file)
    assert o.match["epic/im-not-sorry-for-loving-you"] == ("misc-musicals", "epic-the-musical-not-sorry-for-loving-you")
    assert not o.alias


def test_a_misspelt_artists_accept_writes_its_alias(conn, cfg):
    review_song(conn, "Coldplya", "Yellow", cands=[
        {"artist_key": "coldplay", "song_key": "yellow", "score": 100.0, "step": "typo_artist"}])
    review_songs(conn, cfg, Script("1").io())
    assert load_overrides(cfg.overrides_file).alias["coldplya"] == ("coldplay",)


def test_ignore(conn, cfg):
    s = review_song(conn)
    stats = review_songs(conn, cfg, Script("i").io())
    assert "soda/persiana-americana" in load_overrides(cfg.overrides_file).ignore
    assert get_song(conn, s.id).status == "ignored" and stats.ignored == 1


def test_none_of_these_rejects_every_candidate_shown_and_keeps_the_song(conn, cfg):
    s = review_song(conn)
    script = Script("n")
    rematched = []
    stats = review_songs(conn, cfg, script.io(), rematch=lambda: rematched.append(True))
    o = load_overrides(cfg.overrides_file)
    assert o.reject["soda/persiana-americana"] == frozenset({("soda-stereo", "persiana-americana"),
                                                             ("soda-stereo", "persiana")})
    assert not o.ignore and not o.match and not o.alias
    assert (get_song(conn, s.id).review, get_song(conn, s.id).status) == (False, "wanted")
    assert stats.rejected == 1 and stats.changed and rematched == [True]
    assert script.prompts == ["Pick 1-2, (n)one of these, (p)in a URL, (i)gnore, (s)kip, (q)uit: "]


def test_none_of_these_is_offered_only_with_candidates(conn, cfg):
    s = add_song(conn, "Radiohead", "Creep")
    update_song(conn, s.id, review=True, match_decision="review", match_candidates=[])
    script = Script("n")
    stats = review_songs(conn, cfg, script.io())
    assert script.prompts == ["Pick (p)in a URL, (i)gnore, (s)kip, (q)uit: "]
    assert stats.skipped == 1 and stats.rejected == 0 and not cfg.overrides_file.exists()


def test_pin_url(conn, cfg):
    review_song(conn)
    stats = review_songs(conn, cfg, Script("p", "https://tabs.ultimate-guitar.com/tab/1081460").io())
    assert load_overrides(cfg.overrides_file).pin["soda/persiana-americana"] == (1081460,)
    assert stats.pinned == 1


def test_bad_pin_url_is_reported_and_skipped(conn, cfg):
    s = review_song(conn)
    script = Script("p", "https://example.com/x")
    stats = review_songs(conn, cfg, script.io())
    assert stats.skipped == 1 and get_song(conn, s.id).review is True
    assert any("not an Ultimate Guitar tab URL" in line for line in script.out)
    assert not cfg.overrides_file.exists()


def test_enter_at_the_url_prompt_skips_the_song(conn, cfg):
    s = review_song(conn)
    script = Script("p", "")
    stats = review_songs(conn, cfg, script.io())
    assert stats.skipped == 1 and stats.pinned == 0 and get_song(conn, s.id).review is True
    assert not any("not an Ultimate Guitar tab URL" in line for line in script.out)
    assert not cfg.overrides_file.exists()


def test_skip_and_quit(conn, cfg):
    review_song(conn, "A", "One")
    review_song(conn, "B", "Two")
    review_song(conn, "C", "Three")
    script = Script("s", "q")
    rematched = []
    stats = review_songs(conn, cfg, script.io(), rematch=lambda: rematched.append(True))
    assert stats.skipped == 1 and len(script.prompts) == 2
    assert rematched == []
    assert not cfg.overrides_file.exists()


def test_nothing_to_review(conn, cfg):
    script = Script()
    stats = review_songs(conn, cfg, script.io())
    assert stats.accepted == stats.skipped == 0
    assert any("Nothing to review" in line for line in script.out)


# --- one answer at a time (caracole review --song, and caracole serve's picker) -----------------


def test_the_candidates_a_review_lists_are_numbered_as_it_numbers_them(conn, cfg):
    from caracole.review import candidates_of

    s = review_song(conn, cands=[
        {"artist_key": "soda-stereo", "song_key": "persiana-americana", "score": 82.0, "step": "fuzzy_artist"},
        {"artist_key": None, "song_key": "persiana", "score": 80.0, "step": "fuzzy_artist"},  # no artist: unlisted
        *({"artist_key": "soda-stereo", "song_key": f"song-{n}", "score": 70.0, "step": "fuzzy_title"}
          for n in range(10)),
    ])
    listed = candidates_of(get_song(conn, s.id))
    assert [c["song_key"] for c in listed] == ["persiana-americana", *(f"song-{n}" for n in range(8))]
    script = Script("q")
    review_songs(conn, cfg, script.io())
    assert script.prompts == ["Pick 1-9, (n)one of these, (p)in a URL, (i)gnore, (s)kip, (q)uit: "]


def test_accepting_one_candidate_writes_what_its_number_writes(conn, cfg):
    from caracole.review import accept, candidates_of

    s = get_song(conn, review_song(conn).id)
    accept(conn, cfg, s, candidates_of(s)[0])
    o = load_overrides(cfg.overrides_file)
    assert o.match["soda/persiana-americana"] == ("soda-stereo", "persiana-americana")
    assert o.alias["soda"] == ("soda-stereo",)
    assert get_song(conn, s.id).review is False


def test_accepting_a_cover_or_a_catch_alls_song_writes_no_alias(conn, cfg):
    from caracole.review import accept, candidates_of, writes_alias

    cover = review_song(conn, "Someone", "Hallelujah", cands=[
        {"artist_key": "jeff-buckley", "song_key": "hallelujah", "score": 100.0, "step": "title_only"}])
    show = review_song(conn, "epic", "Not Sorry for Loving You", cands=[
        {"artist_key": "misc-musicals", "song_key": "epic-the-musical-not-sorry-for-loving-you", "score": 94.1,
         "step": "catch_all"}])
    typo = review_song(conn, "Coldplya", "Yellow", cands=[
        {"artist_key": "coldplay", "song_key": "yellow", "score": 100.0, "step": "typo_artist"}])
    cover, show, typo = (get_song(conn, s.id) for s in (cover, show, typo))
    assert [writes_alias(s, candidates_of(s)[0]) for s in (cover, show, typo)] == [False, False, True]
    for s in (cover, show):
        accept(conn, cfg, s, candidates_of(s)[0])
    assert not load_overrides(cfg.overrides_file).alias


def test_none_of_these_as_one_answer_rejects_the_candidates_given(conn, cfg):
    from caracole.review import candidates_of, reject

    s = get_song(conn, review_song(conn).id)
    reject(conn, cfg, s, candidates_of(s))
    o = load_overrides(cfg.overrides_file)
    assert o.reject["soda/persiana-americana"] == frozenset({("soda-stereo", "persiana-americana"),
                                                             ("soda-stereo", "persiana")})
    assert not o.match and not o.alias
    assert (get_song(conn, s.id).review, get_song(conn, s.id).status) == (False, "wanted")


def test_review_songs_can_ask_about_one_song_alone(conn, cfg):
    review_song(conn, "A", "One")
    two = review_song(conn, "B", "Two")
    script = Script("1")
    stats = review_songs(conn, cfg, script.io(), only={two.id})
    assert stats.accepted == 1 and len(script.prompts) == 1
    assert any("[1/1] B - Two" in line for line in script.out)
    assert list(load_overrides(cfg.overrides_file).match) == [override_key("B - Two")]


@pytest.mark.parametrize("cand,words", [
    ({"step": "exact", "artist_key": "radiohead"}, "same artist and title"),
    ({"step": "alias", "artist_key": "radiohead"}, "under the artist's [alias]"),
    ({"step": "fuzzy_title", "artist_key": "radiohead"}, "title spelled differently"),
    ({"step": "fuzzy_artist", "artist_key": "radiohead"}, "artist spelled differently"),
    ({"step": "word_title", "artist_key": "radiohead"}, "a title of the artist's with words more or fewer"),
    ({"step": "typo_artist", "artist_key": "coldplay"}, "artist a letter or two off"),
    ({"step": "catch_all", "artist_key": "misc-musicals"}, "under UG's catch-all misc-musicals"),
    ({"step": "catch_all", "artist_key": "misc-originals"},
     "under UG's catch-all misc-originals, the performer's name first"),
    ({"step": "title_only", "artist_key": "jeff-buckley"}, "title only: another artist's song, probably a cover"),
    ({"step": "brand_new", "artist_key": "x"}, "brand_new"),
    ({"artist_key": "x"}, ""),
])
def test_each_step_is_said_in_plain_words(cand, words):
    from caracole.review import step_words

    assert step_words(cand) == words
