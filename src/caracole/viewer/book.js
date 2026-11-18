(() => {
  "use strict";
  // songbook.html, before the sheet viewer's script: the contents, or one song for the viewer.
  const doc = document.documentElement;
  const sections = Array.from(document.querySelectorAll("section.song"));
  const toc = document.getElementById("contents");
  // The viewer keeps a page's settings under this name, and each song's under its own (its id after "#": songStore), so
  // that two tabs of the songbook never write each other's. Before that, the one name held the song open last, each
  // song's kept in the songbook's record (book.songs) and swapped in: what they still hold moves to the song's own name.
  const VIEWER = "caracole-viewer:" + location.pathname;
  const songStore = (id) => VIEWER + "#" + id;
  const BOOK = "caracole-songbook:" + location.pathname;
  const book = (() => {
    try {
      const saved = JSON.parse(localStorage.getItem(BOOK) || "null");
      if (saved && typeof saved === "object") return saved;
    } catch (err) { /* no storage: nothing is remembered */ }
    return {};
  })();
  if (!book.songs || typeof book.songs !== "object") book.songs = {};
  const keep = () => {
    try {
      localStorage.setItem(BOOK, JSON.stringify(book));
    } catch (err) { /* private mode, or a sandbox */ }
  };
  // The settings the viewer saved under the one name, for the song open last: into that song's own place, once.
  const harvest = () => {
    try {
      const mine = localStorage.getItem(VIEWER);
      if (mine === null) return;
      if (typeof book.at === "string" && localStorage.getItem(songStore(book.at)) === null) {
        localStorage.setItem(songStore(book.at), mine);
      }
      localStorage.removeItem(VIEWER);
    } catch (err) { /* no storage */ }
  };

  const hash = location.hash.replace(/^#/, "");
  const asked = /^song-(\d+)=?(?:&|$)/.exec(hash);  // the viewer may add its settings: "song-3=&t=2"
  let current = asked ? sections.find((s) => s.dataset.n === asked[1]) || null : null;
  if (!current && !hash) {
    current = sections.find((s) => s.dataset.id === book.at) || null;  // where you were
    // The address names it, as a link to it would: the viewer keeps its settings there too ("#song-3=&t=2"),
    // so a reload opens this song with them. Replaced, so Back still leaves the page.
    if (current) {
      try {
        history.replaceState(history.state, "", "#song-" + current.dataset.n);
      } catch (err) { /* an address the page can't change */ }
    }
  }
  harvest();
  // The player's instrument: the one the song came with in its address (carried from the song before; none where the
  // browser keeps it), or the last one chosen here by hand; and the one the song's own version names, if any, which
  // it opens on (viewer.js), its own alone. On such a song the address's inst= is the song's own once the viewer has
  // written it, so the player's goes on beside it (player=), for a reload there where the browser keeps nothing.
  const given = new URLSearchParams(hash);
  let player = given.has("player") ? given.get("player") : given.get("inst"), ownInst = null;
  const notePlayer = () => {
    if (ownInst === null || player === null) return;
    try {
      const to = new URLSearchParams(location.hash.slice(1));
      if (to.get("player") === player) return;
      to.set("player", player);
      history.replaceState(history.state, "", "#" + to.toString());
    } catch (err) { /* an address the page can't change */ }
  };

  // The songs' names (their titles, their artists') in the characters the viewer shows the Chinese in, Simplified at
  // first: its Chinese characters, kept for every page (localStorage), else trad=1 in the address, which carryScreen
  // takes on. book.py's song-names block converts each by its text as written (data-zh); on a song, viewer.js draws
  // them again when the choice changes there.
  const namesEl = document.getElementById("song-names");
  let names = null;
  try {
    names = JSON.parse(namesEl ? namesEl.textContent : "null");
  } catch (err) { /* none: as written */ }
  // As the viewer reads it (viewer.js choiceOf): the one a link names, else the browser's; on a page come back to (a
  // reload, a songbook's next song, Back), the browser's over an address written before.
  let returning = false, hanziKept = null;
  try {
    const entry = performance.getEntriesByType("navigation")[0];
    returning = Boolean(entry) && (entry.type === "reload" || entry.type === "back_forward");
  } catch (err) { /* read as a link followed */ }
  try {
    hanziKept = localStorage.getItem("caracole-viewer-hanzi");
  } catch (err) { /* no storage: the address says */ }
  const tradNamed = new URLSearchParams(location.hash.slice(1)).get("trad") === "1";
  const trad = tradNamed && (!returning || hanziKept === null) ? true : hanziKept === "traditional";
  const named = (text) => {
    const table = names && typeof names === "object" ? names[trad ? "traditional" : "simplified"] : null;
    return table && typeof table === "object" && Object.prototype.hasOwnProperty.call(table, text)
      && typeof table[text] === "string" ? table[text] : text;
  };
  for (const el of document.querySelectorAll("[data-zh]")) el.textContent = named(el.getAttribute("data-zh"));
  // On the contents, the songbook's PDF in Traditional characters while they are chosen (book.py's data-trad); on a
  // song, viewer.js links it, as it does its own.
  if (!current && trad) {
    for (const link of document.querySelectorAll("a.pdf[data-trad]")) link.setAttribute("href", link.getAttribute("data-trad"));
  }

  if (current) {
    const n = current.dataset.n;
    doc.dataset.view = "song";
    toc.hidden = true;
    for (const s of sections) s.hidden = s !== current;
    // The names the viewer looks for.
    for (const [from, to] of [["facts-", "facts"], ["necks-", "necks"], ["strip-", "strip"], ["sheet-", "sheet"],
      ["data-", "song"]]) {
      const el = document.getElementById(from + n);
      if (el) el.id = to;
    }
    const data = document.getElementById("song");
    try {
      const song = JSON.parse(data.textContent);
      song.voicings = JSON.parse(document.getElementById("voicings").textContent);
      const easy = document.getElementById("easy");  // every instrument's easy keys, for a song with a key
      if (easy && song.key) song.easy = JSON.parse(easy.textContent);
      const winds = document.getElementById("winds");  // the winds' fingerings and the harps' notes, every song's
      if (winds) song.winds = JSON.parse(winds.textContent);
      song.store = songStore(current.dataset.id);  // the name its settings are kept under (viewer.js store)
      data.textContent = JSON.stringify(song);
      ownInst = new URLSearchParams(String(song.start || "")).get("inst");
    } catch (err) { /* the viewer says so */ }
    notePlayer();
    document.addEventListener("change", (e) => {
      if (!(e.target instanceof HTMLSelectElement && e.target.id === "insts")) return;
      player = e.target.value;
      notePlayer();
    });
    const title = current.querySelector("h2.title");
    const name = document.querySelector(".book-head h1");
    if (title && name) document.title = title.textContent + " · " + name.textContent;
    // A Chinese song's tab title follows the choice too: its name as written, converted as its title is.
    const head = document.querySelector("title");
    if (title && name && head && title.hasAttribute("data-zh") && names && typeof names === "object" && namesEl) {
      const own = title.getAttribute("data-zh"), written = own + " · " + name.textContent;
      for (const script of ["simplified", "traditional"]) {
        const table = names[script];
        if (table && typeof table === "object" && Object.prototype.hasOwnProperty.call(table, own)) {
          table[written] = table[own] + " · " + name.textContent;
        }
      }
      head.setAttribute("data-zh", written);
      namesEl.textContent = JSON.stringify(names);
    }
    const returning = book.at === current.dataset.id;
    const before = book.songs[current.dataset.id];  // kept in the songbook's record before: to its own name, once
    if (typeof before === "string") {
      try {
        if (localStorage.getItem(songStore(current.dataset.id)) === null) {
          localStorage.setItem(songStore(current.dataset.id), before);
        }
      } catch (err) { /* no storage */ }
    }
    delete book.songs[current.dataset.id];
    book.at = current.dataset.id;
    if (!returning) book.y = 0;
    keep();
    if (returning && Number(book.y) > 0) {
      window.addEventListener("load", () => requestAnimationFrame(() => window.scrollTo(0, Number(book.y))));
    }
  } else {
    doc.dataset.view = "contents";
    for (const s of sections) s.hidden = true;
    const here = toc.querySelector('a[data-id="' + String(book.at || "").replace(/[^0-9a-f]/g, "") + '"]');
    if (here && book.at) here.parentElement.classList.add("here");
  }

  const save = () => {
    if (current) book.y = Math.round(window.scrollY);
    keep();
  };
  // The rail of necks, the pinyin, the Chinese characters and the instrument are the screen's choices, not a song's:
  // where there is no storage (caracole serve's sandbox), the address the viewer keeps them in ("necks=0", "py=1",
  // "trad=1", "inst=ukulele") goes on with every step, to the next song or the contents. From a song on an instrument
  // of its own, the step goes on with the player's.
  const SCREEN = ["necks", "py", "trad", "inst"];
  const carryScreen = (from) => {
    const at = String(from || "").indexOf("#");
    const was = new URLSearchParams(at >= 0 ? from.slice(at + 1) : "");
    const to = new URLSearchParams(location.hash.slice(1));
    let changed = to.has("player");  // the song's own address alone holds it (notePlayer)
    to.delete("player");
    for (const name of SCREEN) {
      const kept = name === "inst" && ownInst !== null ? player : was.get(name);
      if (to.get(name) === kept) continue;
      if (kept !== null) to.set(name, kept);
      else to.delete(name);
      changed = true;
    }
    if (!changed) return;
    try {
      history.replaceState(history.state, "", "#" + to.toString());
    } catch (err) { /* an address the page can't change */ }
  };
  // Each step loads the page again, so the viewer starts afresh on the song it shows.
  // A change that names the same song (a layer closing, the viewer writing its settings) never reloads it.
  const songOf = (url) => {
    const at = url.indexOf("#");
    const m = at < 0 ? null : /^song-(\d+)(?:=|&|$)/.exec(url.slice(at + 1));
    return m ? m[1] : "";
  };
  window.addEventListener("hashchange", (e) => {
    save();
    carryScreen(e.oldURL);
    const same = songOf(e.oldURL);
    // The contents (any fragment that names no song) load again whatever the change: "#contents" to no address.
    if (!same || same !== songOf(e.newURL)) location.reload();
  });
  window.addEventListener("pagehide", save);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") save();
  });
  if (!current) return;

  const at = sections.indexOf(current);
  const go = (to) => {
    if (to) location.hash = "song-" + to.dataset.n;
  };
  // The settings, the key list, a card or the overlay's sheet (its Harmony tab among them) open, or a progression
  // playing from the rail's Harmony tab (viewer.js marks it data-playing): the arrows and a swipe stay with them.
  const busy = () => ["panel", "key-list", "card"].some((id) => {
    const el = document.getElementById(id);
    return el && !el.hidden;
  }) || Boolean(document.querySelector("#necks[data-sheet]:not([hidden]), #necks #harmony[data-playing]"));
  // A swipe across the sheet: left for the next song, right for the one before.
  let start = null;
  document.addEventListener("touchstart", (e) => {
    const target = e.target instanceof Element ? e.target : null;
    start = e.touches.length === 1 && !busy()
      && !(target && target.closest(".tab, .necks, .strip, .sheet-ui, .pill, .bar, input"))
      ? { x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now() } : null;
  }, { passive: true });
  document.addEventListener("touchend", (e) => {
    if (!start || !e.changedTouches.length) return;
    const dx = e.changedTouches[0].clientX - start.x;
    const dy = e.changedTouches[0].clientY - start.y;
    const quick = Date.now() - start.t < 800;
    start = null;
    if (quick && Math.abs(dx) > 70 && Math.abs(dx) > 2 * Math.abs(dy)) go(sections[dx < 0 ? at + 1 : at - 1]);
  }, { passive: true });
  document.addEventListener("keydown", (e) => {
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || busy()) return;
    if (e.target instanceof Element && e.target.closest("input, select, textarea")) return;
    if (e.key === "ArrowRight") go(sections[at + 1]);
    else if (e.key === "ArrowLeft") go(sections[at - 1]);
  });
})();
