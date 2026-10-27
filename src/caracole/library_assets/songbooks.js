// The Songbooks tab (songbook_section.py gives its data): the songbooks as lines, and the one opened as a set list.
// Served, each song can be dragged (or moved with ↑ and ↓ on its grip), played elsewhere (its chip: key, mode,
// capo, instrument), taken out (×) or got now (Get it); the songbook gets its missing songs, a song from your library or the
// indexes (Add a song), another name, or deleted. Each is one form posted with fetch(), queued as a caracole
// songbook command; the songbook's status line says how it goes, a lookup's line its song's, and once a change, a
// lookup or a removal is over /jobs.json brings the songbooks as they are now (library.js tells: "caracole:songbooks").
// The file on disk shows them read-only, with the commands that change them. Every text is put in with textContent.
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const panel = byId("songbooks");
  const libraryView = byId("library-view");
  const tabLibrary = byId("tab-library");
  const tabBooks = byId("tab-songbooks");
  let data;
  try {
    data = JSON.parse(byId("songs").textContent);
  } catch (err) {
    return;
  }
  if (!panel || !libraryView || !tabLibrary || !tabBooks) return;
  const listOf = (value) => (Array.isArray(value) ? value : []);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const button = (label, cls, onclick, aria) => {
    const b = el("button", cls, label);
    b.type = "button";
    if (aria) b.setAttribute("aria-label", aria);
    if (onclick) b.addEventListener("click", onclick);
    return b;
  };
  // Served by caracole serve (the data's ``server``), else the file on disk, or the Android app's copy of it.
  const server = data.server && typeof data.server === "object" ? data.server : null;
  const lib = window.caracoleLibrary || null;  // library.js: track a job, write a request's line
  const rows = window.caracole || null;  // rows.js, through library.js: a dense line
  const isActive = (view) => Boolean(view) && (view.state === "queued" || view.state === "running");
  const plural = (n, word) => n + " " + word + (Number(n) === 1 ? "" : "s");
  const shellQuote = (text) => "'" + String(text).replace(/'/g, "'\\''") + "'";
  // The names a command takes, each quoted, after "--" when one starts with "-" (-M-, an artist): caracole would
  // take it for an option ("No such option: -M"). caracole serve's own command lines always have it.
  const shellNames = (...names) => (names.some((n) => String(n).startsWith("-")) ? "-- " : "") +
    names.map(shellQuote).join(" ");
  const shelfOf = (value) => (value && typeof value === "object" ? value : {});
  let shelf = shelfOf(data.songbooks);
  const books = () => listOf(shelf.books).filter((b) => b && typeof b === "object");
  // A songbook Select was making whose make failed where it ran: songbooks.toml hasn't got it, and nothing deleted it.
  // It stays as it would have been, its line saying it couldn't be made and its status line why, until it is made
  // (under its name, or with the picks it gave back under another) or forgotten (``letGo``).
  const unmade = new Map();  // its name -> its book
  const withUnmade = (given) => {
    const named = new Set(listOf(given.books).map((b) => String(b && b.name)));
    for (const name of Array.from(unmade.keys())) if (named.has(name)) unmade.delete(name);
    return unmade.size ? Object.assign({}, given, { books: listOf(given.books).concat(Array.from(unmade.values())) })
      : given;
  };
  const songs = listOf(data.songs);
  // Whether a songbook offers to get a song of your library now (Get the missing songs now), as
  // songbook.songs_to_get has it: one with no sheet yet (no file of it is its sheet's), unless it is ignored.
  const gettable = (id) => {
    const s = songs.find((x) => x && Number(x.id) === Number(id));
    return Boolean(s) && s.status !== "ignored" && !listOf(s.files).some((f) => f && f.primary);
  };

  // --- the tab, and the address ---------------------------------------------------------------------------
  // #tab=songbooks shows it, and book=NAME the songbook open; the library's own words in the address stay.
  const state = { tab: "library", book: "" };
  try {
    const params = new URLSearchParams(location.hash.slice(1));
    if (params.get("tab") === "songbooks") state.tab = "songbooks";
    state.book = params.get("book") || "";
  } catch (err) {
    // A malformed address: the library.
  }
  const save = () => {
    let params = new URLSearchParams();
    try {
      params = new URLSearchParams(location.hash.slice(1));
    } catch (err) {
      // A malformed address: the tab's words alone.
    }
    params.delete("tab");
    params.delete("book");
    if (state.tab === "songbooks") {
      params.set("tab", "songbooks");
      if (state.book) params.set("book", state.book);
    }
    try {
      history.replaceState(null, "", "#" + params.toString());
    } catch (err) {
      // Some browsers refuse this for local files: the page works the same.
    }
  };
  const showTab = (name, focus) => {
    const onBooks = name === "songbooks";
    tabLibrary.setAttribute("aria-selected", String(!onBooks));
    tabBooks.setAttribute("aria-selected", String(onBooks));
    tabLibrary.tabIndex = onBooks ? -1 : 0;
    tabBooks.tabIndex = onBooks ? 0 : -1;
    libraryView.hidden = onBooks;
    panel.hidden = !onBooks;
    document.body.classList.toggle("on-songbooks", onBooks);
    state.tab = onBooks ? "songbooks" : "library";
    save();
    if (focus) (onBooks ? tabBooks : tabLibrary).focus();
  };
  tabLibrary.addEventListener("click", () => showTab("library"));
  tabBooks.addEventListener("click", () => showTab("songbooks"));
  tabBooks.parentNode.addEventListener("keydown", (e) => {  // the tabs' own keys: ← → Home End
    if (["ArrowLeft", "ArrowRight", "Home", "End"].indexOf(e.key) < 0) return;
    e.preventDefault();
    const onBooks = e.key === "End" || (e.key !== "Home" && document.activeElement === tabLibrary);
    showTab(onBooks ? "songbooks" : "library", true);
  });

  // --- the jobs it shows ---------------------------------------------------------------------------------
  const newest = new Map();  // a songbook's name -> the newest view of a change of it
  const lookupViews = new Map();  // job id -> the newest view of a lookup that a song added here waits for
  const songViews = new Map();  // song id -> the newest view of its lookup
  // The set list's lines of a lookup's song: by its id, and by its identity key where both have one, which an id
  // given again never shares (songs.id has no AUTOINCREMENT: once the newest song is removed, in another tab or by
  // caracole remove, the next one added gets its id, while a set list drawn before still has the removed one's).
  const songLines = (root, view) => Array.from(root.querySelectorAll('.set-line[data-song="' + Number(view.songId) +
    '"]')).filter((li) => !view.identity || !li.dataset.key || li.dataset.key === String(view.identity));
  const changes = new Map();  // job id -> the newest view of a songbook's change
  // A songbook's name -> the one a rename sent gives it: over its set list from the tap until the rename is over, so
  // that nothing beside it moves then.
  const renaming = new Map();
  const placed = new Map();  // job id -> the line that shows it (a song added, before the songbook has it)
  const namesOf = (view) => {
    const book = view && view.songbook && typeof view.songbook === "object" ? view.songbook : null;
    return book ? [String(book.name), book.after === null || book.after === undefined ? "" : String(book.after)] : [];
  };
  const busyBook = (name, but) => Array.from(changes.values())
    .some((v) => isActive(v) && v.id !== but && namesOf(v).indexOf(name) >= 0);
  const showLine = (p, view) => {
    if (lib) lib.showLine(p, view);
    else p.textContent = String(view && view.line && view.line.text || "");
  };
  const failed = (text) => ({ line: { tone: "failed", text } });
  const UNREACHABLE = "caracole serve can't be reached: is it running?";
  const failure = (reply) => (reply.body && reply.body.error) || "caracole serve answered " + reply.status +
    ": reload the page.";
  const postTo = (path, body) => fetch(path, {
    method: "POST", body, headers: { Accept: "application/json" },
  }).then((r) => r.json().catch(() => null).then((answer) => ({ ok: r.ok, status: r.status, body: answer })));
  const fields = (book, more) => {
    const body = new URLSearchParams({ csrf: String(server && server.csrf || ""), name: String(book) });
    for (const [k, v] of Object.entries(more || {})) {
      if (v !== undefined && v !== null && v !== "") body.set(k, String(v));
    }
    return body;
  };
  // A line under a set list's song, made the first time, as a song's in the library (library.js's progressIn).
  const lineIn = (item) => {
    let p = item.querySelector(":scope > .progress");
    if (!p) {
      p = el("p", "progress");
      p.setAttribute("role", "status");
      item.appendChild(p);
    }
    return p;
  };

  // --- the list of songbooks -------------------------------------------------------------------------------
  const inner = el("div", "books-in");
  const side = el("nav", "book-list");
  side.setAttribute("aria-label", "Songbooks");
  const lines = el("ul", "book-lines");
  const sideError = el("p", "sb-error");
  sideError.setAttribute("role", "alert");
  const sideEmpty = el("p", "hint book-none");
  const newBook = button("+ New songbook", "btn small new-book", () => {
    showTab("library");
    document.dispatchEvent(new CustomEvent("caracole:new-songbook"));
  });
  newBook.title = "Pick its songs in your library, then name it";
  side.append(lines, sideEmpty, sideError, newBook);
  inner.appendChild(side);
  panel.appendChild(inner);
  const wide = window.matchMedia ? window.matchMedia("(min-width: 900px)") : { matches: true };
  const openName = () => {
    const named = books().find((b) => b.name === state.book);
    if (named) return named.name;
    return wide.matches && books().length ? String(books()[0].name) : "";
  };
  const metaOf = (b) => [plural(Number(b.songs) || 0, "song"),
    Number(b.missing) ? b.missing + " without a sheet" : "",
    b.changed ? "changed " + b.changed : b.failed ? "couldn't be made" : b.pending ? "on its way" : "not made yet"]
    .filter(Boolean).join(" · ");
  const gone = new Set();  // what a change left on the page, until your next click or key: nothing moves meanwhile
  const sweep = () => {
    if (!gone.size) return;
    for (const node of gone) node.remove();
    gone.clear();
    if (!book || !book.isConnected) draw();
  };
  document.addEventListener("pointerdown", sweep, true);
  document.addEventListener("keydown", sweep, true);
  const drawList = () => {
    const shownNow = new Map(Array.from(lines.children).map((li) => [li.dataset.book, li]));
    const open = openName();
    const kept = [];
    for (const b of books()) {
      const name = String(b.name);
      const li = shownNow.get(name) || el("li");
      shownNow.delete(name);
      li.dataset.book = name;
      li.classList.remove("gone");
      li.style.minHeight = "";
      const go = button(null, "book-line", () => openBook(name, true));
      go.dataset.book = name;
      go.append(el("span", "book-name", name), el("span", "book-meta", metaOf(b)));
      if (name === open) go.setAttribute("aria-current", "true");
      const focused = li.contains(document.activeElement);
      li.replaceChildren(go);
      if (focused) go.focus({ preventScroll: true });
      kept.push(li);
    }
    for (const [name, li] of shownNow) {  // gone from songbooks.toml: says so where it was, until your next click
      if (!gone.has(li)) {
        const tall = li.getBoundingClientRect().height;  // as tall as it was: the lines under it stay where they were
        if (tall) li.style.minHeight = tall + "px";
        const left = el("p", "book-line gone");
        left.append(el("span", "book-name", name), el("span", "book-meta", "deleted"));
        li.replaceChildren(left);
        li.classList.add("gone");
        gone.add(li);
      }
      const at = Array.from(lines.children).indexOf(li);
      kept.splice(Math.min(at, kept.length), 0, li);
    }
    lines.replaceChildren(...kept);
    lines.hidden = !kept.length;
    newBook.hidden = !songs.length;  // its songs are picked in the library: with none, there is nothing to pick
    sideEmpty.textContent = books().length || shelf.error ? "" : !songs.length
      ? "No songbook yet. Your library has no songs to pick from: add one first."
      : server
      ? "No songbook yet: + New songbook picks its songs in your library."
      : "No songbook yet. Select songs in your library to make one.";
    sideEmpty.hidden = !sideEmpty.textContent;
    sideError.textContent = shelf.error ? String(shelf.error) : "";
    sideError.hidden = !shelf.error;
    const count = tabBooks.querySelector(".n");
    if (count) count.textContent = books().length ? String(books().length) : "";
  };

  // --- the songbook opened: a set list ----------------------------------------------------------------------
  let book = null;  // its article
  let bookName = "";
  let status = null;  // its status line, which says how its changes go
  const said = el("p", "visually-hidden set-said");  // where a song moved, for a screen reader
  said.setAttribute("aria-live", "polite");
  const keys = listOf(shelf.keys);
  const modes = listOf(shelf.modes);
  const capoMax = Number(shelf.capoMax) || 11;
  // The viewer's instruments, each [id, name, whether it takes a capo]: on one that takes none, the key is the key
  // the song sounds in (the data's ``at.sounds``), and the capo menu is off.
  const instruments = listOf(shelf.instruments).filter((i) => Array.isArray(i) && i.length >= 3);
  const takesCapo = (id) => {
    const found = instruments.find((i) => String(i[0]) === id);
    return !found || found[2] !== false;
  };
  const titleOf = (text) => String(text).charAt(0).toUpperCase() + String(text).slice(1);
  const editSerial = { n: 0 };
  const lockBook = (on) => {
    if (!book || book.classList.contains("sb-busy") === on) return;
    book.classList.toggle("sb-busy", on);
    for (const control of book.querySelectorAll("button, input, select")) {
      if (!control.closest(".add-song") && !control.classList.contains("book-back")
          && !control.classList.contains("book-forget")) control.disabled = on;
    }
  };
  const lineOf = (ev) => ev.currentTarget.closest(".set-line");  // a line drawn again keeps its element
  // A song's Guitar Pro mark, after its title (the data's ``guitar``): a set list is a playlist too. A Guitar Pro or
  // Power Tab file caracole keeps is a guitar drawn solid: served, it opens caracole serve's Guitar Pro page (with
  // alphaTab there); else, and on the file on disk, it downloads the file under the song's name, as the library's line
  // does. The guitar is body.html's #guitar-glyph, an SVG the HTML parser made (a body, its sound hole and bridge, a
  // neck and a headstock), cloned: no namespace to name, nothing parsed here.
  const glyph = byId("guitar-glyph");
  const guitarGlyph = () => (glyph && glyph.content && glyph.content.firstElementChild
    ? glyph.content.firstElementChild.cloneNode(true) : el("span", null, "GP"));
  const relativeHref = (href) => (/^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith("/") ? "#" : href);
  const guitarMark = (e) => {
    const g = e.guitar && typeof e.guitar === "object" ? e.guitar : null;
    const href = g && g.kind === "file" && typeof g.href === "string" ? g.href : "";
    if (!href) return null;
    const song = String(e.title || "");
    const a = el("a", "set-gp");
    const page = server && server.guitar && typeof g.page === "string" && g.page ? g.page : "";
    const file = typeof g.download === "string" && g.download ? g.download : song;
    a.href = relativeHref(page || href);
    if (!page && typeof g.download === "string" && g.download) a.setAttribute("download", g.download);
    a.setAttribute("aria-label", "Guitar Pro tab: " + file + (page ? ", open it in the browser" : ", download it"));
    a.title = page ? "Guitar Pro tab: open it in the browser" : "Guitar Pro tab: download " + file;
    a.appendChild(guitarGlyph());
    return a;
  };
  const setLine = (e, total, readOnly) => {
    const title = String(e.title || "");
    const li = el("li", "set-line");
    li.dataset.entry = String(e.entry || "");
    li.dataset.key = String(e.key || "");
    if (e.id !== null && e.id !== undefined) li.dataset.song = String(e.id);
    if (e.pending) li.classList.add("pending");
    if (!readOnly) {
      const grip = button(null, "grip", null, "Move " + title + ", " + e.n + " of " + total +
        ": drag it, or press ↑ or ↓");
      grip.title = "Drag it to its place, or press ↑ or ↓";
      const dots = el("span", null, "⠿");
      dots.setAttribute("aria-hidden", "true");
      grip.appendChild(dots);
      if (e.pending) grip.disabled = true;
      li.appendChild(grip);
    }
    const name = el("div", "set-name");
    name.appendChild(el("span", "set-n", e.n));
    const heading = el("h3", null, title);
    heading.title = title;
    let titled = el("div", "set-title");
    if (e.href) {
      titled = el("a", "set-title");
      titled.href = /^[a-z][a-z0-9+.-]*:/i.test(String(e.href)) || String(e.href).startsWith("/") ? "#" : String(e.href);
    }
    titled.appendChild(heading);
    name.appendChild(titled);
    const gp = guitarMark(e);
    if (gp) name.appendChild(gp);
    li.appendChild(name);
    const meta = el("div", "set-meta");
    meta.appendChild(el("span", "set-by", e.artist || ""));
    const slot = el("span", "set-plays");
    if (e.plays) {
      const where = String(e.plays);
      const whose = e.own ? where + ", its own version" : where + " here";
      if (readOnly || !e.at) {
        const chip = el("span", "plays", where);
        chip.title = e.own ? "As its own version plays it" : "Where this songbook plays it";
        slot.appendChild(chip);
      } else {
        const chip = button(where, "plays" + (e.own ? "" : " set"), (ev) => edit(lineOf(ev), e),
          title + " plays in " + whose + ": change it");
        chip.title = "Where this songbook plays it: its key, mode, capo and instrument";
        chip.setAttribute("aria-expanded", "false");
        if (e.pending) chip.disabled = true;
        slot.appendChild(chip);
      }
    } else if (e.missing) {
      slot.appendChild(el("span", "badge missing", titleOf(e.missing)));
    } else if (e.pending) {
      slot.appendChild(el("span", "plays pending", "…"));
    }
    meta.appendChild(slot);
    li.appendChild(meta);
    if (!readOnly) {
      const act = el("div", "set-act");
      if (e.get && server) {
        const get = button("Get it", "btn small set-get", (ev) => getOne(lineOf(ev), e), "Get " + title + " now");
        get.title = "Looks it up now, as caracole get does, then makes the songbook again";
        act.appendChild(get);
      }
      li.appendChild(act);
      const out = button(null, "set-out", (ev) => takeOut(lineOf(ev), e), "Take " + title + " out of " + bookName);
      out.title = "Take it out";
      const cross = el("span", null, "×");
      cross.setAttribute("aria-hidden", "true");
      out.appendChild(cross);
      if (e.pending) out.disabled = true;
      li.appendChild(out);
    }
    return li;
  };
  // A line drawn again as fresh where it is: its own request line kept (a live region, read out to the last), the
  // focus kept on what had it (the grip after ↑, say).
  const refill = (old, fresh) => {
    const kept = old.querySelector(":scope > .progress");
    const at = document.activeElement;
    const focused = at && at !== old && old.contains(at) && (!kept || !kept.contains(at)) ? at.classList[0] : "";
    old.replaceChildren(...Array.from(fresh.childNodes));
    if (kept) old.appendChild(kept);
    old.className = fresh.className;
    for (const name of Object.keys(old.dataset)) delete old.dataset[name];
    Object.assign(old.dataset, fresh.dataset);
    if (focused) {
      const again = old.querySelector("." + focused);
      if (again && !again.disabled) again.focus({ preventScroll: true });
      else if (kept && lib) lib.focusOn(kept);
    }
    return old;
  };
  const renumber = () => {
    if (!book) return;
    const shown = Array.from(book.querySelectorAll(".set > .set-line:not(.gone)"));
    shown.forEach((li, i) => {
      const n = li.querySelector(".set-n");
      if (n && n.textContent !== String(i + 1)) n.textContent = String(i + 1);
      const grip = li.querySelector(".grip");
      const title = li.querySelector("h3") ? li.querySelector("h3").textContent : "";
      if (grip) grip.setAttribute("aria-label", "Move " + title + ", " + (i + 1) + " of " + shown.length +
        ": drag it, or press ↑ or ↓");
    });
  };
  let moving = 0;  // a drag, or ↑ and ↓ waiting to be sent: the set list isn't drawn again under it
  const drawSet = (b, readOnly) => {
    const list = book.querySelector(".set");
    const entries = listOf(b.set).filter((e) => e && typeof e === "object");
    const before = Array.from(list.children);
    const byEntry = new Map(before.filter((li) => !li.classList.contains("gone")).map((li) => [li.dataset.entry, li]));
    const byKey = new Map(before.filter((li) => li.classList.contains("pending")).map((li) => [li.dataset.key, li]));
    const final = entries.map((e) => {
      const fresh = setLine(e, entries.length, readOnly);
      const was = byEntry.get(String(e.entry)) || (e.key ? byKey.get(String(e.key)) : null);
      if (!was) return fresh;
      byEntry.delete(was.dataset.entry);
      if (was.classList.contains("editing")) return was;  // its menus open: as you left them
      return refill(was, fresh);
    });
    for (const li of byEntry.values()) {  // taken out: it says so where it was, until your next click or key
      if (!gone.has(li)) {
        const left = el("div", "set-name");
        left.appendChild(el("h3", null, li.querySelector("h3") ? li.querySelector("h3").textContent : ""));
        const kept = li.querySelector(":scope > .progress");
        li.replaceChildren(left, el("span", "set-gone", li.classList.contains("pending") ? "Not added" : "Taken out"));
        if (kept) li.appendChild(kept);
        li.className = "set-line gone";
        gone.add(li);
      }
      final.splice(Math.min(before.indexOf(li), final.length), 0, li);
    }
    for (const li of before) if (gone.has(li) && final.indexOf(li) < 0) final.splice(before.indexOf(li), 0, li);
    list.replaceChildren(...final);
    for (const view of songViews.values()) {  // a lookup's line, on its song's line
      for (const li of songLines(list, view)) showLine(lineIn(li), view);
    }
    renumber();
  };
  const fileCommands = (b) => {
    const first = listOf(b.set)[0];
    const song = first ? String(first.entry) : "ARTIST - TITLE";
    const setting = "--key G --mode dorian --capo 0";  // before "--", when the names need it
    const names = shellNames(b.name, song);
    const box = el("div", "book-commands");
    box.appendChild(el("p", "hint", "This page changes nothing: where caracole runs, these do (or edit songbooks.toml):"));
    const list = el("ul", "commands");
    for (const [what, command] of [
      ["Add a song", "caracole songbook add " + shellNames(b.name, "ARTIST - TITLE")],
      ["Move a song", "caracole songbook move " + names + " 2"],
      ["Play it elsewhere", "caracole songbook set " +
        (names.startsWith("--") ? setting + " " + names : names + " " + setting)],
      ["Take it out", "caracole songbook remove " + names],
      ["Rename it", "caracole songbook rename " + shellNames(b.name, "NEW NAME")],
      ["Delete it", "caracole songbook delete " + shellNames(b.name)],
    ]) {
      const item = el("li");
      item.append(el("span", "command-what", what), el("code", null, command));
      list.appendChild(item);
    }
    box.appendChild(list);
    return box;
  };
  const drawFiles = (b, readOnly) => {
    const row = book.querySelector(".book-files");
    const links = listOf(b.files).filter((f) => f && typeof f === "object").map((f) => {
      const a = el("a", "btn small", f.label);
      a.href = /^[a-z][a-z0-9+.-]*:/i.test(String(f.href)) || String(f.href).startsWith("/") ? "#" : String(f.href);
      return a;
    });
    // On its way (Select's make): the files it will have, and its button to get the songs without a sheet, there
    // already, not to be used until it is made, so that nothing under them moves then.
    const coming = Boolean(b.pending) && !b.failed && !links.length && listOf(shelf.fileLabels).length > 0;
    const soon = (label) => {
      const go = el("button", "btn small", label);
      go.type = "button";
      go.disabled = true;
      go.title = "Its files come once it is made.";
      return go;
    };
    const parts = links.length ? links : coming ? listOf(shelf.fileLabels).map((label) => soon(String(label)))
      : [el("p", "hint", b.failed ? "Not made: Select can make it again." : b.pending ? "Its files come once it is made."
        : "Not made yet: caracole render, or caracole songbook render, makes its files.")];
    if (b.failed && !links.length) {
      const name = b.name;
      parts.push(button("Forget it", "btn small book-forget", () => {
        letGo(name);
        const li = Array.from(lines.children).find((x) => x.dataset.book === name);
        if (li) li.remove();  // gone at your tap: nothing says so where it was
        if (state.book === name) {
          state.book = "";
          save();
        }
        draw();
        const line = lines.querySelector("button.book-line");
        (line || newBook).focus({ preventScroll: true });
      }, "Forget " + name + ": take it off the page"));
    }
    const toGet = listOf(b.set).filter((e) => e && (coming ? e.pending && gettable(e.id) : e.get)).length;
    const was = row.querySelector("form.get-missing");
    if (!toGet && was && !gone.has(was)) {  // nothing left to get: its room kept until your next click or key
      was.classList.add("spent");
      for (const control of was.querySelectorAll("button")) control.disabled = true;
      gone.add(was);
    }
    if (was && gone.has(was)) parts.push(was);
    if (toGet && server && !readOnly) {
      const label = toGet === 1 ? "Get the missing song now" : "Get the " + toGet + " missing songs now";
      if (coming) {
        const box = el("div", "get-missing");  // as the form will hold it
        box.appendChild(soon(label));
        parts.push(box);
      } else {
        const form = el("form", "get-missing");
        form.method = "post";
        form.setAttribute("action", "/songbook/get");
        const go = el("button", "btn small", label);
        go.type = "submit";
        go.title = "Looks each one up now, as caracole get does, then makes the songbook again";
        form.appendChild(go);
        parts.push(form);
      }
    }
    row.replaceChildren(...parts);
  };
  const moreForms = (name) => {
    const more = el("details", "book-more");
    more.appendChild(el("summary", null, "Rename or delete"));
    const rename = el("form", "book-rename");
    rename.method = "post";
    rename.setAttribute("action", "/songbook/rename");
    const label = el("label", "f", "New name");
    const input = el("input");
    input.name = "new";
    input.required = true;
    input.maxLength = 80;
    input.autocomplete = "off";
    input.value = name;
    label.appendChild(input);
    const go = el("button", "btn small", "Rename");
    go.type = "submit";
    rename.append(label, go);
    const del = el("form", "book-delete");
    del.method = "post";
    del.setAttribute("action", "/songbook/delete");
    const sure = el("label", "sb-sure");
    const box = el("input");
    box.type = "checkbox";
    box.required = true;
    sure.append(box, document.createTextNode(" Delete it, and the files caracole made of it"));
    const drop = el("button", "btn small", "Delete " + name);
    drop.type = "submit";
    del.append(sure, drop);
    more.append(rename, del);
    return more;
  };
  const openBook = (name, focus) => {
    sweep();
    state.book = name;
    save();
    draw();
    if (focus && book) {
      const heading = book.querySelector("h2");
      heading.focus({ preventScroll: true });
      if (!wide.matches) panel.scrollIntoView({ block: "start" });
    }
  };
  const draw = () => {
    drawList();
    const name = openName();
    const b = books().find((x) => x.name === name) || null;
    const readOnly = !server;
    inner.classList.toggle("has-book", Boolean(b) && Boolean(state.book || wide.matches));
    if (!b) {
      if (book && !gone.has(book)) book.remove();
      if (book && !book.isConnected) book = null;
      return;
    }
    if (book && bookName !== b.name && !gone.has(book)) {
      book.remove();
      book = null;
    }
    if (!book || !book.isConnected) {
      book = el("article", "book" + (readOnly ? " read-only" : ""));
      book.setAttribute("aria-labelledby", "book-title");
      const back = button("‹ Songbooks", "btn small book-back", () => {
        const was = state.book;
        state.book = "";
        save();
        draw();
        const line = lines.querySelector('.book-line[data-book="' + CSS.escape(was) + '"]');
        if (line) line.focus({ preventScroll: true });
      });
      const head = el("header", "book-head");
      const h2 = el("h2");
      h2.id = "book-title";
      h2.tabIndex = -1;
      head.append(h2, el("p", "book-meta"));
      status = el("p", "progress book-status");
      status.setAttribute("role", "status");
      const files = el("div", "book-files actions");
      const set = el("ol", "set");
      set.setAttribute("aria-label", "Its songs, in order");
      book.append(back, head, status, files, set, said);
      if (readOnly) book.appendChild(fileCommands(b));
      else book.append(addSong(), moreForms(b.name));
      inner.appendChild(book);
      bookName = b.name;
      const view = newest.get(b.name);
      if (view) showLine(status, view);
      lockBook(locked(b.name));
    }
    bookName = b.name;
    book.dataset.songbook = b.name;
    showTitle(b.name);
    book.querySelector(".book-meta").textContent = metaOf(b)
      .replace(/ · changed .*| · not made yet| · on its way| · couldn't be made/, "");
    drawFiles(b, readOnly);
    if (!moving) drawSet(b, readOnly);
    const adder = book.querySelector(".add-song");
    if (adder) adder.hidden = Boolean(b.failed);
    if (b.failed) lockBook(true);
    const rename = book.querySelector(".book-rename input[name=new]");
    if (rename && document.activeElement !== rename) rename.value = b.name;
    const del = book.querySelector(".book-delete button");
    if (del) del.textContent = "Delete " + b.name;
    for (const out of book.querySelectorAll(".set-out")) {
      const h3 = out.closest(".set-line").querySelector("h3");
      out.setAttribute("aria-label", "Take " + (h3 ? h3.textContent : "it") + " out of " + b.name);
    }
  };
  const showTitle = (name) => {
    const h2 = book && book.querySelector("h2");
    const title = renaming.get(name) || name;
    if (h2 && h2.textContent !== title) h2.textContent = title;
  };
  // A rename or a deletion waits: the songbook's controls wait with it (a form sent meanwhile would name it wrong).
  const busyFor = (name) => Array.from(changes.values()).some((v) => isActive(v) && namesOf(v).indexOf(name) >= 0 &&
    v.songbook && (v.songbook.action === "rename" || v.songbook.action === "delete"));
  const locked = (name) => busyFor(name) || unmade.has(name);  // or never made: nothing in it to change
  // A songbook whose make failed, off the page: made again, or forgotten (its Forget it).
  const letGo = (name) => {
    if (!unmade.delete(name)) return;
    shelf = Object.assign({}, shelf, { books: books().filter((x) => x.name !== name) });
    if (book && bookName === name) {
      book.remove();
      book = null;
    }
  };

  // --- the songbook's changes -------------------------------------------------------------------------------------
  // A change posted; ``spot``, a line it shows on as well (a set list's song, an Add a song result).
  const change = (path, body, spot, lookups) => {
    const name = bookName;
    if (status) showLine(status, { line: { tone: "queued", text: "Sending…" } });
    if (spot) showLine(lineIn(spot), { line: { tone: "queued", text: "Sending…" } });
    return postTo(path, body).then((reply) => {
      const view = reply.ok && reply.body && reply.body.job;
      if (!view || typeof view !== "object") {
        if (status && bookName === name) showLine(status, failed(failure(reply)));
        if (spot) showLine(lineIn(spot), failed(failure(reply)));
        return null;
      }
      follow(view);
      for (const each of listOf(reply.body.jobs)) {  // its lookups: each on its song's line, not in the corner's list
        if (!each || typeof each !== "object") continue;
        if (lookups) lookups(each);
        if (lib) lib.track(each, { quiet: true });
      }
      return view;
    }, () => {
      if (status && bookName === name) showLine(status, failed(UNREACHABLE));
      if (spot) showLine(lineIn(spot), failed(UNREACHABLE));
      return null;
    });
  };
  const follow = (view) => {
    changes.set(Number(view.id), view);
    for (const n of namesOf(view)) if (n) newest.set(n, view);
    if (lib) lib.track(view);
    shown(view);
  };
  const shown = (view) => {
    if (view.kind === "songbook") {
      changes.set(Number(view.id), view);
      const names = namesOf(view);
      for (const n of names) if (n) newest.set(n, view);
      if (book && status && names.indexOf(bookName) >= 0) showLine(status, view);
      if (book && names.indexOf(bookName) >= 0) lockBook(locked(bookName));
      const spot = placed.get(Number(view.id));
      // A song new to the library has its lookup's line there until that is over, then the songbook's change's.
      const lookup = spot ? lookupViews.get(Number(spot.dataset.lookup)) : null;
      const looking = lookup && (lookup.state === "queued" || lookup.state === "running");
      if (spot && spot.isConnected && !looking) showLine(lineIn(spot), view);
    } else if (view.kind === "song") {
      const spot = placed.get(Number(view.id));
      if (spot) {  // a song added here: its line, even before the lookup has found the song (no songId yet)
        spot.dataset.lookup = String(Number(view.id));
        lookupViews.set(Number(view.id), view);
      }
      if (view.songId !== null && view.songId !== undefined) {
        songViews.set(Number(view.songId), view);
        if (book) for (const li of songLines(book, view)) showLine(lineIn(li), view);
      }
      if (spot && spot.isConnected) showLine(lineIn(spot), view);
    }
  };
  document.addEventListener("caracole:job", (e) => {
    const view = e.detail;
    if (view && typeof view === "object") shown(view);
  });
  // A song gone from the library, removed on the page or elsewhere (library.js): Add a song offers it no more, as its
  // id may come back with the next song added (songs.id has no AUTOINCREMENT).
  document.addEventListener("caracole:gone", (e) => {
    const s = songs.find((x) => x && Number(x.id) === Number(e.detail && e.detail.id));
    if (s) s.status = "removed";
  });
  document.addEventListener("caracole:songbooks", (e) => {
    const detail = e.detail && typeof e.detail === "object" ? e.detail : {};
    const before = books();
    shelf = shelfOf(detail.songbooks);
    const view = detail.view && typeof detail.view === "object" ? detail.view : null;
    const [was, after] = view ? namesOf(view) : ["", ""];
    if (view && view.songbook && view.songbook.action === "rename" && !isActive(view)) renaming.delete(was);
    if (view && view.state === "failed" && view.songbook && view.songbook.action === "make") {
      const b = before.find((x) => x.name === was && x.pending);
      if (b && !books().some((x) => x.name === was)) {  // never made, not deleted; the Select bar gets its ticks back
        unmade.set(was, Object.assign(b, { failed: true }));
        const why = String(view.line && view.line.text || "");
        document.dispatchEvent(new CustomEvent("caracole:unmade", { detail: {
          name: was, songs: listOf(b.set).map((x) => x && x.id).filter((id) => id !== null && id !== undefined),
          error: "“" + was + "” wasn't made" + (why ? ": " + why : ".") } }));
      }
    }
    shelf = withUnmade(shelf);
    if (view && view.state === "done" && view.songbook) {
      if (view.songbook.action === "rename") {  // its line in the list, where it was, under its new name
        const li = Array.from(lines.children).find((x) => x.dataset.book === was);
        if (li) li.dataset.book = after;
      }
      if (view.songbook.action === "rename" && bookName === was) {  // the songbook open, under its new name
        if (state.book === was) {
          state.book = after;
          save();
        }
        bookName = after;
      }
      if (view.songbook.action === "delete" && bookName === was && book) {  // says Deleted where it was
        state.book = "";
        save();
        // As tall as it was, its way back's room kept: nothing on the screen moves until your next click or key.
        const tall = book.getBoundingClientRect().height;
        if (tall) book.style.minHeight = tall + "px";
        const back = book.querySelector(".book-back");
        if (back) back.style.visibility = "hidden";
        for (const part of book.querySelectorAll(".book-files, .set, .add-song, .book-more")) part.remove();
        if (status) showLine(status, view);
        book.classList.add("gone");
        gone.add(book);
        book = null;
        drawList();
        return;
      }
    }
    if (book && view && busyBook(bookName, view.id)) {  // another change of it still on its way: once it is over
      drawList();
      return;
    }
    draw();
  });

  // Each song's controls.
  const takeOut = (li, e) => {
    li.classList.add("leaving");
    change("/songbook/remove", fields(bookName, { song: e.entry })).then((view) => {
      if (!view) li.classList.remove("leaving");
    });
  };
  const getOne = (li, e) => {
    const go = li.querySelector(".set-get");
    if (go) go.disabled = true;
    change("/songbook/get", fields(bookName, { song: e.id }), li, null).then((view) => {
      if (!view && go) go.disabled = false;
    });
  };
  const edit = (li, e) => {
    const open = li.querySelector(":scope > .set-edit");
    const chip = li.querySelector(".plays");
    if (open) {
      open.remove();
      li.classList.remove("editing");
      if (chip) chip.setAttribute("aria-expanded", "false");
      return;
    }
    const form = el("form", "set-edit");
    form.method = "post";
    form.setAttribute("action", "/songbook/set");
    editSerial.n += 1;
    form.id = "set-edit-" + editSerial.n;
    const at = e.at && typeof e.at === "object" ? e.at : {};
    const menu = (label, name, options, chosen, off) => {
      const box = el("label", "f", label);
      const select = el("select");
      select.name = name;
      for (const [value, text] of options) select.appendChild(new Option(text, value));
      select.value = chosen;
      select.disabled = Boolean(off);
      box.appendChild(select);
      form.appendChild(box);
    };
    const keyless = at.tonic === null || at.tonic === undefined;
    menu("Key", "key", keys.map((k) => [String(k), String(k)]), keyless ? "" : String(keys[Number(at.tonic)] || ""),
      keyless);
    menu("Mode", "mode", modes.map((m) => [String(m[0]), String(m[1])]), String(at.mode || ""), keyless);
    const capos = [["0", "No capo"]];
    for (let n = 1; n <= capoMax; n += 1) capos.push([String(n), "Capo " + n]);
    const playsOn = String(at.inst || "guitar");  // the instrument it is played on now
    menu("Capo", "capo", capos, String(Number(at.capo) || 0), !takesCapo(playsOn));
    const keySelect = form.querySelector("select[name=key]");
    const capoSelect = form.querySelector("select[name=capo]");
    if (instruments.length > 1) {
      menu("Instrument", "instrument", instruments.map((i) => [String(i[0]), String(i[1])]), playsOn, false);
      // Another instrument: one with no capo plays the key the song sounds in, its capo menu off; back on one that
      // takes a capo, the key and the capo it plays at now (those it sounds in, from an instrument that takes none)
      form.querySelector("select[name=instrument]").addEventListener("change", (ev) => {
        const chosen = ev.currentTarget.value;
        const fromShapes = takesCapo(chosen) && takesCapo(playsOn);
        if (!keyless) keySelect.value = String(keys[Number(fromShapes ? at.tonic : at.sounds)] || keySelect.value);
        capoSelect.value = fromShapes ? String(Number(at.capo) || 0) : "0";
        capoSelect.disabled = !takesCapo(chosen);
      });
    }
    const actions = el("div", "actions");
    const go = el("button", "btn small primary", "Play it here");
    go.type = "submit";
    actions.appendChild(go);
    if (!e.own) {
      actions.appendChild(button("Its own version", "btn small as-own", () => {
        close();
        if (chip) chip.focus();
        change("/songbook/set", fields(bookName, { song: e.entry, clear: "1" }));
      }, "Play " + e.title + " in its own version here"));
    }
    actions.appendChild(button("Cancel", "btn small edit-cancel", () => {
      close();
      if (chip) chip.focus();
    }));
    form.appendChild(actions);
    if (keyless) form.appendChild(el("p", "hint", "No key caracole can read in its sheet: its capo alone."));
    const close = () => {
      form.remove();
      li.classList.remove("editing");
      if (chip) chip.setAttribute("aria-expanded", "false");
    };
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const body = fields(bookName, { song: e.entry });
      for (const [k, v] of new FormData(form).entries()) body.set(k, String(v));
      if (body.get("instrument") === playsOn) body.delete("instrument");  // an instrument only once it changes
      close();
      if (chip) chip.focus();
      change("/songbook/set", body);
    });
    li.classList.add("editing");
    const progress = li.querySelector(":scope > .progress");
    li.insertBefore(form, progress);
    if (chip) {
      chip.setAttribute("aria-expanded", "true");
      chip.setAttribute("aria-controls", form.id);
    }
    form.querySelector("select:not(:disabled)").focus();
  };

  // The forms of the songbook (Get the missing songs now, Rename, Delete) and the Select bar's Make songbook (or Add
  // to), once select.js has checked it: posted here, they leave you where you are; the Select bar's lands here.
  const FORM = /^\/songbook\/(make|add|get|rename|delete)$/;
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (e.defaultPrevented || !(form instanceof HTMLFormElement) || !server) return;
    const action = form.getAttribute("action") || "";
    if (!FORM.test(action)) return;
    const bar = form.closest(".pickbar");
    if (!bar && !panel.contains(form)) return;
    e.preventDefault();
    if (bar) {
      fromSelect(form, action);
      return;
    }
    const body = fields(bookName, Object.fromEntries(new FormData(form).entries()));
    const renamed = /\/rename$/.test(action) ? bookName : null;
    if (renamed !== null) {  // its new name as caracole keeps it (songbook.check_name), at once
      renaming.set(renamed, String(body.get("new") || "").normalize("NFC").split(/\s+/).filter(Boolean).join(" ") ||
        renamed);
      showTitle(renamed);
    }
    if (/\/get$/.test(action)) {
      for (const li of book.querySelectorAll(".set-line")) {
        const entry = listOf((books().find((b) => b.name === bookName) || {}).set)
          .find((x) => x && String(x.entry) === li.dataset.entry);
        if (entry && entry.get) showLine(lineIn(li), { line: { tone: "queued", text: "Sending…" } });
      }
    }
    for (const control of form.querySelectorAll("button")) control.disabled = true;
    change(action, body).then((view) => {
      for (const control of form.querySelectorAll("button")) control.disabled = false;
      if (!view && renamed !== null && renaming.delete(renamed) && bookName === renamed) showTitle(renamed);  // refused
      if (view && /\/delete$/.test(action)) lockBook(true);
    });
  });
  const fromSelect = (form, action) => {
    const name = String(form.elements.namedItem("name").value);
    const ids = String(form.elements.namedItem("songs").value).split(",").filter(Boolean).map(Number);
    postTo(action, new URLSearchParams(new FormData(form))).then((reply) => {
      const view = reply.ok && reply.body && reply.body.job;
      form.dispatchEvent(new CustomEvent("caracole:sent", {
        detail: { ok: Boolean(view && view.songbook), error: view ? "" : failure(reply) } }));
      if (!view || !view.songbook) return;
      const after = String(view.songbook.after || name);
      // One whose make failed, made again (under its name, or with the picks it gave back under another): off the
      // page, its article too; the one sent comes as new, its line where that one's was.
      const sent = ids.join(",");
      for (const [was, b] of Array.from(unmade)) {
        if (was !== after && !(sent && listOf(b.set).map((x) => Number(x && x.id)).join(",") === sent)) continue;
        const li = Array.from(lines.children).find((x) => x.dataset.book === was);
        if (li && !books().some((x) => x.name === after)) li.dataset.book = after;
        letGo(was);
      }
      // Until it is done, the songbook as it will be: its songs as the library names them, at its end.
      let b = books().find((x) => x.name === after);
      if (!b) {
        b = { name: after, songs: 0, missing: 0, files: [], set: [], pending: true };
        shelf = Object.assign({}, shelf, { books: books().concat([b]) });
      }
      const set = listOf(b.set).slice();
      for (const id of ids) {
        const s = songs.find((x) => Number(x.id) === id);
        if (!s || set.some((x) => Number(x.id) === id)) continue;
        set.push({ n: set.length + 1, entry: String(s.display), key: String(s.identity || ""), title: s.title,
                   artist: s.artist, id, pending: true });
      }
      Object.assign(b, { set, songs: set.length });
      showTab("songbooks");
      openBook(after, true);
      follow(view);
    }, () => form.dispatchEvent(new CustomEvent("caracole:sent", { detail: { ok: false, error: UNREACHABLE } })));
  };

  // --- moving a song: a drag on its grip, or ↑ and ↓ ------------------------------------------------------------
  // A drag moves the line with the pointer, and the lines it passes make room, as transforms (nothing on the page
  // is laid out again until you let go); let go, the line takes its place and its move is sent. ↑ and ↓ move it at
  // once, and the move is sent a moment after the last key, so that ↑ ↑ ↑ is one move.
  const places = () => Array.from(book.querySelectorAll(".set > .set-line:not(.gone)"));
  // Until the server has it, the set list isn't drawn again either: an older change's songbooks would put the line
  // back where it was, for a moment. Refused, it is drawn as the songbook is.
  const sendMove = (li, from) => {
    const to = places().indexOf(li);
    if (to < 0 || to === from) return;
    moving += 1;
    change("/songbook/move", fields(bookName, { song: li.dataset.entry, position: to + 1 })).then((view) => {
      moving -= 1;
      if (!view) draw();
    });
  };
  const smooth = !(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  panel.addEventListener("pointerdown", (e) => {
    const grip = e.target instanceof Element ? e.target.closest(".grip") : null;
    if (!grip || grip.disabled || e.button !== 0 || !book) return;
    const li = grip.closest(".set-line");
    e.preventDefault();
    grip.focus({ preventScroll: true });
    grip.setPointerCapture(e.pointerId);
    const others = places();
    const from = others.indexOf(li);
    const boxes = others.map((x) => x.getBoundingClientRect());
    const tall = boxes[from].height;
    const middles = boxes.map((r) => r.top + r.height / 2);
    const startY = e.clientY;
    let to = from;
    moving += 1;
    li.classList.add("dragging");
    const move = (ev) => {
      const dy = ev.clientY - startY;
      li.style.transform = "translateY(" + dy + "px)";
      const centre = middles[from] + dy;
      to = from;
      while (to < others.length - 1 && centre > middles[to + 1]) to += 1;
      while (to > 0 && centre < middles[to - 1]) to -= 1;
      others.forEach((x, i) => {
        if (x === li) return;
        const shift = i > from && i <= to ? -tall : i < from && i >= to ? tall : 0;
        x.style.transform = shift ? "translateY(" + shift + "px)" : "";
        x.classList.toggle("making-room", smooth);
      });
    };
    // pointerup drops the line where it is; pointercancel (the browser taking the gesture) puts it back and sends nothing.
    const finish = (cancelled) => {
      grip.removeEventListener("pointermove", move);
      grip.removeEventListener("pointerup", end);
      grip.removeEventListener("pointercancel", cancel);
      if (cancelled) to = from;
      for (const x of others) {
        x.style.transform = "";
        x.classList.remove("making-room");
      }
      li.classList.remove("dragging");
      if (to !== from) {
        const list = li.parentNode;
        const anchor = others[to];
        list.insertBefore(li, to > from ? anchor.nextSibling : anchor);
        renumber();
        said.textContent = (li.querySelector("h3") || {}).textContent + ": " + (to + 1) + " of " + others.length;
      }
      moving -= 1;
      if (!cancelled) sendMove(li, from);
    };
    const end = () => finish(false);
    const cancel = () => finish(true);
    grip.addEventListener("pointermove", move);
    grip.addEventListener("pointerup", end);
    grip.addEventListener("pointercancel", cancel);
  });
  const keyMoves = new Map();  // a line moved with ↑ and ↓ -> {from, timer}
  panel.addEventListener("keydown", (e) => {
    const grip = e.target instanceof Element ? e.target.closest(".grip") : null;
    if (!grip || (e.key !== "ArrowUp" && e.key !== "ArrowDown") || !book) return;
    e.preventDefault();
    const li = grip.closest(".set-line");
    const all = places();
    const at = all.indexOf(li);
    const to = e.key === "ArrowUp" ? at - 1 : at + 1;
    if (at < 0 || to < 0 || to >= all.length) return;
    const pending = keyMoves.get(li) || { from: at, timer: 0 };
    if (!pending.timer) moving += 1;
    clearTimeout(pending.timer);
    li.parentNode.insertBefore(li, e.key === "ArrowUp" ? all[to] : all[to].nextSibling);
    grip.focus({ preventScroll: true });
    renumber();
    said.textContent = (li.querySelector("h3") || {}).textContent + ": " + (to + 1) + " of " + all.length;
    pending.timer = setTimeout(() => {
      keyMoves.delete(li);
      moving -= 1;
      sendMove(li, pending.from);
    }, 700);
    keyMoves.set(li, pending);
  });

  // --- Add a song: your songs and the indexes', as you type -------------------------------------------------------
  const fold = lib ? lib.fold : (text) => String(text).toLowerCase();  // the library's search's, as it reads songs
  const words = (text) => fold(text).split(/\s+/).map((w) => w.replace(/['’‘`´ʼ]/g, "")
    .replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "")).filter(Boolean);
  const HAN = /\p{Script=Han}/u;
  const enough = (text) => (String(text).match(/[\p{L}\p{N}]/gu) || []).length >= (HAN.test(text) ? 2 : 3);
  const SEARCH_PAUSE = 250;
  // Add a song's id, sent with each search: one typed on stops this box's older ones alone (web/search_routes.py).
  const SEARCH_BOX = Math.random().toString(36).slice(2, 12) || "songbook";
  function addSong() {
    const box = el("div", "add-song");
    const label = el("label", "add-label", "Add a song");
    const field = el("div", "field");
    const input = el("input");
    input.type = "search";
    input.id = "add-q";
    label.htmlFor = input.id;
    input.placeholder = "Your songs, or any song the indexes have";
    input.autocomplete = "off";
    input.setAttribute("autocapitalize", "off");
    input.setAttribute("autocorrect", "off");
    input.spellcheck = false;
    input.setAttribute("enterkeyhint", "search");
    field.appendChild(input);
    const note = el("p", "bar-status add-status");
    note.setAttribute("aria-live", "polite");
    const found = el("div", "lines add-results");
    found.hidden = true;
    box.append(label, field, note, found);
    let timer = 0;
    let asking = null;
    let asked = 0;
    let answer = null;  // the newest answer of the server's, for its query
    const inBook = (key, id) => {
      const b = books().find((x) => x.name === bookName);
      return listOf(b && b.set).some((x) => x && ((id !== null && id !== undefined && Number(x.id) === Number(id)) ||
        (key && String(x.key) === key)));
    };
    const line = (hit) => {
      const has = inBook(hit.key, hit.id);
      const go = button(has ? "In it" : "Add", "btn small" + (has ? "" : " primary"), null,
        has ? hit.title + " is in " + bookName + " already" : "Add " + hit.title + " by " + hit.artist + " to " + bookName);
      go.disabled = has;
      const row = rows ? rows.resultRow({ dense: true, title: hit.title, artist: hit.artist, sources: hit.sources,
        facts: hit.facts, badges: hit.id !== null && hit.id !== undefined ? [{ kind: "found", text: "Yours" }] : [],
        action: go }) : el("article", "line", hit.title);
      go.addEventListener("click", () => add(hit, row, go));
      return row;
    };
    const show = (q) => {
      const typed = words(q);
      const hits = [];
      const seen = new Set();
      const push = (hit) => {
        const key = hit.id !== null && hit.id !== undefined ? "id:" + hit.id : "key:" + hit.key;
        if (seen.has(key) || (hit.key && seen.has("key:" + hit.key))) return;
        seen.add(key);
        if (hit.key) seen.add("key:" + hit.key);
        hits.push(hit);
      };
      if (typed.length) {  // yours, as the library's own search reads them
        for (const s of songs) {
          if (s.status === "removed" || !typed.every((w) => String(s.search || "").indexOf(w) >= 0)) continue;
          push({ id: s.id, key: String(s.identity || ""), title: s.title, artist: s.artist, sources: [s.source] });
          if (hits.length >= 5) break;
        }
      }
      const a = answer && answer.q === q ? answer.data : null;
      if (a) {
        for (const s of listOf(a.library)) {
          if (s && typeof s === "object") push({ id: s.id, key: "", title: s.title, artist: s.artist, sources: [s.source] });
        }
        const keyOf = (r) => String(r.artist_key || "") + "/" + String(r.title_key || "");
        for (const r of listOf(a.index)) {
          if (!r || typeof r !== "object") continue;
          const mine = r.library && typeof r.library === "object" ? r.library : null;
          push(mine ? { id: mine.id, key: keyOf(r), title: mine.title, artist: mine.artist, sources: ["ug"] }
            : { key: keyOf(r), title: r.title, artist: r.artist, sources: ["ug"], pick: { ug: r.ug },
                facts: Object.entries(r.counts && typeof r.counts === "object" ? r.counts : {})
                  .map(([k, n]) => k + " ×" + n).join(" · ") });
        }
        for (const [site, rows_] of [["lacuerda", a.lacuerda], ["gtptabs", a.gtptabs]]) {
          for (const r of listOf(rows_)) {
            if (!r || typeof r !== "object") continue;
            const mine = r.library && typeof r.library === "object" ? r.library : null;
            const chords = site === "lacuerda" && /^https:[/][/]/i.test(String(r.sheet || "")) &&
              /^https:[/][/]/i.test(String(r.url || ""));
            push(mine ? { id: mine.id, key: keyOf(r), title: mine.title, artist: mine.artist, sources: [site] }
              : { key: keyOf(r), title: r.title, artist: r.artist, sources: [site],
                  pick: chords ? { lacuerda: r.url } : {} });
          }
        }
      }
      found.replaceChildren(...hits.slice(0, 8).map(line));
      found.hidden = !hits.length;
      note.textContent = !q.trim() ? "" : hits.length ? ""
        : server && enough(q) && !a ? "Searching your songs and the indexes…" : "Nothing found yet.";
    };
    const ask = (q) => {
      clearTimeout(timer);
      if (asking) asking.abort();
      asked += 1;
      const mine = asked;
      if (!enough(q)) return;
      timer = setTimeout(() => {
        asking = new AbortController();
        fetch("api/search?q=" + encodeURIComponent(q.trim()) + "&box=" + SEARCH_BOX, {
          signal: asking.signal, cache: "no-store", headers: { Accept: "application/json" },
        }).then((r) => r.json().catch(() => null)).then((body) => {
          if (mine !== asked || !body || typeof body !== "object") return;
          if (body.superseded) {
            ask(q);
            return;
          }
          answer = { q, data: body };
          show(q);
        }, () => {});
      }, SEARCH_PAUSE);
    };
    input.addEventListener("input", () => {
      show(input.value);
      ask(input.value);
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "/") e.stopPropagation();  // a title may hold one: the library's own key is for its search
      if (e.key === "Enter") e.preventDefault();  // Enter spends nothing: Add does
    });
    // A song added: at once a line of its own at the set list's end, which its lookup and the songbook's change say
    // how they go on; the set list draws it again as the songbook has it once it is done.
    const add = (hit, row, go) => {
      go.disabled = true;
      const list = book.querySelector(".set");
      const entry = { n: places().length + 1, entry: hit.artist + " - " + hit.title, key: hit.key, title: hit.title,
                      artist: hit.artist, id: hit.id, pending: true };
      const spot = setLine(entry, entry.n, false);
      showLine(lineIn(spot), { line: { tone: "queued", text: "Sending…" } });  // its height, from the tap
      list.appendChild(spot);
      renumber();
      const pick = hit.id !== null && hit.id !== undefined ? { song: hit.id }
        : Object.assign({ artist: hit.artist, title: hit.title }, hit.pick || {});
      change("/songbook/add-song", fields(bookName, pick), row, (lookup) => placed.set(Number(lookup.id), spot))
        .then((view) => {
          if (!view) {
            spot.remove();
            renumber();
            go.disabled = false;
            return;
          }
          placed.set(Number(view.id), spot);
          go.textContent = "In it";
        });
    };
    return box;
  }

  // --- the jobs on their way when the page loaded, and the first drawing --------------------------------------------
  for (const view of listOf(server && server.jobs)) {
    if (!view || typeof view !== "object") continue;
    if (view.kind === "songbook") {
      changes.set(Number(view.id), view);
      for (const n of namesOf(view)) if (n) newest.set(n, view);
    } else if (view.kind === "song" && view.songId !== null && view.songId !== undefined) {
      songViews.set(Number(view.songId), view);
    }
  }
  if (wide.addEventListener) wide.addEventListener("change", draw);
  draw();
  showTab(state.tab);
})();
