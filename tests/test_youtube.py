"""youtube.py: YouTube's video addresses, picking a song's video from a search, and running yt-dlp.

yt-dlp is ``FakeYtDlp`` (helpers/fake_ytdlp.py), a script that answers from a plan: no test
reaches YouTube.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pytest
from helpers.fake_ytdlp import FakeYtDlp, entry

from caracole.config import ProviderPolicy
from caracole.http import BudgetExhausted, ProviderBlocked, ProviderError
from caracole.youtube import (
    Video,
    VideoUnavailable,
    YtDlp,
    choose,
    parse_search,
    search_query,
    video_id_from_url,
    watch_url,
)

ID = "dQw4w9WgXcQ"


# --- addresses ---------------------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={ID}",
    f"https://www.youtube.com/watch?v={ID}&list=PL123&index=4",
    f"https://youtube.com/watch?feature=share&v={ID}",
    f"http://m.youtube.com/watch?v={ID}",
    f"https://music.youtube.com/watch?v={ID}&si=abc",
    f"www.youtube.com/watch?v={ID}",
    f"https://youtu.be/{ID}",
    f"https://youtu.be/{ID}?t=42",
    f"https://www.youtube.com/shorts/{ID}",
    f"https://www.youtube.com/embed/{ID}",
    f"https://www.youtube.com/live/{ID}?feature=share",
    f"  https://WWW.YouTube.com/watch?v={ID}  ",
])
def test_a_videos_address_as_a_browser_shows_it_gives_its_id(url):
    assert video_id_from_url(url) == ID


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/playlist?list=PL123",
    "https://www.youtube.com/@radiohead",
    "https://www.youtube.com/results?search_query=creep",
    "https://www.youtube.com/watch?v=short",
    f"https://www.youtube.com.evil.example/watch?v={ID}",
    f"https://example.com/watch?v={ID}",
    f"ftp://www.youtube.com/watch?v={ID}",
    ID,
    "none",
    "",
    5,
    None,
])
def test_anything_else_is_no_video(url):
    assert video_id_from_url(url) is None


def test_a_video_is_asked_for_at_its_plain_watch_address():
    assert watch_url(ID) == f"https://www.youtube.com/watch?v={ID}"
    assert Video(ID, "t", "c").url == watch_url(ID)


# --- search results ---------------------------------------------------------------------------


def test_a_flat_search_gives_each_results_id_title_channel_and_duration():
    text = (
        '{"_type": "playlist", "entries": ['
        f'{{"id": "{ID}", "title": "Creep", "channel": "Radiohead - Topic", "duration": 239.0, '
        f'"url": "https://www.youtube.com/watch?v={ID}"}},'
        '{"id": "AAAAAAAAAAA", "title": "Live now", "channel": "X", "duration": null, "live_status": "is_live",'
        ' "url": "https://www.youtube.com/watch?v=AAAAAAAAAAA"},'
        '{"id": "BBBBBBBBBBB", "title": "A short", "channel": "Y", "duration": 30,'
        ' "url": "https://www.youtube.com/shorts/BBBBBBBBBBB"},'
        '{"title": "no id"}, {"id": "bad id", "title": "x"}, 7'
        ']}'
    )
    videos = parse_search(text)
    assert [v.id for v in videos] == [ID, "AAAAAAAAAAA", "BBBBBBBBBBB"]
    assert videos[0] == Video(ID, "Creep", "Radiohead - Topic", 239.0)
    assert videos[1].live and not videos[0].live
    assert videos[2].short and not videos[0].short


def test_a_search_answer_that_is_no_json_is_a_provider_error():
    with pytest.raises(ProviderError, match="youtube"):
        parse_search("not json")


# --- choosing the song's video -----------------------------------------------------------------


@dataclass
class S:
    artist: str
    title: str
    artists: list[str] = field(default_factory=list)


def pick(song, *videos, expected=None, skip=()):
    found = choose(song, [Video(*v) if isinstance(v, tuple) else v for v in videos], expected, skip=skip)
    return found.id if found else None


def v(vid, title, channel, duration=239.0):
    return Video(vid.ljust(11, "x")[:11], title, channel, duration)


CREEP = S("Radiohead", "Creep")


def test_the_artists_topic_channel_comes_first_then_official_audio_then_the_artists_own_channel():
    video = v("video", "Radiohead - Creep (Official Video)", "Radiohead")
    lyrics = v("lyrics", "Radiohead - Creep (Lyrics)", "7clouds")
    audio = v("audio", "Radiohead - Creep (Official Audio)", "Radiohead")
    topic = v("topic", "Creep", "Radiohead - Topic")
    assert pick(CREEP, lyrics, video, audio, topic) == topic.id
    assert pick(CREEP, lyrics, video, audio) == audio.id
    assert pick(CREEP, lyrics, video) == video.id
    assert pick(CREEP, lyrics) == lyrics.id


def test_a_vevo_channel_is_the_artists_own():
    vevo = v("vevo", "Radiohead - Creep", "RadioheadVEVO")
    other = v("other", "Radiohead - Creep", "Music Channel 24")
    assert pick(CREEP, other, vevo) == vevo.id


def test_the_title_must_be_the_songs_not_one_that_starts_like_it():
    help_ = S("The Beach Boys", "Help")
    assert pick(help_, v("rhonda", "The Beach Boys - Help Me Rhonda", "The Beach Boys")) is None
    assert pick(help_, v("help", "The Beach Boys - Help!", "The Beach Boys")) == "helpxxxxxxx"
    # Quoted, or the artist and the title run together with words around them.
    assert pick(CREEP, v("quoted", "Radiohead 'Creep' official video", "Radiohead")) == "quotedxxxxx"
    assert pick(CREEP, v("plain", "Radiohead Creep Official Music Video HD", "Radiohead")) == "plainxxxxxx"


def test_the_artist_must_be_named_by_the_channel_or_the_title():
    assert pick(CREEP, v("other", "Creep", "Stone Temple Pilots - Topic")) is None
    assert pick(CREEP, v("anyone", "Creep (Official Audio)", "Someone Else")) is None
    assert pick(CREEP, v("fan", "Creep - Radiohead | lyrics", "lyricsfan")) == "fanxxxxxxxx"


def test_the_duration_must_fit_lrclibs_and_the_closest_wins():
    near = v("near", "Radiohead - Creep (Lyrics)", "lyricsfan", 243.0)
    off = v("off", "Creep", "Radiohead - Topic", 270.0)  # an album cut 30 s longer
    exact = v("exact", "Radiohead - Creep [Lyrics]", "other lyrics", 238.5)
    assert pick(CREEP, off, expected=239.0) is None
    assert pick(CREEP, near, off, expected=239.0) == near.id
    assert pick(CREEP, near, exact, expected=239.0) == exact.id  # within 2 s, synced lyrics fit it
    assert pick(CREEP, off) == off.id  # no duration to fit


def test_without_a_duration_to_fit_a_clip_or_a_compilation_is_no_song():
    assert pick(CREEP, v("clip", "Radiohead - Creep", "Radiohead", 20.0)) is None
    assert pick(CREEP, v("hour", "Radiohead - Creep", "Radiohead", 3600.0)) is None


@pytest.mark.parametrize("title", [
    "Creep - Radiohead (Acoustic Cover)",
    "Radiohead - Creep (Live at Glastonbury 1997)",
    "Radiohead - Creep (Karaoke Version)",
    "Radiohead - Creep (Instrumental)",
    "How to play Creep by Radiohead - Guitar Lesson",
    "Radiohead - Creep guitar tutorial (chords)",
    "Radiohead - Creep (slowed + reverb)",
    "Radiohead - Creep (sped up)",
    "Radiohead - Creep (Nightcore)",
    "Radiohead - Creep (8D Audio)",
    "Radiohead - Creep (Remix)",
    "Reacting to Radiohead - Creep (reaction)",
])
def test_covers_live_karaoke_lessons_and_slowed_versions_lose_to_the_song_and_win_only_alone(title):
    worse = v("worse", title, "Radiohead")
    song = v("song", "Radiohead - Creep (Lyrics)", "a lyrics channel")
    assert pick(CREEP, worse, song) == song.id
    assert pick(CREEP, worse) == worse.id  # better than nothing


def test_a_song_thats_live_or_acoustic_takes_its_own_version():
    live = S("Radiohead", "Creep - Live")
    concert = v("concert", "Radiohead - Creep (Live)", "Radiohead")
    studio = v("studio", "Creep", "Radiohead - Topic")
    assert pick(live, concert, studio) == concert.id
    acoustic = S("Radiohead", "Creep (Acoustic)")
    assert pick(acoustic, v("acoustic", "Radiohead - Creep (Acoustic)", "Radiohead"), studio) == "acousticxxx"


def test_streams_shorts_and_skipped_videos_are_never_picked():
    live = Video("livexxxxxxx", "Radiohead - Creep", "Radiohead", None, live=True)
    short = Video("shortxxxxxx", "Radiohead - Creep", "Radiohead", 239.0, short=True)
    gone = v("gone", "Creep", "Radiohead - Topic")
    assert pick(CREEP, live, short) is None
    assert pick(CREEP, gone, skip={gone.id}) is None


def test_names_in_two_scripts_meet():
    banma = S("宋冬野", "斑马，斑马")
    assert pick(banma, v("hanzi", "宋冬野 - 斑马，斑马 (Official Audio)", "宋冬野")) == "hanzixxxxxx"
    assert pick(banma, v("brackets", "宋冬野《斑马斑马》", "Song Dongye")) == "bracketsxxx"
    assert pick(banma, v("pinyin", "Song Dongye - Banma Banma", "Song Dongye - Topic")) == "pinyinxxxxx"
    assert pick(banma, v("twice", "Song Dongye 宋冬野 - Banma Banma 斑马斑马", "Modern Sky")) == "twicexxxxxx"
    assert pick(banma, v("other", "赵雷 - 成都", "赵雷")) is None


def test_any_of_the_songs_artists_counts():
    duet = S("Simon & Garfunkel", "The Boxer", ["Simon & Garfunkel", "Paul Simon"])
    assert pick(duet, v("paul", "Paul Simon - The Boxer (Official Audio)", "Paul Simon")) == "paulxxxxxxx"


def test_the_search_asks_for_the_artist_and_the_clean_title():
    assert search_query(S("Radiohead", "Creep - Remastered 2009")) == "Radiohead Creep"


# --- running yt-dlp ------------------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


@pytest.fixture
def fake(tmp_path):
    return FakeYtDlp(tmp_path / "bin")


def runner(fake, tmp_path, *, budget=6, delay=(15.0, 30.0), events=None, clock=None, **kw):
    clock = clock or Clock()
    return YtDlp(fake.bin, ProviderPolicy(budget=budget, delay=delay), tmp_path / "cache",
                 on_event=events.append if events is not None else None, sleep=clock.sleep, clock=clock, **kw)


def test_a_search_runs_yt_dlp_flat_with_no_cookies_config_or_plugins(fake, tmp_path):
    fake.search("Radiohead Creep", entry(ID, "Creep", "Radiohead - Topic", 239))
    found = runner(fake, tmp_path).search("Radiohead Creep")
    assert found == [Video(ID, "Creep", "Radiohead - Topic", 239.0)]
    (argv,) = fake.argvs()
    assert argv[-2:] == ["--", "ytsearch8:Radiohead Creep"]  # the query is never an option
    for flag in ("--ignore-config", "--no-plugin-dirs", "--no-cookies", "--no-cookies-from-browser",
                 "--no-remote-components", "--flat-playlist", "--dump-single-json", "--no-playlist"):
        assert flag in argv, flag
    assert not any(a.startswith(("--cookies", "--username", "--password", "--netrc", "--extractor-args",
                                 "--proxy")) for a in argv if a != "--cookies-from-browser")
    assert argv[argv.index("--sleep-requests") + 1] == "2"
    assert argv[argv.index("--cache-dir") + 1] == str(tmp_path / "cache" / "yt-dlp")
    assert argv[argv.index("--retries") + 1] == "0"


def test_a_query_that_looks_like_an_option_is_still_the_query(fake, tmp_path):
    runner(fake, tmp_path).search("--exec rm -rf ~ Creep")
    assert fake.argvs()[0][-2:] == ["--", "ytsearch8:--exec rm -rf ~ Creep"]


def test_a_download_takes_the_audio_alone_as_m4a_into_the_folder_given(fake, tmp_path):
    fake.video(ID, "Creep", "Radiohead - Topic", 239, ext="m4a", data="AAC bytes")
    into = tmp_path / "download"
    into.mkdir()
    got = runner(fake, tmp_path).download(ID, into)
    assert got.path == into / "audio.m4a" and got.path.read_text() == "AAC bytes"
    assert got.video == Video(ID, "Creep", "Radiohead - Topic", 239.0)
    (argv,) = fake.argvs()
    assert argv[-2:] == ["--", watch_url(ID)]
    assert argv[argv.index("-o") + 1] == str(into / "audio.%(ext)s")
    for flag in ("-x", "--no-playlist", "--no-mtime", "--ignore-config", "--no-cookies"):
        assert flag in argv, flag
    assert argv[argv.index("--audio-format") + 1] == "m4a"
    assert argv[argv.index("--sleep-interval") + 1] == "10"
    assert argv[argv.index("--max-sleep-interval") + 1] == "20"
    assert argv[argv.index("--max-filesize") + 1] == "100M"


@pytest.mark.parametrize("printed", ["elsewhere/audio.m4a", "into/missing.m4a", "into/audio.txt", "into"])
def test_a_download_that_leaves_no_audio_file_in_its_folder_is_an_error(fake, tmp_path, printed):
    into = tmp_path / "into"
    into.mkdir()
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "audio.m4a").write_text("x")
    (into / "audio.txt").write_text("x")
    fake.video(ID, print_path=str(tmp_path / printed))
    with pytest.raises(ProviderError, match="no audio file"):
        runner(fake, tmp_path).download(ID, into)


def test_deno_runs_without_its_jit_so_the_units_memory_protection_holds(fake, tmp_path, monkeypatch):
    # yt-dlp solves YouTube's JavaScript with deno, whose JIT dies under systemd's
    # MemoryDenyWriteExecute; caracole's units keep that, so V8 runs as an interpreter.
    monkeypatch.delenv("DENO_V8_FLAGS", raising=False)
    runner(fake, tmp_path).search("q")
    assert fake.calls()[0]["env"]["DENO_V8_FLAGS"] == "--jitless"
    monkeypatch.setenv("DENO_V8_FLAGS", "--jitless --max-old-space-size=256")
    runner(fake, tmp_path).search("q")
    assert fake.calls()[1]["env"]["DENO_V8_FLAGS"] == "--jitless --max-old-space-size=256"


def test_runs_are_counted_against_the_budget_and_paced(fake, tmp_path):
    clock, events = Clock(), []
    yt = runner(fake, tmp_path, budget=2, clock=clock, events=events, rng=FixedRng(20.0))
    yt.search("a")
    yt.search("b")
    with pytest.raises(BudgetExhausted):
        yt.search("c")
    assert yt.requests_made == 2 and len(fake.argvs()) == 2
    assert clock.slept == [20.0]  # before the second run, not the first
    assert [e.decision for e in events] == ["ok", "ok", "budget"]
    assert events[0].provider == "youtube" and events[0].url == "ytsearch8:a"


class FixedRng:
    def __init__(self, value):
        self.value = value

    def uniform(self, low, high):
        assert low <= self.value <= high
        return self.value


@pytest.mark.parametrize("stderr,status", [
    (("ERROR: [youtube] dQw4w9WgXcQ: Sign in to confirm you’re not a bot. Use --cookies-from-browser or "
      "--cookies for the authentication."), None),
    ("ERROR: [youtube] dQw4w9WgXcQ: Sign in to confirm you're not a bot. This helps protect our community.", None),
    ("ERROR: unable to download video data: HTTP Error 429: Too Many Requests", 429),
    ("ERROR: unable to download video data: HTTP Error 403: Forbidden", 403),
    (("ERROR: [youtube] dQw4w9WgXcQ: This content isn't available, try again later. The current session has "
      "been rate-limited by YouTube for up to an hour."), None),
])
def test_a_bot_check_a_429_or_a_403_is_a_block_and_nothing_more_runs(fake, tmp_path, stderr, status):
    fake.video(ID, stderr=stderr, exit=1)
    events = []
    yt = runner(fake, tmp_path, events=events)
    with pytest.raises(ProviderBlocked) as e:
        yt.download(ID, tmp_path)
    assert e.value.provider == "youtube" and e.value.status == status
    with pytest.raises(ProviderBlocked, match="blocked earlier this run"):
        yt.search("anything")
    assert len(fake.argvs()) == 1  # nothing retried
    assert [ev.decision for ev in events] == ["blocked"]


@pytest.mark.parametrize("stderr", [
    "ERROR: [youtube] dQw4w9WgXcQ: Video unavailable",
    "ERROR: [youtube] dQw4w9WgXcQ: Video unavailable. This video has been removed by the uploader",
    "ERROR: [youtube] dQw4w9WgXcQ: Private video. Sign in if you've been granted access to this video",
    "ERROR: [youtube] dQw4w9WgXcQ: Sign in to confirm your age. This video may be inappropriate for some users.",
    "ERROR: [youtube] dQw4w9WgXcQ: The uploader has not made this video available in your country",
    "ERROR: [youtube] dQw4w9WgXcQ: Join this channel to get access to members-only content like this video",
])
def test_a_video_that_cant_be_had_without_logging_in_is_unavailable_not_a_block(fake, tmp_path, stderr):
    fake.video(ID, stderr=stderr, exit=1)
    yt = runner(fake, tmp_path)
    with pytest.raises(VideoUnavailable):
        yt.download(ID, tmp_path)
    yt.search("next")  # YouTube still answers
    assert len(fake.argvs()) == 2


def test_any_other_failure_is_an_error_that_names_yt_dlps_reason(fake, tmp_path):
    fake.search("q", stderr="WARNING: something\nERROR: Unable to download API page: [Errno -3] Temporary failure "
                            "in name resolution", exit=1)
    events = []
    with pytest.raises(ProviderError, match="Temporary failure in name resolution") as e:
        runner(fake, tmp_path, events=events).search("q")
    assert not isinstance(e.value, (ProviderBlocked, VideoUnavailable))
    assert [ev.decision for ev in events] == ["error"]


def test_a_run_that_takes_too_long_is_stopped_and_is_an_error(fake, tmp_path):
    fake.search("slow", sleep=30)
    started = time.monotonic()
    with pytest.raises(ProviderError, match="took longer than 1 s") as e:
        runner(fake, tmp_path, timeouts=(1.0, 1.0)).search("slow")
    assert time.monotonic() - started < 15
    assert isinstance(e.value.__cause__, TimeoutError)


def test_a_missing_yt_dlp_is_an_error_naming_it(tmp_path):
    yt = YtDlp(str(tmp_path / "no-such-yt-dlp"), ProviderPolicy(6, (0, 0)), tmp_path / "cache", sleep=lambda s: None)
    with pytest.raises(ProviderError, match="no-such-yt-dlp"):
        yt.search("q")


def test_closing_lets_go_once(fake, tmp_path):
    closed = []
    yt = runner(fake, tmp_path, on_close=lambda: closed.append(1))
    yt.close()
    yt.close()
    assert closed == [1]
