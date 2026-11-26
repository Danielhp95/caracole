"""caracole/web/outcome.py: what the requests page says of a request, the running one's steps and how a
finished one ended, with the next step to take."""

from datetime import UTC, datetime, timedelta

import pytest

from caracole.get import GTPTABS_KEPT, MATCH_NOT_FOUND, NOT_IN_INDEX, SHEET_FROM, STAGES
from caracole.songs import get_song, update_song
from caracole.youtube_sheet import HOLDS
from caracole.web.jobs import (
    INTERRUPTED,
    KEEP_STAGES,
    LACUERDA_ARTIST,
    REMOVING,
    Job,
    Stage,
    Step,
    lookup_steps,
    remove_steps,
    version_steps,
)
from caracole.web.outcome import (INTERRUPTED_RAN, INTERRUPTED_SYNC_RAN, INTERRUPTED_SYNC_WAITED, SITE_NAMES, Action,
                                  Chip, Outcome, elsewhere, outcome, progress, steps)
from caracole.web.status import SongFacts, job_line

from conftest import add_song


START = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)  # long past: a running job asked with no ``now`` ran for days


def times(state):
    """A job's start and end in ``state``: started at ``START`` unless queued or cancelled, over 30 s later."""
    return {"started_at": None if state in ("queued", "cancelled") else START,
            "finished_at": None if state in ("queued", "running") else START + timedelta(seconds=30)}


def lookup(state="running", stages=None, *, args=None, job_id=4, display="Muse - Hysteria"):
    """A lookup, its stages in ``stages`` (name -> (state, detail)), the others waiting."""
    made = [Step(label, tuple(a)) for label, a in lookup_steps(*display.split(" - "))] if args is None else [
        Step("Fetching", tuple(args))]
    said = stages or {}
    job = Job(job_id, f"Fetch {display}", display.lower().replace(" - ", "/"), made, fetching=True,
              display=display, state=state, **times(state),
              stages=[Stage(name, label, *said.get(name, ("waiting", ""))) for name, label in STAGES])
    if state != "running":
        made[0].state = "done" if state == "done" else "failed"
    return job


def ended(stages, state="done", **kw):
    """A lookup that is over: every stage not named done, unless named."""
    every = {name: ("done", "") for name, _ in STAGES} | stages
    return lookup(state, every, **kw)


def upto(name, state="running", **said):
    """A lookup's stages: those before ``name`` done, ``name`` in ``state``, then ``said`` over them."""
    names = [n for n, _ in STAGES]
    return {n: ("done", "") for n in names[:names.index(name)]} | {name: (state, "")} | said


# --- the running request's steps ---------------------------------------------------------------------


def test_a_lookup_in_progress_shows_its_stages_as_steps_in_plain_words():
    job = lookup(stages={"song": ("done", "in the book"), "match": ("done", "matched to muse/hysteria"),
                         "sheet": ("done", "tab 1 from Ultimate Guitar"), "pdf": ("running", "")})
    assert steps(job, SongFacts(sheet="Muse/Hysteria/sheet.html", sheet_from="UG")) == [
        Chip("Song", "done", "", "in the book"), Chip("Match", "done", "Ultimate Guitar", "matched to muse/hysteria"),
        Chip("Sheet", "done", "Ultimate Guitar", "tab 1 from Ultimate Guitar"), Chip("PDF", "running"),
        Chip("Lyrics", "waiting"), Chip("Extras", "waiting"), Chip("Songbooks", "waiting")]
    # Ultimate Guitar's second pass, LaCuerda's and gtptabs.com's are one step, running from the first to the last.
    later = lookup(stages={name: ("done", "") for name in ("song", "match", "sheet", "pdf", "lyrics", "ug")}
                   | {"lacuerda": ("running", "")})
    assert Chip("Extras", "running") in steps(later) and Chip("Lyrics", "done") in steps(later)


def test_each_step_names_its_site_in_full_and_says_what_it_found():
    job = lookup(stages={"song": ("done", "in the book"), "match": ("done", "matched to muse/hysteria"),
                         "sheet": ("done", "tab 1 from Ultimate Guitar"), "pdf": ("running", "")})
    assert steps(job, SongFacts(sheet="Muse/Hysteria/sheet.html", sheet_from="UG"))[:4] == [
        Chip("Song", "done", "", "in the book"), Chip("Match", "done", "Ultimate Guitar", "matched to muse/hysteria"),
        Chip("Sheet", "done", "Ultimate Guitar", "tab 1 from Ultimate Guitar"), Chip("PDF", "running")]
    extras = ended({"ug": ("done", "sheet 1"), "lacuerda": ("skipped", "not for LaCuerda"),
                    "gtptabs": ("done", GTPTABS_KEPT)})
    assert steps(extras)[5] == Chip("Extras", "done", "", "sheet 1 · " + GTPTABS_KEPT)
    failed = lookup(stages={"song": ("done", ""), "match": ("done", "")})
    failed.heard({"stage": "sheet", "state": "running", "detail": SHEET_FROM["ug"]})
    failed.heard({"stage": "sheet", "state": "failed",
                  "detail": "Ultimate Guitar failed (ug: 502); tried again tonight"})
    assert steps(failed)[2] == Chip("Sheet", "failed", "Ultimate Guitar",
                                    "Ultimate Guitar answered 502. The sheet waits until tonight.")
    plain = lookup(stages={"song": ("done", ""), "match": ("done", MATCH_NOT_FOUND)})
    assert steps(plain)[1] == Chip("Match · not on UG", "plain")  # its name says it: nothing found to add
    assert SITE_NAMES["UG"] == "Ultimate Guitar" and SITE_NAMES["LaCuerda"] == "LaCuerda"


def test_harptabs_coms_stage_is_part_of_the_extras_step_and_says_what_waits_in_its_words():
    # The lookup's last site, after gtptabs.com: Extras runs until it is over, and a spent budget says its harmonica tab.
    extras = {name: ("done", "") for name in ("song", "match", "sheet", "pdf", "lyrics", "ug", "lacuerda", "gtptabs")}
    running = lookup(stages=extras | {"harptabs": ("running", "")})
    assert Chip("Extras", "running") in steps(running)
    assert Chip("Extras", "running", "", "harmonica tab kept") in steps(lookup(stages=extras | {
        "harptabs": ("done", "harmonica tab kept"), "gametabs": ("waiting", "")}))
    assert Chip("Extras", "done", "", "harmonica tab kept") in steps(lookup(stages=extras | {
        "harptabs": ("done", "harmonica tab kept"), "gametabs": ("done", "")}))
    spent = ended({"harptabs": ("skipped", "this fetch's 6 asks of harptabs.com are spent; tonight's run does "
                                           "the rest")})
    assert said(spent, SongFacts(sheet="Muse/Hysteria/sheet.html")).reason == (
        "This fetch's 6 asks of harptabs.com are spent. The harmonica tab waits until tonight.")


def test_gametabs_nets_stage_is_the_extras_steps_last_and_says_what_waits_in_its_words():
    extras = {name: ("done", "") for name in ("song", "match", "sheet", "pdf", "lyrics", "ug", "lacuerda", "gtptabs",
                                              "harptabs")}
    assert Chip("Extras", "running") in steps(lookup(stages=extras | {"gametabs": ("running", "")}))
    assert Chip("Extras", "done", "", "game music tab kept") in steps(lookup(stages=extras | {
        "gametabs": ("done", "game music tab kept")}))
    spent = ended({"gametabs": ("skipped", "this fetch's 6 asks of gametabs.net are spent; tonight's run does "
                                           "the rest")})
    assert said(spent, SongFacts(sheet="Muse/Hysteria/sheet.html")).reason == (
        "This fetch's 6 asks of gametabs.net are spent. The game music tab waits until tonight.")


def test_a_lookups_steps_are_fixed_when_it_starts_and_a_skipped_one_keeps_its_place():
    skipped = lookup(stages={"song": ("done", ""), "match": ("done", MATCH_NOT_FOUND),
                             "sheet": ("skipped", NOT_IN_INDEX), "pdf": ("skipped", "no sheet yet"),
                             "lyrics": ("running", "")})
    assert [(c.name, c.state) for c in steps(skipped)] == [
        ("Song", "done"), ("Match · not on UG", "plain"), ("Sheet", "skipped"), ("PDF", "skipped"),
        ("Lyrics", "running"), ("Extras", "waiting"), ("Songbooks", "waiting")]
    leaves = lookup(args=lookup_steps("Muse", "Hysteria", songbooks=False)[0][1])  # fixed by its command
    assert [c.name for c in steps(leaves)] == ["Song", "Match", "Sheet", "PDF", "Lyrics", "Extras"]
    # A failed stage stays, as failed.
    failed = lookup(stages={"song": ("done", ""), "match": ("done", ""), "sheet": ("done", ""),
                            "pdf": ("failed", "chordpro couldn't make the PDF (see the log)"),
                            "lyrics": ("running", "")})
    assert Chip("PDF", "failed", "", "chordpro couldn't make the PDF (see the log).") in steps(failed)


def test_match_says_the_index_it_matched_in_and_sheet_the_site_it_asked_then_got_it_from():
    # Match is the offline index's, Ultimate Guitar's. The sheet names no site until it asks one, then the one it
    # asks (get.SHEET_FROM), switching when it falls back to the other; once done, where the song's sheet came from.
    asked = {"song": ("done", "in the book"), "match": ("done", "matched to muse/hysteria")}
    assert steps(lookup(stages={**asked, "sheet": ("running", "")}))[1:3] == [
        Chip("Match", "done", "Ultimate Guitar", "matched to muse/hysteria"), Chip("Sheet", "running")]
    assert steps(lookup(stages={**asked, "sheet": ("running", SHEET_FROM["ug"])}))[2] == Chip(
        "Sheet", "running", "Ultimate Guitar")
    assert steps(lookup(stages={**asked, "sheet": ("running", SHEET_FROM["lacuerda"])}))[2] == Chip(
        "Sheet", "running", "LaCuerda")
    done = lookup(stages={**asked, "sheet": ("done", "sheet kept from LaCuerda"), "pdf": ("running", "")})
    assert steps(done, SongFacts(sheet="Muse/Hysteria/sheet.html", sheet_from="LaCuerda"))[2] == Chip(
        "Sheet", "done", "LaCuerda", "sheet kept from LaCuerda")
    # Where it came from isn't known: no site, never a guess.
    assert steps(done)[2] == Chip("Sheet", "done", "", "sheet kept from LaCuerda")
    assert [c.name for c in steps(lookup(stages={}))[:3]] == ["Song", "Match", "Sheet"]  # waiting: no site yet
    # The auto sheet's is auto-chords; a tag caracole has no name for in full is named as it is.
    auto = SongFacts(sheet="Muse/Hysteria/sheet%20%28auto%29.html", sheet_from="auto")
    assert steps(done, auto)[2].site == "auto-chords"
    assert steps(done, SongFacts(sheet="Muse/Hysteria/sheet.html", sheet_from="Frob"))[2].site == "Frob"


def test_a_song_ultimate_guitars_index_lacks_is_drawn_plain_never_a_failure():
    # The sheet may come from LaCuerda: "Match · not on UG", which is over, as a done step is.
    job = lookup(stages={"song": ("done", "in the book"),
                         "match": ("done", MATCH_NOT_FOUND + " (UG's index is incomplete)"),
                         "sheet": ("running", SHEET_FROM["lacuerda"])})
    assert steps(job)[:3] == [Chip("Song", "done", "", "in the book"), Chip("Match · not on UG", "plain"),
                              Chip("Sheet", "running", "LaCuerda")]


def test_a_sheet_that_failed_names_the_site_it_asked_when_it_did():
    job = lookup(stages={"song": ("done", ""), "match": ("done", "matched to muse/hysteria")})
    job.heard({"stage": "sheet", "state": "running", "detail": SHEET_FROM["ug"]})
    job.heard({"stage": "sheet", "state": "failed", "detail": "Ultimate Guitar failed (ug: 502); tried again "
                                                              "tonight"})
    assert steps(job)[2] == Chip("Sheet", "failed", "Ultimate Guitar",
                                 "Ultimate Guitar answered 502. The sheet waits until tonight.")
    # A failure the outcome's words don't read is found as the stage said it.
    bug = lookup(stages={"song": ("done", ""), "match": ("done", ""), "sheet": ("failed", "a bug in caracole: x")})
    assert steps(bug)[2] == Chip("Sheet", "failed", "", "a bug in caracole: x")


def test_the_library_page_draws_a_running_lookups_steps_with_the_count_of_the_step_in_hand():
    facts = SongFacts(sheet_from="UG")
    lyrics = lookup(stages={name: ("done", "") for name in ("song", "match", "sheet", "pdf")} | {"lyrics": (
        "running", "")})
    shown = progress(lyrics, job_line(lyrics, facts), facts)
    assert shown == {
        "steps": [{"name": "Song", "site": "", "state": "done", "found": ""},
                  {"name": "Match", "site": "Ultimate Guitar", "state": "done", "found": ""},
                  {"name": "Sheet", "site": "Ultimate Guitar", "state": "done", "found": ""},
                  {"name": "PDF", "site": "", "state": "done", "found": ""},
                  {"name": "Lyrics", "site": "", "state": "running", "found": ""},
                  {"name": "Extras", "site": "", "state": "waiting", "found": ""},
                  {"name": "Songbooks", "site": "", "state": "waiting", "found": ""}],
        "at": 4, "count": "5 of 7"}
    assert [list(step) for step in shown["steps"]] == [["name", "site", "state", "found"]] * 7  # in that order
    # Match: not on UG is over, as a done step is; a skipped step keeps its place, and the total stays.
    lacuerda = lookup(stages={"song": ("done", ""), "match": ("done", MATCH_NOT_FOUND),
                              "sheet": ("running", SHEET_FROM["lacuerda"])})
    assert progress(lacuerda, job_line(lacuerda, None), None)["count"] == "3 of 7"
    dropped = lookup(stages={"song": ("done", ""), "match": ("done", MATCH_NOT_FOUND),
                             "sheet": ("skipped", NOT_IN_INDEX), "pdf": ("skipped", "no sheet yet"),
                             "lyrics": ("running", "")})
    assert progress(dropped, job_line(dropped, None), None)["count"] == "5 of 7"


def test_the_count_names_the_step_in_hand_and_only_rises():
    said = [{}, upto("song"), upto("match", "waiting"),
            upto("lyrics", sheet=("skipped", NOT_IN_INDEX), pdf=("skipped", "no sheet yet")),
            upto("lacuerda", "waiting"), upto("pages"), upto("songbooks")]
    shown = [progress(job, job_line(job, None), None) for job in (lookup(stages=s) for s in said)]
    assert [s["count"] for s in shown] == ["1 of 7", "1 of 7", "2 of 7", "5 of 7", "6 of 7", "7 of 7", "7 of 7"]
    assert [s["at"] for s in shown] == [0, 0, 1, 4, 5, 6, 6] and {len(s["steps"]) for s in shown} == {7}


def test_once_over_the_count_names_the_step_that_failed_and_nothing_else():
    stopped = ended({"sheet": ("skipped", COOLING), "pdf": ("skipped", "no sheet yet"),
                     "songbooks": ("skipped", "in no songbook")})
    shown = progress(stopped, job_line(stopped, SongFacts()), SongFacts())
    assert [s["state"] for s in shown["steps"]] == ["done", "done", "failed", "skipped", "done", "done", "skipped"]
    assert (shown["at"], shown["count"]) == (2, "3 of 7")
    missing = ended({"match": ("done", MATCH_NOT_FOUND), "sheet": ("skipped", NOT_IN_INDEX),
                     "pdf": ("skipped", "no sheet yet"), "songbooks": ("skipped", "in no songbook")})
    facts = SongFacts(not_found=True, checked_now=True)
    assert set(progress(missing, job_line(missing, facts), facts)) == {"steps"}  # no failure: the bar alone
    refused = ended({"song": ("failed", "overrides.toml can't be read: line 3")}
                    | {name: ("skipped", "") for name, _ in STAGES[1:]}, state="failed")
    shown = progress(refused, job_line(refused, None), None)
    assert [s["state"] for s in shown["steps"]] == ["failed"] + ["skipped"] * 6 and shown["count"] == "1 of 7"
    cut = ended(upto("sheet", INTERRUPTED) | {n: ("skipped", "") for n, _ in STAGES[3:]}, state=INTERRUPTED)
    shown = progress(cut, job_line(cut, None), None)
    assert [s["state"] for s in shown["steps"]] == ["done", "done", "failed"] + ["skipped"] * 4
    assert shown["count"] == "3 of 7"
    # Cut off as it asked Ultimate Guitar: the site it asked, and nothing found, what it said while it ran being no
    # finding.
    asking = lookup(stages={"song": ("done", "in the book"), "match": ("done", "matched to muse/hysteria")})
    asking.heard({"stage": "sheet", "state": "running", "detail": SHEET_FROM["ug"]})
    asking.heard({"stage": "sheet", "state": INTERRUPTED, "detail": SHEET_FROM["ug"]})  # as jobs.py leaves it
    assert steps(asking)[2] == Chip("Sheet", "failed", "Ultimate Guitar")
    # A stage of the same step that ended keeps its words.
    later = ended(upto("lacuerda", INTERRUPTED, ug=("done", "sheet 1"), lacuerda=(INTERRUPTED, "asking LaCuerda"))
                  | {n: ("skipped", "") for n, _ in STAGES[7:]}, state=INTERRUPTED)
    assert progress(later, job_line(later, None), None)["steps"][5] == {
        "name": "Extras", "site": "", "state": "failed", "found": "sheet 1"}


def test_the_steps_fold_away_once_a_lookup_ends_ready_and_stay_once_it_ends_otherwise():
    ready = SongFacts(sheet="Muse/Hysteria/sheet.html", sheet_from="UG")
    over = ended({"songbooks": ("skipped", "in no songbook")})
    assert progress(over, job_line(over, ready), ready) == {}  # the song's line opens the sheet itself
    # Ended otherwise, the steps stay, each in its place: they show which step stopped, the count naming the one that
    # failed, and none when none did.
    missing = ended({"match": ("done", MATCH_NOT_FOUND), "sheet": ("skipped", NOT_IN_INDEX),
                     "pdf": ("skipped", "no sheet yet"), "songbooks": ("skipped", "in no songbook")})
    facts = SongFacts(not_found=True, checked_now=True)
    assert job_line(missing, facts).text == "Not on the sites"
    assert progress(missing, job_line(missing, facts), facts) == {"steps": [
        {"name": "Song", "site": "", "state": "done", "found": ""},
        {"name": "Match · not on UG", "site": "", "state": "plain", "found": ""},
        {"name": "Sheet", "site": "", "state": "skipped", "found": ""},
        {"name": "PDF", "site": "", "state": "skipped", "found": ""},
        {"name": "Lyrics", "site": "", "state": "done", "found": ""},
        {"name": "Extras", "site": "", "state": "done", "found": ""},
        {"name": "Songbooks", "site": "", "state": "skipped", "found": ""}]}
    failed = ended({"song": ("failed", "overrides.toml can't be read: line 3")} | {
        name: ("skipped", "") for name, _ in STAGES[1:]}, state="failed")
    assert progress(failed, job_line(failed, None), None) == {"steps": [
        {"name": "Song", "site": "", "state": "failed", "found": "overrides.toml can't be read: line 3"},
        {"name": "Match", "site": "Ultimate Guitar", "state": "skipped", "found": ""},
        {"name": "Sheet", "site": "", "state": "skipped", "found": ""},
        {"name": "PDF", "site": "", "state": "skipped", "found": ""},
        {"name": "Lyrics", "site": "", "state": "skipped", "found": ""},
        {"name": "Extras", "site": "", "state": "skipped", "found": ""},
        {"name": "Songbooks", "site": "", "state": "skipped", "found": ""}], "at": 0, "count": "1 of 7"}


COOLING = "Waiting out Ultimate Guitar until 2026-10-28 14:00 UTC"
WAITS = (COOLING,
         "Ultimate Guitar turned us back (ug: 403: https://x). No more asks until 2026-10-28 14:00 UTC. "
         "Nothing marked not on the sites.",
         "no more asks of Ultimate Guitar this hour (60 spent); tonight's run does the rest")
# What each of them found, as the outcome words it.
WAITED = ("Waiting out Ultimate Guitar until 2026-10-28 14:00 UTC. The sheet waits.",
          "Ultimate Guitar turned us back. The sheet waits until 2026-10-28 14:00 UTC.",
          "No more asks of Ultimate Guitar this hour (60 spent). The sheet waits until tonight.")


def test_a_sheet_a_block_a_cooldown_or_a_spent_budget_stopped_stays_to_show_which_step_stopped():
    # Skipped for a wait, the sheet had something to do for the song: its step is drawn as one a site's error ended
    # is, never dropped as a step with nothing to do (the PDF of a song with no sheet), so a lookup that ends Not
    # fetched yet shows which step stopped, and what stopped it.
    for detail, found in zip(WAITS, WAITED, strict=True):
        waited = ended({"sheet": ("skipped", detail), "pdf": ("skipped", "no sheet yet"),
                        "songbooks": ("skipped", "in no songbook")})
        facts = SongFacts()
        line = job_line(waited, facts)
        assert line.text == "Not fetched yet"
        assert progress(waited, line, facts) == {"steps": [
            {"name": "Song", "site": "", "state": "done", "found": ""},
            {"name": "Match", "site": "Ultimate Guitar", "state": "done", "found": ""},
            {"name": "Sheet", "site": "", "state": "failed", "found": found},
            {"name": "PDF", "site": "", "state": "skipped", "found": ""},
            {"name": "Lyrics", "site": "", "state": "done", "found": ""},
            {"name": "Extras", "site": "", "state": "done", "found": ""},
            {"name": "Songbooks", "site": "", "state": "skipped", "found": ""}], "at": 2, "count": "3 of 7"}, detail
    # While it runs, the step keeps its place: over, and not done.
    running = lookup(stages={"song": ("done", ""), "match": ("done", "matched to muse/hysteria"),
                             "sheet": ("skipped", COOLING), "pdf": ("skipped", "no sheet yet"),
                             "lyrics": ("running", "")})
    assert Chip("Sheet", "failed", "", WAITED[0]) in steps(running)
    assert progress(running, job_line(running, None), None)["count"] == "5 of 7"
    # A block met while it asked names the site it asked.
    blocked = lookup(stages={"song": ("done", ""), "match": ("done", "matched to muse/hysteria")})
    blocked.heard({"stage": "sheet", "state": "running", "detail": SHEET_FROM["ug"]})
    blocked.heard({"stage": "sheet", "state": "skipped", "detail": WAITS[1]})
    assert steps(blocked)[2] == Chip("Sheet", "failed", "Ultimate Guitar", WAITED[1])


def test_a_request_that_runs_no_lookup_or_hasnt_run_has_no_steps_on_the_library_page():
    queued = lookup(state="queued")
    assert progress(queued, job_line(queued, None), None) == {}  # its line says its place in the queue
    cancelled = ended({name: ("skipped", "") for name, _ in STAGES}, state="cancelled")
    cancelled.state = "cancelled"
    assert progress(cancelled, job_line(cancelled, None), None) == {}
    add = Job(2, "Add Muse - Hysteria", "muse/hysteria", [Step("Adding to the book", ("add", "--", "Muse",
                                                                                       "Hysteria"),
                                                                 state="running")], state="running")
    assert progress(add, job_line(add, None), None) == {}
    read = Job(3, "x", LACUERDA_ARTIST + "caifanes", [Step("Reading LaCuerda's page for Caifanes", (
        "lacuerda", "--artist=caifanes"), state="running")], state="running")
    assert progress(read, job_line(read, None), None) == {}
    keep = Job(5, "Keep", "muse/hysteria", [Step("Fetching the version from UG", tuple(
        version_steps("Muse", "Hysteria", keep="3")[0][1]), state="running")], state="running",
               stages=[Stage(name, label) for name, label in KEEP_STAGES])
    assert progress(keep, job_line(keep, None), None) == {}


def test_a_request_draws_nothing_for_its_first_second_and_none_if_it_ends_within_it():
    running = lookup(stages=upto("song"))
    assert progress(running, job_line(running, None), None, now=START + timedelta(milliseconds=999)) == {}
    assert progress(running, job_line(running, None), None, now=START + timedelta(seconds=1))["count"] == "1 of 7"
    quick = ended({"sheet": ("skipped", COOLING)})
    quick.finished_at = START + timedelta(milliseconds=600)
    assert progress(quick, job_line(quick, SongFacts()), SongFacts()) == {}  # no bar, frozen or not
    quick.finished_at = START + timedelta(seconds=3)
    assert progress(quick, job_line(quick, SongFacts()), SongFacts())["count"] == "3 of 7"
    never = ended({}, state=INTERRUPTED)
    never.started_at = None  # interrupted while it waited
    assert progress(never, job_line(never, None), None) == {}


def test_a_lookup_waiting_for_the_book_says_so_of_its_step_in_hand():
    # A nightly run holds caracole's lock: the song stage runs, waiting for it (get.py's words, the very ones its line
    # says "Waiting for the book…" of), and the view says so beside the step in hand, Song, "1 of 7".
    held = "waiting for the book (pid 42: run); a fetch goes first at its next pause"
    waiting = lookup(stages=upto("song", song=("running", held)))
    assert job_line(waiting, None).text == "Waiting for the book…"
    shown = progress(waiting, job_line(waiting, None), None)
    assert (shown["at"], shown["count"], shown["waits"]) == (0, "1 of 7", True)
    assert list(shown) == ["steps", "at", "count", "waits"]  # right after the count
    assert shown["steps"][0]["state"] == "running"  # the step's own state: the page draws it waiting
    # The lock taken, the song stage goes on: no wait any more, nor once it moved on to the match.
    for stages in (upto("song"), upto("match")):
        going = lookup(stages=stages)
        assert "waits" not in progress(going, job_line(going, None), None)
    # A sheet from a YouTube video waits the same way (youtube_sheet.py's words).
    youtube = youtube_job(stages={"song": ("running", "waiting for the book (pid 9: run)")})
    assert progress(youtube, job_line(youtube, None), None)["waits"] is True
    # Nothing for its first second, as for any request, and never once it is over.
    assert progress(waiting, job_line(waiting, None), None, now=START + timedelta(milliseconds=500)) == {}


def test_a_request_of_other_commands_shows_its_job_steps_the_same_way():
    job = Job(2, "Pick muse/hysteria for Muse - Hysteria, and fetch it", "muse/hysteria", [
        Step("Noting your answer in overrides.toml", ("review", "--song=Muse - Hysteria", "--pick=muse/hysteria"),
             state="done"),
        Step("Fetching from UG", ("fetch", "--song=Muse - Hysteria"), state="running"),
        Step("Making the PDF", ("render", "--song=Muse - Hysteria"))], state="running")
    assert steps(job) == [Chip("Your pick", "done"), Chip("Sheet", "running"), Chip("PDF", "waiting")]
    # A command it doesn't name is shown by its label.
    other = Job(3, "x", "x", [Step("Reading LaCuerda's page for Caifanes", ("lacuerda", "--artist=caifanes"),
                                   state="running")], state="running")
    assert steps(other) == [Chip("LaCuerda", "running")]
    odd = Job(5, "x", "x", [Step("Doing something new", ("frobnicate",), state="running")], state="running")
    assert steps(odd) == [Chip("Doing something new", "running")]


# --- how a finished request ended, and what to do next -------------------------------------------------


def said(job, facts=None, *, song_id=None, songbook_page=None):
    return outcome(job, job_line(job, facts, songbook_page=songbook_page), facts, song_id=song_id)


def test_ready_opens_its_sheet():
    facts = SongFacts(sheet="Muse/Hysteria/sheet.html")
    assert said(ended({}), facts, song_id=1) == Outcome(
        "ready", "Ready", "", Action("Open", href="/Muse/Hysteria/sheet.html"))


def test_ready_says_what_waits_for_tonights_run_in_the_stages_words():
    lrclib = ended({"lyrics": ("failed", "LRCLIB failed (lrclib: 503: https://lrclib.net/api/get?x=1: HTTP 503); "
                                         "tried again tonight")})
    facts = SongFacts(sheet="Radiohead/Creep/sheet.html")
    assert said(lrclib, facts).reason == "LRCLIB answered 503. The lyrics wait until tonight."
    timeout = ended({"lyrics": ("failed", "LRCLIB failed (lrclib: https://lrclib.net/api/get: timed out); "
                                          "tried again tonight")})
    assert said(timeout, facts).reason == "LRCLIB failed. The lyrics wait until tonight."
    spent = ended({"gtptabs": ("skipped", "this fetch's 6 asks of gtptabs.com are spent; tonight's run does "
                                          "the rest")})
    assert said(spent, facts).reason == ("This fetch's 6 asks of gtptabs.com are spent. The Guitar Pro file "
                                         "waits until tonight.")
    blocked = ended({"ug": ("skipped", "Ultimate Guitar turned us back (ug: 429: https://x: HTTP 429). No more "
                                       "asks until 2026-10-22 18:00 UTC. Nothing marked not on the sites.")})
    assert said(blocked, facts).reason == ("Ultimate Guitar turned us back. Its other versions and tab "
                                           "wait until 2026-10-22 18:00 UTC.")
    cooling = ended({"lyrics": ("skipped", "Waiting out LRCLIB until 2026-10-22 18:00 UTC")})
    assert said(cooling, facts).reason == ("Waiting out LRCLIB until 2026-10-22 18:00 UTC. The lyrics wait.")
    # Nothing to say of a site turned off, or of a stage that had nothing to do.
    quiet = ended({"gtptabs": ("skipped", "gtptabs.com is off (caracole.toml)"),
                   "songbooks": ("skipped", "in no songbook")})
    assert said(quiet, facts).reason == ""


def test_needs_review_picks_the_match():
    facts = SongFacts(review=True, picker="review?song=7")
    job = ended({"sheet": ("skipped", "caracole isn't sure which Ultimate Guitar song this is")})
    assert said(job, facts, song_id=7) == Outcome(
        "review", "Needs your pick", "Not sure which UG song it is.",
        Action("Pick", href="/review?song=7"))
    # Without candidates to pick from, its line on the library page, where caracole review's answers are.
    bare = said(job, SongFacts(review=True), song_id=7)
    assert bare.action == Action("Open in the library", href="/#song=7")


SEARCH = Action("Search the index", href="/review?song=3")


def test_not_found_says_ultimate_guitar_has_no_chords_only_once_it_was_asked():
    # The offline index didn't match the name, and UG couldn't be asked: whether UG has chords, nobody knows.
    # What caracole search finds for it is the way on, the one next step.
    job = ended({"sheet": ("skipped", NOT_IN_INDEX)}, display="Horse The Band - Crippled By Pizza")
    unmatched = SongFacts(not_found=True, checked_now=True)
    assert said(job, unmatched, song_id=3) == Outcome(
        "missing", "Not on the sites", "Not in UG's index under this name.", SEARCH)
    # Its artist's UG page was read for it, with no chords there: UG was asked, and the index still lacks it.
    read = SongFacts(not_found=True, checked_now=True, asked_ug=True)
    assert said(job, read, song_id=3) == Outcome("missing", "Not on the sites", "UG has no chords for it.",
                                                 SEARCH)
    # A song the index matched, whose UG page had no sheet to keep: requested by name.
    matched = ended({"sheet": ("skipped", "UG has no sheet to keep")},
                    display="Horse The Band - Crippled By Pizza")
    assert said(matched, SongFacts(checked_now=True, asked_ug=True), song_id=3) == Outcome(
        "missing", "Not on the sites", "UG has no chords for it.",
        Action("Ask by name", href="/#q=Horse+The+Band+-+Crippled+By+Pizza"))
    # A fetch of commands that refused the song as not in the index (it failed): not asked either.
    fetch = Job(9, "Fetch Horse The Band - Crippled By Pizza", "horse-the-band/crippled-by-pizza",
                [Step("Fetching from UG", ("fetch", "--song=Horse The Band - Crippled By Pizza"),
                      state="failed")], fetching=True, state="failed")
    assert said(fetch, SongFacts(not_found=True), song_id=3).reason == (
        "Not in UG's index under this name.")


def test_not_found_with_something_elsewhere_gets_it_from_there():
    job = ended({"sheet": ("skipped", "UG has no sheet to keep")})
    gtp = SongFacts(checked_now=True, asked_ug=True, elsewhere=("gtptabs", "https://gtptabs.com/tabs/x.html"))
    assert said(job, gtp, song_id=3) == Outcome(
        "missing", "Not on the sites", "UG has no chords for it. gtptabs lists a page for it.",
        Action("Fetch from there", post="/lookup", fields=(("song", "3"), ("identity", "muse/hysteria"))))
    # A song the index didn't match: LaCuerda's sheet first, and what caracole search finds beside it.
    unmatched = ended({"sheet": ("skipped", NOT_IN_INDEX)})
    lc = SongFacts(not_found=True, checked_now=True,
                   elsewhere=("lacuerda", "https://acordes.lacuerda.net/estopa/como_camaron.shtml"))
    assert said(unmatched, lc, song_id=3) == Outcome(
        "missing", "Not on the sites", "Not in UG's index under this name. LaCuerda has a sheet.",
        Action("Fetch from there", post="/lookup", fields=(
            ("song", "3"), ("identity", "muse/hysteria"),
            ("lacuerda", "https://acordes.lacuerda.net/estopa/como_camaron.shtml"))),
        also=SEARCH)
    # A Guitar Pro file the lookup itself downloaded is in the library already: the song's line has it.
    got = ended({"sheet": ("skipped", ""), "gtptabs": ("done", "Guitar Pro file downloaded")})
    assert said(got, SongFacts(checked_now=True, asked_ug=True), song_id=3) == Outcome(
        "missing", "Not on the sites", "UG has no chords for it. Got a Guitar Pro file from "
                                "gtptabs.", Action("Open in the library", href="/#song=3"))
    assert said(got, SongFacts(not_found=True, checked_now=True), song_id=3) == Outcome(
        "missing", "Not on the sites", "Not in UG's index under this name. Got a Guitar "
                                "Pro file from gtptabs.", Action("Open in the library", href="/#song=3"),
        also=SEARCH)


def test_failed_and_not_fetched_yet_try_again():
    failed = ended({"song": ("failed", "overrides.toml can't be read: line 3")}, state="failed")
    assert said(failed) == Outcome("failed", "Failed", "overrides.toml can't be read: line 3.",
                                   Action("Try again", post="/jobs/again", fields=(("job", "4"),)))
    # Not fetched yet says why, from its stages: a wait is never a miss.
    waits = ended({"sheet": ("skipped", "no more asks of Ultimate Guitar this hour (60 spent); tonight's "
                                        "run does the rest"), "pdf": ("skipped", "no sheet yet")})
    assert said(waits, SongFacts()) == Outcome(
        "waiting", "Not fetched yet", "No more asks of Ultimate Guitar this hour (60 spent). The sheet waits "
                                      "until tonight.",
        Action("Try again", post="/jobs/again", fields=(("job", "4"),)))
    # A fetch of commands, which has no stages: its output says which.
    fetch = Job(9, "Fetch Radiohead - Creep", "radiohead/creep",
                [Step("Fetching from UG", ("fetch", "--song=Radiohead - Creep"), state="done")],
                fetching=True, state="done")
    assert said(fetch, SongFacts()).reason == ("UG not asked this time: waiting out a block, no asks left, or an "
                                               "error. The output says which.")


def test_a_failed_removal_tries_again_through_its_question_never_straight_to_remove():
    removal = Job(7, "Remove Radiohead - Creep", REMOVING + "radiohead/creep",
                  [Step(label, args, state="failed") for label, args in remove_steps("Radiohead - Creep")],
                  state="failed", song_id=12)
    # What goes is asked again (POST /remove without confirm: removal.plan_removal, as of now).
    assert said(removal).action == Action("Try again", post="/remove",
                                          fields=(("song", "12"), ("identity", "radiohead/creep")))
    unknown = Job(8, "Remove X - Y", REMOVING + "x/y", [Step("Removing", ("remove", "--yes"), state="failed")],
                  state="failed")
    assert said(unknown).action is None


def test_a_songbook_made_opens_it_and_a_deletion_and_a_removal_say_so():
    from caracole.web.songbooks import KEY

    made = Job(5, "Make the songbook Campfire", f"{KEY}songbook\x1fmake\x1f--\x1fCampfire", [
        Step("Making the songbook", ("songbook", "make", "--", "Campfire"), state="done")], state="done")
    page = "_songbooks/Campfire/songbook.html"
    assert said(made, songbook_page=page) == Outcome("ready", "Made", "",
                                                     Action("Open songbook", href="/" + page))
    gone = Job(6, 'Delete the songbook "test"', f"{KEY}songbook\x1fdelete\x1f--\x1ftest", [
        Step("Deleting the songbook", ("songbook", "delete", "--", "test"), state="done")], state="done")
    assert said(gone) == Outcome("removed", "Deleted")
    removal = Job(7, "Remove Radiohead - Creep", REMOVING + "radiohead/creep",
                  [Step(label, args, state="done") for label, args in remove_steps("Radiohead - Creep")], state="done")
    assert said(removal) == Outcome("removed", "Removed")


def test_an_add_and_a_lacuerda_read_say_their_line_as_a_word_and_a_sentence():
    add = Job(8, "Add Radiohead - Creep", "radiohead/creep", [Step("Adding to the book", ("add",), state="done")],
              state="done")
    assert said(add, SongFacts()) == Outcome("added", "Added", "Fetched tonight.")
    read = Job(9, "Read the page of Caifanes on LaCuerda", LACUERDA_ARTIST + "caifanes",
               [Step("Reading", ("lacuerda", "--artist=caifanes"), state="done",
                     output=["Not read: LaCuerda failed (lacuerda: 503: x). Try again later."])],
               state="done")
    assert said(read) == Outcome("waiting", "Not read", "LaCuerda failed.",
                                 Action("Try again", post="/jobs/again", fields=(("job", "9"),)))


# --- what the library's indexes have elsewhere, for a song not found ---------------------------------------


NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)


def test_elsewhere_is_a_lacuerda_sheet_or_a_gtptabs_page_the_local_indexes_list(conn, cfg):
    song = add_song(conn, "Estopa", "Como Camarón")
    # A lookup that asked neither: LaCuerda didn't look like the song's, gtptabs.com failed.
    job = ended({"sheet": ("skipped", ""), "lacuerda": ("skipped", "not for LaCuerda: not Spanish"),
                 "gtptabs": ("failed", "gtptabs.com failed (gtptabs: 500: x); tried again tonight")},
                display="Estopa - Como Camarón")
    assert elsewhere(conn, cfg, song, job, NOW) is None
    conn.execute("INSERT INTO gtptabs_index (path, artist_path, artist_key, title_key, base_key, sitemap) VALUES "
                 "('tabs/e/estopa/como-camaron.html', 'tabs/e/estopa.html', 'estopa', 'como-camaron', 'como-camaron', "
                 "'s1')")
    page = elsewhere(conn, cfg, song, job, NOW)
    assert page is not None and page[0] == "gtptabs" and page[1].endswith("/tabs/e/estopa/como-camaron.html")
    # LaCuerda's sheet comes first: chords, where gtptabs.com has a Guitar Pro file.
    conn.execute("INSERT INTO lacuerda_index (path, artist_slug, artist, artist_key, title, title_key, versions, "
                 "acordes, page) VALUES ('estopa/como_camaron', 'estopa', 'Estopa', 'estopa', 'Como Camarón', "
                 "'como-camaron', 'lcd', 2, 'e')")
    assert elsewhere(conn, cfg, song, job, NOW) == (
        "lacuerda", "https://acordes.lacuerda.net/estopa/como_camaron-2.shtml")
    # A site the lookup asked already answered: no.
    asked = ended({"sheet": ("skipped", ""), "lacuerda": ("done", "not on LaCuerda"),
                   "gtptabs": ("done", "no file there")}, display="Estopa - Como Camarón")
    assert elsewhere(conn, cfg, song, asked, NOW) is None
    # gtptabs.com looked up for the song this month: not again.
    from caracole.db import kv_set
    from caracole.gtptabs_fetch import CHECKED_PREFIX

    conn.execute("DELETE FROM lacuerda_index")
    kv_set(conn, f"{CHECKED_PREFIX}{song.id}", "2026-10-20T00:00:00Z")
    assert elsewhere(conn, cfg, song, job, NOW) is None
    update_song(conn, song.id, status="ignored")
    assert elsewhere(conn, cfg, song, job, NOW) is None


def test_elsewhere_offers_no_site_the_new_lookup_would_skip_again(conn, cfg):
    from caracole.health import record_block

    song = add_song(conn, "Estopa", "Como Camarón")
    conn.execute("INSERT INTO gtptabs_index (path, artist_path, artist_key, title_key, base_key, sitemap) VALUES "
                 "('tabs/e/estopa/como-camaron.html', 'tabs/e/estopa.html', 'estopa', 'como-camaron', 'como-camaron', "
                 "'s1')")
    conn.execute("INSERT INTO lacuerda_index (path, artist_slug, artist, artist_key, title, title_key, versions, "
                 "acordes, page) VALUES ('estopa/como_camaron', 'estopa', 'Estopa', 'estopa', 'Como Camarón', "
                 "'como-camaron', 'lcd', 1, 'e')")
    job = ended({"sheet": ("skipped", ""), "lacuerda": ("skipped", ""), "gtptabs": ("skipped", "")},
                display="Estopa - Como Camarón")
    assert elsewhere(conn, cfg, song, job, NOW)[0] == "lacuerda"
    # LaCuerda asked about the song this month: a lookup skips it until the month is over.
    update_song(conn, song.id, lacuerda_checked_at="2026-10-01T00:00:00Z")
    song = get_song(conn, song.id)
    assert elsewhere(conn, cfg, song, job, NOW)[0] == "gtptabs"
    update_song(conn, song.id, lacuerda_checked_at="2026-09-01T00:00:00Z")
    song = get_song(conn, song.id)
    assert elsewhere(conn, cfg, song, job, NOW)[0] == "lacuerda"
    # A site that cools down after a block: the lookup would skip it again.
    record_block(conn, "lacuerda", NOW, "lacuerda: 403")
    assert elsewhere(conn, cfg, song, job, NOW)[0] == "gtptabs"
    record_block(conn, "gtptabs", NOW, "gtptabs: 403")
    assert elsewhere(conn, cfg, song, job, NOW) is None
    # A stage skipped for a spent budget or a block: not offered either, whatever the cooldowns say now.
    conn.execute("DELETE FROM kv WHERE key LIKE 'provider:%'")
    spent = ended({"sheet": ("skipped", ""),
                   "lacuerda": ("skipped", "this fetch's 6 asks of LaCuerda are spent; tonight's run does the rest"),
                   "gtptabs": ("skipped", "gtptabs.com turned us back (gtptabs: 429: x). No more asks "
                                          "until 2026-10-22 18:00 UTC.")}, display="Estopa - Como Camarón")
    assert elsewhere(conn, cfg, song, spent, NOW) is None


# --- a sheet from a YouTube video ------------------------------------------------------------------------


def youtube_job(state="running", stages=None):
    from caracole.web.jobs import YOUTUBE_SHEET, youtube_sheet_steps
    from caracole.youtube_sheet import STAGES as SHEET_STAGES

    said = stages or {}
    made = [Step(label, tuple(args)) for label, args in
            youtube_sheet_steps("Nick Cani - Vikingos veganos", "https://www.youtube.com/watch?v=lzN7Thn3FV4")]
    if state != "running":
        made[0].state = "done" if state == "done" else "failed"
    return Job(6, "YouTube sheet", YOUTUBE_SHEET + "nick cani/vikingos veganos", made, state=state,
               display="Nick Cani - Vikingos veganos", **times(state),
               stages=[Stage(name, label, *said.get(name, ("waiting", ""))) for name, label in SHEET_STAGES])


EVERY = {"song": ("done", "added to wanted.txt, line 16"), "audio": ("done", "downloaded Vikingos veganos"),
         "lyrics": ("done", "found, timed"), "vocals": ("skipped", "not transcribed: its lyrics are found"),
         "words": ("skipped", "no vocals"), "chords": ("done", "chords over the lyrics"),
         "pdf": ("done", "made"), "pages": ("done", "")}
SHEET = SongFacts(sheet="Nick%20Cani/Vikingos%20veganos/sheet%20%28auto%29.html")


def test_a_sheet_from_youtube_shows_its_steps_audio_from_youtube():
    job = youtube_job(stages={"song": ("done", ""), "audio": ("done", "downloaded Vikingos veganos"),
                              "lyrics": ("running", "")})
    assert steps(job) == [Chip("Song", "done"), Chip("Audio", "done", "YouTube", "downloaded Vikingos veganos"),
                          Chip("Lyrics", "running"), Chip("Words", "waiting"), Chip("Chords", "waiting"),
                          Chip("PDF", "waiting")]
    line = job_line(job, None)
    assert progress(job, line, None) == {"steps": [c.as_json() for c in steps(job)], "at": 2, "count": "3 of 6"}
    ready = youtube_job("done", EVERY)
    assert progress(ready, job_line(ready, SHEET), SHEET) == {}  # Ready: its steps fold away
    waited = youtube_job("done", EVERY | {"audio": ("skipped", "YouTube turned us back; waiting until "
                                                               "2026-10-30 20:00 UTC"),
                                          "chords": ("skipped", "no audio")})
    # The audio a block stopped is the step that stopped it, drawn failed; one it left with nothing to do keeps its
    # place, skipped. What stopped it is found as its stage said it.
    assert progress(waited, job_line(waited, SHEET), SHEET)["steps"] == [
        {"name": "Song", "site": "", "state": "done", "found": "added to wanted.txt, line 16"},
        {"name": "Audio", "site": "YouTube", "state": "failed",
         "found": "YouTube turned us back; waiting until 2026-10-30 20:00 UTC"},
        {"name": "Lyrics", "site": "", "state": "done", "found": "found, timed"},
        {"name": "Words", "site": "", "state": "skipped", "found": ""},
        {"name": "Chords", "site": "", "state": "skipped", "found": ""},
        {"name": "PDF", "site": "", "state": "done", "found": "made"}]
    # Cut off as it took the audio: failed, and nothing found, what it said while it ran being no finding.
    cut = youtube_job(INTERRUPTED, EVERY | {"audio": (INTERRUPTED, "taking the audio"), "lyrics": ("skipped", ""),
                                            "chords": ("skipped", ""), "pdf": ("skipped", "")})
    assert steps(cut)[1] == Chip("Audio", "failed", "YouTube")


def test_a_sheet_from_youtube_says_what_it_holds_or_what_stopped_it():
    ready = youtube_job("done", EVERY)
    assert outcome(ready, job_line(ready, SHEET), SHEET) == Outcome(
        "ready", "Ready", "Chords over the lyrics.", Action("Open", href="/" + SHEET.sheet))
    no_words = youtube_job("done", EVERY | {"lyrics": ("failed", "no lyrics yet (LRCLIB unavailable); tried again "
                                                                "tonight"),
                                            "chords": ("done", "chords only, no lyrics")})
    assert outcome(no_words, job_line(no_words, SHEET), SHEET).reason == (
        "No lyrics yet (LRCLIB unavailable); tried again tonight.")
    waited = youtube_job("done", EVERY | {"audio": ("skipped", "YouTube turned us back; waiting until "
                                                               "2026-10-30 20:00 UTC"),
                                          "chords": ("skipped", "no audio"), "pdf": ("skipped", "no sheet")})
    said = outcome(waited, job_line(waited, None), None)
    assert said == Outcome("waiting", "Not made yet", "YouTube turned us back; waiting until 2026-10-30 20:00 UTC.",
                           Action("Try again", post="/jobs/again", fields=(("job", "6"),)))
    failed = youtube_job("failed", EVERY | {"chords": ("failed", "auto-chords can't read the audio")})
    assert outcome(failed, job_line(failed, None), None).word == "Failed"


def test_a_youtube_sheets_steps_are_song_audio_lyrics_words_chords_pdf():
    # One Words step for the vocals and words stages, between Lyrics and Chords.
    job = youtube_job(stages=EVERY | {"vocals": ("done", "sung from 9.3 s"), "words": ("done", "212 words")})
    assert [c.name for c in steps(job)] == ["Song", "Audio", "Lyrics", "Words", "Chords", "PDF"]
    assert steps(job)[3] == Chip("Words", "done", "", "sung from 9.3 s \u00b7 212 words")
    # Skipped, it keeps its place; running vocals is the Words step in hand.
    assert steps(youtube_job(stages=EVERY))[3].state == "skipped"
    running = youtube_job(stages={"song": ("done", ""), "audio": ("done", ""), "lyrics": ("done", "none"),
                                  "vocals": ("running", "2 of ~12 min")})
    shown = progress(running, job_line(running, None), None)
    assert shown["at"] == 3 and shown["count"] == "4 of 6" and shown["steps"][3]["state"] == "running"


def test_a_sheet_whose_words_failed_is_ready_and_says_why():
    job = youtube_job("done", EVERY | {"vocals": ("done", "sung from 9.3 s"),
                                       "words": ("failed", "Whisper can't read the audio"),
                                       "chords": ("done", HOLDS["none"])})
    assert steps(job)[3].state == "failed"
    assert outcome(job, job_line(job, SHEET), SHEET) == Outcome(
        "ready", "Ready", "Chords only, no lyrics: the words couldn't be heard here (Whisper can't read the audio).",
        Action("Open", href="/" + SHEET.sheet))


# --- a sheet from an audio file you gave ------------------------------------------------------------------------


def audio_job(state="running", stages=None):
    from caracole.audio_sheet import STAGES as AUDIO_STAGES
    from caracole.web.jobs import AUDIO_SHEET, audio_sheet_steps

    said = stages or {}
    made = [Step(label, tuple(args)) for label, args in
            audio_sheet_steps("Nick Cani - Vikingos veganos", "0123456789abcdef")]
    if state != "running":
        made[0].state = "done" if state == "done" else "failed"
    return Job(7, "Sheet from an audio file", AUDIO_SHEET + "nick cani/vikingos veganos", made, state=state,
               display="Nick Cani - Vikingos veganos", **times(state),
               stages=[Stage(name, label, *said.get(name, ("waiting", ""))) for name, label in AUDIO_STAGES])


def test_an_audio_sheets_audio_step_names_no_site():
    from caracole.web.outcome import AUDIO_STEPS

    assert AUDIO_STEPS == (("Song", ("song",)), ("Audio", ("audio",)), ("Lyrics", ("lyrics",)),
                           ("Words", ("vocals", "words")), ("Chords", ("chords",)), ("PDF", ("pdf",)))
    kept = EVERY | {"audio": ("done", "kept as its audio: MP3, 3:18")}
    job = audio_job(stages={"song": ("done", ""), "audio": kept["audio"], "lyrics": ("running", "")})
    assert steps(job) == [Chip("Song", "done"), Chip("Audio", "done", "", "kept as its audio: MP3, 3:18"),
                          Chip("Lyrics", "running"), Chip("Words", "waiting"), Chip("Chords", "waiting"),
                          Chip("PDF", "waiting")]
    assert progress(job, job_line(job, None), None)["count"] == "3 of 6"
    ready = audio_job("done", kept)
    assert job_line(ready, SHEET).text == "Ready" and progress(ready, job_line(ready, SHEET), SHEET) == {}
    assert outcome(ready, job_line(ready, SHEET), SHEET).reason == "Chords over the lyrics."
    heard = audio_job("done", kept | {"lyrics": ("done", "LRCLIB has none"), "vocals": ("done", "sung from 9.3 s"),
                                      "words": ("failed", "the GPU failed"), "chords": ("done", HOLDS["none"])})
    assert outcome(heard, job_line(heard, SHEET), SHEET).reason == (
        "Chords only, no lyrics: the words couldn't be heard here (the GPU failed).")
    # A sheet of an earlier source is none of its doing: Ready only once its chords are made.
    refused = audio_job("failed", {"song": ("failed", "Nick Cani - Vikingos veganos already has a sheet")})
    assert job_line(refused, SHEET).text != "Ready"
    gone = audio_job("done", {"song": ("done", ""), "audio": ("failed", "that upload is gone")})
    assert job_line(gone, SHEET).text == "Not made yet"
    assert outcome(gone, job_line(gone, SHEET), SHEET).reason == "That upload is gone."


def test_a_sheet_whose_vocals_failed_says_why_with_the_stages_own_words():
    why = "the separator can't run here (no GPU adapter)"
    job = youtube_job("done", EVERY | {"vocals": ("failed", why), "words": ("skipped", "no vocals"),
                                       "chords": ("done", HOLDS["none"])})
    assert steps(job)[3] == Chip("Words", "failed", "", why)
    assert outcome(job, job_line(job, SHEET), SHEET).reason == (
        f"Chords only, no lyrics: the words couldn't be heard here ({why}).")


def test_a_sheet_over_nothing_sung_is_ready_chords_only():
    job = youtube_job("done", EVERY | {"vocals": ("done", "sung 6.2 s"),
                                       "words": ("done", "nothing sung was heard (6.2 s sung)"),
                                       "chords": ("done", HOLDS["silent"])})
    assert outcome(job, job_line(job, SHEET), SHEET).reason == "Chords only: nothing sung was heard."


def test_a_transcription_the_owner_said_isnt_sung_is_ready_in_their_words():
    # caracole transcribe --none: the Journal's Ready says it is the owner's word, from the chords stage's words;
    # a sheet caracole heard nothing in keeps its own (above).
    job = transcribe_job("done", TRANSCRIBED | {"vocals": ("skipped", "you said nothing is sung"),
                                                "words": ("done", "transcript dropped"),
                                                "chords": ("done", HOLDS["said"])})
    assert outcome(job, job_line(job, SHEET), SHEET).reason == "Chords only: you said it isn't sung."


# --- a song's lyrics transcribed from its audio ---------------------------------------------------------------


def transcribe_job(state="running", stages=None):
    from caracole.transcribe_job import STAGES as TRANSCRIBE_STAGES
    from caracole.web.jobs import TRANSCRIBE, transcribe_steps

    said = stages or {}
    made = [Step(label, tuple(args)) for label, args in transcribe_steps("Nick Cani - Vikingos veganos")]
    if state != "running":
        made[0].state = "done" if state == "done" else "failed"
    return Job(9, "Lyrics from the audio: Nick Cani - Vikingos veganos", TRANSCRIBE + "nick cani/vikingos veganos",
               made, state=state, display="Nick Cani - Vikingos veganos", **times(state),
               stages=[Stage(name, label, *said.get(name, ("waiting", ""))) for name, label in TRANSCRIBE_STAGES])


TRANSCRIBED = {"song": ("done", "in the book"), "vocals": ("done", "sung from 9.3 s, 4 stretches"),
               "words": ("done", "212 words in 31 lines (es), 3 dropped"),
               "chords": ("done", "chords over the transcribed lyrics"), "pdf": ("done", "made"),
               "pages": ("done", "_todo.md and index.html rewritten")}


def test_a_transcription_shows_its_steps_and_says_what_it_holds_or_what_stopped_it():
    from caracole.web.outcome import TRANSCRIBE_STEPS, lists_steps

    assert TRANSCRIBE_STEPS == (("Song", ("song",)), ("Vocals", ("vocals",)), ("Words", ("words",)),
                                ("Chords", ("chords",)), ("PDF", ("pdf",)))
    job = transcribe_job(stages={"song": ("done", "in the book"), "vocals": ("done", "sung from 9.3 s, 4 stretches"),
                                 "words": ("running", "")})
    # Its steps, each by what it does, none naming a site; the pages are the line's, as a lookup's are.
    assert steps(job) == [Chip("Song", "done", "", "in the book"),
                          Chip("Vocals", "done", "", "sung from 9.3 s, 4 stretches"),
                          Chip("Words", "running"), Chip("Chords", "waiting"), Chip("PDF", "waiting")]
    line = job_line(job, SongFacts())
    assert line.text == "Transcribing the lyrics…"
    assert progress(job, line, SongFacts()) == {"steps": [c.as_json() for c in steps(job)], "at": 2,
                                                "count": "3 of 5"}
    waiting = transcribe_job(stages={"song": ("done", ""), "vocals": ("running", "waiting for the book (pid 9: x)")})
    assert progress(waiting, job_line(waiting, SongFacts()), SongFacts())["waits"] is True
    assert "doing" not in progress(waiting, job_line(waiting, SongFacts()), SongFacts())
    # A long stage's words while it runs (status.LONG_STAGES), for the bar, after the step's place: "doing".
    hearing = transcribe_job(stages={"song": ("done", "in the book"),
                                     "vocals": ("done", "sung from 9.3 s, 4 stretches"),
                                     "words": ("running", "1:20 of 3:45")})
    assert list(progress(hearing, job_line(hearing, SongFacts()), SongFacts()).items())[1:] == [
        ("at", 2), ("count", "3 of 5"), ("doing", "1:20 of 3:45")]
    assert steps(hearing)[2] == Chip("Words", "running")  # no finding: what it does is the bar's
    lyrics = youtube_job(stages={"song": ("done", ""), "audio": ("done", "downloaded"), "lyrics": ("running", "x")})
    assert "doing" not in progress(lyrics, job_line(lyrics, None), None)
    # Ready: what the sheet holds now, its steps folded away; listed in the Requests tab as it left them.
    ready = transcribe_job("done", TRANSCRIBED)
    assert outcome(ready, job_line(ready, SHEET), SHEET) == Outcome(
        "ready", "Ready", "Chords over the transcribed lyrics.", Action("Open", href="/" + SHEET.sheet))
    assert progress(ready, job_line(ready, SHEET), SHEET) == {} and lists_steps(ready)
    assert [c.state for c in steps(ready)] == ["done"] * 5
    # Failed: the stage that stopped it, in its words (as a sheet from YouTube's), drawn failed; Try again.
    deaf = transcribe_job("failed", TRANSCRIBED | {"words": ("failed", "no singing heard"),
                                                   "chords": ("skipped", "no transcript"),
                                                   "pdf": ("skipped", "no sheet")})
    assert outcome(deaf, job_line(deaf, SHEET), SHEET) == Outcome(
        "failed", "Failed", "no singing heard.", Action("Try again", post="/jobs/again", fields=(("job", "9"),)))
    assert [(c.name, c.state, c.found) for c in steps(deaf)][2:] == [
        ("Words", "failed", "no singing heard"), ("Chords", "skipped", ""), ("PDF", "skipped", "")]
    gpu = transcribe_job("failed", TRANSCRIBED | {"vocals": ("failed", "the GPU failed: CUDA out of memory"),
                                                  "words": ("skipped", "no vocals"),
                                                  "chords": ("skipped", "no transcript"),
                                                  "pdf": ("skipped", "no sheet")})
    assert outcome(gpu, job_line(gpu, SHEET), SHEET).reason == "the GPU failed: CUDA out of memory."
    # Over with no new sheet (its chords skipped): Not made yet, and the stage that stopped it.
    unmade = transcribe_job("done", TRANSCRIBED | {"words": ("skipped", "no vocals"),
                                                   "chords": ("skipped", "no transcript")})
    assert outcome(unmade, job_line(unmade, SHEET), SHEET) == Outcome(
        "waiting", "Not made yet", "No vocals.", Action("Try again", post="/jobs/again", fields=(("job", "9"),)))
    # A sheet from YouTube says the same of its own stages, as before.
    assert outcome(youtube_job("done", EVERY), job_line(youtube_job("done", EVERY), SHEET), SHEET).reason == (
        "Chords over the lyrics.")


# --- a song's lyrics searched under a name, and a record of it picked --------------------------------------------

YEREN = "孟维来 - 野人"


def lyrics_pick_job(state="running", stages=None, *, record="lrclib:28399373", output=()):
    from caracole.lyrics_pick import STAGES as PICK_STAGES
    from caracole.web.jobs import LYRICS_PICK, lyrics_pick_steps

    said = stages or {}
    made = [Step(label, tuple(args)) for label, args in lyrics_pick_steps(f"{YEREN} (官方MV)", record)]
    if state != "running":
        made[0].state = "done" if state == "done" else "failed"
    made[0].output = list(output)
    return Job(10, f"Lyrics for {YEREN} (官方MV)", LYRICS_PICK + "孟维来/野人", made, state=state,
               display=f"{YEREN} (官方MV)", **times(state),
               stages=[Stage(name, label, *said.get(name, ("waiting", ""))) for name, label in PICK_STAGES])


TAKEN = {"song": ("done", "in the book; its last search's lrclib:28399373"),
         "lyrics": ("done", f"timed lyrics from LRCLIB: {YEREN} (野人, 3:46); in place of AZLyrics' plain lyrics"),
         "chords": ("done", "chords over the lyrics"), "pdf": ("done", "made"), "pages": ("done", "")}
AGAIN = Action("Try again", post="/jobs/again", fields=(("job", "10"),))


def test_a_lyrics_picks_steps_are_song_lyrics_chords_pdf():
    from caracole.web.outcome import LYRICS_PICK_STEPS, lists_steps

    assert LYRICS_PICK_STEPS == (("Song", ("song",)), ("Lyrics", ("lyrics",)), ("Chords", ("chords",)),
                                 ("PDF", ("pdf",)))
    running = lyrics_pick_job(stages={"song": TAKEN["song"], "lyrics": ("running", "")})
    # Its Lyrics step names the picked record's site in full, from the start; the pages are the line's.
    assert steps(running) == [Chip("Song", "done", "", TAKEN["song"][1]), Chip("Lyrics", "running", "LRCLIB"),
                              Chip("Chords", "waiting"), Chip("PDF", "waiting")]
    assert progress(running, job_line(running, SongFacts()), SongFacts()) == {
        "steps": [c.as_json() for c in steps(running)], "at": 1, "count": "2 of 4"}
    made = lyrics_pick_job("done", TAKEN, record="megalobiz:8")
    assert steps(made)[1] == Chip("Lyrics", "done", "Megalobiz", TAKEN["lyrics"][1])  # what it took, in its words
    assert lists_steps(made) and progress(made, job_line(made, SHEET), SHEET) == {}  # Ready: folded away
    assert steps(lyrics_pick_job(stages={}, record="azlyrics:a/b"))[1].site == "AZLyrics"
    # A site's error is the step that stopped it, found in the stage's words; a wait leaves it skipped.
    failed = lyrics_pick_job("done", TAKEN | {"lyrics": ("failed", "LRCLIB failed (lrclib: 503: x); nothing kept"),
                                              "chords": ("skipped", "no new lyrics"),
                                              "pdf": ("skipped", "no new lyrics")})
    assert steps(failed)[1] == Chip("Lyrics", "failed", "LRCLIB", "LRCLIB failed (lrclib: 503: x); nothing kept")
    assert progress(failed, job_line(failed, SHEET), SHEET)["count"] == "2 of 4"


def test_its_ready_says_what_it_took_and_what_it_replaced():
    ready = lyrics_pick_job("done", TAKEN)
    assert outcome(ready, job_line(ready, SHEET), SHEET) == Outcome(
        "ready", "Ready", f"Timed lyrics from LRCLIB: {YEREN} (野人, 3:46); in place of AZLyrics' plain lyrics.",
        Action("Open", href="/" + SHEET.sheet))
    took = f"Timed lyrics from LRCLIB: {YEREN} (野人, 3:46); in place of AZLyrics' plain lyrics."
    # Its chords skipped: what became of the sheet follows what it took, a sentence of its own.
    alone = lyrics_pick_job("done", TAKEN | {"chords": ("skipped", "no audio to make an auto sheet from"),
                                             "pdf": ("skipped", "no sheet")})
    assert outcome(alone, job_line(alone, SongFacts()), SongFacts()) == Outcome(
        "ready", "Ready", f"{took} No audio to make an auto sheet from.")
    absent = lyrics_pick_job("done", TAKEN | {"chords": ("skipped", "auto-chords isn't here (no torch); tonight's run "
                                                                   "makes it again")})
    assert outcome(absent, job_line(absent, SHEET), SHEET) == Outcome(
        "ready", "Ready", f"{took} Auto-chords isn't here (no torch); tonight's run makes it again.",
        Action("Open", href="/" + SHEET.sheet))
    human = lyrics_pick_job("done", TAKEN | {
        "chords": ("skipped", "its sheet is a site's: no auto sheet to make again")})
    assert outcome(human, job_line(human, SHEET), SHEET).reason == (
        f"{took} Its sheet is a site's: no auto sheet to make again.")
    # Chords that ran are their step's to say; "no new lyrics" is never said after lyrics kept.
    assert outcome(ready, job_line(ready, SHEET), SHEET).reason == took
    # Kept, then the server stopped: the lyrics said kept before the stop.
    cut = lyrics_pick_job(INTERRUPTED, TAKEN | {"chords": (INTERRUPTED, "finding the beats"),
                                                "pdf": ("skipped", ""), "pages": ("skipped", "")})
    assert outcome(cut, job_line(cut, SHEET), SHEET) == Outcome(
        "waiting", "Interrupted", "Lyrics kept. The server stopped mid-way. Try again to finish.", AGAIN)
    early = lyrics_pick_job(INTERRUPTED, {"song": ("done", ""), "lyrics": (INTERRUPTED, "")})
    assert outcome(early, job_line(early, SHEET), SHEET).reason == "The server stopped mid-way. Try again to finish."
    # Kept, then failed after: Failed, the lyrics said kept, Try again.
    after = lyrics_pick_job("failed", TAKEN | {"chords": ("failed", "auto-chords can't read the audio"),
                                               "pdf": ("skipped", "no new lyrics")},
                            output=["Lyrics kept; the job failed after: auto-chords can't read the audio."])
    assert outcome(after, job_line(after, SHEET), SHEET) == Outcome(
        "failed", "Failed", "Lyrics kept; the job failed after: auto-chords can't read the audio.", AGAIN)


def test_a_lyrics_pick_that_kept_none_says_why_and_tries_again():
    none = {"chords": ("skipped", "no new lyrics"), "pdf": ("skipped", "no new lyrics")}
    for state, said, reason in (
            ("skipped", "waiting out LRCLIB until 27 Nov 03:00; nothing kept",
             "Waiting out LRCLIB until 27 Nov 03:00; nothing kept."),
            ("failed", "LRCLIB failed (lrclib: 503: x); nothing kept", "LRCLIB failed (lrclib: 503: x); nothing kept."),
            ("skipped", "no more asks of LRCLIB this hour (60 spent); nothing kept",
             "No more asks of LRCLIB this hour (60 spent); nothing kept.")):
        job = lyrics_pick_job("done", TAKEN | {"lyrics": (state, said)} | none)
        assert outcome(job, job_line(job, SHEET), SHEET) == Outcome("waiting", "Not kept", reason, AGAIN)
    # A record gone answers the same when asked again: missing, and no Try again (the card's pick another is next).
    gone = lyrics_pick_job("done", TAKEN | {"lyrics": ("skipped", "LRCLIB's record 28399373 has no lyrics now; "
                                                                  "nothing kept")} | none)
    assert outcome(gone, job_line(gone, SHEET), SHEET) == Outcome(
        "missing", "Not kept", "LRCLIB's record 28399373 has no lyrics now; nothing kept.")
    refused = lyrics_pick_job("failed", {"song": ("failed", "“lrclib:1” isn't among the records its last search "
                                                            "listed")})
    assert outcome(refused, job_line(refused, SHEET), SHEET) == Outcome(
        "failed", "Failed", "“lrclib:1” isn't among the records its last search listed.", AGAIN)


def test_a_lyrics_search_says_its_last_lines_words_as_a_site_reads():
    from caracole.web.jobs import LYRICS_SEARCH, lyrics_search_steps

    def search(said):
        made = [Step(label, tuple(args), state="done", output=[said])
                for label, args in lyrics_search_steps(f"{YEREN} (官方MV)", YEREN)]
        return Job(11, f"Lyrics under “{YEREN}”", LYRICS_SEARCH + "孟维来/野人", made, state="done", **times("done"))

    found = search(f"Searched: LRCLIB lists 2 records for “{YEREN}”.")
    assert outcome(found, job_line(found, None), None) == Outcome(
        "added", "Searched", f"LRCLIB lists 2 records for “{YEREN}”.")
    nothing = search(f"Nothing found: LRCLIB lists nothing for “{YEREN}”.")
    assert outcome(nothing, job_line(nothing, None), None) == Outcome(
        "missing", "Nothing found", f"LRCLIB lists nothing for “{YEREN}”.")
    waited = search("Not searched: waiting out LRCLIB until 27 Nov 03:00; try again later.")
    assert outcome(waited, job_line(waited, None), None) == Outcome(
        "waiting", "Not searched", "waiting out LRCLIB until 27 Nov 03:00.",  # its words, as LaCuerda's search's
        Action("Try again", post="/jobs/again", fields=(("job", "11"),)))
    assert steps(found) == [Chip("Looking for lyrics under “孟维来 - 野人”", "done")]  # no stages: its command


def test_a_lyrics_clear_is_cleared_or_nothing_to_clear_in_the_commands_words():
    from caracole.web.jobs import LYRICS_CLEAR, lyrics_clear_steps

    def clear(state, said):
        made = [Step(label, tuple(args), state=state, output=[said])
                for label, args in lyrics_clear_steps(f"{YEREN} (官方MV)")]
        return Job(12, f"Clear the lyrics record: {YEREN} (官方MV)", LYRICS_CLEAR + "孟维来/野人", made, state=state,
                   **times(state))

    done = clear("done", f"Cleared the record you picked for {YEREN} (官方MV) (lrclib 28399373); every lyrics site "
                         "is asked again under its own name, tonight or at a lookup.")
    assert outcome(done, job_line(done, None), None) == Outcome(
        "added", "Cleared", f"The record you picked for {YEREN} (官方MV) (lrclib 28399373); every lyrics site is "
                            "asked again under its own name, tonight or at a lookup.")
    refused = clear("failed", f"error: {YEREN} (官方MV) has no lyrics record picked under [lyrics]: nothing to "
                              "clear.")
    assert outcome(refused, job_line(refused, None), None) == Outcome(
        "added", "Nothing to clear", "No lyrics record is picked.")
    assert steps(done) == [Chip("Clearing the lyrics record you picked", "done")]


def test_a_sync_whose_indexes_were_of_another_schema_says_so_after_what_it_shared():
    """A sync between databases of different schemas skips its index stage before any download (I4): its outcome
    says why in one sentence after what it did, as the stage said it; an index stage skipped for nothing newer, or
    left out by the owner, says nothing."""
    from caracole.commands.peer import INDEXES_LEFT_OUT, NO_INDEX
    from caracole.web.sync_routes import INDEXES_NEWER, INDEXES_OLDER

    from test_web_sync import peer_job

    took = [("song/oasis/wonderwall", "taken", ""), ("song/muse/hysteria", "given", "")]
    left = took + [("song/radiohead/creep", "left", "skipped, as chosen")]
    done = {"compare": ("done", "4 differences"), "take": ("done", "took 1"), "give": ("done", "gave 1"),
            "agree": ("done", "12 units the books agree on")}

    def said(index, units=took):
        job = peer_job("sync", "done", dict(done, index=index), units=units)
        over = outcome(job, job_line(job, None))
        return over.tone, over.word, over.reason

    assert said(("skipped", INDEXES_NEWER)) == (
        "ready", "Shared", f"1 change taken, 1 change given. {INDEXES_NEWER}.")
    assert said(("skipped", INDEXES_OLDER), left) == (
        "waiting", "Shared", f"1 change taken, 1 change given. 1 change left as it was. {INDEXES_OLDER}.")
    assert said(("skipped", INDEXES_NEWER), [])[2] == f"Nothing changed in either book. {INDEXES_NEWER}."
    for ordinary in (NO_INDEX, INDEXES_LEFT_OUT):
        assert said(("skipped", ordinary)) == ("ready", "Shared", "1 change taken, 1 change given.")


def test_a_removal_left_because_its_song_is_here_is_no_change_left_in_the_journal_or_the_summary():
    """A sync that met the other side's removal of a song this side keeps, the song's own difference left unsettled
    (``peer_sync.SONG_HERE``): that is the sync's answer, the song kept, never a change left. Its line, outcome and
    view read as the same sync without it; a real leftover beside it is counted alone."""
    from caracole.peer_sync import SONG_HERE
    from caracole.web.jobs_routes import peer_outcome

    from test_web_sync import peer_job

    answered = ("removed/oasis/wonderwall", "left", SONG_HERE)
    took = [("song/a/one", "taken", ""), ("song/b/two", "taken", ""), ("song/c/three", "taken", "")]
    done = {"compare": ("done", "4 differences"), "take": ("done", "took 3"), "give": ("done", "gave 0"),
            "agree": ("done", "12 units the books agree on")}

    def said(units):
        job = peer_job("sync", "done", done, units=units)
        line = job_line(job, None)
        over = outcome(job, line)
        return (line.tone, line.text), (over.tone, over.word, over.reason), peer_outcome(job)["left"]

    for others in ([], took):  # nothing else, or three taken: as the same sync without the removal
        assert said(others + [answered]) == said(others)
    assert said([answered]) == (("ready", "Shared"), ("ready", "Shared", "Nothing changed in either book."), [])
    assert said(took + [answered])[1] == ("ready", "Shared", "3 changes taken.")
    # A real leftover beside it: one left, not two.
    real = ("song/radiohead/creep", "left", "it changed here since the comparison")
    assert said([real, answered]) == (
        ("waiting", "Shared · 1 change left as it was"),
        ("waiting", "Shared", "Nothing changed in either book. 1 change left as it was."),
        [["song/radiohead/creep", "it changed here since the comparison"]])


def test_a_sync_whose_indexes_or_pages_failed_after_its_changes_says_what_it_shared_first():
    """The phone's sync goes on past a failed index or mirror stage (its job done, its line a wait in the stage's
    words); the computer's exits 1 for its index stage. Either took and gave its changes first: the outcome says them,
    then what failed, never "Not taken". With nothing shared, the failure's words alone, as before."""
    from test_web_sync import peer_job

    took = [("song/oasis/wonderwall", "taken", ""), ("song/muse/hysteria", "given", "")]
    done = {"compare": ("done", "4 differences"), "take": ("done", "took 1"), "give": ("done", "gave 1"),
            "agree": ("done", "12 units the books agree on")}
    index = "Couldn't download the computer's indexes: the connection was reset"
    pages = "No answer from http://192.168.1.20:8737: timed out"

    def said(state, stages, units=took):
        job = peer_job("sync", state, dict(done, **stages), units=units)
        if "mirror" in stages:  # the phone's own stage, after give, which caracole serve's sync has none of
            job.stages.insert(3, Stage("mirror", "Copy", *stages["mirror"], ""))
        over = outcome(job, job_line(job, None))
        return over.tone, over.word, over.reason, over.action.label

    assert said("done", {"index": ("failed", index)}) == (
        "waiting", "Shared", f"1 change taken, 1 change given. {index}.", "Compare again")
    assert said("done", {"mirror": ("failed", pages)}) == (
        "waiting", "Shared", f"1 change taken, 1 change given. {pages}.", "Compare again")
    assert said("failed", {"index": ("failed", index)}) == (
        "failed", "Failed", f"1 change taken, 1 change given. {index}.", "Compare again")
    left = took + [("song/radiohead/creep", "left", "skipped, as chosen")]
    assert said("done", {"index": ("failed", index)}, left)[2] == (
        f"1 change taken, 1 change given. 1 change left as it was. {index}.")
    # Nothing shared: the failure's words, as before.
    assert said("done", {"index": ("failed", index)}, []) == ("waiting", "Not taken", f"{index}.", "Compare again")
    assert said("failed", {"index": ("failed", index)}, []) == ("failed", "Failed", f"{index}.", "Compare again")


def test_an_interrupted_take_pull_or_merge_names_what_the_owner_can_do_never_a_try_again_it_has_not():
    """A take (the phone's push), a pull (asked by the other caracole) or a merge of the phone's index pages the server
    stopped offers no action: its words send the owner to the other device, where the next share or sync gives it
    again; the phone sends its pages again by itself (it forgets its notes of them once their merge ends done)."""
    import dataclasses

    from caracole.web.outcome import (INTERRUPTED_MERGE_RAN, INTERRUPTED_MERGE_WAITED, INTERRUPTED_PULL_RAN,
                                      INTERRUPTED_PULL_WAITED, INTERRUPTED_TAKE_RAN, INTERRUPTED_TAKE_WAITED)

    from test_web_sync import peer_job

    assert INTERRUPTED_TAKE_RAN == "The server stopped mid-way. Share again from the other device to finish."
    assert INTERRUPTED_TAKE_WAITED == "The server stopped before it ran. Share again from the other device to run it."
    assert INTERRUPTED_PULL_RAN == "The server stopped mid-way. Sync again from the other caracole to finish."
    assert INTERRUPTED_PULL_WAITED == "The server stopped before it ran. Sync again from the other caracole to run it."
    take = peer_job("peer-push", "running", {"check": ("running", "")})
    pull = dataclasses.replace(take, steps=[dataclasses.replace(take.steps[0], args=(
        "peer", "pull", "--unit=song/a/b", "--", "http://192.168.1.10:8737"))])
    assert INTERRUPTED_MERGE_RAN == "The server stopped mid-way. The phone's next sync sends them again."
    assert INTERRUPTED_MERGE_WAITED == "The server stopped before it ran. The phone's next sync sends them again."
    merge = peer_job("index-merge", "running", {"merge": ("running", "")})
    for job, ran, waited in ((take, INTERRUPTED_TAKE_RAN, INTERRUPTED_TAKE_WAITED),
                             (pull, INTERRUPTED_PULL_RAN, INTERRUPTED_PULL_WAITED),
                             (merge, INTERRUPTED_MERGE_RAN, INTERRUPTED_MERGE_WAITED)):
        job.state = INTERRUPTED
        over = outcome(job, job_line(job, None))
        assert (over.word, over.reason, over.action) == ("Interrupted", ran, None)
        job.started_at = None
        over = outcome(job, job_line(job, None))
        assert (over.word, over.reason, over.action) == ("Interrupted", waited, None)


@pytest.mark.parametrize("given, sent, pushes", [(1, 1, 3), (350, 2, 4)])
def test_a_give_stopped_after_its_pushes_says_its_count_once_in_the_words_peer_sync_really_writes(given, sent, pushes):
    """commands/peer.py's own words for how far a stopped give got (``given_so_far``, what ``_push`` fails with): the
    outcome says what was given there alone, so a rewording of them that the outcome stops reading fails here."""
    from caracole.commands.peer import TAKEN_STAY, given_so_far

    from test_web_sync import peer_job

    far = given_so_far(given, sent, pushes)
    assert far.startswith(f"{given} given in the first ")
    failure = f"Couldn't give them {given + 5}: {far}push {sent + 1} of {pushes}: the computer answered 503."
    units = [("song/oasis/wonderwall", "taken", "")] + [(f"song/a/{n}", "given", "") for n in range(given)]
    job = peer_job("sync", "failed", {"compare": ("done", ""), "take": ("done", "took 1"),
                                      "give": ("failed", f"{failure} {TAKEN_STAY}")},
                   units=units, output=(f"error: {failure} {TAKEN_STAY}",))
    reason = outcome(job, job_line(job, None)).reason
    assert reason == f"1 change taken. {failure}", reason
    assert "change given" not in reason and "changes given" not in reason  # the count said once, the failure's


def test_a_sync_that_failed_at_any_stage_after_its_changes_says_what_it_shared_first():
    """Whatever stage failed after the changes went (the give, a push of several, the agreement), and a sync the
    server interrupted after it took some: what was shared said first, then the failure, as the Sync sheet's title
    says "Synced with" for the same job (test_sync_sheet.py); with nothing shared, the failure's words alone."""
    from caracole.commands.peer import TAKEN_STAY

    from test_web_sync import peer_job

    took = [("song/oasis/wonderwall", "taken", ""), ("song/muse/hysteria", "taken", ""),
            ("song/blur/song-2", "taken", "")]
    done = {"compare": ("done", "4 differences"), "take": ("done", "took 3")}
    give = "Couldn't give them 2: No answer from http://192.168.1.20:8737: timed out"
    # commands/peer.py's own words for a give stopped after its first push (``far``): its count said there alone.
    pushed = (f"Couldn't give them 3: 1 given in the first push of 3; then push 2 of 3: the computer answered 503. "
              f"{TAKEN_STAY}")

    def said(state, stages, units=took, output=()):
        job = peer_job("sync", state, dict(done, **stages), units=units, output=output)
        over = outcome(job, job_line(job, None))
        return over.tone, over.word, over.reason, over.action.label

    assert said("failed", {"give": ("failed", give)}, output=(f"error: {give}",)) == (
        "failed", "Failed", f"3 changes taken. {give}.", "Compare again")
    stopped = took[:1] + [("song/abba/sos", "given", "")]
    assert said("failed", {"give": ("failed", pushed)}, stopped, output=(f"error: {pushed}",)) == (
        "failed", "Failed", "1 change taken. " + pushed.split(f" {TAKEN_STAY}")[0], "Compare again")
    # Nothing taken, the failure's count of what was given the one said.
    assert said("failed", {"take": ("done", "took 0"), "give": ("failed", pushed)}, stopped[1:],
                output=(f"error: {pushed}",)) == (
        "failed", "Failed", pushed.split(f" {TAKEN_STAY}")[0], "Compare again")
    agree = "Couldn't note where the books agree: database is locked"
    assert said("failed", {"give": ("done", "gave 0"), "agree": ("failed", agree)},
                output=(f"error: {agree}",)) == ("failed", "Failed", f"3 changes taken. {agree}.", "Compare again")
    # Nothing shared: the give's failure alone, as before.
    assert said("failed", {"take": ("done", "took 0"), "give": ("failed", give)}, [],
                output=(f"error: {give}",)) == ("failed", "Failed", f"{give}.", "Compare again")
    # Interrupted after it took some: those said, then the server's words.
    job = peer_job("sync", "running", dict(done, give=("running", "1 of 2")), units=took)
    job.state = INTERRUPTED
    assert job.started_at is not None
    over = outcome(job, job_line(job, None))
    assert (over.word, over.reason) == ("Interrupted", f"3 changes taken. {INTERRUPTED_SYNC_RAN}")
    assert INTERRUPTED_SYNC_RAN == "The server stopped mid-way. Compare again to finish." != INTERRUPTED_RAN
    # Its action is Compare again, never Try again (its choices were made on a comparison that is past): so it says.
    assert over.action.label == "Compare again"
    waited = peer_job("sync", "queued", {})
    waited.state, waited.started_at = INTERRUPTED, None
    over = outcome(waited, job_line(waited, None))
    assert (over.word, over.reason, over.action.label) == ("Interrupted", INTERRUPTED_SYNC_WAITED, "Compare again")
    assert INTERRUPTED_SYNC_WAITED == "The server stopped before it ran. Compare again to run it."
