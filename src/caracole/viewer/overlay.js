(() => {
  "use strict";
  // The overlay: the rail on the left of a wide screen (from 1200 px, viewer.css), with two tabs, Guitar and
  // Harmonica, for the sheet viewer and a songbook (viewer.js) and a harmonica tab's page (harptab.js), which inline
  // it before their own script; narrower, the phone's sheet, the same overlay slid up from the bar (its neck button)
  // over half the screen, or the whole of it, a dialog that is not modal. Every element is made with createElement,
  // createElementNS and textContent; nothing is loaded, nothing sounds, and nothing here computes music theory: each
  // page hands it what Python made (page.py, harp.py, harptab_page.py), looked up for where the song is played.
  //
  // window.caracoleOverlay:
  //   NECKS                    the browser's name for whether the rail shows ("shown", "hidden"): the screen's
  //                            choice, kept once for every page that has the rail; the sheet has no such choice
  //   keyNeck(spec)            the key's neck, a <section class="kn">: its scale, or its pentatonic box, across 15
  //                            frets, the tonic marked; ``spec``: {name ("Am"), tonic (its pitch class), tonicName,
  //                            scale and pentatonic (steps above the tonic), pentaName ("minor pentatonic"), tuning
  //                            (each open string, low first), box (the pentatonic shown), onSwitch(which): "scale"
  //                            or "penta", pressed}
  //   rail(aside, page)        draws the overlay into ``aside`` (the page's <aside class="necks">) on each draw(),
  //                            the tab shown kept from one draw to the next, the first by default, as the rail or
  //                            as the sheet (page.sheet()); the page shows or hides the aside itself. Returns
  //                            {draw(), tab() (the tab shown), empty() (nothing in it, the rail's again: as the
  //                            page hides it), landing() (where the focus goes as the sheet opens: the tab shown,
  //                            else its handle)}. ``page``:
  //     first                  "guitar" or "harmonica": the tab a page opens on, first in the control too
  //     guitar()               the Guitar tab, or null for none (a harmonica tab's page with no sheet): {name (the
  //                            instrument whose necks, in short: "Guitar", "Ukulele", "Baritone"), strings, key (a
  //                            keyNeck spec, or null),
  //                            chords: [{name, list (its positions: voicings.py), mine (how many are the sheet's),
  //                            chosen (the one played)}], each chord shown once, in the order it first comes}
  //     harmonica()            the Harmonica tab: {key: null, none (a line: why there is no harp), plain (or null: a
  //                            harp to show the notes of, {name, tonic, names, holes})}, or the song's key as it sounds,
  //                            the harp tables (harp.py) for the mode played, the chords and the harp chosen:
  //                              key ("Bm"), tonic (its pitch class), names (each pitch class's name in that key),
  //                              harpKeys (each harp's name, by its key's pitch class), ring (harpRing), holes
  //                              (harpHoles), scales (harpScales[mode]), outside (harpOutside[mode]), choices
  //                              (harps[mode]: [position, offset, label]), chords ([{name (as it sounds), shape (as
  //                              the sheet shows it, "" when the same), root (its root's name, as it sounds), entries
  //                              (the 12 harps' entries, by offset: harpForms), notes (its notes, as steps)}]), chosen
  //                              (the harp's offset above the tonic), tabs (the offsets of the harps the song's
  //                              harmonica tabs play on)
  //     pick(name, p)          position ``p`` of the chord ``name`` picked, on its neck or in its legend
  //     chooseHarp(offset)     a harp tapped on the circle
  //     hide()                 the rail's Hide pressed
  //     sheet()                null for the rail; "half" or "full" for the phone's sheet, open at half the screen or
  //                            the whole of it: drawn with its handle (half to whole and back) and ✕ in place of
  //                            Hide, and named a dialog ("Necks and harps", data-sheet: viewer.css)
  //     grow()                 the sheet's handle pressed
  //     close()                the sheet's ✕ pressed
  //   The page draws the rail again after each of these (draw()). A step is a note as semitones above the tonic,
  //   named names[(tonic + step) % 12]; a text, a list of strings and steps.
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
  const chip = (text, pressed, onClick) => {
    const b = el("button", "chip", null, text);
    b.type = "button";
    b.setAttribute("aria-pressed", pressed ? "true" : "false");
    b.addEventListener("click", onClick);
    return b;
  };
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)");
  const NECKS = "caracole-viewer-necks";
  const SIDEBAR = "M3 2h10a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm0 1.5a.5.5 0 0 0-.5.5v8"
    + "a.5.5 0 0 0 .5.5h10a.5.5 0 0 0 .5-.5V4a.5.5 0 0 0-.5-.5zM3.5 4.5h3v7h-3z";  // as the bar's button draws it

  // --- the guitar: a neck per chord, and the key's ------------------------------------------------------------------
  // A neck's strings, frets, nut and inlays (the 12th fret's two), ``strings`` across, the first on top: a chord's
  // neck and the key's.
  const fretboard = (root, strings, frets) => {
    const left = 14, top = 9, cell = 19, gap = 9, last = strings - 1;
    for (let s = 0; s < strings; s++) {
      svg("line", { class: "nk-string", x1: left, y1: top + s * gap, x2: left + cell * frets, y2: top + s * gap }, root);
    }
    for (let f = 1; f <= frets; f++) {
      svg("line", { class: "nk-fret", x1: left + f * cell, y1: top, x2: left + f * cell, y2: top + gap * last }, root);
    }
    svg("rect", { class: "nk-nut", x: left - 1.5, y: top - 1, width: 3, height: gap * last + 2 }, root);
    for (const f of [3, 5, 7, 9, 12, 15]) {
      if (f > frets) continue;
      const x = left + (f - 0.5) * cell, mid = top + gap * last / 2;
      for (const dy of f === 12 ? [-0.3, 0.3] : [0]) svg("circle", { class: "nk-inlay", cx: x, cy: mid + dy * gap * last, r: 1.8 }, root);
    }
  };
  // A chord's positions along the neck of the instrument played (``strings`` of them, six on a guitar, four on a
  // ukulele), frets 0 to ``frets``, the first string (the high e) on top: each position's dots
  // at absolute frets (a position's fret n is n + base - 1 up the neck), in its own colour (p0 to p3,
  // round again after four; the first ``mine`` are the tab's own, marked), open strings as rings at the nut, muted strings nothing. ``chosen``
  // is drawn bolder, last. Every dot carries its position (data-p) and fret (data-fret).
  // A note several positions play is a smaller dot for each, side by side along the string in the order of
  // the positions (the first on the left), so none hides another and each is its own to click: inside its
  // fret's cell, shrunk to fit for three or more, their outlines thinner (few); at the nut, left of it, the neck
  // widened to the left for them, and drawn that much wider, so its frets stay under the other necks' frets.
  const neck = (positions, opts) => {
    const frets = opts.frets || 15;
    const strings = opts.strings || 6, last = strings - 1;
    const left = 14, top = 9, cell = 19, gap = 9;
    const notes = positions.map(([shape, , base]) => {
      const up = (Number(base) || 1) - 1, out = [];
      for (let s = 0; s < strings; s++) if (shape[s] !== "x") out.push([s, shape[s] === "0" ? 0 : Number(shape[s]) + up]);
      return out;
    });
    const sharing = new Map();  // "string.fret": the positions that play it, in order
    notes.forEach((list, p) => list.forEach(([s, fret]) => {
      const k = s + "." + fret;
      if (!sharing.has(k)) sharing.set(k, []);
      sharing.get(k).push(p);
    }));
    // n dots on one note: 6.4 apart, 2.9 across (3.6 the chosen one); for more than two, smaller and outlined
    // thinner (viewer.css: half the chosen's outline, 1 or 0.6, beyond its radius), so the outermost stays 8
    // from the middle: inside the cell, clear of the nut.
    const sizes = (n) => {
      const few = n > 2, out = few ? 0.6 : 1, k = Math.min(1, (8 - out) / (3.2 * (n - 1) + 3.6));
      return { step: 6.4 * k, r: 2.9 * k, bold: 3.6 * k, out, few };
    };
    const openRight = left - 2;  // where shared open strings end, short of the nut
    let margin = 0;  // the room shared open strings take left of the picture
    for (const [k, ps] of sharing) {
      if (ps.length < 2 || !k.endsWith(".0")) continue;
      const z = sizes(ps.length);
      margin = Math.max(margin, Math.ceil(1 + (z.bold + z.out) * 2 + z.step * (ps.length - 1) - openRight));
    }
    const width = left + cell * frets + 4, height = top * 2 + gap * last;
    const label = (positions.length === 1 ? "1 position" : positions.length + " positions");
    const root = svg("svg", { class: "neck", viewBox: -margin + " 0 " + (width + margin) + " " + height, role: "img",
      "aria-label": (opts.name || "") + ": " + label });
    if (margin) {
      root.style.width = "calc(100% * " + (width + margin) / width + ")";
      root.style.marginLeft = "calc(-100% * " + margin / width + ")";
    }
    fretboard(root, strings, frets);
    const order = positions.map((_, p) => p).filter((p) => p !== opts.chosen);
    if (opts.chosen >= 0 && opts.chosen < positions.length) order.push(opts.chosen);
    for (const p of order) {
      const bold = p === opts.chosen;
      for (const [s, fret] of notes[p]) {
        const attrs = { class: (fret === 0 ? "nk-open" : "nk-dot") + " p" + (p % 4) + (bold ? " chosen" : "") + (p < (opts.mine || 0) ? " tabs" : ""),
          cy: top + (last - s) * gap, r: bold ? 4.2 : 3.2, "data-p": p, "data-fret": fret };
        attrs.cx = fret === 0 ? left - 7 : left + (fret - 0.5) * cell;
        const ps = sharing.get(s + "." + fret), n = ps.length, i = ps.indexOf(p);
        if (n > 1) {
          const z = sizes(n);
          attrs.r = bold ? z.bold : z.r;
          if (z.few) attrs.class += " few";
          attrs.cx = fret === 0 ? openRight - (z.bold + z.out) - (n - 1 - i) * z.step : attrs.cx + (i - (n - 1) / 2) * z.step;
        }
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
  // The key's neck: its scale, or its pentatonic box, across the frets, the tonic marked. In the key of the shapes
  // played: with a capo, the frets count from it, as the chords' necks do. The Guitar tab's first neck; on a phone,
  // the Harmony panel's (viewer.js). Scale or the pentatonic switches it.
  const keyNeck = (spec) => {
    const box = Boolean(spec.box);
    const steps = (box ? spec.pentatonic : spec.scale) || [];
    const group = el("section", "kn");
    const penta = String(spec.pentaName || "pentatonic");
    const head = el("p", "kn-name", group, spec.name + " " + (box ? penta : "scale"));
    const chips = el("div", "chips kn-switch", group);
    chips.dataset.f = "kn";
    chips.appendChild(chip("Scale", !box, () => spec.onSwitch("scale")));
    chips.appendChild(chip(penta.charAt(0).toUpperCase() + penta.slice(1), box, () => spec.onSwitch("penta")));
    const tuning = spec.tuning || [], strings = tuning.length, last = strings - 1;
    const frets = 15, left = 14, top = 9, cell = 19, gap = 9;
    const root = svg("svg", { class: "neck key-neck", viewBox: "0 0 " + (left + cell * frets + 4) + " " + (top * 2 + gap * last),
      role: "img", "aria-label": head.textContent + ": the tonic, " + spec.tonicName + ", marked" }, group);
    fretboard(root, strings, frets);
    for (let s = 0; s < strings; s++) {
      for (let f = 0; f <= frets; f++) {
        const step = mod12(tuning[s] + f - spec.tonic);
        if (steps.indexOf(step) < 0) continue;
        svg("circle", { class: "kn-dot" + (step === 0 ? " tonic" : "") + (f === 0 ? " open" : ""),
          cx: f === 0 ? left - 7 : left + (f - 0.5) * cell, cy: top + (last - s) * gap, r: step === 0 ? 4.2 : 3.2,
          "data-string": s, "data-fret": f }, root);
      }
    }
    return group;
  };
  // The Guitar tab: the key's neck, then each chord with every position of it along a neck and a legend naming them.
  // A legend is a group of radio buttons: one Tab stop a chord, on the shape played, and the arrows go from shape to
  // shape.
  const guitarPane = (pane, model) => {
    if (model.key) pane.appendChild(keyNeck(model.key));
    for (const chord of model.chords) {
      const group = el("div", "nk", pane);
      group.dataset.name = chord.name;
      el("p", "nk-name", group, chord.name);
      if (!chord.list.length) {
        el("p", "nk-none", group, "No shape to show for this chord.");
        continue;
      }
      const chosen = Math.min(chord.chosen || 0, chord.list.length - 1);
      group.appendChild(neck(chord.list, { name: chord.name, chosen, mine: chord.mine, strings: model.strings || 6,
        frets: Math.max(15, ...chord.list.map(topFret)) }));
      const legend = el("div", "nk-legend", group);
      legend.setAttribute("role", "radiogroup");
      legend.setAttribute("aria-label", chord.name);
      legend.dataset.f = "nk:" + chord.name;
      neckLabels(chord.list, chord.mine).forEach((words, p) => {
        const b = el("button", "", legend);
        b.type = "button";
        b.setAttribute("role", "radio");
        b.setAttribute("aria-checked", p === chosen ? "true" : "false");
        b.tabIndex = p === chosen ? 0 : -1;
        b.dataset.p = String(p);
        const swatch = el("span", "sw p" + (p % 4) + (p < chord.mine ? " tabs" : ""), b);
        swatch.setAttribute("aria-hidden", "true");
        b.appendChild(document.createTextNode(words));
      });
    }
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

  // --- the harmonica ------------------------------------------------------------------------------------------------
  const nameOf = (m, step) => m.names[mod12(m.tonic + step)];
  const textOf = (m, text) => (Array.isArray(text) ? text.map((part) => (typeof part === "number" ? nameOf(m, part)
    : String(part))).join("") : "");
  const harpName = (m, offset) => m.harpKeys[mod12(m.tonic + offset)] + " harp";
  const an = (name) => (/^[AEF]/.test(name) ? "an " : "a ") + name;
  const ringAt = (m, offset) => {
    const i = m.ring.findIndex((r) => r[0] === offset);
    return i < 0 ? null : { i, position: i + 1, ordinal: m.ring[i][1], mode: m.ring[i][2] };
  };
  // "4th position, aeolian"; in short, "4th, aeolian".
  const positionWords = (m, offset, short) => {
    const at = ringAt(m, offset);
    return at ? at.ordinal + (short ? "" : " position") + (at.mode ? ", " + at.mode : "") : "";
  };
  const listed = (xs) => (xs.length > 1 ? xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1] : xs[0] || "");
  // What the harp plays of the song's chords: each it plays whole or as its triad, then each as its minor stand-in.
  const playsLine = (m, offset) => {
    const whole = [], subs = [];
    for (const c of m.chords) {
      const entry = c.entries ? c.entries[offset] : null;
      if (!entry) continue;
      if (entry[0] === "minor") subs.push(c.name + " as " + c.root + entry[4]);
      else whole.push(c.name);
    }
    if (!whole.length && !subs.length) return "Plays none of the song's chords: melody only.";
    return "Plays " + (whole.length ? listed(whole) + (subs.length ? "; " + listed(subs) : "") : listed(subs)) + ".";
  };
  // What a chord's card says of its run: "draw 4–6", "blow 1–3 · as F#, its triad", "draw 4–6 · as Em, the minor
  // stand-in", or that the harp has no such chord.
  const runLine = (c, entry) => {
    if (!entry) return "no chord here: its notes, one hole at a time";
    const where = entry[1] + " " + entry[2] + "–" + entry[3];
    if (entry[0] === "part") return where + " · as " + c.root + entry[4] + ", its triad";
    if (entry[0] === "minor") return where + " · as " + c.root + entry[4] + ", the minor stand-in";
    return where;
  };

  // The circle of fifths, small: the song's key in the middle as it sounds, the 12 harps round it, the 1st position
  // at the top and counted round the other way (↺), each a fifth below the one before; those harp.py's choices pick
  // shaded on a soft band, the one chosen in the accent, the rest plain, an ordinal outside each of the first and the
  // one chosen. A radio group: a tap or Enter on a harp chooses it; the arrows go round the circle.
  const W = 172, MID = W / 2, R = 56, DOT = 12.5, ORD = 77, BAND = 27;
  const angle = (i) => (-90 - i * 30) * Math.PI / 180;
  const at = (i, r) => [MID + r * Math.cos(angle(i)), MID + r * Math.sin(angle(i))];
  const wheel = (m, chosen) => {
    const picked = new Set(m.choices.map((h) => h[1]));
    const root = svg("svg", { class: "hw-ring", viewBox: "0 0 " + W + " " + W, role: "radiogroup",
      "aria-label": "Harp, for " + m.key });
    root.dataset.f = "ring";
    svg("circle", { class: "hw-track", cx: MID, cy: MID, r: R }, root);
    // The band under each run of picked harps side by side on the circle.
    const on = m.ring.map((r) => picked.has(r[0]));
    for (let i = 0; i < 12; i++) {
      if (!on[i] || (on[mod12(i - 1)] && on.some((x) => !x))) continue;  // a run starts here
      let n = 0;
      while (n < 11 && on[mod12(i + n + 1)]) n++;
      if (n === 0) {
        const [x, y] = at(i, R);
        svg("circle", { class: "hw-band one", cx: x, cy: y, r: BAND / 2 }, root);
        continue;
      }
      const [x1, y1] = at(i, R), [x2, y2] = at(i + n, R);
      svg("path", { class: "hw-band", "stroke-width": BAND,
        d: "M" + x1 + " " + y1 + " A" + R + " " + R + " 0 " + (n * 30 > 180 ? 1 : 0) + " 0 " + x2 + " " + y2 }, root);
    }
    m.ring.forEach((r, i) => {
      const offset = r[0], [x, y] = at(i, R), name = m.harpKeys[mod12(m.tonic + offset)];
      const g = svg("g", { class: "hw-harp" + (offset === chosen ? " sel" : picked.has(offset) ? " good" : ""),
        role: "radio", "aria-checked": offset === chosen ? "true" : "false", tabindex: offset === chosen ? 0 : -1,
        "aria-label": name + " harp, " + positionWords(m, offset), "data-offset": offset, "data-i": i }, root);
      svg("circle", { class: "hw-hit", cx: x, cy: y, r: DOT + 2.5 }, g);
      svg("circle", { class: "hw-dot", cx: x, cy: y, r: DOT }, g);
      svg("text", { class: "hw-kn", x, y: y + 3.3, "text-anchor": "middle", "aria-hidden": "true" }, g).textContent = name;
      if (offset === chosen || picked.has(offset) || m.tabs.indexOf(offset) >= 0) {
        const [ox, oy] = at(i, ORD);
        svg("text", { class: "hw-ord", x: ox, y: oy + 3, "text-anchor": "middle", "aria-hidden": "true" }, root)
          .textContent = r[1];
      }
    });
    svg("text", { class: "hw-key", x: MID, y: MID + 6, "text-anchor": "middle", "aria-hidden": "true" }, root)
      .textContent = m.key;
    return root;
  };

  // A harp's ten holes: the comb of hole numbers, the blow notes above it, the draw notes below and, on the key's
  // card, each hole's bends beyond its row (the blow bends of holes 7 to 10 above, the draw bends of holes 1 to 6
  // below, the deepest farthest). Each note is its name in a circle, drawn as ``role`` says of it (data-role):
  // tonic, in, out, bent-tonic, bent-in, bent-out on the key's card; run, tone, off on a chord's; plain with no key.
  const CELL = 24, LEFT = 30, WORDS = { blow: "blow", draw: "draw" };
  const harpChart = (m, offset, roleOf, opts) => {
    const holes = m.holes[offset];
    const rows = [];
    if (opts.bends) rows.push(["bend", "blow", 2, 15], ["bend", "blow", 1, 15]);
    rows.push(["note", "blow", 0, 23], ["comb", "", 0, 14], ["note", "draw", 0, 23]);
    if (opts.bends) rows.push(["bend", "draw", 1, 15], ["bend", "draw", 2, 15], ["bend", "draw", 3, 15]);
    let y = 3;
    const placed = rows.map(([kind, breath, depth, h]) => {
      const row = { kind, breath, depth, y: y + h / 2 };
      y += h + 2;
      return row;
    });
    const width = LEFT + CELL * 10 + 2;
    const root = svg("svg", { class: "harp", viewBox: "0 0 " + width + " " + (y + 2), role: "img",
      "aria-label": opts.label });
    const cx = (k) => LEFT + (k + 0.5) * CELL;
    for (const row of placed) {
      const word = row.kind === "note" ? WORDS[row.breath] : row.kind === "bend" && row.depth === 1 ? "bend" : "";
      if (word) svg("text", { class: "hx-lab", x: 0, y: row.y + 3 }, root).textContent = word;
    }
    if (opts.run) {
      const [kind, breath, first, last] = opts.run, row = placed.find((r) => r.kind === "note" && r.breath === breath);
      svg("rect", { class: "hx-run " + breath + (kind === "minor" ? " sub" : ""), x: LEFT + (first - 1) * CELL + 1,
        y: row.y - 12, width: (last - first + 1) * CELL - 2, height: 24, rx: 12 }, root);
    }
    for (const row of placed) {
      if (row.kind === "comb") {
        svg("rect", { class: "hx-comb", x: LEFT, y: row.y - 7, width: CELL * 10, height: 14, rx: 4 }, root);
        for (let k = 0; k < 10; k++) {
          svg("text", { class: "hx-hole", x: cx(k), y: row.y + 3, "text-anchor": "middle" }, root).textContent = String(k + 1);
        }
        continue;
      }
      for (let k = 0; k < 10; k++) {
        let step;
        if (row.kind === "note") step = holes[row.breath][k];
        else {
          const [breath, bent] = holes.bends[k];
          if (breath !== row.breath || bent.length < row.depth) continue;
          step = bent[row.depth - 1];
        }
        const role = roleOf(step, row.kind === "bend", row.breath, k + 1);
        const g = svg("g", { class: "hx " + role + " " + row.breath, "data-role": role, "data-hole": k + 1,
          "data-row": row.kind === "bend" ? "bend" : row.breath, "data-note": nameOf(m, step) }, root);
        if (role === "bent-out") {
          svg("circle", { class: "hx-dot", cx: cx(k), cy: row.y, r: 1.6 }, g);
          continue;
        }
        const small = row.kind === "bend";
        if (role !== "off") svg("circle", { class: "hx-note", cx: cx(k), cy: row.y, r: small ? 6.5 : 10 }, g);
        svg("text", { class: "hx-name" + (small ? " sm" : ""), x: cx(k), y: row.y + (small ? 2.4 : 3),
          "text-anchor": "middle" }, g).textContent = nameOf(m, step);
      }
    }
    return root;
  };
  const swatch = (cls, parent) => {
    const s = el("span", "sw " + cls, parent);
    s.setAttribute("aria-hidden", "true");
    return s;
  };

  // The Harmonica tab: the circle and the harp chosen beside it, the key on that harp, a card per chord.
  const harpPane = (pane, m, ui) => {
    if (!m.key) {
      el("p", "hw-none", pane, m.none || "");
      if (m.plain) {
        const card = el("section", "hk", pane);
        el("p", "hk-name", card, m.plain.name);
        const p = { names: m.plain.names, tonic: m.plain.tonic, holes: m.plain.holes };
        card.appendChild(harpChart(p, 0, () => "plain", { bends: true, label: m.plain.name + ": its holes' notes" }));
      }
      return;
    }
    const chosen = m.chosen;
    const name = harpName(m, chosen);
    const top = el("section", "hw", pane);
    top.appendChild(wheel(m, chosen));
    const side = el("div", "hw-side", top);
    el("p", "hw-name", side, name);
    el("p", "hw-pos", side, positionWords(m, chosen));
    if (m.tabs.indexOf(chosen) >= 0) el("p", "hw-tag", side, "the tab's");
    el("p", "hw-plays", side, playsLine(m, chosen));
    el("p", "hw-hint", pane, "Tap a harp. Shaded: the ones that play the song's chords.");

    // The key on that harp: its scale, its pentatonic or the blues, over the ten holes with their bends.
    const card = el("section", "hk", pane);
    const head = el("p", "hk-name", card, m.key + " on " + an(name));
    el("small", "", head, positionWords(m, chosen));
    const which = Math.min(ui.hk, m.scales.length - 1);
    const chips = el("div", "chips hk-switch", card);
    chips.dataset.f = "hk";
    m.scales.forEach(([words], k) => chips.appendChild(chip(words, k === which, () => {
      ui.hk = k;
      ui.draw();
    })));
    const steps = m.scales[which][1];
    const roleOf = (step, bent) => {
      const kind = step === 0 ? "tonic" : steps.indexOf(step) >= 0 ? "in" : "out";
      return bent ? "bent-" + kind : kind;
    };
    card.appendChild(harpChart(m, chosen, roleOf, { bends: true,
      label: m.key + " on " + an(name) + ": the tonic and the " + m.scales[which][0].toLowerCase() + " marked" }));
    const legend = el("p", "hk-legend", card);
    const item = (cls, words) => {
      const span = el("span", "", legend);
      swatch(cls, span);
      span.appendChild(document.createTextNode(words));
    };
    item("k-tonic", nameOf(m, 0) + ", the tonic");
    item("k-in", which === 0 ? "in the scale" : which === m.scales.length - 1 ? "in the blues scale"
      : "in the pentatonic");
    item("k-bent", "bent");
    el("p", "hk-out", card, textOf(m, m.outside[chosen]));

    // A card per chord, in the order the Guitar tab lists them.
    for (const c of m.chords) {
      const entry = c.entries ? c.entries[chosen] : null;
      const tones = new Set(c.notes || []);
      const box = el("section", "hc", pane);
      const title = el("p", "hc-name", box, c.name);
      if (c.shape) el("small", "", title, c.shape + " shape");
      const inRun = (breath, hole) => Boolean(entry) && entry[1] === breath && hole >= entry[2] && hole <= entry[3];
      box.appendChild(harpChart(m, chosen, (step, bent, breath, hole) => (inRun(breath, hole) ? "run"
        : tones.has(step) ? "tone" : "off"), { run: entry, label: c.name + ": " + runLine(c, entry) }));
      const line = el("p", "hc-run", box);
      swatch(entry ? "b-" + entry[1] : "b-none", line);
      line.appendChild(document.createTextNode(runLine(c, entry)));
    }
  };

  // --- the rail, or the phone's sheet -------------------------------------------------------------------------------
  const SHEET = "Necks and harps";  // the sheet's name, as the bar's neck button says it
  const rail = (aside, page) => {
    const ui = { tab: page.first === "harmonica" ? "harmonica" : "guitar", hk: 0, draw: () => draw() };
    const railName = aside.getAttribute("aria-label") || "Chord necks";
    const sheetNow = () => (typeof page.sheet === "function" ? page.sheet() : null);
    let slim = null, circle = null, head = null;
    // The tabs, in the page's order: Guitar named for the instrument whose necks it shows.
    const tabsOf = (guitar) => {
      const both = [["guitar", guitar ? guitar.name || "Guitar" : null], ["harmonica", "Harmonica"]]
        .filter((t) => t[1]);
      return page.first === "harmonica" ? both.reverse() : both;
    };
    // The rail's head, kept at its top as it scrolls: the tabs (or, with one, its name) and Hide; under it, once the
    // circle has scrolled out of the rail, the slim bar naming the harp, with Change harp. The sheet's has its handle
    // across its top, which reaches down under the tabs' row (viewer.css), and ✕ in place of Hide.
    const headOf = (tabs, m, how) => {
      const box = el("header", "nk-head");  // not a div: the chords' necks are the rail's divs
      if (how) {
        const handle = el("button", "ov-handle", box);
        handle.type = "button";
        handle.setAttribute("aria-label", "Whole screen");
        handle.setAttribute("aria-pressed", how === "full" ? "true" : "false");
        handle.setAttribute("aria-controls", aside.id);
        el("span", "ov-grip", handle).setAttribute("aria-hidden", "true");
      }
      const row = el("div", "nk-row", box);
      if (tabs.length > 1) {
        const control = el("div", "seg ov-tabs", row);
        control.setAttribute("role", "tablist");
        control.setAttribute("aria-label", "The rail");
        control.dataset.f = "tabs";
        for (const [id, words] of tabs) {
          const b = el("button", "", control, words);
          b.type = "button";
          b.id = aside.id + "-tab-" + id;
          b.dataset.tab = id;
          b.setAttribute("role", "tab");
          b.setAttribute("aria-selected", id === ui.tab ? "true" : "false");
          b.setAttribute("aria-controls", aside.id + "-pane");
          b.tabIndex = id === ui.tab ? 0 : -1;
        }
      } else {
        el("p", "nk-title", row, tabs.length ? tabs[0][1] : "");
      }
      if (how) {
        const close = el("button", "x ov-close", row, "×");
        close.type = "button";
        close.setAttribute("aria-label", "Close");
      } else {
        const hide = el("button", "nk-hide", row);
        hide.type = "button";
        hide.setAttribute("aria-label", "Hide chord necks");
        hide.setAttribute("aria-controls", aside.id);
        svg("path", { d: SIDEBAR, "fill-rule": "evenodd" }, svg("svg", { viewBox: "0 0 16 16", "aria-hidden": "true" }, hide));
      }
      if (ui.tab === "harmonica" && m && m.key) {
        const clip = el("div", "ov-clip", box);
        slim = el("div", "ov-slim", clip);
        slim.inert = true;
        const words = el("p", "ov-harp", slim);
        el("b", "", words, harpName(m, m.chosen));
        words.appendChild(document.createTextNode(" · " + positionWords(m, m.chosen, true)));
        const up = el("button", "chip ov-change", slim);
        up.type = "button";
        const icon = svg("svg", { viewBox: "0 0 16 16", "aria-hidden": "true" }, up);
        svg("circle", { cx: 8, cy: 8, r: 6.2 }, icon);
        svg("circle", { cx: 8, cy: 8, r: 2.2, class: "fill" }, icon);
        up.appendChild(document.createTextNode("Change harp"));
      }
      return box;
    };
    // The slim bar, in once the circle's foot is above the head's.
    const slide = () => {
      if (!slim || !circle || !head) return;
      const on = circle.getBoundingClientRect().bottom <= head.getBoundingClientRect().bottom;
      if (slim.classList.contains("on") === on) return;
      slim.classList.toggle("on", on);
      slim.inert = !on;
    };
    // The head's own controls, by the name the focus is kept under: Hide is the rail's, ✕ and the handle the
    // sheet's, each of the rail's or the sheet's head standing for the other's as the window crosses 1200 px.
    const OWN = { hide: ".nk-hide", close: ".ov-close", handle: ".ov-handle" };
    const ownOf = (node) => Object.keys(OWN).find((k) => node.matches(OWN[k])) || null;
    // Drawn anew: the focus goes back to the control it was on (its group's checked one: the shape, the harp or the
    // tab now chosen), and the rail stays where it was scrolled to, unless the tab changed.
    const draw = (fresh) => {
      const active = aside.contains(document.activeElement) ? document.activeElement : null;
      const holder = active && active.closest("[data-f]");
      const back = holder ? holder.dataset.f : active && ownOf(active) ? ownOf(active)
        : active && active.classList.contains("ov-change") ? "ring" : null;
      const scrolled = aside.scrollTop;
      const guitar = page.guitar();
      const tabs = tabsOf(guitar);
      if (!tabs.some((t) => t[0] === ui.tab)) ui.tab = tabs[0][0];
      const m = ui.tab === "harmonica" ? page.harmonica() : null;
      const how = sheetNow();
      if (how) {
        aside.dataset.sheet = how;
        aside.setAttribute("role", "dialog");
        aside.setAttribute("aria-label", SHEET);
      } else {
        unmark();
      }
      slim = circle = null;
      aside.textContent = "";
      head = aside.appendChild(headOf(tabs, m, how));
      const pane = el("div", "ov-pane", aside);
      pane.id = aside.id + "-pane";
      pane.dataset.tab = ui.tab;
      if (tabs.length > 1) {
        pane.setAttribute("role", "tabpanel");
        pane.setAttribute("aria-labelledby", aside.id + "-tab-" + ui.tab);
      }
      if (ui.tab === "guitar") guitarPane(pane, guitar);
      else harpPane(pane, m, ui);
      circle = pane.querySelector(".hw");
      aside.scrollTop = fresh ? 0 : scrolled;
      slide();
      if (back) {
        const to = own.call(OWN, back) ? aside.querySelector(OWN[back]) || aside.querySelector(".nk-hide, .ov-close")
          : aside.querySelector('[data-f="' + (window.CSS && CSS.escape ? CSS.escape(back) : back) + '"]');
        const one = to && (to.querySelector('[aria-checked="true"], [aria-selected="true"], [aria-pressed="true"]') || to);
        if (one && typeof one.focus === "function") one.focus({ preventScroll: true });
      }
    };
    // As the rail again, with nothing in it: as the page hides it.
    const unmark = () => {
      delete aside.dataset.sheet;
      aside.removeAttribute("role");
      aside.setAttribute("aria-label", railName);
    };
    const empty = () => {
      slim = circle = head = null;
      aside.textContent = "";
      unmark();
    };
    const showTab = (id) => {
      if (id === ui.tab) return;
      ui.tab = id;
      draw(true);
    };
    aside.addEventListener("scroll", slide, { passive: true });
    aside.addEventListener("click", (e) => {
      const target = e.target instanceof Element ? e.target : null;
      if (!target) return;
      if (target.closest(".nk-hide")) {
        page.hide();
        return;
      }
      if (target.closest(".ov-close")) {
        page.close();
        return;
      }
      if (target.closest(".ov-handle")) {
        page.grow();
        return;
      }
      const tab = target.closest("[role=tab]");
      if (tab) {
        showTab(tab.dataset.tab);
        return;
      }
      if (target.closest(".ov-change")) {
        aside.scrollTo({ top: 0, behavior: calm.matches ? "auto" : "smooth" });
        const harp = aside.querySelector('.hw-harp[aria-checked="true"]');
        if (harp) harp.focus({ preventScroll: true });
        return;
      }
      const harp = target.closest(".hw-harp");
      if (harp) {
        page.chooseHarp(Number(harp.dataset.offset));
        return;
      }
      const group = target.closest(".nk");
      if (!group) return;
      const radio = target.closest("[role=radio]");
      const p = radio ? Number(radio.dataset.p)
        : target.closest("svg.neck") ? nearestPosition(group, e.clientX, e.clientY) : -1;
      if (p >= 0) page.pick(group.dataset.name, p);
    });
    const STEPS = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    aside.addEventListener("keydown", (e) => {
      const target = e.target instanceof Element ? e.target : null;
      if (!target || e.altKey || e.ctrlKey || e.metaKey) return;
      const harp = target.closest(".hw-harp");
      if (harp && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        page.chooseHarp(Number(harp.dataset.offset));
        return;
      }
      if (!own.call(STEPS, e.key)) return;
      const tab = target.closest("[role=tab]");
      const radio = target.closest(".nk [role=radio]");
      if (!tab && !radio && !harp) return;
      e.preventDefault();
      e.stopPropagation();  // in a songbook the arrows go from song to song (book.js), but not from here
      if (tab) {
        const all = Array.from(tab.parentElement.children);
        showTab(all[(all.indexOf(tab) + STEPS[e.key] + all.length) % all.length].dataset.tab);
        const to = aside.querySelector('[role=tab][aria-selected="true"]');
        if (to) to.focus({ preventScroll: true });
      } else if (radio) {
        const all = radio.parentElement.children.length;
        page.pick(radio.closest(".nk").dataset.name, (Number(radio.dataset.p) + STEPS[e.key] + all) % all);
      } else {
        const ring = harp.parentNode.querySelectorAll(".hw-harp");
        const next = ring[mod12(Number(harp.dataset.i) + STEPS[e.key])];
        page.chooseHarp(Number(next.dataset.offset));
      }
    });
    return Object.freeze({ draw: () => draw(false), tab: () => ui.tab, empty,
      landing: () => aside.querySelector('[role=tab][aria-selected="true"]') || aside.querySelector(".ov-handle") || null });
  };

  window.caracoleOverlay = Object.freeze({ NECKS, keyNeck, rail });
})();
