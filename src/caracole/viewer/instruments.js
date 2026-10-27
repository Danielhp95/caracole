(() => {
  "use strict";
  // The instruments' pictures of a chord, for the sheet viewer and a songbook (inlined after strum.js, before
  // viewer.js, which calls it), and the place another instrument's script registers its own. Every element is
  // made with createElementNS and textContent; nothing is loaded. What each instrument is (its strings, its capo,
  // where its shapes are filed) is the page's data (``instruments``: viewer/instruments.py); its shapes are the
  // data's too, computed in Python per root: nothing here computes music theory.
  //
  // window.caracoleInstruments:
  //   box(position, title, bare)        a fretted instrument's chord box, as an <svg>: a position as the data has
  //                                     one ([frets, fingers, base fret, barres]: voicings.py), with as many strings
  //                                     as its frets have characters (six, four), drawn left to right in that order;
  //                                     ``bare`` leaves the fingers out (the strip's, too small to read)
  //   keyboard(position, title, bare, span)
  //                                     a piano position ([bass, ...right hand], MIDI notes: instruments.py
  //                                     piano_positions) as a keyboard strip, an <svg>: the right hand's keys lit
  //                                     (kb-on), the bass marked (kb-bass); the keys from the C or F at or below the
  //                                     lowest note to the E or B at or above the highest, of the position or of every
  //                                     position in ``span`` (a list of them), so a card keeps its width from one
  //                                     inversion to the next
  //   register(id, parts)               draws the instrument ``id`` of the data's list, whose kind the viewer doesn't
  //                                     draw itself (a harmonica, a flute: not "strings" or "keys"); the viewer offers
  //                                     it in its Instrument row only once registered, and draws the page again
  //                                     (the event "caracole:instruments" on document). ``parts``, each optional:
  //                                       header(view)  a line of text under the key line, for this instrument alone,
  //                                                     or "" for none
  //                                       diagram(view, chord, bare)
  //                                                     a chord's picture, an Element (the card's, and the strip's,
  //                                                     ``bare``), or null for none
  //                                       panel(view, box)
  //                                                     fills ``box``, the instrument's own row of the settings,
  //                                                     under the Instrument row, emptied before each call
  //                                       notes(view, chord)
  //                                                     the MIDI notes a tap on the chord sounds, struck together
  //                                                     in the instrument's voice (strum.js), or null for none
  //                                     ``view`` is where the page is played, read-only: {data, instrument (its entry
  //                                     in data.instruments), mode, shift (semitones the chords are named from the
  //                                     sheet's key, the capo folded in on an instrument that takes none: the data's
  //                                     tables are by it), key (the key shown, by name, "" for none), names (each pitch
  //                                     class's name in that key), chords (each chord the page shows, once, in the
  //                                     order it first comes: {i, name, rep}, its index in data.chords, its name as
  //                                     shown, and [root, suffix, bass, ...] as played, at ``shift``)}; ``chord`` is
  //                                     one of those
  //   registered(id)                    its ``parts``, or null
  const NS = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs, parent) => {
    const node = document.createElementNS(NS, tag);
    for (const k in attrs) node.setAttribute(k, String(attrs[k]));
    if (parent) parent.appendChild(node);
    return node;
  };

  // A chord box: the strings across one width whatever their number (a ukulele's four further apart than a
  // guitar's six), four frets or more down, the nut or the base fret, barres, open and muted strings, the dots
  // with their fingers. Each string's mark carries its string (data-string, 0 the first drawn) and its fret as the
  // position writes it (data-fret: "x", "0", or the fret from the base fret); the box, its base fret (data-base).
  const box = (position, title, bare) => {
    const frets = String(position[0]);
    const fingers = String(position[1]);
    const first = Number(position[2]) || 1;
    const barres = Array.isArray(position[3]) ? position[3] : [];
    const strings = Math.max(2, frets.length);
    const deepest = Math.max(4, ...Array.from(frets).map((f) => (f === "x" ? 0 : Number(f))));
    const left = 16, top = 16, span = 50, row = 13, gap = span / (strings - 1);
    const width = left + span + 10, height = top + row * deepest + 6;
    const root = svg("svg", { viewBox: "0 0 " + width + " " + height, role: "img", "aria-label": title,
      class: "box", "data-base": first });
    for (let s = 0; s < strings; s++) {
      svg("line", { class: "dg-grid", x1: left + s * gap, y1: top, x2: left + s * gap, y2: top + row * deepest }, root);
    }
    for (let f = 0; f <= deepest; f++) {
      svg("line", { class: "dg-grid", x1: left, y1: top + f * row, x2: left + span, y2: top + f * row }, root);
    }
    if (first === 1) svg("rect", { class: "dg-nut", x: left - 0.5, y: top - 2.5, width: span + 1, height: 3 }, root);
    else svg("text", { class: "dg-fret", x: left - 4, y: top + row / 2 }, root).textContent = first + "fr";
    for (const b of barres) {
      const on = [];
      for (let s = 0; s < strings; s++) if (Number(frets[s]) === b) on.push(s);
      if (on.length < 2) continue;
      const x1 = left + on[0] * gap, x2 = left + on[on.length - 1] * gap, y = top + (b - 0.5) * row;
      svg("rect", { class: "dg-barre", x: x1 - 4.2, y: y - 4.2, width: x2 - x1 + 8.4, height: 8.4, rx: 4.2 }, root);
    }
    for (let s = 0; s < strings; s++) {
      const x = left + s * gap;
      const f = frets[s];
      if (f === "x") {
        svg("path", { class: "dg-mute", d: `M${x - 2.6} ${top - 9.6}l5.2 5.2m0 -5.2l-5.2 5.2`, "data-string": s,
          "data-fret": "x" }, root);
      } else if (f === "0") {
        svg("circle", { class: "dg-open", cx: x, cy: top - 7, r: 2.8, "data-string": s, "data-fret": "0" }, root);
      } else {
        const y = top + (Number(f) - 0.5) * row;
        svg("circle", { class: "dg-dot", cx: x, cy: y, r: 4.2, "data-string": s, "data-fret": f }, root);
        if (!bare && fingers[s] && fingers[s] !== "0") {
          svg("text", { class: "dg-finger", x: x, y: y + 0.3 }, root).textContent = fingers[s];
        }
      }
    }
    return root;
  };

  // A keyboard strip: white keys, the black ones over them, the right hand's keys lit, the bass marked. Each key
  // carries its MIDI note (data-note); a lit one says what it is (data-role: "on", "bass").
  const BLACK = [1, 3, 6, 8, 10];  // the black keys' places in an octave from C
  const notesOf = (position) => (Array.isArray(position) ? position.filter((n) => Number.isInteger(n)) : []);
  const keyboard = (position, title, bare, span) => {
    const shown = notesOf(position);
    const all = (Array.isArray(span) && span.length ? span : [position]).map(notesOf)
      .reduce((out, notes) => out.concat(notes), []);
    const root = svg("svg", { role: "img", "aria-label": title, class: "kb" + (bare ? " bare" : "") });
    if (!shown.length || !all.length) return root;
    const low = Math.min(...all), high = Math.max(...all);
    // From the C or F at or below the lowest note to the E or B at or above the highest: whole halves of octaves.
    let from = low;
    while (from % 12 !== 0 && from % 12 !== 5) from -= 1;
    let to = high;
    while (to % 12 !== 4 && to % 12 !== 11) to += 1;
    const bass = shown[0], lit = new Set(shown.slice(1));
    const white = 10, height = 42, blackWidth = 6, blackHeight = 26;
    const whites = [];
    for (let n = from; n <= to; n++) if (BLACK.indexOf(n % 12) < 0) whites.push(n);
    root.setAttribute("viewBox", "0 0 " + (whites.length * white + 1) + " " + (height + 1));
    const role = (n) => (n === bass ? "bass" : lit.has(n) ? "on" : "");
    const key = (n, attrs) => {
      const r = role(n);
      const rect = svg("rect", Object.assign(attrs, { "data-note": n }), root);
      if (r) rect.setAttribute("data-role", r);
      return rect;
    };
    whites.forEach((n, k) => {
      const r = role(n);
      key(n, { class: "kb-white" + (r ? " kb-" + r : ""), x: k * white + 0.5, y: 0.5, width: white, height, rx: 1.2 });
    });
    for (let n = from; n <= to; n++) {
      if (BLACK.indexOf(n % 12) < 0) continue;
      const k = whites.indexOf(n - 1) + 1;  // the white key after it: it sits on their join
      const r = role(n);
      key(n, { class: "kb-black" + (r ? " kb-" + r : ""), x: k * white + 0.5 - blackWidth / 2, y: 0.5,
        width: blackWidth, height: blackHeight, rx: 1 });
    }
    return root;
  };

  const parts = new Map();
  const register = (id, given) => {
    if (typeof id !== "string" || !id || !given || typeof given !== "object") return;
    parts.set(id, Object.freeze(Object.assign({}, given)));
    document.dispatchEvent(new CustomEvent("caracole:instruments", { detail: { id } }));
  };
  const registered = (id) => parts.get(id) || null;

  window.caracoleInstruments = Object.freeze({ box, keyboard, register, registered });
})();
