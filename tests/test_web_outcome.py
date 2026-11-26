"""caracole/web/outcome.py: what the requests page says of a request, the running one's steps and how a
finished one ended, with the next step to take."""

from datetime import UTC, datetime, timedelta

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
from caracole.web.outcome import SITE_NAMES, Action, Chip, Outcome, elsewhere, outcome, progress, steps
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
