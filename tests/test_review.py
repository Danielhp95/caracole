from tabarr.overrides import load_overrides
from tabarr.review import ReviewIO, review_songs
from tabarr.songs import get_song, update_song

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


def test_title_only_accept_writes_match_without_alias(conn, cfg):
    review_song(conn, "Someone", "Hallelujah", cands=[
        {"artist_key": "jeff-buckley", "song_key": "hallelujah", "score": 100.0, "step": "title_only"}])
    review_songs(conn, cfg, Script("1").io())
    o = load_overrides(cfg.overrides_file)
    assert o.match["someone/hallelujah"] == ("jeff-buckley", "hallelujah")
    assert not o.alias


def test_ignore(conn, cfg):
    s = review_song(conn)
    stats = review_songs(conn, cfg, Script("i").io())
    assert "soda/persiana-americana" in load_overrides(cfg.overrides_file).ignore
    assert get_song(conn, s.id).status == "ignored" and stats.ignored == 1


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
