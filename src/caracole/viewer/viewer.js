(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const doc = document.documentElement;
  let data;
  try {
    data = JSON.parse($("song").textContent);
  } catch (err) {
    doc.dataset.error = "data";
    return;
  }
  const own = Object.prototype.hasOwnProperty;
  const mod12 = (n) => ((n % 12) + 12) % 12;
  const signed = (n) => (n > 0 ? "+" + n : n < 0 ? "−" + -n : "0");
  const key = data.key;
  const chordEls = Array.from(document.querySelectorAll("#sheet .c"));
  const written = {};  // each chord as the sheet writes it, by index
  for (const el of chordEls) if (!own.call(written, el.dataset.c)) written[el.dataset.c] = el.textContent;
  const count = data.chords.length;
  const MODES = {
    ionian: ["Major", "bright and settled"],
    dorian: ["Dorian", "minor, with a brighter sixth"],
    phrygian: ["Phrygian", "minor and dark, with a Spanish half step"],
    lydian: ["Lydian", "major and dreamy, with a raised fourth"],
    mixolydian: ["Mixolydian", "major and bluesy, with a flat seventh"],
    aeolian: ["Minor", "the natural minor"],
    locrian: ["Locrian", "tense and unstable"],
  };
  const FS = { min: 13, max: 30, step: 2, start: 18 };
  // The scroll's speed, 1 to 30: ``px`` pixels a second a step at the usual text size (see pace()).
  const SPEED = { min: 1, max: 30, start: 6, px: 2 };
  // The capo goes on any fret up to the 11th (past it the shapes come round again), or the sheet's.
  const CAPO_MAX = Math.max(11, Number(data.capoSheet) || 0);
  // A chord heard (strum.js), as loud as this: the setting's names and caracoleSound's volumes.
  const VOLUMES = [["Off", 0], ["Soft", 0.3], ["Medium", 0.6], ["Loud", 1]];
  const VOL = 2;

  // --- the state: where the song is played, kept per page ------------------------------------
  // capo: the fret the capo is on (0 for none), or null for the sheet's own. It stays there
  // through a transposition, as on a guitar: the shapes move instead.
  const state = { t: Number(data.transpose) || 0, mode: null, alt: {}, at: {}, capo: null, fs: FS.start, strip: false,
    speed: SPEED.start, vol: VOL };
  const store = "caracole-viewer:" + location.pathname;
  // Chords chosen instead of others are kept for the sheet's chords by index: they only hold
  // while the sheet's chords do.
  const sheetChords = Object.keys(written).map((i) => written[i]).join("|");
  const validMode = (m) => Boolean(key) && data.modes.indexOf(m) >= 0;
  const clampT = (t) => Math.max(-11, Math.min(11, Math.round(Number(t) || 0)));
  const fretOf = (v) => (v === null || v === undefined || v === "" || !(Number(v) >= 0) ? null
    : Math.min(CAPO_MAX, Math.round(Number(v))));
  const sizeOf = (v) => (Number(v) >= FS.min && Number(v) <= FS.max ? Math.round(Number(v)) : null);
  const speedOf = (v) => (Number(v) >= SPEED.min && Number(v) <= SPEED.max ? Math.round(Number(v)) : null);
  const volOf = (v) => (/^[0-3]$/.test(String(v)) ? Number(v) : null);
  // The address spells the chords swapped as alt=<mode>.<i>.<root>.<suffix>.<bass>,… (suffix
  // URL-encoded, bass empty for none) and the shapes chosen as at=<i>.<n>,….
  const swapsOf = (text) => {
    const out = {};
    for (const part of String(text || "").split(",")) {
      const [mode, i, root, suffix, bass] = part.split(".");
      if (!validMode(mode) || !/^\d+$/.test(i || "") || !/^\d+$/.test(root || "") || !/^(\d+)?$/.test(bass || "")) continue;
      let text;
      try { text = decodeURIComponent(suffix || ""); } catch (err) { continue; }
      out[mode] = out[mode] || {};
      out[mode][i] = [Number(root), text, bass === "" || bass === undefined ? null : Number(bass)];
    }
    return out;
  };
  const swapsText = (alt) => Object.keys(alt).map((mode) => Object.keys(alt[mode]).filter((i) => Array.isArray(alt[mode][i]))
    .map((i) => [mode, i, alt[mode][i][0], encodeURIComponent(alt[mode][i][1]).replace(/\./g, "%2E"),
      alt[mode][i][2] === null ? "" : alt[mode][i][2]].join("."))).reduce((all, one) => all.concat(one), []).join(",");
  const positionsOf = (text) => {
    const out = {};
    for (const part of String(text || "").split(",")) {
      const [i, n] = part.split(".");
      if (/^\d+$/.test(i || "") && /^\d+$/.test(n || "") && Number(n) > 0) out[i] = Number(n);
    }
    return out;
  };
  // The shapes kept chosen, each with the chord it was chosen for (atSigns): read back once the chords
  // can be named (below setAt), as only a chord still named so gets its shape back.
  let keptAt = null;
  // Where an address (or the song's own version) plays the song: what it names of it.
  const adopt = (params) => {
    if (params.has("alt")) state.alt = swapsOf(params.get("alt"));
    if (params.has("at")) {
      state.at = positionsOf(params.get("at"));
      keptAt = null;  // the address says which
    }
    if (params.has("t")) state.t = clampT(params.get("t"));
    if (validMode(params.get("mode"))) state.mode = params.get("mode");
    if (params.has("capo")) state.capo = fretOf(params.get("capo"));
  };
  // The song's own version (overrides.toml's [version], "Make this my version"), which its PDF is in: the page
  // starts there when its address names no version of its own, and Reset everything goes back there.
  const start = new URLSearchParams(data.start || "");
  const hash = new URLSearchParams(location.hash.slice(1));
  if (data.start && !["t", "mode", "capo", "alt", "at"].some((name) => hash.has(name))) adopt(start);
  // What the browser kept was for this song as its PDF then was: a new [transpose] or version starts afresh.
  const keptFor = data.start || data.transpose;
  try {
    const saved = JSON.parse(localStorage.getItem(store) || "null");
    if (saved && typeof saved === "object") {
      const same = saved.base === keptFor;
      if (same) state.t = clampT(saved.t);
      if (same || !data.start) {  // in place of the version's: the sheet's own mode and shapes too
        state.mode = validMode(saved.mode) ? saved.mode : null;
        if (saved.alt && typeof saved.alt === "object" && saved.chords === sheetChords) state.alt = saved.alt;
        if (saved.at && typeof saved.at === "object" && saved.atSigns && typeof saved.atSigns === "object"
          && saved.chords === sheetChords) {
          state.at = {};
          keptAt = { at: saved.at, signs: saved.atSigns };
        }
        state.capo = fretOf(saved.capo);
      }
      if (sizeOf(saved.fs) !== null) state.fs = sizeOf(saved.fs);
      if (speedOf(saved.speed) !== null) state.speed = speedOf(saved.speed);
      if (volOf(saved.vol) !== null) state.vol = volOf(saved.vol);
      state.strip = saved.strip === true;
    }
  } catch (err) { /* no storage: the page still works */ }
  adopt(hash);
  if (sizeOf(hash.get("fs")) !== null) state.fs = sizeOf(hash.get("fs"));
  if (speedOf(hash.get("speed")) !== null) state.speed = speedOf(hash.get("speed"));
  if (volOf(hash.get("vol")) !== null) state.vol = volOf(hash.get("vol"));
  const save = () => {
    try {
      // Each shape chosen with the chord it was chosen for, so that only that chord gets it back.
      const atSigns = {};
      for (const i of Object.keys(state.at)) if (own.call(atSeen, i)) atSigns[i] = atSeen[i];
      localStorage.setItem(store, JSON.stringify(Object.assign({ base: keptFor, chords: sheetChords }, state,
        { atSigns })));
    } catch (err) { /* private mode, or a server's sandbox */ }
    // The address keeps where the song is played too, and the text size and the scroll speed,
    // read back above: without storage (a server's sandbox), a reload and Back still keep them.
    // Replaced, so Back isn't a step per tap.
    try {
      const params = new URLSearchParams(location.hash.slice(1));
      const keep = (name, value, kept) => (kept ? params.set(name, String(value)) : params.delete(name));
      // With a version of its own, t always: an address naming none would start in that version again.
      keep("t", state.t, Boolean(data.start) || state.t !== (Number(data.transpose) || 0));
      keep("mode", state.mode, state.mode !== null);
      keep("capo", state.capo, state.capo !== null);
      keep("alt", swapsText(state.alt), swapsText(state.alt) !== "");
      keep("at", Object.keys(state.at).map((i) => i + "." + state.at[i]).join(","), Object.keys(state.at).length > 0);
      keep("fs", state.fs, state.fs !== FS.start);
      keep("speed", state.speed, state.speed !== SPEED.start);
      keep("vol", state.vol, state.vol !== VOL);
      const fragment = params.toString();
      if (fragment !== location.hash.slice(1)) {
        history.replaceState(null, "", fragment ? "#" + fragment : location.pathname + location.search);
      }
    } catch (err) { /* an address the page can't change */ }
    exportLink();
  };

  // Export PDF of this version: served, a link to the server's export page for this very address, followed in
  // this tab (the sandbox has no popups); from a file, the command that makes it, with Copy.
  const exportLink = () => {
    const link = $("export");
    const cmd = $("export-cmd");
    if (!link || !cmd) return;
    const version = new URLSearchParams(location.hash.slice(1));
    if (location.protocol === "file:") {
      const title = (document.querySelector("h1") || {}).textContent || "";
      const artist = (document.querySelector(".artist") || {}).textContent || "";
      const quoted = (text) => "'" + text.replace(/'/g, "'\\''") + "'";
      for (const name of ["fs", "speed", "vol"]) version.delete(name);
      cmd.textContent = "caracole render --song " + quoted(artist ? artist + " - " + title : title)
        + " --version " + quoted(version.toString().replace(/%2C/g, ","));
      link.hidden = true;
      cmd.hidden = false;
      $("export-copy").hidden = false;
      $("export-hint").textContent = "Run this where caracole is installed; the PDF is written beside the sheet. "
        + "With --mine, it is your version instead: the song's own PDF, its viewer and its songbooks.";
      return;
    }
    const query = new URLSearchParams();
    query.set("sheet", decodeURIComponent(location.pathname.slice(1)));
    version.forEach((value, name) => query.append(name, value));
    link.setAttribute("href", "/export?" + query.toString());
  };
  if ($("export-copy")) {
    $("export-copy").addEventListener("click", () => {
      const done = () => { $("export-copy").textContent = "Copied"; };
      try {
        navigator.clipboard.writeText($("export-cmd").textContent).then(done, () => {});
      } catch (err) { /* no clipboard: the command is selectable */ }
    });
  }

  // --- naming chords -------------------------------------------------------------------------
  const modeNow = () => (key ? state.mode || key.mode : "");
  const asWritten = () => !state.mode || (key && state.mode === key.mode);
  const sheetCapo = Number(data.capoSheet) || 0;
  const capoNow = () => (state.capo === null ? sheetCapo : state.capo);
  // The chords are named for the shapes played: with another capo, as many semitones off.
  const shift = () => state.t - (capoNow() - sheetCapo);
  const names = (s) => (key ? data.names[modeNow()][mod12(key.tonic + s)] : data.names[""]).split(" ");
  const keyName = (s) => (key ? data.keyNames[modeNow()][mod12(key.tonic + s)] : "");
  const choices = () => state.alt[modeNow()] || {};
  // A chord chosen instead of another is kept as itself ([root, suffix, bass]) and found again
  // among the alternatives offered now: once the key or caracole's alternatives change, a
  // chord no longer offered is dropped rather than another one played in its place.
  const sameChord = (a, b) => a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
  const choice = (i) => {
    const chosen = own.call(choices(), i) ? choices()[i] : null;
    return Array.isArray(chosen) ? alts(i).findIndex((rep) => sameChord(rep, chosen)) : -1;
  };
  const alts = (i) => (key && data.alts[modeNow()] ? data.alts[modeNow()][i] || [] : []);
  const base = (i) => (asWritten() ? data.chords[i] : data.mapped[modeNow()][i]);
  const current = (i) => {
    const j = choice(i);
    return j >= 0 && alts(i)[j] ? alts(i)[j] : base(i);
  };
  const nameOf = (rep, s) => {
    const n = names(s);
    return n[mod12(rep[0] + s)] + rep[1] + (rep[2] === null ? "" : "/" + n[mod12(rep[2] + s)]);
  };
  const label = (i, rep) => {
    if (!rep) return written[i];
    if (shift() === 0 && asWritten() && rep === data.chords[i]) return written[i];
    return nameOf(rep, shift());
  };
  const capoHints = () => (key ? data.capo[modeNow()][mod12(state.t)] : []);
  // Where the song is played, as Cifra Club's key line says it: with a capo, the key of the
  // shapes, the capo and the key the song sounds in ("Em shapes · capo 2 · sounds F#m"), as
  // "Key Em" alone would read as the song's key; with none, the key. Each part is
  // [before, in bold, after, where the key came from]; ``moved`` says the transposition.
  // page.py writes the same line for the sheet as written.
  const keyLine = (moved) => {
    const capo = capoNow();
    if (!key) return capo ? [["Capo ", String(capo), "", ""]] : sheetCapo ? [["No capo", "", "", ""]] : [];
    const sounds = keyName(state.t + sheetCapo);
    if (!capo) return [["Key ", sounds, moved, key.from]].concat(sheetCapo ? [["no capo", "", "", ""]] : []);
    return [["", keyName(shift()), " shapes", ""], ["capo ", String(capo), "", ""], ["sounds ", sounds, moved, ""]]
      .concat(key.from ? [["", "", "", "key " + key.from]] : []);
  };
  // The same as one line of text, for a screen reader in the bar (``moved``: with the
  // transposition) and the settings' heading; without a key, Transpose and the capo.
  const keyLabel = (moved) => {
    const shown = moved && state.t ? signed(state.t) : "";
    if (!key) {
      const capo = capoNow();
      return ["Transpose" + (shown ? " " + shown : "")]
        .concat(capo ? ["capo " + capo] : sheetCapo ? ["no capo"] : []).join(" · ");
    }
    return keyLine("").filter((part) => part[1] || !part[3]).map((part) => part[0] + part[1] + part[2])
      .concat(shown ? [shown] : []).join(" · ");
  };
  // In short, for the bar, between − and +: the key you play, and under it what it is, the capo
  // and the transposition (["Em", "shapes", ["capo 2"]], ["Em", "key", ["+1"]]); the key it sounds
  // in is the key line's.
  const keyShort = () => {
    const capo = capoNow();
    const rest = (capo ? ["capo " + capo] : sheetCapo ? ["no capo"] : []).concat(state.t ? [signed(state.t)] : []);
    if (!key) return ["Transpose", "", rest];
    if (capo) return [keyName(shift()), "shapes", rest];
    return [keyName(state.t + sheetCapo), "key", rest];
  };
  // The line under the key, whole where there is room ("shapes · capo 2 · +1"); on a narrow screen
  // the capo and the transposition alone ("capo 2 · +1"), so that neither is cut off. Fitted again
  // when the bar comes back into view or the window changes.
  let keyUnder = ["", []];
  const fitKey = () => {
    const line = $("key-now").querySelector(".d");
    const [what, rest] = keyUnder;
    line.textContent = (what ? [what] : []).concat(rest).join(" · ");
    if (what && rest.length && line.scrollWidth > line.clientWidth) line.textContent = rest.join(" · ");
  };

  // --- chord diagrams --------------------------------------------------------------------------
  const NS = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs, parent) => {
    const node = document.createElementNS(NS, tag);
    for (const k in attrs) node.setAttribute(k, String(attrs[k]));
    if (parent) parent.appendChild(node);
    return node;
  };
  // A chord's shapes: those the sheet gives that very chord first (page.py's "shapes", "mine" of them:
  // the first so many), then chords-db's; the note goes with chords-db's.
  const shapesOf = (rep, s) => {
    if (!rep) return { list: [], note: "", mine: 0 };
    const pc = mod12(rep[0] + s);
    const n = names(s);
    const which = pc + "," + rep[1] + "," + (rep[2] === null ? "" : mod12(rep[2] + s));
    const given = data.shapes && own.call(data.shapes, which) ? data.shapes[which] : { list: null, mine: 0 };
    const slash = rep[5] && data.voicings[rep[5]] ? data.voicings[rep[5]][pc] : null;
    if (slash && slash.length) return { list: given.list || slash, note: "", mine: given.mine };
    const list = data.voicings[rep[3]] ? data.voicings[rep[3]][pc] || [] : [];
    let note = "";
    if (rep[4]) {
      const q = own.call(data.qualities, rep[3]) ? data.qualities[rep[3]] : rep[3];
      note = "No shape for this chord here: " + n[pc] + q + " is the closest.";
    }
    if (rep[2] !== null) note = (note ? note + " " : "") + "Play " + n[mod12(rep[2] + s)] + " in the bass.";
    return { list: given.list || list, note, mine: given.mine };
  };
  // A position as a diagram; the strip's (bare) leave the fingers out, too small to read there.
  const diagram = (position, title, bare) => {
    const frets = String(position[0]);
    const fingers = String(position[1]);
    const first = Number(position[2]) || 1;
    const barres = Array.isArray(position[3]) ? position[3] : [];
    const deepest = Math.max(4, ...Array.from(frets).map((f) => (f === "x" ? 0 : Number(f))));
    const left = 16, top = 16, gap = 10, row = 13;
    const width = left + gap * 5 + 10, height = top + row * deepest + 6;
    const root = svg("svg", { viewBox: "0 0 " + width + " " + height, role: "img", "aria-label": title });
    for (let s = 0; s < 6; s++) {
      svg("line", { class: "dg-grid", x1: left + s * gap, y1: top, x2: left + s * gap, y2: top + row * deepest }, root);
    }
    for (let f = 0; f <= deepest; f++) {
      svg("line", { class: "dg-grid", x1: left, y1: top + f * row, x2: left + gap * 5, y2: top + f * row }, root);
    }
    if (first === 1) svg("rect", { class: "dg-nut", x: left - 0.5, y: top - 2.5, width: gap * 5 + 1, height: 3 }, root);
    else svg("text", { class: "dg-fret", x: left - 4, y: top + row / 2 }, root).textContent = first + "fr";
    for (const b of barres) {
      const on = [];
      for (let s = 0; s < 6; s++) if (Number(frets[s]) === b) on.push(s);
      if (on.length < 2) continue;
      const x1 = left + on[0] * gap, x2 = left + on[on.length - 1] * gap, y = top + (b - 0.5) * row;
      svg("rect", { class: "dg-barre", x: x1 - 4.2, y: y - 4.2, width: x2 - x1 + 8.4, height: 8.4, rx: 4.2 }, root);
    }
    for (let s = 0; s < 6; s++) {
      const x = left + s * gap;
      const f = frets[s];
      if (f === "x") {
        svg("path", { class: "dg-mute", d: `M${x - 2.6} ${top - 9.6}l5.2 5.2m0 -5.2l-5.2 5.2` }, root);
      } else if (f === "0") {
        svg("circle", { class: "dg-open", cx: x, cy: top - 7, r: 2.8 }, root);
      } else {
        const y = top + (Number(f) - 0.5) * row;
        svg("circle", { class: "dg-dot", cx: x, cy: y, r: 4.2 }, root);
        if (!bare && fingers[s] && fingers[s] !== "0") {
          svg("text", { class: "dg-finger", x: x, y: y + 0.3 }, root).textContent = fingers[s];
        }
      }
    }
    return root;
  };

  // A chord's positions along the neck, frets 0 to ``frets``, the high e on top: each position's dots
  // at absolute frets (a position's fret n is n + base - 1 up the neck), in its own colour (p0 to p3,
  // round again after four; the first ``mine`` are the tab's own, marked), open strings as rings at the nut, muted strings nothing. ``chosen``
  // is drawn bolder, last. Every dot carries its position (data-p) and fret (data-fret).
  const neck = (positions, opts) => {
    const frets = opts.frets || 15;
    const left = 14, top = 9, cell = 19, gap = 9;
    const width = left + cell * frets + 4, height = top * 2 + gap * 5;
    const label = (positions.length === 1 ? "1 position" : positions.length + " positions");
    const root = svg("svg", { class: "neck", viewBox: "0 0 " + width + " " + height, role: "img",
      "aria-label": (opts.name || "") + ": " + label });
    for (let s = 0; s < 6; s++) {
      svg("line", { class: "nk-string", x1: left, y1: top + s * gap, x2: left + cell * frets, y2: top + s * gap }, root);
    }
    for (let f = 1; f <= frets; f++) {
      svg("line", { class: "nk-fret", x1: left + f * cell, y1: top, x2: left + f * cell, y2: top + gap * 5 }, root);
    }
    svg("rect", { class: "nk-nut", x: left - 1.5, y: top - 1, width: 3, height: gap * 5 + 2 }, root);
    for (const f of [3, 5, 7, 9, 12, 15]) {
      if (f > frets) continue;
      const x = left + (f - 0.5) * cell, mid = top + gap * 2.5;
      if (f === 12) {
        svg("circle", { class: "nk-inlay", cx: x, cy: mid - gap * 1.5, r: 1.8 }, root);
        svg("circle", { class: "nk-inlay", cx: x, cy: mid + gap * 1.5, r: 1.8 }, root);
      } else svg("circle", { class: "nk-inlay", cx: x, cy: mid, r: 1.8 }, root);
    }
    const order = positions.map((_, p) => p).filter((p) => p !== opts.chosen);
    if (opts.chosen >= 0 && opts.chosen < positions.length) order.push(opts.chosen);
    for (const p of order) {
      const [shape, , base] = positions[p];
      const up = (Number(base) || 1) - 1;
      const bold = p === opts.chosen;
      for (let s = 0; s < 6; s++) {
        const c = shape[s];
        if (c === "x") continue;
        const fret = c === "0" ? 0 : Number(c) + up;
        const attrs = { class: (c === "0" ? "nk-open" : "nk-dot") + " p" + (p % 4) + (bold ? " chosen" : "") + (p < (opts.mine || 0) ? " tabs" : ""),
          cy: top + (5 - s) * gap, r: bold ? 4.2 : 3.2, "data-p": p, "data-fret": fret };
        attrs.cx = fret === 0 ? left - 7 : left + (fret - 0.5) * cell;
        svg("circle", attrs, root);
      }
    }
    return root;
  };
  // What each position is called in the neck's legend: its number, as the card counts them ("2 of 4"), then
  // "the tab's" for the first ``mine`` of them, "open" for one with open strings at the nut, else the fret
  // its lowest finger is on. Numbered, two at one fret ("1 · fret 1", "2 · fret 1") have names of their own,
  // and are told apart by more than their colour.
  const neckLabels = (positions, mine) => positions.map((position, p) => {
    const n = p + 1 + " · ";
    if (p < mine) return n + "the tab's";
    const up = (Number(position[2]) || 1) - 1;
    const fretted = Array.from(position[0]).filter((c) => c !== "x" && c !== "0").map((c) => Number(c) + up);
    return n + (up === 0 && position[0].includes("0") ? "open" : "fret " + Math.min(...fretted));
  });
  // The highest fret a position reaches up the neck (0 for open strings alone).
  const topFret = (position) => Math.max(0, ...Array.from(String(position[0])).filter((c) => c !== "x" && c !== "0")
    .map((c) => Number(c) + (Number(position[2]) || 1) - 1));

  // --- drawing the page --------------------------------------------------------------------------
  const bar = $("bar"), panel = $("panel"), card = $("card"), pill = $("pill"), go = $("go");
  const more = $("more"), sizes = $("sizes"), sizeButton = $("size");
  const button = (text, pressed, onClick, small) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.textContent = text;
    if (small) {
      const s = document.createElement("small");
      s.textContent = small;
      b.appendChild(s);
    }
    b.setAttribute("aria-pressed", pressed ? "true" : "false");
    b.addEventListener("click", onClick);
    return b;
  };
  // A row of chips drawn anew, as one of them is pressed: the focus, when it was on one, goes to the
  // one in its place, and stays in the settings or the card rather than falling back to the page.
  const refill = (box, chips) => {
    const at = Array.prototype.indexOf.call(box.children, document.activeElement);
    box.textContent = "";
    for (const chip of chips) box.appendChild(chip);
    const to = at >= 0 ? box.children[Math.min(at, box.children.length - 1)] : null;
    if (to) to.focus({ preventScroll: true });
  };

  // A chord's chosen position holds while the chord is the same: once its name or its number of
  // shapes changes (a transposition, a mode, a capo, a swap), it starts at its first shape again.
  const atSeen = {};
  const atSign = (i) => {
    const rep = own.call(written, i) ? current(i) : null;
    return rep ? label(i, rep) + "|" + shapesOf(rep, shift()).list.length : "";
  };
  const keepPositions = () => {
    for (const i of Object.keys(state.at)) {
      const sign = atSign(i);
      if (!sign || state.at[i] >= Number(sign.split("|")[1]) || (i in atSeen && atSeen[i] !== sign)) {
        delete state.at[i];
        delete atSeen[i];
      } else atSeen[i] = sign;
    }
  };
  // A position chosen now, for the chord as it is now: it holds until that changes.
  const setAt = (i, n) => {
    if (n > 0) {
      state.at[i] = n;
      atSeen[i] = atSign(i);
    } else {
      delete state.at[i];
      delete atSeen[i];
    }
  };
  // The shapes the browser kept (no address said which): each chord named now as it was when its shape was
  // chosen plays it again. One named otherwise (an address with another key, mode or capo, or a swap)
  // starts at its first shape, as it would have, rather than take a shape chosen for another chord.
  if (keptAt) {
    for (const i of Object.keys(keptAt.at)) {
      const n = Number(keptAt.at[i]);
      const sign = atSign(i);
      if (Number.isInteger(n) && n > 0 && sign !== "" && keptAt.signs[i] === sign) setAt(i, n);
    }
  }
  const render = () => {
    if (state.capo === sheetCapo) state.capo = null;  // the sheet's own again
    keepPositions();
    for (const el of chordEls) {
      const i = el.dataset.c;
      el.textContent = label(i, current(i));
      el.classList.toggle("changed", choice(i) >= 0);
    }
    doc.style.setProperty("--fs", state.fs + "px");
    $("fs-now").textContent = state.fs + " px";
    $("smaller").setAttribute("aria-disabled", state.fs <= FS.min ? "true" : "false");
    $("bigger").setAttribute("aria-disabled", state.fs >= FS.max ? "true" : "false");

    const [main, what, rest] = keyShort();
    $("key-now").querySelector(".k").textContent = main;
    keyUnder = [what, rest];
    fitKey();
    $("key-full").textContent = keyLabel(true);
    $("panel-title").textContent = key ? keyLabel(false) : "Transpose";
    const box = $("facts");
    box.textContent = "";
    keyLine(state.t ? " (" + signed(state.t) + ")" : "").forEach((f, n) => {
      if (n) box.appendChild(document.createTextNode(" · "));
      if (f[0]) box.appendChild(document.createTextNode(f[0]));
      if (f[1]) {
        const b = document.createElement("b");
        b.textContent = f[1];
        box.appendChild(b);
      }
      if (f[2]) box.appendChild(document.createTextNode(f[2]));
      if (f[3]) {
        const from = document.createElement("span");
        from.className = "from";
        from.textContent = (f[0] || f[1] ? " " : "") + f[3];
        box.appendChild(from);
      }
    });

    $("shift").textContent = signed(state.t);
    $("shift-hint").textContent = data.transpose
      ? "Your PDF is transposed " + signed(data.transpose) + "; Reset goes back there." : "";
    $("capo-at").textContent = String(capoNow());
    const hints = capoHints();
    refill($("capo"), hints.map(([fret, shapesKey]) => button(fret ? "Capo " + fret : "No capo", state.capo === fret, () => {
      state.capo = state.capo === fret ? null : fret;
      render();
    }, shapesKey + " shapes")));
    // The same words wherever the capo is, so the row keeps its height under your thumb.
    $("capo-hint").textContent = "Wherever the capo is, the song sounds the same: the chords show the shapes to play."
      + (hints.length ? " Easier shapes:" : "");

    $("mode-row").hidden = !key;
    refill($("modes"), key ? data.modes.map((mode) => button((MODES[mode] || [mode])[0], modeNow() === mode, () => {
      state.mode = mode === key.mode ? null : mode;
      render();
    }, mode === key.mode ? "as written" : "")) : []);
    if (key) {
      const info = MODES[modeNow()] || ["", ""];
      $("mode-hint").textContent = keyName(state.t + sheetCapo) + ": " + info[1] + "." +
        (asWritten() ? "" : " Each chord moves to the same degree of the new scale.");
    }

    $("sound-row").hidden = !sound || count === 0;
    if (sound) sound.setVolume(VOLUMES[state.vol][1]);
    refill($("volumes"), sound ? VOLUMES.map(([name], v) => button(name, state.vol === v, () => {
      state.vol = v;
      render();
    })) : []);
    $("strip-toggle").setAttribute("aria-pressed", state.strip ? "true" : "false");
    $("strip-toggle").textContent = state.strip ? "Hide" : "Show all";
    drawSpeed();
    drawStrip();
    drawNecks();  // before layout(), which measures the song beside the rail
    layout();  // fit() too
    if (!card.hidden) drawCard();  // an open card follows the key, the mode and the capo
    dock();
    save();
    hush();  // the lines moved under the page's scroll position, not by your hand
  };

  // A chord may reach over the words after it, up to the next chord on its row: lyrics then
  // read without gaps. Where two chords would touch, the first one's column is widened. A chord
  // never reaches past the line's edge, which would widen the page: where the row has less room
  // left than the chord is wide, its column takes the chord's width, and goes on to the next row.
  const sheetEl = $("sheet");
  const fit = () => {
    sheetEl.classList.add("tight");
    for (const y of sheetEl.querySelectorAll(".s > .y")) y.style.minWidth = "";
    const space = parseFloat(getComputedStyle(sheetEl).fontSize) * 0.45;
    for (const line of sheetEl.querySelectorAll(".l")) {
      const kids = Array.from(line.children);
      const right = line.getBoundingClientRect().right;
      kids.forEach((col, k) => {
        if (!col.classList.contains("s")) return;
        const box = col.getBoundingClientRect();
        const chord = col.firstElementChild.offsetWidth;
        const need = chord + space;
        let room = right - box.left;  // no chord after it on its row: up to the edge
        for (let m = k + 1; m < kids.length; m++) {
          const next = kids[m].getBoundingClientRect();
          if (Math.abs(next.bottom - box.bottom) > 2) break;  // wrapped onto the next row
          if (kids[m].classList.contains("s")) {
            room = next.left - box.left;
            break;
          }
        }
        let width = room < need ? box.width + need - room : 0;
        if (box.left + chord > right + 0.5) width = Math.max(width, chord);  // past the edge: on to the next row
        if (width) col.lastElementChild.style.minWidth = Math.ceil(width) + "px";
      });
    }
  };
  // One column, or two side by side where viewer.css offers them (a wide screen), only for a song
  // the window then shows whole: the song's end in the second column, and the sheet no taller than
  // the window above the room the page keeps at its foot for the controls.
  const layout = () => {
    const y = window.scrollY;
    doc.dataset.columns = "2";
    if (getComputedStyle(sheetEl).columnCount !== "2") {  // not offered here
      doc.dataset.columns = "1";
      fit();
      return;
    }
    fit();
    const box = sheetEl.getBoundingClientRect();
    const end = sheetEl.lastElementChild && sheetEl.lastElementChild.lastElementChild;
    const page = sheetEl.closest(".page") || document.body;
    const room = window.innerHeight - (parseFloat(getComputedStyle(page).paddingBottom) || 0);
    const fits = Boolean(end) && end.getBoundingClientRect().left > box.left + box.width / 2 && box.height <= room;
    if (!fits) {
      doc.dataset.columns = "1";
      fit();
    }
    // Two columns are shorter than one: measuring them may have moved the page. Back to where it was.
    if (window.scrollY !== y) window.scrollTo(0, y);
  };
  let fitting = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(fitting);
    fitting = requestAnimationFrame(() => {
      layout();
      fitKey();
      place();
      dock();
    });
  });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { layout(); fitKey(); }, () => {});
  // The tab's preamble opened or folded again (page.py): the song moves, and may no longer fit two
  // columns; an open card goes with its chord.
  for (const fold of sheetEl.querySelectorAll("details")) fold.addEventListener("toggle", () => { layout(); place(); });
  // Printed, the notes print whole: where the stylesheet can't show a folded one's text (no
  // ::details-content), they open for the printout and fold again after it.
  if (!(window.CSS && CSS.supports && CSS.supports("selector(::details-content)"))) {
    let unfolded = [];
    window.addEventListener("beforeprint", () => {
      unfolded = [...document.querySelectorAll("details.pre:not([open])")];
      for (const fold of unfolded) fold.open = true;
    });
    window.addEventListener("afterprint", () => {
      for (const fold of unfolded) fold.open = false;
      unfolded = [];
    });
  }

  const drawStrip = () => {
    const strip = $("strip");
    strip.hidden = !state.strip;
    strip.textContent = "";
    if (!state.strip) return;
    for (let i = 0; i < count; i++) {
      const rep = current(String(i));
      const shapes = shapesOf(rep, shift());
      const shape = shapes.list[Math.min(state.at[String(i)] || 0, shapes.list.length - 1)];
      const b = document.createElement("button");
      b.type = "button";
      const name = label(String(i), rep);
      if (shape) b.appendChild(diagram(shape, name, true));
      b.appendChild(document.createTextNode(name));
      b.addEventListener("click", () => {
        openCard(String(i), b);
        hear();
      });
      strip.appendChild(b);
    }
  };

  // --- the rail of necks: a wide screen's, on the left -----------------------------------------------
  // From 1200 px wide (viewer.css), each chord the sheet shows, once, in the order it first comes (two
  // chords shown by one name are one), with every position of it along a neck and a legend naming them.
  // Picking one, on the neck or in the legend, makes it the shape the strip and the chord's card show, at
  // every place of that chord, kept with the rest (state.at). A legend is a group of radio buttons: one
  // Tab stop a chord, on the shape played, and the arrows go from shape to shape. Narrower, the card alone.
  const necksEl = $("necks");
  const railWide = window.matchMedia("(min-width: 1200px)");
  const shownAs = (name) => {  // the chords the sheet shows by this name, by index
    const out = [];
    for (let i = 0; i < count; i++) {
      const rep = own.call(written, String(i)) ? current(String(i)) : null;
      if (rep && label(String(i), rep) === name) out.push(String(i));
    }
    return out;
  };
  const drawNecks = () => {
    if (!necksEl) return;
    const on = count > 0 && railWide.matches;
    necksEl.hidden = !on;
    if (on) doc.dataset.necks = "1";  // the song and the bar move over for it
    else delete doc.dataset.necks;
    const active = necksEl.contains(document.activeElement) ? document.activeElement.closest(".nk") : null;
    const focused = active ? Array.prototype.indexOf.call(necksEl.children, active) : -1;
    necksEl.textContent = "";
    if (!on) return;
    const drawn = new Set();
    for (let i = 0; i < count; i++) {
      const c = String(i);
      const rep = own.call(written, c) ? current(c) : null;
      if (!rep) continue;  // a chord caracole can't read: nothing to play
      const name = label(c, rep);
      if (drawn.has(name)) continue;
      drawn.add(name);
      const group = necksEl.appendChild(document.createElement("div"));
      group.className = "nk";
      group.dataset.name = name;
      const head = group.appendChild(document.createElement("p"));
      head.className = "nk-name";
      head.textContent = name;
      const shapes = shapesOf(rep, shift());
      if (!shapes.list.length) {
        const none = group.appendChild(document.createElement("p"));
        none.className = "nk-none";
        none.textContent = "No shape to show for this chord.";
        continue;
      }
      const chosen = Math.min(state.at[c] || 0, shapes.list.length - 1);
      group.appendChild(neck(shapes.list, { name, chosen, mine: shapes.mine,
        frets: Math.max(15, ...shapes.list.map(topFret)) }));
      const legend = group.appendChild(document.createElement("div"));
      legend.className = "nk-legend";
      legend.setAttribute("role", "radiogroup");
      legend.setAttribute("aria-label", name);
      neckLabels(shapes.list, shapes.mine).forEach((words, p) => {
        const b = legend.appendChild(document.createElement("button"));
        b.type = "button";
        b.setAttribute("role", "radio");
        b.setAttribute("aria-checked", p === chosen ? "true" : "false");
        b.tabIndex = p === chosen ? 0 : -1;
        b.dataset.p = String(p);
        const swatch = b.appendChild(document.createElement("span"));
        swatch.className = "sw p" + (p % 4) + (p < shapes.mine ? " tabs" : "");
        swatch.setAttribute("aria-hidden", "true");
        b.appendChild(document.createTextNode(words));
      });
    }
    // Drawn anew under the focus: it goes to the shape now played of the same chord.
    const back = focused >= 0 ? necksEl.children[focused] : null;
    const to = back && back.querySelector('[aria-checked="true"]');
    if (to) to.focus({ preventScroll: true });
  };
  // A position picked for a chord: every place the sheet shows it plays it, and its card, when it shows
  // that chord as it is played, turns to it.
  const pickPosition = (name, p) => {
    const places = shownAs(name);
    for (const i of places) setAt(i, p);
    if (!card.hidden && places.indexOf(shown.i) >= 0 && shown.pick === choice(shown.i)) shown.at = p;
    drawStrip();
    drawNecks();
    if (!card.hidden) drawCard();
    save();
  };
  // The neck clicked: the position of the dot nearest to the pointer, within a fingertip of it.
  const nearestPosition = (group, x, y) => {
    let best = -1, reach = 20;
    for (const dot of group.querySelectorAll("svg.neck circle[data-p]")) {
      const r = dot.getBoundingClientRect();
      const d = Math.hypot(r.left + r.width / 2 - x, r.top + r.height / 2 - y);
      if (d < reach) {
        reach = d;
        best = Number(dot.dataset.p);
      }
    }
    return best;
  };
  if (necksEl) {
    necksEl.addEventListener("click", (e) => {
      const target = e.target instanceof Element ? e.target : null;
      const group = target && target.closest(".nk");
      if (!group) return;
      const radio = target.closest("[role=radio]");
      const p = radio ? Number(radio.dataset.p)
        : target.closest("svg.neck") ? nearestPosition(group, e.clientX, e.clientY) : -1;
      if (p >= 0) pickPosition(group.dataset.name, p);
    });
    const STEPS = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    necksEl.addEventListener("keydown", (e) => {
      const radio = e.target instanceof Element ? e.target.closest("[role=radio]") : null;
      if (!radio || !own.call(STEPS, e.key) || e.altKey || e.ctrlKey || e.metaKey) return;
      e.preventDefault();
      e.stopPropagation();  // in a songbook the arrows go from song to song (book.js), but not from here
      const all = radio.parentElement.children.length;
      pickPosition(radio.closest(".nk").dataset.name, (Number(radio.dataset.p) + STEPS[e.key] + all) % all);
    });
    // The window widened past 1200 px, or narrowed under it: the rail comes or goes, and the song with it.
    railWide.addEventListener("change", () => {
      drawNecks();
      layout();
      place();
    });
  }

  // --- the chord card: shapes, and chords to play instead ----------------------------------------
  // ``el`` is the chord tapped (or the strip's button): the card is placed by it, from 900 px wide,
  // and the focus goes back to it. Another chord tapped while the card is open fills it in its place.
  const shown = { i: null, pick: -1, at: 0, el: null, position: null };
  const openCard = (i, el) => {
    if (!own.call(written, i)) return;
    shown.i = i;
    shown.pick = choice(i);
    shown.at = state.at[i] || 0;
    shown.el = el || chordEls.find((c) => c.dataset.c === i) || null;
    for (const c of chordEls) c.classList.toggle("on", c.dataset.c === i);
    drawCard();  // filled before it takes the focus, so a screen reader hears the chord
    open(card, el || null);
    // On a phone, a chord tapped where the card now docks comes up above it (the dock's scroll padding),
    // lit, with the words of its line; one in sight already stays where it is.
    if (!wide.matches && shown.el && el) {
      (shown.el.closest(".l") || shown.el).scrollIntoView({ block: "nearest", behavior: calm.matches ? "auto" : "smooth" });
    }
  };
  // What the card is placed by: the chord, or the strip's button for it, which the strip draws anew.
  const anchor = () => {
    if (shown.el && shown.el.isConnected) return shown.el;
    const again = $("strip").children[Number(shown.i)];
    if (shown.el && again) return (shown.el = again);
    return chordEls.find((c) => c.dataset.c === shown.i) || $("sheet");
  };
  const drawCard = () => {
    const i = shown.i;
    const list = alts(i);
    if (shown.pick >= list.length) shown.pick = -1;
    const rep = shown.pick >= 0 ? list[shown.pick] : base(i);
    const name = label(i, rep);
    $("card-name").textContent = name;
    const shapes = shapesOf(rep, shift());
    const box = $("diagram");
    box.textContent = "";
    shown.position = null;
    if (shapes.list.length) {
      shown.at = Math.min(shown.at, shapes.list.length - 1);
      shown.position = shapes.list[shown.at];
      box.appendChild(diagram(shapes.list[shown.at], name));
      const c = document.createElement("span");
      c.className = "count";
      c.textContent = shapes.list.length > 1 ? shown.at + 1 + " of " + shapes.list.length : "";
      box.appendChild(c);
    } else {
      box.textContent = rep ? "No shape to show for this chord." : "caracole can't read this chord.";
    }
    heardBy(box, name);
    $("prev").disabled = shown.at <= 0;
    $("next").disabled = shown.at >= shapes.list.length - 1;
    const capoNote = capoNow() ? " With the capo on fret " + capoNow() + "." : sheetCapo ? " With no capo." : "";
    // The shape's note, and a hidden copy of the note on the chord's other shapes (viewer.css): from the
    // tab's shapes to chords-db's, the card keeps its height, and ‹ › stay under the thumb.
    const tabs = shown.at < shapes.mine;
    const said = (mine) => ((mine ? "As the tab plays it." : shapes.note) + capoNote).trim();
    const noteBox = $("shape-note");
    noteBox.textContent = "";
    const line = (text, room) => {
      if (!text) return;
      const span = noteBox.appendChild(document.createElement("span"));
      span.textContent = text;
      if (room) span.className = "room";
    };
    line(said(tabs));
    if (shapes.mine && shapes.mine < shapes.list.length) line(said(!tabs), true);

    const altBox = $("alts");
    $("alts-title").hidden = !list.length;
    refill(altBox, list.length ? [button(label(i, base(i)), shown.pick < 0, () => pick(-1), "as written")]
      .concat(list.map((alt, j) => button(label(i, alt), shown.pick === j, () => pick(j)))) : []);
    const use = $("use");
    const using = document.activeElement === use;
    use.hidden = shown.pick === choice(i);
    // Played for every one, it hides: the focus goes to the chord now played.
    if (using && use.hidden) {
      const played = altBox.querySelector('[aria-pressed="true"]');
      if (played) played.focus({ preventScroll: true });
    }
    const was = label(i, base(i));
    use.textContent = shown.pick >= 0 ? "Play " + name + " for every " + was : "Back to " + was + " everywhere";
    place();
    dock();
  };
  // --- hearing it (strum.js): a tap on a chord, or on its card's diagram, strums the shape the card shows,
  // at the capo; nothing sounds otherwise. The diagram is a button only while it has a shape to play.
  const sound = window.caracoleSound && window.caracoleSound.available ? window.caracoleSound : null;
  const hearable = () => Boolean(sound) && state.vol > 0 && Boolean(shown.position);
  const hear = () => {
    if (hearable()) sound.strum(shown.position, { capo: capoNow() });
  };
  function heardBy(box, name) {
    if (hearable()) {
      box.setAttribute("role", "button");
      box.tabIndex = 0;
      box.setAttribute("aria-label", "Hear " + name);
    } else {
      for (const attr of ["role", "tabindex", "aria-label"]) box.removeAttribute(attr);
    }
  }
  $("diagram").addEventListener("click", hear);
  $("diagram").addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      hear();
    }
  });
  const pick = (j) => {
    shown.pick = j;
    shown.at = 0;
    drawCard();
  };
  $("use").addEventListener("click", () => {
    const mode = modeNow();
    const mine = Object.assign({}, state.alt[mode] || {});
    if (shown.pick >= 0) mine[shown.i] = alts(shown.i)[shown.pick].slice(0, 3);
    else delete mine[shown.i];
    state.alt[mode] = mine;
    render();
  });
  // The position shown is kept for the chord played now (not one tried among the alternatives).
  const keepAt = () => {
    if (shown.pick !== choice(shown.i)) return;
    for (const i of shownAs(label(shown.i, current(shown.i)))) setAt(i, shown.at);  // the rail's one chord
    drawStrip();
    drawNecks();
    save();
  };
  $("prev").addEventListener("click", () => { shown.at = Math.max(0, shown.at - 1); drawCard(); keepAt(); });
  $("next").addEventListener("click", () => { shown.at += 1; drawCard(); keepAt(); });
  let touchX = null;
  $("diagram").addEventListener("touchstart", (e) => { touchX = e.touches[0].clientX; }, { passive: true });
  $("diagram").addEventListener("touchend", (e) => {
    if (touchX === null) return;
    const dx = e.changedTouches[0].clientX - touchX;
    touchX = null;
    if (Math.abs(dx) > 36) (dx < 0 ? $("next") : $("prev")).click();
  });

  // --- the settings and a chord's card: beside the song, never over it ------------------------------
  // Neither is modal: nothing dims the song and the page stays within reach, so you see the chords
  // change as you transpose and tap one chord after another. On a phone each docks at the foot, above
  // the bar, the one opened last over the other, and the song scrolls under it; from 900 px wide
  // (viewer.css) the settings are a rail beside the song and the card a popover by its chord. Each
  // takes the focus as it opens (its heading); Escape closes the one on top, and the focus goes back
  // to what opened it when it was in there.
  const pageEl = document.querySelector(".page");
  const wide = window.matchMedia("(min-width: 900px)");
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)");
  const layers = [];  // the open ones, the last on top: {el, opener}
  const topLayer = () => (layers.length ? layers[layers.length - 1].el : null);
  const inSight = (which) => !which.hidden && (wide.matches || topLayer() === which);
  // On a phone the page leaves room under the song for the one docked at its foot, so the end of
  // the song comes up above it, and the pill rides above it (--dock: its height). The bar is out of
  // the way while the song moves by itself, unless one is docked on it: then nothing moves as the
  // scroll pauses and resumes. Paused, or at the end of the song, it is back, under the pill.
  function dock() {
    const there = wide.matches ? null : topLayer();
    const away = moving() && !there;
    if (bar.hidden !== away) {
      bar.hidden = away;
      if (!away) {
        slide(false);
        fitKey();
      }
    }
    if (there) {
      doc.dataset.dock = there.id;
      doc.style.setProperty("--dock", there.offsetHeight + "px");
    } else if (doc.dataset.dock) {
      delete doc.dataset.dock;
      doc.style.removeProperty("--dock");
    }
  }
  // From 900 px wide the card is a popover by its chord: under it, or above it where the bar leaves
  // no room below, and across it, within the song's column. It is placed in the page, so it goes
  // with its chord as the page scrolls.
  function place() {
    if (card.hidden || !wide.matches) return;
    const a = anchor().getBoundingClientRect();
    const column = pageEl.getBoundingClientRect();
    const width = card.offsetWidth, height = card.offsetHeight, gap = 8;
    const floor = bar.hidden || bar.classList.contains("away") ? window.innerHeight : bar.getBoundingClientRect().top;
    let top = a.bottom + gap;
    if (top + height > floor - gap && a.top - gap - height >= gap) top = a.top - gap - height;
    const left = Math.max(column.left + gap, Math.min(a.left - 16, column.right - gap - width));
    card.style.setProperty("--pop-top", Math.round(top + window.scrollY) + "px");
    card.style.setProperty("--pop-left", Math.round(left + window.scrollX) + "px");
  }
  const restack = () => {
    const rail = doc.dataset.panel;
    for (const which of [panel, card]) which.classList.toggle("top", which === topLayer());
    more.setAttribute("aria-expanded", panel.hidden ? "false" : "true");
    if (panel.hidden) delete doc.dataset.panel;
    else doc.dataset.panel = "open";
    if (wide.matches && rail !== doc.dataset.panel) layout();  // the song's column narrows beside the rail
    place();
    dock();
  };
  const open = (which, opener) => {
    const at = layers.findIndex((layer) => layer.el === which);
    if (at >= 0) layers.splice(at, 1);  // open already: on top again
    layers.push({ el: which, opener: opener instanceof Element && opener !== document.body ? opener : null });
    showSizes(false);
    which.hidden = false;
    slide(false);  // the bar it sits on
    restack();
    pauseScroll();
    which.querySelector("h2").focus({ preventScroll: true });
  };
  const close = (which) => {
    const at = layers.findIndex((layer) => layer.el === which);
    if (at < 0) return;
    const opener = layers.splice(at, 1)[0].opener;
    const active = document.activeElement;
    const mine = !active || active === document.body || which.contains(active);
    which.hidden = true;
    if (which === card) for (const el of chordEls) el.classList.remove("on");
    restack();
    if (!mine) return;  // the focus is somewhere else of yours: it stays there
    let to = opener && opener.isConnected ? opener : null;
    if (!to && opener && which === card) to = anchor();  // the strip drew its button anew
    if (!to && topLayer()) to = topLayer().querySelector("h2");
    if (to) to.focus({ preventScroll: true });
  };
  const closeAll = () => {
    while (layers.length) close(topLayer());
  };
  for (const x of document.querySelectorAll("[data-close]")) x.addEventListener("click", () => close(x.closest(".sheet-ui")));
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!sizes.hidden) {
      // The size box first, and the focus back to Aa when it was in there.
      const inside = $("size-box").contains(document.activeElement);
      showSizes(false);
      if (inside) sizeButton.focus({ preventScroll: true });
      return;
    }
    if (layers.length) close(topLayer());
  });
  // ⋯ closes the settings where you see them, and brings them up from under a card on a phone.
  more.addEventListener("click", () => (inSight(panel) ? close(panel) : open(panel, more)));

  // In the focus order the card comes after its chord, wherever it is on the page: Tab from its last
  // control goes on to what follows the chord, and Shift+Tab from its first back to the chord.
  const reachable = (el) => el.tabIndex >= 0 && !el.disabled && el.getClientRects().length > 0
    && getComputedStyle(el).visibility === "visible";
  const FOCUSABLE = "a[href], button, input, select, textarea, summary, [tabindex]";
  card.addEventListener("keydown", (e) => {
    if (e.key !== "Tab" || e.altKey || e.ctrlKey || e.metaKey) return;
    const from = anchor();
    if (!from || from === $("sheet") || card.contains(from)) return;
    const mine = Array.from(card.querySelectorAll(FOCUSABLE)).filter(reachable);
    const here = document.activeElement;
    const edge = e.shiftKey ? here === $("card-name") || here === mine[0] : here === mine[mine.length - 1];
    if (!edge) return;
    const to = e.shiftKey ? from : Array.from(document.querySelectorAll(FOCUSABLE)).find((el) => !card.contains(el)
      && !from.contains(el) && Boolean(from.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) && reachable(el));
    if (!to) return;
    e.preventDefault();
    to.focus();
  });

  // --- Aa: the text size, in a box beside the song -------------------------------------------------
  // Not a dialog: the song stays in view and within reach, and the box closes on Escape, on a tap
  // anywhere else, or when the focus leaves it.
  function showSizes(on) {
    sizes.hidden = !on;
    sizeButton.setAttribute("aria-expanded", on ? "true" : "false");
  }
  sizeButton.addEventListener("click", () => showSizes(sizes.hidden));
  document.addEventListener("pointerdown", (e) => {
    if (!sizes.hidden && !(e.target instanceof Node && $("size-box").contains(e.target))) showSizes(false);
  }, true);
  $("size-box").addEventListener("focusout", (e) => {
    if (e.relatedTarget instanceof Node && !$("size-box").contains(e.relatedTarget)) showSizes(false);
  });

  const sheet = $("sheet");
  sheet.addEventListener("click", (e) => {
    const el = e.target.closest(".c");
    if (el) {
      openCard(el.dataset.c, el);
      hear();
    }
  });
  sheet.addEventListener("keydown", (e) => {
    const el = e.target.closest(".c");
    if (el && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      openCard(el.dataset.c, el);
      hear();
    }
  });

  const step = (t) => {
    state.t = clampT(t);
    render();
  };
  $("down").addEventListener("click", () => step(state.t - 1));
  $("up").addEventListener("click", () => step(state.t + 1));
  $("reset-t").addEventListener("click", () => step(data.transpose));
  const moveCapo = (fret) => {
    state.capo = Math.max(0, Math.min(CAPO_MAX, fret));
    render();
  };
  $("capo-down").addEventListener("click", () => moveCapo(capoNow() - 1));
  $("capo-up").addEventListener("click", () => moveCapo(capoNow() + 1));
  $("reset-capo").addEventListener("click", () => moveCapo(sheetCapo));
  $("t-down").addEventListener("click", () => step(state.t - 1));
  $("t-up").addEventListener("click", () => step(state.t + 1));
  $("smaller").addEventListener("click", () => { state.fs = Math.max(FS.min, state.fs - FS.step); render(); });
  $("bigger").addEventListener("click", () => { state.fs = Math.min(FS.max, state.fs + FS.step); render(); });
  $("strip-toggle").addEventListener("click", () => { state.strip = !state.strip; render(); });
  $("reset-all").addEventListener("click", () => {
    Object.assign(state, { t: Number(data.transpose) || 0, mode: null, alt: {}, at: {}, capo: null });
    for (const i of Object.keys(atSeen)) delete atSeen[i];  // the version's shapes are for its own chords
    adopt(start);  // the song's own version, if it has one
    render();
  });

  // --- scrolling by itself, hands on the guitar ----------------------------------------------------
  // Off, counting down (3 s, for your hands to get to the guitar; pressed again, it starts at
  // once), running, or paused. While it is on, the pill steers it, above the bar's place: − and +
  // change the speed as it runs, ❚❚ pauses and ▶ resumes (after a countdown again), × ends it; the
  // bar is out of the way while it counts down and runs (dock()). A finger on the page, the wheel, a
  // key that scrolls, a scroll by hand, a card opening or the end of the song pauses it: the page and
  // the bar are yours until you press ▶, which stays within reach with the card open.
  const COUNTDOWN = 3000;
  const scroll = { state: "off", from: 0, travelled: 0, last: 0, at: 0, ends: 0, timer: 0, loop: 0 };
  const moving = () => scroll.state === "counting" || scroll.state === "running";
  // Pixels a second: a bigger text scrolls as much faster, so a speed keeps its pace through the song.
  const pace = () => (state.speed * SPEED.px * state.fs) / FS.start;
  const LABELS = { counting: "Start now", running: "Pause", paused: "Resume" };
  const showScroll = (said) => {
    pill.hidden = scroll.state === "off";
    if (scroll.state === "off") delete doc.dataset.pill;
    else doc.dataset.pill = scroll.state;  // room under the song for the pill
    dock();  // the bar, away or back
    pill.dataset.state = scroll.state;
    go.setAttribute("aria-label", LABELS[scroll.state] || "Pause");
    $("tick").textContent = scroll.state === "counting"
      ? String(Math.max(1, Math.ceil((scroll.ends - performance.now()) / 1000))) : "";
    if (said !== undefined) $("scroll-status").textContent = said;
  };
  const drawSpeed = () => {
    $("pill-speed").textContent = String(state.speed);
  };
  const setSpeed = (n) => {
    state.speed = Math.max(SPEED.min, Math.min(SPEED.max, n));
    drawSpeed();
    save();
  };

  // The screen stays on while it counts down and scrolls. A browser lets go of the lock when the
  // page is hidden; it is asked for again when the page shows.
  let wake = null, asking = false;
  const holdScreen = () => {
    if (wake || asking || !navigator.wakeLock) return;
    asking = true;
    try {
      navigator.wakeLock.request("screen").then((lock) => {
        asking = false;
        if (!moving()) {
          lock.release().catch(() => {});
          return;
        }
        wake = lock;
        lock.addEventListener("release", () => { if (wake === lock) wake = null; });
      }, () => { asking = false; });
    } catch (err) {
      asking = false;  // no wake lock here
    }
  };
  const letScreenSleep = () => {
    const lock = wake;
    wake = null;
    if (lock) lock.release().catch(() => {});
  };
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && moving()) holdScreen();
  });

  const countdown = () => {
    clearTimeout(scroll.timer);
    scroll.state = "counting";
    scroll.ends = performance.now() + COUNTDOWN;
    const tick = () => {
      const left = scroll.ends - performance.now();
      if (left <= 0) {
        run();
        return;
      }
      showScroll();
      scroll.timer = setTimeout(tick, left % 1000 || 1000);
    };
    tick();
    showScroll("Scrolling in " + COUNTDOWN / 1000 + " seconds");
    holdScreen();
  };
  // Each frame scrolls to a whole pixel counted from where it began, Math.round(from + travelled),
  // never a pixel on from where the page is: a browser that rounds a scroll to its device pixels
  // (WebKit at a zoom other than 100 %, bug 281786) would lose every such step and stall.
  const run = () => {
    clearTimeout(scroll.timer);
    scroll.state = "running";
    scroll.from = scroll.at = window.scrollY;
    scroll.travelled = 0;
    scroll.last = 0;
    const loop = ++scroll.loop;
    const frame = (now) => {
      if (scroll.state !== "running" || loop !== scroll.loop) return;
      // Moved some other way (the scroll bar, a search in the page, a link): yours to read.
      if (Math.abs(window.scrollY - scroll.at) > 3) {
        pauseScroll();
        return;
      }
      if (scroll.last) {
        // A frame long in coming (a tab in the background) moves no further than a quarter second.
        scroll.travelled += (Math.min(now - scroll.last, 250) / 1000) * pace();
        const y = Math.round(scroll.from + scroll.travelled);
        if (y !== Math.round(scroll.at)) {
          window.scrollTo(0, y);
          scroll.at = window.scrollY;
        }
        if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
          pauseScroll("Paused at the end of the song");
          return;
        }
      }
      scroll.last = now;
      requestAnimationFrame(frame);
    };
    showScroll("Scrolling");
    holdScreen();
    requestAnimationFrame(frame);
  };
  function pauseScroll(said) {
    if (!moving()) return;
    clearTimeout(scroll.timer);
    scroll.state = "paused";
    showScroll(said || "Paused");
    letScreenSleep();
  }
  const endScroll = () => {
    const mine = pill.contains(document.activeElement);
    clearTimeout(scroll.timer);
    scroll.state = "off";
    showScroll("");
    letScreenSleep();
    if (mine) $("scroll").focus({ preventScroll: true });
  };

  $("scroll").addEventListener("click", () => {
    closeAll();
    showSizes(false);
    countdown();
    go.focus({ preventScroll: true });  // press it again, or Enter, to start at once
  });
  go.addEventListener("click", () => {
    if (scroll.state === "counting") run();
    else if (scroll.state === "running") pauseScroll();
    else countdown();
  });
  $("pill-end").addEventListener("click", endScroll);
  for (const b of document.querySelectorAll("[data-speed]")) {
    b.addEventListener("click", () => setSpeed(state.speed + Number(b.dataset.speed)));
  }
  window.addEventListener("touchstart", (e) => {
    if (!(e.target instanceof Element && e.target.closest("#pill"))) pauseScroll();
  }, { passive: true });
  window.addEventListener("wheel", () => pauseScroll(), { passive: true });
  const SCROLL_KEYS = ["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End"];
  document.addEventListener("keydown", (e) => {
    const control = e.target instanceof Element && e.target.closest("button, a, [role=button], summary, input");
    if (SCROLL_KEYS.indexOf(e.key) >= 0 || (e.key === " " && !control)) pauseScroll();
  });

  // --- the bar: away as you read down the song, back when you want it -----------------------------
  // It slides away as you scroll down, and comes back as you scroll up, at the top and the end of
  // the song, on a tap on the page (not on one of its controls) or when the keyboard's focus comes to
  // it. Only your own scrolling moves it: none before you first touch the page (the browser, or the
  // songbook, putting you back where you were), and none just after a change of key or text size,
  // when the browser keeps the line you were reading in place by scrolling. It stays while the size
  // box or a sheet is open, and while one of its controls has the keyboard's focus, which would
  // otherwise go out of sight.
  const reveal = { y: window.scrollY, quiet: 0, touched: false };
  function hush() {
    if (doc.dataset.ready === "1") reveal.quiet = performance.now() + 400;
  }
  function slide(away) {
    bar.classList.toggle("away", away);
    if (away) showSizes(false);
  }
  const keyboardIn = (el) => {
    try {
      return Boolean(el.querySelector(":focus-visible"));
    } catch (err) {  // a browser without :focus-visible: any focus counts
      return el.contains(document.activeElement);
    }
  };
  for (const kind of ["touchstart", "pointerdown", "wheel", "keydown"]) {
    window.addEventListener(kind, () => { reveal.touched = true; }, { passive: true, capture: true });
  }
  window.addEventListener("scroll", () => {
    const y = window.scrollY, dy = y - reveal.y;
    if (y <= 0 || window.innerHeight + y >= document.documentElement.scrollHeight - 2) {
      slide(false);
      reveal.y = y;
      return;
    }
    if (!reveal.touched || performance.now() < reveal.quiet || !sizes.hidden || !panel.hidden || !card.hidden
        || keyboardIn(bar)) {
      reveal.y = y;
      return;
    }
    if (Math.abs(dy) < 8) return;  // a few pixels add up before they count
    slide(dy > 0);
    reveal.y = y;
  }, { passive: true });
  document.addEventListener("click", (e) => {
    const target = e.target instanceof Element ? e.target : null;
    if (target && !target.closest("#bar, #pill, .sheet-ui, a, button, summary, input, [role=button]")) slide(false);
  });
  bar.addEventListener("focusin", () => slide(false));

  // Nothing to transpose and no other setting for a sheet without chords: Aa and ▶ alone.
  $("keys").hidden = count === 0;
  more.hidden = count === 0;
  showScroll();
  render();
  if (hash.get("panel") === "1") open(panel, null);
  if (hash.has("chord")) openCard(String(hash.get("chord")));
  doc.dataset.ready = "1";
})();
