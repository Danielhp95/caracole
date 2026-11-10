"""The computer of the phone's end-to-end scenario (the Android plan's §9: tests/test_android_e2e.py on the JVM, and the
device tests of the integration step): a library of 20 songs, built with no request, and caracole serve over it::

    from helpers.e2e_library import build, free_port

    computer = build(tmp_path / "e2e")   # DIR/computer/: its caracole.toml, database and folders; DIR/scenario.json
    computer.export_index()              # caracole index export DIR/index.sqlite
    with computer.serving(free_port()) as url:   # caracole serve on 127.0.0.1, a process of its own
        ...
    computer.units()                     # peer_sync.library_state of it now: {unit id: (label, digest)}

It is built as docs/screenshots/make.py builds its demo, with caracole's own functions and the suite's helpers, the
way the nightly run leaves a library: wanted.txt synced (an album and a length on some lines), each song's chart kept
as ug/fetch.py's ``_keep_text`` keeps a fetched UG sheet (``sheet.txt`` and ``sheet.json``, two kept files of its
version) and the song matched, Ultimate Guitar's index read from a sitemap written here (as ``caracole index build
--from`` reads one: the library's songs and ``INDEX``'s), a letter of LaCuerda's listing and an artist page's songs
(``lacuerda_index.store_*``, with the listing's record), gtptabs.com's rows stored as site_index.py stores a sitemap
it read (its record, and the index read whole), a Guitar Pro file kept as gtptabs.com's download is
(tests/fixtures/guitar/synthetic.gp), lyrics recorded as the lyrics step records LRCLIB's (``lyrics.txt`` written, the
song's ``lyrics_json``), a songbook with a setting, every sheet and the songbook rendered by the real chordpro, and the
pages written. With it the goal's changes (docs/android_port.md): ``[version]`` and ``[transpose]`` on five songs
(``CHANGED``), and two songs whose sheet the owner chose among their two UG versions, ``[pin]`` (``CHOSEN``).

The songs are traditional or long out of copyright (one Chinese, one artist's name accented), and their charts are
made up here, chords over words that are no song's. The Chinese song's chart sings made-up Chinese words (``CHINESE``,
in Simplified characters), so that its page carries the readings Pinyin shows (the data's ``pinyin``) and its words
in either script (``hanzi``), as a sheet whose words hold no Chinese never does whatever its title: the sheet the
device's pinches try with Pinyin on. One song keeps a harmonica tab as harptabs.com's is kept (``HARMONICA``: its
``harmonica-1.txt``, made up, and the page render.py writes beside it, ``harmonica-1.html``).

``Computer.phone_pages(keys, into)`` is the phone's reference for its songs' pages (milestone 5's check): render.py's
page path with no PDF (tests/helpers/phone_render.py) run on a copy of the computer in ``into``, so that the pages
the phone made of its own lookups are compared, byte for byte, with what Python writes for the same inputs once the
computer has taken them.

``scenario.json`` tells the Kotlin phases (android/e2e's PhoneScenarioTest) which songs the scenario does what with:
``songs`` (the 20: artist, title, identity key), ``changed`` (the keys of each overrides.toml table the goal's changes
fill: what the phone's ``phone_overrides`` holds once it took them), ``index`` (a song of UG's index the library hasn't
got, the query that finds it, and its names and identity key as search.py's ``search_index`` gives them),
``index_tables`` (the tables ``caracole index export`` writes, index_transfer.py's ``SITES``), ``requests`` (the songs
the phone asks for by name, ``fetch`` 1 and 0), ``removed`` (R and C1, which the phone removes), ``transposed`` (C1
and C2, whose ``[transpose]`` the computer changes while the phone is away) and ``adds`` (the songs the computer adds
meanwhile, ``after_the_phone_left``).

``python -m tests.helpers.e2e_library serve DIR PORT`` (in nix develop, from the repository's root) builds the library
in DIR when DIR holds none, exports its index to DIR/index.sqlite (what ``GET /api/peer/index`` gives the phone, and
the app's own import reads), and runs caracole serve on 0.0.0.0:PORT until it is stopped, so that an emulator reaches
it at http://10.0.2.2:PORT (the plan's device step). ``--address`` listens elsewhere.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
TESTS = REPO / "tests"

NOW = datetime(2026, 10, 22, 3, 0, tzinfo=UTC)
FETCHED = "2026-10-22T03:00:00Z"
NAME = "Computer"  # caracole.toml's name: what the pages, and the phone's Sync tab, call this library
LABEL = "E2E"  # caracole serve --label: the badge on its pages
FIRST_TAB = 5000001  # the made-up tab id of the first song's sheet, and so on
SECOND_TAB = 100  # a chosen song's second version: its first's tab id and this
INDEX_TAB = 5000501  # the first of INDEX's

# (artist, title, the chart's key, its chords): the library, in the order wanted.txt lists it.
SONGS = (
    ("Traditional", "Scarborough Fair", "Am", ("Am", "G", "C", "D")),
    ("Traditional", "Greensleeves", "Am", ("Am", "C", "G", "E")),
    ("Traditional", "Shenandoah", "D", ("D", "G", "Bm", "A")),
    ("Traditional", "茉莉花", "G", ("G", "C", "Em", "D")),
    ("John Newton", "Amazing Grace", "G", ("G", "C", "Em", "D")),
    ("Frederic Weatherly", "Danny Boy", "C", ("C", "F", "Am", "G7")),
    ("Stephen Foster", "Hard Times Come Again No More", "D", ("D", "G", "A", "Bm")),
    ("Robert Burns", "Auld Lang Syne", "G", ("G", "D", "C", "Em")),
    ("Stephen Foster", "Oh! Susanna", "C", ("C", "G", "F", "G7")),
    ("Stephen Foster", "Beautiful Dreamer", "D", ("D", "Bm", "G", "A")),
    ("Traditional", "The Water Is Wide", "G", ("G", "C", "Am", "D")),
    ("Traditional", "Wayfaring Stranger", "Em", ("Em", "Am", "B7", "C")),
    ("Traditional", "The Parting Glass", "G", ("G", "Em", "C", "D")),
    ("Traditional", "Molly Malone", "C", ("C", "Am", "Dm", "G")),
    ("Traditional", "The Skye Boat Song", "G", ("G", "Em", "C", "D")),
    ("Robert Burns", "A Red, Red Rose", "C", ("C", "F", "G", "Am")),
    ("Traditional", "Wild Mountain Thyme", "D", ("D", "G", "Em", "A")),
    ("Traditional", "Barbara Allen", "G", ("G", "C", "D", "Em")),
    ("Quirino Mendoza y Cortés", "Cielito Lindo", "C", ("C", "G7", "F", "Dm")),
    ("Traditional", "She Moved Through the Fair", "Em", ("Em", "D", "G", "Am")),
)

# What some lines of wanted.txt say besides the names: (album, length in ms).
LINES = {
    ("Traditional", "Scarborough Fair"): ("Folk Songs of England", 190_000),
    ("John Newton", "Amazing Grace"): ("Olney Hymns", None),
    ("Traditional", "茉莉花"): (None, 151_000),
}

# The goal's changes: each song's [version], as Make this my version writes one, and its [transpose].
CHANGED = {
    ("Traditional", "Scarborough Fair"): ("key=Bm&capo=0", 2),
    ("Traditional", "Shenandoah"): ("key=E&capo=2", -1),
    ("John Newton", "Amazing Grace"): ("key=F&capo=0", -2),
    ("Frederic Weatherly", "Danny Boy"): ("key=Bb&capo=0", 3),
    ("Robert Burns", "Auld Lang Syne"): ("key=A&capo=0", 1),
}
# The songs whose sheet the owner chose: their second UG version, pinned.
CHOSEN = (("Traditional", "Greensleeves"), ("Traditional", "Molly Malone"))
# The Chinese song, whose chart sings made-up Chinese words: its page carries pinyin, and either script.
CHINESE = ("Traditional", "茉莉花")
# A harmonica tab, made up, kept as harptabs.com's is (harptabs_fetch.py): its key and harp chips, as its page names
# them, and its page's id.
HARMONICA = ("Stephen Foster", "Oh! Susanna")
HARMONICA_TAB = (6001, "C", "Diatonic")
# Lyrics as LRCLIB gives them, made up.
LYRICS = (("Traditional", "Wayfaring Stranger"), ("Stephen Foster", "Beautiful Dreamer"),
          ("Traditional", "Wild Mountain Thyme"))
GUITAR = ("Traditional", "Greensleeves")  # its Guitar Pro file, gtptabs.com's
SONGBOOK = "Campfire"
SET_LIST = ("Traditional - Greensleeves", "John Newton - Amazing Grace", "Traditional - Shenandoah",
            "Frederic Weatherly - Danny Boy", "Traditional - 茉莉花")

# The rest of Ultimate Guitar's index, as its sitemaps list chords: what a search finds beside the library's songs.
INDEX = (
    ("stephen-foster", "camptown-races"), ("stephen-foster", "jeanie-with-the-light-brown-hair"),
    ("stephen-foster", "my-old-kentucky-home"), ("stephen-foster", "old-folks-at-home"),
    ("traditional", "black-is-the-color"), ("traditional", "down-in-the-valley"),
    ("traditional", "red-river-valley"), ("traditional", "home-on-the-range"),
    ("joseph-brackett", "simple-gifts"), ("traditional", "the-house-carpenter"),
)
# gtptabs.com's pages, as its sitemaps list them: songs, and an artist's page.
GTPTABS = (
    "https://gtptabs.com/tabs/20/traditional/greensleeves.html",
    "https://gtptabs.com/tabs/20/traditional/greensleeves-2.html",
    "https://gtptabs.com/tabs/20/traditional/scarborough-fair.html",
    "https://gtptabs.com/tabs/20/traditional.html",
    "https://gtptabs.com/tabs/19/stephen-foster/oh-susanna.html",
    "https://gtptabs.com/tabs/19/stephen-foster/camptown-races.html",
)
# A letter of LaCuerda's listing, and an artist page's songs: (slug, title, versions' types).
LACUERDA_PAGE = "tabs/q/index0.html"
LACUERDA_ARTISTS = (("quirino_mendoza_y_cortes", "Quirino Mendoza y Cortés", 2), ("quilapayun", "Quilapayún", 41))
LACUERDA_SONGS = (("cielito_lindo", "Cielito Lindo", "RT"), ("la_cucaracha", "La Cucaracha", "R"))

# What the scenario does with which song (scenario.json, for the Kotlin phases).
INDEX_SONG = ("stephen-foster", "jeanie-with-the-light-brown-hair", "jeanie light brown")  # Get it on its row
REQUESTS = (("Traditional", "Black Is the Color", "1"), ("Traditional", "Down in the Valley", "0"))  # /request, fetch
REMOVED = {"R": ("Traditional", "Barbara Allen"), "C1": ("Traditional", "The Parting Glass")}  # on the phone
TRANSPOSED = {"C1": (("Traditional", "The Parting Glass"), 4), "C2": (("Traditional", "The Water Is Wide"), -3)}
ADDS = (("Traditional", "Red River Valley"), ("Traditional", "Home on the Range"), ("Joseph Brackett", "Simple Gifts"))


def slug(name: str) -> str:
    """A name as Ultimate Guitar's addresses write it: "Quirino Mendoza y Cortés" is quirino-mendoza-y-cortes."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def tab_url(artist: str, title: str, tab: int) -> str:
    return f"https://tabs.ultimate-guitar.com/tab/{slug(artist)}/{slug(title)}-chords-{tab}"


def chart(title: str, chords: Sequence[str], version: int = 1) -> str:
    """A chart in Ultimate Guitar's markup: two verses and a chorus, each line's two chords over its made-up words
    (``words``)."""
    lines = []
    for section in ("Verse 1", "Chorus", "Verse 2"):
        lines.append(f"[{section}]")
        for n in range(4):
            first, second = chords[n % len(chords)], chords[(n + 1) % len(chords)]
            lines.append(f"[tab][ch]{first}[/ch]" + " " * (16 - len(first)) + f"[ch]{second}[/ch]")
            lines.append(words(title, section, n, version) + "[/tab]")
    lines.insert(0, f"{title}: a chart made up for caracole's tests")
    return "\r\n".join(lines) + "\r\n"


# The Chinese chart's parts and its lines' numbers, as its made-up words name them.
CHINESE_PARTS = {"Verse 1": "第一段", "Chorus": "副歌", "Verse 2": "第二段"}
CHINESE_NUMBERS = "一二三四"


def words(title: str, section: str, n: int, version: int = 1) -> str:
    """The made-up words of line ``n`` of a chart's ``section``: for the Chinese song (``CHINESE``), Chinese in
    Simplified characters, most of which Traditional writes otherwise (这 這, 为 為, 测试 測試, 编 編, 词 詞), so that
    the viewer's Chinese characters change the words shown, each with its reading."""
    if title == CHINESE[1]:
        return f"这是为测试编的歌词，{CHINESE_PARTS[section]}第{CHINESE_NUMBERS[n]}行"
    return f"Words of {section.lower()} for the test, line {n + 1}, take {version}"


def harmonica_tab(title: str) -> str:
    """A harmonica tab in harptabs.com's way, made up: a title line, then rows of holes for a C harp, each hole over
    a word of the made-up words under it, blown (``4``) or drawn (``-4``)."""
    rows = (("4", "4", "5", "6", "6", "-6", "6", "5"), ("4", "-4", "5", "5", "-4", "4", "-4", "4"),
            ("4", "4", "5", "6", "6", "-6", "6", "5"), ("4", "-4", "5", "5", "-4", "-4", "4", "4"))
    out = [f"{title}: a harmonica tab made up for caracole's tests", ""]
    for n, holes in zip(("one", "two", "three", "four"), rows):
        lyric = f"made up words of row {n} for harp"
        starts = [i for i, ch in enumerate(lyric) if ch != " " and (i == 0 or lyric[i - 1] == " ")]
        line = [" "] * (len(lyric) + 4)
        for at, hole in zip(starts, holes):
            line[at:at + len(hole)] = hole
        out += ["".join(line).rstrip(), lyric, ""]
    return "\n".join(out)


# --- the computer ---------------------------------------------------------------------------------------------------


def free_port() -> int:
    """A port nothing listens on now, of 127.0.0.1."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Computer:
    """The library built in ``dir`` (``dir/computer/``), and caracole's commands run on it, each a process of its own
    as the owner runs them: ``caracole --config dir/computer/caracole.toml …``."""

    def __init__(self, dir: Path):
        self.dir = Path(dir).resolve()
        self.root = self.dir / "computer"
        self.config = self.root / "caracole.toml"
        self.index = self.dir / "index.sqlite"
        self.logs = self.dir / "logs"

    def cfg(self):
        from caracole.config import load_config

        return load_config(self.config, env=self.env())

    def scenario(self) -> dict:
        return json.loads((self.dir / "scenario.json").read_text(encoding="utf-8"))

    def env(self) -> dict[str, str]:
        """The environment of its commands: the dev shell's (chordpro, the fonts), a home of its own, no service of
        the machine's (service.py) and no yt-dlp, the checkout's src/ first on PYTHONPATH."""
        env = dict(os.environ)
        env.update({
            "HOME": str(self.root / "home"),
            "CARACOLE_SERVICE_FILE": str(self.root / "no-caracole-service"),
            "CARACOLE_YTDLP_BIN": str(self.root / "no-yt-dlp"),
            "PYTHONPATH": os.pathsep.join(p for p in (str(SRC), os.environ.get("PYTHONPATH")) if p),
        })
        env.pop("CARACOLE_CONFIG", None)
        return env

    def command(self, *args: str) -> list[str]:
        return [sys.executable, "-m", "caracole", "--config", str(self.config), *args]

    def caracole(self, *args: str, timeout: float = 300) -> str:
        """``caracole ARGS`` on this library, which must succeed; what it printed."""
        done = subprocess.run(self.command(*args), env=self.env(), cwd=self.root, capture_output=True, text=True,
                              check=False,
                              timeout=timeout)
        if done.returncode != 0:
            raise RuntimeError(f"caracole {' '.join(args)} exited {done.returncode}:\n{done.stdout}\n{done.stderr}")
        return done.stdout

    def export_index(self) -> Path:
        """``caracole index export DIR/index.sqlite``, in place of the one there."""
        self.index.unlink(missing_ok=True)
        self.caracole("index", "export", str(self.index))
        return self.index

    @contextmanager
    def serving(self, port: int, address: str = "127.0.0.1", *, timeout: float = 120) -> Iterator[str]:
        """``caracole serve --address ADDRESS --port PORT`` while the block runs, answering once it does; its address
        on 127.0.0.1. It stops as Ctrl-C stops it, and its output is in DIR/logs/."""
        self.logs.mkdir(parents=True, exist_ok=True)
        log = self.logs / f"serve-{time.strftime('%H%M%S')}-{port}.log"
        with log.open("ab") as out:
            server = subprocess.Popen(self.command("serve", "--address", address, "--port", str(port),
                                                   "--label", LABEL),
                                      env=self.env(), cwd=self.root, stdout=out, stderr=subprocess.STDOUT)
        url = f"http://127.0.0.1:{port}"
        try:
            wait_until_answering(url, server, log, timeout)
            yield url
        finally:
            stop(server)

    def units(self) -> dict[str, tuple[str, str]]:
        """``peer_sync.library_state`` of the library now, as caracole serve's ``/api/peer/state`` reads it: each
        unit's label and digest, by its id."""
        from caracole import db
        from caracole import peer_sync as sync
        from caracole.overrides import Overrides, load_overrides
        from caracole.songbook import load_songbooks, songbooks_file

        cfg = self.cfg()
        overrides = load_overrides(cfg.overrides_file) if cfg.overrides_file.exists() else Overrides()
        books = load_songbooks(songbooks_file(cfg.library_dir))
        conn = db.connect(cfg.db_path)
        try:
            return {u.id: (u.label, u.digest) for u in sync.library_state(conn, overrides, books).values()}
        finally:
            conn.close()

    def songs(self) -> dict[str, str]:
        """The library's songs: "Artist - Title" by identity key."""
        from caracole import db
        from caracole.songs import list_songs

        conn = db.connect(self.cfg().db_path)
        try:
            return {s.key: f"{s.artist} - {s.title}" for s in list_songs(conn)}
        finally:
            conn.close()

    def phone_pages(self, keys: Collection[str], into: Path) -> dict[str, bytes]:
        """The pages the phone writes of the songs of identity keys ``keys``, as Python writes them for the same
        inputs: render.py's page path with no PDF (tests/helpers/phone_render.py's ``phone_render``, the phone's
        reference) over a copy of this computer made in ``into`` (``into/computer/``: its database copied whole, its
        library and overrides.toml, a caracole.toml naming the copy's folders), this computer untouched. Each file
        the pass recorded of those songs (kv ``render:files:<id>``: a viewer, a kept version's, a harmonica tab's
        page, the sheet's .cho) and each one's info.json, its bytes by its path in the library."""
        import shutil
        import sqlite3

        from caracole import db
        from caracole.library import song_dir
        from caracole.render import FILES_KEY
        from caracole.songs import find_song
        from helpers.phone_render import phone_render

        copy = Computer(into)
        if copy.root.exists():
            raise FileExistsError(f"{copy.root} is there already: the reference is made on a copy of its own")
        cfg = self.cfg()
        shutil.copytree(cfg.library_dir, copy.root / cfg.library_dir.relative_to(self.root), symlinks=True)
        (copy.root / "home").mkdir()
        copy.config.write_text(self.config.read_text(encoding="utf-8").replace(str(self.root), str(copy.root)),
                               encoding="utf-8")
        mine = copy.cfg()
        mine.db_path.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(cfg.db_path)
        try:  # the database whole, as one read sees it, whatever serve writes meanwhile
            source.execute("VACUUM INTO ?", (str(mine.db_path),))
        finally:
            source.close()
        conn = db.connect(mine.db_path)
        try:
            songs = []
            for key in keys:
                song = find_song(conn, key)
                if song is None:
                    raise LookupError(f"no song {key!r} in the computer's library")
                songs.append(song)
            done = phone_render(conn, mine, song_ids=[song.id for song in songs])
            if done.failed:
                raise RuntimeError(f"the phone's reference failed on {done.failed}")
            pages = {}
            for song in songs:
                folder = song_dir(mine.library_dir, song)
                names = sorted(db.kv_get_json(conn, f"{FILES_KEY}{song.id}", default={}) or {}) + ["info.json"]
                for name in names:
                    pages[(folder / name).relative_to(mine.library_dir).as_posix()] = (folder / name).read_bytes()
            conn.commit()
            return pages
        finally:
            conn.close()

    def after_the_phone_left(self) -> None:
        """What the owner does on the computer while the phone is away (§9's step 5): ``caracole add`` adds ``ADDS``,
        and C1's and C2's ``[transpose]`` change (overrides.toml's writer, ``put_song_entries``, keeping their other
        entries), their sheets rendered again in the new key (``caracole render --song``)."""
        from caracole.overrides import load_overrides, override_key, put_song_entries, song_entries

        for artist, title in ADDS:
            self.caracole("add", f"{artist} - {title}")
        cfg = self.cfg()
        for (artist, title), semitones in TRANSPOSED.values():
            display = f"{artist} - {title}"
            entries = song_entries(load_overrides(cfg.overrides_file), override_key(display))
            put_song_entries(cfg.overrides_file, display, {**entries, "transpose": semitones})
            self.caracole("render", "--song", display)


def wait_until_answering(url: str, server: subprocess.Popen, log: Path, timeout: float) -> None:
    """Until ``url``'s ``/api/peer/state`` answers 200; RuntimeError, with what the server said, when it exits first or
    the time runs out. Asked straight, never through a proxy the environment names."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if server.poll() is not None:
            raise RuntimeError(f"caracole serve exited {server.returncode}:\n{log.read_text(errors='replace')}")
        try:
            with opener.open(url + "/api/peer/state", timeout=30) as answer:
                if answer.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.2)
    stop(server)
    raise RuntimeError(f"caracole serve didn't answer at {url} in {timeout:.0f} s:\n{log.read_text(errors='replace')}")


def stop(server: subprocess.Popen) -> None:
    """The server stopped as Ctrl-C stops it, killed if it hasn't within 30 s."""
    if server.poll() is None:
        server.send_signal(signal.SIGINT)
        try:
            server.wait(30)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


# --- building it ----------------------------------------------------------------------------------------------------


def write_config(computer: Computer) -> None:
    root = computer.root
    root.mkdir(parents=True)
    (root / "home").mkdir()
    computer.config.write_text(
        f"name = {json.dumps(NAME)}\n"
        f"library_dir = {json.dumps(str(root / 'library'))}\nmusic_dir = {json.dumps(str(root / 'music'))}\n"
        f"state_dir = {json.dumps(str(root / 'state'))}\ncache_dir = {json.dumps(str(root / 'cache'))}\n",
        encoding="utf-8")


def build(dir: Path) -> Computer:
    """The computer's library in ``dir/computer/`` (a folder that must not exist yet), the goal's changes made, and
    ``dir/scenario.json``; no request is sent, and chordpro (on PATH, as in the dev shell) renders every sheet."""
    if str(TESTS) not in sys.path:  # the suite's helpers, when run as python -m tests.helpers.e2e_library
        sys.path.insert(0, str(TESTS))
    from caracole import db, gtptabs_fetch, site_index
    from caracole import lacuerda_index as li
    from caracole.gtptabs import parse_page_url
    from caracole.lacuerda import LCArtist, LCSong
    from caracole.library import keep_file, song_dir, write_info
    from caracole.lyrics import Lyrics, write_lyrics
    from caracole.normalize import identity_key, ug_slug_key
    from caracole.overrides import add_pin, load_overrides, put_song_entries
    from caracole.render import render_all
    from caracole.songbook import make_songbook, render_songbooks, set_song_setting, songbooks_file
    from caracole.songs import find_song, get_song, refresh_status, update_song
    from caracole.todo import write_pages
    from caracole.ug.index import build_index
    from caracole.ug.page import strip_markup
    from caracole.versions import upsert_version
    from caracole.viewer.version import Setting
    from caracole.wanted import append_wanted, sync_wanted
    from helpers.guitar import SYNTHETIC, keep_guitar
    from helpers.ug_pages import version_dict

    computer = Computer(dir)
    write_config(computer)
    cfg = computer.cfg()
    cfg.library_dir.mkdir(parents=True)
    for artist, title, _, _ in SONGS:
        album, duration_ms = LINES.get((artist, title), (None, None))
        append_wanted(cfg.wanted_file, artist, title, album, duration_ms)
    conn = db.connect(cfg.db_path)
    try:
        sync_wanted(conn, cfg.wanted_file, NOW)

        sitemap = []
        for n, (artist, title, key, chords) in enumerate(SONGS):
            song = find_song(conn, identity_key(artist, title))
            assert song is not None, f"{artist} - {title} wasn't added"
            tabs = [FIRST_TAB + n] + ([FIRST_TAB + n + SECOND_TAB] if (artist, title) in CHOSEN else [])
            kept = None
            for version, tab in enumerate(tabs, 1):
                rating, votes = (4.8, 120) if version == 1 else (4.1, 30)
                raw = version_dict(tab, song=title, artist=artist, version=version, rating=rating, votes=votes,
                                   tonality_name=key, tab_url=tab_url(artist, title, tab))
                kept = (upsert_version(conn, provider="ug", tab_id=str(tab), song_id=song.id, slot="sheet",
                                       kind="chords", rating=rating, votes=votes, version=version, label=None,
                                       url=raw["tab_url"], raw=raw, now=FETCHED), raw, version)
            vid, raw, version = kept  # the chosen song's second version: the sheet it keeps
            content = chart(title, chords, version)
            # As ug/fetch.py's _keep_text keeps a page's sheet: its text, and its version's JSON, both kept files.
            keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt",
                      data=strip_markup(content).encode("utf-8"), rank=1)
            doc = {"version": raw, "content": content, "url": raw["tab_url"], "meta": {}}
            keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.json",
                      data=(json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), rank=1)
            if title.isascii():  # as the match and fetch steps leave a song they found
                sitemap += [(slug(artist), slug(title), tab) for tab in tabs]
                update_song(conn, song.id, match_decision="accept", match_step="exact", match_score=100.0,
                            match_artist_key=ug_slug_key(slug(artist)), match_song_key=ug_slug_key(slug(title)),
                            matched_at=FETCHED, ug_dirty=False, ug_checked_at=FETCHED)
            if (artist, title) in LYRICS:
                words = Lyrics(plain=f"Made-up words of {title}\nfor caracole's tests\n", synced=None,
                               instrumental=False, duration=None, lrclib_id=900 + n)
                write_lyrics(song_dir(cfg.library_dir, song), words)  # as the lyrics step's _record stores them
                update_song(conn, song.id, lyrics_status="found", lyrics_json=words.to_json(), lyrics_at=FETCHED)
            refresh_status(conn, song.id, ignored=False)
            write_info(conn, cfg.library_dir, get_song(conn, song.id))
        sitemap += [(a, s, INDEX_TAB + n) for n, (a, s) in enumerate(INDEX)]

        sitemaps = computer.root / "sitemaps"
        sitemaps.mkdir()
        urls = "".join(f"<url><loc>https://tabs.ultimate-guitar.com/tab/{a}/{s}-chords-{tab}</loc></url>\n"
                       for a, s, tab in sitemap)
        (sitemaps / "sitemap1.xml").write_text(
            f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{urls}</urlset>\n", encoding="utf-8")
        build_index(conn, None, NOW, from_dir=sitemaps)
        # gtptabs.com's sitemapGoogle1.xml of these pages, stored as site_index.refresh stores a sitemap it read (its
        # rows and its record, which index_transfer's merge compares), and its index read whole.
        site_index._store(conn, gtptabs_fetch.SITE, "1", [parse_page_url(u) for u in GTPTABS],
                          {"etag": None, "last_modified": None}, NOW)
        db.kv_set(conn, gtptabs_fetch.SITE.complete_key, FETCHED)
        li.store_artists(conn, LACUERDA_PAGE, [LCArtist(s, name, n) for s, name, n in LACUERDA_ARTISTS])
        slug_of, name = LACUERDA_ARTISTS[0][:2]
        li.store_songs(conn, slug_of, name, [LCSong(s, t, types, tuple(range(1, len(types) + 1)))
                                             for s, t, types in LACUERDA_SONGS])
        db.kv_set_json(conn, li.PAGES_KEY, {LACUERDA_PAGE: {"checked_at": FETCHED, "etag": None,
                                                            "last_modified": None, "rows": len(LACUERDA_ARTISTS),
                                                            "pages": ["index0.html"],
                                                            "total": len(LACUERDA_ARTISTS)}})

        keep_guitar(conn, cfg, find_song(conn, identity_key(*GUITAR)), SYNTHETIC.read_bytes(), name="guitar-1.gp",
                    tab="7701")
        keep_harmonica(conn, cfg, find_song(conn, identity_key(*HARMONICA)))

        # The goal's changes, before the renders that play them.
        for (artist, title), (version, semitones) in CHANGED.items():
            put_song_entries(cfg.overrides_file, f"{artist} - {title}", {"version": version, "transpose": semitones})
        for artist, title in CHOSEN:
            n = next(i for i, s in enumerate(SONGS) if s[:2] == (artist, title))
            add_pin(cfg.overrides_file, f"{artist} - {title}", [tab_url(artist, title, FIRST_TAB + n + SECOND_TAB)])
        overrides = load_overrides(cfg.overrides_file)

        render = render_all(conn, cfg, overrides)
        if render.failed:
            raise RuntimeError(f"rendering failed: {render}")
        book = songbooks_file(cfg.library_dir)
        make_songbook(book, SONGBOOK, list(SET_LIST))
        set_song_setting(book, SONGBOOK, "John Newton - Amazing Grace", Setting(key="A", capo=0))
        books = render_songbooks(conn, cfg, overrides)
        if books.failed or books.error:
            raise RuntimeError(f"the songbook failed: {books}")
        write_pages(conn, cfg, overrides, NOW)
        conn.commit()
        found = index_song(conn)
    finally:
        conn.close()
    write_scenario(computer, found)
    return computer


def keep_harmonica(conn, cfg, song) -> None:
    """``HARMONICA``'s tab kept as harptabs_fetch.py's ``_keep`` keeps one: its version (provider harptabs, kind
    harmonica, the page's chips in its raw) and ``harmonica-1.txt``, which render.py gives its page."""
    from caracole.harptabs import PROVIDER, page_url
    from caracole.inbox import HARMONICA_KIND
    from caracole.library import keep_file
    from caracole.versions import upsert_version

    tab, key, harp = HARMONICA_TAB
    raw = {"title": song.title, "artist": song.artist, "key": key, "harp": harp, "difficulty": "Beginner",
           "views": 1200, "rating": 4.5}
    vid = upsert_version(conn, provider=PROVIDER, tab_id=str(tab), song_id=song.id, slot="guitar", kind=HARMONICA_KIND,
                         rating=4.5, votes=1200, version=1, label=None, url=page_url(f"tab/{tab}/{slug(song.title)}"),
                         raw=raw, now=FETCHED)
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="harmonica-1.txt",
              data=harmonica_tab(song.title).encode("utf-8"), rank=1)


def index_song(conn) -> dict:
    """``INDEX_SONG`` as search.py's ``search_index`` finds it by its query: its keys, its names, the identity key
    a song added under them has, and the query."""
    from caracole.normalize import identity_key
    from caracole.search import search_index

    artist_key, song_key, query = INDEX_SONG
    hit = next((h for h in search_index(conn, query) if (h.artist_key, h.song_key) == (artist_key, song_key)), None)
    assert hit is not None, f"search_index({query!r}) doesn't find {artist_key}/{song_key}"
    return {"artist_key": artist_key, "song_key": song_key, "query": query, "artist": hit.artist, "title": hit.title,
            "key": identity_key(hit.artist, hit.title)}


def write_scenario(computer: Computer, index: dict) -> None:
    """scenario.json: what the Kotlin phases need to know of the scenario's songs (this module's docstring), with
    ``index``, ``index_song``'s. Written last, so a folder that has it holds a library built whole."""
    from caracole.index_transfer import SITES
    from caracole.normalize import identity_key

    def named(artist: str, title: str, **more) -> dict:
        return {"artist": artist, "title": title, "key": identity_key(artist, title), **more}

    scenario = {
        "format": 1,
        "name": NAME,
        "songs": [named(a, t) for a, t, _, _ in SONGS],
        "changed": {
            "version": sorted(identity_key(*s) for s in CHANGED),
            "transpose": sorted(identity_key(*s) for s in CHANGED),
            "pin": sorted(identity_key(*s) for s in CHOSEN),
        },
        "songbook": SONGBOOK,
        "index": index,
        "index_tables": [table for site in SITES.values() for table in site.tables],
        "requests": [named(a, t, fetch=fetch) for a, t, fetch in REQUESTS],
        "removed": {name: named(*song) for name, song in REMOVED.items()},
        "transposed": {name: named(*song, transpose=n) for name, (song, n) in TRANSPOSED.items()},
        "adds": [named(a, t) for a, t in ADDS],
    }
    (computer.dir / "scenario.json").write_text(json.dumps(scenario, ensure_ascii=False, indent=1) + "\n",
                                                encoding="utf-8")


# --- python -m tests.helpers.e2e_library serve DIR PORT -------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tests.helpers.e2e_library",
                                     description="The end-to-end scenario's computer, served for the device tests.")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="build the library in DIR when it holds none, export its index to "
                                              "DIR/index.sqlite, and run caracole serve on PORT until stopped")
    serve.add_argument("dir", type=Path, metavar="DIR")
    serve.add_argument("port", type=int, metavar="PORT")
    serve.add_argument("--address", default="0.0.0.0", help="where caracole serve listens (0.0.0.0)")
    args = parser.parse_args(argv)

    computer = Computer(args.dir)
    if (computer.dir / "scenario.json").is_file():
        print(f"the library in {computer.root}, as built before", flush=True)
    elif computer.root.exists():
        sys.exit(f"{computer.root} holds a library whose build was cut short: remove it, and run this again")
    else:
        print(f"building the library in {computer.root}…", flush=True)
        build(computer.dir)
    print(f"the index: {computer.export_index()}", flush=True)
    print(f"caracole serve on {args.address}:{args.port} (an emulator reaches it at http://10.0.2.2:{args.port}; "
          "Ctrl-C stops it)", flush=True)
    command = computer.command("serve", "--address", args.address, "--port", str(args.port), "--label", LABEL)
    os.chdir(computer.root)
    os.execve(command[0], command, computer.env())


if __name__ == "__main__":
    main()
