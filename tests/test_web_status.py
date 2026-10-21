"""caracole/web/status.py: the one line a request shows, on its card and on /jobs."""

from caracole.web.jobs import Job, Step
from caracole.web.status import Line, SongFacts, details_href, job_line

FETCH = [("Adding to the library", ("add", "--", "Radiohead", "Creep")),
         ("Looking it up", ("match",)),
         ("Fetching from Ultimate Guitar", ("fetch", "--song=Radiohead - Creep")),
         ("Rendering the sheet", ("render",))]


def job(state="queued", steps=FETCH, *, fetching=True, states=None, outputs=None, job_id=3):
    made = [Step(label, args) for label, args in steps]
    for step, s in zip(made, states or []):
        step.state = s
    for step, out in zip(made, outputs or []):
        step.output = list(out)
    return Job(job_id, "Fetch Radiohead - Creep", "radiohead/creep", made, fetching=fetching, state=state)


READY = SongFacts(sheet="Radiohead/Creep/sheet.pdf")


def test_a_queued_request_says_how_many_wait_before_it():
    assert job_line(job(), None) == Line("queued", "Queued…")
    assert job_line(job(), None, ahead=1) == Line("queued", "Queued behind 1 request…")
    assert job_line(job(), None, ahead=3).text == "Queued behind 3 requests…"


def test_a_running_request_says_its_running_steps_label_whatever_the_command():
    running = job("running", states=["done", "done", "running", "waiting"])
    assert job_line(running, None) == Line("running", "Fetching from Ultimate Guitar…")
    # A job of any other commands reads the same way: the label is the line.
    other = job("running", [("Searching every site", ("get", "Radiohead - Creep"))], states=["running"])
    assert job_line(other, None).text == "Searching every site…"
    # Between two steps, the one about to run.
    between = job("running", states=["done", "waiting", "waiting", "waiting"])
    assert job_line(between, None).text == "Looking it up…"


def test_a_removal_says_removing_while_it_runs_then_removed():
    from caracole.web.jobs import REMOVING, remove_steps

    def removal(state, states):
        made = job(state, remove_steps("Radiohead - Creep"), fetching=False, states=states)
        made.song_key = REMOVING + "radiohead/creep"
        return made

    assert job_line(removal("running", ["running"]), None) == Line("running", "Removing from caracole…")
    # Its song is gone once it is done: that is what it did, not a request that added the song.
    assert job_line(removal("done", ["done"]), None) == Line("removed", "Removed")
    failed = removal("failed", ["failed"])
    failed.steps[0].output = ["error: wanted.txt can't be read."]
    assert job_line(failed, None) == Line("failed", "wanted.txt can't be read.", details=details_href(3))


def test_a_songbook_change_links_its_page_once_made_or_added_to_only():
    # Made, or added to, the songbook's page is the next thing to open; moved, taken out of or renamed, the
    # songbook's own card, where its buttons are, shows it already: no link to repeat it.
    page = "_songbooks/Campfire/songbook.html"
    said = {}
    for action, args in [("make", ("Campfire", "Muse - Hysteria")), ("add", ("Campfire", "Muse - Hysteria")),
                         ("move", ("Campfire", "Muse - Hysteria", "2")), ("remove", ("Campfire", "Muse - Hysteria")),
                         ("rename", ("Picnic", "Campfire"))]:
        command = ("songbook", action, "--", *args)
        made = Job(4, action, "songbook\x1f" + "\x1f".join(command), [Step("Changing the songbook", command)],
                   state="done")
        made.steps[0].state = "done"
        line = job_line(made, None, songbook_page=page)
        said[action] = (line.text, line.link)
    assert said == {"make": ("Made", ("Open songbook", page)), "add": ("Added", ("Open songbook", page)),
                    "move": ("Moved", None), "remove": ("Taken out", None), "rename": ("Renamed", None)}


def test_a_done_request_whose_song_has_a_sheet_is_ready_with_a_link_to_it():
    done = job("done", states=["done"] * 4)
    assert job_line(done, READY) == Line("ready", "Ready", ("Open sheet", "Radiohead/Creep/sheet.pdf"))
    # Asked only to add it, a song with a sheet already is ready too.
    added = job("done", FETCH[:1], fetching=False, states=["done"])
    assert job_line(added, READY).tone == "ready"


def test_a_done_fetch_without_a_sheet_says_why_and_never_calls_a_wait_a_miss():
    done = job("done", states=["done"] * 4)
    # Looked up during the request (its fetch finished, or its artist's page was read): UG has no sheet.
    assert job_line(done, SongFacts(checked_now=True)) == Line(
        "missing", "Not found", ("see the to-do page", "_todo.md"))
    # A cooldown, a block, a spent budget or an error exits 0 and looks nothing up: it waits, it isn't missing.
    assert job_line(done, SongFacts()) == Line("waiting", "Not fetched yet", details=details_href(3))
    assert job_line(done, SongFacts(not_found=True)).tone == "waiting"  # an earlier match's word, not this fetch's
    assert job_line(done, SongFacts(review=True)) == Line(
        "review", "Needs review", ("see the to-do page", "_todo.md"))
    assert job_line(done, SongFacts(ignored=True)).text == "Ignored in overrides.toml"


def test_a_done_add_says_the_nightly_run_looks_for_it():
    added = job("done", FETCH[:1], fetching=False, states=["done"])
    assert job_line(added, SongFacts()) == Line("added", "Added: the nightly run looks for it")
    assert job_line(added, None) == Line("added", "Added: the nightly run looks for it")


def test_a_done_add_of_a_song_picked_on_lacuerda_says_tonights_run_gets_that_sheet():
    added = job("done", FETCH[:1], fetching=False, states=["done"])
    picked = SongFacts(not_found=True, lacuerda=True)
    assert job_line(added, picked) == Line("added", "Added: tonight's run gets the sheet you picked on LaCuerda")
    # A review of the artist's own songs is still one; a pick LaCuerda had no sheet for is the usual add.
    assert job_line(added, SongFacts(review=True, lacuerda=True)).text == "Needs review"
    assert job_line(added, SongFacts(not_found=True)) == Line("added", "Added: the nightly run looks for it")


def test_reading_a_lacuerda_artists_page_says_what_lacuerda_answered():
    from caracole.web.jobs import LACUERDA_ARTIST, lacuerda_artist_steps

    def read(said, state="done"):
        made = job(state, lacuerda_artist_steps("caifanes", "Caifanes"), fetching=False, states=[state],
                   outputs=[["<6>caracole.http: GET https://acordes.lacuerda.net/caifanes/", said]])
        made.song_key = LACUERDA_ARTIST + "caifanes"
        return made

    details = details_href(3)
    assert job_line(read("Read: LaCuerda's page of Caifanes lists 88 songs, in the index now."), None) == Line(
        "added", "Read: LaCuerda's page of Caifanes lists 88 songs, in the index now.")
    assert job_line(read("Not found: LaCuerda has no artist page for Caifanes."), None) == Line(
        "missing", "Not found: LaCuerda has no artist page for Caifanes.", details=details)
    failed = "Not read: LaCuerda failed (ConnectError: [Errno 111] Connection refused); nothing changed: try again later."
    assert job_line(read(failed), None) == Line("waiting", "Not read: LaCuerda failed.", details=details)
    cooling = "Not read: LaCuerda is cooling down after a block until 21 Oct 03:00; caracole won't ask it before then."
    assert job_line(read(cooling), None).text == "Not read: LaCuerda is cooling down after a block until 21 Oct 03:00."
    spent = "Not read: this hour's 60 lookup requests to LaCuerda are spent; ask again later."
    assert job_line(read(spent), None).text == "Not read: this hour's 60 lookup requests to LaCuerda are spent."
    assert job_line(read("something else"), None) == Line("added", "Done", details=details)  # an older caracole's


def test_a_failed_request_says_its_error_in_one_short_sentence_with_a_link_to_the_details():
    error = ('error: Ultimate Guitar lists Joaquín Sabina only by bare tab ids, which caracole can\'t see. Find '
             "the artist's page on UG, or one of their tab pages, and paste its address under [artist_url].")
    failed = job("failed", states=["done", "done", "failed", "skipped"],
                 outputs=[["Added"], [], ["Ultimate Guitar GET … → 200", error], []])
    line = job_line(failed, None)
    assert line == Line("failed", "Ultimate Guitar lists Joaquín Sabina only by bare tab ids, which caracole "
                                  "can't see.", details="jobs?job=3#job-3")
    # Under systemd the log's lines start with their priority.
    journal = job("failed", states=["failed"], outputs=[["<3>error: wanted.txt can't be written."]])
    assert job_line(journal, None).text == "wanted.txt can't be written."


def test_a_fetch_that_fails_on_a_song_in_review_or_not_found_says_so_not_the_commands_words():
    # `caracole fetch --song` refuses these (exit 1); its error is for a terminal, the line for the card.
    review = job("failed", states=["done", "done", "failed", "skipped"],
                 outputs=[[], [], ['error: "Radiohead - Creep" needs review first: run `caracole review`.'], []])
    assert job_line(review, SongFacts(review=True)) == Line(
        "review", "Needs review", ("see the to-do page", "_todo.md"), details=details_href(3))
    bare = job("failed", states=["done", "done", "failed", "skipped"],
               outputs=[[], [], ["error: Ultimate Guitar lists Obscure Band only by bare tab ids, which …"], []])
    assert job_line(bare, SongFacts(not_found=True)) == Line(
        "missing", "Not found", ("see the to-do page", "_todo.md"), details=details_href(3))
    # Reviewed on its title alone (other artists' songs of it), it needs review too.
    assert job_line(bare, SongFacts(review=True)).tone == "review"
    # Any other failure, or a song that has its sheet, says the error.
    assert job_line(bare, SongFacts()).tone == "failed"
    assert job_line(bare, SongFacts(sheet="a/sheet.pdf", not_found=True)).tone == "failed"
    added = job("failed", FETCH[:1], fetching=False, states=["failed"], outputs=[["error: no"]])
    assert job_line(added, SongFacts(not_found=True)).tone == "failed"  # it fetched nothing


def test_a_song_in_review_with_candidates_links_to_its_picker_not_the_to_do_page():
    # Its picker (the card's, or /review?song=ID) answers the review: that is where to go next.
    picker = "review?song=7"
    review = job("failed", states=["done", "done", "failed", "skipped"],
                 outputs=[[], [], ['error: "Radiohead - Creep" needs review first: run `caracole review`.'], []])
    assert job_line(review, SongFacts(review=True, picker=picker)) == Line(
        "review", "Needs review", ("Pick the match", picker), details=details_href(3))
    done = job("done", states=["done"] * 4)
    assert job_line(done, SongFacts(review=True, picker=picker)) == Line(
        "review", "Needs review", ("Pick the match", picker))
    # A review without candidates has nothing to pick: caracole review offers a pin or an ignore.
    assert job_line(done, SongFacts(review=True)).link == ("see the to-do page", "_todo.md")


def test_a_failure_without_an_error_line_names_its_step():
    crashed = job("failed", states=["done", "failed", "skipped", "skipped"], outputs=[[], ["Traceback …"]])
    assert job_line(crashed, None).text == "Looking it up failed."
    stopped = job("failed", states=["done", "skipped", "skipped", "skipped"])
    assert job_line(stopped, None).text == "It stopped before it was done."


def test_a_long_error_is_cut_to_a_short_sentence():
    words = "error: " + " ".join(["word"] * 80)
    failed = job("failed", states=["failed"], outputs=[[words]])
    text = job_line(failed, None).text
    assert len(text) <= 160 and text.endswith("…") and " wor…" not in text


def test_a_line_as_json():
    assert Line("ready", "Ready", ("Open sheet", "a/b.pdf")).as_json() == {
        "tone": "ready", "text": "Ready", "link": {"label": "Open sheet", "href": "a/b.pdf"}, "details": None}
    assert Line("queued", "Queued…").as_json() == {"tone": "queued", "text": "Queued…", "link": None,
                                                    "details": None}
    # Details: the request's output on /jobs, after the line's own link.
    assert Line("failed", "No.", details="jobs?job=2#job-2").as_json()["details"] == "jobs?job=2#job-2"


# --- a lookup: one `caracole get`, its stages on the line -------------------------------------------


def lookup_job(state="running", stages=None):
    from caracole.web.jobs import JobQueue, lookup_steps

    queue = JobQueue(lambda args, emit: 0)
    made, _ = queue.submit("Fetch Radiohead - Creep", "radiohead/creep", lookup_steps("Radiohead", "Creep"),
                           fetching=True)
    made.state = state
    made.steps[0].state = {"queued": "waiting", "running": "running"}.get(state, state)
    for stage in made.stages:
        stage.state, stage.detail = (stages or {}).get(stage.name, ("waiting", ""))
    return made


def test_a_running_lookup_says_its_running_stage_as_a_steps_label_would():
    # One `caracole get` does what match, fetch and render did: the card still says which part runs.
    assert job_line(lookup_job(), SongFacts()) == Line("running", "Finding the song…")
    assert job_line(lookup_job(), None) == Line("running", "Adding to the library…")  # a song new to the library
    sheet = lookup_job(stages={"song": ("done", "in the library"), "match": ("done", "matched to radiohead/creep"),
                               "sheet": ("running", "")})
    assert job_line(sheet, None) == Line("running", "Fetching from Ultimate Guitar…")
    pdf = lookup_job(stages={"song": ("done", ""), "match": ("done", ""), "sheet": ("done", ""),
                             "pdf": ("running", "")})
    assert job_line(pdf, None).text == "Rendering the sheet…"
    lyrics = lookup_job(stages={name: ("done", "") for name in ("song", "match", "sheet", "pdf")})
    assert job_line(lyrics, None).text == "Fetching the lyrics from LRCLIB…"  # between two: the one about to run


def test_a_lookups_sheet_stage_says_lacuerda_while_it_asks_lacuerda_for_the_sheet():
    # The sheet you picked on LaCuerda, or LaCuerda's when Ultimate Guitar has none, comes from LaCuerda: the line
    # says so (get.py's SHEET_FROM), and Ultimate Guitar's again once the stage turns to it.
    from caracole.get import SHEET_FROM

    before = {"song": ("done", "in the library"), "match": ("done", "matched to radiohead/creep")}
    lacuerda = lookup_job(stages={**before, "sheet": ("running", SHEET_FROM["lacuerda"])})
    assert job_line(lacuerda, None) == Line("running", "Fetching from LaCuerda…")
    back = lookup_job(stages={**before, "sheet": ("running", SHEET_FROM["ug"])})
    assert job_line(back, None) == Line("running", "Fetching from Ultimate Guitar…")


def test_a_lookup_remaking_a_songbook_names_it():
    done = {name: ("done", "") for name in ("song", "match", "sheet", "pdf", "lyrics", "ug", "lacuerda", "gtptabs",
                                              "pages")}
    remaking = lookup_job(stages={**done, "songbooks": ("running", "Campfire")})
    assert job_line(remaking, None).text == "Remaking songbook Campfire…"


def test_a_lookup_waiting_for_the_lock_says_so():
    waiting = lookup_job(stages={"song": ("running", "waiting for another caracole (pid 42: run), which lets "
                                                     "a lookup go first at its next pause, or between two songs")})
    assert job_line(waiting, None).text == "Waiting for another caracole…"


def test_a_refused_lookup_says_why_in_its_stages_words():
    refused = lookup_job("failed", stages={
        "song": ("failed", "Radiohead - Creep is ignored in overrides.toml: take it out of [ignore] to look it up"),
        "match": ("skipped", "")})
    assert job_line(refused, None) == Line(
        "failed", "Radiohead - Creep is ignored in overrides.toml: take it out of [ignore] to look it up.",
        details=details_href(1))
