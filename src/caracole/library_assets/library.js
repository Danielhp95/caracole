
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
  const barStatus = byId("bar-status");
  const results = byId("results");
  const found = byId("found");
  const sort = byId("sort");
  const count = byId("count");
  const jump = byId("jump");
  const artistChip = byId("artist");  // the artist's filter: a tag of the toolbar's
  // The toolbar's Filter, and the panel it opens (body.html): the songs' Status, what they have something for, their Key.
  const toolbar = document.querySelector(".toolbar");
  const filterButton = byId("filter");
  const panel = byId("filter-panel");
  const statusButtons = Array.from(panel.querySelectorAll("[data-show]"));
  const instChips = Array.from(panel.querySelectorAll("[data-inst]"));
  const modeButtons = Array.from(panel.querySelectorAll("[data-mode]"));
  const libraryView = byId("library-view");
  const progLine = byId("prog");
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
  // Served by caracole serve: its forms' token, and the songs it is fetching already. The one place the page tells
  // the two apart: the file on disk has no ``server``, and nor has caracole's Android app's offline copy, which is
  // that file (web/offline_routes.py), so both ask nothing of anyone, wherever they are opened.
  const server = data.server && typeof data.server === "object" ? data.server : null;
  const busy = new Set(listOf(server && server.busy).map(Number));
  const removing = new Set(listOf(server && server.removing).map(Number));
  // A timer of the page's, in ms: its own, unless the tests that drive it on real time set it (WebControls.timers).
  const paced = (name, ms) => {
    const set = server && server.timers && typeof server.timers === "object" ? Number(server.timers[name]) : NaN;
    return set > 0 && set < Infinity ? set : ms;
  };

  // The same folding as caracole's normalize.fold: NFKD, no accents, a few letters spelled out, lowercase.
  // An accent is a mark with a canonical combining class (unicodedata.combining), not every \p{Mn}: a Devanagari
  // vowel sign ("ु") has none, and stays, and a few \p{Mc} have one. JavaScript can't read the class, but canonical
  // ordering shows it: a mark with one goes before U+0301 (class 230) when its class is lower, or after U+0334 (1)
  // when it is higher, and one without moves nowhere.
  const classed = new Map();
  const accent = (ch) => {
    if (!classed.has(ch)) {
      const before = "x\u0301" + ch;
      const after = "x" + ch + "\u0334";
      classed.set(ch, /\p{M}/u.test(ch) && (before.normalize("NFD") !== before || after.normalize("NFD") !== after));
    }
    return classed.get(ch);
  };
  const fold = (text) => {
    let out = "";
    for (const ch of String(text).normalize("NFKD")) {
      if (!accent(ch)) out += own.call(table, ch) ? table[ch] : ch;
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
  // The names a command takes, each quoted, after "--" when one starts with "-" (-M-, an artist): caracole would
  // take it for an option ("No such option: -M"). caracole serve's own command lines always have it.
  const shellNames = (...names) => (names.some((n) => String(n).startsWith("-")) ? "-- " : "") +
    names.map(shellQuote).join(" ");
  const hay = songs.map((s) => String(s.search || ""));
  const inits = songs.map((s) => String(s.initials || ""));  // a title's initials: "wywh" finds Wish You Were Here

  const STATUS_TEXT = { found: "Found", wanted: "Wanted", ignored: "Ignored" };
  const LYRICS_TEXT = { pending: "Lyrics pending", missing: "No lyrics found", instrumental: "Instrumental" };
  const label = (texts, value) => (own.call(texts, value) ? texts[value] : "");
  const SHOWS = {
    all: () => true,
    found: (s) => s.status === "found",
    wanted: (s) => s.status === "wanted",
    // Not a song removed since the page loaded, which counts nowhere (counted, below), as found and wanted have it.
    review: (s) => Boolean(s.review) && s.status !== "ignored" && s.status !== "removed",
  };
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
  const normal = (text) => String(text).trim().replace(/\s+/g, " ");
  // Whether the sites can be searched for what is typed: words, and no key. Served, they are searched as you type
  // once there is enough to search: three letters or digits, two with a Chinese character, as /api/search looks
  // nowhere for fewer.
  const sitesCan = (text) => Boolean(normal(text)) && !keyed(text);
  const HAN = /\p{Script=Han}/u;
  const typedEnough = (text) => (normal(text).match(/[\p{L}\p{N}]/gu) || []).length >= (HAN.test(text) ? 2 : 3);
  const searchesAsYouType = (text) => Boolean(server) && sitesCan(text) && typedEnough(text);
  const songKeys = songs.map((s) => keyId(s.key));
  // Whether song i matches what is typed: each word in its search text, or its title's initials whole, and
  // each key typed.
  const typedMatch = (query) => (i) =>
    query.keys.every((k) => songKeys[i] === k) &&
    query.either.every((e) => songKeys[i] === e.key || (e.word && hay[i].indexOf(e.word) >= 0)) &&
    query.words.every((w) => hay[i].indexOf(w) >= 0 || (w.length > 1 && inits[i] === w));
  // Each song's progressions (progressions.py: a section's cycle in numerals, its key the same in every key and
  // rotation, "I V vi IV"), and the catalogue's names by key: a progression the catalogue names stands for every
  // progression of that name (the pop progression read in C major, and in A minor), as caracole search reads it.
  const CATALOGUE = data.catalogue && typeof data.catalogue === "object" ? data.catalogue : {};
  const progName = (key) => (own.call(CATALOGUE, key) ? String(CATALOGUE[key]) : "");
  const progsOf = (s) => listOf(s && s.progressions).filter((p) => p && typeof p.key === "string" && p.key);
  const playsProg = (s, key) => {
    const name = progName(key);
    return progsOf(s).some((p) => p.key === key || (name !== "" && progName(p.key) === name));
  };
  const progLabel = (key) => String(key).trim().split(/\s+/).join("–");
  // An address's progression as its key, as harmony.progression_key makes one of numerals given by their roots: "vi IV
  // I V", "vi–IV–I–V" and "IV I V vi IV I V vi" are all "I V vi IV", "bVII" is "♭VII".
  const progKeyOf = (text) => {
    const cycle = String(text).split(/[\s,–—-]+/).filter(Boolean).map((n) => n.replace(/^b/, "♭").replace(/^#/, "♯"))
      .filter((n, i, all) => i === 0 || n !== all[i - 1]);
    while (cycle.length > 1 && cycle[0] === cycle[cycle.length - 1]) cycle.pop();
    const n = cycle.length;
    let period = n;
    for (let p = 1; p < n; p++) {
      if (n % p === 0 && cycle.every((x, i) => x === cycle[i % p])) {
        period = p;
        break;
      }
    }
    const once = cycle.slice(0, period);
    let best = once;
    for (let i = 1; i < once.length; i++) {
      const turned = once.slice(i).concat(once.slice(0, i));
      const at = turned.findIndex((x, j) => x !== best[j]);
      if (at >= 0 && turned[at] < best[at]) best = turned;
    }
    return best.join(" ");
  };
  // A progression in numerals: its name when that is numerals ("ii–V–I", whose key is "I ii V"), else its key's.
  const progNumerals = (key) => {
    const name = progName(key);
    return name && progKeyOf(name) === key ? name : progLabel(key);
  };
  // "I–V–vi–IV, the pop progression"; "ii–V–I", whose name is its numerals.
  const progSaid = (key) => {
    const said = progNumerals(key);
    const name = progName(key);
    return name && name !== said ? said + ", " + name : said;
  };

  const compare = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  // Each key the library has, its spellings together ("F# / Gb minor"), with how many songs it has. Its commonest
  // spelling stands for it in the address (``key=``), and its tonic for the tonic in the Filter panel.
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
  // The Filter panel's Key: a mode (major or minor), a tonic (a pitch class, 0 for C), or both, an exact key. Its
  // twelve tonics in circle-of-fifths order, each named as the page names keys: as the library spells the key in the
  // mode chosen (in either, with none chosen), else as the circle does, in a minor key the way minor keys are spelt.
  const MODES = ["major", "minor"];
  const CIRCLE = [0, 7, 2, 9, 4, 11, 6, 1, 8, 3, 10, 5];
  const NAMED = { major: ["C", "D♭", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B"],
    minor: ["C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "G♯", "A", "B♭", "B"] };
  const signed = (text) => String(text).replace(/([A-G])#/g, "$1♯").replace(/([A-G])b/g, "$1♭");
  const tonicName = (pc, mode) => {
    const groups = (mode ? [mode] : ["major", "minor"]).map((m) => keyGroups.get(pc + " " + m)).filter(Boolean)
      .sort((a, b) => b.n - a.n);
    return groups.length ? signed(groups[0].value.replace(/ minor$/, "")) : NAMED[mode || "major"][pc];
  };
  // A key's name in words: "A minor", "F♯ / G♭ minor", "G major".
  const keyNamed = (pc, mode) => (keyGroups.has(pc + " " + mode) ? signed(keyGroups.get(pc + " " + mode).name)
    : tonicName(pc, mode) + " " + mode);
  const pitchOf = (i) => (songKeys[i] ? Number(songKeys[i].split(" ")[0]) : -1);
  const modeOf = (i) => (songKeys[i] ? songKeys[i].split(" ")[1] : "");
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
  // ROWS_SCRIPT's, which the lookup page shares; and a song's card (card.js), drawn with them.
  const rowKit = caracoleRows(ICONS);
  const { sourceMark, glyph, link, resultRow, artistFilter, artistSearch, artistOnly, button, many, indexLine,
    titleLine, readArtistPage, lacuerdaSearcher, readOutcome, didYouMean, nothingFound, lookedLine } = rowKit;
  const card = caracoleCard(ICONS, rowKit);
  // The file a song opens with, from its title and its line's button: its viewer, else its PDF, else its text
  // (the data marks it primary).
  const primaryOf = (s) => listOf(s.files).find((f) => f && f.primary) || null;
  // A line's button for it, its main action unless the server's control has its place (a wanted song's Fetch
  // now): "Open" for the viewer, "Open PDF" and "Open text" for the others. An auto sheet's says so in its name, as a
  // touch screen shows no title and YouTube's mark says only where the audio came from.
  const openButton = (s, f) => {
    const kind = /\.html$/i.test(String(f.name || "")) ? "" : /\.pdf$/i.test(String(f.name || "")) ? "PDF" : "text";
    const text = kind ? "Open " + kind : "Open";
    const open = link({ label: text, href: f.href }, "btn small primary", false);
    open.setAttribute("aria-label", text + (kind ? " of " : " ") + String(s.title) + " by " + String(s.artist) +
      (s.auto === true ? ", an auto sheet" : ""));
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
  // a refusal, or a server that doesn't answer, says so there, and ``go`` can be pressed again. ``viewOf``: the
  // job in the server's answer (its ``job``; a lookup's is its ``view``).
  const postInPlace = (form, go, s, viewOf) => {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const item = form.closest("article");
      const line = progressIn(item);  // in the page before its first words, so they are read out
      showLine(line, { line: { tone: "queued", text: "Sending…" } });
      if (form.contains(document.activeElement)) focusOn(line);  // a disabled button would drop it
      go.disabled = true;
      send(form).then((answer) => {
        const view = answer.ok && answer.body && (viewOf ? viewOf(answer.body) : answer.body.job);
        if (!view || typeof view !== "object") {
          go.disabled = false;
          showLine(progressIn(item), failure(answer));
          return;
        }
        if (item && !isOwn(s, item)) spots.set(Number(view.id), item);
        track(view);  // its line takes the form's place
      }, () => {
        go.disabled = false;
        showLine(progressIn(item), UNREACHABLE);
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
  // A song you have, looked up again now (POST /lookup with its id: one caracole get, its sheet first), as the lookup
  // page's Fetch again and its LaCuerda row's Get it again post it: with ``lacuerda``, that LaCuerda sheet kept, as
  // caracole get --lacuerda keeps it. Under its line's chevron, served alone; a refusal says why on the line. ``icon``:
  // a glyph before its words.
  const lookupForm = (s, label, aria, title, lacuerda, icon) => {
    const form = songForm("again", "/lookup", s);
    if (lacuerda) form.appendChild(hidden("lacuerda", lacuerda));
    const go = el("button", "btn small", label);
    if (icon) go.prepend(glyph(icon));
    go.type = "submit";
    go.setAttribute("aria-label", aria);
    go.title = title;
    form.appendChild(go);
    postInPlace(form, go, s, (body) => body.view);
    return form;
  };
  // The LaCuerda sheet of each song of yours that the bar's search found (a LaCuerda row of it with chords, which
  // mergeSites folds into its line), by song id: its line offers it until the page is loaded again.
  const lacuerdaFound = new Map();
  // The LaCuerda sheet a song could be looked up with: your pick on LaCuerda, else the best one caracole met for it
  // (the data's ``lacuerdaSheet``), else the one the search found; none when its sheet is LaCuerda's already.
  const lacuerdaOf = (s) => {
    if (listOf(s.files).some((f) => f && f.name === "sheet.txt" && f.source === "lacuerda")) return "";
    const url = String(s.lacuerdaSheet || lacuerdaFound.get(Number(s.id)) || "");
    return /^https:[/][/]/i.test(url) ? url : "";
  };
  // Under a song's chevron, served: Fetch again, for a song with its sheet (a wanted one has Fetch now), and Use
  // LaCuerda's sheet, when LaCuerda has one of it; neither for an ignored song, nor while a request of it waits or
  // runs (its line says how that goes, and the line is drawn again once it is over).
  const againActions = (s) => {
    if (s.status === "ignored") return null;
    const names = String(s.title) + " by " + String(s.artist);
    const box = el("div", "actions again");
    if (s.status === "found") {
      box.appendChild(lookupForm(s, "Fetch again", "Fetch " + names + " again",
        "Looks the song up anew now, as caracole get does: Ultimate Guitar's best sheet of it, then the rest", "",
        "refresh"));
    }
    const lacuerda = lacuerdaOf(s);
    if (lacuerda) {
      box.appendChild(lookupForm(s, "Use LaCuerda's sheet", "Get " + names + " again, keeping LaCuerda's sheet",
        "Looks the song up now and keeps this LaCuerda sheet, as caracole get --lacuerda does", lacuerda, "refresh"));
    }
    return box.childNodes.length ? box : null;
  };
  // A wanted song caracole fetch would refuse until its match is settled: a button that says so, and does nothing.
  const reviewFirst = (cls) => {
    const held = el("button", cls, "Review first");
    held.type = "button";
    held.disabled = true;
    held.title = "caracole review settles this match; then it can be fetched";
    return held;
  };
  // Every line's "Remove", under its chevron: one tap counts down REMOVE_WAIT seconds on the song's own line,
  // "Removing in 5 s · Undo", with what goes (the server's answer to the question, ``removal.brief``), and sends
  // nothing else meanwhile; then the removal, whose line the song's follows to Removed, never leaving the page.
  // Undo stops it. Without JavaScript the form posts, and caracole serve asks on a page of its own, whose answers
  // go back to the library as you left it (`back`: the address after #, its search, filters and sort).
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
    const go = el("button", "btn small remove", "Remove");
    go.prepend(glyph("trash"));
    go.type = "submit";
    go.setAttribute("aria-label", "Remove " + String(s.title) + " by " + String(s.artist) + " from caracole");
    go.title = "Delete the files caracole wrote for it, and keep caracole from bringing it back; Undo, for " +
      REMOVE_WAIT + " seconds, keeps it";
    form.appendChild(go);
    return form;
  };
  // The song's line, and the one that showed it elsewhere (#requested's), if any: where its removal shows.
  const removalItems = (id, r) => {
    const i = byIndex.get(id);
    const own = i === undefined ? [] : [lines.get(i)];
    return own.concat([r.spot]).filter((item, n, all) => item && all.indexOf(item) === n);
  };
  // A removal's line while it counts down: a screen reader hears it once ("Removing Creep in 5 seconds."), the
  // seconds left are for the eye; then Undo, and what goes. The item's other buttons wait meanwhile.
  const countdownIn = (item, r) => {
    const s = r.song;
    const p = progressIn(item);
    drawSteps(p, null);  // what the line says now is the removal, not a lookup
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
  // The forms post with fetch(), so the page stays where it is, and each song's line says on a line of its own how
  // its request goes. /jobs.json gives each request's line, and its song's data once it is over; the page asks
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
  const settled = new Set();  // watched jobs that are over, their lines drawn again
  const spots = new Map();  // job id -> what shows it outside the list (a result's row, #requested's line)
  const byIndex = new Map(songs.map((s, i) => [Number(s.id), i]));  // song id -> its place in songs
  const isActive = (view) => view.state === "queued" || view.state === "running";
  const jobOfSong = (id) => (songJob.has(Number(id)) ? views.get(songJob.get(Number(id))) : null);
  // Whether node is the song's own line in the list, which the page draws again itself; any other (#requested's,
  // a result's row) is a spot of the job's.
  const isOwn = (s, node) => {
    const i = byIndex.get(Number(s.id));
    return i !== undefined && lines.get(i) === node;
  };
  // A request's line, written into p only when it changed, so a screen reader hears each change once.
  // Its link says where to go next; details, the request's output on /jobs, follows it. ``counted``: a song's line or
  // a result's row (showRequest), which says how many of its lookup's steps are over, "· 4 of 7 done" (the view's
  // ``count``, while it runs).
  const showLine = (p, view, counted) => {
    const line = view && view.line && typeof view.line === "object" ? view.line : {};
    const to = line.link && typeof line.link === "object" ? line.link : null;
    const more = typeof line.details === "string" ? line.details : "";
    const count = counted && view && typeof view.count === "string" ? view.count : "";
    const key = [line.tone, line.text, to ? to.href : "", more, count].map(String).join("|");
    if (p.dataset.key === key) return;
    const focused = p !== document.activeElement && p.contains(document.activeElement);
    p.dataset.key = key;
    p.dataset.tone = String(line.tone || "");
    p.textContent = "";
    p.appendChild(el("span", null, line.text || ""));
    if (count) {
      const dot = el("span", "dot", "·");
      dot.setAttribute("aria-hidden", "true");
      p.append(dot, el("span", "steps-over", count));
    }
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
  // A lookup's steps (the view's ``steps``: outcome.py's, each its name, the site it names and its state) as chips
  // under its request line ``p`` (steps.css's, the requests page's markup): those done ticked, the one that runs lit
  // and the current step, those to come grey, a failed one crossed; a plain one ("Match: not on UG") its name alone.
  // No live region: the line above says how it goes; this is a list to read. None in the view (a request that runs no
  // lookup, or ended Ready, its steps folded away): none drawn.
  const STEP_MARKS = { done: "✓ ", failed: "✕ " };
  const STEP_STATES = ["waiting", "running", "done", "failed", "plain"];
  const stepsAfter = (p) => (p && p.nextElementSibling && p.nextElementSibling.classList.contains("step-chips")
    ? p.nextElementSibling : null);
  const drawSteps = (p, view) => {
    const chips = listOf(view && view.steps).filter((c) => c && typeof c === "object" && c.name);
    let box = stepsAfter(p);
    if (!chips.length) {
      if (box) box.remove();
      return;
    }
    const key = JSON.stringify(chips.map((c) => [c.name, c.source, c.state]));
    if (box && box.dataset.key === key) return;
    if (!box) {
      box = el("ol", "step-chips");
      box.setAttribute("aria-label", "Steps");
      p.after(box);
    }
    box.dataset.key = key;
    box.replaceChildren(...chips.map((c) => {
      const state = STEP_STATES.indexOf(c.state) >= 0 ? String(c.state) : "waiting";
      const chip = el("li", "step-chip " + state);
      if (state === "running") chip.setAttribute("aria-current", "step");
      if (own.call(STEP_MARKS, state)) {
        const mark = el("span", null, STEP_MARKS[state]);
        mark.setAttribute("aria-hidden", "true");
        chip.appendChild(mark);
      }
      chip.appendChild(document.createTextNode(String(c.name)));
      if (c.source) chip.append(" ", el("b", null, String(c.source)));
      if (state !== "plain") chip.appendChild(el("span", "visually-hidden", ": " + state));
      return chip;
    }));
  };
  // How a song's request goes on its line, a result's row or a line under the bar: its request line, with the count of
  // its lookup's steps over, and the steps under it. Ended Ready, the steps fold away and the line's words are for a
  // screen reader alone (rows.css), which hears the request end: the line is the song's, its title and its Open
  // opening the sheet. The focus, if the request line had it (Fetch now hands it there), goes to that Open, where
  // Fetch now was.
  const showRequest = (item, view) => {
    const p = progressIn(item);
    showLine(p, view, true);
    drawSteps(p, view);
    if (p.dataset.tone === "ready" && p === document.activeElement) {
      const open = item.querySelector(".line-action a, .row-action a");
      if (open) open.focus({ preventScroll: true });
    }
    return p;
  };
  // A song in review's line sends you to its picker (review?song=ID): on a line that has the picker, it opens
  // that one, where you are, rather than the picker's own page. The list of requests has none: it goes there.
  const pickHere = (e, p) => {
    const item = p.closest("article");
    const box = item && item.querySelector("details.picker");
    const href = e.currentTarget.getAttribute("href") || "";
    if (!box || !box.querySelector("form") || !/^review\?song=\d+$/.test(href)) return;
    e.preventDefault();
    showPicker(box);
  };
  // Opens a picker where it is, in its line's panel (its chevron's), which opens first. Opened, the picker
  // takes the focus to its first candidate (its toggle); open already, the focus goes there.
  const showPicker = (box) => {
    const panel = box.closest(".line-panel");
    if (panel && panel.hidden) {
      const more = panel.parentNode.querySelector(":scope > .line-more");
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
  // A song's request line, made the first time: role="status" has it read out when it changes. A live region
  // put in the page with its text already in it is not read out, so a song's line (or a result's row) keeps its
  // request line from the first text to the last (refill), and only that text changes.
  const progressIn = (item) => {
    let p = item.querySelector(".progress");
    if (!p) {
      p = el("p", "progress");
      p.setAttribute("role", "status");
      // A line of its own across the song's line, under its status (a row's, under its artist).
      const after = item.querySelector(":scope > .line-meta") || item.querySelector(".row-sub") ||
        item.querySelector(".row-title");
      if (after) after.after(p);
      else item.appendChild(p);
    }
    return p;
  };
  // The line old, drawn again as fresh (lineFor's) where it is, around its own request line, which never leaves
  // the page, and its steps under it, which the request's next view draws again; returns old. The focus, if it was on
  // something of old's that goes, moves to that line. Opened, it stays open, a drawer of its card closed.
  const refill = (old, fresh) => {
    const was = old.querySelector(":scope > .line-more");
    const more = fresh.querySelector(":scope > .line-more");
    const panel = fresh.querySelector(":scope > .line-panel");
    if (was && was.getAttribute("aria-expanded") === "true" && more && panel) {
      more.setAttribute("aria-expanded", "true");
      panel.hidden = false;
    }
    const kept = old.querySelector(".progress");
    if (!kept) {
      if (old.parentNode) old.replaceWith(fresh);
      return fresh;
    }
    const at = document.activeElement;
    const focused = at !== old && old.contains(at) && !kept.contains(at);  // on something that goes
    const steps = stepsAfter(kept);
    const drawn = progressIn(fresh);  // where fresh has its line
    const freshSteps = stepsAfter(drawn);
    for (const child of Array.from(old.childNodes)) if (child !== kept && child !== steps) child.remove();
    let before = true;
    for (const child of Array.from(fresh.childNodes)) {
      if (child === drawn) before = false;
      else if (child === freshSteps) continue;  // old's stay where they are
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
    method: "POST", body, headers: { Accept: "application/json" },
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
  // What a line shows under its chevron of a song with no picker: why its match waits (a review with no candidates
  // to pick from), or, on the file, the line that lists a song not found's search hits; else nothing (null).
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
  let searchFor = () => {};
  let setProg = () => {};
  // The line over the list while it shows a progression's songs alone: "Songs with I–V–vi–IV, the pop progression ·
  // Show all".
  const drawProg = () => {
    progLine.hidden = !state.prog;
    if (progLine.dataset.prog === state.prog) return;
    progLine.dataset.prog = state.prog;
    progLine.replaceChildren();
    if (!state.prog) return;
    progLine.append("Songs with " + progSaid(state.prog) + " · ", button("Show all", "small", () => {
      state.prog = "";
      render();
      save();
      input.focus();
    }, "Show every song, not only those with " + progNumerals(state.prog)));
  };
  // The song's progressions, as it plays them, for its card: each shows the songs that play it too.
  const progressionsOf = (s) => card.progressions(progsOf(s).map((p) => ({ text: String(p.plays || progLabel(p.key)),
    said: "Your songs with " + progSaid(p.key), go: () => setProg(p.key) })));

  // Lines: a song a line (resultRow's dense form, from ROWS_SCRIPT: the seam the module docstring describes), in
  // its artist's group. A line is an article titled by its h3; the A-Z strip moves the focus to its group.
  // A song's main action on its line when the server's control holds the line's button (``held``): a wanted
  // song's fetch, or the button that opens its picker; Removing… while caracole removes it; no button at all
  // (``action`` null) while its request, or its removal, waits or runs, as the line's request line then says
  // how it goes. Not held, the line's button opens its sheet (openButton), as it does on the file.
  const serverAction = (s, picker) => {
    const held = (action) => ({ held: true, action });
    if (server && removing.has(Number(s.id))) {
      const job = jobOfSong(s.id);
      if (job && job.kind === "remove") return held(null);
      const going = el("a", "line-busy", "Removing…");
      going.href = "/jobs";
      going.title = "See the requests";
      return held(going);
    }
    if (server && s.status === "wanted") {
      const job = jobOfSong(s.id);
      if ((job && isActive(job)) || busy.has(Number(s.id))) return held(null);
      if (s.fetchable === false && picker && picker.querySelector("form")) {
        // caracole fetch would refuse it until the match is picked: this opens the picker, in the line's panel.
        const pick = el("button", "btn small line-pick", "Pick the match");
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
  // A line's one word for where its song stands, when it needs something or isn't plainly yours: Needs review, Not
  // found, Wanted or Ignored. A song found, nearly every one, says nothing: null.
  const statusOf = (s) => (SHOWS.review(s) ? { kind: "review", text: "Needs review" }
    : s.notFound && s.status === "wanted" ? { kind: "missing", text: "Not found" }
    : s.status === "found" ? null
    : { kind: s.status, text: label(STATUS_TEXT, s.status) || s.status });
  // What a song holds, for its line's glyphs (rows.js ``holds``), read from its files and its instruments: its sheet
  // (the auto one, when it has no other; UG's Ukulele Chords), a Guitar Pro file or else a text tab, a harmonica tab,
  // its lyrics and a score you filed.
  const holdingsOf = (s) => {
    const names = listOf(s.files).map((f) => String((f && f.name) || ""));
    const has = (pattern) => names.some((n) => pattern.test(n));
    const plays = (x) => listOf(s.instruments).indexOf(x) >= 0;
    const holds = [];
    if (s.auto === true) holds.push("auto");
    else if (has(/^sheet[.](html|pdf|txt|cho)$/)) holds.push(plays("ukulele") ? "ukulele" : "sheet");
    if (has(/^guitar-\d+[.]/)) holds.push("guitar");
    else if (names.indexOf("tab.txt") >= 0) holds.push("tab");
    if (plays("harmonica")) holds.push("harmonica");
    if (has(/^lyrics[.](txt|lrc)$/)) holds.push("lyrics");
    if (plays("score")) holds.push("score");
    return holds;
  };
  // What a song has something for, as the Filter panel asks it (``inst=``, any of them): its closed line's holds,
  // read the same way: a chord sheet (the auto one, UG's Ukulele Chords), a guitar's (a Guitar Pro file or a text
  // tab), and, from its instruments, UG's Ukulele Chords, a harmonica tab and a score you filed.
  const INSTRUMENTS = ["sheet", "guitar", "ukulele", "harmonica", "score"];
  const instruments = new WeakMap();  // a song's data -> what it has something for, until the data changes
  const instOf = (s) => {
    if (!instruments.has(s)) {
      const holds = holdingsOf(s);
      const plays = listOf(s.instruments);
      const has = new Set();
      if (holds.some((h) => h === "sheet" || h === "auto" || h === "ukulele")) has.add("sheet");
      if (holds.indexOf("guitar") >= 0 || holds.indexOf("tab") >= 0) has.add("guitar");
      for (const x of ["ukulele", "harmonica", "score"]) if (plays.indexOf(x) >= 0) has.add(x);
      instruments.set(s, has);
    }
    return instruments.get(s);
  };
  // A list of them as the address writes it: the known ones, in the panel's order, each once.
  const instList = (names) => INSTRUMENTS.filter((x) => names.indexOf(x) >= 0).join(",");
  // Each as a tag names it, and as a sentence does ("with a harmonica tab or a score").
  const INST_TAG = { sheet: "Chord sheet", guitar: "Guitar tab", ukulele: "Ukulele", harmonica: "Harmonica",
    score: "Score" };
  const INST_SAID = { sheet: "a chord sheet", guitar: "a guitar tab", ukulele: "ukulele chords",
    harmonica: "a harmonica tab", score: "a score" };
  // A song's facts, under its line's chevron: the key in words and where it came from, the PDF's transposition, the
  // lyrics, when the song came, and its other artists.
  const factsOf = (s) => {
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
    const others = listOf(s.artists).slice(1).map(String);
    if (others.length) facts.appendChild(el("span", "with", "With " + others.join(", ")));
    return facts.childNodes.length ? facts : null;
  };
  // Under a line's chevron: Select, the song picked, and its bar to put it in a songbook there is or a new one
  // (select.js, which hears "caracole:pick"). Select knows the songs the page was loaded with: a song new to the
  // library since (Get it, a request) has none until the page is loaded again, as it would do nothing.
  const bookButton = (s) => {
    const go = button("Add to a songbook…", "small", () => {
      document.dispatchEvent(new CustomEvent("caracole:pick", { detail: { id: Number(s.id) } }));
    }, "Add " + String(s.title) + " by " + String(s.artist) + " to a songbook");
    go.prepend(glyph("book"));
    go.title = "Pick it, and any other songs, for a songbook";
    return go;
  };
  // A post of caracole serve's versions routes for a song, by its id (``action``: /versions/choose, /clear or
  // /keep-more), ``fields`` beside it; sent by the page's script, its request followed on the song's line.
  const versionsForm = (s, action, label, aria, title, fields) => {
    const form = songForm("versions-post", action, s);
    for (const [name, value] of Object.entries(fields || {})) form.appendChild(hidden(name, value));
    const go = el("button", "btn small", label);
    go.type = "submit";
    go.setAttribute("aria-label", aria);
    go.title = title;
    form.appendChild(go);
    postInPlace(form, go, s);
    return form;
  };
  // What a card's drawers do with a song's versions (card.js ``acts``), each made when its drawer opens. Served,
  // while no request of the song waits or runs (its line says how that goes) and it isn't ignored: Use this one
  // (``caracole versions --choose``, a [pin]), Back to caracole's pick (``--clear``), Fetch them (``--keep-more``,
  // "Fetch 6 more" when more are left than one lookup keeps), and LaCuerda's Use this one, the lookup that keeps
  // that LaCuerda sheet. From the file, which can ask nothing, the command that fetches the versions not kept.
  const drawerActs = (s) => {
    if (!server) return { keepMoreCommand: "caracole versions --keep-more " + shellNames(String(s.display)) };
    const id = Number(s.id);
    const title = String(s.title);
    const names = title + " by " + String(s.artist);
    const free = () => {
      const asked = jobOfSong(id);
      return s.status !== "ignored" && !removing.has(id) && !busy.has(id) && !(asked && isActive(asked));
    };
    return {
      choose: (v, ver) => (free() ? versionsForm(s, "/versions/choose", "Use this one", "Use " + ver + " of " + names,
        "Make it the sheet the title opens, as caracole versions --choose does: a [pin] in overrides.toml",
        { tab: String(v.tab) }) : null),
      clear: () => (free() ? versionsForm(s, "/versions/clear", "Back to caracole's pick",
        "Back to caracole's pick for " + names,
        "Take your choice out of [pin], as caracole versions --clear does: caracole picks the sheet again") : null),
      keepMore: (rest, n) => {
        if (!free() || !(n > 0)) return null;
        const some = n < rest;
        return versionsForm(s, "/versions/keep-more", some ? "Fetch " + n + " more" : "Fetch them",
          "Fetch " + (some ? n + " more versions" : rest === 1 ? "the version" : "the " + rest + " versions") + " of " +
          title + " from Ultimate Guitar",
          "Keeps them beside the sheet, one request each at a lookup's pace, as caracole versions --keep-more does");
      },
      useLaCuerda: (x, ver) => (free() ? lookupForm(s, "Use this one", "Use LaCuerda's " + ver + " of " + names,
        "Looks the song up now and keeps this LaCuerda sheet, as caracole get --lacuerda does", String(x.href)) : null),
    };
  };
  // A song's line: its title (which opens its sheet), its status when it needs something, what it holds, its key, its
  // main action; and under its chevron, its card (card.js): its facts, then what needs you (its picker or what to do
  // about its match, where its audio comes from, a LaCuerda pick, Look in the index), what you play from it as tiles
  // and their versions' drawer, its progressions, where else to find it, and its foot (Fetch again, Use LaCuerda's
  // sheet, Add to a songbook…, info.json, Remove).
  const lineFor = (s) => {
    const id = Number(s.id);
    const primary = primaryOf(s);
    const more = [];
    const facts = factsOf(s);
    if (facts) more.push(facts);
    // The picker, or the note that says why there is none.
    const picker = SHOWS.review(s) && listOf(s.candidates).length > 0 ? makePicker(s) : null;
    if (picker) {
      // The line's button says Pick the match: its picker folds as a read-only one does, "3 candidates".
      const summary = picker.querySelector("summary");
      summary.className = "picker-open";
      summary.textContent = plural(listOf(s.candidates).filter((c) => c && c.ref).length, "candidate");
      more.push(picker);
    } else {
      const why = unpicked(s);
      if (why) more.push(why);
    }
    const fromYouTube = youtubeNote(s);
    if (fromYouTube) more.push(fromYouTube);
    const picked = lacuerdaNote(s);
    if (picked) more.push(picked);
    if (server && s.notFound && s.status === "wanted" && !removing.has(id)) {
      const look = el("div", "actions");
      look.appendChild(lookLink(s, "btn small"));
      more.push(look);
    }
    // What you play from it, and every file a tile shows: the rest, any, a group of their own.
    const claimed = new Set();
    const shown = card.tiles(s, { guitar: Boolean(server && server.guitar), acts: drawerActs(s), claimed });
    if (shown) more.push(shown);
    const info = listOf(s.files).find((f) => f && f.name === "info.json") || null;
    const others = listOf(s.files).filter((f) => f && !claimed.has(f) && f !== info);
    if (others.length) more.push({ heading: "Files", links: others });
    if (server && !server.guitar && listOf(s.files).some((f) => f && typeof f.guitarPage === "string" && f.guitarPage)) {
      more.push(el("p", "note", "caracole serve can show Guitar Pro files in the browser once it has alphaTab " +
        "(CARACOLE_ALPHATAB_DIR): until then they are downloads."));
    }
    const progs = progressionsOf(s);
    if (progs) more.push(progs);
    const elsewhere = card.findElsewhere([{ heading: "Find the chords", links: s.links },
      { heading: "Scores on MuseScore", links: s.museScore }, { heading: "Buy the track for an auto sheet", links: s.buy }]);
    if (elsewhere) more.push(elsewhere);
    // The sheet is the line's button unless the server's control has its place (Fetch now beside an auto
    // sheet): its tile opens it all the same, as the title does.
    const control = serverAction(s, picker);
    const action = control.held ? control.action : primary ? openButton(s, primary) : null;
    const asked = server ? jobOfSong(id) : null;
    const again = server && !removing.has(id) && !busy.has(id) && !(asked && isActive(asked)) ? againActions(s) : null;
    const foot = card.foot(s, { actions: [again], book: byIndex.has(id) ? bookButton(s) : null, info,
      remove: server && !removing.has(id) ? removeForm(s) : null });  // removing: its action says so
    if (foot) more.push(foot);
    const artists = listOf(s.artists);
    const keyed = typeof s.key === "string" && s.key;
    const status = statusOf(s);
    const line = resultRow({
      dense: true,
      title: s.title,
      href: primary ? primary.href : "",
      artist: artists.length > 1 ? artists.join(", ") : s.artist,  // shown where no group names it
      holds: holdingsOf(s),  // its glyphs, in place of where each came from: the card says that
      status: s.status,
      key: keyed ? s.key : "",
      keyText: keyed ? keyText(s) : "",
      badges: status ? [status] : [],
      action,
      more,
      onArtist: () => {
        setArtist(String(s.sortArtist || ""));
        window.scrollTo(0, 0);
      },
      onSearch: server ? () => searchFor(String(s.artist)) : null,  // served, the name searches; the funnel filters
    });
    line.dataset.id = String(s.id);  // the Select mode finds the song's line by it
    // How the song's request goes, on a line of its own, and its lookup's steps under it.
    const job = server ? jobOfSong(id) : null;
    if (job) {
      showRequest(line, job);
    } else if (server && s.status === "wanted" && !removing.has(id) && busy.has(id)) {
      showLine(progressIn(line), { line: { tone: "running", text: "Fetching…" } });
    }
    if (removals.has(id)) countdownIn(line, removals.get(id));  // drawn again while its removal counts down
    return line;
  };
  const lines = new Map();  // song index -> its line, made the first time it shows
  const lineOf = (i) => {
    if (!lines.has(i)) lines.set(i, lineFor(songs[i]));
    return lines.get(i);
  };
  // An artist's group: a header that names them and counts the songs of theirs you have, "Soda Stereo · you have
  // 2" (``counts.mine``: all of them, whatever the search or a filter leaves out), and, while the served page searches
  // the sites, the songs each site's index lists of theirs, "· UG 96 · LaCuerda 140 · Guitar Pro 12" (``counts.ug``,
  // ``counts.lacuerda``, ``counts.gtptabs``: gtptabs.com's; ``counts.note``, any other words); then their lines. Served,
  // the name searches for them (searchFor; not a group that names no artist, ``artist.search`` false: MuseScore's), and,
  // once you have songs of theirs, the funnel beside it shows those alone (``artist.filter``, their sortArtist, else
  // ``artist.key``); from a file, which can't search the sites, the name is the funnel's.
  let groupSerial = 0;
  const artistGroup = (artist, items, counts) => {
    const a = artist && typeof artist === "object" ? artist : { name: artist };
    const name = String(a.name || "");
    const filter = String(own.call(a, "filter") ? a.filter : a.key || "");
    const c = counts && typeof counts === "object" ? counts : {};
    const mine = Number(c.mine) || 0;
    const section = el("section", "artist");
    section.dataset.artist = String(a.key || "");
    section.tabIndex = -1;  // the A-Z strip moves the focus to it
    const heading = el("h2", "artist-title");
    groupSerial += 1;
    heading.id = "artist-" + groupSerial;
    section.setAttribute("aria-labelledby", heading.id);
    const only = () => {
      setArtist(filter);
      window.scrollTo(0, 0);
    };
    if (server && name && a.search !== false) {
      heading.appendChild(artistSearch(name, () => searchFor(name)));
      if (filter && mine) heading.appendChild(artistOnly(name, only));
    } else {
      heading.appendChild(filter && mine ? artistFilter(name, name, only) : el("span", "artist-name", name));
    }
    const said = [mine ? "you have " + mine : "", Number(c.ug) ? "UG " + Number(c.ug).toLocaleString("en") : "",
      Number(c.lacuerda) ? "LaCuerda " + Number(c.lacuerda).toLocaleString("en") : "",
      Number(c.gtptabs) ? "Guitar Pro " + Number(c.gtptabs).toLocaleString("en") : "",
      Number(c.harptabs) ? "Harmonica " + Number(c.harptabs).toLocaleString("en") : "", c.note ? String(c.note) : ""]
      .filter(Boolean);
    if (said.length) heading.appendChild(el("span", "artist-counts", " · " + said.join(" · ")));
    section.appendChild(heading);
    const box = el("div", "lines");
    for (const item of listOf(items)) box.appendChild(item);
    section.appendChild(box);
    return section;
  };
  // For lists the page doesn't make itself (the served page's type-ahead): the same rows and marks.
  window.caracole = Object.freeze({ resultRow, sourceMark, icons: ICONS });

  // artist: one artist's songs alone, by sortArtist, which a search for the name wouldn't give
  // ("Queen" also finds "Dancing Queen").
  // mode, tonic: the songs in a mode, on a tonic (its pitch class, "9" for A), or both, in one key.
  // inst: the songs that have something for any of these (INSTRUMENTS, comma-separated), in the panel's order.
  // all: the search of the sites under the bar: served, as you type (searchesAsYouType); on the file, the line that
  // searches them, on Enter.
  // prog: the songs that play a progression alone, by its key (#prog=, from under a song's chevron, a viewer's Harmony
  // panel or the served search).
  const state = { q: "", show: "all", sort: "artist", artist: "", mode: "", tonic: "", inst: "", prog: "", all: false };
  const artistName = (key) => {
    const s = key ? songs.find((song) => String(song.sortArtist || "") === key) : undefined;
    return s ? String(s.artist) : "";
  };
  // The key of the artist named ``name`` (their sortArtist): the songs' artist as written, else as fold reads it.
  const artistKey = (name) => {
    const s = songs.find((song) => String(song.artist) === name) ||
      songs.find((song) => fold(String(song.artist)) === fold(name));
    return s ? String(s.sortArtist || "") : "";
  };
  // What the address says of the list (save() writes it): what the page opens on, and what Back brings again.
  const addressed = () => {
    const at = { q: "", show: "all", sort: "artist", artist: "", mode: "", tonic: "", inst: "", prog: "", all: false };
    try {
      const params = new URLSearchParams(location.hash.slice(1));
      at.q = params.get("q") || "";
      if (artistName(params.get("artist") || "")) at.artist = params.get("artist");
      if (own.call(SHOWS, params.get("show"))) at.show = params.get("show");
      if (SORTS.indexOf(params.get("sort")) >= 0) at.sort = params.get("sort");
      // key: an exact key, as the Key menu wrote it once, in any spelling the library has; else a mode, a tonic.
      const exact = keyId(params.get("key"));
      const tonicAt = keyId(params.get("tonic"));
      if (keyGroups.has(exact)) {
        [at.tonic, at.mode] = exact.split(" ");
      } else {
        if (MODES.indexOf(params.get("mode")) >= 0) at.mode = params.get("mode");
        if (tonicAt) at.tonic = tonicAt.split(" ")[0];
      }
      at.inst = instList(String(params.get("inst") || "").split(","));
      at.prog = progKeyOf(String(params.get("prog") || "").slice(0, 200));
      at.all = params.get("all") === "1" && sitesCan(at.q) && (!server || typedEnough(at.q));
      // by: an artist's name, as a sheet viewer's artist line links here (viewer/page.py artist_line), for what
      // pressing their name here does: served, the search for them (searchFor's, which asks no site); from a file and
      // in the Android app's copy, which can't search the sites, their songs alone (the funnel's), else the songs the
      // name finds. Read once: the page then writes its own address for it (``cameBy``, below).
      const by = normal(params.get("by") || "");
      if (by && !at.q && !at.artist && !at.prog) {
        if (server) {
          at.q = by;
          at.all = searchesAsYouType(by);
        } else if (artistKey(by)) {
          at.artist = artistKey(by);
        } else {
          at.q = by;
        }
      }
    } catch (err) {
      // A malformed address: the defaults.
    }
    return at;
  };
  Object.assign(state, addressed());
  const tonicButtons = CIRCLE.map((pc) => {
    const b = el("button");
    b.type = "button";
    b.dataset.pc = String(pc);
    b.setAttribute("aria-pressed", "false");
    byId("tonics").appendChild(b);
    return b;
  });
  // The filters of the panel that are on, as Filter counts them: the status, each instrument, and the key.
  const instsChosen = () => (state.inst ? state.inst.split(",") : []);
  const keyChosen = () => Boolean(state.mode || state.tonic);
  const filtersOn = () => (state.show !== "all" ? 1 : 0) + instsChosen().length + (keyChosen() ? 1 : 0);
  // The key chosen in words: "A minor" (both), "a minor key" (the mode), "E major or minor" (the tonic).
  const keySaid = () => (state.mode && state.tonic ? keyNamed(Number(state.tonic), state.mode)
    : state.mode ? "a " + state.mode + " key" : tonicName(Number(state.tonic), "") + " major or minor");
  // The filters the songs list keeps to, the search aside: the panel's and the artist's. Clear (the toolbar's), Clear
  // all (the panel's) and an empty list's Show all let every one go; the search stays.
  const filtered = () => filtersOn() > 0 || Boolean(state.artist);
  const clearFilters = () => {
    state.show = "all";
    state.inst = "";
    state.mode = "";
    state.tonic = "";
    state.artist = "";
  };
  // Them in words, for an empty list: "wanted songs of Eagles with a harmonica tab in B minor", "songs needing review".
  const STATUS_SAID = { found: "found songs", wanted: "wanted songs" };
  const filtersSaid = () => {
    const words = [label(STATUS_SAID, state.show) || "songs"];
    if (state.artist) words.push("of " + artistName(state.artist));
    if (state.inst) words.push("with " + instsChosen().map((x) => INST_SAID[x]).join(" or "));
    if (keyChosen()) words.push("in " + keySaid());
    if (state.show === "review") words.push("needing review");
    return words.join(" ");
  };
  const filterCount = byId("filter-count");
  const filterLive = byId("filter-live");
  const showN = byId("show-n");
  const glyphFor = caracoleRows({}).glyph;
  filterButton.prepend(glyphFor("sliders"));
  for (const c of instChips) c.prepend(glyphFor(c.dataset.inst));
  sort.before(glyphFor("sort"));
  const save = () => {
    const params = new URLSearchParams();
    let was = new URLSearchParams();
    try {
      was = new URLSearchParams(location.hash.slice(1));
    } catch (err) {
      // A malformed address: nothing of the Songbooks tab's to keep.
    }
    for (const name of ["tab", "book"]) if (was.get(name)) params.set(name, was.get(name));  // songbooks.js's
    if (state.q) params.set("q", state.q);
    if (state.show !== "all") params.set("show", state.show);
    if (state.sort !== "artist") params.set("sort", state.sort);
    if (state.artist) params.set("artist", state.artist);
    // An exact key, as the address had it before (the library's commonest spelling); else its mode and its tonic.
    if (state.mode && state.tonic && keyGroups.has(state.tonic + " " + state.mode)) {
      params.set("key", keyGroups.get(state.tonic + " " + state.mode).value);
    } else {
      if (state.mode) params.set("mode", state.mode);
      if (state.tonic) params.set("tonic", tonicName(Number(state.tonic), state.mode));
    }
    if (state.inst) params.set("inst", state.inst);
    if (state.prog) params.set("prog", state.prog);
    if (state.all) params.set("all", "1");
    try {
      history.replaceState(null, "", "#" + params.toString());
    } catch (err) {
      // Some browsers refuse this for local files; the page works the same, it just isn't remembered.
    }
  };

  const plural = (n, word) => n + " " + word + (n === 1 ? "" : "s");
  const arrived = new Map();  // song id -> the data of a song new to the library since the page loaded
  // A song removed since the page loaded counts nowhere, though its line says Removed until the next load.
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

  // How many of the songs the search and filters match each option of the panel would show; a line drawn again
  // changes it. matchingNow: the songs the search, the artist's filter and the progression leave, the panel's
  // filters aside.
  let matchingNow = [];
  let shownNow = [];
  const keyFits = (i) => (!state.mode || modeOf(i) === state.mode) && (!state.tonic || pitchOf(i) === Number(state.tonic));
  const instFits = (i) => !state.inst || instsChosen().some((x) => instOf(songs[i]).has(x));
  // An option's count: the songs it would show chosen, the panel's other groups as they are.
  const tallyChips = () => {
    const tally = { all: 0, found: 0, wanted: 0, review: 0 };
    const having = { sheet: 0, guitar: 0, ukulele: 0, harmonica: 0, score: 0 };
    const onTonic = CIRCLE.map(() => 0);  // by pitch class: the songs on it in the mode chosen
    for (const i of matchingNow) {
      if (!counted(songs[i])) continue;
      const keyed = keyFits(i);
      const held = instFits(i);
      const shows = SHOWS[state.show](songs[i]);
      if (keyed && held) {
        tally.all += 1;
        for (const k of ["found", "wanted", "review"]) if (SHOWS[k](songs[i])) tally[k] += 1;
      }
      if (keyed && shows) for (const x of instOf(songs[i])) having[x] += 1;
      if (held && shows && pitchOf(i) >= 0 && (!state.mode || modeOf(i) === state.mode)) onTonic[pitchOf(i)] += 1;
    }
    // The Key, there once a song has one: the mode chosen, then each tonic, dashed and not to be pressed where no song
    // is on it in that mode (one chosen can always be let go).
    byId("keys").hidden = keyGroups.size === 0 && !keyChosen();
    for (const b of modeButtons) {
      const on = b.dataset.mode === state.mode;
      b.setAttribute("aria-checked", String(on));
      b.tabIndex = on ? 0 : -1;
    }
    for (const b of tonicButtons) {
      const pc = Number(b.dataset.pc);
      const on = state.tonic === b.dataset.pc;
      const n = onTonic[pc];
      b.textContent = tonicName(pc, state.mode);
      b.setAttribute("aria-pressed", String(on));
      b.setAttribute("aria-label", b.textContent + (state.mode ? " " + state.mode : "") + ": " +
        (n ? plural(n, "song") : "no songs"));
      b.disabled = !on && n === 0;
    }
    // An instrument no song has here is greyed and can't be pressed, unless it is on: pressed again, it goes. The
    // group shows once a song has something but a chord sheet, and each line's glyph of one that is on is lit.
    const chosen = instsChosen();
    for (const c of instChips) {
      const on = chosen.indexOf(c.dataset.inst) >= 0;
      c.setAttribute("aria-pressed", String(on));
      c.querySelector(".n").textContent = String(having[c.dataset.inst]);
      c.disabled = !on && having[c.dataset.inst] === 0;
    }
    byId("f-insts").hidden = !chosen.length && !songs.some((s) => counted(s) &&
      Array.from(instOf(s)).some((x) => x !== "sheet"));
    libraryView.dataset.lit = chosen.join(" ");
    // Review, only while a song needs it (or while it is the one chosen).
    const reviewing = songs.some((s) => SHOWS.review(s)) || Array.from(arrived.values()).some((s) => SHOWS.review(s));
    for (const b of statusButtons) {
      const on = b.dataset.show === state.show;
      b.setAttribute("aria-checked", String(on));
      b.tabIndex = on ? 0 : -1;
      b.querySelector(".n").textContent = String(tally[b.dataset.show]);
      b.hidden = b.dataset.show === "review" && !reviewing && !on;
    }
    // Filter says how many of its filters are on, in the accent.
    const on = filtersOn();
    filterButton.classList.toggle("on", on > 0);
    filterCount.hidden = !on;
    filterCount.textContent = on ? String(on) : "";
    filterButton.setAttribute("aria-label", on ? "Filter, " + on + " on" : "Filter");
  };
  // How many songs the list shows, of how many; and in the panel, "4 songs", or on a phone "Show 4 songs".
  const tell = () => {
    const total = songs.filter(counted).length;
    const n = shownNow.filter((i) => counted(songs[i])).length;
    count.textContent = n === total ? plural(total, "song") : n + " of " + plural(total, "song");
    filterLive.textContent = plural(n, "song");
    showN.textContent = "Show " + plural(n, "song");
  };

  const render = () => {
    const query = parseQuery(state.q);
    const fits = typedMatch(query);
    matchingNow = ORDERS[state.sort].filter((i) =>
      (!state.artist || String(songs[i].sortArtist || "") === state.artist) &&
      (!state.prog || playsProg(songs[i], state.prog)) && fits(i));
    tallyChips();
    const matching = matchingNow.filter((i) => keyFits(i) && instFits(i));
    const shown = matching.filter((i) => SHOWS[state.show](songs[i]));
    sort.value = state.sort;
    if (Boolean(server) && state.all) closePanel(false);  // the sites' results take the list's place, its tools too
    clear.hidden = !state.q;
    drawTags();
    drawProg();
    // Searching the sites, served: the results take the list's place, its tools with it, until Escape.
    const searchingAll = Boolean(server) && state.all;
    document.body.classList.toggle("searching-all", searchingAll);
    drawBar(matching.length === 0, query.keys.length > 0);
    let answerInList = false;  // the file's line that searches the sites, in the list's empty state
    if (searchingAll) {
      drawResults(query, false);
      return;
    }

    // By artist, a group of lines per artist, A to Z, each song's line under its artist's name. By title or by
    // when they came, the lines alone, each with its artist. The strip jumps to a letter's first group, or line.
    list.textContent = "";
    jump.textContent = "";
    const letterOf = LETTERS[state.sort];
    const firsts = new Map();
    const first = (letter, item) => {
      if (!firsts.has(letter)) firsts.set(letter, item);
    };
    if (state.sort === "artist") {
      const runs = [];  // ORDERS.artist has each artist's songs together
      for (const i of shown) {
        const key = String(songs[i].sortArtist || "");
        if (!runs.length || runs[runs.length - 1].key !== key) runs.push({ key, items: [] });
        runs[runs.length - 1].items.push(i);
      }
      // How many songs of each artist you have, the songs the search or a filter leaves out too.
      const yours = new Map();
      for (const s of songs.concat(Array.from(arrived.values())).filter(counted)) {
        const key = String(s.sortArtist || "");
        yours.set(key, (yours.get(key) || 0) + 1);
      }
      const groups = el("div", "groups");
      for (const { key, items } of runs) {
        const group = artistGroup({ key, name: String(songs[items[0]].artist) }, items.map(lineOf),
          { mine: yours.get(key) || 0 });
        first(String(songs[items[0]].artistLetter || "#"), group);
        groups.appendChild(group);
      }
      if (runs.length) list.appendChild(groups);
    } else if (shown.length) {
      const flat = el("section", "flat");
      flat.appendChild(el("h2", "visually-hidden", state.sort === "title" ? "Your songs by title"
        : "Your songs, the newest first"));
      const box = el("div", "lines");
      for (const i of shown) {
        const line = lineOf(i);
        if (letterOf) first(String(songs[i][letterOf] || "#"), line);
        box.appendChild(line);
      }
      flat.appendChild(box);
      list.appendChild(flat);
    }
    for (const [letter, item] of firsts) {
      const to = el("button", null, letter);
      to.type = "button";
      to.setAttribute("aria-label", "Jump to " + letter);
      to.addEventListener("click", () => {
        item.scrollIntoView({ block: "start", behavior: smooth() });
        item.focus({ preventScroll: true });  // so the next Tab goes on from there
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
    } else if (!shown.length && filtered() && (loose(fits) || !state.q)) {
      // The filters hide what the search finds (or every song): say which, every one, and offer them all.
      list.appendChild(el("p", "empty", "No " + filtersSaid() + (state.q ? " match “" + state.q + "”." : ".")));
      const n = loose(fits);
      const all = el("button", "btn", state.q ? "Show all " + n + " match" + (n === 1 ? "" : "es") : "Show all");
      all.type = "button";
      all.addEventListener("click", () => {
        clearFilters();
        render();
        save();
      });
      list.appendChild(all);
    } else if (!shown.length && state.prog) {
      // The progression hides them: the line above says which, with Show all.
      list.appendChild(el("p", "empty", state.q ? "No songs with " + progNumerals(state.prog) + " match “" + state.q + "”."
        : "No songs of yours play " + progNumerals(state.prog) + "."));
    } else if (!shown.length && state.q) {
      list.appendChild(el("p", "empty", "No songs match “" + state.q + "”."));
      if (!query.keys.length && server) {  // the offline indexes have no keys
        // Back from the sites' results with Escape: the way to them again.
        if (typedEnough(state.q)) list.appendChild(button("Search the sites for “" + state.q.trim() + "”", "primary", () => enterAll()));
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

  // How many songs the search and the progression find, the filters aside: an empty list's Show all brings them.
  const loose = (fits) => order.filter((i) => counted(songs[i]) && (!state.prog || playsProg(songs[i], state.prog)) &&
    fits(i)).length;
  // The filters on, as tags before Filter: the status, each instrument (its glyph), the key, the artist (#artist,
  // body.html's), each a button that lets it go, then Clear. Drawn again only when they change.
  const tags = byId("tags");
  const clearTags = byId("clear-filters");
  const tag = (text, drop, glyphName) => {
    const b = el("button", "tag");
    b.type = "button";
    b.dataset.filter = text;
    if (glyphName) b.appendChild(glyphFor(glyphName));
    b.append(el("span", null, text), cross());
    b.setAttribute("aria-label", "Remove the filter: " + text);
    b.addEventListener("click", () => letGo(b, drop));
    return b;
  };
  const cross = () => {
    const x = el("span", "x");
    x.appendChild(glyphFor("close"));
    return x;
  };
  // A tag pressed: its filter goes, and the focus to the tag that takes its place, else Clear's, else Filter.
  const letGo = (pressed, drop) => {
    const shown = () => Array.from(tags.querySelectorAll(".tag")).filter((t) => !t.hidden);
    const at = shown().indexOf(pressed);
    drop();
    render();
    save();
    const left = shown();
    (left[Math.min(at, left.length - 1)] || filterButton).focus({ preventScroll: true });
  };
  let tagsDrawn = "";
  const drawTags = () => {
    const on = [];
    if (state.show !== "all") on.push([state.show === "review" ? "Needs review" : label(STATUS_TEXT, state.show),
      () => { state.show = "all"; }]);
    for (const x of instsChosen()) on.push([INST_TAG[x], () => { state.inst = instList(instsChosen().filter((y) => y !== x)); }, x]);
    if (keyChosen()) on.push([state.mode && state.tonic ? keyNamed(Number(state.tonic), state.mode)
      : state.mode ? (state.mode === "major" ? "Major" : "Minor") : tonicName(Number(state.tonic), ""),
    () => { state.mode = ""; state.tonic = ""; }]);
    const drawn = JSON.stringify([on.map((t) => t[0]), state.artist]);
    if (drawn === tagsDrawn) return;
    tagsDrawn = drawn;
    for (const old of tags.querySelectorAll(".tag[data-filter]")) old.remove();
    for (const [text, drop, glyphName] of on) artistChip.before(tag(text, drop, glyphName));
    const who = artistName(state.artist);
    artistChip.hidden = !state.artist;
    artistChip.replaceChildren(...(state.artist ? [el("span", null, "by " + who), cross()] : []));
    artistChip.setAttribute("aria-label", state.artist ? "Remove the filter: by " + who : "");
    artistChip.title = state.artist ? "Show every artist, not only " + who : "";
    clearTags.hidden = !filtered();
    tags.hidden = !filtered();
  };
  clearTags.addEventListener("click", () => {
    clearFilters();
    render();
    save();
    filterButton.focus({ preventScroll: true });
  });

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
  // An artist's name pressed, served (a header's, a line's): the search for them, as typing their name runs it (your
  // songs that match, then the sites', their group first, as /api/search leads with an artist it is given whole),
  // sent at once, which asks no site: the indexes alone. The focus goes to the box, from which Enter goes on to the
  // first result and Escape back to your songs; the query before it is a step back in the browser's history (Back).
  searchFor = (name) => {
    const q = String(name || "").trim();
    if (!q) return;
    if (q !== state.q) {
      try {
        history.pushState(null, "", location.href);  // save() makes it this search's
      } catch (err) {
        // A browser that refuses it: the search runs all the same, with no step back.
      }
    }
    input.value = q;
    state.q = q;
    focusFirst = false;
    const sites = searchesAsYouType(q);
    if (state.all && !sites) {
      leaveAll(false);
    } else {
      state.all = sites;
      render();
      save();
      if (sites) askSources(true);
    }
    window.scrollTo(0, 0);
    input.focus({ preventScroll: true });
  };
  // Back (or Forward) to a step of the list's: the list as the address has it, its query, its results, its artist,
  // show, sort, key and progression; an address that changes none of them (the Songbooks tab's, say) moves nothing.
  window.addEventListener("popstate", () => {
    const at = addressed();
    if (Object.keys(at).every((name) => at[name] === state[name])) return;
    const all = at.all;
    Object.assign(state, at, { all: state.all });
    input.value = state.q;
    focusFirst = false;
    if (state.all && !all) {
      leaveAll(false);
    } else {
      state.all = all;
      render();
    }
  });
  artistChip.addEventListener("click", () => letGo(artistChip, () => { state.artist = ""; }));
  setProg = (key) => {
    state.prog = key;
    setQuery("");
    window.scrollTo(0, 0);
  };
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
    focusFirst = false;  // an Enter before: what it waited for is typed over
    if (searcher) searcher.typed();
    // Served, typing searches the sites too, once there is enough to search; the file's Enter shows its line.
    const sites = server ? searchesAsYouType(state.q) : state.all && sitesCan(state.q);
    if (state.all && !sites) {  // nothing the sites can search: your songs again
      leaveAll(false);
      return;
    }
    state.all = sites;
    update();
  });
  clear.addEventListener("click", () => {
    setQuery("");
    input.focus();
  });
  for (const b of statusButtons) {
    b.addEventListener("click", () => {
      state.show = b.dataset.show;
      render();
      save();
    });
  }
  for (const c of instChips) {
    c.addEventListener("click", () => {
      const chosen = instsChosen();
      const name = c.dataset.inst;
      state.inst = instList(chosen.indexOf(name) >= 0 ? chosen.filter((x) => x !== name) : chosen.concat(name));
      render();
      save();
    });
  }
  sort.addEventListener("change", () => {
    state.sort = SORTS.indexOf(sort.value) >= 0 ? sort.value : "artist";
    render();
    save();
  });
  for (const b of modeButtons) {
    b.addEventListener("click", () => {
      state.mode = b.dataset.mode;
      render();
      save();
    });
  }
  for (const b of tonicButtons) {
    b.addEventListener("click", () => {  // the tonic chosen, pressed again, goes
      state.tonic = state.tonic === b.dataset.pc ? "" : b.dataset.pc;
      render();
      save();
    });
  }

  // --- Filter's panel: a popover under it from 720 px, a sheet from the bottom on a phone ------------------------
  // On a computer a dialog of its own (show(), not modal): the list behind it filters as you tap, with no Apply; a
  // click outside it, Escape or Filter again closes it. On a phone a modal one (showModal()), over the page dimmed,
  // which neither takes a tap nor scrolls behind it; Tab keeps to it, and Show N songs closes it. Either way the
  // focus goes to the status chosen, and back to Filter once it closes.
  const wide = window.matchMedia("(min-width: 720px)");
  // The popover under Filter, its right edge with Filter's, kept within the window; its arrow at Filter's middle.
  const placePanel = () => {
    if (!panel.open || panel.matches(":modal")) return;
    const bar = toolbar.getBoundingClientRect();
    const at = filterButton.getBoundingClientRect();
    const width = panel.offsetWidth;
    const room = document.documentElement.clientWidth;
    const left = Math.max(16, Math.min(at.right - width, room - 16 - width));
    panel.style.left = Math.round(left - bar.left) + "px";
    panel.style.top = Math.round(at.bottom - bar.top + 8) + "px";
    panel.style.setProperty("--arrow", Math.round(at.left + at.width / 2 - left) + "px");
  };
  const openPanel = () => {
    if (panel.open) return;
    if (wide.matches) {
      panel.show();
      placePanel();
    } else {
      document.documentElement.classList.add("sheet-open");
      panel.showModal();
    }
    filterButton.setAttribute("aria-expanded", "true");
    const chosen = statusButtons.find((b) => b.tabIndex === 0 && !b.hidden) || statusButtons[0];
    chosen.focus({ preventScroll: true });
  };
  // ``refocus``: the focus back to Filter, unless it went somewhere of its own (a click on another control).
  const closePanel = (refocus = true) => {
    if (!panel.open) return;
    const at = document.activeElement;
    const back = refocus && (!at || at === document.body || panel.contains(at));
    panel.close();
    closed();
    if (back) filterButton.focus({ preventScroll: true });
  };
  const closed = () => {
    filterButton.setAttribute("aria-expanded", "false");
    document.documentElement.classList.remove("sheet-open");
  };
  panel.addEventListener("close", closed);  // its event comes a task later: closePanel says so at once
  filterButton.addEventListener("click", () => (panel.open ? closePanel() : openPanel()));
  showN.addEventListener("click", () => closePanel());
  byId("clear-all").addEventListener("click", () => {
    clearFilters();
    render();
    save();
  });
  panel.addEventListener("cancel", (e) => {  // Escape, on the modal sheet
    e.preventDefault();
    closePanel();
  });
  // Escape closes it wherever the focus is, before the page's own Escape (the search box's) hears it.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !panel.open || composing(e)) return;
    e.preventDefault();
    e.stopPropagation();
    closePanel();
  }, true);
  // A click outside the popover closes it; on the sheet, a tap on the page dimmed behind it.
  document.addEventListener("click", (e) => {
    if (!panel.open) return;
    const path = e.composedPath();  // as the click found it: what it pressed may be drawn again since
    if (panel.matches(":modal")) {
      const box = panel.getBoundingClientRect();
      const outside = e.clientY < box.top || e.clientY > box.bottom || e.clientX < box.left || e.clientX > box.right;
      if (e.target === panel && outside) closePanel();
    } else if (path.indexOf(panel) < 0 && path.indexOf(filterButton) < 0) {
      closePanel();
    }
  });
  // Tab and Shift+Tab go round the sheet's controls.
  panel.addEventListener("keydown", (e) => {
    if (e.key !== "Tab" || !panel.matches(":modal")) return;
    const stops = Array.from(panel.querySelectorAll("button, select")).filter((n) => !n.disabled && n.tabIndex >= 0 &&
      n.checkVisibility());
    if (!stops.length) return;
    const at = stops.indexOf(document.activeElement);
    if (e.shiftKey && at <= 0) {
      e.preventDefault();
      stops[stops.length - 1].focus();
    } else if (!e.shiftKey && at === stops.length - 1) {
      e.preventDefault();
      stops[0].focus();
    }
  });
  // A segmented control's options, one of them chosen: the arrow keys move between them, choosing as they go.
  for (const group of panel.querySelectorAll('[role="radiogroup"]')) {
    group.addEventListener("keydown", (e) => {
      const options = Array.from(group.querySelectorAll('[role="radio"]')).filter((b) => !b.hidden && !b.disabled);
      const at = options.indexOf(document.activeElement);
      const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
      const to = at < 0 ? -1 : step ? (at + step + options.length) % options.length
        : e.key === "Home" ? 0 : e.key === "End" ? options.length - 1 : -1;
      if (to < 0) return;
      e.preventDefault();
      options[to].focus();
      options[to].click();
    });
  }
  window.addEventListener("resize", placePanel);
  const reopen = () => {  // past 720 px either way: the other kind of panel
    if (!panel.open) return;
    const inside = panel.contains(document.activeElement);
    panel.close();
    openPanel();
    if (!inside) filterButton.focus({ preventScroll: true });
  };
  if (wide.addEventListener) wide.addEventListener("change", reopen);

  // --- the bar: your songs and every index as you type ------------------------------------------
  // Typing filters your songs, here, asking nothing. Served, it searches the sites too (searchesAsYouType), a moment
  // after the last key: one list under the bar, in the list's place, its tools with it, until Escape: your songs that
  // match, then what caracole's offline indexes hold of Ultimate Guitar, LaCuerda, gtptabs.com and MuseScore
  // (/api/search), under the same artist headers (mergeSites), the newest query's answer alone, the older one staying
  // until it comes. Enter moves the focus to the first result: it never asks for a song, only a result's Get it
  // does. LaCuerda's own search, which finds the songs of artists whose page caracole hasn't read, is one request:
  // sent by itself once the query has settled, when /api/search says so (``lacuerda_search``), at once by Enter
  // when its gate sends one, or offered as a button, a line under the results (rows.js lacuerdaSearcher, lcBox), or by
  // Ask LaCuerda's, the one LaCuerda button, where the results offer a name's page too; its rows come in a new answer
  // once it is over. On the file, which can ask nothing, Enter shows the line that searches the sites.
  const say = (text) => {
    if (barStatus.textContent === text) return;
    barStatus.textContent = text;
    barStatus.title = text;  // one line on a phone: the whole of it on hovering
  };
  const drawBar = (none, key) => {
    const q = normal(state.q);
    if (server && state.all) return;  // the search of the sites says how it goes
    if (!q) say(server ? "Type to search your songs and the sites" : "Filter your songs as you type");
    else if (key) say(none ? "None of yours match: the sites know no keys" : "A key filters your songs alone: the sites know no keys");
    else if (server && !typedEnough(q)) say(none ? "None of yours match: three letters search the sites too"
      : "Three letters or more search the sites too");
    else if (server) say(none ? "None of yours match: Enter searches the sites" : "Your songs alone: Enter searches the sites too");
    else if (none) say("None of yours match: see the line below");
    else if (state.all) say("The sites need caracole serve: run the line below");
    else say("Enter: the line that searches the sites");
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
    const code = el("code", null, "caracole search " + shellNames(q));
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

  const MINE_SHOWN = 5;  // your songs in the results; the list has them all
  const SEARCH_PAUSE = 150;  // ms after the last key before the sites are searched
  // The bar's id, sent with each search: a search typed on stops the older ones of this bar alone, never another
  // page's (another person searching at once is answered too: web/search_routes.py).
  const SEARCH_BOX = Math.random().toString(36).slice(2, 12) || "bar";
  const allMine = el("p", "all-mine");
  const meantBox = el("div", "meant");  // Did you mean, first
  const groupsBox = el("div", "groups");
  const lcBox = el("div", "lacuerda-search-box");  // LaCuerda's own search, under the results
  const notesBox = el("div", "notes");
  let asking = null;  // the search of the sites on its way, to abort
  let asked = 0;  // the newest search sent: an older one's answer is dropped
  let askTimer = 0;
  let askedFor = null;  // the query the newest search was sent for
  let answer = null;  // the answer on the screen: { data, q, model } (mergeSites)
  let focusFirst = false;  // Enter before the query's answer: the focus goes to its first result once it is drawn
  // Until the first answer since the results opened, what goes under them (the request form, the footer) waits too:
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
  let addAgain = () => {};
  const objects = (value) => listOf(value).filter((x) => x && typeof x === "object");
  // The artist part of a song's identity key: the header its line shares with the sites' rows of its artist.
  const artistKeyOf = (s) => String((s && s.identity) || "").split("/")[0] || "~" + String((s && s.sortArtist) || "");
  const titleKeyOf = (s) => String((s && s.identity) || "").split("/").slice(1).join("/");

  // The answer's artists and songs, put together by artist and by song, in the order the answer ranks them: the
  // removed songs it matches first (songs you had), then LaCuerda's artists and songs when it alone has the artist the
  // query names (``lacuerda_leads``), the artists the query names when one leads, Ultimate Guitar's songs, its
  // artists otherwise, LaCuerda's, gtptabs.com's songs, harptabs.com's artists and songs (by an artist whose page
  // caracole read); MuseScore's pages and harptabs.com's tabs whose artist no page names, titles alone, apart. An artist's group is
  // keyed by the artist part of its rows' identity keys (``artist_key``; an artist's ``group_key``), a row of a song of
  // yours by your song's artist (``song``, ``same_artist``) putting its artist's rows under your artist (UG's "Song
  // Dongye (宋冬野)" is your 宋冬野); within it, a song (``title_key``) is one item, which each site's row of it is on.
  const mergeSites = (data) => {
    const model = { groups: new Map(), order: [], items: new Map(), lines: new Map(), alias: new Map(),
      titles: objects(data.musescore), harps: objects(data.harptabs).filter((h) => !h.artist),
      unlisted: data.lacuerda_unlisted && typeof data.lacuerda_unlisted === "object"
        ? data.lacuerda_unlisted : null, meant: undefined, card: undefined, line: undefined };
    const ugArtists = objects(data.artists);
    const lcArtists = objects(data.lacuerda_artists);
    const htArtists = objects(data.harptabs_artists);
    const htSongs = objects(data.harptabs).filter((h) => h.artist);
    for (const row of [...objects(data.index), ...objects(data.gtptabs), ...objects(data.lacuerda), ...htSongs,
      ...ugArtists.flatMap((a) => objects(a.top)), ...lcArtists.flatMap((a) => objects(a.top)),
      ...htArtists.flatMap((a) => objects(a.top))]) {
      const i = yourSong(row);
      if (i !== undefined && row.same_artist === true && row.artist_key && !model.alias.has(String(row.artist_key))) {
        model.alias.set(String(row.artist_key), artistKeyOf(songs[i]));
      }
    }
    const leads = data.lacuerda_leads === true;
    const lacuerda = [...lcArtists.map((a) => ["artist", "lacuerda", a]),
      ...objects(data.lacuerda).map((h) => ["song", "lacuerda", h])];
    const named = ugArtists.map((a) => ["artist", "ug", a]);
    for (const [kind, source, row] of [
      ...objects(data.removed).map((r) => ["song", "removed", r]),
      ...(leads ? lacuerda : []),
      ...(data.lead === "artist" ? named : []),
      ...objects(data.index).map((h) => ["song", "ug", h]),
      ...(data.lead === "artist" ? [] : named),
      ...(leads ? [] : lacuerda),
      ...objects(data.gtptabs).map((h) => ["song", "gtptabs", h]),
      ...htArtists.map((a) => ["artist", "harptabs", a]),
      ...htSongs.map((h) => ["song", "harptabs", h]),
    ]) {
      if (kind === "artist") addArtist(model, source, row);
      else addSong(model, source, row);
    }
    return model;
  };
  const yourSong = (row) => (row.song === null || row.song === undefined ? undefined : byIndex.get(Number(row.song)));
  const groupOf = (model, key, name) => {
    let g = model.groups.get(key);
    if (!g) {
      g = { key, name: String(name || ""), ug: null, lacuerda: null, harptabs: null, items: [], ugListed: 0, ugOffset: 0,
        lcListed: false, htListed: false, tail: null };
      model.groups.set(key, g);
      model.order.push(key);
    }
    return g;
  };
  // An artist the query names (``source``'s): their group's header counts their songs there, and their most tabbed (or
  // most popular) songs are its first lines.
  const addArtist = (model, source, a) => {
    const g = groupOf(model, model.alias.get(String(a.group_key)) || String(a.group_key || ""), a.artist);
    if (!g[source]) g[source] = a;
    for (const t of objects(a.top)) addSong(model, source, t, g);
    if (source === "ug") g.ugListed = Math.max(g.ugListed, objects(a.top).length);
  };
  // A site's row of a song, on the song's item in its artist's group (``into``, for an artist's songs), made the first
  // time; an item drawn already is drawn again with it, unless its line shows a request.
  const addSong = (model, source, row, into) => {
    const i = yourSong(row);
    const g = i !== undefined ? groupOf(model, artistKeyOf(songs[i]), songs[i].artist)
      : into || groupOf(model, model.alias.get(String(row.artist_key)) || String(row.artist_key || ""), row.artist);
    const key = g.key + "/" + (i !== undefined ? titleKeyOf(songs[i]) : String(row.title_key || ""));
    let item = model.items.get(key);
    if (!item) {
      item = { key, mine: undefined, ug: null, lacuerda: null, gtptabs: null, harptabs: null, removed: null };
      model.items.set(key, item);
      g.items.push(item);
    }
    if (i !== undefined) item.mine = i;
    if (i !== undefined && source === "lacuerda") offerLaCuerda(i, row);
    if (!item[source]) {
      item[source] = row;
      const drawn = model.lines.get(key);
      if (drawn && !drawn.querySelector(".progress")) model.lines.delete(key);
    }
    return item;
  };
  // A LaCuerda row of a song of yours, with chords: its line offers that sheet (Use LaCuerda's sheet), drawn again
  // now if it is drawn already and had none. Its chevron open, it stays open, and the focus on its button stays there.
  const offerLaCuerda = (i, row) => {
    const id = Number(songs[i].id);
    const https = (url) => /^https:[/][/]/i.test(String(url || ""));
    if (lacuerdaFound.has(id) || !https(row.sheet) || !https(row.url)) return;
    const before = lacuerdaOf(songs[i]);
    lacuerdaFound.set(id, String(row.url));
    if (!lines.has(i) || lacuerdaOf(songs[i]) === before) return;
    const old = lines.get(i);
    const more = old.querySelector(":scope > .line-more");
    const focused = Boolean(more && more === document.activeElement);
    const drawn = refill(old, lineFor(songs[i]));
    lines.set(i, drawn);
    const fresh = drawn.querySelector(":scope > .line-more");
    if (focused && fresh && fresh.isConnected) fresh.focus();
  };
  const lineOfItem = (model, item) => {
    if (!model.lines.has(item.key)) model.lines.set(item.key, indexLine(item, { get: getIt, later, again: addAgain }));
    return model.lines.get(item.key);
  };

  // An artist's group's foot, made once: "+ 57 more by Estopa" (the rest of their songs on Ultimate Guitar, fifty at a
  // time, from /api/artist), "+ 3 more by Estopa on LaCuerda" (the rest the index holds of theirs), the same on
  // harptabs.com, or, for an artist whose page caracole has never read there, the offer to read it. None when there is
  // nothing more: null.
  const tailOf = (m) => {
    if (!m.tail) {
      m.tail = { box: el("div", "group-tail"), ug: null, lc: null, offer: null, ht: null, htOffer: null };
      if (m.ug) {
        m.tail.ug = button("", "small more-by", () => moreOf(m, "ug"));
        m.tail.box.appendChild(m.tail.ug);
      }
      if (m.lacuerda && Number(m.lacuerda.known) > 0) {
        m.tail.lc = button("", "small more-by", () => moreOf(m, "lacuerda"));
        m.tail.box.appendChild(m.tail.lc);
      } else if (m.lacuerda) {
        m.tail.offer = readOffer(m);
        m.tail.box.appendChild(m.tail.offer);
      }
      if (m.harptabs && Number(m.harptabs.known) > 0) {
        m.tail.ht = button("", "small more-by", () => moreOf(m, "harptabs"));
        m.tail.box.appendChild(m.tail.ht);
      } else if (m.harptabs) {
        m.tail.htOffer = harpOffer(m);
        m.tail.box.appendChild(m.tail.htOffer);
      }
    }
    const listed = (source) => m.items.filter((item) => item[source]).length;
    const more = (go, left, text, aria) => {
      if (!go) return;
      if (left <= 0) {
        go.remove();
        return;
      }
      go.textContent = "+ " + left.toLocaleString("en") + " more by " + text;
      go.setAttribute("aria-label", aria(left));
    };
    more(m.tail.ug, Number(m.ug && m.ug.songs) - m.ugListed, m.name, (n) => "List " + n + " more songs by " + m.name +
      " on Ultimate Guitar");
    more(m.tail.lc, m.lcListed ? 0 : Number(m.lacuerda && m.lacuerda.known) - listed("lacuerda"), m.name + " on LaCuerda",
      (n) => "List " + n + " more songs by " + m.name + " on LaCuerda");
    more(m.tail.ht, m.htListed ? 0 : Number(m.harptabs && m.harptabs.held) - listed("harptabs"),
      m.name + " on harptabs.com", (n) => "List " + n + " more songs by " + m.name + " on harptabs.com");
    return m.tail.box.childNodes.length ? m.tail.box : null;
  };
  // "+ N more": the artist's next songs, in their group, each a line as the others are; the focus stays on the button,
  // or, once it is gone, goes to the first song it listed.
  const moreOf = (m, source) => {
    const was = answer;
    const go = source === "ug" ? m.tail.ug : source === "harptabs" ? m.tail.ht : m.tail.lc;
    const before = new Set(m.items);
    go.disabled = true;
    say("Listing " + m.name + "'s songs…");
    const listing = source === "ug" ? artistPage(String(m.ug.artist_key || ""), m.ugOffset)
      : source === "harptabs" ? sitePage({ harptabs: String(m.harptabs.path || "") })
      : sitePage({ slug: String(m.lacuerda.slug || "") });
    listing.then((page) => {
      go.disabled = false;
      if (!page || answer !== was || !state.all) return;
      const got = objects(page.songs);
      if (source === "ug") {
        for (const h of got) addSong(was.model, "ug", h, m);
        m.ugOffset += got.length;
        m.ugListed = got.length ? Math.max(m.ugListed, m.ugOffset) : Number(m.ug.songs);
        say(m.name + ": " + many(page.total, "song") + " on Ultimate Guitar");
      } else if (source === "harptabs") {
        listHarptabs(m, page);
      } else {
        listLaCuerda(m, page);
      }
      drawGroups();
      const first = m.items.find((item) => !before.has(item));
      const line = first ? (first.mine !== undefined ? lines.get(first.mine) : was.model.lines.get(first.key)) : null;
      if (go.isConnected) go.focus();
      else if (line && line.isConnected) line.focus();
    });
  };
  // A LaCuerda artist's songs the index holds (/api/artist?lacuerda=), all of them, in their group.
  const listLaCuerda = (m, page) => {
    for (const h of objects(page.songs)) addSong(answer.model, "lacuerda", h, m);
    m.lcListed = true;
    if (m.tail && m.tail.offer) {
      m.tail.offer.remove();
      m.tail.offer = null;
    }
    say(String(page.artist) + ": " + many(page.total, "song") + " on LaCuerda");
  };
  // A harptabs.com artist's songs the index holds (/api/artist?harptabs=), all of them, in their group.
  const listHarptabs = (m, page) => {
    for (const h of objects(page.songs)) addSong(answer.model, "harptabs", h, m);
    m.htListed = true;
    if (m.tail && m.tail.htOffer) {
      m.tail.htOffer.remove();
      m.tail.htOffer = null;
    }
    say(String(page.artist) + ": " + many(objects(page.songs).length, "song") + " on harptabs.com");
  };
  // A harptabs.com artist whose page caracole has never read: the button that reads it (a request, a job of its own),
  // then lists their songs in their group.
  const harpOffer = (m) => {
    const name = String(m.harptabs.artist || m.name);
    const box = el("div", "read-page");
    box.appendChild(el("p", null, "caracole hasn't read the page of " + name + " on harptabs.com yet. Reading it is one " +
      "request to harptabs.com, at a lookup's pace."));
    box.appendChild(button("Read their page", "small primary", (e) => readThenShow(
      { harptabs: String(m.harptabs.path || "") }, e.currentTarget, box, (page) => {
        listHarptabs(m, page);
        drawGroups();
      }), "Read the page of " + name + " on harptabs.com"));
    return box;
  };
  // An artist whose page caracole has never read: how many songs LaCuerda lists, and the button that reads it (a
  // request, a job of its own), then lists them in their group.
  const readOffer = (m) => {
    const name = String(m.lacuerda.artist || m.name);
    const box = el("div", "read-page");
    box.appendChild(el("p", null, "caracole hasn't read the page of " + name + " on LaCuerda yet, which lists " +
      many(m.lacuerda.songs, "song") + ". Reading it is one request to LaCuerda, at a lookup's pace."));
    box.appendChild(button("Read their page", "small primary", (e) => readThenShow({ slug: String(m.lacuerda.slug || "") },
      e.currentTarget, box, (page) => {
        listLaCuerda(m, page);
        drawGroups();
      }), "Read the page of " + name + " on LaCuerda"));
    return box;
  };
  // A name LaCuerda's index has no artist by, read by that name (Ask LaCuerda, under the groups or on the card of a
  // search that found nothing): their group, first; Ask LaCuerda gone.
  const readByName = (model) => (page) => {
    const g = groupOf(model, String(page.group_key || ""), page.artist);
    g.lacuerda = { artist: page.artist, slug: page.slug, songs: page.listed, known: page.total, gtptabs: page.gtptabs };
    model.order.splice(model.order.indexOf(g.key), 1);
    model.order.unshift(g.key);
    listLaCuerda(g, page);
    model.unlisted = null;
    model.card = model.line = undefined;
    drawGroups();
  };
  // An artist the answer suggests ("Did you mean Lynyrd Skynyrd?"), opened: their songs (/api/artist, fifty, or those
  // LaCuerda's index holds, or the offer to read their page), in their group, first, as an artist the query names
  // is; the focus to it. It reads the indexes alone: no site is asked anything.
  const openSuggested = (model, s, go) => {
    const was = answer;
    const ug = s.source !== "lacuerda";
    go.disabled = true;
    say("Listing " + String(s.artist || "") + "'s songs…");
    (ug ? artistPage(String(s.artist_key || ""), 0) : sitePage({ slug: String(s.slug || "") })).then((page) => {
      go.disabled = false;
      if (!page || answer !== was || !state.all) return;
      const g = groupOf(model, model.alias.get(String(s.group_key)) || String(s.group_key || ""), page.artist);
      g.tail = null;  // made again, with what this group has now
      if (ug) {
        const got = objects(page.songs);
        g.ug = { artist_key: page.artist_key, artist: page.artist, songs: page.total, tabs: page.tabs,
          group_key: s.group_key, top: [] };
        for (const h of got) addSong(model, "ug", h, g);
        g.ugOffset = got.length;
        g.ugListed = got.length;
        say(String(page.artist) + ": " + many(page.total, "song") + " on Ultimate Guitar");
      } else {
        g.lacuerda = { artist: page.artist, slug: page.slug, songs: page.listed, known: page.total, gtptabs: page.gtptabs };
        if (page.read) listLaCuerda(g, page);
      }
      model.order.splice(model.order.indexOf(g.key), 1);
      model.order.unshift(g.key);
      drawGroups();
      const section = Array.from(groupsBox.querySelectorAll("section.artist")).find((x) => x.dataset.artist === g.key);
      if (section) section.focus();
    });
  };

  // Of your songs, those the filters show (the Filter panel's and the artist's), in the list as in the results (the
  // sites' songs are what the sites have, whatever they show); and that in words, for the results' head, which hides
  // the toolbar: "Your songs here: wanted · by Soda Stereo · with a harmonica tab · in A minor", or nothing when they
  // show every song.
  const kept = (i) => (!state.artist || String(songs[i].sortArtist || "") === state.artist) &&
    keyFits(i) && (!state.prog || playsProg(songs[i], state.prog)) && instFits(i) && SHOWS[state.show](songs[i]);
  const SHOW_WORD = { found: "found", wanted: "wanted", review: "needing review" };
  const keptSaid = () => {
    const parts = [label(SHOW_WORD, state.show), state.artist ? "by " + artistName(state.artist) : "",
      state.inst ? "with " + instsChosen().map((x) => INST_SAID[x]).join(" or ") : "",
      keyChosen() ? "in " + keySaid() : "",
      state.prog ? "with " + progNumerals(state.prog) : ""].filter(Boolean);
    return parts.length ? "Your songs here: " + parts.join(" · ") : "";
  };
  // Show all of yours: every status, instrument, key, artist and progression, here and in the list; the focus to the
  // box, as the button goes with its note.
  const keptNote = el("p", "filtered");
  keptNote.append(el("span"), button("Show all of yours", "small", () => {
    clearFilters();
    state.prog = "";
    render();
    save();
    input.focus();
  }, "Show all of yours: every status, instrument, key, artist and progression"));
  keptNote.hidden = true;
  // A progression typed or named (/api/search's ``progression``: "vi IV I V", "andalusian"): how many of your songs
  // play it, and Show them, the list of those songs alone (#prog=). The first few are among the results already.
  const progNote = el("p", "filtered prog-found");
  progNote.hidden = true;
  const drawProgFound = () => {
    const p = answer && answer.q === normal(state.q) && answer.data.progression &&
      typeof answer.data.progression === "object" ? answer.data.progression : null;
    const key = p && typeof p.key === "string" ? p.key : "";
    const said = key ? String(p.label || progLabel(key)) + (p.name && p.name !== p.label ? ", " + String(p.name) : "") : "";
    progNote.hidden = !key;
    if (progNote.dataset.said === said + "|" + String(p && p.songs)) return;
    progNote.dataset.said = said + "|" + String(p && p.songs);
    progNote.replaceChildren();
    if (!key) return;
    const n = Number(p.songs) || 0;
    if (!n) {
      progNote.append("None of your songs play " + said + " yet");
      return;
    }
    progNote.append(el("span", null, "Your songs with " + said + ": " + n),
      button("Show them", "small", () => setProg(key), "Show your " + plural(n, "song") + " with " + said));
  };

  // What the results show now: your songs that match what is typed and that the buttons show (not one removed since
  // the page loaded: the answer has it as removed, with Add again), then the server's close matches the filter missed
  // (MINE_SHOWN in all, then All N of your songs), and the answer's groups, under one header
  // an artist: yours first, A to Z, then the answer's, in its order. A song of yours is its own line, with all it
  // offers, wherever the answer has it, unless the buttons hide it; a song of the sites, an index line (indexLine),
  // the same node from one draw to the next while the answer stands, so that what it shows stays. The focus stays
  // where it was as they are drawn again, a newer answer's too (LaCuerda's search's end brings one): on the same
  // node; else, from a line (Enter's, or Tab's), on the line of the same song, else on the first line.
  const drawGroups = () => {
    const had = groupsBox.contains(document.activeElement) ? document.activeElement : null;
    const hadLine = had ? had.closest("article") : null;
    const hadHit = hadLine ? String(hadLine.dataset.hit || "") : "";
    const model = answer && answer.model;
    const q = normal(state.q);
    const fits = typedMatch(parseQuery(state.q));
    const local = ORDERS.artist.filter((i) => counted(songs[i]) && fits(i) && kept(i));
    const close = answer && answer.q === q ? listOf(answer.data.library).map((h) => byIndex.get(Number(h && h.id)))
      .filter((i) => i !== undefined && kept(i) && local.indexOf(i) < 0) : [];
    const mine = local.concat(close);
    const shown = mine.slice(0, MINE_SHOWN);
    const groups = new Map();
    const at = (key) => {
      if (!groups.has(key)) groups.set(key, { mine: [], model: null });
      return groups.get(key);
    };
    for (const i of shown) at(artistKeyOf(songs[i])).mine.push(i);
    if (model) for (const key of model.order) at(key).model = model.groups.get(key);
    const yours = new Map();  // how many songs of each artist you have, the songs the search leaves out too
    const named = new Map();  // a song of each artist you have, which names them and filters by them
    for (const s of songs.concat(Array.from(arrived.values())).filter(counted)) {
      yours.set(artistKeyOf(s), (yours.get(artistKeyOf(s)) || 0) + 1);
      if (!named.has(artistKeyOf(s))) named.set(artistKeyOf(s), s);
    }
    const drawn = new Set(shown);
    const keys = new Set(shown.map((i) => String(songs[i].identity || "")));
    const box = document.createDocumentFragment();
    for (const [key, g] of groups) {
      const items = [];
      const theirs = g.mine.slice();
      for (const item of g.model ? g.model.items : []) {
        if (item.mine !== undefined) {
          if (!drawn.has(item.mine) && kept(item.mine)) {
            drawn.add(item.mine);
            theirs.push(item.mine);
          }
        } else if (!keys.has(item.key)) {
          items.push(lineOfItem(model, item));
        }
      }
      const tail = g.model ? tailOf(g.model) : null;
      if (!theirs.length && !items.length && !tail) continue;
      const you = theirs.length ? songs[theirs[0]] : named.get(key) || null;
      const ug = (g.model && g.model.ug) || {};  // the artists the query names there, if any
      const lc = (g.model && g.model.lacuerda) || {};
      const ht = (g.model && g.model.harptabs) || {};
      const section = artistGroup({ key, name: you ? you.artist : g.model.name, filter: you ? you.sortArtist : "" },
        [...theirs.map(lineOf), ...items], { mine: yours.get(key) || 0, ug: ug.songs, lacuerda: lc.songs,
          gtptabs: Math.max(Number(ug.gtptabs) || 0, Number(lc.gtptabs) || 0), harptabs: ht.songs });
      if (tail) section.appendChild(tail);
      box.appendChild(section);
    }
    if (model && model.titles.length) {  // MuseScore's pages: a title alone, no artist to put them under
      if (!model.titleLines) model.titleLines = model.titles.map(titleLine);
      box.appendChild(artistGroup({ name: "MuseScore", search: false }, model.titleLines,
        { note: many(model.titles.length, "page") + " by that title" }));
    }
    if (model && model.harps.length) {  // harptabs.com's harmonica tabs: a title alone too
      if (!model.harpLines) model.harpLines = model.harps.map(titleLine);
      box.appendChild(artistGroup({ name: "harptabs.com", search: false }, model.harpLines,
        { note: many(model.harps.length, "harmonica tab") + " by that title" }));
    }
    groupsBox.replaceChildren(box);
    groupsBox.hidden = !groupsBox.childNodes.length;  // no empty box: nothing matches yet
    if (had && !groupsBox.contains(document.activeElement)) {
      const lines = Array.from(groupsBox.querySelectorAll("article"));
      const back = groupsBox.contains(had) ? had
        : hadLine ? (hadHit && lines.find((a) => String(a.dataset.hit || "") === hadHit)) || lines[0] : null;
      if (back) back.focus({ preventScroll: true });
    }
    allMine.replaceChildren();
    if (mine.length > MINE_SHOWN) {
      allMine.appendChild(button("All " + mine.length + " of your songs", "small", () => leaveAll(true)));
    }
    allMine.hidden = !allMine.childNodes.length;
    const said = keptSaid();
    if (keptNote.firstChild.textContent !== said) keptNote.firstChild.textContent = said;
    keptNote.hidden = !said;
    drawProgFound();
    if (model && model.meant === undefined) model.meant = didYouMean(answer.data.suggest, (s, go) => openSuggested(model, s, go));
    meantBox.replaceChildren(...(model && model.meant ? [model.meant] : []));
    notesBox.replaceChildren(...(model ? notesOf(model, !groupsBox.childNodes.length) : []));
  };
  // Under the groups, what the search says beside them (rows.js): for a query that found nothing (``nothing``), one card,
  // its request by name first, then Ask LaCuerda for a name under a letter its listings don't reach yet, where caracole
  // looked, and why it may not see an artist; under results, where it looked in one muted line, when a site wasn't
  // searched whole. Each made once an answer, Ask LaCuerda's state kept from one draw to the next. Ask LaCuerda is the
  // one LaCuerda button: it sends LaCuerda's search while its gate lets one go by hand (the searcher's ``ask``), else
  // reads the name's page.
  const notesOf = (model, nothing) => {
    const data = Object.assign({}, answer.data, { lacuerda_unlisted: model.unlisted });
    const q = answer.q;
    const does = {
      request: requestByName,
      ask: (go, box) => {
        if (searcher && searcher.ask(q, go)) return;
        readThenShow({ name: String(model.unlisted.name || "") }, go, box, readByName(model));
      },
    };
    if (nothing) {
      if (!model.card) model.card = nothingFound(data, answer.q, does);
      return [model.card];
    }
    if (model.line === undefined) model.line = lookedLine(data, answer.q, does);
    return model.line ? [model.line] : [];
  };
  // "Request “…” by name": the request form, filled in from the query (prefill), open and in view, the focus on its
  // first field still empty.
  const requestByName = () => {
    const box = byId("request-box");
    if (!box) return;
    box.open = true;
    box.scrollIntoView({ block: "center", behavior: smooth() });
    const form = box.querySelector("form");
    const field = form && (["artist", "title"].map((n) => form.elements.namedItem(n)).find((f) => f && !f.value) ||
      form.elements.namedItem("artist"));
    if (field) field.focus({ preventScroll: true });
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
    drawGroups();
    askSources(false);
  };

  // LaCuerda's own search (rows.js): ``current()`` the query the box holds, ``done`` asks the sites again once it is
  // over, for the rows it put into LaCuerda's index.
  const searcher = server ? lacuerdaSearcher(server.csrf, () => normal(state.q), (q) => {
    if (state.all && normal(state.q) === q) askSources(true);
  }, (line) => lcBox.replaceChildren(line)) : null;
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
    fetch("api/search?q=" + encodeURIComponent(q) + "&box=" + SEARCH_BOX, {
      signal: asking.signal, cache: "no-store", headers: { Accept: "application/json" },
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
  // What a result's line stands for, the same in an older answer and a newer one: its song's identity.
  const hitKey = (row) => String(row.dataset.hit || "");
  // The answer of the newest search, in one go: the old one stays until then, so nothing flashes. A line whose
  // request is on its way stays, its request line in it, where the newer answer has its song; one the newer answer
  // lacks becomes its line under the bar (settleSpots), its request line going on there.
  const showSites = (data, q) => {
    const going = new Map();
    for (const [id, node] of spots) {
      if (found.contains(node) && node.classList.contains("hit") && views.has(id) && isActive(views.get(id))) {
        going.set(hitKey(node), node);
      }
    }
    answer = { data, q, model: data.short ? null : mergeSites(data) };
    found.dataset.query = q;
    for (const [key, node] of answer.model ? going : []) {
      if (!answer.model.items.has(key)) continue;
      answer.model.lines.set(key, node);
      going.delete(key);
    }
    drawGroups();
    if (going.size) settleSpots(true);
    // Sent, if Enter came first; with no button of its own beside Ask LaCuerda's, which sends it then.
    const lcLine = searcher && !data.short ? searcher.show(data.lacuerda_search, q, Boolean(answer.model.unlisted)) : null;
    lcBox.replaceChildren(...(lcLine ? [lcLine] : []));
    if (data.short) {
      say("Type three letters or more to search the sites");
      return;
    }
    const index = objects(data.index);
    const artists = objects(data.artists);
    const gtp = objects(data.gtptabs);
    const ms = objects(data.musescore);
    const harps = objects(data.harptabs);
    const htArtists = objects(data.harptabs_artists);
    const lcArtists = objects(data.lacuerda_artists);
    const lc = objects(data.lacuerda);
    const parts = [];
    if (index.length || artists.length) parts.push((index.length + artists.length) + " on Ultimate Guitar");
    if (lc.length || lcArtists.length) {
      parts[data.lacuerda_leads === true ? "unshift" : "push"]((lc.length + lcArtists.length) + " on LaCuerda");
    }
    if (gtp.length) parts.push(gtp.length + " on gtptabs.com");
    if (ms.length) parts.push(ms.length + " on MuseScore");
    if (harps.length || htArtists.length) parts.push((harps.length + htArtists.length) + " on harptabs.com");
    const meant = objects(data.suggest).filter((x) => x.artist);
    say(parts.length ? parts.join(" · ") : meant.length ? "Nothing on the sites: did you mean " + String(meant[0].artist) + "?"
      : "Nothing on the sites: request it by name below");
    prefill(data.lead || (lcArtists.length && !lc.length ? "artist" : null));  // an artist LaCuerda alone knows
    if (focusFirst && q === normal(state.q)) {
      focusFirst = false;
      toFirstResult();
    }
  };
  // Enter: on to the first result's line, from which Tab goes on to its name (which gets it, as its button does),
  // then its button. Enter itself never asks for a song (LaCuerda's search, the keydown's, asks for none).
  const toFirstResult = () => {
    const first = groupsBox.querySelector("article");
    if (first) first.focus();
  };

  // An artist's songs on Ultimate Guitar, fifty from ``offset`` (/api/artist), for their group's "+ N more".
  const artistPage = (key, offset) => fetch("api/artist?key=" + encodeURIComponent(key) + "&offset=" + offset,
    { headers: { Accept: "application/json" } })
    .then((r) => r.json().catch(() => null).then((body) => ({ ok: r.ok, status: r.status, body })))
    .then((reply) => {
      if (!reply.ok || !reply.body || reply.body.error) {
        say(failure(reply).line.text);
        return null;
      }
      return reply.body;
    }, () => {
      say(UNREACHABLE.line.text);
      return null;
    });
  // A LaCuerda artist's songs the index holds (/api/artist?lacuerda=): ``who`` names them by the slug of their page
  // ({ slug }) or by a name ({ name }: a page read by name); a harptabs.com artist's (?harptabs=), by their page's path
  // ({ harptabs }); ``quiet``, a 404 isn't said.
  const sitePage = (who) => fetch("api/artist?" + (who.harptabs ? "harptabs=" + encodeURIComponent(String(who.harptabs))
    : who.slug ? "lacuerda=" + encodeURIComponent(String(who.slug))
    : "lacuerda_name=" + encodeURIComponent(String(who.name || ""))),
    { headers: { Accept: "application/json" } })
    .then((r) => r.json().catch(() => null).then((body) => ({ ok: r.ok, status: r.status, body })))
    .then((reply) => {
      if (!reply.ok || !reply.body || reply.body.error) {
        if (!(who.quiet && reply.status === 404)) say(failure(reply).line.text);
        return null;
      }
      return reply.body;
    }, () => {
      say(UNREACHABLE.line.text);
      return null;
    });
  // Read a LaCuerda page (``who``: { slug } or { name }), or a harptabs.com one ({ harptabs }), from the button ``go`` in
  // ``offer``, then ``done(page)`` with the artist's songs; a read that leaves none to list says what the site
  // answered, under the offer.
  const readThenShow = (who, go, offer, done) => {
    const was = answer;
    go.disabled = true;
    readArtistPage(server.csrf, who, say).then((read) => {
      if (answer !== was || !state.all) return;
      if (read.error) {
        go.disabled = false;
        say(read.error);
        return;
      }
      sitePage(Object.assign({ quiet: true }, who)).then((page) => {
        if (answer !== was || !state.all) return;
        if (page && page.read) {
          done(page);
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

  // Into the sites' results: as you type, served (the input's listener), the address (#all=1), or Enter once you left
  // them; on the file, Enter shows the line that searches them.
  const enterAll = () => {
    if (!sitesCan(state.q) || (server && !typedEnough(state.q))) {  // the line under the box says why not
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
    focusFirst = false;
    if (searcher) searcher.leave();  // an Enter waiting for the answer: LaCuerda's search with it too
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
    head.appendChild(keptNote);
    allMine.hidden = true;
    found.append(head, progNote, allMine, meantBox, groupsBox, lcBox, notesBox);
  }
  // A key that ends an input method's word (pinyin, kana) is still typing, never a command.
  const composing = (e) => e.isComposing || e.keyCode === 229;
  input.addEventListener("keydown", (e) => {
    if (composing(e)) return;
    if (e.key === "Enter") {
      e.preventDefault();
      const q = normal(state.q);
      if (!server || !state.all) {
        enterAll();
        if (searcher && state.all) searcher.enter(q, false);  // LaCuerda's search too, with the sites' answer
      } else if (answer && answer.q === q) {  // the query's answer is in: its first result
        const line = searcher && searcher.enter(q, true);  // and LaCuerda's search now, when its gate sends one
        if (line) lcBox.replaceChildren(line);
        toFirstResult();
      } else {  // on its way: its first result once it is drawn, the search sent now, LaCuerda's with its answer
        focusFirst = true;
        if (searcher) searcher.enter(q, false);
        askSources(true);
      }
    } else if (e.key === "ArrowDown" && state.all && server) {  // on to the first result's button
      const first = found.querySelector(".line-action button, .line-action a");
      if (first) {
        e.preventDefault();
        first.focus();
      }
    }
  });
  // A field you type in keeps its keys: a "/" there is the text's ("AC/DC" as a request's artist, "Either/Or").
  const UNTYPED = /^(checkbox|radio|button|submit|reset|range|color|file|image|hidden)$/;
  const typedIn = (el) => el instanceof HTMLElement && (el.isContentEditable || el.tagName === "TEXTAREA"
    || el.tagName === "SELECT" || (el.tagName === "INPUT" && !UNTYPED.test(el.type)));
  document.addEventListener("keydown", (e) => {
    if (composing(e)) return;
    const typing = document.activeElement === input;
    if (e.key === "/" && !typing && !typedIn(e.target) && !e.ctrlKey && !e.metaKey && !e.altKey
        && !input.closest("[hidden]")) {
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
  const quiet = new Set();  // the lookups the Songbooks tab asked for: its set list says how they go
  let trayClosed = false;
  // The list of requests, once there are two or more: one line each, not read out (the songs' lines are), with no
  // steps (the songs' lines have them); a song's name opens its sheet once it is Ready. A songbook's change, or a
  // removal, is left out: its songbook or line, where it was asked for, says how it goes.
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
    // Ready: the song's name opens its sheet (the view's ``sheet``), as its line's title does.
    const name = item.querySelector(".tray-song");
    if (typeof view.sheet === "string" && view.sheet && name.tagName !== "A") {
      const opens = link({ label: view.display || "", href: view.sheet }, "tray-song", false);
      opens.title = "Open its sheet";
      name.replaceWith(opens);
    }
    // One Details link, the list's own: a line here says how its request goes, and its song's links the rest.
    const line = view.line && typeof view.line === "object" ? view.line : {};
    showLine(item.querySelector(".progress"), { line: Object.assign({}, line, { details: null }) });
    const shown = Array.from(trayItems.keys()).map((n) => views.get(n)).filter(Boolean);
    const going = shown.filter(isActive).length;
    traySum.textContent = plural(shown.length, "request") + (going ? " · " + going + " to go" : " · all done");
    tray.hidden = trayClosed || shown.length < 2;
    document.body.classList.toggle("with-tray", !tray.hidden);
  };
  // The lines drawn again from what the library has now: a request is over. Each keeps its request line. A
  // removal done leaves its song's line saying so. Each brings the songbooks as they are now (a songbook's change,
  // a lookup that made the songbooks its song is in again, a removal), which the Songbooks tab (songbooks.js) and
  // the Select bar's menu (select.js) draw again ("caracole:songbooks").
  const redraw = (view) => {
    if (view.songbooks && typeof view.songbooks === "object") {
      document.dispatchEvent(new CustomEvent("caracole:songbooks", { detail: { songbooks: view.songbooks, view } }));
    }
    if (view.kind === "remove" && songOf(view) !== null) {
      removing.delete(songOf(view));
      if (view.state === "done") {
        removed(songOf(view));
        return;
      }
    }
    if (view.kind === "songbook") return;
    const data = view.card && typeof view.card === "object" ? view.card : null;
    if (!data) return;
    lostTo(Number(data.id), data.identity);
    const i = byIndex.get(Number(data.id));
    if (i !== undefined) {
      songs[i] = data;
      songKeys[i] = keyId(data.key);
      hay[i] = String(data.search || "");
      if (lines.has(i)) lines.set(i, refill(lines.get(i), lineFor(data)));  // else drawn when shown
    } else {
      arrived.set(Number(data.id), data);  // counted, and shown under the form until the next load
    }
    const spot = spots.get(Number(view.id));  // a result's row, or a line under the bar: the song's line, now
    if (spot) spots.set(Number(view.id), refill(spot, lineFor(data)));
    summarize();
    tallyChips();  // the list itself stays as it is: a line the filter now hides goes at the next search
  };
  const songOf = (view) => (view.songId === null || view.songId === undefined ? null : Number(view.songId));
  // Whether a job that is over brings what the page draws again: its song's line (none for a song the library
  // hasn't got), or the songbooks, for a songbook's change; a removal's song is gone, or as it was.
  const drawable = (view) => (view.kind === "songbook" ? Boolean(view.songbooks)
    : view.kind === "remove" || Boolean(view.card) || songOf(view) === null);
  const apply = (view) => {
    const id = Number(view.id);
    views.set(id, view);
    const song = songOf(view);
    if (song !== null) lostTo(song, view.identity);  // before anything shows the view on the line of another song
    if (song !== null) {
      if (!songJob.has(song) || songJob.get(song) <= id) songJob.set(song, id);
      if (!isActive(view)) busy.delete(song);
    }
    if (!isActive(view) && !settled.has(id) && drawable(view)) {
      settled.add(id);
      redraw(view);
    }
    paint(view);
    // A removal done, its line saying so: the id names that song no more.
    if (view.kind === "remove" && view.state === "done" && song !== null && byIndex.has(song)
        && songs[byIndex.get(song)].status === "removed") forget(song);
  };
  // The job's line on the song's line, and wherever else it shows (a result's row, #requested), and in the list
  // of requests.
  const paint = (view) => {
    const id = Number(view.id);
    const song = songOf(view);
    const i = song !== null && songJob.get(song) === id ? byIndex.get(song) : undefined;
    for (const item of [i === undefined ? null : lines.get(i), spots.get(id)]) {
      if (!item || (song !== null && removals.has(song))) continue;  // its line counts down to its removal
      const p = showRequest(item, view);
      if (view.kind === "remove") continue;  // its buttons wait where they are: the song is gone once it is done
      const button = item.querySelector("form.fetch");
      if (button && isActive(view)) {
        if (button.contains(document.activeElement)) focusOn(p);  // the line takes the button's place
        button.remove();
      }
      const again = item.querySelector(".actions.again");
      if (again && isActive(view)) {  // asked for already: the line is drawn again once it is over
        if (again.contains(document.activeElement)) focusOn(p);
        again.remove();
      }
      const picker = item.querySelector("form.pick-form");
      if (picker && isActive(view)) {  // POST /review would refuse a pick now: the line is drawn again after
        const box = picker.closest("details.picker");
        if (box.contains(document.activeElement)) focusOn(p);
        box.remove();
        const pick = item.querySelector(".line-pick");  // the line's button that opened it
        if (pick) {
          if (pick.contains(document.activeElement)) focusOn(p);
          pick.remove();
        }
      }
    }
    trayShow(view);
    // The Songbooks tab shows a songbook's change on its songbook, and a lookup on its song's set list lines.
    document.dispatchEvent(new CustomEvent("caracole:job", { detail: view }));
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

  // A song caracole removed: its line says so until the page is loaded again, with nothing left to open, fetch or
  // pick (its files are gone, and so is its data-id, which the Select mode finds songs by).
  const goneItem = (s) => {
    const artist = listOf(s.artists).length > 1 ? listOf(s.artists).join(", ") : String(s.artist);
    const line = resultRow({ dense: true, title: s.title, artist, status: "removed" });
    line.classList.add("gone");
    return line;
  };
  const removed = (id) => {
    const i = byIndex.get(id);
    if (i === undefined) return;
    songs[i] = Object.assign({}, songs[i], { status: "removed" });
    // Drawn again where it is, as tall as it was, its line where it was: nothing on the screen moves, seconds
    // after the tap.
    const gone = (old) => {
      const fresh = goneItem(songs[i]);
      if (!old) return fresh;
      // An opened card keeps its box, its margins and edge (card.css), as it keeps its height.
      if (old.matches('.line:not(.hit):has(> .line-more[aria-expanded="true"])')) fresh.classList.add("card-gone");
      const tall = old.isConnected ? old.getBoundingClientRect().height : 0;
      const line = old.querySelector(".progress");
      const top = line && old.isConnected ? line.getBoundingClientRect().top : null;
      const kept = refill(old, fresh);
      if (tall) kept.style.minHeight = tall + "px";
      if (line) line.style.minHeight = "";  // the last thing on the line, which keeps the height: as tall as it says
      if (top !== null && line.isConnected) {  // measured before a frame is drawn: it never moves
        const drop = top - line.getBoundingClientRect().top;
        if (drop > 0) line.style.marginTop = drop + "px";
      }
      return kept;
    };
    lines.set(i, gone(lines.get(i)));
    summarize();
    tallyChips();
    tell();
  };
  // A song of the page's gone from the library: its id names it no more, nor does what the page knew of it by that id
  // (fetched or removed when the page loaded). songs.id has no AUTOINCREMENT, so the next song added may get the id
  // again, and comes as a song new to the page (``arrived``), never in the gone one's line; select.js and
  // songbooks.js, which know the page's songs by id too, let it go ("caracole:gone").
  const forget = (id) => {
    if (!byIndex.has(id)) return;
    byIndex.delete(id);
    busy.delete(id);
    removing.delete(id);
    document.dispatchEvent(new CustomEvent("caracole:gone", { detail: { id } }));
  };
  // A view or a card that names by ``identity`` another song than the one the page knows by its id ``id``: that song
  // left the library where the page never saw it (removed in another tab, on another device or by caracole remove;
  // merged into another), and the newest song since got its id. Its line says Removed, as one removed here does.
  const REMOVED = { line: { tone: "removed", text: "Removed" } };
  const lostTo = (id, identity) => {
    const i = byIndex.get(id);
    if (i === undefined || !identity || String(songs[i].identity || "") === String(identity)) return;
    stopRemoval(id, REMOVED, false);  // counting down to its removal: nothing left to remove
    removed(id);
    showRequest(lines.get(i), REMOVED);
    forget(id);
  };

  let timer = 0;
  let misses = 0;
  let stopped = false;
  const pending = () => Array.from(watched).filter((id) => !settled.has(id));
  const schedule = (delay) => {
    if (timer || stopped || !pending().length) return;
    timer = setTimeout(poll, delay !== undefined ? delay : document.hidden ? BACKGROUND_POLL : POLL);
  };
  // The server can't answer this page any more (it restarted since the page was loaded): say so on each line.
  const stop = (text) => {
    stopped = true;
    for (const id of pending()) {
      apply(Object.assign({}, views.get(id), { line: { tone: "failed", text }, count: null }));
    }
  };
  const poll = () => {
    timer = 0;
    const ask = pending();
    fetch("jobs.json?jobs=" + ask.join(","), {
      cache: "no-store",
      headers: { Accept: "application/json", "X-Caracole-Form-Token": String(server.csrf || "") },
    }).then((r) => r.json().catch(() => null).then((body) => ({ ok: r.ok, status: r.status, body })))
      .then((answer) => {
        if (answer.status === 403) {
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
          for (const id of pending()) {
            paint(Object.assign({}, views.get(id), { line: { tone: "waiting", text }, count: null }));
          }
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
  // The Songbooks tab's seam (songbooks.js, which runs after this script): a job it asked for, followed as this
  // page's own are (``quiet``: its set list says how a lookup goes, so the list of requests leaves it out), each of
  // its views told back ("caracole:job"), a request's line, written as this page writes them, and the search's fold.
  window.caracoleLibrary = Object.freeze({
    track: (view, options) => {
      if (options && options.quiet) quiet.add(Number(view.id));
      track(view);
    },
    showLine,
    focusOn,
    fold,
  });

  if (server) {
    const requested = byId("requested");
    const requestedList = byId("requested-list");
    // A song asked for, before the library has it: its names alone, and how its request goes.
    const placeholder = (artist, title) => {
      const line = resultRow({ dense: true, title, artist });
      line.classList.add("pending");
      showLine(progressIn(line), { line: { tone: "queued", text: "Sending…" } });
      return line;
    };
    // A result's line whose request the server has just answered, put where it would be had the answer come at
    // once: the line left the results while it was on its way (Back to your songs, the ×, Escape, a newer answer
    // drawn). A newer answer with the same song takes this line in place of its own, its request line in it; else
    // the request's card comes under the bar (settleSpots), as for a line that leaves the results after the answer.
    const placed = (row) => {
      if (state.all && !row.isConnected && answer && answer.model && answer.model.items.has(hitKey(row))) {
        answer.model.lines.set(hitKey(row), row);
        drawGroups();
      }
      if (!state.all || !row.isConnected) settleSpots(state.all);
    };
    // A result's request, its request line in the result's own line, from "Sending…" on: ``view`` finds the job in
    // the answer.
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
      fetch(path, { method: "POST", body, headers: { Accept: "application/json" } })
        .then((r) => r.json().catch(() => null).then((answer) => ({ ok: r.ok, status: r.status, body: answer })))
        .then((reply) => {
          const job = reply.ok && reply.body && view(reply.body);
          if (go) go.disabled = false;
          if (!job || typeof job !== "object") {
            showLine(progressIn(row), failure(reply));
            return;
          }
          if (go && go.closest(".line-action, .later")) go.remove();  // its request line takes the button's place
          spots.set(Number(job.id), row);
          track(job);
          placed(row);
        }, () => {
          if (go) go.disabled = false;
          showLine(progressIn(row), UNREACHABLE);
        });
    };
    // Get it: the song looked up now (POST /lookup, one caracole get), to its sheet; a version picked under its chevron too.
    getIt = (pick, display, row, go) => askFrom("lookup", pick, ["song", "artist", "title", "ug", "tab", "lacuerda",
      "harptabs"], row, go, (answer) => answer.view);
    // Add for tonight's run: the song into wanted.txt under the site's names (POST /request, not fetched now).
    later = (pick, display, row, go) => askFrom("request", pick, ["artist", "title", "lacuerda"], row, go,
      (answer) => answer.job);
    // Add again, a song caracole removed: asked for as the request form asks, Fetch it now ticked (POST /request): a
    // wanted.txt line brings it back, and its lookup gets its sheet.
    addAgain = (pick, display, row, go) => askFrom("request", Object.assign({ fetch: "1" }, pick),
      ["artist", "title", "fetch"], row, go, (answer) => answer.job);
    // Back to your songs: a request's line in the results that is a song new to the library becomes its line
    // under the bar, which goes on saying how it goes; a song the list has says it on its own line. With
    // ``dropped``, only the lines a newer answer left out, at once.
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
        const card = song !== null && arrived.has(song) ? lineFor(arrived.get(song))
          : title.length ? placeholder(artist, title.join(" - ")) : placeholder("", artist);
        if (view) showRequest(card, view);
        requestedList.prepend(card);
        requested.hidden = false;
        spots.set(id, card);
      }
    };
    for (const view of listOf(server.jobs)) {
      if (!view || typeof view !== "object") continue;
      watched.add(Number(view.id));
      const song = songOf(view);
      if (view.kind === "songbook") {
        // A songbook's change: on its songbook, in the Songbooks tab (songbooks.js reads the page's jobs itself).
      } else if (requestedList && isActive(view) && view.kind === "song" && (song === null || !byIndex.has(song))) {
        // A song new to the library, on its way since before this page loaded: its line under the bar.
        const [artist, ...title] = String(view.display || "").split(" - ");
        const spot = title.length ? placeholder(artist, title.join(" - ")) : placeholder("", artist);
        requestedList.appendChild(spot);  // newest first, as they come
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
    if (tray) {  // folded, on every width: the lines say how each goes, and it would cover them
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
    // The request form, under the results: a line for the song at once, under the bar, which says how its
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
    const refused = new Set();  // the lines of requests the server refused, gone at the next one
    // The line #requested shows already for the job's song (or, before the song is in the library, for the
    // same "Artist - Title"), if any: asked for again, it is the one that says how this request goes.
    const spotOf = (view) => {
      const song = songOf(view);
      for (const [id, card] of spots) {
        const was = views.get(id);
        if (!was || !card.isConnected || !requestedList.contains(card)) continue;
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
        requestedList.prepend(spot);
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
          if (shown) {  // asked for again: its line says how it goes, where it is, still in the page
            spot.remove();
            spot = shown[1];
            if (shown[0] !== id) spots.delete(shown[0]);
          } else {
            const i = songOf(view) === null ? undefined : byIndex.get(songOf(view));
            if (i !== undefined) spot = refill(spot, lineFor(songs[i]));  // a song the library has: its line
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
    schedule();
  }
  summarize();
  render();
  // Come from a sheet's artist line (#by=): the address the page writes for what it shows, in place of the link's, with
  // no step of its own, so Back goes to the sheet and a reload or a bookmark keeps the search, or the artist's songs.
  let cameBy = false;
  try {
    cameBy = new URLSearchParams(location.hash.slice(1)).has("by");
  } catch (err) {
    // A malformed address: nothing to write again.
  }
  if (cameBy) save();
  // Back from a page of caracole serve's about a song (Remove's question): its line in view, and the focus
  // on it, as the A-Z strip leaves a group; the address keeps the rest. In the next frame, once every script
  // has drawn what it draws (the Songbooks tab, shown as it was left).
  let back = NaN;
  try {
    back = Number(new URLSearchParams(location.hash.slice(1)).get("song"));
  } catch (err) {
    // A malformed address: nothing to show.
  }
  if (back) {
    requestAnimationFrame(() => {
      const i = byIndex.get(back);
      const item = i === undefined ? null : lines.get(i);
      if (item && item.isConnected) {
        item.scrollIntoView({ block: "center" });
        item.focus({ preventScroll: true });
      }
      save();
    });
  }
})();
