"""``caracole youtube --song --sheet`` for the phone: whole jobs recorded, for :server's ``YouTubeSheetRunner`` (the
phone-YouTube plan's Y2.3) to agree with, as test_conformance_audio_sheet.py records ``caracole audio`` (E21's record
shape, whose docstring this one follows and whose helpers it shares).

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
  as ``fixture`` holds them, which the replay writes at its yield there);
- ``out.result``: ``{result, progress, python}`` as E21's (``phone_words``: the song stage of a song added
  ``get.ADDED``, vocals and words the phone's skip, the pdf ``get.NO_PDFS``, the pages ``get.LIBRARY_PAGE``; Python's
  own in ``python``);
- ``out.runs``: each yt-dlp run in order, ``{what, target}`` (``search``, ``video`` or ``download``, the target after
  ``--``) and a download's ``into`` (``<into>``: the folder it was given), as youtube/runs.jsonl's: the phone's argv
  is its own template's (youtube.json), never the computer's;
- ``out.youtube``: the files of ``cache_dir/youtube/`` after, each by its SHA-256; ``out.store``: ``state_dir/audio/``'s
  after (E21's ``store_after``);
- ``out.maker``: the auto sheet's maker members Python wrote, each side's own, out of the ``versions`` rows' raw;
- ``apart``: what the replay compares apart, by design: ``lyrics`` (get.py's words at the lookup pace on the phone),
  ``events_run`` and ``pauses`` (the bulk pace's against the lookup's), and ``kv`` the phone never writes
  (``autochords:status``, ``autochords:failed:``) or the computer doesn't (``http:last_request:youtube``: the
  phone's runner keeps its last run there, the computer's reads its events).

Every path under the world's state folder is written ``{state}``, under its cache folder ``{cache}``.

The cases: a video pasted (``--url``) for a song new to the library, its timed lyrics found and the chords over them;
a search's pick for a song of the library; a search none of whose videos fits; a video with no m4a stream (a
pass-over); an unavailable video; YouTube blocking the download (the cooldown recorded, the chords skipped); YouTube
cooling down (nothing run); a song with an audio file of its own given (refused); a human sheet kept while the job let
a lookup go first before the chords (refused there); and the same job again once the video's audio is kept (nothing
run, the sheet up to date).

A pass-over is recorded as the phone reads it: the computer's runner reads "Requested format is not available" as an
error (its download asks ``bestaudio[ext=m4a]/bestaudio/best``, so it is the network's or the extractor's fault there)
and counts it against the video, where the phone's asks m4a alone (``youtube.PHONE_FORMAT``) and passes the video over
(``core.youtube.PassedOver``, a VideoUnavailable, its event an ``error`` with the reason, as the computer's). The record
runs the computer's job with that one reading swapped (``_passed_over``), and says so (``kw.reads`` "phone").

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
from helpers.corpus import VECTORS, check, dump_fixture, jsonl
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
NOT_A_BOT = (f"ERROR: [youtube] {PASTED}: Sign in to confirm you’re not a bot. Use --cookies-from-browser or "
             "--cookies for the authentication.")


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
        for r in holder["fixture"]:  # kept at SQLite's clock: at the record's time, as the settle puts it after
            if r.get("table") == "files":
                r["row"] = {**r["row"], "created_at": STAMP}
        real(self)

    return mock.patch.object(StagedRun, "_after_a_lookup", after)


def job(w: World, case: str, url: str | None, plan: dict[str, Any], *, reads: str = "computer",
        at_yield: Callable[[Any], None] | None = None) -> dict[str, Any]:
    """``caracole youtube --song --sheet`` of River Road, recorded (the module's docstring)."""
    from contextlib import ExitStack

    from caracole.youtube_sheet import SheetRequest, make_sheet

    heard = Heard()
    cache, store = cache_files(w), store_files(w)
    request = SheetRequest(ARTIST, TITLE, WATCH.format(url) if url else None)
    yielded: dict[str, Any] = {}

    def call() -> dict[str, Any]:
        result = make_sheet(w.cfg, request, heard, runner=None, recognizer=Recognizer(), beats_fn=Beats(),
                            hears=False, now=NOW, clock=lambda: 0.0)
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
                  "at_yield": {"stage": "chords", "fixture": yielded["fixture"]} if at_yield is not None else None}
    out = made["out"]
    out["result"] = phone_words(out["result"])
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


def kept_already(tmp: Path) -> dict[str, Any]:
    w = world(tmp, "kept")
    w.song()
    plan = plan_of({PASTED: video(w)})
    job(w, "the first run", PASTED, plan)
    w.conn.execute("UPDATE files SET created_at = ?", (STAMP,))
    return job(w, "the same job again once the video's audio is kept: nothing run, its sheet up to date", PASTED,
               plan)


def records(tmp: Path) -> list[dict[str, Any]]:
    return [pasted(tmp), picked(tmp), none_fits(tmp), pass_over(tmp), unavailable(tmp), blocked(tmp), cooling(tmp),
            upload(tmp), human_sheet(tmp), kept_already(tmp)]


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> list[dict[str, Any]]:
    return records(tmp_path_factory.mktemp("youtube-sheet"))


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
    block = by["YouTube blocking the download"]
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
    again = by["the same job again once the video's audio is kept"]
    assert _ends(again)["audio"] == ["done", f"has the audio of {watch} already"]
    assert _ends(again)["chords"] == ["done", "up to date: chords over the lyrics"]
    assert again["out"]["runs"] == [] and again["kw"]["cache"]
    for r in made:  # a refusal or a video that can't be had exits 1; a block or a cooldown is a wait, 0
        states = r["out"]["result"]["result"]["states"]
        assert r["out"]["result"]["result"]["exit"] == int("failed" in (states["song"], states["audio"])), r["case"]
