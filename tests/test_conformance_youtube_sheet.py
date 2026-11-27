"""``caracole youtube --song --sheet`` for the phone: whole jobs recorded, for :server's ``YouTubeSheetRunner`` (the
phone-YouTube plan's Y2.3) to agree with, as test_conformance_audio_sheet.py records ``caracole audio`` (E21's record
shape, whose docstring this one follows and whose helpers it shares).

**Data** (``data/caracole/library/youtube_sheet.json``, ``youtube_sheet_json``): youtube_sheet.py's ``STAGES`` and
the words of its song and audio stages the phone says as the computer does, by their constants (``OWN_AUDIO``,
``DECLINED``, ``CANT_NOTE``, ``NOTED``, ``DOWNLOADING``, ``LOOKING``, ``AUDIO_ALREADY``, ``TURNED_BACK``,
``NO_RUNS_LEFT``, ``DOWNLOADED``, ``NO_VIDEO_FITS``, ``CANT_DOWNLOAD``, ``DOWNLOAD_FAILED``, ``COOLING_LATER``); the
rest of its words are audio_sheet.json's.

**Vectors** (``vectors/lookup/youtube_sheet.jsonl``), a header, then a record a line, each a scenario record
(helpers/scenario.py ``record_lookup``) of youtube_sheet.py's ``make_sheet`` over a world of
test_conformance_lookup_scenarios.py's (``World``: Calla Lake's River Road, the fake lyrics sites by address), yt-dlp
helpers/fake_ytdlp.py's ``FakeYtDlp`` (never a real one), the models E21's fake recognizer and beats, each with:

- ``kw``: ``own`` (the world's kv ``sync:id``), ``request`` (``artist``, ``title``, ``url``: SheetRequest's, the video
  pasted or null), ``providers`` (the world's policies over the defaults: YouTube's ``delay`` [0, 0], so that no
  random pause is drawn), ``heard`` (what the fake models heard, ``sheet.heard_record``, which the phone's fake
  ChordModels answers), ``hearing`` ("ok"), ``audio`` (``{format, duration}``, what the phone's examiner reads of the
  downloaded file), ``ytdlp`` (FakeYtDlp's plan: ``searches`` by query, each ``{entries}`` or ``{stderr, exit}``;
  ``videos`` by id, each ``{id, title, channel, uploader, duration, ext, base64, mtime}`` (the bytes it writes, and
  their time on the disk, so that the song's ``audio_mtime`` is the same on both sides) or ``{…, stderr, exit}``),
  ``cache`` (``{name: {base64, mtime}}``, the files of ``cache_dir/youtube/`` before the job), ``store`` (the files of
  ``state_dir/audio/`` before it, as E21's) and ``at_yield`` (null, or ``{"stage": "chords", "fixture": [records]}``:
  what another caracole wrote while the job let a waiting lookup go first, before that stage's models, fixture records
  as ``fixture`` holds them, which the replay writes at its yield there, and ``store``, the files of
  ``state_dir/audio/`` once it wrote, as ``store`` holds them);
- ``out.result``: ``{result, progress, python}`` as E21's (``phone_words``: the song stage of a song added
  ``get.ADDED``, vocals and words the phone's skip, the pdf ``get.NO_PDFS``, the pages ``get.LIBRARY_PAGE``; Python's
  own in ``python``);
- ``out.runs``: each yt-dlp run in order, ``{what, target}`` (``search``, ``video`` or ``download``, the target after
  ``--``) and a download's ``into`` (``<into>``: the folder it was given), as youtube/runs.jsonl's: the phone's argv
  is its own template's (youtube.json), never the computer's;
- ``out.youtube``: the files of ``cache_dir/youtube/`` after, each by its SHA-256; ``out.store``: ``state_dir/audio/``'s
  after (E21's ``store_after``);
- ``out.maker``: the auto sheet's maker members Python wrote, each side's own, out of the ``versions`` rows' raw;
- ``out.sent``: what the command's done line says it sent (commands/youtube.py ``sent_words``), its time aside;
- ``apart``: what the replay compares apart, by design: ``lyrics`` (get.py's words at the lookup pace on the phone),
  ``events_run`` and ``pauses`` (the bulk pace's against the lookup's), and ``kv`` the phone never writes
  (``autochords:status``, ``autochords:failed:``) or the computer doesn't (``http:last_request:youtube``: the
  phone's runner keeps its last run there, the computer's reads its events).

Every path under the world's state folder is written ``{state}``, under its cache folder ``{cache}``.

The cases: a video pasted (``--url``) for a song new to the library, its timed lyrics found and the chords over them;
a search's pick for a song of the library; a search none of whose videos fits; a pasted video with no m4a stream (a
pass-over: unusable); a searched one with none (passed over into ``skip``), then the same job again (the next pick
taken); an unavailable video; YouTube blocking the download (one run, the cooldown recorded, the chords skipped);
YouTube cooling down (nothing run); a song with an audio file of its own given (refused); a human sheet kept, and an
audio file of the owner's given, while the job let a lookup go first before the chords (refused there); and the same
job again once the video's audio is kept (nothing run, the sheet up to date), and that job on the phone's own state
instead, once its sheet was kept and the video's audio let go (``let_go``: Python's second run its answer, by the
controller's ruling of 2026-11-27); and the error ladder (youtube_fetch ``_count_failure``): an error of the network
(counted against nothing), one counted, and a third failure of a pasted and of a searched video (given up).

A pass-over is recorded as the phone reads it: the computer's runner reads "Requested format is not available" as an
error (its download asks ``bestaudio[ext=m4a]/bestaudio/best``, so it is the network's or the extractor's fault there)
and counts it against the video, where the phone's asks m4a alone (``youtube.PHONE_FORMAT``) and passes the video over
(``core.youtube.PassedOver``, a VideoUnavailable, its event an ``error`` with the reason, as the computer's). The record
runs the computer's job with that one reading swapped (``_passed_over``), and says so (``kw.reads`` "phone"). The swap
reads ``PHONE_PASS_OVER`` over the error's message, which is ``_reason``'s, the last ERROR line, where the phone's
``classify`` reads it over that line and passes a degraded WARNING to "outdated": the same reading for a run with no
WARNING, which every pass-over record is.

Regenerate with ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_youtube_sheet.py``.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from helpers.audio_files import audio, given
from helpers.corpus import DATA, VECTORS, check, dump_fixture, jsonl
from helpers.fake_ytdlp import FakeYtDlp, entry
from helpers.scenario import LEAVES_OUT, record_lookup
from test_conformance_audio_sheet import (
    ARTIST,
    LENGTH,
    MAKER,
    MTIME,
    OWN,
    TITLE,
    Beats,
    Recognizer,
    heard_of,
    lake_sites,
    phone_words,
    placed,
    store_after,
    store_files,
)
from test_conformance_lookup_scenarios import NOW, STAMP, Heard, World, clock

MADE_BY = "tests/test_conformance_youtube_sheet.py"
VECTOR = VECTORS / "lookup" / "youtube_sheet.jsonl"

PASTED = "RiverRoad01"  # the video pasted
PICKED = "RiverRoad02"  # the one a search picks
NEXT = "RiverRoad03"  # the one a search picks next, once its first pick is passed over
YOUTUBE_SHEET_JSON = DATA / "library" / "youtube_sheet.json"
OTHER = "SomethingEl"  # a video of another song
WATCH = "https://www.youtube.com/watch?v={}"
PROVIDERS = {"youtube": {"delay": (0.0, 0.0)}}
# The kv the replay compares apart: the to-do page's record of a run and the file auto-chords couldn't read (E21's),
# which the phone never writes; and YouTube's last run, which the phone's runner keeps in kv (core.youtube.YtDlp) where
# the computer's reads its events.
APART_KV = ["autochords:status", "autochords:failed:", "http:last_request:youtube"]
NO_FORMAT = (f"ERROR: [youtube] {PASTED}: Requested format is not available. Use --list-formats for a list of "
             "available formats")
UNAVAILABLE = f"ERROR: [youtube] {PASTED}: Video unavailable"
NETWORK = (f"ERROR: [youtube] {PASTED}: Unable to download webpage: <urlopen error [Errno -3] Temporary failure in "
           "name resolution>")
BROKE = f"ERROR: [youtube] {PASTED}: fragment 1 not found, unable to continue"  # an error counted against the video
GIVE_UP = 3  # youtube_fetch.GIVE_UP_AFTER, which test_the_cases_come_to_what_they_say holds it to
NOT_A_BOT = (f"ERROR: [youtube] {PASTED}: Sign in to confirm you’re not a bot. Use --cookies-from-browser or "
             "--cookies for the authentication.")


def youtube_sheet_json() -> str:
    from caracole import youtube_sheet as ys

    names = ("OWN_AUDIO", "DECLINED", "CANT_NOTE", "NOTED", "DOWNLOADING", "LOOKING", "AUDIO_ALREADY", "TURNED_BACK",
             "NO_RUNS_LEFT", "DOWNLOADED", "NO_VIDEO_FITS", "CANT_DOWNLOAD", "DOWNLOAD_FAILED", "COOLING_LATER")
    data = {"stages": [list(s) for s in ys.STAGES], "words": {n.lower(): getattr(ys, n) for n in names}}
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def world(tmp: Path, name: str) -> World:
    from caracole import db

    w = World(tmp, name, providers=PROVIDERS)
    w.cfg.state_dir.mkdir(parents=True, exist_ok=True)
    db.kv_set(w.conn, "sync:id", OWN)
    w.fake = FakeYtDlp(w.dir / "bin")  # type: ignore[attr-defined]
    w.cfg = dataclasses.replace(w.cfg, ytdlp_bin=w.fake.bin)  # type: ignore[attr-defined]
    return w


def video(w: World, vid: str = PASTED, **spec: Any) -> dict[str, Any]:
    """A video FakeYtDlp downloads (River Road's audio, 213 s, as an m4a dated MTIME), or fails as ``spec`` says;
    its plan as the record carries it."""
    data = audio("M4A", LENGTH)
    source = w.dir / "videos" / f"{vid}.m4a"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(data)
    w.fake.video(vid, f"{ARTIST} - {TITLE} (Official Audio)", ARTIST, LENGTH, ext="m4a", copy=str(source),
                 mtime=MTIME, **spec)
    carried = {k: v for k, v in w.fake.videos[vid].items() if k != "copy"}
    return {**carried, "base64": base64.b64encode(data).decode("ascii")}


def cache_files(w: World) -> dict[str, Any]:
    root = w.cfg.cache_dir / "youtube"
    return {p.name: {"base64": base64.b64encode(p.read_bytes()).decode("ascii"), "mtime": p.stat().st_mtime}
            for p in sorted(root.iterdir())} if root.is_dir() else {}


def cache_after(w: World) -> dict[str, str]:
    root = w.cfg.cache_dir / "youtube"
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.iterdir())} if root.is_dir() \
        else {}


def runs_of(w: World) -> list[dict[str, Any]]:
    """Each yt-dlp run, as youtube/runs.jsonl's ``_kind`` names it."""
    from caracole import youtube

    out = []
    for argv in w.fake.argvs():
        what = "download" if "-o" in argv else "video" if "--skip-download" in argv else "search"
        run = {"what": what, "target": argv[-1]}
        if what == "download":
            into = argv[argv.index("-o") + 1]
            assert into.endswith(f"/{youtube.OUTPUT_NAME}"), into
            run["into"] = "<into>"
        out.append(run)
    return out


def _passed_over():
    """The computer's runner, its pass-over read as the phone reads it (the module's docstring): the event as it
    wrote it, the error raised a VideoUnavailable."""
    from caracole import youtube

    real = youtube.YtDlp._run

    def run(self, args, target, what, timeout):
        try:
            return real(self, args, target, what, timeout)
        except youtube.ProviderError as e:
            if type(e) is youtube.ProviderError and youtube.PHONE_PASS_OVER.search(e.message or ""):
                raise youtube.VideoUnavailable(e.provider, e.url, e.status, e.message) from e
            raise

    return mock.patch.object(youtube.YtDlp, "_run", run)


def _yielding(w: World, write: Callable[[Any], None], holder: dict[str, Any]):
    """The chords' yield (staged.py ``_after_a_lookup``): another caracole's ``write`` meanwhile, its fixture records
    kept in ``holder``."""
    from caracole.staged import StagedRun

    real = StagedRun._after_a_lookup

    def after(self) -> None:
        before = dump_fixture(self.conn, w.cfg.library_dir)
        write(self.conn)
        holder["fixture"] = [r for r in dump_fixture(self.conn, w.cfg.library_dir) if r not in before]
        holder["store"] = store_files(w)
        for r in holder["fixture"]:  # kept at SQLite's clock: at the record's time, as the settle puts it after
            if r.get("table") == "files":
                r["row"] = {**r["row"], "created_at": STAMP}
        real(self)

    return mock.patch.object(StagedRun, "_after_a_lookup", after)


def job(w: World, case: str, url: str | None, plan: dict[str, Any], *, reads: str = "computer",
        at_yield: Callable[[Any], None] | None = None) -> dict[str, Any]:
    """``caracole youtube --song --sheet`` of River Road, recorded (the module's docstring)."""
    from contextlib import ExitStack

    from caracole.commands.youtube import sent_words
    from caracole.youtube_sheet import SheetRequest, make_sheet

    heard = Heard()
    cache, store = cache_files(w), store_files(w)
    request = SheetRequest(ARTIST, TITLE, WATCH.format(url) if url else None)
    yielded: dict[str, Any] = {}
    sent: dict[str, Any] = {}

    def call() -> dict[str, Any]:
        result = make_sheet(w.cfg, request, heard, runner=None, recognizer=Recognizer(), beats_fn=Beats(),
                            hears=False, now=NOW, clock=lambda: 0.0)
        sent["requests"] = dict(result.requests)
        return {"result": {"song_id": result.song_id, "display": result.display, "states": dict(result.states),
                           "details": dict(result.details), "files": dict(result.files),
                           "exit": 0 if result.ok else 1}, "progress": heard.events}

    leaves = {"kv": [*LEAVES_OUT["kv"], "autochords:status", "autochords:failed:"], "files": LEAVES_OUT["files"]}
    calls_before = len(w.fake.argvs())
    with ExitStack() as stack:
        if reads == "phone":
            stack.enter_context(_passed_over())
        if at_yield is not None:
            stack.enter_context(_yielding(w, at_yield, yielded))
        made = record_lookup(w.cfg, fn="caracole.youtube_sheet.make_sheet", call=call, answers=lake_sites(), now=NOW,
                             case=case, kw={}, settle=w.settled(NOW), leaves_out=leaves)
    assert "out" in made, made.get("raises")
    assert at_yield is None or yielded, "the job never yielded before its chords"
    made["kw"] = {"own": OWN, "request": {"artist": ARTIST, "title": TITLE, "url": request.url},
                  "providers": PROVIDERS, "reads": reads, "heard": heard_of(LENGTH), "hearing": "ok",
                  "audio": {"format": "M4A", "duration": LENGTH}, "ytdlp": plan, "cache": cache, "store": store,
                  "at_yield": {"stage": "chords", "fixture": yielded["fixture"], "store": yielded["store"]}
                  if at_yield is not None else None}
    out = made["out"]
    out["result"] = phone_words(out["result"])
    out["sent"] = sent_words(sent["requests"])
    out["runs"] = runs_of(w)[calls_before:]
    out["youtube"] = cache_after(w)
    out["store"] = store_after(w)
    out["maker"] = None
    for row in out["rows"].get("versions", []):
        raw = json.loads(row["raw"])
        if "made_on" in raw:
            out["maker"] = {k: raw.pop(k) for k in MAKER if k in raw}
            row["raw"] = json.dumps(raw, ensure_ascii=False)
    made["apart"] = {"lyrics": True, "events_run": True, "pauses": True, "kv": APART_KV}
    made = placed(_cached(made, str(w.cfg.cache_dir)), str(w.cfg.state_dir))
    assert str(w.dir) not in json.dumps(made, ensure_ascii=False), "a path of the world's left in the record"
    return made


def _cached(value: Any, cache: str) -> Any:
    """Every text of ``value`` with the world's cache folder written ``{cache}``."""
    if isinstance(value, str):
        return value.replace(cache, "{cache}")
    if isinstance(value, list):
        return [_cached(v, cache) for v in value]
    if isinstance(value, dict):
        return {k: _cached(v, cache) for k, v in value.items()}
    return value


def plan_of(videos: dict[str, Any] | None = None, searches: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"searches": searches or {}, "videos": videos or {}}


def query() -> str:
    from types import SimpleNamespace

    from caracole.youtube import search_query

    return search_query(SimpleNamespace(artist=ARTIST, title=TITLE))


def search(w: World, *entries: dict[str, Any]) -> dict[str, Any]:
    w.fake.search(query(), *entries)
    return {query(): {"entries": list(entries)}}


def pasted(tmp: Path) -> dict[str, Any]:
    w = world(tmp, "pasted")
    plan = plan_of({PASTED: video(w)})
    return job(w, "a video pasted for a song new to the library: added, the video noted under [youtube], its audio "
                  "downloaded, its timed lyrics found and the chords over them", PASTED, plan)


def picked(tmp: Path) -> dict[str, Any]:
    w = world(tmp, "picked")
    w.song()
    searched = search(w, entry(OTHER, "Somebody Else - Another Song", "Somebody Else", 180),
                      entry(PICKED, f"{ARTIST} - {TITLE} (Official Audio)", ARTIST, LENGTH))
    plan = plan_of({PICKED: video(w, PICKED)}, searched)
    return job(w, "a search's pick for a song of the library: the video that fits downloaded, the chords over its "
                  "lyrics", None, plan)


def none_fits(tmp: Path) -> dict[str, Any]:
    w = world(tmp, "none-fits")
    w.song()
    plan = plan_of(searches=search(w, entry(OTHER, "Somebody Else - Another Song", "Somebody Else", 180)))
    return job(w, "a search none of whose videos fits: the audio failed, nothing downloaded", None, plan)


def pass_over(tmp: Path) -> dict[str, Any]:
    w = world(tmp, "pass-over")
    w.song()
    plan = plan_of({PASTED: video(w, stderr=NO_FORMAT, exit=1)})
    return job(w, "a pasted video with no m4a stream: passed over as the phone reads it, the video unusable", PASTED,
               plan, reads="phone")


def searched_pass_over(tmp: Path) -> list[dict[str, Any]]:
    w = world(tmp, "searched-pass-over")
    w.song()
    searched = search(w, entry(PICKED, f"{ARTIST} - {TITLE} (Official Audio)", ARTIST, LENGTH),
                      entry(NEXT, f"{ARTIST} - {TITLE}", ARTIST, LENGTH))
    plan = plan_of({PICKED: video(w, PICKED, stderr=NO_FORMAT.replace(PASTED, PICKED), exit=1),
                    NEXT: video(w, NEXT)}, searched)
    first = job(w, "a searched video with no m4a stream: passed over as the phone reads it, kept in skip", None,
                plan, reads="phone")
    then = job(w, "the same job again once its first pick was passed over: the search's next pick downloaded", None,
               plan, reads="phone")
    return [first, then]


def unavailable(tmp: Path) -> dict[str, Any]:
    w = world(tmp, "unavailable")
    w.song()
    plan = plan_of({PASTED: video(w, stderr=UNAVAILABLE, exit=1)})
    return job(w, "a pasted video YouTube says is unavailable: the audio failed, the video unusable", PASTED, plan)


def blocked(tmp: Path) -> dict[str, Any]:
    w = world(tmp, "blocked")
    w.song()
    plan = plan_of({PASTED: video(w, stderr=NOT_A_BOT, exit=1)})
    return job(w, "YouTube blocking the download: its cooldown recorded, the audio skipped and the chords with it",
               PASTED, plan)


def cooling(tmp: Path) -> dict[str, Any]:
    from datetime import timedelta

    from caracole.health import record_block

    w = world(tmp, "cooling")
    w.song()
    record_block(w.conn, "youtube", NOW - timedelta(hours=1), "blocked")
    plan = plan_of({PASTED: video(w)})
    return job(w, "YouTube cooling down after a block: nothing run, the audio skipped", PASTED, plan)


def upload(tmp: Path) -> dict[str, Any]:
    import os

    from caracole.songs import get_song, update_song

    w = world(tmp, "upload")
    with clock(STAMP):
        song = get_song(w.conn, w.song())
        path = given(w.conn, w.cfg.state_dir, song, "M4A", LENGTH)
        os.utime(path, (MTIME, MTIME))
        update_song(w.conn, song.id, audio_mtime=float(MTIME))
    plan = plan_of({PASTED: video(w)})
    return job(w, "a song with an audio file of its own given: refused, YouTube asked nothing", PASTED, plan)


def human_sheet(tmp: Path) -> dict[str, Any]:
    from caracole.library import keep_file
    from caracole.normalize import identity_key
    from caracole.songs import find_song
    from caracole.versions import upsert_version

    w = world(tmp, "human")
    w.song()

    def keep(conn) -> None:  # another caracole's `caracole get` kept UG's chords meanwhile
        song = find_song(conn, identity_key(ARTIST, TITLE))
        vid = upsert_version(conn, provider="ug", tab_id="101", song_id=song.id, slot="sheet", kind="chords",
                             rating=4.8, votes=120, version=1, label=None, url="https://tabs.ultimate-guitar.com/tab/x",
                             raw={}, now=STAMP)
        keep_file(conn, w.cfg.library_dir, song=song, version_id=vid, name="sheet.txt", data=b"[ch]G[/ch]\nHi", rank=1)

    plan = plan_of({PASTED: video(w)})
    return job(w, "a human sheet kept while the job let a lookup go first before its chords: refused there, its audio "
                  "and lyrics kept", PASTED, plan, at_yield=keep)


def upload_meanwhile(tmp: Path) -> dict[str, Any]:
    import os

    from caracole.normalize import identity_key
    from caracole.songs import find_song, update_song

    w = world(tmp, "upload-meanwhile")
    w.song()

    def upload(conn) -> None:  # the owner's audio file kept for the song meanwhile (another caracole's `audio`)
        song = find_song(conn, identity_key(ARTIST, TITLE))
        path = given(conn, w.cfg.state_dir, song, "M4A", LENGTH)
        os.utime(path, (MTIME, MTIME))
        update_song(conn, song.id, audio_mtime=float(MTIME))

    plan = plan_of({PASTED: video(w)})
    return job(w, "an audio file of the owner's kept while the job let a lookup go first before its chords: refused "
                  "there, the video's audio kept for its days", PASTED, plan, at_yield=upload)


def kept_already(tmp: Path) -> dict[str, Any]:
    w = world(tmp, "kept")
    w.song()
    plan = plan_of({PASTED: video(w)})
    job(w, "the first run", PASTED, plan)
    w.conn.execute("UPDATE files SET created_at = ?", (STAMP,))
    return job(w, "the same job again once the video's audio is kept: nothing run, its sheet up to date", PASTED,
               plan)


def let_go(made: dict[str, Any], case: str) -> dict[str, Any]:
    """``made`` (a job of a song whose sheet and audio were kept, Python's) as the phone's own state leaves it before
    the job: once its sheet was kept the phone let the video's audio go (YouTubeAudio.letGo, the design's §5.4), so
    its fixture's song has no ``audio_path`` and no ``audio_mtime`` (its ``updated_at`` the first job's), its record no
    ``audio`` and the cache no file. What the job comes to is Python's own second run's: the phone's, by the ruling of
    2026-11-27, runs no yt-dlp and no model for a sheet made of the very video asked for and up to date."""
    out = json.loads(json.dumps(made))
    out["case"] = case
    for r in out["fixture"]:
        if r.get("table") == "songs":
            r["row"] = {**r["row"], "audio_path": None, "audio_mtime": None, "updated_at": out["now"]}
        elif r.get("kv", "").startswith("youtube:") and r["kv"][len("youtube:"):].isdigit():
            r["value"] = json.dumps({**json.loads(r["value"]), "audio": None}, ensure_ascii=False)
    out["kw"]["cache"] = {}
    return out


def kept_after_let_go(kept: dict[str, Any]) -> dict[str, Any]:
    return let_go(kept, "the same job again on the phone's state once its sheet was kept and the video's "
                                     "audio let go: nothing run, no model, its sheet up to date")


def _seeded(w: World, record: Any) -> None:
    from caracole.youtube_fetch import _save

    _save(w.conn, 1, record)


def network_error(tmp: Path) -> dict[str, Any]:
    w = world(tmp, "network")
    w.song()
    plan = plan_of({PASTED: video(w, stderr=NETWORK, exit=1)})
    return job(w, "a pasted video's download the network failed: an error, nothing counted against the video", PASTED,
               plan)


def counted_error(tmp: Path) -> dict[str, Any]:
    w = world(tmp, "counted")
    w.song()
    plan = plan_of({PASTED: video(w, stderr=BROKE, exit=1)})
    return job(w, "a pasted video's download that failed: the error counted once against the video", PASTED, plan)


def given_up_pasted(tmp: Path) -> dict[str, Any]:
    from caracole.youtube_fetch import Record

    w = world(tmp, "given-up-pasted")
    w.song()
    _seeded(w, Record(failures={PASTED: GIVE_UP - 1}))
    plan = plan_of({PASTED: video(w, stderr=BROKE, exit=1)})
    return job(w, "a pasted video's download failing for the third time: the video given up, unusable", PASTED, plan)


def given_up_searched(tmp: Path) -> dict[str, Any]:
    from caracole.youtube import Video
    from caracole.youtube_fetch import Record

    w = world(tmp, "given-up-searched")
    w.song()
    _seeded(w, Record(video=Video(PICKED, f"{ARTIST} - {TITLE} (Official Audio)", ARTIST, float(LENGTH)),
                      source="search", query=query(), failures={PICKED: GIVE_UP - 1}))
    plan = plan_of({PICKED: video(w, PICKED, stderr=BROKE.replace(PASTED, PICKED), exit=1)})
    return job(w, "a searched video's download failing for the third time: the video given up into skip", None, plan)


def records(tmp: Path) -> list[dict[str, Any]]:
    kept = kept_already(tmp)
    return [pasted(tmp), picked(tmp), none_fits(tmp), pass_over(tmp), *searched_pass_over(tmp), unavailable(tmp),
            blocked(tmp), cooling(tmp), upload(tmp), human_sheet(tmp), upload_meanwhile(tmp), kept,
            kept_after_let_go(kept), network_error(tmp), counted_error(tmp), given_up_pasted(tmp),
            given_up_searched(tmp)]


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> list[dict[str, Any]]:
    return records(tmp_path_factory.mktemp("youtube-sheet"))


def test_youtube_sheet_json_is_the_jobs_words():
    check(YOUTUBE_SHEET_JSON, youtube_sheet_json())


def test_the_vector_is_what_caracole_youtube_sheet_does(made):
    check(VECTOR, jsonl(made, corpus="lookup", made_by=MADE_BY))


def test_the_vector_is_the_same_on_another_run(made, tmp_path):
    assert jsonl(records(tmp_path), corpus="lookup", made_by=MADE_BY) == jsonl(made, corpus="lookup",
                                                                               made_by=MADE_BY)


def _ends(record: dict[str, Any]) -> dict[str, list[str]]:
    r = record["out"]["result"]["result"]
    return {k: [r["states"][k], r["details"][k]] for k in r["states"]}


def test_the_cases_come_to_what_they_say(made):
    by = {r["case"].split(":")[0]: r for r in made}
    watch = WATCH.format(PASTED)
    first = by["a video pasted for a song new to the library"]
    ends = _ends(first)
    assert ends["song"] == ["done", f"added to the book; noted under [youtube]: {watch}"]
    assert ends["audio"] == ["done", f"downloaded {ARTIST} - {TITLE} (Official Audio) ({ARTIST}), {watch}"]
    assert ends["lyrics"] == ["done", "found, timed"] and ends["chords"] == ["done", "chords over the lyrics"]
    assert first["out"]["runs"] == [{"what": "download", "target": watch, "into": "<into>"}]
    assert first["out"]["youtube"] == {f"1-{PASTED}.m4a": hashlib.sha256(audio("M4A", LENGTH)).hexdigest()}
    assert first["out"]["maker"]["made_on"] == "computer"
    pick = by["a search's pick for a song of the library"]
    assert [r["what"] for r in pick["out"]["runs"]] == ["search", "download"]
    assert pick["out"]["runs"][1]["target"] == WATCH.format(PICKED) and _ends(pick)["chords"][0] == "done"
    assert _ends(by["a search none of whose videos fits"])["audio"] == ["failed", "no video fits; give it one"]
    for case in ("a pasted video with no m4a stream", "a pasted video YouTube says is unavailable"):
        assert _ends(by[case])["audio"] == ["failed", "can't download this video; try another"], case
        assert json.loads(by[case]["out"]["kv"]["youtube:1"])["unusable"] == PASTED, case
    assert by["a pasted video with no m4a stream"]["out"]["events"][0][4] == "error"
    skipped = by["a searched video with no m4a stream"]
    assert _ends(skipped)["audio"] == ["failed", "can't download this video; try another"]
    assert json.loads(skipped["out"]["kv"]["youtube:1"])["skip"] == [PICKED]
    assert [r["what"] for r in skipped["out"]["runs"]] == ["search", "download"]
    after = by["the same job again once its first pick was passed over"]
    assert [r["target"] for r in after["out"]["runs"]] == [f"ytsearch8:{query()}", WATCH.format(NEXT)]
    assert _ends(after)["audio"][0] == "done" and _ends(after)["chords"][0] == "done"
    block = by["YouTube blocking the download"]
    assert len(block["out"]["runs"]) == 1, "a block stops the runs: no second"
    assert _ends(block)["audio"][1].startswith("YouTube turned us back; waiting until ")
    assert json.loads(block["out"]["kv"]["provider:youtube"])["strikes"] == 1
    assert _ends(block)["chords"] == ["skipped", "no audio"] and _ends(block)["pdf"][0] == "skipped"
    cool = by["YouTube cooling down after a block"]
    assert _ends(cool)["audio"][1].startswith("waiting out YouTube until ") and cool["out"]["runs"] == []
    given_audio = by["a song with an audio file of its own given"]
    assert _ends(given_audio)["song"] == ["failed", f"{ARTIST} - {TITLE} has its own audio (bought or given); "
                                                   "auto-chords uses that"]
    assert given_audio["out"]["runs"] == [] and given_audio["kw"]["store"]
    human = by["a human sheet kept while the job let a lookup go first before its chords"]
    assert _ends(human)["song"] == ["failed", f"{ARTIST} - {TITLE} already has a sheet"]
    assert _ends(human)["audio"][0] == "done" and _ends(human)["chords"][0] == "skipped"
    assert any(r.get("table") == "files" for r in human["kw"]["at_yield"]["fixture"]) and human["out"]["maker"] is None
    meanwhile = by["an audio file of the owner's kept while the job let a lookup go first before its chords"]
    assert _ends(meanwhile)["song"] == ["failed", f"{ARTIST} - {TITLE} has its own audio (bought or given); "
                                                  "auto-chords uses that"]
    assert _ends(meanwhile)["audio"][0] == "done" and _ends(meanwhile)["chords"][0] == "skipped"
    assert meanwhile["kw"]["at_yield"]["store"] and meanwhile["out"]["youtube"]
    again = by["the same job again once the video's audio is kept"]
    assert _ends(again)["audio"] == ["done", f"has the audio of {watch} already"]
    assert _ends(again)["chords"] == ["done", "up to date: chords over the lyrics"]
    assert again["out"]["runs"] == [] and again["kw"]["cache"]
    let_go_again = by["the same job again on the phone's state once its sheet was kept and the video's audio let go"]
    assert let_go_again["out"] == again["out"] and let_go_again["kw"]["cache"] == {}
    [song] = [r["row"] for r in let_go_again["fixture"] if r.get("table") == "songs"]
    assert song["audio_path"] is None and song["autochords_mtime"] is not None
    from caracole.youtube_fetch import GIVE_UP_AFTER

    assert GIVE_UP == GIVE_UP_AFTER

    def record_of(case: str) -> dict[str, Any]:
        return json.loads(by[case]["out"]["kv"]["youtube:1"])

    network = "a pasted video's download the network failed"
    assert _ends(by[network])["audio"] == ["failed", "download failed; try again later"]
    assert record_of(network)["failures"] == {} and "Temporary failure" in record_of(network)["error"]
    counted = "a pasted video's download that failed"
    assert _ends(by[counted])["audio"] == ["failed", "download failed; try again later"]
    assert record_of(counted)["failures"] == {PASTED: 1}
    pasted_up = record_of("a pasted video's download failing for the third time")
    assert pasted_up["unusable"] == PASTED and pasted_up["failures"] == {}
    assert pasted_up["unusable_reason"].startswith("its download failed 3 times: ")
    searched_up = record_of("a searched video's download failing for the third time")
    assert searched_up["skip"] == [PICKED] and searched_up["video"] is None and searched_up["failures"] == {}
    assert searched_up["error"].endswith("failed 3 times: the next run picks another)")
    assert first["out"]["sent"] == "1 yt-dlp run, 1 LRCLIB request" and again["out"]["sent"] == ""
    waits = {network, counted}  # an error is a wait (exit 0), as a block or a cooldown is
    for r in made:  # a refusal or a video that can't be had exits 1
        states = r["out"]["result"]["result"]["states"]
        failed = "failed" in (states["song"], states["audio"]) and r["case"].split(":")[0] not in waits
        assert r["out"]["result"]["result"]["exit"] == int(failed), r["case"]
