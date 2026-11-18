(() => {
  "use strict";
  // The version line under a song's title, and the list it opens: which of the song's versions this page is, and an
  // icon for each kind of thing the song keeps to play from, with how many of it. Inlined on a sheet viewer's page
  // (sheet.html and a kept version's page, viewer.js) and on a harmonica tab's page (harptab.js) after layers.js and
  // before the page's own script, which attaches it; never in a songbook, whose songs have no versions. It loads
  // nothing: the standard library alone, every element made with createElement and textContent.
  //
  // window.caracoleKinds:
  //   GLYPHS           the library card's drawings of what a song holds (library_assets/rows.js GLYPHS, copied: the
  //                    sheet pages don't inline rows.js; test_viewer_versions.py fails once the two differ), each the
  //                    paths of a stroke in the text's colour on a 24-unit grid: sheet, ukulele, guitar, harmonica,
  //                    score; and rows.js's check, the tick before this page's row in the list.
  //   GLYPH_OF         each kind's glyph, as library_assets/card.js's things draw it (copied, held by the same test):
  //                    the chord sheet's "sheet", UG's Ukulele Chords' "ukulele", a text tab's and a game music tab's
  //                    the guitar's.
  //   attach(o)        draws the line and the list of a page whose data (o.data) has ``versions`` (UG's chords
  //                    versions of the song, render.py _versions_data: sheet_versions.as_data with each entry's
  //                    ``this``, the one's provider ``sheet`` and ``pinned``) or ``kinds`` (what else it keeps to play
  //                    from, render.py _kinds_data: ``sheet``, ``page``, ``groups``), and shows it where the versions
  //                    list any version or the song keeps more than this page alone; null on a page with no
  //                    #versions, or nothing to show. A page that is one of another kind's items (a harmonica tab's,
  //                    its ``page``) names that kind and which of them it is ("Harmonica · Tab 1 of 2"), none of UG's
  //                    versions its own. o: here, this page's file name ("sheet.html"); served, whether
  //                    caracole serve sent it (its /versions page then keeps a version, or makes one the one); sheetPath,
  //                    the page's path in the library ("Artist/Title/sheet.html"), absent for a page of a song with no
  //                    sheet; folder, the song's folder in the library ("Artist/Title"), for caracole serve's Guitar
  //                    Pro page alone, else sheetPath's (a harmonica tab's page of a song with no sheet gives its own:
  //                    the versions' Keep still needs sheetPath); carry(page), the address of another page of the song
  //                    from this one, with what the reader chose for the screen (the text size, the scroll speed, the
  //                    rail of necks...); open(el, opener) and close(el), the page's layers (the list is one);
  //                    inSight(el), whether a layer is in sight.
  //                    Returns { links(), place() }: links() writes each link to another page of the song again,
  //                    with what carry gives now (the page calls it as the reader's choices change); place() puts
  //                    the list, while it is open, where it goes from 900 px wide, a popover under the line
  //                    (layers.js's placeUnder, under #ver-now: the page calls it as a layer opens or closes, a rail
  //                    among them, and as the window resizes); below, the page's stylesheet docks it at the foot, a
  //                    sheet from the bottom, and place() does nothing.
  //
  // The list (page.py _VERSION_LIST's #kind-groups) is a group a kind, section.kind-group[data-kind], each headed by
  // h3.kind-head (its glyph, its name, how many) over an ol.vers of li.ver rows, each row's .ver-main a link where it
  // opens something and none for this page's own, ticked and aria-current="page": Chords first (#ver-acts, what to do
  // with this page's version, then #ver-items, every version UG has, or the chord sheet alone where it lists none),
  // then each other kind the song keeps, in the card's order, each row named as the card names it.

  const own = Object.prototype.hasOwnProperty;
  const SVG = "http://www.w3.org/2000/svg";
  const frozen = (paths) => Object.freeze(paths);
  // rows.js's, path for path.
  const GLYPHS = Object.freeze({
    // a page, its corner folded, with a note on it
    sheet: frozen(["M14 2.5H6.5A1.5 1.5 0 0 0 5 4v16a1.5 1.5 0 0 0 1.5 1.5h11A1.5 1.5 0 0 0 19 20V7.5z", "M14 2.5v5h5",
      "M8.7 17a1.8 1.8 0 1 0 3.6 0a1.8 1.8 0 1 0-3.6 0", "M12.3 17v-6.2l2.7.9"]),
    // a guitar across the grid: its body, sound hole, neck and head
    guitar: frozen(["M10.4 9.6c-1.6-.7-3.6-.3-4.9 1-.7.7-.9 1.6-1.4 2.1-.5.5-1.5.8-1.9 1.7-.6 1.4.2 3.1 1.5 4.4 1.3 1.3 3 " +
      "2.1 4.4 1.5.9-.4 1.2-1.4 1.7-1.9.5-.5 1.4-.7 2.1-1.4 1.3-1.3 1.7-3.3 1-4.9",
    "M7.2 16.8a1.4 1.4 0 1 0 0-2.8a1.4 1.4 0 1 0 0 2.8", "M11 13l8-8", "M17.5 3.5l3 3"]),
    // a ukulele: its round body and sound hole, a short neck
    ukulele: frozen(["M3.8 15a5.2 5.2 0 1 0 10.4 0a5.2 5.2 0 1 0-10.4 0", "M7.7 15a1.3 1.3 0 1 0 2.6 0a1.3 1.3 0 1 0-2.6 0",
      "M13 11l7-7", "M18.5 2.5l3 3"]),
    // a harmonica's front: its covers, and the comb's chambers between them
    harmonica: frozen(["M4 7h16a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z", "M2 10h20M2 14h20",
      "M6 10v4M10 10v4M14 10v4M18 10v4"]),
    // two notes beamed together, as a score writes them
    score: frozen(["M9 18V6l11-2.5v12", "M9 9.5l11-2.5", "M4 18a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0",
      "M15 15.5a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0"]),
    // a tick: this page's row in the list
    check: frozen(["M5 12.5l4.5 4.5L19 7.5"]),
  });
  // card.js's, kind for kind.
  const GLYPH_OF = Object.freeze({ sheet: "sheet", ukulele: "ukulele", guitar: "guitar", tab: "guitar",
    harmonica: "harmonica", gametab: "guitar", score: "score" });
  // A glyph as inline SVG, as rows.js's glyph draws one with no label: unheard, the words beside it name it.
  const glyph = (name) => {
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("class", "glyph glyph-" + name);
    for (const [attr, value] of [["viewBox", "0 0 24 24"], ["width", "1em"], ["height", "1em"], ["fill", "none"],
      ["stroke", "currentColor"], ["stroke-width", "1.8"], ["stroke-linecap", "round"], ["stroke-linejoin", "round"],
      ["focusable", "false"]]) {
      svg.setAttribute(attr, value);
    }
    svg.setAttribute("aria-hidden", "true");
    for (const d of own.call(GLYPHS, name) ? GLYPHS[name] : []) {
      const path = document.createElementNS(SVG, "path");
      path.setAttribute("d", d);
      svg.appendChild(path);
    }
    return svg;
  };
  // The chord sheet's kinds and the line's first word, its group's name; and its row, where UG lists no version of it.
  const SHEETS = { sheet: "Chords", ukulele: "Ukulele chords" };
  const SHEET_ROWS = { sheet: "Chord sheet", ukulele: "Ukulele chords" };
  // Each other kind's group in the list, by its name.
  const NAMES = { guitar: "Guitar Pro", tab: "Guitar tab", harmonica: "Harmonica", gametab: "Game music",
    score: "Score" };
  // Each kind in words, one and more, for what names the icons: "13 chord versions, 2 Guitar Pro files".
  const WORDS = { sheet: ["chord version", "chord versions"], ukulele: ["ukulele chord version", "ukulele chord versions"],
    guitar: ["Guitar Pro file", "Guitar Pro files"], tab: ["guitar tab", "guitar tabs"],
    harmonica: ["harmonica tab", "harmonica tabs"], gametab: ["game music tab", "game music tabs"],
    score: ["score", "scores"] };
  // The sheet the title opens when it is none of UG's versions: LaCuerda's, or an auto sheet standing alone.
  const OTHERS = { lacuerda: { label: "LaCuerda's sheet", page: "sheet.html" },
    auto: { label: "the auto sheet", page: "sheet (auto).html" } };
  const SAYS = {
    keep: "it fetches this version from UG and keeps it beside the sheet.",
    choose: "this version becomes the song's sheet, PDF and songbook entry.",
    clear: "the song goes back to our pick, the best rated version with lyrics.",
  };
  const make = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  };
  const apart = () => make("span", "vh", " · ");  // heard between the parts a row shows apart
  // The song's name as a command names it, quoted for the shell: "Artist - Title".
  const songNamed = () => {
    const title = (document.querySelector("h1") || {}).textContent || "";
    const artist = (document.querySelector(".artist") || {}).textContent || "";
    return "'" + (artist ? artist + " - " + title : title).replace(/'/g, "'\\''") + "'";
  };

  const attach = (o) => {
    const $ = (id) => document.getElementById(id);
    const box = $("versions"), vList = $("version-list"), now = $("ver-now"), line = $("ver-line"), icons = $("kinds");
    const groupsBox = $("kind-groups");
    if (!o || typeof o !== "object" || !box || !vList || !now || !line || !icons || !groupsBox) return null;
    const data = o.data && typeof o.data === "object" ? o.data : {};
    const here = typeof o.here === "string" ? o.here : "";
    const served = Boolean(o.served);
    const sheetPath = typeof o.sheetPath === "string" && o.sheetPath ? o.sheetPath : null;
    const carry = typeof o.carry === "function" ? o.carry : (page) => encodeURIComponent(page);

    // --- the versions -------------------------------------------------------------------------------------------
    // UG's chords versions of the song, in rank order (first the sheet the title opens, when it is none of UG's). In
    // the list a kept version opens, in this tab: the served viewer's sandbox opens no other, and its link takes the
    // reader's choices for the screen along (carry: the key and the rest are this sheet's chords'); one not kept is
    // kept by caracole serve's /versions page, which reads it on UG now, or, from a file, links to UG's page and
    // shows the command that keeps it, with Copy; a version gone from UG opens nothing. Make this the one, and Back
    // to our pick (while your [pin] chooses the sheet), the same way. Each rated "★ 4.86 (408)", or "New".
    const vSource = data.versions && typeof data.versions === "object" ? data.versions : {};
    const vRows = (Array.isArray(vSource.list) ? vSource.list : [])
      .filter((v) => v && typeof v === "object" && typeof v.tab === "string")
      .sort((a, b) => (Number(a.rank) || 0) - (Number(b.rank) || 0));
    const vChosen = vRows.find((v) => v.chosen) || null;
    // This page's version: the one its data says, or, where it says none, the one whose page this is.
    const vHere = vRows.some((v) => typeof v.this === "boolean") ? vRows.find((v) => v.this === true) || null
      : vRows.find((v) => v.page === here && v.chosen) || vRows.find((v) => v.page === here) || null;
    const vOne = vChosen || !own.call(OTHERS, vSource.sheet) ? null : OTHERS[vSource.sheet];
    const vTotal = Number.isInteger(vSource.total) && vSource.total >= vRows.length ? vSource.total : vRows.length;
    const vName = (v) => (Number.isInteger(v.number) ? "Ver " + v.number : "No. " + v.rank);
    // The line's and the list's: "★ 4.86 (408)", or "New" for a version with no rating or no votes yet (the card's rule).
    const stars = (v) => (typeof v.rating !== "number" || !isFinite(v.rating) || !(Number(v.votes) > 0) ? "New"
      : "★ " + v.rating.toFixed(2) + " (" + Number(v.votes).toLocaleString("en") + ")");

    // --- the kinds --------------------------------------------------------------------------------------------------
    // The chord sheet's kind (a page with versions and no ``kinds`` is a chord sheet's), then each other kind the song
    // keeps a file of, in the card's order, as render.py lists them, each counted by its items.
    const kinds = data.kinds && typeof data.kinds === "object" ? data.kinds : null;
    const sheetKind = !kinds ? "sheet" : own.call(SHEETS, kinds.sheet) ? kinds.sheet : null;
    const groups = (kinds && Array.isArray(kinds.groups) ? kinds.groups : [])
      .filter((g) => g && typeof g === "object" && own.call(GLYPH_OF, g.kind) && !own.call(SHEETS, g.kind))
      .map((g) => ({ kind: g.kind, items: (Array.isArray(g.items) ? g.items : [])
        .filter((item) => item && typeof item === "object" && typeof item.name === "string") }))
      .filter((g) => g.items.length > 0);
    // The other pages and files the song has besides this page: the chord sheet's (on a page that isn't it), and
    // each group's but this page's own (a harmonica tab's page is one of its group).
    const elsewhere = (kinds && typeof kinds.page === "string" && kinds.page && kinds.page !== here ? 1 : 0)
      + groups.reduce((n, g) => n + g.items.filter((item) => item.page !== here).length, 0);
    // The group this page is one of, where it is another kind's page (a harmonica tab's), or null.
    const hereIn = here ? groups.find((g) => g.items.some((item) => item.page === here)) || null : null;
    if (vRows.length === 0 && elsewhere === 0) return null;
    const counted = (sheetKind ? [[sheetKind, vRows.length ? vTotal : 1]] : [])
      .concat(groups.map((g) => [g.kind, g.items.length]));

    // --- the line: its kind, which version this page is and its rating; then an icon a kind, with how many ------------
    const drawLine = () => {
      box.hidden = false;
      const words = [hereIn ? NAMES[hereIn.kind] : SHEETS[sheetKind] || SHEETS.sheet];
      if (hereIn) {  // which of its kind's pages: "Tab 1 of 2"
        const n = hereIn.items.findIndex((item) => item.page === here);
        if (hereIn.items.length > 1) words.push("Tab " + (n + 1) + " of " + hereIn.items.length);
      } else if (vHere) {
        if (vTotal > 1) words.push(vName(vHere) + " of " + vTotal);
        if (typeof vHere.label === "string" && vHere.label) words.push(vHere.label);
        words.push(stars(vHere));
      } else if (vOne && vOne.page === here) {
        words.push(vOne.label);
      }
      // A part a box that wraps whole (its " ·" with it), so that a narrow screen breaks the line between two parts,
      // never inside "★ 4.86 (408)"; read as words.join(" · ").
      const said = make("span", "");
      words.forEach((word, n) => {
        if (n) said.appendChild(document.createTextNode(" "));
        said.appendChild(make("span", "vw", n < words.length - 1 ? word + " ·" : word));
      });
      line.textContent = "";
      line.appendChild(said);
      icons.textContent = "";
      icons.appendChild(make("span", "vh", counted.map(([kind, n]) => n + " " + WORDS[kind][n === 1 ? 0 : 1])
        .join(", ")));
      for (const [kind, n] of counted) {
        const icon = make("span", "kind");
        icon.dataset.kind = kind;
        icon.setAttribute("aria-hidden", "true");
        icon.append(glyph(GLYPH_OF[kind]), make("span", "n", String(n)));
        icons.appendChild(icon);
      }
    };

    // --- the list: a group a kind, Chords first --------------------------------------------------------------------
    // Served, a link to caracole serve's page that asks for it; from a file, a button that shows the command.
    const vCommand = (where, what, tab) => {
      for (const old of vList.querySelectorAll(".vcmd")) old.remove();
      const shown = make("div", "vcmd");
      const code = make("code", "cmd", "caracole versions " + songNamed() + " --" + what + (tab ? " " + tab : ""));
      const copy = make("button", "chip", "Copy");
      copy.type = "button";
      copy.addEventListener("click", () => {
        try {
          navigator.clipboard.writeText(code.textContent).then(() => { copy.textContent = "Copied"; }, () => {});
        } catch (err) { /* no clipboard: the command is selectable */ }
      });
      shown.append(code, copy, make("p", "hint", "Run this where caracole is installed: " + SAYS[what]));
      where.appendChild(shown);
    };
    const vAction = (place, text, what, tab, primary, where) => {
      if (served && !sheetPath) return;  // no sheet to name to caracole serve
      const control = make(served ? "a" : "button", primary ? "btn primary" : "link", text);
      if (served) {
        const query = new URLSearchParams();
        query.set("sheet", sheetPath);
        if (tab) query.set("tab", tab);
        query.set("do", what);
        control.setAttribute("href", "/versions?" + query.toString());
      } else {
        control.type = "button";
        control.addEventListener("click", () => vCommand(where || place, what, tab));
      }
      place.appendChild(control);
    };
    // A row of the list: its name, its rating, what it is (the one, kept, this page, gone; a Guitar Pro file "in the
    // browser") and the tabber's note; a link where it opens (``to``: another page of the song by its name, which
    // links() addresses with carry; or a file, {href, download}), none for this page's own, which a tick marks; under
    // it, what you can do with it.
    const vItem = (title, rating, tags, note, to, current) => {
      const li = make("li", "ver");
      const opens = Boolean(to) && !current;
      const main = make(opens ? "a" : "div", "ver-main");
      if (opens && typeof to === "string") {
        main.dataset.page = to;
      } else if (opens) {
        main.setAttribute("href", to.href);
        if (to.download) main.setAttribute("download", to.download);
      }
      if (current) {
        main.setAttribute("aria-current", "page");
        main.appendChild(glyph("check"));
      }
      main.appendChild(make("span", "ver-name", title));
      if (rating) main.append(apart(), make("span", "ver-rate", rating));
      const said = tags.concat(current ? ["this page"] : []).filter(Boolean);
      if (said.length) {
        const tagBox = make("span", "ver-tags");
        said.forEach((tag, n) => {
          if (n) tagBox.appendChild(apart());
          tagBox.appendChild(make("span", tag === "the one" ? "tag one" : "tag", tag));
        });
        main.append(apart(), tagBox);
      }
      if (note) main.append(apart(), make("span", "ver-note", note));
      const acts = make("div", "ver-acts");
      li.append(main, acts);
      return [li, acts];
    };
    // A kind's group: its heading, the kind's glyph, its name and how many, as the line's icon counts it.
    const group = (kind, name, n) => {
      const section = make("section", "kind-group");
      section.dataset.kind = kind;
      const head = make("h3", "kind-head");
      head.append(glyph(GLYPH_OF[kind]), make("span", "", name), make("span", "n", String(n)));
      section.appendChild(head);
      groupsBox.appendChild(section);
      return section;
    };
    // The song's folder in the library, for caracole serve's Guitar Pro page alone: the page's own (o.folder), else
    // its sheet's; none for a page that names neither.
    const folder = typeof o.folder === "string" && o.folder ? o.folder
      : sheetPath ? sheetPath.split("/").slice(0, -1).join("/") : null;
    // Where another kind's row goes: a harmonica tab's page, in this tab, with the reader's choices for the screen;
    // served, a Guitar Pro file caracole serve draws, its Guitar Pro page (/guitar?file=…, "in the browser", as the
    // settings' row); any other file the file itself, a Guitar Pro or Power Tab file and a score but a PDF saved under
    // the song's name (``download``), a text tab, a game music tab and a score's PDF opened.
    const itemTo = (kind, item) => {
      if (kind === "harmonica" && typeof item.page === "string" && item.page) return item.page;
      if (kind === "guitar" && served && item.browser === true && folder !== null) {
        return { href: "/guitar?file=" + encodeURIComponent(folder + "/" + item.name), browser: true };
      }
      const saved = (kind === "guitar" || kind === "score") && typeof item.download === "string" ? item.download : "";
      return { href: encodeURIComponent(item.name), download: saved };
    };
    const drawGroups = () => {
      groupsBox.textContent = "";
      // Chords: what to do with this page's version (#ver-acts), then every version UG has (#ver-items), or, where it
      // lists none of the sheet the title opens, the chord sheet alone first.
      const chords = group(sheetKind || "sheet", SHEETS[sheetKind] || SHEETS.sheet, vRows.length ? vTotal : 1);
      const acts = make("div", "row vrow");
      acts.id = "ver-acts";
      const items = make("ol", "vers");
      items.id = "ver-items";
      chords.append(acts, items);
      if (vHere && !vHere.chosen && !vHere.gone) vAction(acts, "Make this the one", "choose", vHere.tab, true);
      // While a [pin] of yours chooses the sheet (the data's ``pinned``, the pin caracole versions --clear takes
      // out); on a page whose data has no ``pinned`` (written before it), while your choice isn't caracole's first.
      const pick = vRows.find((v) => !v.gone);
      const pinned = typeof vSource.pinned === "boolean" ? vSource.pinned : Boolean(vChosen && pick && pick !== vChosen);
      if (pinned) vAction(acts, "Back to our pick", "clear", null, false);
      acts.hidden = acts.children.length === 0;
      const listed = new Set(vRows.map((v) => v.page).concat(vOne ? [vOne.page] : []));
      if (sheetKind && kinds && typeof kinds.page === "string" && kinds.page && !listed.has(kinds.page)) {
        items.appendChild(vItem(SHEET_ROWS[sheetKind], "", [], null, kinds.page, kinds.page === here)[0]);
      }
      if (vOne) items.appendChild(vItem(vOne.label, "", ["the one"], null, vOne.page, !vHere && vOne.page === here)[0]);
      for (const v of vRows) {
        const [li, todo] = vItem(vName(v) + (v.label ? " · " + v.label : ""), stars(v),
          [v.chosen ? "the one" : v.page ? "kept" : "", v.gone ? "gone from UG" : ""],
          typeof v.note === "string" ? v.note : "", v.page && !v.gone ? v.page : null, v === vHere);
        if (!v.page && !v.gone) {
          if (!served && /^https:\/\//.test(String(v.url || ""))) {
            const ug = make("a", "link", "On UG");
            ug.setAttribute("href", v.url);
            todo.appendChild(ug);
          }
          vAction(todo, "Keep", "keep", v.tab, false, li);
        }
        todo.hidden = todo.children.length === 0;
        items.appendChild(li);
      }
      if (!items.children.length) chords.remove();  // no sheet and no version: a page of another kind's
      // Then each other kind the song keeps, a row a file or a page, named as the card names it.
      for (const g of groups) {
        const list = make("ol", "vers");
        for (const item of g.items) {
          const to = itemTo(g.kind, item);
          const [li, todo] = vItem(typeof item.label === "string" && item.label ? item.label : item.name, "",
            [to.browser ? "in the browser" : ""], null, to, typeof to === "string" && to === here);
          todo.hidden = true;
          list.appendChild(li);
        }
        group(g.kind, NAMES[g.kind], g.items.length).appendChild(list);
      }
    };
    // Each link to another page of the song again, with the reader's choices as they are now.
    const links = () => {
      for (const link of vList.querySelectorAll("a[data-page]")) link.setAttribute("href", carry(link.dataset.page));
    };

    drawLine();
    drawGroups();
    links();
    now.addEventListener("click", () => {
      if (typeof o.inSight === "function" && o.inSight(vList)) {
        if (typeof o.close === "function") o.close(vList);
        return;
      }
      if (typeof o.open === "function") o.open(vList, now);
      const mine = vList.querySelector("[aria-current]");  // this page's, in sight
      if (mine) vList.scrollTop = Math.max(0, mine.parentElement.offsetTop - vList.clientHeight / 3);
    });
    const wide = matchMedia("(min-width: 900px)");
    return Object.freeze({
      links,
      place() {
        if (vList.hidden || !wide.matches || !window.caracoleLayers) return;
        window.caracoleLayers.placeUnder(vList, now);
      },
    });
  };

  window.caracoleKinds = Object.freeze({ GLYPHS, GLYPH_OF, attach });
})();
