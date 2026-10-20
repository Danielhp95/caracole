"""YouTube, through yt-dlp: picking a song's video from a search, running yt-dlp.

The one place caracole runs yt-dlp, and the one exception to its rule of honouring
robots.txt: YouTube's closes ``/results`` and ``/youtubei/`` to crawlers, and yt-dlp's
search and downloads use both. The owner chose this, for a handful of their own songs a
night, on these terms (youtube_fetch.py runs it, AGENTS.md says why):

- **A budget and pauses** (``ProviderPolicy``, provider ``youtube``): each yt-dlp run, a
  search or a download, counts as a request against the budget, one at a time, with a
  random pause from the policy's ``delay`` between two runs; inside a run, yt-dlp's own
  pauses (``--sleep-requests``, ``--sleep-interval``) space out its requests.
- **Blocks honoured**: a "Sign in to confirm you're not a bot", an HTTP 429 or 403, a
  rate limit or a captcha is a ``ProviderBlocked``: nothing more runs, nothing is retried
  (``--retries 0``), and the run's cooldown follows as for any provider.
- **No cookies, no login, no PO tokens, no plugins, no config files**: yt-dlp gets
  ``--ignore-config``, ``--no-cookies``, ``--no-cookies-from-browser``,
  ``--no-plugin-dirs`` and ``--no-remote-components``, and nothing that logs in. A video
  that needs a login (private, age-restricted, members-only) is ``VideoUnavailable``.
  Nor any of caracole's secrets: yt-dlp runs in an environment of its own (``ytdlp_env``),
  without the unit's credentials or caracole's tokens.
- **Audio alone**: ``-x`` to m4a, never a playlist, at most 100 MB.

yt-dlp runs as a program, its arguments a list and never a shell, and whatever comes from
a song's name follows ``--``, so it is never read as an option. A run that takes too long,
or that caracole is interrupted in (Ctrl-C reaches caracole alone), is stopped with its
whole process group (yt-dlp, ffmpeg, deno).

YouTube's player needs JavaScript solved, which yt-dlp does with deno. Its JIT dies under
systemd's MemoryDenyWriteExecute, which caracole's units keep, so deno gets
``DENO_V8_FLAGS=--jitless`` unless the environment says otherwise.

A video's address (``video_id_from_url``, ``watch_url``) is youtube_urls.py's, which
overrides.py reads without this module and its HTTP errors; both names are here too.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import signal
import subprocess
import time
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from caracole.config import ProviderPolicy
from caracole.http import BudgetExhausted, Event, ProviderBlocked, ProviderError
from caracole.logs import request_line
from caracole.normalize import clean_title, compact, fold, name_forms, simplified, slug_key, title_variant
from caracole.youtube_urls import _VIDEO_ID, watch_url
from caracole.youtube_urls import video_id_from_url as video_id_from_url

log = logging.getLogger(__name__)

PROVIDER = "youtube"
SEARCH_RESULTS = 8
SEARCH_TIMEOUT = 120.0  # seconds: a search is one or two pages
DOWNLOAD_TIMEOUT = 900.0  # a download, its pauses and ffmpeg's remux
AUDIO_FORMAT = "m4a"  # AAC, which auto-chords decodes (btc.py, through torchaudio)
MAX_FILESIZE = "100M"
# What a download may leave: -x to m4a, or yt-dlp's best audio when that can't be converted.
AUDIO_SUFFIXES = (".m4a", ".mp4", ".aac", ".opus", ".ogg", ".oga", ".mp3", ".flac", ".wav")


@dataclass(frozen=True)
class Video:
    """A video, as a search lists it or a download reports it."""

    id: str
    title: str = ""
    channel: str = ""
    duration: float | None = None
    live: bool = False
    short: bool = False

    @property
    def url(self) -> str:
        return watch_url(self.id)

    def as_json(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "channel": self.channel, "duration": self.duration,
                "url": self.url}

    @classmethod
    def from_json(cls, data: Any) -> Video | None:
        if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not _VIDEO_ID.fullmatch(data["id"]):
            return None
        duration = data.get("duration")
        return cls(data["id"], str(data.get("title") or ""), str(data.get("channel") or ""),
                   float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None)


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_search(text: str) -> list[Video]:
    """The videos of yt-dlp's flat search (``--flat-playlist --dump-single-json``), in its order."""
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as e:  # or nested deeper than the parser goes
        raise ProviderError(PROVIDER, None, None, f"yt-dlp's search answer isn't JSON: {e}") from e
    entries = data.get("entries") if isinstance(data, dict) else None
    videos = []
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not _VIDEO_ID.fullmatch(e["id"]):
            continue
        videos.append(Video(
            e["id"], str(e.get("title") or ""), str(e.get("channel") or e.get("uploader") or ""),
            _number(e.get("duration")),
            live=e.get("live_status") in ("is_live", "is_upcoming"),
            short="/shorts/" in str(e.get("url") or ""),
        ))
    return videos


# --- choosing the song's video ---------------------------------------------------------------------


class _Song(Protocol):
    artist: str
    title: str
    artists: list[str]


def search_query(song: _Song) -> str:
    """What yt-dlp's search is asked: the artist and the title without its version suffix."""
    return f"{song.artist.strip()} {clean_title(song.title)}"


TOLERANCE_S = 20.0  # how far a video's length may be from LRCLIB's: an intro, not another cut
SYNCED_S = 2.0  # close enough for the synced lyrics' timings (autochords/run.py)
CLOSE_S = 5.0
SHORTEST_S, LONGEST_S = 45.0, 15 * 60.0  # with no length to fit: no clip, no compilation
EXACT, ALONE = 2, 1  # how surely a video's title is the song's (_Names.title_in)

# Where a video's title breaks into parts: a spaced dash, slash or bar, a bar, and brackets of
# every width ("Radiohead - Creep (Official Audio)", "宋冬野《斑马斑马》").
_PARTS = re.compile(r"\s+[-–—~/|｜:]\s+|\s*[|｜]\s*|[()\[\]{}（）［］｛｝【】「」『』《》〈〉〔〕〖〗]")
_QUOTED = re.compile(r"[\"“”«»]([^\"“”«»]+)[\"“”«»]|(?<!\w)['‘’]([^'‘’]+)['‘’](?!\w)")
# Words around a title that name no song: what a channel adds, and the versions below.
_DECORATION = frozenset({
    "official", "oficial", "officiel", "video", "videoclip", "clip", "audio", "music", "musica", "lyric", "lyrics",
    "letra", "paroles", "hd", "hq", "4k", "1080p", "mv", "m", "v", "visualizer", "version", "ver", "full",
    "remastered", "remaster", "by", "ft", "feat", "how", "to", "play", "learn", "easy", "guitar", "lesson",
    "tutorial", "chords", "chord", "tab", "tabs", "cover", "live", "karaoke", "instrumental", "slowed", "reverb",
    "sped", "up", "nightcore", "8d", "remix", "acoustic", "reaction", "piano", "bass", "drum", "boosted",
    "original", "single", "new", "premiere", "explicit", "radio", "edit", "with", "and", "the", "en", "vivo",
})
# Versions of a song that aren't the song as recorded, for chords: another key, another tempo, or
# talk over it. One is picked only when nothing better fits.
_UNWANTED = re.compile(
    r"\bcover(?:s|ed)?\b|翻唱|カバー|\blive\b|\ben vivo\b|\bao vivo\b|\ben directo\b|\bconcert\b|\bunplugged\b"
    r"|现场|現場|演唱会|演唱會|ライブ|\bkaraoke\b|\binstrumental\b|\bbacking track\b|\bminus one\b|伴奏|カラオケ"
    r"|노래방|\blesson\b|\btutorial\b|\bhow to play\b|\bchords?\b|\btabs?\b|\bguitar\b|教学|教學|吉他"
    r"|\bslowed\b|\breverb\b|\bsped up\b|\bspeed up\b|\bnightcore\b|\b8d\b|\bbass boosted\b|\b\d+ hours?\b"
    r"|\bloop\b|\breact(?:s|ion|ing)?\b|\bremix\b|\bmashup\b|\bparody\b|\bacoustic\b|\bpiano\b|\bdrum\b"
    r"|\bin the style of\b|\b(?:as )?made famous by\b|\boriginally performed by\b"
)
# Channels that upload karaoke versions whatever their titles say ("Creep - in the style of Radiohead").
_KARAOKE_CHANNEL = re.compile(r"karafun|sing ?king|sunfly|party ?tyme")
_TOPIC = re.compile(r"^(.*\S)\s+-\s+topic$", re.IGNORECASE)
_CHANNEL_SUFFIX = re.compile(r"\s*(?:vevo|official|oficial|officiel)(?:\s+channel)?$", re.IGNORECASE)
_OWN_CHANNEL = ("", "vevo", "official", "oficial", "officiel", "music", "tv", "band", "channel", "officialchannel")
_OFFICIAL_AUDIO = re.compile(r"\bofficial (?:hd )?audio\b")
_OFFICIAL_VIDEO = re.compile(r"\bofficial (?:hd )?(?:music )?video\b|\(official\)")


# Letters of Chinese, Japanese and Korean (Han, kana, Hangul and the jamo it folds to), and runs of one
# script or the other.
_CJK_CHARS = "ᄀ-ᇿ぀-ヿ㐀-䶿一-鿿가-힯豈-﫿\U00020000-\U0002ebef"
_CJK_LETTER = re.compile(f"[{_CJK_CHARS}]")
_SCRIPT_RUN = re.compile(f"[{_CJK_CHARS}]+|[^{_CJK_CHARS}]+")
# What a channel adds around a title in those scripts, and the versions _UNWANTED names, as
# _DECORATION in Latin letters (Simplified: a title is read in Simplified characters too).
_CJK_DECORATION = frozenset(compact(slug_key(w)) for w in (
    "官方", "官方版", "完整版", "正式版", "高清", "高音质", "无损", "音乐", "视频", "影片", "歌词", "动态歌词",
    "歌词版", "字幕", "中字", "首播", "音频", "公式", "フル", "가사", "공식", "뮤직비디오",
    "现场", "现场版", "演唱会", "翻唱", "伴奏", "吉他", "弹唱", "教学", "ライブ", "カバー", "カラオケ", "노래방",
))


def _compact_forms(name: str) -> set[str]:
    return {compact(f) for f in name_forms(name) if f}


class _Squeezed:
    """A video's title as a name is looked for in it with no space between words, as Chinese,
    Japanese and Korean write them: its words as ``slug_key`` reads them, a run of those scripts
    apart from Latin letters glued to it ("k歌之王" is "k" and "歌之王"), run together; and
    where each word starts and ends."""

    def __init__(self, text: str):
        words = [run for token in slug_key(text).split("-") if token for run in _SCRIPT_RUN.findall(token)]
        self.text = "".join(words)
        self.ends: dict[int, int] = {}  # each word's start, and its end
        at = 0
        for word in words:
            self.ends[at] = at + len(word)
            at += len(word)

    def word_around(self, start: int, end: int) -> tuple[int, int]:
        """Where the words holding ``text[start:end]`` start and end."""
        first = max(s for s in self.ends if s <= start)
        last = min(e for e in self.ends.values() if e >= end)
        return first, last


def _parts(text: str) -> list[str]:
    """The title whole, each part of it, and each quoted run in it."""
    found = [text, *_PARTS.split(text)]
    for m in _QUOTED.finditer(text):
        found.append(m.group(1) or m.group(2))
    return [p.strip() for p in found if p and p.strip()]


def _cjk(form: str) -> bool:
    return any(unicodedata.east_asian_width(c) == "W" for c in form)


class _Names:
    """A song's artists and title as a video's names are compared with them."""

    def __init__(self, song: _Song):
        artists = [a for a in (song.artists or [song.artist]) if a and a.strip()] or [song.artist]
        self.artists = set().union(*(_compact_forms(a) for a in artists))
        self.artist_slugs = {f for a in artists for f in name_forms(a) if f}
        title = clean_title(song.title)
        self.titles = _compact_forms(title)
        self.cjk_titles = {t for t in self.titles if _CJK_LETTER.search(t)}
        self.cjk_words = {a for a in self.artists if _CJK_LETTER.search(a)} | _CJK_DECORATION
        self.latin_artists = self.artists - self.cjk_words
        self.whole = fold(f"{song.title} {' '.join(artists)}")  # a version word here is the song's own
        self.variant = title_variant(song.title)

    def names(self, forms: set[str], text: str) -> bool:
        """Whether a part of ``text`` is one of these names, or, for one in Chinese, Japanese or
        Korean, whether the text holds it at all (those scripts don't space their words): for
        the artists, whom the title must name somewhere."""
        if any(forms & _compact_forms(part) for part in _parts(text)):
            return True
        squeezed = {compact(slug_key(t)) for t in (text, simplified(text))}
        return any(_cjk(f) and f in s for f in forms for s in squeezed)

    def title_in(self, title: str) -> int:
        """How surely the video's title is the song's: ``EXACT`` when a part of it is (quoted, or
        between dashes or brackets), or all that is left once the artist and words such as
        "official video" or 官方 are taken off; ``ALONE`` when a title in Chinese, Japanese or
        Korean is a word of its own among others ("周杰伦 Jay Chou 晴天 Sunny Day"); else 0. A title
        in those scripts that is only the start of a longer word is another song's: 雨 isn't
        雨下一整晚, nor 晴天 晴天娃娃."""
        if any(self.titles & _compact_forms(part) for part in _parts(title)) or self._stripped_to_title(title):
            return EXACT
        return self._cjk_title_in(title)

    def _cjk_title_in(self, title: str) -> int:
        if not self.cjk_titles:
            return 0
        found = 0
        for text in dict.fromkeys((title, simplified(title))):
            squeezed = _Squeezed(text)
            for form in self.cjk_titles:
                start = squeezed.text.find(form)
                while start >= 0:
                    end = start + len(form)
                    if self._covered(squeezed, 0, start) and self._covered(squeezed, end, len(squeezed.text)):
                        return EXACT
                    first, last = squeezed.word_around(start, end)
                    if self._covered(squeezed, first, start, latin=False) and \
                            self._covered(squeezed, end, last, latin=False):
                        found = ALONE
                    start = squeezed.text.find(form, start + 1)
        return found

    def _covered(self, squeezed: _Squeezed, start: int, end: int, *, latin: bool = True) -> bool:
        """Whether ``squeezed.text[start:end]`` is only the artist's names and words such as 官方, or,
        with ``latin``, also whole Latin words such as "official" or "mv" and numbers. A run that
        ends inside a Latin word is never covered: "Creep" isn't in "Creeper"."""
        text, ends = squeezed.text, squeezed.ends
        if start < end and ((start not in ends and not _CJK_LETTER.match(text[start]))
                            or (end not in ends.values() and not _CJK_LETTER.match(text[end - 1]))):
            return False
        reached, todo = {start}, [start]
        while todo:
            at = todo.pop()
            if at == end:
                return True
            steps = [at + len(w) for w in self.cjk_words if text.startswith(w, at)]
            if latin and at in ends and not _CJK_LETTER.match(text[at]):
                word = text[at:ends[at]]
                if word in _DECORATION or word.isdigit():
                    steps.append(ends[at])
                steps += [at + len(a) for a in self.latin_artists
                          if text.startswith(a, at) and at + len(a) in ends.values()]
            for step in steps:
                if step <= end and step not in reached:
                    reached.add(step)
                    todo.append(step)
        return False

    def _stripped_to_title(self, title: str) -> bool:
        """Whether the title, its artist and the words around it taken off its ends, is the song's:
        "Radiohead Creep Official Music Video HD", "How to play Creep by Radiohead"."""
        tokens = slug_key(title).split("-")
        artists = [a.split("-") for a in self.artist_slugs]
        while tokens:
            if compact("".join(tokens)) in self.titles:
                return True
            for a in artists:
                if tokens[: len(a)] == a and len(a) < len(tokens):
                    tokens = tokens[len(a):]
                    break
                if tokens[-len(a):] == a and len(a) < len(tokens):
                    tokens = tokens[: -len(a)]
                    break
            else:
                if tokens[-1] in _DECORATION or tokens[-1].isdigit():
                    tokens = tokens[:-1]
                elif tokens[0] in _DECORATION or tokens[0].isdigit():
                    tokens = tokens[1:]
                else:
                    return False
        return False

    def channel_is_artist(self, channel: str) -> bool:
        if not channel.strip():
            return False
        topic = _TOPIC.match(channel.strip())
        bare = _CHANNEL_SUFFIX.sub("", topic.group(1) if topic else channel.strip())
        if bare and self.names(self.artists, bare):
            return True
        squeezed = compact(slug_key(channel))
        return any(squeezed == a + suffix for a in self.artists for suffix in _OWN_CHANNEL)

    def artist_in(self, title: str) -> bool:
        if self.names(self.artists, title):
            return True
        tokens = slug_key(title).split("-")
        return any(tokens[: len(a)] == a or tokens[-len(a):] == a for a in (s.split("-") for s in self.artist_slugs))

    def unwanted(self, title: str, channel: str = "") -> bool:
        """Whether the video is a version of the song other than the song's own: a cover, live,
        karaoke, a lesson, slowed..., by its title or its channel's name (a karaoke channel's
        upload is karaoke). A word the song's own title or artist holds doesn't count."""
        if _KARAOKE_CHANNEL.search(fold(channel)) and not _KARAOKE_CHANNEL.search(self.whole):
            return True
        return any(not re.search(re.escape(m.group(0)), self.whole)
                   for text in (title, channel) for m in _UNWANTED.finditer(fold(text)))


def _official(names: _Names, video: Video) -> int:
    """How official the upload is: the artist's Topic channel (YouTube's own upload of the
    release), official audio, the artist's own channel or an official video, or anyone's."""
    topic = _TOPIC.match(video.channel.strip())
    if topic and names.channel_is_artist(video.channel):
        return 3
    folded = fold(video.title)
    own = names.channel_is_artist(video.channel)
    if _OFFICIAL_AUDIO.search(folded) and (own or names.artist_in(video.title)):
        return 2
    if own or _OFFICIAL_VIDEO.search(folded):
        return 1
    return 0


def _closeness(video: Video, expected: float | None) -> int | None:
    """0 to 3, closest first, or None when the length doesn't fit."""
    if video.duration is None:
        return 3
    if expected is None:
        return 0 if SHORTEST_S <= video.duration <= LONGEST_S else None
    off = abs(video.duration - expected)
    if off > TOLERANCE_S:
        return None
    return 0 if off <= SYNCED_S else 1 if off <= CLOSE_S else 2


def choose(song: _Song, videos: Sequence[Video], expected: float | None, *,
           skip: Iterable[str] = ()) -> Video | None:
    """The video of the song among a search's, or None when none fits.

    A video fits when its title is the song's title (a part of it, quoted in it, or what is
    left once the artist and words such as "official video" or 官方 are taken off; a title in
    Chinese, Japanese or Korean also as a word of its own among others, never as the start
    of a longer one), the artist is its channel or named in its title (names in two scripts
    meet, by ``normalize.name_forms``), its length is within 20 s of ``expected`` (LRCLIB's
    or the song's own; with none, from 45 s to 15 min), and it is no stream, short or
    ``skip``ped.

    Of those, a cover, live, karaoke, lesson, slowed or remixed version loses to any other
    (and a song that is itself live or acoustic prefers its own version); then a title that
    is exactly the song's beats one that only stands among other words; then the closest
    length (within 2 s the synced lyrics fit); then the artist's Topic channel, official
    audio, the artist's own channel or an official video; then the search's order.
    """
    names = _Names(song)
    skipped = set(skip)
    ranked = []
    for rank, video in enumerate(videos):
        if video.id in skipped or video.live or video.short:
            continue
        close = _closeness(video, expected)
        title = names.title_in(video.title) if close is not None else 0
        if not title:
            continue
        if not (names.channel_is_artist(video.channel) or names.artist_in(video.title)):
            continue
        tier = 1 if names.unwanted(video.title, video.channel) else 0
        if names.variant and not re.search(rf"\b{names.variant}\b|unplugged", fold(video.title)):
            tier = max(tier, 1)
        ranked.append(((tier, -title, close, -_official(names, video), rank), video))
    return min(ranked, key=lambda r: r[0])[1] if ranked else None


# --- running yt-dlp -----------------------------------------------------------------------------------

# What every run is given: no config file, plugin, cookie or remote code; no retry; paced requests.
_BASE_ARGS = (
    "--ignore-config", "--no-plugin-dirs", "--no-cookies", "--no-cookies-from-browser",
    "--no-remote-components", "--no-playlist", "--no-progress", "--socket-timeout", "30",
    "--retries", "0", "--extractor-retries", "0", "--fragment-retries", "0", "--sleep-requests", "2",
)
_DOWNLOAD_ARGS = (
    "--sleep-interval", "10", "--max-sleep-interval", "20", "-f", "bestaudio[ext=m4a]/bestaudio/best",
    "-x", "--audio-format", AUDIO_FORMAT, "--max-filesize", MAX_FILESIZE, "--no-mtime",
    "--print", "after_move:%(.{id,title,channel,uploader,duration,filepath})j",
)
# A block: YouTube's bot check, a refusal, a rate limit or a captcha.
_BLOCKED = re.compile(r"not a bot|HTTP Error 4(?:03|29)|Too Many Requests|rate[- ]limited|try again later|captcha",
                      re.IGNORECASE)
# A video that can't be had without logging in, or at all.
_UNAVAILABLE = re.compile(
    r"Video unavailable|Private video|confirm your age|age[- ]restricted|available in your country"
    r"|members[- ]only|has been removed|has been terminated|copyright|live event will begin|Premieres in"
    r"|DRM protected|This video is (?:un|not )available",
    re.IGNORECASE,
)
_STATUS = re.compile(r"HTTP Error (\d{3})")
REASON_CHARS = 300


class VideoUnavailable(ProviderError):
    """YouTube answered that the video can't be had without logging in, or at all: removed,
    private, age-restricted, members-only, not in this country. No block, and no miss."""


@dataclass(frozen=True)
class Download:
    path: Path
    video: Video


def _reason(stderr: str) -> str:
    """yt-dlp's reason, one line: its last error, else its last word."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    errors = [line.removeprefix("ERROR:").strip() for line in lines if line.startswith("ERROR:")]
    text = (errors or lines or ["yt-dlp failed and said nothing"])[-1]
    return text if len(text) <= REASON_CHARS else text[: REASON_CHARS - 1] + "…"


class YtDlp:
    """yt-dlp for one run: budgeted, paced, one run at a time, stopping at the first block.

    ``requests_made`` counts yt-dlp runs, which is what the budget counts; ``policy`` is the
    provider's, for the run's summary. Every run is an ``Event`` for ``on_event``: ``ok``
    (a video unavailable is an answer too), ``error`` or ``blocked``, and ``budget`` once
    the budget stops one. ``on_close`` is called once, at ``close``: caracole's lock goes.
    """

    def __init__(
        self,
        binary: str,
        policy: ProviderPolicy,
        cache_dir: Path,
        *,
        on_event: Callable[[Event], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: Any = None,
        timeouts: tuple[float, float] = (SEARCH_TIMEOUT, DOWNLOAD_TIMEOUT),
        on_close: Callable[[], None] | None = None,
    ):
        self.provider = PROVIDER
        self.binary = binary
        self.policy = policy
        self.cache_dir = cache_dir / "yt-dlp"  # the player's code and signatures, between runs
        self.requests_made = 0
        self._on_event = on_event
        self._sleep = sleep
        self._clock = clock
        self._rng = rng or random.Random()
        self._timeouts = timeouts
        self._on_close = on_close
        self._last: float | None = None
        self._blocked: ProviderBlocked | None = None
        self._budget_reported = False

    def search(self, query: str, n: int = SEARCH_RESULTS) -> list[Video]:
        target = f"ytsearch{n}:{query}"
        out = self._run(["--flat-playlist", "--dump-single-json"], target, "search", self._timeouts[0])
        return parse_search(out)

    def download(self, video_id: str, into: Path) -> Download:
        """The video's audio, in ``into`` as ``audio.<ext>``, and the video as yt-dlp reported it."""
        if not _VIDEO_ID.fullmatch(video_id):
            raise ValueError(f"not a YouTube video id: {video_id!r}")
        url = watch_url(video_id)
        out = self._run([*_DOWNLOAD_ARGS, "-o", str(into / "audio.%(ext)s")], url, "download", self._timeouts[1])
        info: dict[str, Any] = {}
        for line in reversed(out.splitlines()):
            try:
                found = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if isinstance(found, dict) and found.get("filepath"):
                info = found
                break
        path = Path(str(info.get("filepath") or ""))
        if not _audio_in(path, into):
            raise ProviderError(PROVIDER, url, None, f"yt-dlp left no audio file in {into.name}")
        duration = _number(info.get("duration"))
        video = Video(video_id, str(info.get("title") or ""), str(info.get("channel") or info.get("uploader") or ""),
                      duration)
        return Download(path, video)

    def close(self) -> None:
        on_close, self._on_close = self._on_close, None
        if on_close is not None:
            on_close()

    def __enter__(self) -> YtDlp:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- one run --------------------------------------------------------------------------

    def _run(self, args: list[str], target: str, what: str, timeout: float) -> str:
        if self._blocked is not None:
            raise ProviderBlocked(PROVIDER, target, self._blocked.status, "blocked earlier this run")
        if self.requests_made >= self.policy.budget:
            if not self._budget_reported:
                self._budget_reported = True
                self._event(target, None, "budget", f"budget of {self.policy.budget} yt-dlp runs spent")
            raise BudgetExhausted(PROVIDER)
        self._pause()
        argv = [self.binary, *_BASE_ARGS, "--cache-dir", str(self.cache_dir), *args, "--", target]
        env = ytdlp_env(os.environ)
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    env=env, start_new_session=True)
        except OSError as e:  # no yt-dlp there: nothing was sent
            raise ProviderError(PROVIDER, target, None, f"can't run yt-dlp ({self.binary}): {e.strerror or e}") from e
        try:
            self.requests_made += 1
            self._last = self._clock()
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _stop(proc)
            self._last = self._clock()
            message = f"yt-dlp took longer than {timeout:g} s and was stopped"
            self._log(what, target, "timed out")
            self._event(target, None, "error", message)
            raise ProviderError(PROVIDER, target, None, message) from TimeoutError(message)
        except BaseException:  # Ctrl-C, a stop: its own session hears neither, so it goes with caracole
            _stop(proc)
            raise
        self._last = self._clock()
        stdout, stderr = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
        if proc.returncode == 0:
            self._log(what, target, "ok")
            self._event(target, None, "ok", None)
            return stdout
        reason = _reason(stderr)
        status_m = _STATUS.search(stderr)
        status = int(status_m.group(1)) if status_m else None
        self._log(what, target, reason)
        if _BLOCKED.search(stderr):
            self._blocked = ProviderBlocked(PROVIDER, target, status if status in (403, 429) else None, reason)
            self._event(target, status, "blocked", reason)
            raise self._blocked
        if _UNAVAILABLE.search(stderr):
            self._event(target, status, "ok", f"video unavailable: {reason}")
            raise VideoUnavailable(PROVIDER, target, status, reason)
        self._event(target, status, "error", reason)
        raise ProviderError(PROVIDER, target, status, reason)

    def _pause(self) -> None:
        if self._last is None:
            return
        remaining = self._rng.uniform(*self.policy.delay) - (self._clock() - self._last)
        if remaining > 0:
            self._sleep(remaining)

    def _log(self, what: str, target: str, answer: str) -> None:
        if log.isEnabledFor(logging.INFO):
            log.info("%s", request_line(PROVIDER, what, target, answer, used=self.requests_made,
                                        budget=self.policy.budget))

    def _event(self, target: str, status: int | None, decision: str, message: str | None) -> None:
        if self._on_event is not None:
            self._on_event(Event(provider=PROVIDER, url=target, status=status, decision=decision, message=message))


# What yt-dlp, and the deno and ffmpeg it starts, are given of caracole's environment: where
# programs and home are, the language, temporary and cache folders, proxies, certificates, and
# deno's flags. Nothing else: not the unit's credentials (CREDENTIALS_DIRECTORY) nor caracole's
# tokens (CARACOLE_*), for these are other people's programs reading YouTube's pages.
_KEPT_ENV = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LANGUAGE", "LOCALE_ARCHIVE", "TZ", "TZDIR", "TMPDIR", "TEMP", "TMP",
    "XDG_CACHE_HOME",
    "XDG_RUNTIME_DIR", "SSL_CERT_FILE", "SSL_CERT_DIR", "NIX_SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    "DENO_V8_FLAGS", "DENO_DIR", "DENO_NO_UPDATE_CHECK", "DENO_CERT", "DENO_TLS_CA_STORE",
})
_PROXY_ENV = frozenset({"http_proxy", "https_proxy", "all_proxy", "no_proxy"})


def ytdlp_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The environment yt-dlp runs in (``_KEPT_ENV``, ``LC_*`` and the proxy variables), with
    ``DENO_V8_FLAGS=--jitless`` unless it says otherwise."""
    env = {k: v for k, v in environ.items()
           if k in _KEPT_ENV or k.startswith("LC_") or k.lower() in _PROXY_ENV}
    env.setdefault("DENO_V8_FLAGS", "--jitless")
    return env


def _stop(proc: subprocess.Popen) -> None:
    """Stop a run and what it started (ffmpeg, deno), then reap it."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        proc.kill()
    proc.communicate()


def _audio_in(path: Path, folder: Path) -> bool:
    """Whether ``path`` is an audio file of some size right inside ``folder``, and no link."""
    try:
        if path.parent.resolve() != folder.resolve() or path.is_symlink() or not path.is_file():
            return False
        return path.suffix.lower() in AUDIO_SUFFIXES and path.stat().st_size > 0
    except OSError:
        return False
