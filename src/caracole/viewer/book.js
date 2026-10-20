(() => {
  "use strict";
  // songbook.html, before the sheet viewer's script: the contents, or one song for the viewer.
  const doc = document.documentElement;
  const sections = Array.from(document.querySelectorAll("section.song"));
  const toc = document.getElementById("contents");
  // The viewer keeps a page's settings under this name; each song's are kept here, and swapped in.
  const VIEWER = "caracole-viewer:" + location.pathname;
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
  // The settings the viewer saved for the song open last, into that song's own place.
  const harvest = () => {
    if (typeof book.at !== "string") return;
    try {
      const mine = localStorage.getItem(VIEWER);
      if (mine !== null) book.songs[book.at] = mine;
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
        history.replaceState(null, "", "#song-" + current.dataset.n);
      } catch (err) { /* an address the page can't change */ }
    }
  }
  harvest();

  if (current) {
    const n = current.dataset.n;
    doc.dataset.view = "song";
    toc.hidden = true;
    for (const s of sections) s.hidden = s !== current;
    // The names the viewer looks for.
    for (const [from, to] of [["facts-", "facts"], ["strip-", "strip"], ["sheet-", "sheet"], ["data-", "song"]]) {
      const el = document.getElementById(from + n);
      if (el) el.id = to;
    }
    const data = document.getElementById("song");
    try {
      const song = JSON.parse(data.textContent);
      song.voicings = JSON.parse(document.getElementById("voicings").textContent);
      data.textContent = JSON.stringify(song);
    } catch (err) { /* the viewer says so */ }
    const title = current.querySelector("h2.title");
    const name = document.querySelector(".book-head h1");
    if (title && name) document.title = title.textContent + " · " + name.textContent;
    const returning = book.at === current.dataset.id;
    try {
      const mine = book.songs[current.dataset.id];
      if (typeof mine === "string") localStorage.setItem(VIEWER, mine);
      else localStorage.removeItem(VIEWER);
    } catch (err) { /* no storage */ }
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
    harvest();
    if (current) book.y = Math.round(window.scrollY);
    keep();
  };
  // Each step loads the page again, so the viewer starts afresh on the song it shows.
  window.addEventListener("hashchange", () => {
    save();
    location.reload();
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
  const busy = () => ["panel", "card"].some((id) => {
    const el = document.getElementById(id);
    return el && !el.hidden;
  });
  // A swipe across the sheet: left for the next song, right for the one before.
  let start = null;
  document.addEventListener("touchstart", (e) => {
    const target = e.target instanceof Element ? e.target : null;
    start = e.touches.length === 1 && !busy() && !(target && target.closest(".tab, .strip, .sheet-ui, .pill, input"))
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
