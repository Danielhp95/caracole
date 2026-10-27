"""caracole/web/outcome.py: what the requests page says of a request, the running one's steps and how a
finished one ended, with the next step to take."""

from datetime import UTC, datetime

from caracole.get import MATCH_NOT_FOUND, NOT_IN_INDEX, SHEET_FROM, STAGES
from caracole.songs import get_song, update_song
from caracole.web.jobs import (
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
from caracole.web.outcome import Action, Chip, Outcome, elsewhere, outcome, progress, steps
from caracole.web.status import SongFacts, job_line

from conftest import add_song


def lookup(state="running", stages=None, *, args=None, job_id=4, display="Muse - Hysteria"):
    """A lookup, its stages in ``stages`` (name -> (state, detail)), the others waiting."""
    made = [Step(label, tuple(a)) for label, a in lookup_steps(*display.split(" - "))] if args is None else [
        Step("Look it up now", tuple(args))]
    said = stages or {}
    job = Job(job_id, f"Fetch {display}", display.lower().replace(" - ", "/"), made, fetching=True,
              display=display, state=state,
              stages=[Stage(name, label, *said.get(name, ("waiting", ""))) for name, label in STAGES])
    if state != "running":
        made[0].state = "done" if state == "done" else "failed"
    return job


def ended(stages, state="done", **kw):
    """A lookup that is over: every stage not named done, unless named."""
    every = {name: ("done", "") for name, _ in STAGES} | stages
    return lookup(state, every, **kw)


# --- the running request's steps ---------------------------------------------------------------------


def test_a_lookup_in_progress_shows_its_stages_as_steps_in_plain_words():
    job = lookup(stages={"song": ("done", "in the library"), "match": ("done", "matched to muse/hysteria"),
                         "sheet": ("done", "tab 1 from Ultimate Guitar"), "pdf": ("running", "")})
    assert steps(job, SongFacts(sheet="Muse/Hysteria/sheet.html", sheet_from="UG")) == [
        Chip("Song", "done"), Chip("Match", "done", "UG"), Chip("Sheet", "done", "UG"), Chip("PDF", "running"),
        Chip("Lyrics", "waiting"), Chip("Extras", "waiting"), Chip("Songbooks", "waiting")]
    # Ultimate Guitar's second pass, LaCuerda's and gtptabs.com's are one step, running from the first to the last.
    later = lookup(stages={name: ("done", "") for name in ("song", "match", "sheet", "pdf", "lyrics", "ug")}
                   | {"lacuerda": ("running", "")})
    assert Chip("Extras", "running") in steps(later) and Chip("Lyrics", "done") in steps(later)


def test_harptabs_coms_stage_is_part_of_the_extras_step_and_says_what_waits_in_its_words():
    # The lookup's last site, after gtptabs.com: Extras runs until it is over, and a spent budget says its harmonica tab.
    extras = {name: ("done", "") for name in ("song", "match", "sheet", "pdf", "lyrics", "ug", "lacuerda", "gtptabs")}
    running = lookup(stages=extras | {"harptabs": ("running", "")})
    assert Chip("Extras", "running") in steps(running)
    assert Chip("Extras", "done") in steps(lookup(stages=extras | {"harptabs": ("done", "harmonica tab kept")}))
    spent = ended({"harptabs": ("skipped", "the lookup's 6 requests to harptabs.com are spent; the nightly run does "
                                           "the rest")})
    assert said(spent, SongFacts(sheet="Muse/Hysteria/sheet.html")).reason == (
        "The lookup's 6 requests to harptabs.com are spent: the harmonica tab waits for tonight's run.")


def test_a_step_the_request_doesnt_use_is_not_drawn():
    # Its songbooks left to a later job (Get the missing songs): no Songbooks step.
    job = lookup(args=lookup_steps("Muse", "Hysteria", songbooks=False)[0][1])
    assert [c.name for c in steps(job)] == ["Song", "Match", "Sheet", "PDF", "Lyrics", "Extras"]
    # A stage that ended with nothing to do for this song: no sheet, so no PDF; no songbook lists it.
    skipped = lookup(stages={"song": ("done", ""), "match": ("done", "not in the offline Ultimate Guitar index"),
                             "sheet": ("skipped", "the offline index doesn't have it"), "pdf": ("skipped", "no sheet yet"),
                             "lyrics": ("running", "")})
    assert [c.name for c in steps(skipped)] == ["Song", "Match: not on UG", "Lyrics", "Extras", "Songbooks"]
    # A failed stage stays, as failed.
    failed = lookup(stages={"song": ("done", ""), "match": ("done", ""), "sheet": ("done", ""),
                            "pdf": ("failed", "chordpro couldn't make the PDF; the log says why"),
                            "lyrics": ("running", "")})
    assert Chip("PDF", "failed") in steps(failed)


def test_match_says_the_index_it_matched_in_and_sheet_the_site_it_asked_then_got_it_from():
    # Match is the offline index's, Ultimate Guitar's. The sheet names no site until it asks one, then the one it
    # asks (get.SHEET_FROM), switching when it falls back to the other; once done, where the song's sheet came from.
    asked = {"song": ("done", "in the library"), "match": ("done", "matched to muse/hysteria")}
    assert steps(lookup(stages={**asked, "sheet": ("running", "")}))[1:3] == [
        Chip("Match", "done", "UG"), Chip("Sheet", "running")]
    assert steps(lookup(stages={**asked, "sheet": ("running", SHEET_FROM["ug"])}))[2] == Chip("Sheet", "running", "UG")
    assert steps(lookup(stages={**asked, "sheet": ("running", SHEET_FROM["lacuerda"])}))[2] == Chip(
        "Sheet", "running", "LaCuerda")
    done = lookup(stages={**asked, "sheet": ("done", "sheet kept from LaCuerda"), "pdf": ("running", "")})
    assert steps(done, SongFacts(sheet="Muse/Hysteria/sheet.html", sheet_from="LaCuerda"))[2] == Chip(
        "Sheet", "done", "LaCuerda")
    assert steps(done)[2] == Chip("Sheet", "done")  # where it came from isn't known: no site, never a guess
    assert [c.name for c in steps(lookup(stages={}))[:3]] == ["Song", "Match", "Sheet"]  # waiting: no site yet


def test_a_song_ultimate_guitars_index_lacks_is_drawn_plain_never_a_failure():
    # The sheet may come from LaCuerda: "Match: not on UG", which is over, as a done step is.
    job = lookup(stages={"song": ("done", "in the library"),
                         "match": ("done", MATCH_NOT_FOUND + " (the offline index is incomplete)"),
                         "sheet": ("running", SHEET_FROM["lacuerda"])})
    assert steps(job)[:3] == [Chip("Song", "done"), Chip("Match: not on UG", "plain"),
                              Chip("Sheet", "running", "LaCuerda")]


def test_a_sheet_that_failed_names_the_site_it_asked_when_it_did():
    job = lookup(stages={"song": ("done", ""), "match": ("done", "matched to muse/hysteria")})
    job.heard({"stage": "sheet", "state": "running", "detail": SHEET_FROM["ug"]})
    job.heard({"stage": "sheet", "state": "failed", "detail": "Ultimate Guitar failed (ug: 502); the nightly run "
                                                              "tries again"})
    assert steps(job)[2] == Chip("Sheet", "failed", "UG")
    bug = lookup(stages={"song": ("done", ""), "match": ("done", ""), "sheet": ("failed", "a bug in caracole: x")})
    assert steps(bug)[2] == Chip("Sheet", "failed")


def test_the_library_page_draws_a_running_lookups_steps_with_the_count_of_those_over():
    facts = SongFacts(sheet_from="UG")
    lyrics = lookup(stages={name: ("done", "") for name in ("song", "match", "sheet", "pdf")} | {"lyrics": (
        "running", "")})
    assert progress(lyrics, job_line(lyrics, facts), facts) == {
        "steps": [{"name": "Song", "source": "", "state": "done"}, {"name": "Match", "source": "UG", "state": "done"},
                  {"name": "Sheet", "source": "UG", "state": "done"}, {"name": "PDF", "source": "", "state": "done"},
                  {"name": "Lyrics", "source": "", "state": "running"},
                  {"name": "Extras", "source": "", "state": "waiting"},
                  {"name": "Songbooks", "source": "", "state": "waiting"}],
        "count": "4 of 7 done"}
    # Match: not on UG is over, as a done step is; a step that drops out drops from the count.
    lacuerda = lookup(stages={"song": ("done", ""), "match": ("done", MATCH_NOT_FOUND),
                              "sheet": ("running", SHEET_FROM["lacuerda"])})
    assert progress(lacuerda, job_line(lacuerda, None), None)["count"] == "2 of 7 done"
    dropped = lookup(stages={"song": ("done", ""), "match": ("done", MATCH_NOT_FOUND),
                             "sheet": ("skipped", NOT_IN_INDEX), "pdf": ("skipped", "no sheet yet"),
                             "lyrics": ("running", "")})
    assert progress(dropped, job_line(dropped, None), None)["count"] == "2 of 5 done"


def test_the_steps_fold_away_once_a_lookup_ends_ready_and_stay_once_it_ends_otherwise():
    ready = SongFacts(sheet="Muse/Hysteria/sheet.html", sheet_from="UG")
    over = ended({"songbooks": ("skipped", "no songbook lists it")})
    assert progress(over, job_line(over, ready), ready) == {}  # the song's line opens the sheet itself
    # Ended otherwise, the steps stay, with no count: they show which step stopped.
    missing = ended({"match": ("done", MATCH_NOT_FOUND), "sheet": ("skipped", NOT_IN_INDEX),
                     "pdf": ("skipped", "no sheet yet"), "songbooks": ("skipped", "no songbook lists it")})
    facts = SongFacts(not_found=True, checked_now=True)
    assert job_line(missing, facts).text == "Not found"
    assert progress(missing, job_line(missing, facts), facts) == {"steps": [
        {"name": "Song", "source": "", "state": "done"}, {"name": "Match: not on UG", "source": "", "state": "plain"},
        {"name": "Lyrics", "source": "", "state": "done"}, {"name": "Extras", "source": "", "state": "done"}]}
    failed = ended({"song": ("failed", "overrides.toml can't be read: line 3")} | {
        name: ("skipped", "") for name, _ in STAGES[1:]}, state="failed")
    assert progress(failed, job_line(failed, None), None) == {"steps": [
        {"name": "Song", "source": "", "state": "failed"}]}


def test_a_request_that_runs_no_lookup_or_hasnt_run_has_no_steps_on_the_library_page():
    queued = lookup(state="queued")
    assert progress(queued, job_line(queued, None), None) == {}  # its line says its place in the queue
    cancelled = ended({name: ("skipped", "") for name, _ in STAGES}, state="cancelled")
    cancelled.state = "cancelled"
    assert progress(cancelled, job_line(cancelled, None), None) == {}
    add = Job(2, "Add Muse - Hysteria", "muse/hysteria", [Step("Adding to the library", ("add", "--", "Muse",
                                                                                       "Hysteria"),
                                                                 state="running")], state="running")
    assert progress(add, job_line(add, None), None) == {}
    read = Job(3, "x", LACUERDA_ARTIST + "caifanes", [Step("Reading LaCuerda's page for Caifanes", (
        "lacuerda", "--artist=caifanes"), state="running")], state="running")
    assert progress(read, job_line(read, None), None) == {}
    keep = Job(5, "Keep", "muse/hysteria", [Step("Fetching the version from Ultimate Guitar", tuple(
        version_steps("Muse", "Hysteria", keep="3")[0][1]), state="running")], state="running",
               stages=[Stage(name, label) for name, label in KEEP_STAGES])
    assert progress(keep, job_line(keep, None), None) == {}


def test_a_request_of_other_commands_shows_its_job_steps_the_same_way():
    job = Job(2, "Pick muse/hysteria for Muse - Hysteria, and fetch it", "muse/hysteria", [
        Step("Writing the answer to overrides.toml", ("review", "--song=Muse - Hysteria", "--pick=muse/hysteria"),
             state="done"),
        Step("Fetching from Ultimate Guitar", ("fetch", "--song=Muse - Hysteria"), state="running"),
        Step("Rendering the sheet", ("render", "--song=Muse - Hysteria"))], state="running")
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
                                         "the nightly run tries again")})
    facts = SongFacts(sheet="Radiohead/Creep/sheet.html")
    assert said(lrclib, facts).reason == "LRCLIB answered 503: the lyrics wait for tonight's run."
    timeout = ended({"lyrics": ("failed", "LRCLIB failed (lrclib: https://lrclib.net/api/get: timed out); "
                                          "the nightly run tries again")})
    assert said(timeout, facts).reason == "LRCLIB failed: the lyrics wait for tonight's run."
    spent = ended({"gtptabs": ("skipped", "the lookup's 6 requests to gtptabs.com are spent; the nightly run does "
                                          "the rest")})
    assert said(spent, facts).reason == ("The lookup's 6 requests to gtptabs.com are spent: the Guitar Pro file "
                                         "waits for tonight's run.")
    blocked = ended({"ug": ("skipped", "Ultimate Guitar blocked caracole (ug: 429: https://x: HTTP 429): no more "
                                       "requests to it until 2026-10-22 18:00 UTC. Nothing was marked not found.")})
    assert said(blocked, facts).reason == ("Ultimate Guitar blocked caracole: its other versions and its tab "
                                           "wait until 2026-10-22 18:00 UTC.")
    cooling = ended({"lyrics": ("skipped", "LRCLIB is cooling down after a block, until 2026-10-22 18:00 UTC")})
    assert said(cooling, facts).reason == ("LRCLIB is cooling down after a block: the lyrics wait until "
                                           "2026-10-22 18:00 UTC.")
    # Nothing to say of a site turned off, or of a stage that had nothing to do.
    quiet = ended({"gtptabs": ("skipped", "gtptabs.com is off in caracole.toml"),
                   "songbooks": ("skipped", "no songbook lists it")})
    assert said(quiet, facts).reason == ""


def test_needs_review_picks_the_match():
    facts = SongFacts(review=True, picker="review?song=7")
    job = ended({"sheet": ("skipped", "caracole isn't sure which Ultimate Guitar song this is")})
    assert said(job, facts, song_id=7) == Outcome(
        "review", "Needs review", "caracole isn't sure which Ultimate Guitar song it is.",
        Action("Pick the match", href="/review?song=7"))
    # Without candidates to pick from, its line on the library page, where caracole review's answers are.
    bare = said(job, SongFacts(review=True), song_id=7)
    assert bare.action == Action("Open in the library", href="/#song=7")


SEARCH = Action("See what caracole search finds", href="/review?song=3")


def test_not_found_says_ultimate_guitar_has_no_chords_only_once_it_was_asked():
    # The offline index didn't match the name, and UG couldn't be asked: whether UG has chords, nobody knows.
    # What caracole search finds for it is the way on, the one next step.
    job = ended({"sheet": ("skipped", NOT_IN_INDEX)}, display="Horse The Band - Crippled By Pizza")
    unmatched = SongFacts(not_found=True, checked_now=True)
    assert said(job, unmatched, song_id=3) == Outcome(
        "missing", "Not found", "Not in the offline Ultimate Guitar index under this name.", SEARCH)
    # Its artist's UG page was read for it, with no chords there: UG was asked, and the index still lacks it.
    read = SongFacts(not_found=True, checked_now=True, asked_ug=True)
    assert said(job, read, song_id=3) == Outcome("missing", "Not found", "Ultimate Guitar has no chords for it.",
                                                 SEARCH)
    # A song the index matched, whose UG page had no sheet to keep: requested by name.
    matched = ended({"sheet": ("skipped", "Ultimate Guitar has no sheet to keep")},
                    display="Horse The Band - Crippled By Pizza")
    assert said(matched, SongFacts(checked_now=True, asked_ug=True), song_id=3) == Outcome(
        "missing", "Not found", "Ultimate Guitar has no chords for it.",
        Action("Request by name", href="/#q=Horse+The+Band+-+Crippled+By+Pizza"))
    # A fetch of commands that refused the song as not in the index (it failed): not asked either.
    fetch = Job(9, "Fetch Horse The Band - Crippled By Pizza", "horse-the-band/crippled-by-pizza",
                [Step("Fetching from Ultimate Guitar", ("fetch", "--song=Horse The Band - Crippled By Pizza"),
                      state="failed")], fetching=True, state="failed")
    assert said(fetch, SongFacts(not_found=True), song_id=3).reason == (
        "Not in the offline Ultimate Guitar index under this name.")


def test_not_found_with_something_elsewhere_gets_it_from_there():
    job = ended({"sheet": ("skipped", "Ultimate Guitar has no sheet to keep")})
    gtp = SongFacts(checked_now=True, asked_ug=True, elsewhere=("gtptabs", "https://gtptabs.com/tabs/x.html"))
    assert said(job, gtp, song_id=3) == Outcome(
        "missing", "Not found", "Ultimate Guitar has no chords for it; gtptabs.com's index lists a page for it.",
        Action("Get it from there", post="/lookup", fields=(("song", "3"), ("then", "jobs"))))
    # A song the index didn't match: LaCuerda's sheet first, and what caracole search finds beside it.
    unmatched = ended({"sheet": ("skipped", NOT_IN_INDEX)})
    lc = SongFacts(not_found=True, checked_now=True,
                   elsewhere=("lacuerda", "https://acordes.lacuerda.net/estopa/como_camaron.shtml"))
    assert said(unmatched, lc, song_id=3) == Outcome(
        "missing", "Not found", "Not in the offline Ultimate Guitar index under this name; LaCuerda has a sheet.",
        Action("Get it from there", post="/lookup", fields=(
            ("song", "3"), ("lacuerda", "https://acordes.lacuerda.net/estopa/como_camaron.shtml"), ("then", "jobs"))),
        also=SEARCH)
    # A Guitar Pro file the lookup itself downloaded is in the library already: the song's line has it.
    got = ended({"sheet": ("skipped", ""), "gtptabs": ("done", "Guitar Pro file downloaded")})
    assert said(got, SongFacts(checked_now=True, asked_ug=True), song_id=3) == Outcome(
        "missing", "Not found", "Ultimate Guitar has no chords for it; caracole got a Guitar Pro file from "
                                "gtptabs.com.", Action("Open in the library", href="/#song=3"))
    assert said(got, SongFacts(not_found=True, checked_now=True), song_id=3) == Outcome(
        "missing", "Not found", "Not in the offline Ultimate Guitar index under this name; caracole got a Guitar "
                                "Pro file from gtptabs.com.", Action("Open in the library", href="/#song=3"),
        also=SEARCH)


def test_failed_and_not_fetched_yet_try_again():
    failed = ended({"song": ("failed", "overrides.toml can't be read: line 3")}, state="failed")
    assert said(failed) == Outcome("failed", "Failed", "overrides.toml can't be read: line 3.",
                                   Action("Try again", post="/jobs/again", fields=(("job", "4"),)))
    # Not fetched yet says why, from its stages: a wait is never a miss.
    waits = ended({"sheet": ("skipped", "this hour's 60 lookup requests to Ultimate Guitar are spent; the nightly "
                                        "run does the rest"), "pdf": ("skipped", "no sheet yet")})
    assert said(waits, SongFacts()) == Outcome(
        "waiting", "Not fetched yet", "This hour's 60 lookup requests to Ultimate Guitar are spent: the sheet waits "
                                      "for tonight's run.",
        Action("Try again", post="/jobs/again", fields=(("job", "4"),)))
    # A fetch of commands, which has no stages: its output says which.
    fetch = Job(9, "Fetch Radiohead - Creep", "radiohead/creep",
                [Step("Fetching from Ultimate Guitar", ("fetch", "--song=Radiohead - Creep"), state="done")],
                fetching=True, state="done")
    assert said(fetch, SongFacts()).reason == ("caracole didn't ask Ultimate Guitar this time (a cooldown, a block, "
                                               "a spent budget or an error: the output says which).")


def test_a_failed_removal_tries_again_through_its_question_never_straight_to_remove():
    removal = Job(7, "Remove Radiohead - Creep", REMOVING + "radiohead/creep",
                  [Step(label, args, state="failed") for label, args in remove_steps("Radiohead - Creep")],
                  state="failed", song_id=12)
    # What goes is asked again (POST /remove without confirm: removal.plan_removal, as of now).
    assert said(removal).action == Action("Try again", post="/remove", fields=(("song", "12"),))
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
    add = Job(8, "Add Radiohead - Creep", "radiohead/creep", [Step("Adding to the library", ("add",), state="done")],
              state="done")
    assert said(add, SongFacts()) == Outcome("added", "Added", "The nightly run looks for it.")
    read = Job(9, "Read the page of Caifanes on LaCuerda", LACUERDA_ARTIST + "caifanes",
               [Step("Reading", ("lacuerda", "--artist=caifanes"), state="done",
                     output=["Not read: LaCuerda failed (lacuerda: 503: x); the nightly run tries again"])],
               state="done")
    assert said(read) == Outcome("waiting", "Not read", "LaCuerda failed.",
                                 Action("Try again", post="/jobs/again", fields=(("job", "9"),)))


# --- what the library's indexes have elsewhere, for a song not found ---------------------------------------


NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)


def test_elsewhere_is_a_lacuerda_sheet_or_a_gtptabs_page_the_local_indexes_list(conn, cfg):
    song = add_song(conn, "Estopa", "Como Camarón")
    # A lookup that asked neither: LaCuerda didn't look like the song's, gtptabs.com failed.
    job = ended({"sheet": ("skipped", ""), "lacuerda": ("skipped", "not a song for LaCuerda: not Spanish"),
                 "gtptabs": ("failed", "gtptabs.com failed (gtptabs: 500: x); the nightly run tries again")},
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
                   "lacuerda": ("skipped", "the lookup's 6 requests to LaCuerda are spent; the nightly run does the rest"),
                   "gtptabs": ("skipped", "gtptabs.com blocked caracole (gtptabs: 429: x): no more requests to it "
                                          "until 2026-10-22 18:00 UTC.")}, display="Estopa - Como Camarón")
    assert elsewhere(conn, cfg, song, spent, NOW) is None
