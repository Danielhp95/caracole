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


# --- an auto sheet: who made it, from what, over which words (E15) ---------------------------------------------------

HERE_ID, THERE_ID, THIRD_ID = "a1b2c3d4e5f60718", "0f1e2d3c4b5a6978", "9a8b7c6d5e4f3021"
LRCLIB = json.dumps({"plain": "La la", "synced": "[00:01.00] La la", "instrumental": False, "duration": 200.0,
                     "lrclib_id": 9, "raw": {}, "provider": "lrclib", "url": None})


def auto_doc(raw, *, lyrics="found", lyrics_json=LRCLIB, human=False) -> dict:
    """A song's document whose auto sheet's version keeps ``raw`` (a dict, written as its JSON text, or the text
    itself), beside a human sheet with ``human``."""
    doc = song_doc("Nobody", "River Road", pick=("ug", "1234567") if human else ("auto", "42"), lyrics=lyrics)
    auto = doc["versions"][0]
    if human:
        auto = dict(auto, provider="auto", tab_id="42", pick_rank=2, files=[])
        doc["versions"].insert(0, auto)
    auto["raw"] = raw if isinstance(raw, str) or raw is None else json.dumps(raw)
    auto["files"] = [{"name": "sheet (auto).txt", "sha256": "e5" * 32, "kept_rank": 1}]
    doc["song"]["lyrics_json"] = lyrics_json
    return doc


def auto_of(words, doc, makers=None) -> str:
    return words(f"W.autoOf({json.dumps(doc)}, {json.dumps(makers)})")


MAKERS = {"here": {"id": HERE_ID, "the": "the phone"}, "there": {"id": THERE_ID, "the": "the computer"}}
PHONE = {"made_on": "phone", "made_by": HERE_ID, "audio_name": "song.mp3", "lyrics": "synced"}
COMPUTER = {"made_on": "computer", "made_by": THERE_ID, "youtube": {"id": "dQw4w9WgXcQ", "title": "River Road"},
            "lyrics": "synced", "lyrics_source": "transcript"}


def test_an_auto_sheet_says_who_made_it_from_what_and_over_which_words(words):
    assert auto_of(words, auto_doc(PHONE), MAKERS) == "made on the phone from “song.mp3”, chords over LRCLIB's timed lyrics"
    assert auto_of(words, auto_doc(COMPUTER, lyrics="missing", lyrics_json=None), MAKERS) == (
        "made on the computer from its YouTube audio, chords over the transcribed lyrics")
    assert auto_of(words, song_doc("Nobody", "River Road")) == "none"  # a human sheet alone
    assert auto_of(words, auto_doc(PHONE, human=True), MAKERS).startswith("made on the phone")  # beside one
    # The maker: this side, the other, a third caracole by its id; with no ids, the device the record names.
    assert [auto_of(words, auto_doc(dict(PHONE, made_by=by, made_on=on)), makers) for by, on, makers in [
        (THERE_ID, "phone", MAKERS),  # the other side's id wins over the device the record names
        (THIRD_ID, "phone", MAKERS),
        (THIRD_ID, "computer", None), (HERE_ID, "phone", None),
        (HERE_ID, "phone", {"here": {"id": HERE_ID, "the": "this computer"}, "there": {"id": THERE_ID, "the": None}}),
        (THERE_ID, "phone", {"here": {"id": HERE_ID, "the": "this computer"}, "there": {"id": THERE_ID, "the": None}}),
        (THIRD_ID, "tablet", None),  # a device we don't know: no maker said
        (THIRD_ID, "phone", {"here": {"id": HERE_ID, "the": "the phone"}, "there": {}}),  # the other's id unknown
        (THERE_ID, "computer", {"here": {"id": HERE_ID, "the": "this computer"},
                                "there": {"id": THERE_ID, "the": "Studio"}}),  # a file of another computer's, by name
    ]] == ["made on the computer from “song.mp3”, chords over LRCLIB's timed lyrics",
           "made on another caracole from “song.mp3”, chords over LRCLIB's timed lyrics",
           "made on the computer from “song.mp3”, chords over LRCLIB's timed lyrics",
           "made on the phone from “song.mp3”, chords over LRCLIB's timed lyrics",
           "made on this computer from “song.mp3”, chords over LRCLIB's timed lyrics",
           "made on the phone from “song.mp3”, chords over LRCLIB's timed lyrics",  # a file's caracole: its device
           "made from “song.mp3”, chords over LRCLIB's timed lyrics",
           "made from “song.mp3”, chords over LRCLIB's timed lyrics",  # never a guess: no maker said
           "made on Studio from “song.mp3”, chords over LRCLIB's timed lyrics"]
    # A device the record names with no maker's id: named if it is one we know, else no maker said.
    assert [auto_of(words, auto_doc({"made_on": on, "audio_name": "song.mp3", "lyrics": "none"}), MAKERS)
            for on in ("phone", "computer", "tablet", 7)] == [
        "made on the phone from “song.mp3”, chords only", "made on the computer from “song.mp3”, chords only",
        "made from “song.mp3”, chords only", "made from “song.mp3”, chords only"]
    # No maker stated (a sheet made before who made it was kept): no maker clause, never a guess.
    old = {"audio": "/home/me/Music/River Road.mp3", "model": "btc_large_voca", "lyrics": "plain"}
    assert auto_of(words, auto_doc(old), MAKERS) == "chords over LRCLIB's plain lyrics"
    assert auto_of(words, auto_doc(dict(old, audio_name="River Road.mp3")), MAKERS) == (
        "made from “River Road.mp3”, chords over LRCLIB's plain lyrics")
    assert auto_of(words, auto_doc({}), MAKERS) == "an auto sheet"
    assert auto_of(words, auto_doc(None), MAKERS) == "an auto sheet"
    assert auto_of(words, auto_doc("not json"), MAKERS) == "an auto sheet whose record can't be read"
    assert auto_of(words, auto_doc("[1, 2]"), MAKERS) == "an auto sheet whose record can't be read"
    # From what: an upload's or a purchase's name, its YouTube audio, or nothing the record names.
    assert auto_of(words, auto_doc(dict(PHONE, audio_name=None)), MAKERS) == (
        "made on the phone, chords over LRCLIB's timed lyrics")


def test_an_auto_sheet_says_each_kind_of_words_it_lays_its_chords_over(words):
    def said(raw, **doc):
        return auto_of(words, auto_doc({"made_on": "phone", "made_by": HERE_ID, **raw}, **doc), MAKERS)

    def stored(provider, **more):
        return json.dumps({"plain": "La la", "synced": "[00:01.00] La la", "instrumental": False, "duration": None,
                           "lrclib_id": None, "raw": {}, **({} if provider is None else {"provider": provider}),
                           **more})

    assert [said({"lyrics": kind}, lyrics_json=stored(site)) for kind in ("synced", "plain")
            for site in ("lrclib", "megalobiz", "azlyrics", None, "elsewhere")] == [
        "made on the phone, chords over LRCLIB's timed lyrics",
        "made on the phone, chords over Megalobiz's timed lyrics",
        "made on the phone, chords over AZLyrics' timed lyrics",
        "made on the phone, chords over LRCLIB's timed lyrics",  # stored before lyrics named their site: LRCLIB's
        "made on the phone, chords over timed lyrics",  # a site we don't name: none named
        "made on the phone, chords over LRCLIB's plain lyrics",
        "made on the phone, chords over Megalobiz's plain lyrics",
        "made on the phone, chords over AZLyrics' plain lyrics",
        "made on the phone, chords over LRCLIB's plain lyrics",
        "made on the phone, chords over plain lyrics"]
    # The song's lyrics not found now, or unreadable: the words' kind alone, no site guessed.
    assert said({"lyrics": "synced"}, lyrics="missing", lyrics_json=None) == "made on the phone, chords over timed lyrics"
    assert said({"lyrics": "plain"}, lyrics_json="{not json") == "made on the phone, chords over plain lyrics"
    assert said({"lyrics": "synced"}, lyrics_json=json.dumps({"id": 9, "plainLyrics": "La",
                                                              "syncedLyrics": "[00:01.00] La"})) == (
        "made on the phone, chords over LRCLIB's timed lyrics")  # a bare LRCLIB record, as lyrics.py reads one
    # The site is named only where the song's lyrics hold the kind the sheet says it was laid over: never an
    # impossible "AZLyrics' timed lyrics".
    assert said({"lyrics": "synced"}, lyrics_json=stored("azlyrics", synced=None)) == (
        "made on the phone, chords over timed lyrics")
    assert said({"lyrics": "synced"}, lyrics_json=json.dumps({"id": 9, "plainLyrics": "La"})) == (
        "made on the phone, chords over timed lyrics")
    assert said({"lyrics": "plain"}, lyrics_json=stored("lrclib", plain="  ")) == (
        "made on the phone, chords over plain lyrics")
    assert said({"lyrics": "synced"}, lyrics_json=stored("megalobiz", synced="")) == (
        "made on the phone, chords over timed lyrics")
    assert said({"lyrics": "synced", "lyrics_source": "transcript"}, lyrics="missing", lyrics_json=None) == (
        "made on the phone, chords over the transcribed lyrics")
    assert said({"lyrics": "none"}, lyrics="missing", lyrics_json=None) == "made on the phone, chords only"
    assert said({"lyrics": "none", "heard_nothing": True}, lyrics="missing", lyrics_json=None) == (
        "made on the phone, chords only: nothing sung was heard")
    assert said({"lyrics": "none", "heard_nothing": True, "not_sung_by": "you"}, lyrics="missing",
                lyrics_json=None) == "made on the phone, chords only: you said it isn't sung"
    assert said({"lyrics": "none"}, lyrics="instrumental", lyrics_json=None) == (
        "made on the phone, chords only: the lyrics sites say it's instrumental")
    assert said({"lyrics": "none"}, lyrics_json=stored("lrclib", instrumental=True, plain="")) == (
        "made on the phone, chords only: the lyrics sites say it's instrumental")
    assert said({"lyrics": "something new"}) == "made on the phone"


def test_a_files_name_is_text_cut_short_never_markup(words):
    hostile = '<img src=x onerror="window.pwned=1"> "quoted" \'too\'.mp3'
    assert auto_of(words, auto_doc(dict(PHONE, audio_name=hostile)), MAKERS) == (
        f"made on the phone from “{hostile}”, chords over LRCLIB's timed lyrics")
    long = "a" * 100 + ".mp3"
    said = auto_of(words, auto_doc(dict(PHONE, audio_name=long)), MAKERS)
    assert said == "made on the phone from “" + "a" * 59 + "…”, chords over LRCLIB's timed lyrics"
    assert auto_of(words, auto_doc(dict(PHONE, audio_name="  two\nlines\t.mp3 ")), MAKERS).startswith(
        "made on the phone from “two lines .mp3”")
    # Control and format characters a device wrote (a NUL, a right-to-left override) are taken out, never shown.
    assert auto_of(words, auto_doc(dict(PHONE, audio_name="evil\u202egnp.mp3\u0000\u200b")), MAKERS) == (
        "made on the phone from “evilgnp.mp3”, chords over LRCLIB's timed lyrics")
    assert auto_of(words, auto_doc(dict(PHONE, audio_name="\u202e\u0000")), MAKERS) == (
        "made on the phone, chords over LRCLIB's timed lyrics")
    assert auto_of(words, auto_doc(dict(PHONE, audio_name="\u202e" * 30 + "b" * 70)), MAKERS) == (
        "made on the phone from “" + "b" * 59 + "…”, chords over LRCLIB's timed lyrics")  # cut after
    assert auto_of(words, auto_doc(dict(PHONE, audio_name="🎸" * 70)), MAKERS) == (
        "made on the phone from “" + "🎸" * 59 + "…”, chords over LRCLIB's timed lyrics")  # by characters


def test_two_auto_sheets_that_differ_in_maker_and_words_are_one_line_each_side(words):
    here, there = auto_doc(PHONE), auto_doc(COMPUTER, lyrics="missing", lyrics_json=None)
    assert words(f"W.differ('song', {json.dumps(here)}, {json.dumps(there)}, {json.dumps(MAKERS)})") == [
        {"what": "Its auto sheet", "here": "made on the phone from “song.mp3”, chords over LRCLIB's timed lyrics",
         "there": "made on the computer from its YouTube audio, chords over the transcribed lyrics"},
        {"what": "Its lyrics", "here": "found", "there": "missing"}]
    # One side alone has one: the other's none (and its versions and files say the rest, as ever).
    alone = differ(words, "song", here, song_doc("Nobody", "River Road"))
    assert alone[0] == {"what": "Its sheet", "here": "auto · tab 42", "there": "Ultimate Guitar · tab 1234567"}
    assert {"what": "Its auto sheet", "here": "made on the phone from “song.mp3”, chords over LRCLIB's timed lyrics",
            "there": "none"} in alone
    # Alike: no line.
    assert differ(words, "song", here, auto_doc(PHONE)) == []
    # Alike but for who made it: that one line, and no other aspect.
    other = auto_doc(dict(PHONE, made_by=THERE_ID))
    assert words(f"W.differ('song', {json.dumps(here)}, {json.dumps(other)}, {json.dumps(MAKERS)})") == [
        {"what": "Its auto sheet", "here": "made on the phone from “song.mp3”, chords over LRCLIB's timed lyrics",
         "there": "made on the computer from “song.mp3”, chords over LRCLIB's timed lyrics"}]
