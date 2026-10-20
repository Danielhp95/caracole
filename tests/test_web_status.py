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
