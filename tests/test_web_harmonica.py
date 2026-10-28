"""caracole serve's page of how a harmonica tab is read (web/harmonica_routes.py): the readings caracole weighs, best
first, each with its Q and a form that pins it in overrides.toml's ``[harmonica]``; harptabs.com's own notation; back
to caracole's guess; each a ``caracole harmonica`` command queued, which writes the pin and renders the song again."""

import json
import re
from html import unescape
from urllib.parse import quote, urlencode

import pytest

from caracole.overrides import add_harmonica
from caracole.render import render_all
from caracole.web.status import details_href

from conftest import add_song
from helpers.rendered import fake_chordpro
from test_render_harmonica import keep_tab
from test_viewer_harptab_notation import SPOKEY
from test_web_app import ALLOWED, Recorder, get, post, text

FOLDER = "Cowboy Bebop/Spokey Dokey"
PAGE = f"{FOLDER}/harmonica-1.html"
DISPLAY = "Cowboy Bebop - Spokey Dokey"


class Pinning(Recorder):
    """The commands queued, recorded; ``caracole harmonica`` done as the real one does it: the pin written (or taken
    out) in overrides.toml, then the song rendered again."""

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

    def __call__(self, args, emit):
        from caracole import db
        from caracole.overrides import load_overrides

        code = super().__call__(args, emit)
        if args[0] == "harmonica":
            tab = next(a.split("=", 1)[1] for a in args if a.startswith("--tab="))
            spec = next((a.split("=", 1)[1] for a in args if a.startswith("--as=")), None)
            add_harmonica(self.cfg.overrides_file, DISPLAY, tab, spec)
            conn = db.connect(self.cfg.db_path)
            try:
                render_all(conn, self.cfg, load_overrides(self.cfg.overrides_file), runner=fake_chordpro)
            finally:
                conn.close()
        return code


@pytest.fixture
def runner(cfg):
    return Pinning(cfg)


@pytest.fixture
def app(cfg, runner):
    from caracole.web.app import WebApp
    from caracole.web.jobs import JobQueue

    return WebApp(cfg, JobQueue(runner, limit=5), allowed=ALLOWED, csrf="tok")


@pytest.fixture
def spokey(conn, cfg):
    """Spokey Dokey, its harmonica tab kept and its page rendered and recorded."""
    song = add_song(conn, "Cowboy Bebop", "Spokey Dokey")
    keep_tab(conn, cfg, song, SPOKEY)
    render_all(conn, cfg, load(cfg), runner=fake_chordpro)
    return song


def load(cfg):
    from caracole.overrides import load_overrides

    return load_overrides(cfg.overrides_file)


def shown(response) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", text(response))).split())


def forms(response) -> list[tuple[str, dict[str, str], str]]:
    """Each form of the page: its action, its fields and its button's words."""
    found = []
    for action, body in re.findall(r'<form[^>]*action="([^"]+)"[^>]*>(.*?)</form>', text(response), re.S):
        fields = {name: unescape(value) for name, value in
                  re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', body)}
        found.append((action, fields, unescape(re.search(r"<button[^>]*>(.*?)</button>", body, re.S).group(1))))
    return found


def page_url(page=PAGE, extra=""):
    return "/harmonica?" + urlencode([("page", page)]) + extra


def test_the_page_says_how_the_tab_is_read_and_offers_each_reading_best_first(app, spokey):
    response = get(app, page_url())
    assert response.status == 200
    said = shown(response)
    assert "Spokey Dokey · Cowboy Bebop, harmonica-1.txt" in said
    assert ("Now: b blow · d draw · * bend · - joins · (h) hold · (w) wah, from the tab's own legend (Q 0.96)."
            in said)
    found = forms(response)
    assert [(action, button) for action, _, button in found] == [
        ("/harmonica/pin", "Read it by its own legend"), ("/harmonica/pin", "Read it as letters"),
        ("/harmonica/pin", "Read it as brackets"), ("/harmonica/pin", "Read it as signs after"),
        ("/harmonica/pin", "Read it as barrett"), ("/harmonica/pin", "As harptabs.com writes it")]
    assert found[1][1] == {"csrf": "tok", "page": PAGE, "as": "letters"}
    assert found[5][1]["as"] == "signs"
    rows = re.findall(r'<li class="reading( now)?">(.*?)</li>', text(response), re.S)
    assert [bool(now) for now, _ in rows] == [True, False, False, False, False, False]  # the one it is read by
    assert "Q 0.86" in unescape(re.sub(r"<[^>]+>", " ", rows[1][1]))
    assert f'<a class="btn" href="/{quote(FOLDER)}/harmonica-1.html">Back to the tab</a>' in text(response)
    assert "Back to caracole's guess" not in said  # nothing pinned


def test_a_reading_with_a_symbol_changed_is_posted_whole(app, conn, cfg):
    song = add_song(conn, "Cowboy Bebop", "Spokey Dokey")
    keep_tab(conn, cfg, song, "-1 -2 -3* -3*\nla la la la\n", harp="Diatonic")
    render_all(conn, cfg, load(cfg), runner=fake_chordpro)
    found = forms(get(app, page_url()))
    assert json.loads(found[0][1]["as"]) == {"as": "signs", "*": "bend"}
    assert found[0][2] == "Read it so: - draw · * bend"


def test_a_pin_is_a_command_queued_and_the_page_says_how_it_goes(app, runner, spokey):
    response = post(app, "/harmonica/pin", {"page": PAGE, "as": "letters"})
    assert response.status == 303
    location = dict(response.headers)["Location"]
    assert location.startswith(page_url() + "&job=")
    app.queue.run_pending()
    assert runner.calls == [["harmonica", "--tab=harmonica-1.txt", "--as=letters", "--", "Cowboy Bebop",
                             "Spokey Dokey"]]
    after = get(app, location)
    said = shown(after)
    assert "Done: read as b blow · d draw · * bend · - joins, as you set it." in said
    assert "Now: b blow · d draw · * bend · - joins, as you set it" in said
    assert [button for _, _, button in forms(after)][-1] == "Back to caracole's guess"
    assert f'href="/{quote(FOLDER)}/harmonica-1.html"' in text(after)
    assert load(app.cfg).harmonica == {spokey.key: {"harmonica-1.txt": "letters"}}


def test_a_table_and_the_guess_again_are_commands_too(app, runner, spokey):
    reading = json.dumps({"as": "signs", "*": "bend", "(w)": "wah"})
    assert post(app, "/harmonica/pin", {"page": PAGE, "as": reading}).status == 303
    app.queue.run_pending()
    assert runner.calls[-1] == ["harmonica", "--tab=harmonica-1.txt", "--as=signs", "--symbol=*=bend",
                                "--symbol=(w)=wah", "--", "Cowboy Bebop", "Spokey Dokey"]
    add_harmonica(app.cfg.overrides_file, DISPLAY, "harmonica-1.txt", "letters")
    response = post(app, "/harmonica/clear", {"page": PAGE})
    assert response.status == 303
    app.queue.run_pending()
    assert runner.calls[-1] == ["harmonica", "--tab=harmonica-1.txt", "--clear", "--", "Cowboy Bebop",
                                "Spokey Dokey"]
    assert "Done: caracole guesses how it is read again." in shown(get(app, dict(response.headers)["Location"]))


@pytest.mark.parametrize("page", [
    f"{FOLDER}/harmonica-2.html", f"{FOLDER}/sheet.html", f"{FOLDER}/harmonica-1.txt", "Unknown/Song/harmonica-1.html",
    f"{FOLDER}/../{FOLDER}/harmonica-1.html", "harmonica-1.html", ""])
def test_a_page_that_is_no_harmonica_tabs_page_caracole_wrote_is_refused(app, spokey, page):
    response = get(app, page_url(page))
    assert response.status == 404 and "There's no such harmonica tab in the library." in shown(response)
    assert post(app, "/harmonica/pin", {"page": page, "as": "letters"}).status == 404


def test_what_cant_be_done_is_refused_and_nothing_queued(app, runner, spokey):
    assert post(app, "/harmonica/pin", {"page": PAGE, "as": "staff"}).status == 400
    assert post(app, "/harmonica/pin", {"page": PAGE, "as": "{not json"}).status == 400
    assert post(app, "/harmonica/pin", {"page": PAGE, "as": json.dumps({"*": "squeak"})}).status == 400
    refused = post(app, "/harmonica/clear", {"page": PAGE})
    assert refused.status == 409 and "caracole guesses how it is read already" in shown(refused)
    add_harmonica(app.cfg.overrides_file, DISPLAY, "harmonica-1.txt", "letters")
    same = post(app, "/harmonica/pin", {"page": PAGE, "as": "letters"})
    assert same.status == 409 and "It is read so already" in shown(same)
    assert post(app, "/harmonica/pin", {"page": PAGE, "as": "letters"}, csrf="other").status == 403
    app.queue.run_pending()
    assert runner.calls == []


def test_a_pinned_tab_offers_the_guess_again(app, spokey):
    add_harmonica(app.cfg.overrides_file, DISPLAY, "harmonica-1.txt", "signs")
    response = get(app, page_url())
    said = shown(response)
    assert "Now: 4 blow · - draw · b bend · * slide, as you set it" in said
    action, fields, button = forms(response)[-1]
    assert (action, fields, button) == ("/harmonica/clear", {"csrf": "tok", "page": PAGE}, "Back to caracole's guess")
    assert "As harptabs.com writes it" not in [b for _, _, b in forms(response)]  # it is, now


def test_a_job_that_failed_says_so_with_its_output(cfg, spokey):
    from caracole.web.app import WebApp
    from caracole.web.jobs import JobQueue

    app = WebApp(cfg, JobQueue(lambda args, emit: (emit("overrides.toml can't be written"), 1)[1], limit=5),
                 allowed=ALLOWED, csrf="tok")
    response = post(app, "/harmonica/pin", {"page": PAGE, "as": "letters"})
    app.queue.run_pending()
    after = get(app, dict(response.headers)["Location"])
    job = int(dict(response.headers)["Location"].rsplit("=", 1)[1])
    assert "Failed: overrides.toml can't be written" in shown(after)
    assert f'href="/{details_href(job)}"' in text(after)


def test_a_pins_request_is_the_songs_change_never_one_of_its_requests(app, spokey):
    from test_web_app import answer, get_json

    post(app, "/harmonica/pin", {"page": PAGE, "as": "letters"})
    [queued] = answer(get_json(app, "/jobs.json"))["jobs"]
    assert (queued["kind"], queued["songId"], queued["line"]["text"]) == ("export", None, "Queued…")
    app.queue.run_pending()
    [done] = answer(get_json(app, "/jobs.json?jobs=1"))["jobs"]
    assert done["line"] == {"tone": "ready", "text": "Its harmonica tab read as you set it",
                            "link": {"label": "Open the tab", "href": quote(PAGE)}, "details": None}
    requests = text(get(app, "/jobs"))
    assert "Its harmonica tab read as you set it" in requests and "Added" not in requests
