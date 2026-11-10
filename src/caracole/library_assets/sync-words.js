// The sync's words (sync.js reads them, on the computer's page and the phone's alike): how two versions of a unit
// differ, each change, each side's name, the numbers and the dates, exactly as the sheet draws them
// (docs/superpowers/plans/2026-11-03-sync-redesign.md §3.7). It builds no element and asks nothing of anyone: every
// answer is text, which sync.js puts in with textContent.
//
// ``differ(kind, here, there)``: a unit's two documents (GET /api/sync/unit's ``here`` and ``there``, each
// peer_sync.unit_document's ``unit``, or null where a side hasn't got it), told apart aspect by aspect, a line each
// that the two hold differently: ``{what, here, there}``, each value text, "–" for none. A song's own key (its
// ``[version]``), its sheet (the version of the lowest pick rank, its site named as the page's ``icons`` name it), its
// versions, its kept files, its lyrics, its status, its album, length and variant, and any other override; a
// songbook's set list, the songs one has and the other lacks, its order and a song's setting; a removal, an artist's
// slugs or UG page, a blocked tab, by their values. ``changed(change, side)``: "added on the phone".
// ``sides(device, peer)``: this device's and the other side's names, as headings, as places and in sentences, and
// their icons. ``tabs(n, signed)``: 1,503,236 and +12,130 (a minus sign for a fall), digits grouped by hand, no locale.
// ``day(stamp)`` and ``when(stamp)``: dd/mm/yy and dd/mm/yy, HH:MM, in this device's time.
(() => {
  "use strict";
  const NONE = "–";
  const MINUS = "−";
  const own = Object.prototype.hasOwnProperty;
  const listOf = (v) => (Array.isArray(v) ? v : []);
  const objOf = (v) => (v && typeof v === "object" && !Array.isArray(v) ? v : null);
  const text = (v) => (v === null || v === undefined ? "" : String(v));
  const same = (a, b) => JSON.stringify(a === undefined ? null : a) === JSON.stringify(b === undefined ? null : b);

  // --- numbers --------------------------------------------------------------------------------------------------
  const grouped = (n) => {
    const digits = String(Math.round(Math.abs(Number(n) || 0)));
    let out = "";
    for (let i = 0; i < digits.length; i += 1) {
      if (i && (digits.length - i) % 3 === 0) out += ",";
      out += digits[i];
    }
    return out;
  };
  // A count of tabs: as it is (1,503,236), or ``signed``, a change (+12,130, −210, 0).
  const tabs = (n, signed) => {
    const v = Math.round(Number(n) || 0);
    if (signed) return (v > 0 ? "+" : v < 0 ? MINUS : "") + grouped(v);
    return (v < 0 ? MINUS : "") + grouped(v);
  };
  // "1 song", "12 songs", "1,204 songs".
  const counted = (n, word, many) => {
    const v = Math.round(Number(n) || 0);
    return (v < 0 ? MINUS : "") + grouped(v) + " " + (v === 1 ? word : many || word + "s");
  };
  // A size in bytes, as a person reads it: 0.4 MB, 3.4 MB, 207 MB, 1.2 GB (a megabyte a million bytes).
  const size = (bytes) => {
    const b = typeof bytes === "number" ? bytes : NaN;
    if (!Number.isFinite(b) || b < 0) return "";
    const mb = b / 1e6;
    if (mb >= 999.5) return (mb / 1000).toFixed(1) + " GB";
    if (mb >= 9.95) return grouped(mb) + " MB";
    return Math.max(mb, 0.1).toFixed(1) + " MB";
  };

  // --- dates, in this device's time -----------------------------------------------------------------------------
  const pad = (n) => String(n).padStart(2, "0");
  const dateOf = (stamp) => {
    if (typeof stamp !== "string" || !stamp) return null;
    const at = new Date(stamp);
    return Number.isNaN(at.getTime()) ? null : at;
  };
  const day = (stamp) => {
    const at = dateOf(stamp);
    return at ? pad(at.getDate()) + "/" + pad(at.getMonth() + 1) + "/" + pad(at.getFullYear() % 100) : "";
  };
  const when = (stamp) => {
    const at = dateOf(stamp);
    return at ? day(stamp) + ", " + pad(at.getHours()) + ":" + pad(at.getMinutes()) : "";
  };
  // When a site was read, beside what waits: "today", "yesterday", else its day.
  const readOn = (stamp, now) => {
    const at = dateOf(stamp);
    if (!at) return "";
    const today = now instanceof Date ? now : new Date();
    const start = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const days = Math.round((start(today) - start(at)) / 86400000);
    return days === 0 ? "today" : days === 1 ? "yesterday" : day(stamp);
  };

  // --- the two sides --------------------------------------------------------------------------------------------
  // Each side's ``name`` (its button, its icon's), ``on`` (its card's heading), ``the`` (in a sentence), ``whose``
  // and ``short`` (its version kept), and ``icon``; this device always ``here``.
  const side = (icon, name, on, the, short) => Object.freeze({ icon, name, on, the, whose: the + "'s", short });
  const sides = (device, peer) => {
    const p = objOf(peer) || {};
    const here = device === "phone" ? side("phone", "Phone", "On the phone", "the phone", "phone's")
      : side("tower", "This computer", "On this computer", "this computer", "this computer's");
    let there;
    if (p.kind === "file") {
      there = side("file", "File", "In the file", "the file", "file's");
    } else if (p.kind === "computer" || device === "phone") {
      there = side("tower", "Computer", "On the computer", "the computer", "computer's");
    } else {  // another caracole serve, by its library's name
      const name = text(p.name).trim() || text(p.address).trim() || "the other caracole";
      there = side("rack", name, "On " + name, name, name + "'s");
    }
    return Object.freeze({ here, there });
  };
  const CHANGED = { new: "added", changed: "changed", gone: "removed" };
  // What a side did to a unit since the two last agreed (peer_sync.change_of's), on that side.
  const changed = (change, where) => {
    if (!own.call(CHANGED, change)) return "";
    const at = typeof where === "string" ? where : text(where && where.the);
    return CHANGED[change] + " on " + at;
  };

  // --- a song's own key, as overrides.toml's [version] keeps it --------------------------------------------------
  const ACCIDENTAL = { "#": "♯", b: "♭", "♯": "♯", "♭": "♭", "": "" };
  const keyName = (key) => {
    const m = /^([A-Ga-g])([#b♯♭]?)(m?)$/.exec(key);
    return m ? m[1].toUpperCase() + ACCIDENTAL[m[2]] + (m[3] ? " minor" : " major") : key;
  };
  const ownKey = (entry) => {
    if (typeof entry !== "string" || !entry.trim()) return "as the sheet's";
    let fields;
    try {
      fields = new URLSearchParams(entry.replace(/^#/, ""));
    } catch (err) {
      return entry;
    }
    const said = [];
    const key = fields.get("key");
    const t = fields.get("t");
    const mode = fields.get("mode");
    if (key) {
      said.push(keyName(key) + (mode ? " (" + mode + ")" : ""));
    } else if (t !== null && /^-?\d+$/.test(t)) {
      const n = Number(t);
      said.push(n === 0 ? "the sheet's" : "the sheet's, " + Math.abs(n) + (n > 0 ? " up" : " down"));
      if (mode) said.push(mode);
    } else {
      return entry;
    }
    const capo = fields.get("capo");
    if (capo !== null && /^\d+$/.test(capo)) said.push("capo " + Number(capo));
    if (fields.get("alt")) said.push("some chords swapped");
    if (fields.get("at")) said.push("its own shapes");
    return said.join(", ");
  };

  // --- a song --------------------------------------------------------------------------------------------------
  let titles = null;  // each site's name, as the page's data has it (icons.py's): read once
  const titleOf = (provider) => {
    if (titles === null) {
      titles = {};
      try {
        const node = document.getElementById("songs");
        const icons = node ? objOf(JSON.parse(node.textContent).icons) : null;
        for (const [key, value] of Object.entries(icons || {})) {
          if (objOf(value) && typeof value.name === "string") titles[key] = value.name;
        }
      } catch (err) {
        titles = {};
      }
    }
    return own.call(titles, provider) ? titles[provider] : text(provider);
  };
  const versionsOf = (doc) => listOf(doc.versions).filter((v) => objOf(v));
  const sheetOf = (doc) => {
    const ranked = versionsOf(doc).filter((v) => typeof v.pick_rank === "number")
      .sort((a, b) => a.pick_rank - b.pick_rank);
    return ranked.length ? titleOf(ranked[0].provider) + " · tab " + text(ranked[0].tab_id) : NONE;
  };
  const filesOf = (doc) => {
    const names = new Set();
    for (const v of versionsOf(doc)) {
      for (const f of listOf(v.files)) if (objOf(f) && typeof f.name === "string") names.add(f.name);
    }
    return Array.from(names).sort();
  };
  const length = (ms) => {
    const n = Number(ms);
    if (ms === null || ms === undefined || !Number.isFinite(n) || n < 0) return NONE;
    const s = Math.round(n / 1000);
    return Math.floor(s / 60) + ":" + pad(s % 60);
  };
  const worded = (v) => text(v).replace(/_/g, " ") || NONE;
  const overrideOf = (value) => {
    if (value === undefined || value === null) return NONE;
    if (typeof value === "string") return value || "set";
    if (Array.isArray(value)) return value.map(text).join(", ") || "set";
    return "set";
  };
  const songAspects = (doc) => {
    const song = objOf(doc.song) || {};
    const names = objOf(doc.names) || {};
    const overrides = objOf(doc.overrides) || {};
    const files = filesOf(doc);
    const aspects = [
      ["Its own key", ownKey(overrides.version), overrides.version || null],
      ["Its sheet", sheetOf(doc)],
      ["Its versions", String(versionsOf(doc).length)],
      ["Its kept files", files.length ? files.join(", ") : NONE],
      ["Its lyrics", worded(song.lyrics_status)],
      ["Its status", worded(song.status) + (song.review ? ", in review" : "")],
      ["Its album", text(names.album) || NONE],
      ["Its length", length(names.duration_ms)],
      ["Its variant", text(names.variant) || NONE],
    ];
    return { aspects, overrides };
  };
  const songLines = (here, there) => {
    const a = songAspects(here);
    const b = songAspects(there);
    const lines = [];
    for (let i = 0; i < a.aspects.length; i += 1) {
      const [what, mine, mineKey] = a.aspects[i];
      const [, theirs, theirsKey] = b.aspects[i];
      const differs = mineKey !== undefined || theirsKey !== undefined ? !same(mineKey, theirsKey) : mine !== theirs;
      if (differs) lines.push({ what, here: mine, there: theirs });
    }
    const tables = Array.from(new Set(Object.keys(a.overrides).concat(Object.keys(b.overrides))))
      .filter((t) => t !== "version").sort();
    for (const table of tables) {
      if (!same(a.overrides[table], b.overrides[table])) {
        lines.push({ what: "An override: [" + table + "]", here: overrideOf(a.overrides[table]),
                     there: overrideOf(b.overrides[table]) });
      }
    }
    return lines;
  };

  // --- a songbook --------------------------------------------------------------------------------------------
  const entriesOf = (doc) => listOf(doc && doc.songs).filter((e) => Array.isArray(e) && typeof e[0] === "string")
    .map((e) => ({ text: e[0], parts: objOf(e[1]) || {} }));
  const settingOf = (parts) => {
    const said = [];
    if (parts.key !== undefined && parts.key !== null) said.push(text(parts.key) + (parts.mode ? " " + parts.mode : ""));
    else if (parts.mode) said.push(text(parts.mode));
    if (parts.capo !== undefined && parts.capo !== null) said.push("capo " + text(parts.capo));
    if (parts.instrument) said.push("on the " + text(parts.instrument));
    return said.join(", ") || "as its own";
  };
  const joined = (items) => (items.length ? items.join(", ") : NONE);
  // What one set list holds that another doesn't: the songs only one has, the order of those both have, a song's
  // setting changed (the entries of both, by their text).
  const setLists = (from, to) => {
    const a = entriesOf(from);
    const b = entriesOf(to);
    const inA = new Map(a.map((e) => [e.text, e]));
    const inB = new Map(b.map((e) => [e.text, e]));
    const onlyA = a.filter((e) => !inB.has(e.text)).map((e) => e.text);
    const onlyB = b.filter((e) => !inA.has(e.text)).map((e) => e.text);
    const bothA = a.filter((e) => inB.has(e.text)).map((e) => e.text);
    const bothB = b.filter((e) => inA.has(e.text)).map((e) => e.text);
    const settings = bothA.filter((t) => !same(inA.get(t).parts, inB.get(t).parts));
    return { a, b, inA, inB, onlyA, onlyB, bothA, bothB, settings, reordered: !same(bothA, bothB) };
  };
  const bookLines = (here, there) => {
    const s = setLists(here, there);
    const lines = [];
    if (text(here.name) !== text(there.name)) {
      lines.push({ what: "Its name", here: text(here.name) || NONE, there: text(there.name) || NONE });
    }
    if (s.a.length !== s.b.length) {
      lines.push({ what: "Its set list", here: counted(s.a.length, "song"), there: counted(s.b.length, "song") });
    }
    if (s.onlyA.length || s.onlyB.length) {
      lines.push({ what: "Songs added", here: joined(s.onlyA), there: joined(s.onlyB) });
    }
    if (s.reordered) lines.push({ what: "Its order", here: joined(s.bothA), there: joined(s.bothB) });
    if (s.settings.length) {
      const said = (map) => s.settings.map((t) => t + ": " + settingOf(map.get(t).parts)).join("; ");
      lines.push({ what: "A song's setting", here: said(s.inA), there: said(s.inB) });
    }
    return lines;
  };
  // A songbook taken or given, in a word: what the side it went to has now that it hadn't (``from`` its document
  // before, null for a new one; ``to`` the one it has now).
  const bookChange = (from, to) => {
    if (!objOf(to)) return "removed";
    if (!objOf(from)) return counted(entriesOf(to).length, "song");
    const s = setLists(from, to);
    const said = [];
    if (s.onlyB.length) said.push(counted(s.onlyB.length, "song") + " added");
    if (s.onlyA.length) said.push(counted(s.onlyA.length, "song") + " taken out");
    if (s.reordered) said.push("its order changed");
    if (s.settings.length) said.push(s.settings.length === 1 ? "a song's setting changed"
      : s.settings.length + " songs' settings changed");
    if (text(from.name) !== text(to.name)) said.push("its name changed");
    return said.join(", ") || "changed";
  };

  // --- any unit --------------------------------------------------------------------------------------------------
  const valueOf = {
    alias: (doc) => joined(listOf(doc.slugs).map(text)),
    artist_url: (doc) => text(doc.page) || NONE,
    block: (doc) => (doc.tab === undefined || doc.tab === null ? NONE : "tab " + text(doc.tab)),
  };
  const WHAT = { alias: "Its slugs", artist_url: "Its UG page", block: "Blocked" };
  const differ = (kind, here, there) => {
    const a = objOf(here);
    const b = objOf(there);
    if (!a && !b) return [];
    let lines;
    if (kind === "removed") {
      lines = a && b ? [] : [{ what: "Removed", here: a ? "Removed" : "Kept", there: b ? "Removed" : "Kept" }];
    } else if (own.call(valueOf, kind)) {
      const mine = a ? valueOf[kind](a) : NONE;
      const theirs = b ? valueOf[kind](b) : NONE;
      lines = mine === theirs ? [] : [{ what: WHAT[kind], here: mine, there: theirs }];
    } else if (!a || !b) {
      const held = (doc) => (!doc ? NONE : kind === "songbook" ? counted(entriesOf(doc).length, "song") : "Kept");
      lines = [{ what: kind === "songbook" ? "The songbook" : "The song", here: held(a), there: held(b) }];
    } else {
      lines = kind === "song" ? songLines(a, b) : kind === "songbook" ? bookLines(a, b) : [];
    }
    // Two versions that differ only where no line above looks (a version's rating, a record's time): said so.
    return lines.length || same(a, b) ? lines : [{ what: "Its other details", here: "one way", there: "another way" }];
  };

  window.caracoleSyncWords = Object.freeze({
    NONE, differ, changed, sides, tabs, counted, size, day, when, readOn, bookChange, ownKey,
  });
})();
