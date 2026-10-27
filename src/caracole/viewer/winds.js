(() => {
  "use strict";
  // The harmonica, the flute and the recorder, for the sheet viewer and a songbook: registered with instruments.js
  // (window.caracoleInstruments.register; inlined after it and before viewer.js), which offers them in the settings'
  // Instrument menu. None takes a capo, so the viewer names the chords as they sound (the capo folded in) and the
  // tables are read at the shift that includes it (``view.shift``). Every element is made with createElement,
  // createElementNS and textContent; nothing is loaded; nothing here computes music theory: it looks each answer up
  // in the page's data, which Python made (page.py):
  //
  //   the harmonica   harp.py's tables: data.harps[mode], the harps for the song, best first, each [position,
  //                   offset, label], the harp's key ``offset`` semitones above the key shown (data.harpKeys names it);
  //                   data.harpForms[f][offset], what a chord plays on that harp (null, or [kind, breath, first, last,
  //                   suffix]), its form ``f`` by its index (data.harpChords[mode][i], data.harpAlts[mode][i][j]);
  //                   data.winds.harps[harp key], each harp's notes, [blow, draw], for the sound of its holes.
  //                   Its header line, under the key line: "Harmonica: G harp (1st position) · C harp (2nd)". Its
  //                   picture of a chord: the harp's ten holes, those it plays lit, and what to play ("draw 2–5",
  //                   "draw 4–6 (as Dm, minor substitute)", "not on this harp"), on the harp chosen in its settings
  //                   row (Harp: the harps of the header line, the first by default; this page's choice alone),
  //                   which lists the song's harmonica tabs too (data.harmonicaTabs: a link each to its page beside
  //                   the page, harmonica-N.html, its holes over the words, and to its text, with the key its
  //                   harptabs.com page named, "key C (harptabs.com)", never a harp's).
  //   the flute and   winds.py's tables: data.windForms[f], a chord's notes as steps above its root, its form ``f``
  //   the recorder    by its index (data.windChords[mode][i], data.windAlts[mode][i][j]; mode "" for a sheet with no
  //                   key); each note read is data.winds.low + the root's pitch class as shown + a step, and the key's
  //                   scale data.winds.low + the tonic's + each of data.keyScale[mode], then 12; the notes' names are
  //                   data.tones' for the chord; each note's fingering, data.winds.flute.notes[note - low][0], or
  //                   data.winds.recorder[system][note - low]. Their picture of a chord: its notes, each with its
  //                   fingering; their settings row: the note names (A–G, or Do–Si: data.winds.solfege), the
  //                   recorder's fingering (baroque or German), the key's scale and each chord's notes, fingered.
  //                   The recorder sounds an octave above the notes it reads (data.instruments' ``sounds``).
  //
  // The note names and the recorder's fingering are the player's, kept for every page (localStorage
  // "caracole-viewer-winds": {"names": "letters" | "solfege", "recorder": "baroque" | "german"}), where the browser
  // keeps anything. A choice redraws the page: the event "caracole:instruments" on document, which viewer.js answers
  // by drawing it again, and the focus goes back to the chip pressed.
  const kit = window.caracoleInstruments;
  if (!kit) return;
  const NS = "http://www.w3.org/2000/svg";
  const own = Object.prototype.hasOwnProperty;
  const mod12 = (n) => ((n % 12) + 12) % 12;
  const svg = (tag, attrs, parent) => {
    const node = document.createElementNS(NS, tag);
    for (const k in attrs) node.setAttribute(k, String(attrs[k]));
    if (parent) parent.appendChild(node);
    return node;
  };
  const el = (tag, className, parent, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    if (parent) parent.appendChild(node);
    return node;
  };

  // --- the player's choices -------------------------------------------------------------------------------------
  const PREFS = "caracole-viewer-winds";
  const prefs = { names: "letters", recorder: "baroque" };
  try {
    const kept = JSON.parse(localStorage.getItem(PREFS) || "{}");
    if (kept && kept.names === "solfege") prefs.names = "solfege";
    if (kept && kept.recorder === "german") prefs.recorder = "german";
  } catch (err) { /* no storage: the defaults */ }
  const keep = () => {
    try {
      localStorage.setItem(PREFS, JSON.stringify(prefs));
    } catch (err) { /* no storage: for this page alone */ }
  };
  let harpAt = null;  // the position of the harp chosen on this page; null: the first offered
  const again = (id, chip) => {
    document.dispatchEvent(new CustomEvent("caracole:instruments", { detail: { id } }));
    const to = document.querySelector('[data-wind-chip="' + chip + '"]');
    if (to) to.focus({ preventScroll: true });
  };
  const chipOf = (text, small, pressed, name, onClick) => {
    const b = el("button", "chip", null, text);
    b.type = "button";
    if (small) el("small", "", b, small);
    b.setAttribute("aria-pressed", pressed ? "true" : "false");
    b.dataset.windChip = name;
    b.addEventListener("click", onClick);
    return b;
  };
  const line = (box, label) => {
    const row = el("div", "wd-line", box);
    el("span", "lab", row, label);
    return el("span", "chips", row);
  };

  // --- a chord's row in a table by chord: the sheet's in the mode, else one of its alternatives -----------------
  const same = (a, b) => Array.isArray(a) && Array.isArray(b) && a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
  const formOf = (view, byChord, byAlt, chord) => {
    const d = view.data, mode = view.mode || "", i = Number(chord.i);
    if (!byChord || !byChord[mode]) return null;
    const base = mode ? (d.mapped[mode] || [])[i] : d.chords[i];
    if (same(base, chord.rep)) return byChord[mode][i];
    const options = mode && d.alts[mode] ? d.alts[mode][i] || [] : [];
    const j = options.findIndex((a) => same(a, chord.rep));
    return j >= 0 && byAlt && byAlt[mode] && byAlt[mode][i] ? byAlt[mode][i][j] : null;
  };
  const tonicOf = (view) => mod12(view.data.key.tonic + view.shift);

  // --- the harmonica ------------------------------------------------------------------------------------------------
  const harps = (view) => (view.key && view.data.harps && view.data.harps[view.mode]) || [];
  const harpKey = (view, harp) => mod12(tonicOf(view) + harp[1]);
  const harpName = (view, harp) => view.data.harpKeys[harpKey(view, harp)] + " harp";
  // A harp's position in words, from its label ("1st position", "2nd", "4th, aeolian"): "4th position, aeolian", and
  // in short for its chip, "4th, aeolian".
  const short = (harp) => harp[2].replace(" position", "");
  const position = (harp) => short(harp).replace(/^(\w+)/, "$1 position");
  const chosen = (view) => {
    const list = harps(view);
    return list.find((h) => h[0] === harpAt) || list[0] || null;
  };
  const entryOf = (view, chord, harp) => {
    const f = formOf(view, view.data.harpChords, view.data.harpAlts, chord);
    const form = f === null || f === undefined ? null : view.data.harpForms[f];
    return form ? form[harp[1]] || null : null;
  };
  // What to play, as harp.py's entry_text writes it.
  const entryText = (entry, root) => {
    if (!entry) return "not on this harp";
    const where = entry[1] + " " + entry[2] + "–" + entry[3];
    if (entry[0] === "yes") return where;
    return where + " (as " + root + entry[4] + (entry[0] === "minor" ? ", minor substitute)" : ")");
  };
  // The harp's ten holes in a row, numbered, those the chord plays lit; the svg says what (data-kind: "yes", "part",
  // "minor" or "no"; data-breath, data-holes "2-5").
  const holes = (entry, title, bare) => {
    const cell = 9, height = bare ? 13 : 22;
    const root = svg("svg", { viewBox: "0 0 " + (cell * 10 + 2) + " " + height, role: "img", "aria-label": title,
      class: "hp" + (bare ? " bare" : ""), "data-kind": entry ? entry[0] : "no" });
    if (entry) {
      root.setAttribute("data-breath", entry[1]);
      root.setAttribute("data-holes", entry[2] + "-" + entry[3]);
    }
    for (let k = 1; k <= 10; k++) {
      const on = Boolean(entry) && k >= entry[2] && k <= entry[3];
      svg("rect", { class: "hp-hole" + (on ? " hp-on" : ""), x: 2 + (k - 1) * cell, y: 1, width: cell - 2, height: 10,
        rx: 1.6, "data-hole": k }, root);
      if (!bare) svg("text", { class: "hp-num", x: 1 + (k - 0.5) * cell, y: 20 }, root).textContent = String(k);
    }
    return root;
  };
  // The song's harmonica tabs beside the page (data.harmonicaTabs: harptabs.com's, kept), a link each to its page
  // (``page``: harmonica-N.html, render.py) and one to its text, with the key its page's Key chip named, if any, as
  // harptabs.com's: the song's key on some tabs and the harp's on others, so never called a harp.
  const tabs = (view, box) => {
    const list = Array.isArray(view.data.harmonicaTabs) ? view.data.harmonicaTabs : [];
    if (!list.length) return;
    const part = el("div", "wd-part", box);
    el("p", "wd-title", part, list.length === 1 ? "Harmonica tab" : "Harmonica tabs");
    const links = el("ul", "wd-tabs", part);
    for (const tab of list) {
      if (!tab || typeof tab.href !== "string") continue;
      const item = el("li", "", links);
      const name = String(tab.name || tab.href);
      if (typeof tab.page === "string" && tab.page) {
        el("a", "link", item, name.replace(/\.txt$/, "")).href = tab.page;
        const text = el("a", "wd-text", item, "text");
        text.href = tab.href;
        text.setAttribute("aria-label", name + ", as text");
      } else {
        el("a", "link", item, name).href = tab.href;
      }
      if (tab.key) {
        el("span", "wd-key", item, "key " + tab.key + " (harptabs.com)").title =
          "The key harptabs.com's page names: the song's on some tabs, the harp's on others";
      }
    }
  };
  const harmonica = {
    header(view) {
      const list = harps(view);
      return list.length ? "Harmonica: " + list.map((h) => harpName(view, h) + " (" + h[2] + ")").join(" · ") : "";
    },
    diagram(view, chord, bare) {
      const harp = chosen(view);
      if (!harp) return null;
      const entry = entryOf(view, chord, harp);
      const text = entryText(entry, view.names[chord.root]);
      const strip = holes(entry, chord.name + ": " + text, bare);
      if (bare) return strip;
      const box = el("div", "hp-card");
      box.appendChild(strip);
      el("p", "hp-text", box, text);
      el("p", "hp-harp", box, harpName(view, harp) + ", " + position(harp));
      return box;
    },
    panel(view, box) {
      const list = harps(view);
      if (!list.length) {
        el("p", "hint", box, "With no key, caracole can't tell which harp plays the song.");
        tabs(view, box);
        return;
      }
      const harp = chosen(view);
      const chips = line(box, "Harp");
      list.forEach((h) => chips.appendChild(chipOf(harpName(view, h), short(h), h === harp,
        "harp-" + h[0], () => {
          harpAt = h[0];
          again(view.instrument.id, "harp-" + h[0]);
        })));
      el("p", "hint", box, "The harps that play the song, the best first, and each chord on the one chosen: its "
        + "holes, the minor chord a harp plays for a major one it lacks, or none.");
      const rows = el("ul", "wl", box);
      for (const chord of view.chords) {
        const entry = entryOf(view, chord, harp);
        const text = entryText(entry, view.names[chord.root]);
        const row = el("li", "wl-row", rows);
        row.dataset.chord = chord.name;
        row.appendChild(holes(entry, chord.name + ": " + text, true));
        el("b", "wl-name", row, chord.name);
        el("span", "wl-text", row, text);
      }
      tabs(view, box);
    },
    notes(view, chord) {
      const harp = chosen(view);
      const entry = harp ? entryOf(view, chord, harp) : null;
      const layout = entry && view.data.winds && view.data.winds.harps ? view.data.winds.harps[harpKey(view, harp)] : null;
      if (!layout) return null;
      return (entry[1] === "blow" ? layout[0] : layout[1]).slice(entry[2] - 1, entry[3]);
    },
  };

  // --- the flute and the recorder -------------------------------------------------------------------------------
  const facts = (view) => view.data.winds || null;
  const fingeringOf = (view, note) => {
    const w = facts(view), at = note - w.low;
    if (view.instrument.id === "flute") return (w.flute.notes[at] || [])[0] || null;
    return (w.recorder[prefs.recorder] || [])[at] || null;
  };
  const say = (view, name) => (prefs.names === "solfege" && own.call(facts(view).solfege, name.charAt(0))
    ? facts(view).solfege[name.charAt(0)] + name.slice(1) : name);
  // The chord's notes, each [its name, the note read], in the order data.tones names them.
  const notesOf = (view, chord) => {
    const f = formOf(view, view.data.windChords, view.data.windAlts, chord);
    const steps = f === null || f === undefined ? null : view.data.windForms[f];
    const name = view.names[chord.root] + chord.rep[1] + (chord.bass === null ? "" : "/" + view.names[chord.bass]);
    const named = view.data.tones ? view.data.tones[name] : null;
    if (!steps || !named || !facts(view)) return [];
    const names = named.split("|")[0].split(" ");
    return steps.map((step, k) => [names[k] || "", facts(view).low + chord.root + step]);
  };
  const scaleOf = (view) => {
    const steps = view.key && view.data.keyScale ? view.data.keyScale[view.mode] : null;
    if (!steps || !facts(view)) return [];
    const tonic = tonicOf(view);
    return steps.concat([12]).map((step) => [view.names[mod12(tonic + step)], facts(view).low + tonic + step]);
  };
  // A note's fingering, the instrument's keys or holes down its length: pressed or covered filled, half covered
  // half filled, the others open; the svg says which note (data-note, as read) and how (data-fingering, the page's
  // data's string: "x", "o", "h" a key).
  const FLUTE = {  // where each key is drawn: [x, y, rx, ry]
    "thumb-Bb": [5, 6, 2.2, 1.6], thumb: [5, 13, 3, 3], L1: [15, 13, 4, 4], L2: [15, 23, 4, 4], L3: [15, 33, 4, 4],
    "G#": [22.5, 37, 2.4, 1.7], R1: [15, 48, 4, 4], R2: [15, 58, 4, 4], R3: [15, 68, 4, 4],
    "trill-D": [22.5, 53, 1.8, 1.6], "trill-D#": [22.5, 63, 1.8, 1.6], Eb: [22.5, 74, 2.4, 1.7],
    "C#": [10, 82, 2.4, 1.7], C: [17, 82, 2.4, 1.7],
  };
  const RECORDER = {
    thumb: [5, 8, 3, 3], L1: [15, 14, 3.8, 3.8], L2: [15, 24, 3.8, 3.8], L3: [15, 34, 3.8, 3.8],
    R1: [15, 47, 3.8, 3.8], R2: [15, 57, 3.8, 3.8], R3: [15, 67, 3.8, 3.8], R4: [15, 77, 3.8, 3.8],
  };
  const fingering = (view, note, name) => {
    const states = fingeringOf(view, note);
    const keys = view.instrument.id === "flute" ? facts(view).flute.keys : facts(view).recorder.holes;
    const where = view.instrument.id === "flute" ? FLUTE : RECORDER;
    const root = svg("svg", { viewBox: "0 0 26 88", role: "img", "aria-label": say(view, name) + " fingering",
      class: "wd", "data-note": note, "data-fingering": states || "" });
    if (!states) return root;
    if (view.instrument.id === "flute") svg("line", { class: "wd-split", x1: 9, y1: 40.5, x2: 21, y2: 40.5 }, root);
    keys.forEach((k, n) => {
      const state = states.charAt(n);
      if (k === "bell") {
        svg("rect", { class: "wd-bell" + (state === "x" ? " wd-on" : ""), x: 10, y: 83, width: 10, height: 3, rx: 1,
          "data-key": k }, root);
        return;
      }
      const at = where[k];
      if (!at) return;
      const [x, y, rx, ry] = at;
      const double = view.instrument.id !== "flute" && (k === "R3" || k === "R4");
      if (double) {  // two small holes: both covered, the smaller alone (half), or neither
        svg("circle", { class: "wd-key" + (state === "x" ? " wd-on" : ""), cx: x - 2.4, cy: y, r: 2.4, "data-key": k }, root);
        svg("circle", { class: "wd-key" + (state !== "o" ? " wd-on" : ""), cx: x + 3, cy: y, r: 1.7, "data-key": k }, root);
        return;
      }
      svg("ellipse", { class: "wd-key" + (state === "x" ? " wd-on" : ""), cx: x, cy: y, rx, ry, "data-key": k }, root);
      if (state === "h") {  // half covered: its left half filled
        svg("path", { class: "wd-half", d: `M${x} ${y - ry}A${rx} ${ry} 0 0 0 ${x} ${y + ry}Z`, "data-key": k }, root);
      }
    });
    return root;
  };
  const tones = (view, list) => {
    const row = el("div", "wd-tones");
    for (const [name, note] of list) {
      const one = el("span", "wd-tone", row);
      one.appendChild(fingering(view, note, name));
      el("span", "wd-name", one, say(view, name));
    }
    return row;
  };
  const wind = (id) => ({
    header() {
      return "";
    },
    diagram(view, chord, bare) {
      const list = notesOf(view, chord);
      if (!list.length) return null;
      if (bare) return el("span", "wd-names", null, list.map(([name]) => say(view, name)).join(" "));
      return tones(view, list);
    },
    panel(view, box) {
      if (!facts(view)) return;
      const names = line(box, "Note names");
      for (const [value, text] of [["letters", "A–G"], ["solfege", "Do–Si"]]) {
        names.appendChild(chipOf(text, "", prefs.names === value, "names-" + value, () => {
          prefs.names = value;
          keep();
          again(id, "names-" + value);
        }));
      }
      if (id === "recorder") {
        const systems = line(box, "Fingering");
        for (const [value, text] of [["baroque", "Baroque"], ["german", "German"]]) {
          systems.appendChild(chipOf(text, "", prefs.recorder === value, "recorder-" + value, () => {
            prefs.recorder = value;
            keep();
            again(id, "recorder-" + value);
          }));
        }
      }
      const scale = scaleOf(view);
      if (scale.length) {
        const part = el("div", "wd-part", box);
        el("p", "wd-title", part, view.key + " scale");
        part.appendChild(tones(view, scale));
      }
      const rows = el("ul", "wl", box);
      for (const chord of view.chords) {
        const list = notesOf(view, chord);
        if (!list.length) continue;
        const row = el("li", "wl-row wd-row", rows);
        row.dataset.chord = chord.name;
        el("b", "wl-name", row, chord.name);
        row.appendChild(tones(view, list));
      }
    },
    notes(view, chord) {
      const list = notesOf(view, chord);
      const up = Number(view.instrument.sounds) || 0;
      return list.length ? list.map(([, note]) => note + up) : null;
    },
  });

  kit.register("harmonica", harmonica);
  kit.register("flute", wind("flute"));
  kit.register("recorder", wind("recorder"));
})();
