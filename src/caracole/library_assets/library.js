
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const list = byId("list");
  const input = byId("q");
  const clear = byId("clear");
  const allButton = byId("all");
  const barStatus = byId("bar-status");
  const results = byId("results");
  const found = byId("found");
  const sort = byId("sort");
  const count = byId("count");
  const jump = byId("jump");
  const chips = Array.from(document.querySelectorAll(".chip[data-show]"));
  const artistChip = byId("artist");
  const viewToggle = byId("view-toggle");
  const viewPanel = byId("view-panel");
  const JUMP_FROM = 40;  // songs shown before the A-Z strip is worth its room: fewer, and a thumb scrolls

  let data;
  try {
    data = JSON.parse(byId("songs").textContent);
  } catch (err) {
    list.appendChild(el("p", "empty", "This page's song list can't be read. Run caracole todo to write it again."));
    return;
  }
  const songs = Array.isArray(data.songs) ? data.songs : [];
  const table = data.fold && typeof data.fold === "object" ? data.fold : {};
  const own = Object.prototype.hasOwnProperty;
  const listOf = (value) => (Array.isArray(value) ? value : []);
  // Served by caracole serve: its forms' token, and the songs it is fetching already.
  const server = data.server && typeof data.server === "object" ? data.server : null;
  const busy = new Set(listOf(server && server.busy).map(Number));
  const removing = new Set(listOf(server && server.removing).map(Number));
  // A timer of the page's, in ms: its own, unless the tests that drive it on real time set it (WebControls.timers).
  const paced = (name, ms) => {
    const set = server && server.timers && typeof server.timers === "object" ? Number(server.timers[name]) : NaN;
    return set > 0 && set < Infinity ? set : ms;
  };

  // The same folding as caracole's normalize.fold: NFKD, no accents, a few letters spelled out, lowercase.
  const fold = (text) => {
    let out = "";
    for (const ch of String(text).normalize("NFKD").replace(/\p{Mn}/gu, "")) {
      out += own.call(table, ch) ? table[ch] : ch;
    }
    return out.toLowerCase();
  };
  // Apostrophes go, as in caracole's keys: "don’t" and "don't" both find "dont" (the search text has every
  // name without punctuation too). Other punctuation is only trimmed off the ends of a word.
  const APOSTROPHES = /['’‘`´ʼ]/g;
  const EDGES = /^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu;
  const term = (word) => word.replace(APOSTROPHES, "").replace(EDGES, "");
  const terms = (folded) => folded.split(/\s+/).map(term).filter(Boolean);
  // Each word in single quotes, each ' written '\'': bash and zsh expand ! even in double quotes.
  const shellQuote = (text) => "'" + String(text).replace(/'/g, "'\\''") + "'";
  const hay = songs.map((s) => String(s.search || ""));
  const inits = songs.map((s) => String(s.initials || ""));  // a title's initials: "wywh" finds Wish You Were Here

  const STATUS_TEXT = { found: "Found", wanted: "Wanted", ignored: "Ignored" };
  const LYRICS_TEXT = { pending: "Lyrics pending", missing: "No lyrics found", instrumental: "Instrumental" };
  const label = (texts, value) => (own.call(texts, value) ? texts[value] : "");
  const SHOWS = {
    all: () => true,
    found: (s) => s.status === "found",
    wanted: (s) => s.status === "wanted",
    review: (s) => Boolean(s.review) && s.status !== "ignored",
  };
  const CHIP_TEXT = { found: "found songs", wanted: "wanted songs", review: "songs that need review" };
  const SORTS = ["artist", "title", "recent"];
  const LETTERS = { artist: "artistLetter", title: "titleLetter" };  // the A-Z strip's letter, by sort
  // A key is "A minor" or "C" (keys.py); where it came from, as keys.SOURCES says.
  const KEY_SOURCES = { tab: "from the tab", chords: "estimated from the chords", audio: "from the audio" };
  const keyName = (key) => (/ minor$/.test(key) ? key : key + " major");
  const keyText = (s) => "Key " + keyName(String(s.key)) +
    (label(KEY_SOURCES, s.key_source) ? " (" + label(KEY_SOURCES, s.key_source) + ")" : "");
  // Which key a spelling names, as keys.same_key compares them: the tonic's pitch class and the mode, so
  // "F# minor" and "Gb minor" are one key. It reads keys as keys.py writes them, and as typed: "f#m", "bb major".
  const PITCH = { c: 0, d: 2, e: 4, f: 5, g: 7, a: 9, b: 11 };
  const SHIFT = { "": 0, "#": 1, "♯": 1, b: -1, "♭": -1 };
  const MINOR = ["m", "min", "minor"];
  const KEY = /^([a-g])([#♯b♭]?)\s*(m|min|minor|maj|major)?$/i;
  const keyId = (text) => {
    const m = KEY.exec(String(text || "").trim());
    if (!m) return "";
    const pitch = (PITCH[m[1].toLowerCase()] + SHIFT[m[2].toLowerCase()] + 12) % 12;
    return pitch + (MINOR.indexOf((m[3] || "").toLowerCase()) >= 0 ? " minor" : " major");
  };
  // A key typed in the search box: a letter, maybe a sharp or a flat, then the mode ("a minor", "F# major",
  // "bbm"). Its words leave the text search, and it keeps the songs in that key, however they spell it.
  // Written as a chord ("am", "f#m"), it is a word too, so "am" also finds "I Am the Walrus".
  const TYPED_KEY = /(^|[^\p{L}\p{N}])([a-g][#♯b♭]?)(?:\s*(major|minor|maj|min)|(m))(?![\p{L}\p{N}#♯♭])/gu;
  const parseQuery = (query) => {
    const keys = [];
    const either = [];
    const rest = fold(query).replace(TYPED_KEY, (all, before, tonic, mode, chord) => {
      if (chord) either.push({ key: keyId(tonic + chord), word: term(tonic + chord) });
      else keys.push(keyId(tonic + " " + mode));
      return before + " ";
    });
    return { keys, either, words: terms(rest) };
  };
  // Whether a key is typed ("a minor", not "am"): it filters your songs alone, as the sites' indexes know no keys.
  const keyed = (text) => parseQuery(text).keys.length > 0;
  const songKeys = songs.map((s) => keyId(s.key));
  // Whether song i matches what is typed: each word in its search text, or its title's initials whole, and
  // each key typed.
  const typedMatch = (query) => (i) =>
    query.keys.every((k) => songKeys[i] === k) &&
    query.either.every((e) => songKeys[i] === e.key || (e.word && hay[i].indexOf(e.word) >= 0)) &&
    query.words.every((w) => hay[i].indexOf(w) >= 0 || (w.length > 1 && inits[i] === w));

  const compare = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  // The Key menu: one entry per key the library has, its spellings together ("F# / Gb minor"), with how
  // many songs it has. Its commonest spelling stands for it in the menu and in the address.
  const keyGroups = new Map();
  songs.forEach((s, i) => {
    if (!songKeys[i]) return;
    const group = keyGroups.get(songKeys[i]) || { spellings: new Map(), n: 0 };
    group.spellings.set(String(s.key), (group.spellings.get(String(s.key)) || 0) + 1);
    group.n += 1;
    keyGroups.set(songKeys[i], group);
  });
  for (const [id, group] of keyGroups) {
    const spelled = Array.from(group.spellings.keys())
      .sort((a, b) => group.spellings.get(b) - group.spellings.get(a) || compare(a, b));
    group.value = spelled[0];
    group.name = spelled.map((k) => k.replace(/ minor$/, "")).join(" / ") + id.replace(/^\d+/, "");
  }
  const keyGroup = (spelling) => keyGroups.get(keyId(spelling));
  const order = songs.map((_, i) => i);
  const sortedBy = (first, second) => order.slice().sort((i, j) =>
    compare(String(songs[i][first]), String(songs[j][first])) ||
    compare(String(songs[i][second]), String(songs[j][second])) || i - j);
  const ORDERS = {
    artist: sortedBy("sortArtist", "sortTitle"),
    title: sortedBy("sortTitle", "sortArtist"),
    recent: order.slice().sort((i, j) =>
      compare(String(songs[j].added || ""), String(songs[i].added || "")) || (songs[j].id || 0) - (songs[i].id || 0)),
  };

  // Where each file came from (icons.py): its site's own icon, inlined as a data: URI, else its lettered
  // badge; a glyph for the audio model and the inbox. Each is named for a screen reader: "from LaCuerda".
  const ICONS = data.icons && typeof data.icons === "object" ? data.icons : {};
  // ROWS_SCRIPT's, which the lookup page shares
  const { sourceMark, link, resultRow, titleLink, artistFilter, button, many, ugHit, artistHit, siteHit, siteArtist,
    siteArtistSongs, siteUnlisted, readArtistPage, readOutcome, prose } = caracoleRows(ICONS);
  // A song's file from where its sheet came from has no mark of its own: its card's, or its row's, says it.
  const elsewhere = (s, item) => (item && item.source && item.source === s.source
    ? Object.assign({}, item, { source: null }) : item);
  // The file a song opens with, from its title and its card's one button: its viewer, else its PDF, else its
  // text (the data marks it primary).
  const primaryOf = (s) => listOf(s.files).find((f) => f && f.primary) || null;
  // A card's button for it: "Open" for the viewer, "Open PDF" and "Open text" for the others. The card's
  // primary one unless it has another (a wanted song's Fetch now, which its row's button is too).
  const openButton = (s, f, lead) => {
    const kind = /\.html$/i.test(String(f.name || "")) ? "" : /\.pdf$/i.test(String(f.name || "")) ? "PDF" : "text";
    const text = kind ? "Open " + kind : "Open";
    const open = link({ label: text, href: f.href }, lead ? "btn primary" : "btn", false);
    open.setAttribute("aria-label", text + (kind ? " of " : " ") + String(s.title) + " by " + String(s.artist));
    open.title = String(f.label || "");  // "Sheet viewer", "Auto sheet PDF"
    return open;
  };

  // The song has no human sheet, and caracole takes its audio from YouTube (youtube_fetch.py): where
  // that stands, and the video its audio came from.
  const youtubeNote = (s) => {
    if (!s.youtube || typeof s.youtube.text !== "string") return null;
    const note = el("p", "youtube", s.youtube.text);
    if (s.youtube.video && typeof s.youtube.video === "object") {
      note.appendChild(document.createTextNode(" · "));
      note.appendChild(link(s.youtube.video, null, true));
    }
    return note;
  };
  // A wanted song whose sheet you picked on LaCuerda: tonight's run gets it, a link to its page.
  const lacuerdaNote = (s) => {
    if (!s.lacuerda || typeof s.lacuerda !== "object" || !/^https:[/][/]/i.test(String(s.lacuerda.href || ""))) return null;
    const note = el("p", "note lacuerda-pick", "Tonight's run gets ");
    note.appendChild(link(s.lacuerda, null, true));
    note.appendChild(document.createTextNode("."));
    return note;
  };
  const linkRow = (parent, heading, items, cls) => {
    if (!items.length) return;
    parent.appendChild(el("p", "subhead", heading));
    const row = el("div", "actions");
    for (const item of items) row.appendChild(link(item, cls, true));
    parent.appendChild(row);
  };
  const hidden = (name, value) => {
    const field = el("input");
    field.setAttribute("type", "hidden");
    field.setAttribute("name", name);
    field.setAttribute("value", String(value));
    return field;
  };
  // A song's form for caracole serve: it posts to ``action`` with the server's token and the song's id. Without
  // JavaScript it posts as a form.
  const songForm = (cls, action, s) => {
    const form = el("form", cls);
    form.setAttribute("method", "post");
    form.setAttribute("action", action);
    form.appendChild(hidden("csrf", String(server.csrf || "")));
    form.appendChild(hidden("song", Number(s.id)));
    return form;
  };
  // Sent by the page's script, the form leaves the page where it is: "Sending…" on the song's own line (the
  // focus on it, as ``go``, its button, waits), then the request's line, which takes the form's place (``track``);
  // a refusal, or a server that doesn't answer, says so there, and ``go`` can be pressed again.
  const postInPlace = (form, go, s) => {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const card = form.closest("article");
      const line = progressIn(card);  // in the page before its first words, so they are read out
      showLine(line, { line: { tone: "queued", text: "Sending…" } });
      if (form.contains(document.activeElement)) focusOn(line);  // a disabled button would drop it
      go.disabled = true;
      send(form).then((answer) => {
        const view = answer.ok && answer.body && answer.body.job;
        if (!view) {
          go.disabled = false;
          showLine(progressIn(card), failure(answer));
          return;
        }
        if (card && !isOwn(s, card)) spots.set(Number(view.id), card);
        track(view);  // its line takes the form's place
      }, () => {
        go.disabled = false;
        showLine(progressIn(card), UNREACHABLE);
      });
    });
  };
  // A wanted song's "Fetch now": caracole serve queues a fetch of this song alone.
  const fetchForm = (s) => {
    const form = songForm("fetch", "/fetch", s);
    const go = el("button", "btn primary", "Fetch now");
    go.type = "submit";
    go.setAttribute("aria-label", "Fetch " + String(s.title) + " by " + String(s.artist) + " now");
    go.title = "Ask Ultimate Guitar for this song now, politely";
    form.appendChild(go);
    postInPlace(form, go, s);
    return form;
  };
  // A wanted song caracole fetch would refuse until its match is settled: a button that says so, and does nothing.
  const reviewFirst = (cls) => {
    const held = el("button", cls, "Review first");
    held.type = "button";
    held.disabled = true;
    held.title = "caracole review settles this match; then it can be fetched";
    return held;
  };
  // Every card's "Remove…" (a row's, under its "⋯"): one tap counts down REMOVE_WAIT seconds on the song's own
  // line, "Removing in 5 s · Undo", with what goes (the server's answer to the question, ``removal.brief``), and
  // sends nothing else meanwhile; then the removal, whose line the card follows to Removed, never leaving the
  // page. Undo stops it. Without JavaScript the form posts, and caracole serve asks on a page of its own, whose
  // answers go back to the library as you left it (`back`: the address after #, its search, filters and view).
  const REMOVE_WAIT = 5;  // seconds
  const REMOVE_SECOND = paced("undo", REMOVE_WAIT * 1000) / REMOVE_WAIT;  // ms each of them lasts
  const removals = new Map();  // song id -> its removal counting down (startRemoval)
  const removeForm = (s) => {
    const form = songForm("remove", "/remove", s);
    const back = form.appendChild(hidden("back", ""));
    form.addEventListener("submit", (e) => {
      back.value = location.hash.slice(1);
      e.preventDefault();
      startRemoval(s, form.closest("article"));
    });
    const go = el("button", "btn small quiet", "Remove…");
    go.type = "submit";
    go.setAttribute("aria-label", "Remove " + String(s.title) + " by " + String(s.artist) + " from caracole");
    go.title = "Delete the files caracole wrote for it, and keep caracole from bringing it back; Undo, for " +
      REMOVE_WAIT + " seconds, keeps it";
    form.appendChild(go);
    return form;
  };
  // The song's card and row, and the card that showed it elsewhere (#requested's), if any: where its removal shows.
  const removalItems = (id, r) => {
    const i = byIndex.get(id);
    const own = i === undefined ? [] : [cards.get(i), rows.get(i)];
    return own.concat([r.spot]).filter((item, n, all) => item && all.indexOf(item) === n);
  };
  // A removal's line while it counts down: a screen reader hears it once ("Removing Creep in 5 seconds."), the
  // seconds left are for the eye; then Undo, and what goes. The item's other buttons wait meanwhile.
  const countdownIn = (item, r) => {
    const s = r.song;
    const p = progressIn(item);
    p.dataset.key = "";  // drawn here: the next showLine draws its own
    p.dataset.tone = "waiting";
    p.textContent = "";
    const shown = el("span");
    shown.setAttribute("aria-hidden", "true");
    shown.append("Removing in ", el("span", "left", r.left), " s");
    const dot = el("span", "dot", "·");
    dot.setAttribute("aria-hidden", "true");
    const undo = el("button", "undo", "Undo");
    undo.type = "button";
    undo.setAttribute("aria-label", "Undo: keep " + String(s.title) + " by " + String(s.artist));
    undo.addEventListener("click", () => undoRemoval(Number(s.id)));
    p.append(shown, el("span", "visually-hidden", "Removing " + String(s.title) + " in " + REMOVE_WAIT +
      " seconds."), dot, undo, el("span", "goes", r.brief));
    for (const b of item.querySelectorAll("form button")) {
      if (!b.disabled) {
        b.disabled = true;
        r.held.add(b);
      }
    }
    return undo;
  };
  const eachLine = (id, r, part, text) => {
    for (const item of removalItems(id, r)) {
      const node = item.querySelector(".progress " + part);
      if (node) node.textContent = text;
    }
  };
  // The removal over before it was sent: undone, or refused (``view``'s line says why). Its buttons are back.
  const stopRemoval = (id, view, focusBack) => {
    const r = removals.get(id);
    if (!r) return;
    removals.delete(id);
    clearTimeout(r.timer);
    const items = removalItems(id, r);
    const from = items.find((item) => item.contains(document.activeElement));
    for (const item of items) {
      const p = progressIn(item);
      p.style.minHeight = "";
      showLine(p, view);
    }
    for (const b of r.held) b.disabled = false;
    const go = focusBack && from ? from.querySelector("form.remove button") : null;
    if (go) go.focus();
  };
  const undoRemoval = (id) => stopRemoval(id, { line: { tone: "kept", text: "Not removed" } }, true);
  const startRemoval = (s, item) => {
    const id = Number(s.id);
    if (removals.has(id)) return;
    const r = { song: s, left: REMOVE_WAIT, timer: 0, brief: "Asking what goes…", key: null, ready: null,
                spot: item && !isOwn(s, item) ? item : null, held: new Set() };
    removals.set(id, r);
    let undo = null;
    for (const at of removalItems(id, r)) {
      const made = countdownIn(at, r);
      if (at === item) undo = made;
    }
    if (undo) undo.focus();
    // The question alone: what goes. It changes nothing; the removal is sent once the seconds are over.
    r.ready = postTo("/remove", new URLSearchParams({ csrf: String(server.csrf || ""), song: String(id) }))
      .then((answer) => {
        const plan = answer.ok && answer.body && answer.body.removal;
        if (!plan || typeof plan !== "object") throw failure(answer);
        r.key = String(plan.key || "");
        r.brief = String(plan.brief || "");
        eachLine(id, r, ".goes", r.brief);
      }, () => { throw UNREACHABLE; });
    r.ready.catch((said) => {
      if (removals.get(id) === r) stopRemoval(id, said && said.line ? said : UNREACHABLE, false);
    });
    const tick = () => {
      if (removals.get(id) !== r) return;
      r.left -= 1;
      if (r.left > 0) {
        eachLine(id, r, ".left", String(r.left));
        r.timer = setTimeout(tick, REMOVE_SECOND);
      } else {
        sendRemoval(id, r);
      }
    };
    r.timer = setTimeout(tick, REMOVE_SECOND);
  };
  // The seconds are over: the removal, sent with the song's key (an id the library gave another song since
  // removes nothing); its line follows the job from here, as tall as it was, so that nothing under it moves.
  const sendRemoval = (id, r) => {
    for (const item of removalItems(id, r)) {
      const p = progressIn(item);
      const tall = p.getBoundingClientRect().height;
      if (tall) p.style.minHeight = tall + "px";
      showLine(p, { line: { tone: "running", text: "Removing…" } });
    }
    r.ready.then(() => {
      if (removals.get(id) !== r) return;
      const body = new URLSearchParams({ csrf: String(server.csrf || ""), song: String(id), key: r.key || "",
                                         confirm: "1" });
      postTo("/remove", body).then((answer) => {
        const view = answer.ok && answer.body && answer.body.job;
        if (!view || typeof view !== "object") {
          stopRemoval(id, failure(answer), false);
          return;
        }
        removals.delete(id);
        removing.add(id);
        if (r.spot) spots.set(Number(view.id), r.spot);
        track(view);
      }, () => stopRemoval(id, UNREACHABLE, false));
    }, () => {});  // refused already: its line says why
  };

  // --- caracole serve: requests answered on the page ------------------------------------------
  // The forms post with fetch(), so the page stays where it is, and each song's card says on one line how its
  // request goes. /jobs.json gives each request's line, and a request's card once it is over; the page asks
  // it every POLL ms while one it shows waits or runs. Without JavaScript the forms post as forms, and the
  // server sends the browser to the request on /jobs.
  const POLL = paced("poll", 1500);
  const BACKGROUND_POLL = 6000;  // a page in a background tab asks less often
  const UNREACHABLE = { line: { tone: "failed", text: "caracole serve can't be reached: is it running?" } };
  const UNREACHABLE_NOW = "caracole serve can't be reached; trying again…";
  const MISSES = 3;  // asked in vain this many times in a row, the lines say so
  const views = new Map();  // job id -> what the server last said of it
  const songJob = new Map();  // song id -> the newest job of the song this page shows
  const watched = new Set();  // the jobs this page shows: asked for here, or waiting or running when it loaded
  const settled = new Set();  // watched jobs that are over, their cards drawn again
  const spots = new Map();  // job id -> a card outside the grid that shows it (#requested's)
  const byIndex = new Map(songs.map((s, i) => [Number(s.id), i]));  // song id -> its place in songs
  const isActive = (view) => view.state === "queued" || view.state === "running";
  const jobOfSong = (id) => (songJob.has(Number(id)) ? views.get(songJob.get(Number(id))) : null);
  // Whether node is the song's own card or row in the list, which the page draws again itself; any other
  // (#requested's card) is a spot of the job's.
  const isOwn = (s, node) => {
    const i = byIndex.get(Number(s.id));
    return i !== undefined && (cards.get(i) === node || rows.get(i) === node);
  };
  // A request's line, written into p only when it changed, so a screen reader hears each change once.
  // Its link says where to go next; details, the request's output on /jobs, follows it.
  const showLine = (p, view) => {
    const line = view && view.line && typeof view.line === "object" ? view.line : {};
    const to = line.link && typeof line.link === "object" ? line.link : null;
    const more = typeof line.details === "string" ? line.details : "";
    const key = [line.tone, line.text, to ? to.href : "", more].map(String).join("|");
    if (p.dataset.key === key) return;
    const focused = p !== document.activeElement && p.contains(document.activeElement);
    p.dataset.key = key;
    p.dataset.tone = String(line.tone || "");
    p.textContent = "";
    p.appendChild(el("span", null, line.text || ""));
    for (const go of [to, more ? { label: "Details", href: more } : null]) {
      if (!go) continue;
      const dot = el("span", "dot", "·");
      dot.setAttribute("aria-hidden", "true");
      p.appendChild(dot);
      const a = link(go, null, false);
      if (go === to) a.addEventListener("click", (e) => pickHere(e, p));
      p.appendChild(a);
    }
    if (focused) focusOn(p);  // its link is gone: the focus stays on the line
  };
  // A song in review's line sends you to its picker (review?song=ID): on a card that has the picker, it opens
  // that one, where you are, rather than the picker's own page. The list of requests has none: it goes there.
  const pickHere = (e, p) => {
    const card = p.closest("article");
    const box = card && card.querySelector("details.picker");
    const href = e.currentTarget.getAttribute("href") || "";
    if (!box || !box.querySelector("form") || !/^review\?song=\d+$/.test(href)) return;
    e.preventDefault();
    showPicker(box);
  };
  // Opens a picker where it is, a row's in its panel (the "⋯" button's), which opens first. Opened, the
  // picker takes the focus to its first candidate (its toggle); open already, the focus goes there.
  const showPicker = (box) => {
    const panel = box.closest(".row-panel");
    if (panel && panel.hidden) {
      const more = panel.parentNode.querySelector(".row-more");
      if (more) more.setAttribute("aria-expanded", "true");
      panel.hidden = false;
    }
    if (!box.open) {
      box.open = true;
      return;
    }
    const first = box.querySelector("input[name=pick]:checked") || box.querySelector("input[name=pick]");
    if (first) first.focus();
  };
  const focusOn = (p) => {
    p.tabIndex = -1;
    p.focus({ preventScroll: true });
  };
  // A card's line, made the first time: role="status" has it read out when it changes. A live region
  // put in the page with its text already in it is not read out, so a card keeps its line from the first
  // text to the last (refill), and only that text changes.
  const progressIn = (card) => {
    let p = card.querySelector(".progress");
    if (!p) {
      p = el("p", "progress");
      p.setAttribute("role", "status");
      // A card's under its facts; a row's under its artist, a line of its own across the row.
      const after = card.querySelector(".facts") || card.querySelector(".head") || card.querySelector(".row-sub") ||
        card.querySelector(".row-title");
      if (after) after.after(p);
      else card.appendChild(p);
    }
    return p;
  };
  // The card old, drawn again as fresh (makeCard's) where it is, around its own line, which never leaves
  // the page; returns old. The focus, if it was on something of old's that goes, moves to the line.
  const refill = (old, fresh) => {
    const kept = old.querySelector(".progress");
    if (!kept) {
      if (old.parentNode) old.replaceWith(fresh);
      return fresh;
    }
    const at = document.activeElement;
    const focused = at !== old && old.contains(at) && !kept.contains(at);  // on something that goes
    const drawn = progressIn(fresh);  // where fresh has its line
    for (const child of Array.from(old.childNodes)) if (child !== kept) child.remove();
    let before = true;
    for (const child of Array.from(fresh.childNodes)) {
      if (child === drawn) before = false;
      else if (before) old.insertBefore(child, kept);
      else old.appendChild(child);
    }
    old.className = fresh.className;
    old.tabIndex = fresh.tabIndex;
    for (const name of Object.keys(old.dataset)) delete old.dataset[name];
    Object.assign(old.dataset, fresh.dataset);
    if (focused && old.isConnected) focusOn(kept);
    return old;
  };
  const failure = (answer) => ({ line: { tone: "failed", text: (answer.body && answer.body.error) ||
    "caracole serve answered " + answer.status + ": reload the page." } });
  // A form, posted as the page's script: the answer is the job, or {error}, never a page.
  const postTo = (path, body) => fetch(path, {
    method: "POST", body, credentials: "same-origin", headers: { Accept: "application/json" },
  }).then((r) => r.json().catch(() => null).then((answer) => ({ ok: r.ok, status: r.status, body: answer })));
  const send = (form) => postTo(form.getAttribute("action"), new URLSearchParams(new FormData(form)));
  let track = () => {};

  // A song not found: caracole serve's picker page shows what `caracole search` finds for it.
  const lookLink = (s, cls) => {
    const look = el("a", cls || "btn", "Look in the index");
    look.href = "/review?song=" + Number(s.id);
    look.setAttribute("aria-label", "Look for " + String(s.title) + " by " + String(s.artist) + " in the index");
    look.title = "What caracole search finds for it in the offline Ultimate Guitar index, to pick from";
    return look;
  };

  // A song not found, on the file, which can't search: the line that lists its search hits, numbered as
  // `caracole review --song … --pick N` takes them.
  const notFoundHint = (s) => {
    const hint = el("p", "pick-hint", "Not in the offline Ultimate Guitar index under this name: ");
    hint.appendChild(el("code", null, "caracole review --song " + shellQuote(String(s.display))));
    hint.appendChild(document.createTextNode(" lists what caracole search finds for it, to pick one."));
    return hint;
  };

  // The picker: a song in review's candidates, numbered as `caracole review` numbers them. The file shows
  // them with the line that picks one; caracole serve, with a form whose answer `caracole review --song`
  // writes (web/app.py). makePicker(song) builds it from a song of the data that has `candidates`.
  const choiceRow = (c, pickable) => {
    const row = el(pickable ? "div" : "li", "choice");
    const pick = el(pickable ? "label" : "div", "choice-pick");
    if (pickable) {
      const radio = el("input");
      radio.setAttribute("type", "radio");
      radio.setAttribute("name", "pick");
      radio.setAttribute("value", String(c.ref));
      radio.setAttribute("required", "");
      pick.appendChild(radio);
    }
    const text = el("span", "choice-text");
    text.appendChild(el("span", "choice-name", c.n + ". " + String(c.artist) + " – " + String(c.title)));
    const why = [c.why, "score " + (Number(c.score) || 0), c.tabs].filter(Boolean).map(String).join(" · ");
    text.appendChild(el("span", "choice-why", why));
    pick.appendChild(text);
    row.appendChild(pick);
    if (c.href) {
      const page = link({ label: "UG", href: c.href }, "choice-link", true);
      page.setAttribute("aria-label", String(c.artist) + " – " + String(c.title) + " on Ultimate Guitar, in a new tab");
      row.appendChild(page);
    }
    return row;
  };
  const noneRow = () => {
    const row = el("div", "choice none");
    const pick = el("label", "choice-pick");
    const radio = el("input");
    radio.setAttribute("type", "radio");
    radio.setAttribute("name", "pick");
    radio.setAttribute("value", "none");
    radio.setAttribute("required", "");
    pick.appendChild(radio);
    const text = el("span", "choice-text");
    text.appendChild(el("span", "choice-name", "None of these"));
    text.appendChild(el("span", "choice-why", "caracole drops them for good and goes on looking for the song"));
    pick.appendChild(text);
    row.appendChild(pick);
    return row;
  };
  // What a card shows under its facts, and a row in its panel, of a song with no picker: why its match waits (a
  // review with no candidates to pick from), or, on the file, the line that lists a song not found's search hits;
  // else nothing (null).
  const unpicked = (s) => {
    if (SHOWS.review(s)) {
      const note = el("p", "note", "caracole isn't sure about this match: see the ");
      const todo = el("a", null, "to-do page");
      todo.href = "_todo.md";
      note.appendChild(todo);
      note.appendChild(document.createTextNode(", or run caracole review."));
      return note;
    }
    return !server && s.notFound && s.status === "wanted" ? notFoundHint(s) : null;
  };
  const makePicker = (s) => {
    const cands = listOf(s.candidates).filter((c) => c && c.ref);
    const box = el("details", "picker");
    const question = "Which Ultimate Guitar song is “" + String(s.title) + "” by " + String(s.artist) + "?";
    const job = server ? jobOfSong(s.id) : null;
    const pickable = Boolean(server) && !busy.has(Number(s.id)) && !(job && isActive(job));
    const many = plural(cands.length, "candidate");
    const summary = el("summary", pickable ? "btn picker-open" : "picker-open", pickable ? "Pick the match" : many);
    if (pickable) summary.appendChild(el("span", "picker-n", "· " + many));
    box.appendChild(summary);
    if (!pickable) {
      const list = el("ol", "choices");
      list.setAttribute("aria-label", question);
      for (const c of cands) list.appendChild(choiceRow(c, false));
      box.appendChild(list);
      if (server) {
        box.appendChild(el("p", "pick-hint", "A request for this song is running: pick one once it ends."));
      } else {
        const hint = el("p", "pick-hint", "Pick one with ");
        hint.appendChild(el("code", null, "caracole review --song " + shellQuote(String(s.display))));
        hint.appendChild(document.createTextNode(": its number, or "));
        hint.appendChild(el("code", null, "n"));
        hint.appendChild(document.createTextNode(" for none of these."));
        box.appendChild(hint);
      }
      return box;
    }
    const form = songForm("pick-form", "/review", s);
    form.appendChild(hidden("shown", cands.map((c) => String(c.ref)).join(" ")));
    const group = el("fieldset", "choices");
    group.appendChild(el("legend", null, question));
    for (const c of cands) group.appendChild(choiceRow(c, true));
    group.appendChild(noneRow());
    form.appendChild(group);
    const row = el("div", "pick-row");
    const now = el("label", "pick-check");
    const fetch = el("input");
    fetch.setAttribute("type", "checkbox");
    fetch.setAttribute("name", "fetch");
    fetch.setAttribute("value", "1");
    fetch.setAttribute("checked", "");
    now.appendChild(fetch);
    now.appendChild(document.createTextNode("Fetch it now"));
    row.appendChild(now);
    const go = el("button", "btn primary", "Pick");
    go.type = "submit";
    row.appendChild(go);
    form.appendChild(row);
    form.appendChild(el("p", "pick-hint", "Your answer goes into overrides.toml, as caracole review writes it. " +
      "Fetch it now then asks Ultimate Guitar for the song picked; None of these fetches nothing."));
    box.appendChild(form);
    postInPlace(form, go, s);
    // Opened, the picker takes the focus to its candidates: the arrow keys then move between them.
    box.addEventListener("toggle", () => {
      if (!box.open) return;
      const first = form.querySelector("input[name=pick]:checked") || form.querySelector("input[name=pick]");
      if (first) first.focus();
    });
    return box;
  };

  let setArtist = () => {};
  // An artist's monogram, in that artist's colour (one of eight), which a screen reader skips.
  const monogram = (letters, hue) => {
    const mono = el("span", "mono hue-" + (Number.isInteger(hue) && hue >= 0 && hue < 8 ? hue : 0), letters || "");
    mono.setAttribute("aria-hidden", "true");
    return mono;
  };
  // A card's head without its links or badges: the monogram, the title and the artist (a removed song's card;
  // a requested song's, before the library has it).
  const plainHead = (letters, hue, title, artist) => {
    const head = el("div", "head");
    const names = el("div", "names");
    names.append(el("h2", null, title), el("p", "by", artist));
    head.append(monogram(letters, hue), names);
    return head;
  };
  const makeCard = (s) => {
    const card = el("article", "card");
    card.dataset.status = String(s.status);
    card.dataset.id = String(s.id);
    card.tabIndex = -1;  // the A-Z strip moves the focus to it
    const head = el("div", "head");
    head.appendChild(monogram(s.monogram, s.hue));
    const names = el("div", "names");
    const primary = primaryOf(s);
    names.appendChild(primary ? titleLink(primary.href, el("h2", null, s.title)) : el("h2", null, s.title));
    const artists = listOf(s.artists);
    // The artist, then the badges: at the end of the artist's line, or under it, never beside the title.
    const byline = el("div", "byline");
    byline.appendChild(artistFilter(artists.length > 1 ? artists.join(", ") : String(s.artist), String(s.artist),
      () => {
        setArtist(String(s.sortArtist || ""));
        window.scrollTo(0, 0);
      }));
    names.appendChild(byline);
    head.appendChild(names);
    const badges = el("div", "badges");
    const mark = sourceMark(s.source);  // where its sheet came from
    if (mark) badges.appendChild(mark);
    badges.appendChild(el("span", "badge " + String(s.status), label(STATUS_TEXT, s.status) || s.status));
    if (SHOWS.review(s)) badges.appendChild(el("span", "badge review", "Needs review"));
    if (s.auto) badges.appendChild(el("span", "badge auto", "Auto sheet"));
    byline.appendChild(badges);
    card.appendChild(head);

    const facts = el("p", "facts");
    if (typeof s.key === "string" && s.key) facts.appendChild(el("span", "key", keyText(s)));
    const shift = Number(s.transpose) || 0;
    if (shift) {
      const t = el("span", "transpose", (shift > 0 ? "+" : "−") + Math.abs(shift));
      t.title = "The PDF is transposed " + (shift > 0 ? "up " : "down ") + Math.abs(shift) +
        " semitone" + (Math.abs(shift) === 1 ? "" : "s");
      facts.appendChild(t);
    }
    if (label(LYRICS_TEXT, s.lyrics)) facts.appendChild(el("span", "lyrics", label(LYRICS_TEXT, s.lyrics)));
    if (s.added) facts.appendChild(el("span", "added", "Added " + String(s.added).slice(0, 10)));
    if (facts.childNodes.length) card.appendChild(facts);
    const picks = SHOWS.review(s) && listOf(s.candidates).length > 0;
    const why = picks ? makePicker(s) : unpicked(s);
    if (why) card.appendChild(why);
    const fromYouTube = youtubeNote(s);
    if (fromYouTube) card.appendChild(fromYouTube);
    const picked = lacuerdaNote(s);
    if (picked) card.appendChild(picked);

    // Served by caracole serve: how the song's request goes, on one line, and Fetch now unless one runs.
    const job = server ? jobOfSong(s.id) : null;
    if (job) showLine(progressIn(card), job);
    const actions = el("div", "actions");
    if (server && s.status === "wanted" && !removing.has(Number(s.id))) {  // removing: its foot says so
      if ((job && isActive(job)) || busy.has(Number(s.id))) {
        if (!job) showLine(progressIn(card), { line: { tone: "running", text: "Fetching…" } });
      } else if (s.fetchable === false && picks) {
        // caracole fetch would refuse it until the match is picked: the picker above does that.
      } else if (s.fetchable === false) {
        // caracole fetch would refuse it: the match needs review first (the note above says how).
        actions.appendChild(reviewFirst("btn"));
      } else {
        actions.appendChild(fetchForm(s));
      }
      if (s.notFound) actions.appendChild(lookLink(s));
    }
    if (primary) actions.appendChild(openButton(s, primary, !actions.querySelector(".btn.primary")));
    if (actions.childNodes.length) card.appendChild(actions);
    // The other files, and the Guitar Pro versions to download, folded away as a row's "⋯" folds them.
    const others = listOf(s.files).filter((f) => f && f !== primary).map((f) => elsewhere(s, f));
    if (others.length || listOf(s.guitarPro).length) {
      const files = el("details", "more files");
      files.appendChild(el("summary", null, "Files"));
      if (others.length) {
        const line = el("div", "actions");
        for (const f of others) line.appendChild(link(f, "btn small", false));
        files.appendChild(line);
      }
      linkRow(files, "Guitar Pro to download", listOf(s.guitarPro), "btn small");
      card.appendChild(files);
    }
    if (listOf(s.museScore).length || listOf(s.links).length || listOf(s.buy).length) {
      const more = el("details", "more");
      more.appendChild(el("summary", null, "Find it elsewhere"));
      linkRow(more, "Scores on MuseScore", listOf(s.museScore), "btn small");
      linkRow(more, "Find the chords", listOf(s.links), "btn small");
      linkRow(more, "Buy the track for an auto sheet", listOf(s.buy), "btn small");
      card.appendChild(more);
    }
    if (server) {
      const foot = el("div", "foot");
      if (!removing.has(Number(s.id))) {
        foot.appendChild(removeForm(s));
      } else if (!job || job.kind !== "remove") {  // a removal the page follows says how it goes on its line
        const note = el("p", "busy", "Removing… ");
        const jobs = el("a", null, "see the requests");
        jobs.href = "/jobs";
        note.appendChild(jobs);
        foot.appendChild(note);
      }
      if (foot.childNodes.length) card.appendChild(foot);
      if (removals.has(Number(s.id))) countdownIn(card, removals.get(Number(s.id)));  // drawn again meanwhile
    }
    return card;
  };
  const cards = new Map();
  const cardFor = (i) => {
    if (!cards.has(i)) cards.set(i, makeCard(songs[i]));
    return cards.get(i);
  };

  // Rows: one compact line a song (resultRow, from ROWS_SCRIPT: the seam the module docstring describes).
  // A row is an article titled by its h2; the A-Z strip moves the focus to it.
  // A song's main action in its row, as its card has it, when the server's control holds the row's button
  // (``held``): a wanted song's fetch, or the button that opens its picker; Removing… while caracole removes it;
  // no button at all (``action`` null) while its request, or its removal, waits or runs, as the row's line
  // then says how it goes. Not held, the row's button is its sheet (sheetAction), as it is on the file.
  const serverAction = (s, picker) => {
    const held = (action) => ({ held: true, action });
    if (server && removing.has(Number(s.id))) {
      const job = jobOfSong(s.id);
      if (job && job.kind === "remove") return held(null);
      const going = el("a", "row-busy", "Removing…");
      going.href = "/jobs";
      going.title = "See the requests";
      return held(going);
    }
    if (server && s.status === "wanted") {
      const job = jobOfSong(s.id);
      if ((job && isActive(job)) || busy.has(Number(s.id))) return held(null);
      if (s.fetchable === false && picker && picker.querySelector("form")) {
        // caracole fetch would refuse it until the match is picked: this opens the picker, in the row's panel.
        const pick = el("button", "btn small row-pick", "Pick the match");
        pick.type = "button";
        pick.setAttribute("aria-label", "Pick the match for " + String(s.title) + " by " + String(s.artist));
        pick.title = "Which Ultimate Guitar song this is: caracole isn't sure";
        pick.addEventListener("click", () => showPicker(picker));
        return held(pick);
      }
      if (s.fetchable === false) return held(reviewFirst("btn small"));
      return held(fetchForm(s));
    }
    return { held: false, action: null };
  };
  // The row's button for its sheet: the primary one, as Fetch now is, named for what it opens ("Sheet viewer").
  const sheetAction = (s, primary) => {
    const open = link({ label: primary.label, href: primary.href }, "btn small primary", false);
    open.setAttribute("aria-label", String(primary.label) + " of " + String(s.title) + " by " + String(s.artist));
    return open;
  };
  const songRow = (s) => {
    const id = Number(s.id);
    const files = listOf(s.files);
    const primary = primaryOf(s);
    const more = [];
    // What a card shows under its facts, in the row's panel: the picker, or the note that says why not.
    const picker = SHOWS.review(s) && listOf(s.candidates).length > 0 ? makePicker(s) : null;
    if (picker) {
      // The row's button says Pick the match: its picker folds as a read-only one does, "3 candidates".
      const summary = picker.querySelector("summary");
      summary.className = "picker-open";
      summary.textContent = plural(listOf(s.candidates).filter((c) => c && c.ref).length, "candidate");
      more.push(picker);
    } else {
      const why = unpicked(s);
      if (why) more.push(why);
    }
    const fromYouTube = youtubeNote(s);  // as on its card, first in the row's panel
    if (fromYouTube) more.push(fromYouTube);
    const picked = lacuerdaNote(s);
    if (picked) more.push(picked);
    if (server && s.notFound && s.status === "wanted" && !removing.has(id)) {
      const look = el("div", "actions");
      look.appendChild(lookLink(s, "btn small"));
      more.push(look);
    }
    // The sheet is the row's button unless the server's control has its place (Fetch now beside an auto
    // sheet): then it leads the files, and the title opens it all the same.
    const control = serverAction(s, picker);
    const action = control.held ? control.action : primary ? sheetAction(s, primary) : null;
    const listed = control.held ? files : files.filter((f) => f !== primary);
    more.push({ heading: "Files", links: listed.map((f) => elsewhere(s, f)) },
      { heading: "Guitar Pro to download", links: listOf(s.guitarPro) },
      { heading: "Scores on MuseScore", links: listOf(s.museScore) },
      { heading: "Find the chords", links: listOf(s.links) },
      { heading: "Buy the track for an auto sheet", links: listOf(s.buy) });
    if (server && !removing.has(id)) {  // removing: its action says so
      const foot = el("div", "foot");
      foot.appendChild(removeForm(s));
      more.push(foot);
    }
    // No "Auto sheet" badge: the row's mark (♪, "from the audio") and its button ("Auto sheet PDF") say so.
    const badges = [{ kind: s.status, text: label(STATUS_TEXT, s.status) || s.status }];
    if (SHOWS.review(s)) badges.push({ kind: "review", text: "Needs review" });
    const artists = listOf(s.artists);
    const keyed = typeof s.key === "string" && s.key;
    const row = resultRow({
      title: s.title,
      href: primary ? primary.href : "",
      artist: artists.length > 1 ? artists.join(", ") : s.artist,
      source: s.source,
      status: s.status,
      key: keyed ? s.key : "",
      keyText: keyed ? keyText(s) : "",
      badges,
      action,
      more,
      onArtist: () => {
        setArtist(String(s.sortArtist || ""));
        window.scrollTo(0, 0);
      },
    });
    row.dataset.id = String(s.id);  // as a card's: the Select mode finds the song's row by it
    // How the song's request goes, on a line of the row's own, as on its card.
    const job = server ? jobOfSong(id) : null;
    if (job) {
      showLine(progressIn(row), job);
    } else if (server && s.status === "wanted" && !removing.has(id) && busy.has(id)) {
      showLine(progressIn(row), { line: { tone: "running", text: "Fetching…" } });
    }
    if (removals.has(id)) countdownIn(row, removals.get(id));  // drawn again while its removal counts down
    return row;
  };
  const rows = new Map();
  const rowFor = (i) => {
    if (!rows.has(i)) rows.set(i, songRow(songs[i]));
    return rows.get(i);
  };
  const VIEWS = ["cards", "rows"];
  const viewButtons = Array.from(document.querySelectorAll("button[data-view]"));
  // For lists the page doesn't make itself (the served page's type-ahead): the same rows and marks.
  window.caracole = Object.freeze({ resultRow, sourceMark, icons: ICONS });

  // artist: one artist's songs alone, by sortArtist, which a search for the name wouldn't give
  // ("Queen" also finds "Dancing Queen").
  // all: the search of the sites (served; on the file, the line that searches them), under the bar.
  const state = { q: "", show: "all", sort: "artist", artist: "", key: "", view: "cards", all: false };
  const itemFor = (i) => (state.view === "rows" ? rowFor(i) : cardFor(i));
  const artistName = (key) => {
    const s = key ? songs.find((song) => String(song.sortArtist || "") === key) : undefined;
    return s ? String(s.artist) : "";
  };
  try {
    const params = new URLSearchParams(location.hash.slice(1));
    state.q = params.get("q") || "";
    if (artistName(params.get("artist") || "")) state.artist = params.get("artist");
    if (own.call(SHOWS, params.get("show"))) state.show = params.get("show");
    if (SORTS.indexOf(params.get("sort")) >= 0) state.sort = params.get("sort");
    if (keyGroup(params.get("key"))) state.key = keyGroup(params.get("key")).value;  // any spelling of it
    if (VIEWS.indexOf(params.get("view")) >= 0) state.view = params.get("view");
    state.all = params.get("all") === "1" && Boolean(state.q.trim()) && !keyed(state.q);
  } catch (err) {
    // A malformed address: start from the defaults.
  }
  const keySelect = byId("key");
  for (const group of Array.from(keyGroups.values()).sort((a, b) => compare(a.name, b.name))) {
    const option = el("option", null, group.name + " · " + group.n);
    option.value = group.value;
    keySelect.appendChild(option);
  }
  byId("keys").hidden = keyGroups.size === 0;
  const save = () => {
    const params = new URLSearchParams();
    if (state.q) params.set("q", state.q);
    if (state.show !== "all") params.set("show", state.show);
    if (state.sort !== "artist") params.set("sort", state.sort);
    if (state.artist) params.set("artist", state.artist);
    if (state.key) params.set("key", state.key);
    if (state.view !== "cards") params.set("view", state.view);
    if (state.all) params.set("all", "1");
    try {
      history.replaceState(null, "", "#" + params.toString());
    } catch (err) {
      // Some browsers refuse this for local files; the page works the same, it just isn't remembered.
    }
  };

  const plural = (n, word) => n + " " + word + (n === 1 ? "" : "s");
  const arrived = new Map();  // song id -> the card data of a song new to the library since the page loaded
  // A song removed since the page loaded counts nowhere, though its card says Removed until the next load.
  const counted = (s) => s.status !== "removed";
  const summarize = () => {
    const by = { found: 0, wanted: 0, ignored: 0 };
    const every = songs.concat(Array.from(arrived.values())).filter(counted);
    for (const s of every) if (own.call(by, s.status)) by[s.status] += 1;
    const summary = byId("summary");
    summary.textContent = "";
    const stat = (n, word) => {
      const item = el("li", "stat");
      item.appendChild(el("b", null, n));
      item.appendChild(document.createTextNode(" " + word));
      summary.appendChild(item);
    };
    stat(every.length, every.length === 1 ? "song" : "songs");
    stat(by.found, "found");
    stat(by.wanted, "wanted");
    if (by.ignored) stat(by.ignored, "ignored");
    const when = String(data.generated || "").replace("T", " ").slice(0, 16);
    if (when) byId("updated").textContent = "Updated by caracole " + when + " UTC. ";
  };
  const smooth = () => (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ? "auto" : "smooth");

  // The row of buttons, one line that scrolls sideways on a phone: which of its ends hide buttons.
  const chipRow = document.querySelector(".chips");
  const chipEdges = () => {
    if (!chipRow) return;
    const room = chipRow.scrollWidth - chipRow.clientWidth;
    chipRow.classList.toggle("more-start", room > 1 && chipRow.scrollLeft > 1);
    chipRow.classList.toggle("more-end", room > 1 && chipRow.scrollLeft < room - 1);
  };
  if (chipRow) {
    chipRow.addEventListener("scroll", chipEdges, { passive: true });
    if ("ResizeObserver" in window) new ResizeObserver(chipEdges).observe(chipRow);
  }
  // How many of the songs the search and filters match each button would show; a card drawn again changes it.
  let matchingNow = [];
  let shownNow = [];
  const tallyChips = () => {
    const tally = { all: matchingNow.filter((i) => counted(songs[i])).length, found: 0, wanted: 0, review: 0 };
    for (const i of matchingNow) {
      for (const k of ["found", "wanted", "review"]) if (SHOWS[k](songs[i])) tally[k] += 1;
    }
    // Needs review, only while a song does (or while it is the one pressed).
    const reviewing = songs.some((s) => SHOWS.review(s)) || Array.from(arrived.values()).some((s) => SHOWS.review(s));
    for (const chip of chips) {
      chip.setAttribute("aria-pressed", String(chip.dataset.show === state.show));
      chip.querySelector(".n").textContent = String(tally[chip.dataset.show]);
      chip.hidden = chip.dataset.show === "review" && !reviewing && state.show !== "review";
    }
    chipEdges();
  };
  // How many songs the list shows, of how many.
  const tell = () => {
    const total = songs.filter(counted).length;
    const n = shownNow.filter((i) => counted(songs[i])).length;
    count.textContent = n === total ? plural(total, "song") : n + " of " + plural(total, "song");
  };

  const render = () => {
    const query = parseQuery(state.q);
    const inKey = keyId(state.key);
    const fits = typedMatch(query);
    const matching = ORDERS[state.sort].filter((i) =>
      (!state.artist || String(songs[i].sortArtist || "") === state.artist) &&
      (!inKey || songKeys[i] === inKey) && fits(i));
    matchingNow = matching;
    tallyChips();
    const shown = matching.filter((i) => SHOWS[state.show](songs[i]));
    sort.value = state.sort;
    keySelect.value = state.key;
    // On a phone Key, Sort and the view are under View, which says a key chosen there.
    viewToggle.textContent = state.key && keyGroup(state.key) ? "View · " + keyGroup(state.key).name : "View";
    for (const button of viewButtons) button.setAttribute("aria-pressed", String(button.dataset.view === state.view));
    clear.hidden = !state.q;
    artistChip.hidden = !state.artist;
    artistChip.textContent = state.artist ? artistName(state.artist) + " ×" : "";
    artistChip.setAttribute("aria-label", state.artist ? "Show every artist, not only " + artistName(state.artist) : "");
    // Searching the sites, served: the results take the grid's place, its tools with it, until Escape.
    const searchingAll = Boolean(server) && state.all;
    document.body.classList.toggle("searching-all", searchingAll);
    drawBar(matching.length === 0, query.keys.length > 0);
    let answerInList = false;  // the file's line that searches the sites, in the list's empty state
    if (searchingAll) {
      drawResults(query, false);
      return;
    }

    // One grid, whatever the order, so the cards fill each row; the strip jumps to a letter's first card.
    // In rows, one list of rows.
    list.textContent = "";
    jump.textContent = "";
    const grid = el("div", state.view === "rows" ? "rows" : "grid");
    const letterOf = LETTERS[state.sort];
    const firsts = new Map();
    for (const i of shown) {
      const card = itemFor(i);
      if (letterOf) {
        const letter = String(songs[i][letterOf] || "#");
        if (!firsts.has(letter)) firsts.set(letter, card);
      }
      grid.appendChild(card);
    }
    if (shown.length) list.appendChild(grid);
    for (const [letter, card] of firsts) {
      const to = el("button", null, letter);
      to.type = "button";
      to.setAttribute("aria-label", "Jump to " + letter);
      to.addEventListener("click", () => {
        card.scrollIntoView({ block: "start", behavior: smooth() });
        card.focus({ preventScroll: true });  // so the next Tab goes on from this card
      });
      jump.appendChild(to);
    }
    jump.hidden = firsts.size < 2 || shown.length < JUMP_FROM;

    if (!songs.length) {
      list.appendChild(el("p", "empty", "No songs yet."));
      const hint = el("p", "empty-hint", "Add a line to wanted.txt, or run ");
      hint.appendChild(el("code", null, "caracole add ARTIST TITLE"));
      hint.appendChild(document.createTextNode("; the next run lists the song here."));
      list.appendChild(hint);
    } else if (!shown.length && matching.length) {
      // The words match songs that the status filter hides: offer them.
      list.appendChild(el("p", "empty", "No " + CHIP_TEXT[state.show] + " match “" + state.q + "”."));
      const n = matching.length;
      const all = el("button", "btn", "Show all " + n + " match" + (n === 1 ? "" : "es"));
      all.type = "button";
      all.addEventListener("click", () => {
        state.show = "all";
        render();
        save();
      });
      list.appendChild(all);
    } else if (!shown.length && state.artist) {
      // The artist filter hides what the search finds: say so, and offer every artist.
      const who = artistName(state.artist);
      list.appendChild(el("p", "empty", state.q ? "No songs of " + who + " match “" + state.q + "”."
        : "No songs of " + who + " here."));
      const every = el("button", "btn", "Look in every artist's songs");
      every.type = "button";
      every.addEventListener("click", () => {
        state.artist = "";
        render();
        save();
      });
      list.appendChild(every);
    } else if (!shown.length && state.key) {
      // The key filter hides them: offer every key.
      list.appendChild(el("p", "empty", "No songs in " + keyGroup(state.key).name +
        (state.q ? " match “" + state.q + "”." : ".")));
      const any = el("button", "btn", "Any key");
      any.type = "button";
      any.addEventListener("click", () => {
        state.key = "";
        render();
        save();
      });
      list.appendChild(any);
    } else if (!shown.length && state.q) {
      list.appendChild(el("p", "empty", "No songs match “" + state.q + "”."));
      if (!query.keys.length && server) {  // the offline indexes have no keys
        const go = button("Search the sites for “" + state.q.trim() + "”", "primary", () => enterAll());
        list.appendChild(go);
      } else if (!query.keys.length) {
        list.appendChild(fileAnswer(state.q.trim()));
        answerInList = true;
      }
    } else if (!shown.length) {
      list.appendChild(el("p", "empty", state.show === "review" ? "Nothing needs review." : "No songs here."));
    }
    shownNow = shown;
    tell();
    drawResults(query, answerInList);
  };

  let frame = 0;
  const update = () => {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      render();
      save();
    });
  };
  const setQuery = (q) => {
    input.value = q;
    state.q = q;
    if (state.all && !q.trim()) {  // out of the sites' results as Escape goes, with what their rows asked for
      leaveAll(false);
      return;
    }
    render();
    save();
  };
  setArtist = (key) => {
    state.artist = key;
    setQuery("");
  };
  artistChip.addEventListener("click", () => {
    state.artist = "";
    render();
    save();
  });
  viewToggle.addEventListener("click", () => {
    const open = viewToggle.getAttribute("aria-expanded") !== "true";
    viewToggle.setAttribute("aria-expanded", String(open));
    viewPanel.classList.toggle("open", open);
  });
  // The bar kept at the top gets its edge once the page scrolls under it.
  const edge = byId("bar-edge");
  const bar = document.querySelector(".searchbar");
  if (edge && bar && "IntersectionObserver" in window) {
    new IntersectionObserver((seen) => {
      bar.classList.toggle("stuck", !seen[seen.length - 1].isIntersecting);
    }).observe(edge);
  }
  input.value = state.q;
  input.addEventListener("input", () => {
    state.q = input.value;
    if (state.all && (!state.q.trim() || keyed(state.q))) {  // nothing the sites can search: your songs again
      leaveAll(false);
      return;
    }
    update();
  });
  clear.addEventListener("click", () => {
    setQuery("");
    input.focus();
  });
  for (const chip of chips) {
    chip.addEventListener("click", () => {
      state.show = chip.dataset.show;
      render();
      save();
    });
  }
  sort.addEventListener("change", () => {
    state.sort = SORTS.indexOf(sort.value) >= 0 ? sort.value : "artist";
    render();
    save();
  });
  keySelect.addEventListener("change", () => {
    state.key = keyGroup(keySelect.value) ? keyGroup(keySelect.value).value : "";
    render();
    save();
  });
  for (const button of viewButtons) {
    button.addEventListener("click", () => {
      state.view = VIEWS.indexOf(button.dataset.view) >= 0 ? button.dataset.view : "cards";
      render();
      save();
    });
  }

  // --- the bar: your songs as you type, the sites on Enter ---------------------------------------
  // Typing filters your songs, here, asking nothing. Enter, or Search all, searches the sites too: served, one
  // list under the bar, your songs first (as their own rows), then what caracole's offline indexes hold of
  // Ultimate Guitar, LaCuerda, gtptabs.com and MuseScore (/api/search), following what you type a moment after you
  // stop, the newest query alone; on the file, which can ask nothing, the line that searches them. Enter
  // never spends a request: only a result's Get it does. Escape goes back to your songs.
  const normal = (text) => String(text).trim().replace(/\s+/g, " ");
  const say = (text) => {
    if (barStatus.textContent === text) return;
    barStatus.textContent = text;
    barStatus.title = text;  // one line on a phone: the whole of it on hovering
  };
  const drawBar = (none, key) => {
    const q = normal(state.q);
    allButton.classList.toggle("primary", Boolean(q) && none && !key);
    allButton.disabled = key;
    if (key) allButton.title = "The sites' indexes know no keys";
    else allButton.removeAttribute("title");
    if (server && state.all) return;  // the search of the sites says how it goes
    if (!q) say(server ? "Filter your songs; Enter searches the sites too" : "Filter your songs as you type");
    else if (key) say(none ? "None of yours match: the sites know no keys" : "A key filters your songs alone: the sites know no keys");
    else if (none) say(server ? "None of yours match: Enter searches the sites" : "None of yours match: see the line below");
    else if (!server && state.all) say("The sites need caracole serve: run the line below");
    else say(server ? "Enter or Search all looks on the sites too" : "Enter or Search all: the line that searches the sites");
  };
  // Each word in single quotes, as the Select bar copies its command: on the file, Copy selects it too.
  const copyText = (code, copy) => {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(code.textContent).then(() => { copy.textContent = "Copied"; }, () => {});
    }
    const range = document.createRange();
    range.selectNodeContents(code);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  };
  // The file's answer to Enter: what to run where caracole runs, since searching the sites needs caracole serve.
  const fileAnswer = (q) => {
    const box = el("div", "file-answer");
    box.appendChild(el("p", null, "Searching Ultimate Guitar, LaCuerda, gtptabs.com and MuseScore needs caracole serve. " +
      "Where caracole runs, this searches its copies of Ultimate Guitar's and LaCuerda's indexes:"));
    const line = el("div", "command");
    const code = el("code", null, "caracole search " + shellQuote(q));
    const copy = button("Copy", "small", () => copyText(code, copy), "Copy the line");
    line.appendChild(code);
    line.appendChild(copy);
    box.appendChild(line);
    const then = el("p", "hint", "Each hit comes with the line that adds it; ");
    then.appendChild(el("code", null, "caracole get 'Artist - Title'"));
    then.appendChild(document.createTextNode(" looks one up now."));
    box.appendChild(then);
    return box;
  };

  const MINE_SHOWN = 5;  // your songs at the top of the results; the grid has them all
  const SEARCH_PAUSE = 150;  // ms after the last key before the sites are searched
  const mineBox = el("div", "mine");
  const sitesBox = el("div", "sites");
  const group = (title, rows) => {
    const box = el("div", "rows");
    for (const row of rows) box.appendChild(row);
    return [el("h2", "group", title), box];
  };
  let asking = null;  // the search of the sites on its way, to abort
  let asked = 0;  // the newest search sent: an older one's answer is dropped
  let askTimer = 0;
  let askedFor = null;  // the query the newest search was sent for
  let answer = null;  // the answer on the screen, and its query
  let close = { q: null, ids: [] };  // your songs the server found (typos and all) for a query
  // Until the first answer since Enter, what goes under the results (the request form, the footer) waits too:
  // shown at once, the answer would only push it down.
  let waiting = true;
  const heard = () => {
    waiting = false;
    document.body.classList.remove("waiting-sites");
  };
  let settleSpots = () => {};
  let prefill = () => {};
  let getIt = () => {};
  let later = () => {};

  // Your songs that match what is typed, whatever the buttons show: the page's own rows, with what their cards
  // offer; then the server's close matches the filter missed.
  const drawMine = (query) => {
    const mine = ORDERS[state.sort].filter(typedMatch(query));
    const q = normal(state.q);
    const extra = close.q === q ? close.ids.map((id) => byIndex.get(id))
      .filter((i) => i !== undefined && mine.indexOf(i) < 0).slice(0, Math.max(0, MINE_SHOWN - mine.length)) : [];
    mineBox.textContent = "";
    if (mine.length) {
      mineBox.append(...group("In your library · " + mine.length, mine.slice(0, MINE_SHOWN).map(rowFor)));
      if (mine.length > MINE_SHOWN) {
        const every = el("p", "all-mine");
        every.appendChild(button("All " + mine.length + " of your songs", "small", () => leaveAll(true)));
        mineBox.appendChild(every);
      }
    }
    if (extra.length) {
      mineBox.append(...group(mine.length ? "Close to it, in your library" : "In your library, close to it",
        extra.map(rowFor)));
    }
  };
  const drawResults = (query, answerInList) => {
    const q = normal(state.q);
    const open = state.all && Boolean(q);
    if (!server) {  // the file: the line to run, above your songs, unless their empty list shows it already
      found.hidden = !open || answerInList;
      results.hidden = found.hidden;
      if (!found.hidden && found.dataset.query !== q) {
        found.replaceChildren(fileAnswer(q));
        found.dataset.query = q;
      }
      return;
    }
    results.hidden = !open;
    found.hidden = !open;
    document.body.classList.toggle("waiting-sites", open && waiting);
    if (!open) return;
    drawMine(query);
    askSources(false);
  };

  const askSources = (now) => {
    const q = normal(state.q);
    if (!now && q === askedFor) return;
    clearTimeout(askTimer);
    askTimer = setTimeout(() => sendAsk(q), now ? 0 : SEARCH_PAUSE);
  };
  const sendAsk = (q) => {
    if (!state.all || !q) return;
    askedFor = q;
    asked += 1;
    const mine = asked;
    if (asking) asking.abort();
    asking = new AbortController();
    say("Searching the sites…");
    found.setAttribute("aria-busy", "true");
    fetch("api/search?q=" + encodeURIComponent(q), {
      signal: asking.signal, credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" },
    }).then((r) => r.json().catch(() => null).then((body) => ({ ok: r.ok, status: r.status, body })))
      .then((reply) => {
        if (mine !== asked || !state.all) return;
        const data = reply.body && typeof reply.body === "object" ? reply.body : null;
        if (data && data.superseded) {  // another search went first: ask again, still the newest
          askTimer = setTimeout(() => sendAsk(q), SEARCH_PAUSE);
          return;
        }
        found.removeAttribute("aria-busy");
        heard();
        if (!reply.ok || !data || data.error) {
          say(failure(reply).line.text);
          return;
        }
        showSites(data, q);
      }, (e) => {
        if (mine !== asked || (e && e.name === "AbortError")) return;
        found.removeAttribute("aria-busy");
        heard();
        say(UNREACHABLE.line.text);
      });
  };
  // What a result's row stands for, the same in an older answer and a newer one: its site, its UG song, its names.
  const hitKey = (row) => [row.dataset.source, row.dataset.ug, row.querySelector(".row-title"),
    row.querySelector(".row-artist")].map((x) => (x && typeof x === "object" ? x.textContent : String(x || ""))).join("|");
  // The answer of the newest search, in one go: the old one stays until then, so nothing flashes.
  const showSites = (data, q) => {
    answer = { data, q };
    found.dataset.query = q;
    close = { q, ids: listOf(data.library).map((h) => Number(h && h.id)) };
    mineBox.hidden = false;
    drawMine(parseQuery(state.q));
    if (data.short) {
      sitesBox.replaceChildren();
      say("Type three letters or more to search the sites");
      return;
    }
    const objects = (value) => listOf(value).filter((x) => x && typeof x === "object");
    const artists = objects(data.artists);
    const index = objects(data.index);
    const gtp = objects(data.gtptabs);
    const ms = objects(data.musescore);
    const lcArtists = objects(data.lacuerda_artists);
    const lc = objects(data.lacuerda);
    const box = document.createDocumentFragment();
    // LaCuerda's artists, then its songs: the index holds every artist, songs of a few. First when it alone has the
    // artist the query names ("andres calamaro", where Ultimate Guitar has only weak rows: lacuerda_leads).
    const counted = [lcArtists.length ? many(lcArtists.length, "artist") : "", lc.length ? many(lc.length, "song") : ""];
    const lcGroup = lcArtists.length || lc.length ? group("LaCuerda · " + counted.filter(Boolean).join(" · "),
      [...lcArtists.map((a) => siteArtist(a, openSiteArtist)), ...lc.map((h) => siteHit(h, getIt, later))]) : [];
    if (data.lacuerda_leads === true) box.append(...lcGroup);
    // The artists the query names: first when one leads ("oasis"), after the songs when a song does.
    const named = artists.length ? group("Artists on Ultimate Guitar", artists.map((a) => artistHit(a, openArtist))) : [];
    if (data.lead === "artist") box.append(...named);
    if (index.length) box.append(...group("Ultimate Guitar · " + many(index.length, "song"), index.map((h) => ugHit(h, getIt, later))));
    if (data.lead !== "artist") box.append(...named);
    if (data.lacuerda_leads !== true) box.append(...lcGroup);
    // No artist of LaCuerda's by that name, under a letter its listings aren't read to yet: their page may say.
    const unlisted = data.lacuerda_unlisted && typeof data.lacuerda_unlisted === "object" ? data.lacuerda_unlisted : null;
    if (unlisted) {
      const [heading, offer] = siteUnlisted(unlisted, (go, at) => readThenShow({ name: String(unlisted.name || "") }, go, at));
      if (!lc.length) box.appendChild(heading);
      box.appendChild(offer);
    }
    if (gtp.length) {
      box.append(...group("Guitar Pro on gtptabs.com · " + many(gtp.length, "song"), gtp.map((h) => siteHit(h, getIt, later))));
    }
    if (ms.length) {
      box.append(...group("MuseScore · " + many(ms.length, "page") + " by that title", ms.map((h) => siteHit(h, getIt))));
    }
    const left = objects(data.skipped);
    if (left.length) {
      box.appendChild(el("p", "skipped", "Not searched: " +
        left.map((x) => String(x.name || x.source) + " (" + String(x.why || "") + ")").join("; ") + "."));
    }
    const partly = objects(data.partial);
    if (partly.length) {
      box.appendChild(el("p", "skipped partial", "Searched in part: " +
        partly.map((x) => String(x.name || x.source) + " (" + String(x.why || "") + ")").join("; ") + "."));
    }
    if (typeof data.hint === "string" && data.hint) box.appendChild(prose("hint index-hint", data.hint));
    // A row whose request is on its way stays, its line in it, where the newer answer has it; one the newer
    // answer lacks becomes its card under the bar (settleSpots), its line going on there.
    const going = new Map();
    for (const [id, node] of spots) {
      if (sitesBox.contains(node) && views.has(id) && isActive(views.get(id))) going.set(hitKey(node), node);
    }
    for (const fresh of box.querySelectorAll(".hit")) {
      const was = going.get(hitKey(fresh));
      if (!was) continue;
      fresh.replaceWith(was);
      going.delete(hitKey(fresh));
    }
    sitesBox.replaceChildren(box);
    if (going.size) settleSpots(true);
    const parts = [];
    if (index.length || artists.length) parts.push((index.length + artists.length) + " on Ultimate Guitar");
    if (lc.length || lcArtists.length) {
      parts[data.lacuerda_leads === true ? "unshift" : "push"]((lc.length + lcArtists.length) + " on LaCuerda");
    }
    if (gtp.length) parts.push(gtp.length + " on gtptabs.com");
    if (ms.length) parts.push(ms.length + " on MuseScore");
    say(parts.length ? parts.join(" · ") : "Nothing on the sites: request it by name below");
    prefill(data.lead || (lcArtists.length && !lc.length ? "artist" : null));  // an artist LaCuerda alone knows
  };

  // An artist's songs in place of the sites' results, yours by them first; All results, or typing, brings
  // those back.
  const artistPage = (key, offset, signal) => fetch("api/artist?key=" + encodeURIComponent(key) + "&offset=" + offset,
    { signal, credentials: "same-origin", headers: { Accept: "application/json" } })
    .then((r) => r.json().catch(() => null).then((body) => ({ ok: r.ok, status: r.status, body })))
    .then((reply) => {
      if (!reply.ok || !reply.body || reply.body.error) {
        say(failure(reply).line.text);
        return null;
      }
      return reply.body;
    }, (e) => {
      if (!(e && e.name === "AbortError")) say(UNREACHABLE.line.text);
      return null;
    });
  const openArtist = (a) => {
    clearTimeout(askTimer);
    asked += 1;
    const mine = asked;
    if (asking) asking.abort();
    asking = new AbortController();
    say("Listing " + String(a.artist) + "'s songs…");
    artistPage(String(a.artist_key || ""), 0, asking.signal).then((page) => {
      if (page && mine === asked && state.all) showArtist(page);
    });
  };
  const backToResults = () => {
    if (answer) showSites(answer.data, answer.q);
    input.focus();
  };
  const showArtist = (page) => {
    const box = document.createDocumentFragment();
    const head = el("div", "artist-head");
    const name = el("h2", null, page.artist);
    name.tabIndex = -1;
    head.appendChild(name);
    head.appendChild(button("All results", "small", backToResults, "Back to all the results"));
    box.appendChild(head);
    const theirs = listOf(page.library).map((x) => byIndex.get(Number(x && x.id))).filter((i) => i !== undefined);
    if (theirs.length) box.append(...group("Yours by " + page.artist, theirs.map(rowFor)));
    const [heading, rows] = group("Ultimate Guitar, the most tabbed first", listOf(page.songs).map((h) => ugHit(h, getIt, later)));
    box.appendChild(heading);
    box.appendChild(rows);
    let listed = listOf(page.songs).length;
    if (listed < Number(page.total)) {
      const more = el("p", "more-songs");
      const go = button("Show more (" + (page.total - listed) + " left)", "small", () => {
        go.disabled = true;
        artistPage(String(page.artist_key), listed).then((next) => {
          go.disabled = false;
          if (!next || !rows.isConnected) return;
          for (const h of listOf(next.songs)) rows.appendChild(ugHit(h, getIt, later));
          listed += listOf(next.songs).length;
          if (listed >= next.total || !listOf(next.songs).length) more.remove();
          else go.textContent = "Show more (" + (next.total - listed) + " left)";
        });
      }, "Show more of " + page.artist + "'s songs");
      more.appendChild(go);
      box.appendChild(more);
    }
    mineBox.hidden = true;  // the query's songs of yours: back with All results
    sitesBox.replaceChildren(box);
    say(page.artist + ": " + many(page.total, "song"));
    name.focus();
  };

  // A LaCuerda artist's songs in place of the sites' results, as an Ultimate Guitar artist's are: those the index
  // holds, or, while caracole hasn't read their page, a button that reads it (a job) and then lists them. ``who``
  // names them by the slug of their page ({ slug }) or by a name ({ name }: a page read by name); ``quiet``, a 404
  // isn't said.
  const sitePage = (who, signal) => fetch("api/artist?" + (who.slug ? "lacuerda=" + encodeURIComponent(String(who.slug))
    : "lacuerda_name=" + encodeURIComponent(String(who.name || ""))),
    { signal, credentials: "same-origin", headers: { Accept: "application/json" } })
    .then((r) => r.json().catch(() => null).then((body) => ({ ok: r.ok, status: r.status, body })))
    .then((reply) => {
      if (!reply.ok || !reply.body || reply.body.error) {
        if (!(who.quiet && reply.status === 404)) say(failure(reply).line.text);
        return null;
      }
      return reply.body;
    }, (e) => {
      if (!(e && e.name === "AbortError")) say(UNREACHABLE.line.text);
      return null;
    });
  const openSiteArtist = (a) => {
    clearTimeout(askTimer);
    asked += 1;
    const mine = asked;
    if (asking) asking.abort();
    asking = new AbortController();
    say("Listing the songs of " + String(a.artist) + " on LaCuerda…");
    sitePage({ slug: String(a.slug || "") }, asking.signal).then((page) => {
      if (page && mine === asked && state.all) showSiteArtist(page);
    });
  };
  // Read a LaCuerda page (``who``: { slug } or { name }) from the button ``go`` in ``offer``, then list the artist's
  // songs; a read that leaves none to list says what LaCuerda answered, under the offer.
  const readThenShow = (who, go, offer) => {
    const mine = asked;
    go.disabled = true;
    readArtistPage(server.csrf, who, say).then((read) => {
      if (mine !== asked || !state.all || !offer.isConnected) return;
      if (read.error) {
        go.disabled = false;
        say(read.error);
        return;
      }
      sitePage(Object.assign({ quiet: true }, who)).then((page) => {
        if (mine !== asked || !state.all || !offer.isConnected) return;
        if (page && page.read) {
          showSiteArtist(page);
          return;
        }
        const line = read.job && read.job.line && typeof read.job.line === "object" ? read.job.line : {};
        go.disabled = line.tone === "missing";  // no such page: asking again finds none either
        offer.querySelectorAll(".read-outcome").forEach((x) => x.remove());
        const said = readOutcome(read.job);
        offer.appendChild(said);
        say(said.firstChild.textContent.trim());
      });
    });
  };
  const showSiteArtist = (page) => {
    const box = document.createDocumentFragment();
    const head = el("div", "artist-head");
    const name = el("h2", null, page.artist);
    name.tabIndex = -1;
    head.appendChild(name);
    head.appendChild(button("All results", "small", backToResults, "Back to all the results"));
    box.appendChild(head);
    const theirs = listOf(page.library).map((x) => byIndex.get(Number(x && x.id))).filter((i) => i !== undefined);
    if (theirs.length) box.append(...group("Yours by " + page.artist, theirs.map(rowFor)));
    box.append(...siteArtistSongs(page, group, getIt, later,
      (go, offer) => readThenShow({ slug: String(page.slug || "") }, go, offer)));
    mineBox.hidden = true;
    sitesBox.replaceChildren(box);
    say(page.artist + ": " + (page.read ? many(page.total, "song") + " on LaCuerda" : "caracole hasn't read their page yet"));
    name.focus();
  };

  // Searching the sites: on Enter, Search all or the address (#all=1); on Enter again, at once.
  const enterAll = () => {
    if (!normal(state.q) || keyed(state.q)) {  // the line under the box says why a key searches no site
      input.focus();
      return;
    }
    state.all = true;
    render();
    save();
    if (server) {
      prefill(answer && answer.q === normal(state.q) ? answer.data.lead : null);
      askSources(true);
    }
  };
  const leaveAll = (focus) => {
    if (!state.all) return;
    state.all = false;
    clearTimeout(askTimer);
    if (asking) asking.abort();
    asked += 1;
    askedFor = null;
    found.removeAttribute("aria-busy");
    waiting = true;
    document.body.classList.remove("waiting-sites");
    settleSpots();
    render();
    save();
    if (focus) input.focus();
  };
  if (server) {
    const head = el("div", "results-head");
    head.appendChild(button("Back to your songs", "small", () => leaveAll(true), "Back to your songs (Escape)"));
    found.append(head, mineBox, sitesBox);
  }
  allButton.addEventListener("click", enterAll);
  // A key that ends an input method's word (pinyin, kana) is still typing, never a command.
  const composing = (e) => e.isComposing || e.keyCode === 229;
  input.addEventListener("keydown", (e) => {
    if (composing(e)) return;
    if (e.key === "Enter") {
      e.preventDefault();
      enterAll();
    } else if (e.key === "ArrowDown" && state.all && server) {  // on to the first result's button
      const first = found.querySelector(".row-action button, .row-action a");
      if (first) {
        e.preventDefault();
        first.focus();
      }
    }
  });
  document.addEventListener("keydown", (e) => {
    if (composing(e)) return;
    const typing = document.activeElement === input;
    if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      input.focus();
      input.select();
    } else if (e.key === "Escape" && state.all) {
      e.preventDefault();  // a search field clears itself on Escape: here it keeps what you typed
      leaveAll(!typing && results.contains(document.activeElement));
    } else if (e.key === "Escape" && typing && input.value) {
      setQuery("");
    }
  });
  // --- caracole serve: what the page does with a request's answers ----------------------------
  const tray = byId("tray");
  const trayList = byId("tray-list");
  const traySum = byId("tray-sum");
  const trayToggle = byId("tray-toggle");
  const trayItems = new Map();  // job id -> its line in the list of requests
  const quiet = new Set();  // the lookups of a songbook's missing songs: its card says how they go
  let trayClosed = false;
  // The list of requests, once there are two or more: one line each, not read out (the cards' lines are). A
  // songbook's change, or a removal, is left out: its card, where it was asked for, says how it goes.
  const trayShow = (view) => {
    if (!tray || view.kind === "songbook" || view.kind === "remove" || quiet.has(Number(view.id))) return;
    const id = Number(view.id);
    let item = trayItems.get(id);
    if (!item) {
      item = el("li");
      item.appendChild(el("span", "tray-song", view.display || ""));
      item.appendChild(el("p", "progress"));
      trayItems.set(id, item);
      trayList.prepend(item);
    }
    // One Details link, the list's own: a line here says how its request goes, and its card links the rest.
    const line = view.line && typeof view.line === "object" ? view.line : {};
    showLine(item.querySelector(".progress"), { line: Object.assign({}, line, { details: null }) });
    const shown = Array.from(trayItems.keys()).map((n) => views.get(n)).filter(Boolean);
    const going = shown.filter(isActive).length;
    traySum.textContent = plural(shown.length, "request") + (going ? " · " + going + " to go" : " · all done");
    tray.hidden = trayClosed || shown.length < 2;
    document.body.classList.toggle("with-tray", !tray.hidden);
  };
  // The cards drawn again from what the library has now: a request is over. Each keeps its line. A removal
  // done leaves its song's card saying so; a songbook's change, the Songbooks section drawn again.
  const redraw = (view) => {
    if (view.kind === "remove" && songOf(view) !== null) {
      removing.delete(songOf(view));
      if (view.state === "done") {
        removed(songOf(view));
        return;
      }
    }
    if (view.kind === "songbook" && view.songbooks && typeof view.songbooks === "object") {
      drawSongbooks(view);
      return;
    }
    const data = view.card && typeof view.card === "object" ? view.card : null;
    if (!data) return;
    const i = byIndex.get(Number(data.id));
    if (i !== undefined) {
      songs[i] = data;
      songKeys[i] = keyId(data.key);
      hay[i] = String(data.search || "");
      if (cards.has(i)) cards.set(i, refill(cards.get(i), makeCard(data)));  // else drawn when shown
      if (rows.has(i)) rows.set(i, refill(rows.get(i), songRow(data)));
    } else {
      arrived.set(Number(data.id), data);  // counted, and shown under the form until the next load
    }
    const spot = spots.get(Number(view.id));  // a result's row stays a row: the song's own, now
    if (spot) spots.set(Number(view.id), refill(spot, spot.classList.contains("row") ? songRow(data) : makeCard(data)));
    summarize();
    tallyChips();  // the grid itself stays as it is: a card the filter now hides goes at the next search
  };
  const songOf = (view) => (view.songId === null || view.songId === undefined ? null : Number(view.songId));
  // Whether a job that is over brings what the page draws again: its song's card (none for a song the library
  // hasn't got), or the Songbooks section, for a songbook's change; a removal's song is gone, or as it was.
  const drawable = (view) => (view.kind === "songbook" ? Boolean(view.songbooks)
    : view.kind === "remove" || Boolean(view.card) || songOf(view) === null);
  const apply = (view) => {
    const id = Number(view.id);
    views.set(id, view);
    const song = songOf(view);
    if (song !== null) {
      if (!songJob.has(song) || songJob.get(song) <= id) songJob.set(song, id);
      if (!isActive(view)) busy.delete(song);
    }
    if (!isActive(view) && !settled.has(id) && drawable(view)) {
      settled.add(id);
      redraw(view);
    }
    paint(view);
  };
  // The job's line on the cards and rows that show it, and in the list of requests.
  const paint = (view) => {
    const id = Number(view.id);
    const song = songOf(view);
    const i = song !== null && songJob.get(song) === id ? byIndex.get(song) : undefined;
    for (const card of [i === undefined ? null : cards.get(i), i === undefined ? null : rows.get(i), spots.get(id)]) {
      if (!card || (song !== null && removals.has(song))) continue;  // its line counts down to its removal
      const p = progressIn(card);
      showLine(p, view);
      if (view.kind === "remove") continue;  // its buttons wait where they are: the card is gone once it is done
      const button = card.querySelector("form.fetch");
      if (button && isActive(view)) {
        if (button.contains(document.activeElement)) focusOn(p);  // the line takes the button's place
        button.remove();
      }
      const picker = card.querySelector("form.pick-form");
      if (picker && isActive(view)) {  // POST /review would refuse a pick now: the card is drawn again after
        const box = picker.closest("details.picker");
        if (box.contains(document.activeElement)) focusOn(p);
        box.remove();
        const pick = card.querySelector(".row-pick");  // a row's button that opened it
        if (pick) {
          if (pick.contains(document.activeElement)) focusOn(p);
          pick.remove();
        }
      }
    }
    if (i !== undefined && view.kind === "song") bookSongs(song, view);
    trayShow(view);
  };
  // A song's line in the songbooks that hold it too (each song of a songbook names its id, data-song), under its
  // name: Get the missing songs now's lookups show there. Not read out: its songbook's own line says how it goes.
  const bookSongLine = (li, view) => {
    const names = li.querySelector(".sb-names");
    if (!names) return;
    const line = names.querySelector(".progress") || names.appendChild(el("span", "progress"));
    const said = view.line && typeof view.line === "object" ? view.line : {};
    showLine(line, { line: Object.assign({}, said, { details: null }) });
  };
  const bookSongs = (song, view) => {
    for (const li of document.querySelectorAll('#songbooks li[data-song="' + Number(song) + '"]')) bookSongLine(li, view);
  };
  const requestsCount = (n) => {
    const nav = document.querySelector('.navlink[href="/jobs"]');
    if (!nav) return;
    let badge = nav.querySelector(".n");
    if (!n) {
      if (badge) badge.remove();
      return;
    }
    if (!badge) {
      badge = el("span", "n");
      nav.appendChild(badge);
    }
    badge.textContent = String(n);
  };

  // A song caracole removed: its card, and its row, say so until the page is loaded again, with nothing left to
  // open, fetch or pick (its files are gone, and so is its data-id, which the Select mode finds songs by).
  const goneItem = (s, asRow) => {
    const artist = listOf(s.artists).length > 1 ? listOf(s.artists).join(", ") : String(s.artist);
    if (asRow) {
      const row = resultRow({ title: s.title, artist, status: "removed" });
      row.classList.add("gone");
      return row;
    }
    const card = el("article", "card gone");
    card.tabIndex = -1;
    card.appendChild(plainHead(s.monogram, s.hue, s.title, artist));
    return card;
  };
  const removed = (id) => {
    const i = byIndex.get(id);
    if (i === undefined) return;
    songs[i] = Object.assign({}, songs[i], { status: "removed" });
    // Drawn again where it is, as tall as it was, its line where it was: nothing on the screen moves, seconds
    // after the tap.
    const gone = (old, asRow) => {
      const fresh = goneItem(songs[i], asRow);
      if (!old) return fresh;
      const tall = old.isConnected ? old.getBoundingClientRect().height : 0;
      const line = old.querySelector(".progress");
      const top = line && old.isConnected ? line.getBoundingClientRect().top : null;
      const kept = refill(old, fresh);
      if (tall) kept.style.minHeight = tall + "px";
      if (line) line.style.minHeight = "";  // the last thing on the card, which keeps the height: as tall as it says
      if (top !== null && line.isConnected) {  // measured before a frame is drawn: it never moves
        const drop = top - line.getBoundingClientRect().top;
        if (drop > 0) line.style.marginTop = drop + "px";
      }
      return kept;
    };
    cards.set(i, gone(cards.get(i), false));
    rows.set(i, gone(rows.get(i), true));
    summarize();
    tallyChips();
    tell();
  };

  // --- caracole serve: the songbooks' forms ---------------------------------------------------------
  // ↑, ↓, × and Rename or delete in the Songbooks section, and the Select bar's Make songbook (or Add to),
  // post with fetch() as Fetch now does: the songbook's card says how its change goes, on a line under its
  // name, its buttons put away until the change is over (each moves a song by its place now); a songbook on
  // its way gets a card at the end of the section. Once a change is over, /jobs.json gives the section as
  // the server draws it now (the job's `songbooks`): the HTML the page was served with, read by DOMParser,
  // which runs no script of it, and put in place card by card, a card with a line kept where it is around
  // it, so that its line goes on being read out to the last. The section is in the served page even with
  // no songbook, hidden, for the first one. Without JavaScript the forms post as forms, and the server
  // answers with the requests page.
  const SONGBOOK_FORM = /^\/songbook\/(make|add|move|remove|rename|delete|get)$/;
  // job id -> {book: the songbook it changes, card: its card, focus: the button sent, reveal: from the Select bar}
  const bookJobs = new Map();
  const shelf = () => {
    const section = byId("songbooks");
    const details = section ? section.querySelector(":scope > details") : null;
    const list = details ? details.querySelector(":scope > .sb-list") : null;
    return list ? { section, details, list } : null;
  };
  const bookCard = (name) => {
    const at = shelf();
    return (at && Array.from(at.list.children).find((c) => c.dataset.songbook === name)) || null;
  };
  // A songbook card's line, under its name, made the first time, as a song card's is (progressIn).
  const bookLine = (card) => {
    let p = card.querySelector(".progress");
    if (!p) {
      p = el("p", "progress");
      p.setAttribute("role", "status");
      const head = card.querySelector(".sb-head");
      if (head) head.after(p);
      else card.prepend(p);
    }
    return p;
  };
  const lockBook = (card, on) => {
    card.classList.toggle("sb-busy", on);
    for (const control of card.querySelectorAll("form button, form input")) control.disabled = on;
    const at = document.activeElement;
    if (on && at && at.disabled && card.contains(at)) focusOn(bookLine(card));  // a disabled button drops it
  };
  // Deleted, or never made: a songbook's card says so where it was, as tall as it was, so that what is under it
  // doesn't move, until the page is loaded again.
  const goneBook = (card) => {
    const line = bookLine(card);
    const tall = card.isConnected ? card.getBoundingClientRect().height : 0;
    if (tall) card.style.minHeight = tall + "px";
    if (card.contains(document.activeElement) && !line.contains(document.activeElement)) focusOn(line);
    for (const child of Array.from(card.children)) {
      if (!child.classList.contains("sb-head") && child !== line) child.remove();
    }
    card.classList.remove("sb-busy");
    card.classList.add("sb-gone");
  };
  // The card that shows a songbook's change (a new songbook's, made for it at the end of the section): its
  // line says how the change goes, the newest change's alone, and its buttons wait until it is over.
  const bookSpot = (view, hint, focus) => {
    const book = view.songbook && typeof view.songbook === "object" ? view.songbook : null;
    const at = shelf();
    if (!book || !at) return null;
    let card = bookCard(String(book.name));
    if (!card) {
      card = el("article", "sb-card");
      card.dataset.songbook = String(book.name);
      const head = el("div", "sb-head");
      head.append(el("h2", null, String(book.name)), el("p", "hint", hint || ""));
      card.appendChild(head);
      at.list.appendChild(card);
      at.section.hidden = false;
    }
    bookLine(card);
    if (isActive(view)) lockBook(card, true);
    for (const [id, other] of spots) if (other === card) spots.delete(id);
    spots.set(Number(view.id), card);
    bookJobs.set(Number(view.id), { book, card, focus: focus || "" });
    return card;
  };
  // A card keeps the height ``tall`` while it is taller than what it holds, until your next click or key, when what
  // moves under it moves for you; measured before a frame is drawn, so nothing moves meanwhile.
  const holdHeight = (card, tall) => {
    const was = card.style.minHeight;
    card.style.minHeight = "";
    if (!tall || card.getBoundingClientRect().height >= tall - 0.5) return;
    card.style.minHeight = Math.max(tall, parseFloat(was) || 0) + "px";
    const release = () => {
      document.removeEventListener("click", release, true);
      document.removeEventListener("keydown", release, true);
      if (!card.classList.contains("sb-gone")) card.style.minHeight = "";
    };
    document.addEventListener("click", release, true);
    document.addEventListener("keydown", release, true);
  };
  const drawSongbooks = (view) => {
    const at = shelf();
    if (!at) return;
    const page = new DOMParser().parseFromString(String(view.songbooks.html || ""), "text/html");
    const fresh = page.querySelector("#songbooks > details");
    const count = at.details.querySelector(":scope > summary .n");
    const counted = fresh ? fresh.querySelector(":scope > summary .n") : null;
    if (count) count.textContent = counted ? counted.textContent : "0";
    // What the section says besides its songbooks: a songbooks.toml that can't be read.
    for (const part of Array.from(at.details.children)) {
      if (part.tagName !== "SUMMARY" && part !== at.list) part.remove();
    }
    for (const part of fresh ? Array.from(fresh.children) : []) {
      if (part.tagName !== "SUMMARY" && !part.classList.contains("sb-list")) {
        at.details.insertBefore(document.importNode(part, true), at.list);
      }
    }
    const job = bookJobs.get(Number(view.id));
    if (job && job.book.action === "rename" && view.state === "done") job.card.dataset.songbook = String(job.book.after);
    const old = Array.from(at.list.children);
    const kept = old.filter((c) => c.querySelector(".progress"));  // a change's line: read out to the last
    const tall = new Map(kept.map((c) => [c, c.isConnected ? c.getBoundingClientRect().height : 0]));
    const order = (fresh ? Array.from(fresh.querySelectorAll(":scope > .sb-list > .sb-card")) : []).map((f) => {
      const card = document.importNode(f, true);
      const was = kept.find((c) => c.dataset.songbook === card.dataset.songbook);
      if (!was) return card;
      bookLine(card);  // where its line goes
      return refill(was, card);
    });
    for (const card of kept) {
      if (order.indexOf(card) >= 0) continue;
      goneBook(card);
      order.splice(Math.min(old.indexOf(card), order.length), 0, card);
    }
    for (const card of old) if (order.indexOf(card) < 0) card.remove();
    let before = null;
    for (const card of order) {  // in the server's order, a card kept moved only if its place changed
      const next = before ? before.nextElementSibling : at.list.firstElementChild;
      if (card !== next) at.list.insertBefore(card, next);
      before = card;
    }
    at.section.hidden = !order.length && !at.details.querySelector(".sb-error");
    // Drawn again, its songs' lines are back under their names, and a card that showed a change keeps the height it
    // had while it is taller than what it holds now (its songs' "missing" notes gone, say), until your next click
    // or key: nothing under it moves seconds after your tap (a songbook from the Select bar is stretched, below).
    for (const [song, id] of songJob) {
      const shown = views.get(id);
      if (shown && shown.kind === "song") bookSongs(song, shown);
    }
    for (const card of kept) {
      if (card.isConnected && !card.classList.contains("sb-gone") && !(job && job.reveal && card === job.card)) {
        holdHeight(card, tall.get(card));
      }
    }
    for (const [id, other] of bookJobs) {  // the songbooks of changes still on their way wait
      if (id !== Number(view.id) && other.card.isConnected && views.has(id) && isActive(views.get(id))) {
        lockBook(other.card, true);
      }
    }
    // The focus waited on the line: back on the button it was sent with, where it is now (↓ again, say).
    if (job && job.focus && document.activeElement === job.card.querySelector(".progress")) {
      const again = Array.from(job.card.querySelectorAll("button"))
        .find((b) => !b.disabled && (b.getAttribute("aria-label") || b.textContent) === job.focus);
      if (again) again.focus();
    }
    // Made, or added to, from the Select bar: the songbook scrolls into view whole, if its line is still where
    // you left it (scrolling moves nothing on the page, as a card growing over what is on the screen would).
    if (job && job.reveal && view.state === "done" && job.card.isConnected) {
      const at = bookLine(job.card).getBoundingClientRect();
      if (at.top >= 0 && at.bottom <= window.innerHeight) {
        job.card.scrollIntoView({ block: "nearest", behavior: smooth() });
      }
    }
    // A card stretched while its change ran keeps that height while it is taller than what it holds now, until
    // your next click or key, when what moves under it moves for you.
    if (job && job.reveal && !isActive(view) && job.card.style.minHeight) {
      const stretched = parseFloat(job.card.style.minHeight);
      job.card.style.minHeight = "";
      holdHeight(job.card, stretched);  // no frame drawn in between: nothing moves
    }
    // The Select bar's menu of songbooks follows.
    document.dispatchEvent(new CustomEvent("caracole:songbooks", { detail: { books: listOf(view.songbooks.books) } }));
  };

  let timer = 0;
  let misses = 0;
  let stopped = false;
  const pending = () => Array.from(watched).filter((id) => !settled.has(id));
  const schedule = (delay) => {
    if (timer || stopped || !pending().length) return;
    timer = setTimeout(poll, delay !== undefined ? delay : document.hidden ? BACKGROUND_POLL : POLL);
  };
  // The server can't answer this page any more (it restarted, or signs in again): say so on each line.
  const stop = (text) => {
    stopped = true;
    for (const id of pending()) apply(Object.assign({}, views.get(id), { line: { tone: "failed", text } }));
  };
  const poll = () => {
    timer = 0;
    const ask = pending();
    fetch("jobs.json?jobs=" + ask.join(","), {
      credentials: "same-origin", cache: "no-store",
      headers: { Accept: "application/json", "X-Caracole-Form-Token": String(server.csrf || "") },
    }).then((r) => r.json().catch(() => null).then((body) => ({ ok: r.ok, status: r.status, body })))
      .then((answer) => {
        if (answer.status === 401 || answer.status === 403) {
          stop(failure(answer).line.text);
          return;
        }
        if (!answer.ok || !answer.body) {
          const e = new Error(String(answer.status));
          e.said = answer.body && typeof answer.body.error === "string" ? answer.body.error : "";
          throw e;
        }
        misses = 0;
        requestsCount(Number(answer.body.active) || 0);
        const seen = new Set();
        for (const view of listOf(answer.body.jobs)) {
          if (!view || typeof view !== "object" || !watched.has(Number(view.id))) continue;
          seen.add(Number(view.id));
          apply(view);
        }
        for (const id of ask) if (!seen.has(id)) settled.add(id);  // forgotten: the server keeps the last few
        schedule();
      })
      .catch((e) => {
        // The server is restarting, or the network is down: ask again, less and less often. From the third
        // miss in a row the lines say so, until an answer gives them back.
        misses += 1;
        if (misses >= MISSES) {
          const text = e && e.said ? String(e.said) + " Trying again…" : UNREACHABLE_NOW;
          for (const id of pending()) paint(Object.assign({}, views.get(id), { line: { tone: "waiting", text } }));
        }
        schedule(Math.min(POLL * 2 ** misses, 30000));
      });
  };
  track = (view) => {
    watched.add(Number(view.id));
    trayClosed = false;
    apply(view);
    schedule();
  };

  if (server) {
    const requested = byId("requested");
    const requestedGrid = byId("requested-grid");
    const placeholder = (artist, title) => {
      const card = el("article", "card pending");
      card.appendChild(plainHead((artist.match(/[\p{L}\p{N}]/u) || ["?"])[0].toUpperCase(), 0, title, artist));
      showLine(progressIn(card), { line: { tone: "queued", text: "Sending…" } });
      return card;
    };
    // A result's request, its line in the result's own row, from "Sending…" on: ``view`` finds the job in the
    // answer.
    const askFrom = (path, fields, names, row, go, view) => {
      if (!row) return;
      const line = progressIn(row);  // in the page before its first words, so they are read out
      showLine(line, { line: { tone: "queued", text: "Sending…" } });
      if (row.contains(document.activeElement)) focusOn(line);  // a disabled button would drop it
      if (go) go.disabled = true;
      const body = new URLSearchParams({ csrf: String(server.csrf || "") });
      for (const name of names) {
        if (fields && fields[name] !== undefined && fields[name] !== null && fields[name] !== "") {
          body.set(name, String(fields[name]));
        }
      }
      fetch(path, { method: "POST", body, credentials: "same-origin", headers: { Accept: "application/json" } })
        .then((r) => r.json().catch(() => null).then((answer) => ({ ok: r.ok, status: r.status, body: answer })))
        .then((reply) => {
          const job = reply.ok && reply.body && view(reply.body);
          if (go) go.disabled = false;
          if (!job || typeof job !== "object") {
            showLine(progressIn(row), failure(reply));
            return;
          }
          if (go && go.closest(".row-action, .later")) go.remove();  // its line takes the button's place
          spots.set(Number(job.id), row);
          track(job);
        }, () => {
          if (go) go.disabled = false;
          showLine(progressIn(row), UNREACHABLE);
        });
    };
    // Get it: the song looked up now (POST /lookup, one caracole get), to its sheet; a version picked under "⋯" too.
    getIt = (pick, display, row, go) => askFrom("lookup", pick, ["song", "artist", "title", "ug", "tab", "lacuerda"], row,
      go, (answer) => answer.view);
    // Add for tonight's run: the song into wanted.txt under the site's names (POST /request, not fetched now).
    later = (pick, display, row, go) => askFrom("request", pick, ["artist", "title", "lacuerda"], row, go,
      (answer) => answer.job);
    // Back to your songs: a request's row in the results that is a song new to the library becomes its card
    // under the bar, which goes on saying how it goes; a song the grid has says it on its own card. With
    // ``dropped``, only the rows a newer answer left out, at once.
    settleSpots = (dropped) => {
      for (const [id, node] of Array.from(spots)) {
        const left = !node.isConnected && node.classList.contains("hit");  // a newer answer has no such row
        if (dropped ? !left : !left && !results.contains(node)) continue;
        const view = views.get(id);
        const song = view ? songOf(view) : null;
        if (song !== null && byIndex.has(song)) {
          spots.delete(id);
          continue;
        }
        const [artist, ...title] = String((view && view.display) || "").split(" - ");
        const card = song !== null && arrived.has(song) ? makeCard(arrived.get(song))
          : title.length ? placeholder(artist, title.join(" - ")) : placeholder("", artist);
        if (view) showLine(progressIn(card), view);
        requestedGrid.prepend(card);
        requested.hidden = false;
        spots.set(id, card);
      }
    };
    for (const view of listOf(server.jobs)) {
      if (!view || typeof view !== "object") continue;
      watched.add(Number(view.id));
      const song = songOf(view);
      if (view.kind === "songbook") {
        bookSpot(view);  // a songbook's change: on its songbook's card
      } else if (requestedGrid && isActive(view) && view.kind === "song" && (song === null || !byIndex.has(song))) {
        // A song new to the library, on its way since before this page loaded: its card under the form.
        const [artist, ...title] = String(view.display || "").split(" - ");
        const spot = title.length ? placeholder(artist, title.join(" - ")) : placeholder("", artist);
        requestedGrid.appendChild(spot);  // newest first, as they come
        requested.hidden = false;
        spots.set(Number(view.id), spot);
      }
      apply(view);
    }
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && timer) {
        clearTimeout(timer);
        timer = 0;
        poll();
      }
    });
    if (tray) {  // folded, on every width: the cards say how each goes, and it would cover them
      trayToggle.addEventListener("click", () => {
        const open = trayToggle.getAttribute("aria-expanded") !== "true";
        trayToggle.setAttribute("aria-expanded", String(open));
        trayList.hidden = !open;
        tray.classList.toggle("open", open);
      });
      byId("tray-close").addEventListener("click", () => {
        for (const [id, item] of trayItems) {
          if (!isActive(views.get(id) || {})) {
            item.remove();
            trayItems.delete(id);
          }
        }
        trayClosed = true;
        tray.hidden = true;
        document.body.classList.remove("with-tray");
      });
    }
    // The request form, under the results: a card for the song at once, under the bar, which says how its
    // request goes. It is filled in from what was searched ("Artist - Title", or the artist alone when an
    // artist leads, else the title), each field until you type into it yourself.
    const requestForm = document.querySelector("form.request-form");
    const typedInto = new Set();
    if (requestForm) {
      for (const name of ["artist", "title"]) {
        const field = requestForm.elements.namedItem(name);
        if (field) field.addEventListener("input", () => typedInto.add(name));
      }
      prefill = (lead) => {
        const q = normal(state.q);
        const [first, ...rest] = q.split(" - ");
        const values = rest.length ? { artist: first.trim(), title: rest.join(" - ").trim() }
          : lead === "artist" ? { artist: q, title: "" } : { artist: "", title: q };
        for (const name of ["artist", "title"]) {
          const field = requestForm.elements.namedItem(name);
          if (field && !typedInto.has(name)) field.value = values[name];
        }
      };
    }
    const refused = new Set();  // the cards of requests the server refused, gone at the next one
    // The card #requested shows already for the job's song (or, before the song is in the library, for the
    // same "Artist - Title"), if any: asked for again, it is the one that says how this request goes.
    const spotOf = (view) => {
      const song = songOf(view);
      for (const [id, card] of spots) {
        const was = views.get(id);
        if (!was || !card.isConnected || !requestedGrid.contains(card)) continue;
        const same = song !== null && songOf(was) !== null ? songOf(was) === song : was.display === view.display;
        if (same) return [id, card];
      }
      return null;
    };
    if (requestForm && requested) {
      requestForm.addEventListener("submit", (e) => {
        e.preventDefault();
        for (const card of refused) card.remove();
        refused.clear();
        const field = (name) => requestForm.elements.namedItem(name);
        const typed = (name) => String(field(name).value || "").trim().replace(/\s+/g, " ");
        let spot = placeholder(typed("artist"), typed("title"));
        requestedGrid.prepend(spot);
        requested.hidden = false;
        if (state.all) spot.scrollIntoView({ block: "nearest", behavior: smooth() });  // under the bar, in view
        const button = requestForm.querySelector('button[type="submit"]');
        button.disabled = true;
        send(requestForm).then((answer) => {
          button.disabled = false;
          const view = answer.ok && answer.body && answer.body.job;
          if (!view) {
            showLine(progressIn(spot), failure(answer));
            refused.add(spot);
            return;
          }
          for (const name of ["artist", "title", "album", "duration"]) field(name).value = "";
          typedInto.clear();
          const id = Number(view.id);
          const shown = spots.has(id) ? [id, spots.get(id)] : spotOf(view);
          if (shown) {  // asked for again: its card says how it goes, where it is, its line still in the page
            spot.remove();
            spot = shown[1];
            if (shown[0] !== id) spots.delete(shown[0]);
          } else {
            const i = songOf(view) === null ? undefined : byIndex.get(songOf(view));
            if (i !== undefined) spot = refill(spot, makeCard(songs[i]));  // a song the library has: its card
          }
          spots.set(id, spot);
          track(view);
        }, () => {
          button.disabled = false;
          showLine(progressIn(spot), UNREACHABLE);
          refused.add(spot);
        });
      });
    }
    // The songbooks' forms, and the Select bar's, once its own script has checked it (an unchecked form is
    // stopped there): posted as the page's script, they leave you where you are.
    document.addEventListener("submit", (e) => {
      const form = e.target;
      if (e.defaultPrevented || !(form instanceof HTMLFormElement)) return;
      if (!SONGBOOK_FORM.test(form.getAttribute("action") || "")) return;
      e.preventDefault();
      const bar = form.closest(".pickbar");
      const card = bar ? null : form.closest(".sb-card");
      const sent = e.submitter ? e.submitter.getAttribute("aria-label") || e.submitter.textContent : "";
      const songs = form.elements.namedItem("songs");
      const many = songs ? String(songs.value).split(",").filter(Boolean).length : 0;
      const sending = send(form);  // the form read as it is, before its fields wait
      if (card) {
        showLine(bookLine(card), { line: { tone: "queued", text: "Sending…" } });
        if (/\/get$/.test(form.getAttribute("action") || "")) {  // each song it looks up, at once, under its name
          for (const li of card.querySelectorAll("li[data-get]")) {
            bookSongLine(li, { line: { tone: "queued", text: "Sending…" } });
          }
        }
        lockBook(card, true);
      }
      const answered = (view, refusal) => {
        // The Select bar says why the server refused it; told it is on its way, it lets the picks go.
        if (bar) form.dispatchEvent(new CustomEvent("caracole:sent", { detail: { ok: Boolean(view), error: refusal } }));
        if (!view) {
          if (card) {
            lockBook(card, false);
            showLine(bookLine(card), { line: { tone: "failed", text: refusal } });
          }
          return;
        }
        const spot = bookSpot(view, plural(many, "song"), sent);
        if (spot && bar) {  // from the Select bar, the section opens on the songbook
          shelf().details.open = true;
          // Its foot at the screen's (its head at the top, if it is taller than the screen): what it gains once
          // the change is over, its files and its songs, grows below the screen, and nothing on it moves then;
          // the page scrolls it into view whole after that (drawSongbooks). Near the top of the page, which
          // can't scroll that far, it is stretched to the screen's foot instead, now, as you tap.
          const box = spot.getBoundingClientRect();
          const taller = box.height > window.innerHeight * 0.75;
          const reach = window.innerHeight - 16 - (box.top + window.scrollY);
          if (!taller && reach > box.height) spot.style.minHeight = reach + "px";
          spot.scrollIntoView({ block: taller ? "start" : "end", behavior: smooth() });
          focusOn(bookLine(spot));
          bookJobs.get(Number(view.id)).reveal = true;
        }
        track(view);
      };
      sending.then((answer) => {
        const view = answer.ok && answer.body && answer.body.job;
        answered(view && view.songbook ? view : null, failure(answer).line.text);
        // Get the missing songs now: each song's lookup, on its card, its row and its line in the songbook.
        for (const each of view && view.songbook ? listOf(answer.body.jobs) : []) {
          if (!each || typeof each !== "object") continue;
          quiet.add(Number(each.id));
          track(each);
        }
      }, () => answered(null, UNREACHABLE.line.text));
    });
    schedule();
  }
  summarize();
  render();
  // Back from a page of caracole serve's about a song (Remove's question): its card in view, and the focus
  // on it, as the A-Z strip leaves it; the address keeps the rest. In the next frame, once every script
  // has drawn what it draws above the list (the Songbooks section, opened as it was left).
  let back = NaN;
  try {
    back = Number(new URLSearchParams(location.hash.slice(1)).get("song"));
  } catch (err) {
    // A malformed address: nothing to show.
  }
  if (back) {
    requestAnimationFrame(() => {
      const i = byIndex.get(back);
      const item = i === undefined ? null : (state.view === "rows" ? rows : cards).get(i);
      if (item && item.isConnected) {
        item.scrollIntoView({ block: "center" });
        item.focus({ preventScroll: true });
      }
      save();
    });
  }
})();
