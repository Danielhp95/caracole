"""The sync's words (library_assets/sync-words.js, ``window.caracoleSyncWords``), in Chromium: how two unit documents
differ, aspect by aspect, each change, each side's name, the numbers and the dates, as the sheet draws them
(docs/superpowers/plans/2026-11-03-sync-redesign.md §3.7). The script runs alone on a page of its own, with the page's
data block for the sites' names, in a browser whose time zone is Madrid's, so that "this device's time" is pinned."""

from __future__ import annotations

import json

import pytest
from helpers.browser import CHROMIUM_MARKS, Browser

from caracole.library_assets import read

from test_sync_sheet import CAMPFIRE_HERE, CAMPFIRE_THERE, song_doc

pytestmark = CHROMIUM_MARKS  # every test here opens the page in Chromium


@pytest.fixture
def words(tmp_path):
    """``words(expression)``: the value of an expression of ``W`` (caracoleSyncWords) on its page."""
    folder = tmp_path
    page = folder / "words.html"
    icons = {"ug": {"name": "Ultimate Guitar", "letters": "UG"}, "lacuerda": {"name": "LaCuerda", "letters": "LC"}}
    page.write_text("<!doctype html><meta charset=utf-8><body>"
                    f'<script type="application/json" id="songs">{json.dumps({"icons": icons})}</script>'
                    f"<script>{read('sync-words.js')}</script></body>", encoding="utf-8")
    with Browser(folder / "chrome", width=800, height=600) as b:
        b.send("Emulation.setTimezoneOverride", timezoneId="Europe/Madrid")
        b.open(page.as_uri())

        def ask(expression: str):
            return b.js(f"(() => {{ const W = window.caracoleSyncWords; return {expression}; }})()")

        yield ask


def differ(words, kind, here, there):
    return words(f"W.differ({json.dumps(kind)}, {json.dumps(here)}, {json.dumps(there)})")


def test_two_song_documents_are_told_apart_aspect_by_aspect(words):
    here = song_doc("Eagles", "Hotel California", version="key=Am&capo=2", pick=("ug", "1234567"))
    there = song_doc("Eagles", "Hotel California", pick=("ug", "7654321"))
    assert differ(words, "song", here, there) == [
        {"what": "Its own key", "here": "A minor, capo 2", "there": "as the sheet's"},
        {"what": "Its sheet", "here": "Ultimate Guitar · tab 1234567", "there": "Ultimate Guitar · tab 7654321"}]
    # Every other aspect, each a line where the two differ, in the table's order; another override by its table.
    there = song_doc("Eagles", "Hotel California", version="key=Gm&mode=dorian&capo=0", pick=("lacuerda", "eagles/hc"),
                     more=[("ug", "7654321")], lyrics="missing", status="wanted", album="Hotel California")
    there["song"]["review"] = 1
    there["names"]["duration_ms"] = 390_500
    there["names"]["variant"] = "Live"
    there["overrides"]["pin"] = ["https://tabs.ultimate-guitar.com/tab/eagles/hotel-california-chords-1"]
    there["versions"][1]["files"] = [{"name": "tab.txt", "sha256": "d4" * 32, "kept_rank": 2}]
    assert differ(words, "song", here, there) == [
        {"what": "Its own key", "here": "A minor, capo 2", "there": "G minor (dorian), capo 0"},
        {"what": "Its sheet", "here": "Ultimate Guitar · tab 1234567", "there": "LaCuerda · tab eagles/hc"},
        {"what": "Its versions", "here": "1", "there": "2"},
        {"what": "Its kept files", "here": "sheet.txt", "there": "sheet.txt, tab.txt"},
        {"what": "Its lyrics", "here": "found", "there": "missing"},
        {"what": "Its status", "here": "found", "there": "wanted, in review"},
        {"what": "Its album", "here": "–", "there": "Hotel California"},
        {"what": "Its length", "here": "–", "there": "6:31"},
        {"what": "Its variant", "here": "–", "there": "Live"},
        {"what": "An override: [pin]", "here": "–",
         "there": "https://tabs.ultimate-guitar.com/tab/eagles/hotel-california-chords-1"}]
    # Alike but where no line looks: said so, never nothing.
    rated = song_doc("Eagles", "Hotel California")
    rated["versions"][0]["rating"] = 4.9
    assert differ(words, "song", song_doc("Eagles", "Hotel California"), rated) == [
        {"what": "Its other details", "here": "one way", "there": "another way"}]
    assert differ(words, "song", here, here) == []
    # A song one side hasn't got.
    assert differ(words, "song", here, None) == [{"what": "The song", "here": "Kept", "there": "–"}]


def test_an_own_key_reads_as_the_owner_reads_it(words):
    said = words("['key=Am&capo=2', 'key=Gm&mode=dorian&capo=0', 'key=F#&capo=1', 'key=Bb', 't=2&mode=dorian',"
                 " 't=-3&capo=0', 'key=C&capo=0&alt=F.Fmaj7&at=C.x32010', '', 'nonsense'].map(W.ownKey)")
    assert said == ["A minor, capo 2", "G minor (dorian), capo 0", "F♯ major, capo 1", "B♭ major",
                    "the sheet's, 2 up, dorian", "the sheet's, 3 down, capo 0",
                    "C major, capo 0, some chords swapped, its own shapes", "as the sheet's", "nonsense"]


def test_an_own_key_says_the_instrument_it_is_played_on_as_a_versions_name_says_it(words):
    """Two own versions that differ by their instrument alone read apart: ", on the ukulele" (``inst=``, as Make this
    my version writes it), each instrument in viewer/version.py's words; the guitar, none."""
    from caracole.viewer.instruments import GUITAR, INSTRUMENTS
    from caracole.viewer.version import instrument_words

    others = [inst for inst in INSTRUMENTS if inst is not GUITAR]
    entries = [f"key=Am&capo=2&inst={inst.id}" for inst in others] + ["key=Am&capo=2&inst=guitar", "key=Am&inst=lute"]
    said = words(f"{json.dumps(entries)}.map(W.ownKey)")
    assert said == [f"A minor, capo 2, on the {instrument_words(inst)}" for inst in others] + [
        "A minor, capo 2", "A minor, on the lute"]
    assert said[0] == "A minor, capo 2, on the ukulele" and "on the low-G ukulele" in said[1]
    here = song_doc("Eagles", "Hotel California", version="key=Am&capo=2")
    there = song_doc("Eagles", "Hotel California", version="key=Am&capo=2&inst=ukulele")
    assert differ(words, "song", here, there) == [
        {"what": "Its own key", "here": "A minor, capo 2", "there": "A minor, capo 2, on the ukulele"}]


def test_a_songbooks_set_lists_are_told_apart(words):
    assert differ(words, "songbook", CAMPFIRE_HERE, CAMPFIRE_THERE) == [
        {"what": "Its set list", "here": "2 songs", "there": "5 songs"},
        {"what": "Songs added", "here": "–",
         "there": "Pomme - Mononoke, Oasis - Wonderwall, The Beatles - Let It Be"}]
    moved = {"name": "Campfire", "songs": [["Radiohead - Creep", {"key": "A", "capo": 2}],
                                           ["Eagles - Hotel California", {}], ["Blur - Song 2", {}]]}
    assert differ(words, "songbook", CAMPFIRE_HERE, moved) == [
        {"what": "Its set list", "here": "2 songs", "there": "3 songs"},
        {"what": "Songs added", "here": "–", "there": "Blur - Song 2"},
        {"what": "Its order", "here": "Eagles - Hotel California, Radiohead - Creep",
         "there": "Radiohead - Creep, Eagles - Hotel California"},
        {"what": "A song's setting", "here": "Radiohead - Creep: G", "there": "Radiohead - Creep: A, capo 2"}]
    # In a word, what a songbook taken or given brought.
    assert words(f"W.bookChange({json.dumps(CAMPFIRE_HERE)}, {json.dumps(CAMPFIRE_THERE)})") == "3 songs added"
    assert words(f"W.bookChange({json.dumps(CAMPFIRE_THERE)}, {json.dumps(CAMPFIRE_HERE)})") == "3 songs taken out"
    assert words(f"W.bookChange({json.dumps(CAMPFIRE_HERE)}, {json.dumps(moved)})") == (
        "1 song added, its order changed, a song's setting changed")
    assert words(f"W.bookChange(null, {json.dumps(CAMPFIRE_THERE)})") == "5 songs"


def test_a_removal_an_alias_a_ug_page_and_a_blocked_tab_by_their_values(words):
    stone = {"artist": "Blur", "title": "Song 2", "source_ids": [], "removed_at": "2026-11-01T10:00:00Z"}
    assert differ(words, "removed", stone, None) == [{"what": "Removed", "here": "Removed", "there": "Kept"}]
    assert differ(words, "removed", None, stone) == [{"what": "Removed", "here": "Kept", "there": "Removed"}]
    assert differ(words, "alias", {"slugs": ["soda-stereo", "soda"]}, {"slugs": ["soda-stereo"]}) == [
        {"what": "Its slugs", "here": "soda-stereo, soda", "there": "soda-stereo"}]
    assert differ(words, "artist_url", {"name": "Banma", "page": "/artist/banma_1"}, None) == [
        {"what": "Its UG page", "here": "/artist/banma_1", "there": "–"}]
    assert differ(words, "block", None, {"tab": 1234567}) == [{"what": "Blocked", "here": "–", "there": "tab 1234567"}]


def test_each_change_and_number_reads_as_the_owner_reads_it(words):
    said = words("""({
      changed: [W.changed("new", "the phone"), W.changed("changed", W.sides("computer", {kind: "server",
        name: "Studio"}).here), W.changed("gone", W.sides("phone", {kind: "computer"}).here), W.changed(null, "x")],
      tabs: [W.tabs(12130, true), W.tabs(-210, true), W.tabs(1503236), W.tabs(0, true), W.tabs(999), W.tabs(1000)],
      counted: [W.counted(1, "song"), W.counted(12, "song"), W.counted(1204, "index", "indexes")],
      size: [W.size(34000000), W.size(207400000), W.size(3420000), W.size(12000), W.size(1520000000), W.size(null)],
      day: W.when("2026-11-03T18:42:00Z"), date: W.day("2026-11-03T18:42:00Z"), none: W.when(null),
      read: [W.readOn("2026-11-03T08:00:00Z", new Date(2026, 10, 3, 20)),
             W.readOn("2026-11-02T08:00:00Z", new Date(2026, 10, 3, 20)),
             W.readOn("2026-10-30T08:00:00Z", new Date(2026, 10, 3, 20))],
    })""")
    assert said["changed"] == ["added on the phone", "changed on this computer", "removed on the phone", ""]
    assert said["tabs"] == ["+12,130", "−210", "1,503,236", "0", "999", "1,000"]
    assert said["counted"] == ["1 song", "12 songs", "1,204 indexes"]
    assert said["size"] == ["34 MB", "207 MB", "3.4 MB", "0.1 MB", "1.5 GB", ""]
    # What is sent of a size, both in the size's unit and precision (the phone's Sizes.of alike): never MB of GB.
    assert words("""[W.sizeOf(0, 2.1e9), W.sizeOf(1.5e9, 2.1e9), W.sizeOf(9.99e6, 1.2e9), W.sizeOf(120e6, 274e6),
                     W.sizeOf(1.2e6, 3.4e6), W.sizeOf(3.4e6, 3.4e6), W.sizeOf(5000, 12000)]""") == [
        "0.0 of 2.1 GB", "1.5 of 2.1 GB", "0.0 of 1.2 GB", "120 of 274 MB", "1.2 of 3.4 MB", "3.4 of 3.4 MB",
        "0.0 of 0.1 MB"]
    assert said["day"] == "03/11/26, 19:42" and said["date"] == "03/11/26" and said["none"] == ""
    assert said["read"] == ["today", "yesterday", "30/10/26"]


def test_what_an_indexs_merge_added_is_said_as_new_tabs_up_to_date_or_all_new_never_its_whole_size(words):
    said = words("""[
      W.indexNews({before: 1503005, after: 1503236, new: 231}, "here"),
      W.indexNews({before: 1, after: 2, new: 1}, "here"),
      W.indexNews({before: 23105, after: 23105, new: 0}, "here"),
      W.indexNews({before: 0, after: 1503236, new: 1503236}, "here"),
      W.indexNews({before: 0, after: 1, new: 1}, "on the computer"),
      W.indexNews({before: 23105, after: 22895, new: -210}, "here"),
      W.indexNews({before: 10, after: 15}, "here"),
    ]""")
    assert said == [
        {"said": "+231 new tabs", "tone": "up", "all": "1,503,236 in all"},
        {"said": "+1 new tab", "tone": "up", "all": "2 in all"},
        {"said": "up to date", "tone": "", "all": ""},
        {"said": "1,503,236 tabs, all new here", "tone": "up", "all": ""},
        {"said": "1 tab, all new on the computer", "tone": "up", "all": ""},
        {"said": "−210 tabs", "tone": "down", "all": "22,895 in all"},
        {"said": "+5 new tabs", "tone": "up", "all": "15 in all"},  # a report made before `new`
    ]
    # The headline: every site's new tabs, never its total; with none, a fall, else up to date.
    places = '{taken: "here", given: "on Studio"}'
    assert words(f"""[
      W.newTabs([{{before: 1503005, after: 1503236, new: 231}}, {{before: 23105, after: 22895, new: -210}},
                 {{before: 0, after: 1203, new: 1203}}], {places}),
      W.newTabs([{{before: 23105, after: 22895, new: -210}}], {places}),
      W.newTabs([{{before: 5, after: 5, new: 0}}], {places}),
      W.newTabs([{{before: 0, after: 1, new: 1}}], {places}),
      W.newTabs([{{direction: "given", before: 3, after: 43, new: 40}}], {places}),
      W.newTabs([{{direction: "taken", before: 1, after: 232, new: 231}},
                 {{direction: "given", before: 3, after: 43, new: 40}}], {places}),
      W.newTabs([{{direction: "taken", before: 1, after: 232, new: 231}},
                 {{direction: "given", before: 3, after: 3, new: 0}}], {places}),
      W.newTabs([{{direction: "taken", before: 1, after: 1, new: 0}},
                 {{direction: "given", before: 3, after: 3, new: 0}}], {places}),
    ]""") == [
        {"said": "+1,434 new tabs", "tone": "up"}, {"said": "−210 tabs", "tone": "down"},
        {"said": "up to date", "tone": ""}, {"said": "+1 new tab", "tone": "up"},
        {"said": "+40 new tabs", "tone": "up"},  # one direction alone: as for a take
        # Taken and given: each side's new tabs apart, never one sum new to neither.
        {"said": "+231 new here · +40 on Studio", "tone": "up"}, {"said": "+231 new here", "tone": "up"},
        {"said": "up to date", "tone": ""}]
    # Taken and given, a side whose tabs only fell is said too, never left out of the headline (its red row says
    # why); a side with nothing new and none fallen is left out.
    assert words(f"""[
      W.newTabs([{{direction: "taken", before: 23105, after: 22895, new: -210}},
                 {{direction: "given", before: 3, after: 43, new: 40}}], {places}),
      W.newTabs([{{direction: "taken", before: 1, after: 232, new: 231}},
                 {{direction: "given", before: 45, after: 40, new: -5}}], {places}),
      W.newTabs([{{direction: "taken", before: 23105, after: 22895, new: -210}},
                 {{direction: "given", before: 3, after: 3, new: 0}}], {places}),
    ]""") == [
        {"said": "−210 tabs here · +40 on Studio", "tone": ""}, {"said": "+231 new here · −5 tabs on Studio",
                                                                  "tone": ""},
        {"said": "−210 tabs here", "tone": "down"}]
    # The headline's tone: the one tone its sides share, none when they differ.
    assert words(f"""[
      W.newTabs([{{direction: "taken", before: 10, after: 5, new: -5}},
                 {{direction: "given", before: 10, after: 7, new: -3}}], {places}),
      W.newTabs([{{direction: "taken", before: 10, after: 5, new: -5}},
                 {{direction: "given", before: 3, after: 43, new: 40}}], {places}),
      W.newTabs([{{direction: "taken", before: 1, after: 232, new: 231}},
                 {{direction: "given", before: 3, after: 43, new: 40}}], {places}),
    ]""") == [
        {"said": "−5 tabs here · −3 tabs on Studio", "tone": "down"},
        {"said": "−5 tabs here · +40 on Studio", "tone": ""},
        {"said": "+231 new here · +40 on Studio", "tone": "up"}]
    # Which way a row went, for a sync that took and gave.
    assert words('[W.went("taken", "Studio"), W.went("given", "the computer"), W.went("", "x")]') == [
        "taken from Studio", "given to the computer", ""]


def test_each_side_is_named_for_its_device_and_the_other_for_its_kind(words):
    said = words("""[["computer", {kind: "server", name: "Studio", address: "http://10.0.0.7:8737"}],
      ["computer", {kind: "server", name: "", address: "http://10.0.0.7:8737"}], ["phone", {kind: "computer"}],
      ["phone", {kind: "file", name: "horde_logbook"}], ["computer", {kind: "file"}]].map(([d, p]) => {
        const s = W.sides(d, p);
        return [s.here.name, s.here.on, s.here.icon, s.there.name, s.there.on, s.there.the, s.there.whose,
                s.there.short, s.there.icon];
      })""")
    assert said == [
        ["This computer", "On this computer", "tower", "Studio", "On Studio", "Studio", "Studio's", "Studio's",
         "rack"],
        ["This computer", "On this computer", "tower", "http://10.0.0.7:8737", "On http://10.0.0.7:8737",
         "http://10.0.0.7:8737", "http://10.0.0.7:8737's", "http://10.0.0.7:8737's", "rack"],
        ["Phone", "On the phone", "phone", "Computer", "On the computer", "the computer", "the computer's",
         "computer's", "tower"],
        ["Phone", "On the phone", "phone", "File", "In the file", "the file", "the file's", "file's", "file"],
        ["This computer", "On this computer", "tower", "File", "In the file", "the file", "the file's", "file's",
         "file"]]
    assert words("Object.isFrozen(W) && Object.isFrozen(W.sides('phone', {}).here)") is True
