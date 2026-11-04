"""How a page names the library it shows, for the phone: tests/conformance/vectors/web/library_name.jsonl, which the
Kotlin port's ``server.http.LibraryName`` replays (lane prep-core).

Every page the phone writes itself names the library as caracole serve's do (library_name.py's ``LibraryName``), with
the badge ``Phone`` beside it: the computer's library name once a sync gave it (kv ``phone:settings``' ``name``), and
none before (``""``), when the header says caracole and the badge alone. A record a call:

- ``{"fn": "caracole.library_name.LibraryName.title", "args": [name, badge, page], "out": text}``: a tab's title;
- ``{"fn": "caracole.library_name.LibraryName.markup", "args": [name, badge, tag], "out": markup}``: the header's;
- ``{"fn": "caracole.library_name.LibraryName.icon", "args": [name, badge], "out": link}``: the tab's icon, which
  only the badge decides (two names a badge).

``badge`` is ``"Phone"``, ``null`` (a page with none, as the written index.html's), caracole serve's ``SCRATCH`` and one
of markup characters; ``name`` none (``""``), a plain one, and names with markup characters and other scripts, each
escaped as ``html.escape(quote=True)`` escapes them.
"""

from __future__ import annotations

from caracole.library_name import LibraryName
from helpers.corpus import VECTORS, check, jsonl

MADE_BY = "tests/test_conformance_library_name.py"
PHONE = "Phone"  # the badge every page the phone writes itself shows (server.http.MessagePage.PHONE_BADGE)

NAMES = [
    "",  # no name taken from the computer yet
    "Music",
    "Phone",
    "Dani's songs",
    '<b>"Tabs" & chords</b>',
    "Ana & Luis's <3",
    "宋冬野的歌",
    "  spaced  ",
    "é́ ‍🎸",
]
BADGES = [PHONE, None, "Scratch library", "<i>&</i>"]
PAGES = ["", "Look up", "Sync", "Not found", "Hotel California · Eagles", "<script> & 'quotes'"]
TAGS = ["span", "p"]


def records() -> list[dict]:
    out: list[dict] = []
    for badge in BADGES:
        for name in NAMES:
            shown = LibraryName(name, badge)
            for page in PAGES:
                out.append({"fn": "caracole.library_name.LibraryName.title", "args": [name, badge, page],
                            "out": shown.title(page)})
            for tag in TAGS:
                out.append({"fn": "caracole.library_name.LibraryName.markup", "args": [name, badge, tag],
                            "out": shown.markup(tag)})
            if name in ("", "Music"):  # the icon is the badge's alone
                out.append({"fn": "caracole.library_name.LibraryName.icon", "args": [name, badge],
                            "out": shown.icon()})
    return out


def test_library_name_jsonl_is_library_names_answers():
    check(VECTORS / "web" / "library_name.jsonl", jsonl(records(), corpus="web/library_name", made_by=MADE_BY))


def test_the_phone_with_no_name_says_caracole_and_its_badge_once():
    phone = LibraryName("", PHONE)
    assert phone.title() == "Phone · caracole"
    assert phone.title("Look up") == "Phone · Look up · caracole"
    assert phone.markup("p") == ('<p class="libname"><span class="name"></span> '
                                 '<span class="scratch" title="Not your usual library">Phone</span></p>')
    assert LibraryName("Music", PHONE).title() == "Phone · caracole · Music"
