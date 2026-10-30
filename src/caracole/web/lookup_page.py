"""The lookup page of ``caracole serve``: search as you type, pick the song or the tab, read its sheet.

It searches your library and the offline Ultimate Guitar and LaCuerda indexes
as you type (``GET /api/search``: 5–25 ms a query on a full index, up to about
0.15 s for very common words, ug/key_search.py), so finding
a song costs no request to any site. LaCuerda's artists and songs follow
Ultimate Guitar's, with LaCuerda's mark: a song's Get it keeps that LaCuerda
sheet (``lacuerda``), and an artist's Songs lists those the index holds, or,
while caracole hasn't read their page, offers to (``POST /lacuerda/artist``,
one request, a job the page follows on ``/api/jobs``), as it does for a name
under a letter LaCuerda's listings aren't read to yet. harptabs.com's artists and
songs come last, with its mark and the Harmonica badge: a song's Get it keeps that
harmonica tab (``harptabs``), its other tabs under "⋯", and an artist's Songs lists
the tabs the index holds of theirs, or offers to read their page (``POST
/harptabs/artist``, one request, a job followed the same way). gametabs.net's tracks of games
follow, with its mark and their instruments as badges: a song's Get it keeps that tab
(``gametabs``), its other tabs under "⋯". LaCuerda's own search,
which finds the songs of an artist whose page caracole hasn't read, is one
request too (``POST /lacuerda/search``): the page sends it by itself once the
query has settled, the box unchanged for 1.5 s, when ``/api/search`` says so
(``lacuerda_search``), never twice for a query, or offers it as a button, a
line under the results (rows.js ``lacuerdaSearcher``); Enter sends it at once,
by hand as the button does, when its gate sends one. One LaCuerda button at a
time: where a name's page is offered too, Ask LaCuerda sends the search while
its gate lets one go by hand, else reads the page. Its rows come with the
search asked again once it is over (once you are back to All results, when an
artist's songs are open meanwhile). A query may be an
artist's name alone or a title alone, or a word of an artist's name
("skynyrd"): an artist it names is a row of its own, whose Songs lists all
their songs (``GET /api/artist``), and comes first when it leads. A query
nothing matches well, spelled close to an artist's name ("lynrd"), says "Did
you mean" that artist, a row whose Their songs lists their songs the same way. Enter acts
on the answer of the query typed, never of an older one still on the screen:
its ``best`` row, the song you meant; when an artist leads, that artist's
songs; when nothing stands out, nothing, so a guess never spends a request
(LaCuerda's search, which Enter sends too, looks nothing up).
A row's artist is a name to press: it searches for them, as typing their name
would, which asks no site either.
Picking a song (its Get
it, or its name, which does the same), or one of its versions, looks it up
now (``POST /lookup``: one ``caracole get``, which records the pick in
overrides.toml; a song your library has, under any name, is posted as that
song, by its id), and the page follows the request
(``GET /api/jobs/<id>``) stage by stage, the results set aside so that it sits
under the search box: the sheet shows the moment it is kept, scrolled into
view once, then the PDF, the lyrics and the rest arrive. It follows one request
at a time: once you pick another song, an answer of the one before still on its
way (a poll, its sheet) is dropped. The progress line
says what the running stage waits for, and the reasons of the stages left are
listed, not hidden in tooltips. A song of your library with a sheet opens at
once, with no request at all.

Its results are the library's own rows, as index.html's Rows view and its
search of the sites draw them: the page runs library_assets/rows.js
(``ROWS_SCRIPT``) before its own script and builds each result with its row builders
(``resultRow``, ``ugHit``, ``artistHit``, ``siteHit``, ``siteArtist``), with
the mark of where it came from (``icons.page_icons``, inlined as index.html
inlines them) and its other actions under the row's "⋯" (an Ultimate Guitar
song's versions; a song of your library's files). A song of your library
opens as its card does, from its title or its button: its sheet viewer, else
its PDF (a page caracole serves only while it is the one caracole wrote,
``app.written_pages``); one with a sheet and neither is read on the page.

Like index.html it builds every element with ``createElement`` and
``textContent``, never ``innerHTML``: names come from UG's slugs and your own
wanted.txt. Its two scripts and its stylesheet are allowed by their hashes,
its images are the icons' data: URIs, it may connect to the server alone, and
it loads nothing else.
"""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from typing import TYPE_CHECKING, Any

from caracole.inline import json_block, sha256_source
from caracole.library_assets import BASE_STYLE, ROWS_SCRIPT, ROWS_STYLE
from caracole.page_icon import LINK as PAGE_ICON
from caracole.web.top import LIBRARY, top

if TYPE_CHECKING:
    from caracole.library_name import LibraryName

STYLE = BASE_STYLE + ROWS_STYLE + """
.page { max-width: 980px; }
.search { position: sticky; top: 0; z-index: 2; padding: 10px 0; background: var(--bg); }
.search input { width: 100%; height: 54px; padding: 0 16px; border-radius: 14px; border: 1px solid var(--control-edge);
  background: var(--surface); color: var(--text); font: inherit; font-size: 1.15rem; box-shadow: var(--shadow); }
.search input:focus { border-color: var(--focus); outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--focus) 30%, transparent); }
.status { min-height: 1.4em; margin: 6px 2px 0; color: var(--muted); font-size: .85rem; }
/* Under the box, what each site found (ROWS_STYLE's .counts-row), then the words; at rest the words' line alone. */
.said-row { margin: 6px 2px 0; }
.said-row > .status { flex: 1 1 12rem; min-width: 0; margin: 0; }
.group { margin: 18px 0 6px; color: var(--muted); font-size: .78rem; font-weight: 700; letter-spacing: .08em;
  text-transform: uppercase; }
.rows.hits { margin-top: 6px; }
.hint { max-width: 72ch; color: var(--muted); font-size: .85rem; white-space: pre-wrap; }
.artist-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 6px 12px;
  margin: 18px 0 0; }
.artist-head h2 { margin: 0; font-size: 1.2rem; overflow-wrap: anywhere; }
.artist-head h2:focus { outline: none; }
.more-songs { margin: 10px 0 0; }
details.by-name { margin: 22px 0 0; }
/* A search that found nothing has its Look up in its row: the form shows only once that opens it. */
.missed > details.by-name:not([open]) { display: none; }
details.by-name summary { color: var(--muted); font-size: .9rem; font-weight: 600; cursor: pointer; }
.by-name form { display: grid; gap: 10px; margin-top: 10px; grid-template-columns: 1fr; }
.reader { margin: 22px 0 0; padding: 14px 16px; border: 1px solid var(--border); border-radius: 16px;
  background: var(--surface); box-shadow: var(--shadow); scroll-margin-top: var(--bar, 112px); }
.reader-head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 6px 12px; }
.reader h2 { margin: 0; font-size: 1.25rem; overflow-wrap: anywhere; }
details.why { margin: 0 0 10px; color: var(--muted); font-size: .85rem; }
details.why summary { cursor: pointer; }
details.why ul { margin: 6px 0 0; padding-left: 1.2em; }
details.why li.failed { color: var(--failed); }
.said { margin: 4px 0 10px; color: var(--muted); font-size: .9rem; }
.stages { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; padding: 0; list-style: none; }
.stage { display: inline-flex; align-items: center; gap: 6px; padding: 3px 9px; border-radius: 999px;
  background: var(--raised); font-size: .78rem; }
.stage.running { color: var(--wanted); background: var(--wanted-bg); font-weight: 650; }
.stage.done { color: var(--found); background: var(--found-bg); }
.stage.failed { color: var(--failed); background: var(--failed-bg); }
.stage.skipped, .stage.waiting { color: var(--ignored); }
.files { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; }
pre.sheet { margin: 0; padding: 12px; overflow-x: auto; border-radius: 10px; background: var(--bg);
  font: .88rem/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: pre; }
@media (min-width: 720px) {
  .by-name form { grid-template-columns: 1fr 1fr auto; align-items: end; }
  pre.sheet { font-size: .95rem; }
}
/* A thumb's targets, as BASE_STYLE's buttons and ROWS_STYLE's rows are: the folds. */
@media (pointer: coarse) {
  details.by-name summary, details.why summary { min-height: 44px; align-content: center; }
}
"""

SCRIPT = r"""
"use strict";
const root = document.getElementById("lookup");
const csrf = root.dataset.csrf;
const q = document.getElementById("q");
const bar = document.querySelector(".search");
const status = document.getElementById("status");
const counts = document.getElementById("bar-counts");  // the marks of what each site found, beside the words
const saidRow = status.parentElement;
const results = document.getElementById("results");
const byName = document.getElementById("by-name-box");
const reader = document.getElementById("reader");
// The reader's parts stay the same nodes: only the progress line is a live region, read out as it changes.
const heading = document.getElementById("reader-title");
const backToResults = document.getElementById("back");
const saying = document.getElementById("said");
const stageList = document.getElementById("stages");
const whyBox = document.getElementById("why");
const whyList = document.getElementById("why-list");
const fileLinks = document.getElementById("files");
const sheetText = document.getElementById("sheet");
const MIN = 3;
const STATUS = {"found": "Found", "wanted": "Wanted", "ignored": "Ignored"};
// The library's own rows and marks (library_page.ROWS_SCRIPT, run before this script), as index.html has them.
const ICONS = (() => {
  try { return JSON.parse(document.getElementById("icons").textContent || "{}") || {}; } catch (e) { return {}; }
})();
const rowKit = caracoleRows(ICONS, {searchArtist: (name) => searchArtist(name)});
// LaCuerda's own search, sent by itself once the query settles, by Enter or by its button (ROWS_SCRIPT's): once it
// is over, the search again, for the rows it put into LaCuerda's index; an artist's songs open meanwhile stay, and
// All results asks it again (``lcChanged``).
const searcher = rowKit.lacuerdaSearcher(csrf, typedText, (asked) => {
  if (typedText() !== asked) return;
  if (artistOpen) { lcChanged = asked; return; }
  search();
}, (line) => { if (!line.isConnected) results.append(line); });
window.caracole = Object.freeze({resultRow: rowKit.resultRow, sourceMark: rowKit.sourceMark, icons: ICONS});
let typed = 0, inflight = null, timer = null, polling = null, shown = "", lastStages = "";
let shownFor = null;  // the query the results on the screen answer
let shownData = null;  // their answer: what Enter acts on (best) and what leads
let artistOpen = null;  // the artist whose songs are listed in place of the results
let enterFor = null;  // a query Enter was pressed for before its results came: acted on then
let lcChanged = null;  // a query whose answer LaCuerda's search changed while an artist's songs were open
let scrolled = false;  // the sheet was brought into view once already
// The search box's id, sent with each search: one typed on stops this box's older ones alone, never another page's.
const SEARCH_BOX = Math.random().toString(36).slice(2, 12) || "lookup";
// The request the reader shows (openReader counts them): an answer of one before it, come late (a poll, its sheet, its
// lookup's job), is dropped, and its fetches are aborted.
let reading = 0, readingFetches = new AbortController();

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}
function href(path) { return "/" + path.split("/").map(encodeURIComponent).join("/"); }
function letters(s) { return (s.match(/[\p{L}\p{N}]/gu) || []).length; }
function han(s) { return /\p{Script=Han}/u.test(s); }
function typedText() { return q.value.trim().replace(/\s+/g, " "); }
const button = rowKit.button;  // a button as index.html makes them (ROWS_SCRIPT's)
const many = rowKit.many;  // "1 song", "1,234 songs"
function group(title, rows) {
  const list = el("div", "rows hits");
  for (const row of rows) list.append(row);
  return [el("h2", "group", title), list];
}
// The line under the box: words, a live region. ``marks``: the marks beside them say it (the counts, "Searching…"),
// so the words are a screen reader's while those show; anything else shows, after the marks or alone.
function say(text, marks) {
  saidRow.classList.toggle("counted", Boolean(marks));
  status.textContent = text;
}
// What each site found, as marks under the box (ROWS_SCRIPT's countMarks), your songs first: an answer's, or none
// (null), where the results are no search's (an artist's songs) or there is none yet; dimmed while the next comes.
function showCounts(data) {
  counts.replaceChildren(...(data ? rowKit.countMarks(data, data.library.length) : []));
  counts.hidden = !data;
  saidRow.classList.remove("busy");
}
// The sticky search box covers the top of the page: what is scrolled into view lands below it.
function measureBar() { document.documentElement.style.setProperty("--bar", Math.ceil(bar.offsetHeight + 8) + "px"); }

// --- searching ------------------------------------------------------------------------------

function search() {
  const text = typedText();
  if (letters(text) < (han(text) ? 2 : MIN)) {
    results.replaceChildren();
    root.classList.remove("missed");
    shownFor = null;
    showCounts(null);
    say(text ? "Keep typing…" : "");
    return;
  }
  const mine = ++typed;
  if (inflight) inflight.abort();
  inflight = new AbortController();
  say("Searching…", true);
  saidRow.classList.add("busy");
  fetch("/api/search?q=" + encodeURIComponent(text) + "&box=" + SEARCH_BOX,
        {signal: inflight.signal, headers: {"Accept": "application/json"}})
    .then(r => r.json())
    .then(data => {
      if (mine !== typed) return;
      if (data.superseded) { timer = setTimeout(search, 150); return; }
      saidRow.classList.remove("busy");
      if (data.error) { say(data.error); return; }  // the database, say
      show(data, text);
    })
    .catch(e => {
      if (e.name !== "AbortError") { saidRow.classList.remove("busy"); say("The search failed: " + e.message); }
    });
}

function show(data, text) {
  // What found nothing, drawn again for the same query (LaCuerda's search over, say): its "⋯" as it was, the focus on
  // the same control.
  const was = results.querySelector("section.nothing");
  const unfolded = Boolean(was && was.dataset.query === text && was.querySelector('.row-more[aria-expanded="true"]'));
  const focused = was && was.contains(document.activeElement) ? document.activeElement : null;
  results.replaceChildren();
  artistOpen = null;
  const artists = Array.isArray(data.artists) ? data.artists : [];
  const objects = (value) => (Array.isArray(value) ? value : []).filter(x => x && typeof x === "object");
  const lcArtists = objects(data.lacuerda_artists), lc = objects(data.lacuerda);
  const htArtists = objects(data.harptabs_artists), ht = objects(data.harptabs);
  const gt = objects(data.gametabs);
  const n = data.library.length + data.index.length + artists.length + lcArtists.length + lc.length + htArtists.length +
    ht.length + gt.length;
  // The artists and the songs it may have meant first ("Did you mean", a row each), whatever else it found: an
  // artist's row, whose Their songs lists their songs; a song's, as the search's rows of it are (suggestedSong).
  const meant = rowKit.didYouMean(data.suggest, (s) => openSuggested(s), suggestedSong);
  const first = objects(data.suggest).find(x => x.artist);
  // What each site found, under the box, as the library page's bar shows it; in words for a screen reader.
  showCounts(data);
  say(rowKit.countsSaid(data, data.library.length) +
      (meant && first ? " · did you mean " + rowKit.meantName(first) + "?" : ""), true);
  if (meant) results.append(meant);
  if (data.library.length) results.append(...group("In your library", data.library.map(librarySong)));
  // LaCuerda's: its artists, then its songs (the index holds every artist, and the songs of the pages caracole read);
  // first when it alone has the artist the query names ("andres calamaro": lacuerda_leads).
  const lcGroup = lcArtists.length || lc.length ?
    group("On LaCuerda", [...lcArtists.map(siteArtistRow), ...lc.map(lcSong)]) : [];
  if (data.lacuerda_leads === true) results.append(...lcGroup);
  // The artists the query names: first when one leads ("oasis"), after the songs when a song does ("wonderwall").
  const named = artists.length ? group("Artists on Ultimate Guitar", artists.map(artistRow)) : [];
  if (data.lead === "artist") results.append(...named);
  if (data.index.length) results.append(...group("On Ultimate Guitar", data.index.map(ugSong)));
  if (data.lead !== "artist") results.append(...named);
  if (data.lacuerda_leads !== true) results.append(...lcGroup);
  // harptabs.com's: its artists, then its songs (a song's harmonica tabs by an artist whose page caracole read; a tab
  // by its title alone, a possible match, to open), with its mark and the Harmonica badge.
  if (htArtists.length || ht.length) results.append(...group("On harptabs.com", [...htArtists.map(siteArtistRow),
                                                                                ...ht.map(htSong)]));
  // gametabs.net's: its tracks of games, the game the artist, with its mark and their instruments' badges.
  if (gt.length) results.append(...group("On gametabs.net", gt.map(htSong)));
  // What the search says beside its results, as the library page says it (ROWS_SCRIPT's): nothing found, a band,
  // "Not on the sites", over one row: the query, and Look up (the form by name) where a row's Get it is; under its
  // "⋯", Ask LaCuerda for a name under a letter its listings aren't read to yet, whose page may say, and why it may not
  // see an artist. Else those two in a line under the results (notesLine). Where it looked is the marks under the box.
  const unlisted = data.lacuerda_unlisted && typeof data.lacuerda_unlisted === "object" ? data.lacuerda_unlisted : null;
  // Ask LaCuerda, the one LaCuerda button: LaCuerda's search while its gate lets one go by hand, else the name's page.
  const does = {
    request: () => byNameFrom(text), requestText: "Look up", requestLabel: "Look up “" + text + "” by name",
    ask: unlisted ? (go, at) => searcher.ask(text, go) || readThenShow({name: String(unlisted.name || "")}, go, at)
      : null,
  };
  if (!n) {
    const miss = rowKit.nothingFound(data, text, Object.assign(does, {unfolded}));
    results.append(miss);
    const same = focused && [...miss.querySelectorAll(focused.tagName)].find(x => x.className === focused.className);
    if (same) same.focus();
  } else {
    const line = rowKit.notesLine(data, text, does);
    if (line) results.append(line);
  }
  root.classList.toggle("missed", !n);  // one Look up: the form by name waits for the row's
  shownFor = text;
  shownData = data;
  fillByName(text);
  if (lcChanged === text) lcChanged = null;
  if (enterFor === text) { enterFor = null; pickBest(); }  // before LaCuerda's search: a song it looks up goes first
  // LaCuerda's own search, under the results: sent by itself once the query settles, or by an Enter that came first;
  // with no button of its own beside Ask LaCuerda's, which sends it then.
  const lcLine = searcher.show(data.lacuerda_search, text, Boolean(unlisted));
  if (lcLine) results.append(lcLine);
}

// The form by name under the results, filled in as each answer is drawn, as the library page's request form is: with
// the artist and the title the search's answer reads in the query (``names``: song_names.py's reading, the server's;
// the page splits no text itself); else all of it the artist's name when an artist leads (or one LaCuerda alone
// knows), else the title, never the query cut at a space. A field you typed into keeps what you typed, until a lookup
// is sent.
const typedByName = new Set();
for (const name of ["artist", "title"]) {
  document.getElementById("by-name")[name].addEventListener("input", () => typedByName.add(name));
}
function fillByName(text) {
  const f = document.getElementById("by-name");
  const data = shownFor === text && shownData ? shownData : {};
  const objects = (value) => (Array.isArray(value) ? value : []).filter(x => x && typeof x === "object");
  const names = data.names && typeof data.names === "object" && data.names.artist && data.names.title
    ? data.names : null;
  const artistLeads = data.lead === "artist" || (objects(data.lacuerda_artists).length > 0 &&
                                                 !objects(data.lacuerda).length);
  const values = names ? {artist: String(names.artist), title: String(names.title)}
    : artistLeads ? {artist: text, title: ""} : {artist: "", title: text};
  for (const name of ["artist", "title"]) {
    if (!typedByName.has(name)) f[name].value = values[name];
  }
}

// "Look “…” up by name": that form, filled in, open and in view, the focus on its first field still empty.
function byNameFrom(text) {
  const f = document.getElementById("by-name");
  fillByName(text);
  byName.open = true;
  byName.scrollIntoView({block: "center"});
  (f.artist.value ? f.title : f.artist).focus({preventScroll: true});
}

// A name Did you mean offers: their songs, as their row's Songs lists them, by Ultimate Guitar's ``artist_key``, the
// ``slug`` of their LaCuerda page or the ``path`` of their harptabs.com page; else the name searched, as typing it
// would.
function openSuggested(s) {
  if (s.source === "ug" && s.artist_key) { openArtist({artist: String(s.artist), artist_key: String(s.artist_key)}, true); return; }
  if (s.source === "lacuerda" && s.slug) { openSiteArtist({artist: String(s.artist), slug: String(s.slug)}, true); return; }
  if (s.source === "harptabs" && s.path) {
    openSiteArtist({source: "harptabs", artist: String(s.artist), path: String(s.path)}, true);
    return;
  }
  q.value = String(s.artist || "");
  search();
  q.focus();
}

// A song Did you mean offers, as the search's rows of it are: your own row, a song of yours (``library``), which opens
// it; else its row on the first site that has it (``song``: Ultimate Guitar's, LaCuerda's, gtptabs.com's,
// harptabs.com's), whose Get it looks it up as that row's does.
function suggestedSong(s) {
  if (s.library && typeof s.library === "object") return librarySong(s.library);
  const rows = s.song && typeof s.song === "object" ? s.song : {};
  const site = ["ug", "lacuerda", "gtptabs", "harptabs"].find(k => rows[k] && typeof rows[k] === "object");
  if (!site) return null;
  return site === "ug" ? ugSong(rows.ug) : rowKit.siteHit(rows[site], (pick, display) => lookUp(pick, display));
}

// An artist's name on a row, pressed: the search for them, as typing their name runs it (their row first, as an artist
// named whole leads), the focus in the box. It asks no site: the indexes alone.
function searchArtist(name) {
  enterFor = null;
  expand();
  clearTimeout(timer);
  q.value = String(name || "");
  search();
  window.scrollTo(0, 0);
  q.focus({preventScroll: true});
}

// Enter: the answer's best row, its main action (a song of yours opens, an Ultimate Guitar song is looked up);
// when an artist leads, that artist's songs, LaCuerda's when it leads; when nothing stands out, nothing: a guess
// never spends a request.
function pickBest() {
  const data = shownData;
  if (!data || artistOpen) return;
  const best = data.best;
  if (best) {
    const row = [...results.querySelectorAll(".hit")].find(r =>
      (best.library !== undefined && best.library !== null && r.dataset.song === String(best.library)) ||
      (typeof best.ug === "string" && r.dataset.ug === best.ug));
    const main = row && row.querySelector(".row-action .primary");
    if (main) { main.click(); return; }
  }
  const artists = Array.isArray(data.artists) ? data.artists : [];
  if (data.lead === "artist" && artists.length) { openArtist(artists[0], false); return; }
  // LaCuerda's artist when it alone has the one the query names: their Songs, which asks LaCuerda nothing.
  const lcArtists = (Array.isArray(data.lacuerda_artists) ? data.lacuerda_artists : [])
    .filter(a => a && typeof a === "object");
  if (data.lacuerda_leads === true && lcArtists.length) { openSiteArtist(lcArtists[0], false); return; }
  if (results.querySelector(".hit")) say("Nothing stands out: pick one, or type more.");
}

// An artist of the offline index, with its most tabbed songs said: Songs lists every one (ROWS_SCRIPT's row).
function artistRow(a) { return rowKit.artistHit(a, () => openArtist(a, true)); }

function getArtist(key, offset, signal) {
  return fetch("/api/artist?key=" + encodeURIComponent(key) + "&offset=" + offset,
               {signal, headers: {"Accept": "application/json"}})
    .then(r => r.json())
    .then(data => { if (data.error) { say(data.error); return null; } return data; })
    .catch(e => { if (e.name !== "AbortError") say("The list failed: " + e.message); return null; });
}

// An artist's songs in place of the results, yours by them first; typing again, or All results, brings those back.
function openArtist(a, focus) {
  const mine = ++typed;
  if (inflight) inflight.abort();
  inflight = new AbortController();
  say("Listing " + a.artist + "'s songs…");
  getArtist(a.artist_key, 0, inflight.signal).then(data => { if (data && mine === typed) showArtist(data, focus); });
}

function showArtist(data, focus) {
  results.replaceChildren();
  root.classList.remove("missed");
  artistOpen = data.artist_key;
  showCounts(null);  // what is listed is no search's answer
  const head = el("div", "artist-head");
  const name = el("h2", null, data.artist);
  name.tabIndex = -1;
  head.append(name, button("All results", "small", backToSearch, "Back to all the results"));
  results.append(head);
  say(data.artist + ": " + many(data.total, "song") + ".");  // one line: nothing below it moves
  if (data.library.length) results.append(...group("Yours by " + data.artist, data.library.map(librarySong)));
  const [heading, list] = group("On Ultimate Guitar, the most tabbed first", data.songs.map(ugSong));
  results.append(heading, list);
  let listed = data.songs.length;
  if (listed < data.total) {
    const box = el("p", "more-songs");
    const more = button("Show more (" + (data.total - listed) + " left)", "small", () => {
      more.disabled = true;
      getArtist(data.artist_key, listed).then(page => {
        more.disabled = false;
        if (!page || artistOpen !== data.artist_key) return;
        for (const h of page.songs) list.append(ugSong(h));
        listed += page.songs.length;
        if (listed >= page.total || !page.songs.length) box.remove();
        else more.textContent = "Show more (" + (page.total - listed) + " left)";
      });
    }, "Show more of " + data.artist + "'s songs");
    box.append(more);
    results.append(box);
  }
  if (focus) name.focus();
}

function backToSearch() {
  if (lcChanged !== null && lcChanged === typedText()) search();  // LaCuerda's search put rows in meanwhile
  else if (shownData) show(shownData, shownFor);
  q.focus();
}

// A song's sheet viewer or PDF, as its card opens it: a link of the library's, relative to this page.
const opener = rowKit.opener;

// A song of your library, as its row in index.html: its viewer (else its PDF) opens at once; a sheet with
// neither is read here; a song without one is looked up now. Its other files, and Fetch again, under "⋯".
function librarySong(s) {
  const files = Array.isArray(s.links) ? s.links : [];
  const opens = opener(files);
  const again = () => button(s.files.sheet ? "Fetch again" : "Get it now", "small", () => lookUp({song: s.id}, s.display),
                             s.files.sheet ? "Fetch " + s.display + " again" : "Get " + s.display + " now");
  const reading = (label, aria) => button(label, "small" + (opens ? "" : " primary"), () => read(s.display, s.files), aria);
  let action;
  if (opens) action = {label: opens.label, href: opens.href};
  else if (s.files.sheet) action = reading("Read", "Read " + s.display);
  else action = again();
  const here = el("div", "actions");
  if (opens && s.files.sheet) here.append(reading("Read it here", "Read " + s.display + " here"));
  if (s.files.sheet) here.append(again());
  const others = files.filter(f => f && f !== opens)
    .map(f => ({label: f.label, href: f.href, source: f.source === s.source ? null : f.source, download: f.download}));
  const badges = [{kind: s.status, text: STATUS[s.status] || s.status}];
  if (s.review) badges.push({kind: "review", text: "Needs review"});
  badges.push(...rowKit.instrumentBadges(s.instruments));  // what it holds for one instrument, as the hits say
  const row = window.caracole.resultRow({
    title: s.title, href: opens ? opens.href : "", artist: s.artist, onSearch: () => searchArtist(s.artist),
    source: s.source, status: s.status,
    key: typeof s.key === "string" ? s.key : "", badges, action,
    more: [here.childNodes.length ? here : null, {heading: "Files", links: others}].filter(Boolean),
  });
  row.classList.add("hit");
  if (s.status === "found") row.classList.add("have");  // set apart from the sites' rows (rows.css)
  row.dataset.song = String(s.id);
  const main = row.querySelector(".row-action a");
  if (main) main.setAttribute("aria-label", opens.label + " of " + s.display);
  return row;
}

// An Ultimate Guitar song of the offline index, with UG's mark: Get it, and its versions under "⋯", as index.html
// draws it (ROWS_SCRIPT's row); a song your library has, under its own names maybe, is looked up as that song.
function ugSong(h) { return rowKit.ugHit(h, (pick, display) => lookUp(pick, display)); }

// A song of LaCuerda's index, with its mark: Get it looks it up and keeps that LaCuerda sheet (ROWS_SCRIPT's row).
function lcSong(h) { return rowKit.siteHit(h, (pick, display) => lookUp(pick, display)); }

// A song of harptabs.com's index: Get it looks it up and keeps that harmonica tab, its other tabs under "⋯"; a tab by
// its title alone, a link to open (ROWS_SCRIPT's row).
function htSong(h) { return rowKit.siteHit(h, (pick, display) => lookUp(pick, display)); }

// A LaCuerda or harptabs.com artist: Songs lists those the index holds, or offers to read their page (ROWS_SCRIPT's
// rows).
function siteArtistRow(a) { return rowKit.siteArtist(a, () => openSiteArtist(a, true)); }

// A LaCuerda artist, by the slug of their page ({slug}) or by a name ({name}: a page read by name), or a harptabs.com
// artist by their page's path ({harptabs}); ``quiet``, a 404 isn't said.
function getSiteArtist(who, signal) {
  const asked = who.harptabs ? "harptabs=" + encodeURIComponent(who.harptabs)
    : who.slug ? "lacuerda=" + encodeURIComponent(who.slug) : "lacuerda_name=" + encodeURIComponent(who.name || "");
  return fetch("/api/artist?" + asked, {signal, headers: {"Accept": "application/json"}})
    .then(r => r.json().then(data => ({status: r.status, data})))
    .then(({status: code, data}) => {
      if (data.error) { if (!(who.quiet && code === 404)) say(data.error); return null; }
      return data;
    })
    .catch(e => { if (e.name !== "AbortError") say("The list failed: " + e.message); return null; });
}

function openSiteArtist(a, focus) {
  const mine = ++typed;
  if (inflight) inflight.abort();
  inflight = new AbortController();
  const harp = a.source === "harptabs";
  say("Listing the songs of " + a.artist + (harp ? " on harptabs.com…" : " on LaCuerda…"));
  getSiteArtist(harp ? {harptabs: a.path} : {slug: a.slug}, inflight.signal)
    .then(data => { if (data && mine === typed) showSiteArtist(data, focus); });
}

// Read a LaCuerda page ({slug} or {name}), or a harptabs.com one ({harptabs}), from the button ``go`` in ``offer``,
// then list the artist's songs; a read that leaves none to list says what the site answered, under the offer
// (ROWS_SCRIPT's readOutcome).
function readThenShow(who, go, offer) {
  const mine = typed;
  go.disabled = true;
  rowKit.readArtistPage(csrf, who, words => { say(words); }).then(read => {
    if (mine !== typed || !offer.isConnected) return;
    if (read.error) { go.disabled = false; say(read.error); return; }
    getSiteArtist(Object.assign({quiet: true}, who)).then(page => {
      if (mine !== typed || !offer.isConnected) return;
      if (page && page.read) { showSiteArtist(page, true); return; }
      const line = read.job && read.job.line && typeof read.job.line === "object" ? read.job.line : {};
      go.disabled = line.tone === "missing";  // no such page: asking again finds none either
      offer.querySelectorAll(".read-outcome").forEach(x => x.remove());
      const said = rowKit.readOutcome(read.job, Boolean(who.harptabs));
      offer.append(said);
      say(said.firstChild.textContent.trim());
    });
  });
}

function showSiteArtist(data, focus) {
  const harp = data.source === "harptabs";
  const site = harp ? "harptabs.com" : "LaCuerda";
  results.replaceChildren();
  root.classList.remove("missed");
  artistOpen = harp ? "harptabs:" + data.path : "lacuerda:" + data.slug;
  showCounts(null);
  const head = el("div", "artist-head");
  const name = el("h2", null, data.artist);
  name.tabIndex = -1;
  head.append(name, button("All results", "small", backToSearch, "Back to all the results"));
  results.append(head);
  say(data.artist + ": " + (data.read ? many(harp ? data.songs.length : data.total, "song") + " on " +
    site + "." : "caracole hasn't read their page on " + site + " yet."));
  if (data.library.length) results.append(...group("Yours by " + data.artist, data.library.map(librarySong)));
  results.append(...rowKit.siteArtistSongs(data, group, (pick, display) => lookUp(pick, display), null,
    (go, offer) => readThenShow(harp ? {harptabs: data.path} : {slug: data.slug}, go, offer)));
  if (focus) name.focus();
}

q.addEventListener("input", () => {
  searcher.typed();
  enterFor = null;
  expand();
  clearTimeout(timer);
  timer = setTimeout(search, 120);
});
q.addEventListener("keydown", e => {
  if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return;  // the Enter ending a pinyin word types
  e.preventDefault();
  if (results.hidden) { expand(); return; }  // after a pick: the results again, not the pick again
  const text = typedText();
  if (text === shownFor) {
    pickBest();  // first: a song it looks up goes before LaCuerda's search in the queue
    const line = searcher.enter(text, true);  // LaCuerda's search, when its gate sends one
    if (line && !line.isConnected) results.append(line);
    return;
  }
  // The results on the screen answer an older query: search now, and act on its answer, LaCuerda's search with it.
  enterFor = text;
  searcher.enter(text, false);
  clearTimeout(timer);
  search();
});

// While a sheet is read the results step aside, so it sits right under the search box; typing brings them back.
function collapse() {
  results.hidden = true;
  byName.hidden = true;
  backToResults.hidden = !results.childElementCount;
}
function expand() {
  if (!results.hidden) return;
  results.hidden = false;
  byName.hidden = false;
  backToResults.hidden = true;
}
backToResults.addEventListener("click", () => { expand(); window.scrollTo({top: 0}); q.focus(); });

// --- looking up, and reading -----------------------------------------------------------------

function lookUp(pick, display) {
  const body = new URLSearchParams({csrf});
  for (const name of ["song", "artist", "title", "ug", "tab", "lacuerda", "harptabs", "gametabs"]) {
    if (pick[name]) body.set(name, pick[name]);
  }
  openReader(display, "Asking for it…");
  const mine = reading;
  fetch("/lookup", {method: "POST", body, headers: {"Accept": "application/json"}})
    .then(r => r.text().then(text => ({r, text})))
    .then(({r, text}) => {
      if (mine !== reading) return;  // another song is read now: this one is queued all the same
      let data = null;
      try { data = JSON.parse(text); } catch (e) { data = null; }
      if (!r.ok || !data) { refused(r.status, data, text); return; }
      history.replaceState(null, "", "/lookup?job=" + data.job);
      follow(data.url);
    })
    .catch(e => { if (mine === reading) said("The request failed: " + e.message); });
}

// A refusal: its sentence; a page's, as its text. A form token older than the server needs a reload.
function refused(code, data, text) {
  let why = data && data.error;
  if (!why) {
    const page = new DOMParser().parseFromString(text || "", "text/html");
    const words = (page.querySelector("main, .page, body") || page.documentElement).textContent || "";
    why = words.replace(/\s+/g, " ").trim().slice(0, 240) || "caracole answered " + code + ".";
  }
  said(why);
  if ((data && data.reload) || code === 403) {
    const again = el("a", "btn small primary", "Reload the page");
    again.href = location.pathname + location.search;
    fileLinks.replaceChildren(again);
  }
}

function openReader(display, words) {
  collapse();
  reader.hidden = false;
  heading.textContent = display;
  saying.textContent = words;
  stageList.replaceChildren();
  whyList.replaceChildren();
  whyBox.hidden = true;
  fileLinks.replaceChildren();
  sheetText.textContent = "";
  sheetText.hidden = true;
  shown = ""; lastStages = ""; scrolled = false;
  if (polling) clearTimeout(polling);
  reading += 1;
  readingFetches.abort();
  readingFetches = new AbortController();
  measureBar();
  reader.scrollIntoView({block: "start"});
}
function said(words) { if (saying.textContent !== words) saying.textContent = words; }

function follow(url) {
  const mine = reading;
  fetch(url, {signal: readingFetches.signal, headers: {"Accept": "application/json"}})
    .then(r => r.ok ? r.json() : Promise.reject(new Error("that request is gone")))
    .then(job => {
      if (mine !== reading) return;  // another request is read now
      progress(job);
      if (job.active) polling = setTimeout(() => follow(url), 500);
    })
    .catch(e => { if (mine === reading) said(e.message); });
}

function doing(stage) { return stage.detail ? stage.label + ": " + stage.detail : stage.label + "…"; }

function progress(job) {
  if (job.song) heading.textContent = job.song.display;
  stageList.replaceChildren();
  for (const s of job.steps) {
    const li = el("li", "stage " + s.state, s.label);
    if (s.detail) li.title = s.detail;
    stageList.append(li);
  }
  // What was left, and why, where touch and keys reach it too (a title shows on hovering alone).
  const why = job.steps.filter(s => s.detail && (s.state === "skipped" || s.state === "failed"));
  whyList.replaceChildren(...why.map(s => el("li", s.state, s.label + ": " + s.detail)));
  whyBox.hidden = !why.length;
  const running = job.steps.find(s => s.state === "running");
  if (job.files.sheet) {
    said(job.active ? "Here it is" + (job.seconds_to_sheet !== null ? ", in " + job.seconds_to_sheet.toFixed(1) + " s" : "")
         + (running ? "; still getting: " + running.label.toLowerCase() : "") : "Done.");
  } else if (job.active) {
    said(job.state === "queued" ? "Waiting for the request before it…" : (running ? doing(running) : "Working…"));
  } else if (job.state === "cancelled") {  // in the Requests tab, before it ran
    said("Cancelled before it ran: look it up again to get it.");
  } else {
    const failed = job.steps.filter(s => s.detail && s.state !== "done").map(s => s.label + ": " + s.detail);
    said("No sheet this time. " + failed.join(" "));
  }
  const now = job.steps.map(s => s.state).join(",");
  links(job.files);
  if (job.files.sheet && (now !== lastStages || !shown)) sheet(job.files.sheet);
  lastStages = now;
}

function links(files) {
  const box = fileLinks;
  box.replaceChildren();
  for (const [name, label] of [["viewer", "Viewer"], ["pdf", "PDF"], ["sheet", "Text"]]) {
    if (!files[name]) continue;
    const a = el("a", "btn small", label);
    a.href = href(files[name]);
    box.append(a);
  }
  const jobs = el("a", "btn small", "Requests");
  jobs.href = "/#tab=requests";
  box.append(jobs);
}

function sheet(path) {
  const mine = reading, signal = readingFetches.signal;
  fetch(href(path), {signal}).then(r => r.ok ? r.text() : Promise.reject(new Error(r.status))).then(text => {
    if (mine !== reading || text === shown) return;  // another request's sheet is read now
    shown = text;
    sheetText.textContent = text;
    sheetText.hidden = false;
    if (!scrolled) {  // once, the moment it can be read, laid out: later sheets leave your place alone
      scrolled = true;
      requestAnimationFrame(() => { measureBar(); reader.scrollIntoView({block: "start"}); });
    }
  }).catch(() => {});
}

function read(display, files) {
  openReader(display, "From your library.");
  links(files);
  sheet(files.sheet);
}

// --- by name, for a song the index doesn't know -----------------------------------------------

document.getElementById("by-name").addEventListener("submit", e => {
  e.preventDefault();
  const f = e.target;
  const artist = f.artist.value.trim(), title = f.title.value.trim();
  if (!artist || !title) return;
  typedByName.clear();
  lookUp({artist, title}, artist + " - " + title);
});

// Where a search found nothing, the form by name shows only once its row's Look up opens it: folded again, it goes, and
// the focus goes back to Look up.
byName.addEventListener("toggle", () => {
  if (byName.open || !root.classList.contains("missed")) return;
  const go = results.querySelector("section.nothing .row-action button");
  if (go && (document.activeElement === document.body || byName.contains(document.activeElement))) go.focus();
});
window.addEventListener("resize", measureBar);
measureBar();
const params = new URLSearchParams(location.search);
const job = params.get("job");
if (job && /^\d+$/.test(job)) { openReader("Your request", "Following it…"); follow("/api/jobs/" + job); }
if (params.get("q")) { q.value = params.get("q"); search(); }
q.focus();
"""

LOOKUP_CSP = (
    f"default-src 'none'; script-src {sha256_source(ROWS_SCRIPT)} {sha256_source(SCRIPT)}; "
    f"style-src {sha256_source(STYLE)}; img-src data:; "
    "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)

_BODY = """<body>
<div class="page" id="lookup" data-csrf="__CSRF__">
__TOP__<div class="search" role="search">
  <label class="visually-hidden" for="q">Song or artist</label>
  <input id="q" type="search" placeholder="Song or artist" autocomplete="off" autocapitalize="off" autocorrect="off"
    spellcheck="false" enterkeyhint="search">
  <div class="said-row counts-row">
    <ul class="counts" id="bar-counts" aria-label="Found on each site" hidden></ul>
    <p class="status" id="status" aria-live="polite"></p>
  </div>
</div>
<div id="results"></div>
<details class="by-name" id="by-name-box">
  <summary>Not in the list? Look it up by name</summary>
  <form id="by-name" method="post" action="/lookup">
    <input type="hidden" name="csrf" value="__CSRF__">
    <label class="f">Artist<input name="artist" required maxlength="200" autocomplete="off"></label>
    <label class="f">Title<input name="title" required maxlength="300" autocomplete="off"></label>
    <button class="btn primary" type="submit">Look it up</button>
  </form>
</details>
<section class="reader" id="reader" aria-labelledby="reader-title" hidden>
  <div class="reader-head">
    <h2 id="reader-title"></h2>
    <button class="btn small" id="back" type="button" hidden>Back to the results</button>
  </div>
  <p class="said" id="said" role="status" aria-live="polite"></p>
  <ul class="stages" id="stages"></ul>
  <details class="why" id="why" hidden>
    <summary>What was left, and why</summary>
    <ul id="why-list"></ul>
  </details>
  <div class="files" id="files"></div>
  <pre class="sheet" id="sheet" hidden></pre>
</section>
</div>
"""


def lookup_page(csrf: str, icons: Mapping[str, Any] | None = None, *, library_name: LibraryName | None = None) -> str:
    """The whole page, with the form token every POST carries and each source's mark (``icons.page_icons``);
    ``library_name``, the library the server shows (library_name.py), in its header and its tab's title."""
    token = escape(csrf, quote=True)
    title = library_name.title("Look up") if library_name is not None else "Look up · caracole"
    links = LIBRARY + '<a class="navlink" href="/#tab=requests">Requests</a>'
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="light dark">\n<meta name="referrer" content="same-origin">\n'
        f"{library_name.icon() if library_name is not None else PAGE_ICON}<title>{escape(title)}</title>\n"
        f"<style>{STYLE}</style>\n</head>\n"
        + _BODY.replace("__TOP__", top("Look up a song", links, library_name=library_name))
        .replace("__CSRF__", token)
        + json_block("icons", dict(icons or {}))
        + f"<script>{ROWS_SCRIPT}</script>\n<script>{SCRIPT}</script>\n</body>\n</html>\n"
    )
