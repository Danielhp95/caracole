// The sync with another caracole, one flow on both devices (sync-sheet.html, the sheet; on caracole serve's page also
// sync-panel.html, the Sync tab's three panels): what to sync, a card for each conflict, the sync followed to its end,
// and what it did; and a library exported to a file, or a file imported and synced with as if its caracole were here.
// Its words are sync-words.js's (window.caracoleSyncWords); it asks the routes both servers answer alike
// (docs/superpowers/plans/2026-11-03-sync-redesign.md §3.4), every path relative, and puts every text in with
// textContent.
//
// The sheet opens from the Sync tab's buttons (Sync, Export, Choose a file), from the address (#sheet=sync,
// #sheet=export, #sheet=import, which it takes out of the address once open; #tab=sync on a page with no Sync tab,
// the phone's, is #sheet=sync) and, on the phone, from the app's sync button, which loads that address.
//
// - **What to sync**: it compares as it opens (POST /sync/compare with the address, the Sync tab's field's on the
//   computer, the one remembered on the phone; POST /sync/import/compare for a file sent), then shows the three parts
//   ticked, Library, Songbooks and Site indexes, each with what waits in it, and above them what the sync does (↓ to
//   take, ↑ to give, ⚠ changed on both, counted in the parts ticked: a song a songbook lists comes along with
//   Songbooks), with the steps as chips. A part a file doesn't hold is greyed, "Not in this file".
// - **A card for each conflict** in the parts ticked: the unit's name, "1 of N", each side's version told apart
//   (GET /api/sync/unit, once a card), this device on the left; Which version to keep, a button for each side named
//   for it, and Same for the other N, which settles every conflict left the same way. No Skip: Cancel, at any step
//   before Sync goes, ends it with nothing taken or given and nothing sent.
// - **Sync** posts the comparison, the parts and each conflict's side in one field (POST /sync/apply); a refusal says
//   the server's words, and one the server makes because the two changed since (409) compares again.
// - **On its way**: the sync is a request as any (library.js's ``track``, quietly: the sheet says how it goes); its
//   line and its steps as it goes. One on its way as the page loads (the server's ``jobs``) is followed, and the sheet
//   opened then shows it, never another sync.
// - **What it did**: "Synced with:" and the other side's name, when, the two sides as icons, and a section for each
//   kind of change, closed until its chevron opens it: songs taken, songs given (why), the conflicts (whose version was
//   kept, and how it differs), the songbooks, the indexes (each site's tabs before and after, a fall in red). Drawn from
//   the comparison and the choices the sheet holds, and the view's outcome and report (§3.5); from the outcome alone
//   for a sync it didn't start. A file's has no "given" arrow: a file takes nothing back.
// - **Export**: the parts with their sizes (GET /api/sync/sizes), Site indexes unticked; Export makes the file (POST
//   /sync/export) and downloads it (GET /api/sync/export, once), a link, which the phone hands to its share sheet.
// - **Import a file**: the file input (#sync-file: the browser's chooser, the phone's picker), the file sent in parts
//   of 8 MiB, one at a time (POST /sync/import/open, /sync/import/part), then the sheet as a sync, with the file in the
//   other side's place.
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const sheet = byId("sync-sheet");
  const W = window.caracoleSyncWords;
  if (!sheet || !W || typeof sheet.showModal !== "function") return;
  let data;
  try {
    data = JSON.parse(byId("songs").textContent);
  } catch (err) {
    return;
  }
  const server = data && data.server && typeof data.server === "object" ? data.server : null;
  if (!server) return;
  const lib = window.caracoleLibrary || null;
  const tabs = window.caracoleTabs || null;
  const panel = byId("sync");  // the Sync tab's panel: caracole serve's page alone
  const own = Object.prototype.hasOwnProperty;
  const listOf = (v) => (Array.isArray(v) ? v : []);
  const objOf = (v) => (v && typeof v === "object" && !Array.isArray(v) ? v : null);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const icon = (name, cls) => {
    const node = el("span", cls);
    node.dataset.icon = name;
    const template = byId("sync-icon-" + name);
    if (template) node.appendChild(template.content.cloneNode(true));
    return node;
  };
  for (const node of document.querySelectorAll("[data-icon]")) {
    const template = byId("sync-icon-" + node.dataset.icon);
    if (template && !node.firstChild) node.appendChild(template.content.cloneNode(true));
  }

  const title = byId("sync-title");
  const sub = byId("sync-sub");
  const check = byId("sync-check");
  const chips = byId("sync-chips");
  const counts = byId("sync-counts");
  const status = byId("sync-status");
  const cancel = byId("sync-cancel");
  const go = byId("sync-go");
  const fileInput = byId("sync-file");
  const partsBox = byId("sync-parts");
  const boxes = Array.from(sheet.querySelectorAll("input[name=part]"));
  const card = { name: byId("sync-card-name"), at: byId("sync-card-at"), here: byId("sync-card-here"),
                 there: byId("sync-card-there"), keepHere: byId("sync-keep-here"), keepThere: byId("sync-keep-there"),
                 same: byId("sync-same"), sameSaid: byId("sync-same-said"), sameRow: byId("sync-same-row") };
  const goingLine = byId("sync-going-line");
  const goingDetail = byId("sync-going-detail");
  const devs = byId("sync-devs");
  const sections = byId("sync-sections");
  const fileNote = byId("sync-file-note");
  const PANES = { what: byId("sync-what"), conflict: byId("sync-conflict"), going: byId("sync-going"),
                  done: byId("sync-done") };
  if (!title || !sub || !chips || !counts || !status || !cancel || !go || !partsBox || !goingLine || !sections
      || Object.values(PANES).some((v) => !v) || Object.values(card).some((v) => !v)) return;

  const PARTS = ["library", "songbooks", "indexes"];
  // Each kind of unit and its part (peer_sync.part_of): a song a songbook lists comes along with Songbooks too.
  const PART_OF = [["song", "library"], ["removed", "library"], ["songbook", "songbooks"], ["alias", "library"],
                   ["artist_url", "library"], ["block", "library"]];
  const PART_SIZE = 8 * 1024 * 1024;  // an import's part at most (peer_import.PART_MAX)
  const UNREACHABLE = "This caracole didn't answer: reload the page.";
  const TOKEN = String(server.csrf || "");

  // --- the server -------------------------------------------------------------------------------------------------
  const answerOf = (r) => r.json().catch(() => null).then((body) => ({ ok: r.ok, status: r.status, body }));
  // A read, with the form's token in its header: a unit's two documents are the page's own script's alone to ask.
  const ask = (path) => fetch(path, {
    cache: "no-store", headers: { Accept: "application/json", "X-Caracole-Form-Token": TOKEN },
  }).then(answerOf);
  // A form posted as the page's script, with the form's token: its answer as data, never a page.
  const post = (path, fields) => {
    const body = new URLSearchParams({ csrf: TOKEN });
    for (const [name, value] of fields) body.set(name, value);
    return fetch(path, { method: "POST", body, headers: { Accept: "application/json" } }).then(answerOf);
  };
  // A JSON document or bytes, the token in its header.
  const send = (path, body, type) => fetch(path, {
    method: "POST", body, headers: { Accept: "application/json", "Content-Type": type, "X-Caracole-Form-Token": TOKEN },
  }).then(answerOf);
  const refusal = (answer) => (answer && answer.body && typeof answer.body.error === "string" && answer.body.error
    ? answer.body.error : "This caracole answered " + (answer ? answer.status : "nothing") + ": try again.");

  // --- what the sheet holds ------------------------------------------------------------------------------------
  let me = null;  // GET /api/sync's answer: this caracole, its device, the address it synced with last, its peers
  let meAsked = null;
  let flow = "sync";  // the sheet's flow: sync, export or import
  let view = "what";
  let turn = 0;  // each opening and each Cancel a turn of its own: an answer for an earlier one is dropped
  let busy = false;  // a comparison, an upload, an export or a sync's post on its way
  let compared = null;  // the comparison: POST /sync/compare's answer, or /sync/import/compare's
  let source = null;  // whom it compares with: {address} or {import, file}
  const choices = new Map();  // a conflict's unit id -> "here" or "there"
  const kept = new Map();  // a conflict as compared (id, both digests) -> its side, for a comparison again
  const docs = new Map();  // a unit id -> GET /api/sync/unit's {here, there}, or {error}
  let conflicts = [];  // the conflicts the cards ask, in order
  let at = 0;  // the card shown
  let following = null;  // the sync's job id, while it waits or runs
  let sent = null;  // what the sheet sent it with: the comparison, the choices, the parts, the flow
  let ended = null;  // the sync over: its last view and what it was sent with, for the summary
  let sizes = null;  // GET /api/sync/sizes's answer
  let exported = false;  // the export's file made and downloaded: Export is Done

  const device = () => (me && me.device === "phone") || (!me && !panel) ? "phone" : "computer";
  const peerOf = () => objOf(compared && compared.peer) || {};
  const isFile = () => flow === "import" || peerOf().kind === "file";
  const nameOf = () => {
    const peer = peerOf();
    if (isFile()) return String(peer.name || "") || "a caracole";
    const where = source && source.address ? source.address : "";
    const known = listOf(me && me.peers).find((p) => p && p.address === where);
    return String(peer.name || (known && known.name) || where) || "another caracole";
  };
  const sidesNow = () => W.sides(device(), isFile() ? { kind: "file", name: nameOf() }
    : { kind: device() === "phone" ? "computer" : null, name: nameOf(), address: source && source.address });
  const lowered = (text) => String(text).charAt(0).toLowerCase() + String(text).slice(1);
  const say = (text, tone) => {
    status.replaceChildren();
    if (text) status.append(...(Array.isArray(text) ? text : [text]));
    status.dataset.tone = tone || "";
  };
  const differences = () => listOf(compared && compared.differences)
    .filter((d) => objOf(d) && typeof d.id === "string");
  const kindOf = (d) => d.id.split("/")[0];
  const partOf = (d) => {
    if (typeof d.part === "string") return d.part;
    const found = PART_OF.find(([kind]) => kind === kindOf(d));
    return found ? found[1] : null;
  };
  const ticked = () => boxes.filter((b) => b.checked && !b.disabled).map((b) => b.value);
  // peer_sync.in_scope: a difference of a part ticked, or a song a songbook lists while Songbooks is.
  const inScope = (d, parts) => parts.indexOf(partOf(d)) >= 0
    || (kindOf(d) === "song" && parts.indexOf("songbooks") >= 0 && listOf(d.with).length > 0);
  const scoped = () => differences().filter((d) => inScope(d, ticked()));
  const keyOf = (d) => [d.id, d.here || "", d.there || ""].join("\n");
  const nameIn = (d) => {
    const names = objOf(d.names);
    return names ? String(names.artist) + " · " + String(names.title) : String(d.label || d.id);
  };

  const setView = (name) => {
    view = name;
    sheet.dataset.view = name;
    sheet.dataset.flow = flow;
    for (const [key, node] of Object.entries(PANES)) node.hidden = key !== name;
  };

  // --- the chips and the counts --------------------------------------------------------------------------------
  // Where the sync is: Compared, Your choice, then each part it syncs, as the job's stages go.
  const drawChips = (job) => {
    const synced = sent ? sent.parts : ticked();
    const states = {};
    states.compared = compared || sent ? "done" : busy && view === "what" ? "now" : "";
    states.choice = view === "conflict" ? "now" : sent ? "done" : "";
    const stages = listOf(job && job.steps);
    const indexing = stages.some((s) => s && s.name === "index" && (s.state === "running" || s.state === "done"));
    const over = job && job.state !== "queued" && job.state !== "running";
    for (const part of PARTS) {
      if (over || view === "done") states[part] = "done";
      else if (!job || job.state === "queued") states[part] = "";
      else if (part === "indexes") states[part] = indexing ? "now" : "";
      else states[part] = indexing ? "done" : "now";
    }
    const shown = [["compared", "Compared"], ["choice", "Your choice"]]
      .concat([["library", "Library"], ["songbooks", "Songbooks"], ["indexes", "Indexes"]]
        .filter(([part]) => synced.indexOf(part) >= 0));
    chips.replaceChildren(...shown.map(([key, label]) => {
      const chip = el("li", null, label);
      if (states[key]) chip.dataset.state = states[key];
      if (states[key] === "now") chip.setAttribute("aria-current", "step");
      return chip;
    }));
    chips.hidden = flow === "export" || (!compared && !busy) || view === "done";
  };
  const drawCounts = () => {
    const found = scoped();
    const n = { take: found.filter((d) => d.proposal === "theirs").length,
                give: found.filter((d) => d.proposal === "mine").length,
                both: found.filter((d) => d.proposal === "conflict").length };
    for (const key of Object.keys(n)) {
      const item = counts.querySelector("." + key);
      if (!item) continue;
      item.querySelector(".n").textContent = String(n[key]);
      item.dataset.n = String(n[key]);
    }
    const give = counts.querySelector(".give");
    if (give) give.hidden = isFile();  // a file takes nothing back
    counts.hidden = !compared || view === "done" || view === "going" || flow === "export";
  };

  // --- what to sync -------------------------------------------------------------------------------------------
  const partSaid = (part, words) => {
    const line = partsBox.querySelector(`.sync-part[data-part="${part}"] .sync-part-said`);
    if (line) line.textContent = words;
  };
  // What waits in a part, where it is known: "2 changed on Studio", "newer on the computer: Ultimate Guitar (read
  // today) and 1 more".
  const waiting = (part) => {
    if (!compared) return "";
    const sides = sidesNow();
    if (part === "indexes") {
      const said = [];
      for (const [newer, side] of [["there", sides.there], ["here", sides.here]]) {
        if (newer === "here" && isFile()) continue;
        const sites = listOf(compared.indexes).filter((s) => objOf(s) && s.newer === newer);
        if (!sites.length) continue;
        const read = W.readOn(sites[0][newer]);
        said.push("newer " + lowered(side.on) + ": " + String(sites[0].title || sites[0].site)
                  + (read ? " (read " + read + ")" : "") + (sites.length > 1 ? " and " + (sites.length - 1) + " more" : ""));
      }
      return said.join(" · ");
    }
    const mine = differences().filter((d) => partOf(d) === part);
    const there = mine.filter((d) => listOf(d.change)[1]).length;
    const here = isFile() ? 0 : mine.filter((d) => listOf(d.change)[0]).length;
    return [there ? there + " changed " + lowered(sides.there.on) : "",
            here ? here + " changed " + lowered(sides.here.on) : ""].filter(Boolean).join(", ");
  };
  const PART_WORDS = {
    sync: { library: "Your songs, their sheets and pages, both ways",
            songbooks: "Your songbooks and their set lists, both ways", indexes: "For searching offline" },
    import: { library: "Its songs, sheets and pages · it takes nothing back",
              songbooks: "Its songbooks and their set lists", indexes: "For searching offline" },
  };
  const drawWhat = () => {
    const sides = sidesNow();
    check.hidden = true;
    partsBox.hidden = flow === "import" && !compared;
    if (flow === "export") {
      title.textContent = "Export this library";
      const s = sizes || {};
      sub.textContent = [String(s.name || (me && me.name) || ""), Number.isInteger(s.songs) ? W.counted(s.songs, "song")
        : "", W.day(s.made)].filter(Boolean).join(" · ");
      partSaid("library", "Your songs, their sheets and pages" + (typeof s.library === "number" ? " · "
        + W.size(s.library) : ""));
      partSaid("songbooks", Number.isInteger(s.songbooks) ? W.counted(s.songbooks, "songbook")
        : "Your songbooks and their set lists");
      partSaid("indexes", "For searching offline" + (typeof s.indexes === "number" ? " · " + W.size(s.indexes)
        : Number.isInteger(s.tabs) ? " · " + W.tabs(s.tabs) + " tabs" : ""));
      go.textContent = "Export";
      go.disabled = busy || !sizes || !ticked().some((p) => p === "library" || p === "songbooks");
    } else if (flow === "import" && !compared) {
      title.textContent = "Import a file";
      sub.textContent = source && source.file ? String(source.file.name || "")
        : "A file a phone or a server exported, synced as if its caracole were here";
      go.textContent = "Choose a file";
      go.disabled = busy;
    } else {
      const peer = peerOf();
      title.replaceChildren();
      if (isFile()) {
        title.append("Sync with a file from ", el("span", "sync-name", nameOf()));
        sub.textContent = [source && source.file ? String(source.file.name || "") : "",
                           peer.made ? "exported " + W.when(peer.made) : "",
                           compared && compared.synced_before ? "last synced with it " + W.when(compared.synced_before)
                             : ""].filter(Boolean).join(" · ");
      } else {
        title.textContent = "Sync with " + nameOf();
        const where = source && source.address ? source.address : "";
        const before = compared ? compared.synced_before : null;
        const known = listOf(me && me.peers).find((p) => p && p.address === where);
        const last = compared ? before : known && known.synced_at;
        sub.textContent = [where, last ? "last synced " + W.when(last) : compared ? "never synced" : ""]
          .filter(Boolean).join(" · ");
      }
      const words = PART_WORDS[isFile() ? "import" : "sync"];
      const holds = compared ? listOf(compared.holds) : PARTS;
      for (const part of PARTS) {
        const box = boxes.find((b) => b.value === part);
        const held = !compared || holds.indexOf(part) >= 0;
        if (box) {
          box.disabled = !held;
          if (!held) box.checked = false;
        }
        let said = !held ? "Not in this file" : words[part];
        if (held && isFile() && part === "songbooks" && Number.isInteger(peer.songbooks)) {
          said = W.counted(peer.songbooks, "songbook");
        }
        const more = held ? waiting(part) : "";
        partSaid(part, said + (more ? " · " + more : ""));
      }
      go.textContent = !compared && !busy && source ? "Compare again" : "Sync";
      go.disabled = busy || (compared ? !ticked().length : !source);
    }
    cancel.textContent = "Cancel";
    cancel.hidden = false;
    go.hidden = false;
    go.className = "btn primary";
    drawChips(null);
    drawCounts();
  };
  for (const box of boxes) {
    box.addEventListener("change", () => {
      if (view === "what") drawWhat();
    });
  }

  // --- opening and closing -------------------------------------------------------------------------------------
  const loadMe = () => {
    if (!meAsked) {
      meAsked = ask("api/sync").then((answer) => {
        if (answer.ok && objOf(answer.body)) me = answer.body;
        else meAsked = null;
        return answer;
      }, () => {
        meAsked = null;
        return { ok: false, status: 0, body: { error: UNREACHABLE } };
      });
    }
    return meAsked;
  };
  const show = () => {
    if (!sheet.open) {
      sheet.showModal();
      document.documentElement.classList.add("sheet-open");
    }
  };
  const reset = () => {
    exported = false;
    compared = null;
    source = null;
    sizes = null;
    busy = false;
    choices.clear();
    docs.clear();
    conflicts = [];
    at = 0;
    for (const box of boxes) {
      box.disabled = false;
      box.checked = true;
    }
    say("");
  };
  const close = () => {
    turn += 1;
    partsBox.disabled = false;
    if (sheet.open) sheet.close();
    document.documentElement.classList.remove("sheet-open");
    if (view === "done" || (ended && following === null)) {
      ended = null;
      sent = null;
    }
    if (following === null) reset();
  };
  // ``to``: the flow (sync, export, import); ``how``: ``address`` (sync), ``file`` (import).
  const open = (to, how) => {
    const opts = how || {};
    if (following !== null || ended) {  // a sync on its way, or over while the sheet was shut: that one
      show();
      if (ended) drawDone();
      else drawGoing(sent ? sent.view : null);
      return;
    }
    turn += 1;
    reset();
    flow = to;
    setView("what");
    show();
    const mine = turn;
    if (to === "export") {
      boxes.forEach((b) => { b.checked = b.value !== "indexes"; });
      drawWhat();
      ask("api/sync/sizes").then((answer) => {
        if (mine !== turn) return;
        if (!answer.ok || !objOf(answer.body)) {
          say(refusal(answer), "failed");
          return;
        }
        sizes = answer.body;
        drawWhat();
      }, () => mine === turn && say(UNREACHABLE, "failed"));
      loadMe();
      return;
    }
    drawWhat();
    loadMe().then((answer) => {
      if (mine !== turn) return;
      if (to === "import") {
        if (opts.file) upload(opts.file);
        else drawWhat();
        return;
      }
      const where = String(opts.address || (panel && byId("sync-address") ? byId("sync-address").value : "") || "")
        .trim() || (me && typeof me.address === "string" ? me.address : "");
      if (!where) {
        say(answer.ok ? (device() === "phone" ? "No computer to sync with yet: give its address in Settings."
          : "Give the other caracole's address first.") : refusal(answer), "failed");
        drawWhat();
        return;
      }
      compareWith(where);
    });
  };
  cancel.addEventListener("click", () => close());
  sheet.addEventListener("cancel", (e) => {  // Escape: Cancel before Sync, Done after it
    e.preventDefault();
    close();
  });

  // --- the comparison --------------------------------------------------------------------------------------------
  const took = (answer) => answer.ok && objOf(answer.body) && Array.isArray(answer.body.differences);
  const onCompared = (answer, mine, said) => {
    if (mine !== turn) return;
    busy = false;
    if (!took(answer)) {
      say(said ? [said, " ", refusal(answer)] : refusal(answer), "failed");
      drawWhat();
      return;
    }
    compared = answer.body;
    choices.clear();
    for (const d of differences()) {
      if (kept.has(keyOf(d))) choices.set(d.id, kept.get(keyOf(d)));
    }
    if (said) say(said, "failed");
    else if (!differences().length && !listOf(compared.indexes).length) say("Nothing differs: the two agree.", "done");
    else say("");
    drawWhat();
    go.focus({ preventScroll: true });
  };
  const compareWith = (address, said) => {
    const mine = turn;
    busy = true;
    compared = null;
    docs.clear();
    source = { address };
    say(said ? [said, " Comparing again…"] : "Comparing with " + address + "…", said ? "failed" : "running");
    drawWhat();
    post("sync/compare", [["address", address]]).then((answer) => onCompared(answer, mine, said),
                                                       () => onCompared({ ok: false, status: 0, body: null }, mine, said));
  };
  const compareFile = (id, file, said) => {
    const mine = turn;
    busy = true;
    compared = null;
    docs.clear();
    source = { import: id, file };
    say(said ? [said, " Comparing again…"] : "Reading the file…", said ? "failed" : "running");
    drawWhat();
    post("sync/import/compare", [["import", id]]).then((answer) => onCompared(answer, mine, said),
                                                        () => onCompared({ ok: false, status: 0, body: null }, mine,
                                                                        said));
  };
  const compareAgain = (said) => {
    if (source && source.import) compareFile(source.import, source.file, said);
    else if (source && source.address) compareWith(source.address, said);
  };

  // --- a card for each conflict --------------------------------------------------------------------------------
  const sideHead = (box, side) => {
    const head = box.querySelector(".sync-side-head");
    head.replaceChildren(icon(side.icon), el("span", null, side.on));
  };
  const drawLines = (box, lines, which) => {
    const list = box.querySelector(".sync-lines");
    const items = [];
    for (const line of lines) items.push(el("dt", null, line.what), el("dd", null, line[which]));
    list.replaceChildren(...items);
  };
  const drawCard = () => {
    const d = conflicts[at];
    if (!d) return;
    const shown = docs.get(d.id);
    for (const [box, which] of [[card.here, "here"], [card.there, "there"]]) {
      const list = box.querySelector(".sync-lines");
      if (!shown) {
        list.dataset.state = "reading";
        list.replaceChildren(el("dd", null, "Reading both versions…"));
      } else if (shown.error) {
        list.dataset.state = "failed";
        list.replaceChildren(el("dd", null, shown.error));
      } else {
        list.dataset.state = "";
        const lines = W.differ(kindOf(d), shown.here, shown.there);
        if (lines.length) drawLines(box, lines, which);
        else list.replaceChildren(el("dd", null, shown[which] ? "As the other side's" : W.NONE));
      }
    }
  };
  const readUnit = (d) => {
    if (docs.has(d.id) || !compared) return;
    docs.set(d.id, null);
    const mine = turn;
    ask("api/sync/unit?comparison=" + encodeURIComponent(String(compared.comparison || "")) + "&id="
        + encodeURIComponent(d.id)).then((answer) => {
      if (mine !== turn) return;
      docs.set(d.id, answer.ok && objOf(answer.body)
        ? { here: answer.body.here, there: answer.body.there } : { error: refusal(answer) });
      if (view === "conflict" && conflicts[at] && conflicts[at].id === d.id) drawCard();
    }, () => {
      if (mine !== turn) return;
      docs.set(d.id, { error: UNREACHABLE });
      if (view === "conflict" && conflicts[at] && conflicts[at].id === d.id) drawCard();
    });
  };
  const showCard = () => {
    setView("conflict");
    const d = conflicts[at];
    const sides = sidesNow();
    card.name.textContent = nameIn(d);
    card.at.textContent = (at + 1) + " of " + conflicts.length;
    sideHead(card.here, sides.here);
    sideHead(card.there, sides.there);
    card.keepHere.replaceChildren(icon(sides.here.icon), el("span", null, sides.here.name));
    card.keepThere.replaceChildren(icon(sides.there.icon), el("span", null, sides.there.name));
    const left = conflicts.length - at - 1;
    card.sameRow.hidden = left < 1;
    card.same.checked = false;
    card.sameSaid.textContent = "Same for the other " + left;
    cancel.hidden = false;
    cancel.textContent = "Cancel";
    go.hidden = true;
    say("");
    drawChips(null);
    drawCounts();
    drawCard();
    readUnit(d);
    card.keepHere.focus({ preventScroll: true });
  };
  const choose = (side) => {
    const d = conflicts[at];
    if (!d || view !== "conflict") return;
    const rest = card.same.checked ? conflicts.slice(at) : [d];
    for (const e of rest) {
      choices.set(e.id, side);
      kept.set(keyOf(e), side);
    }
    at += rest.length;
    if (at < conflicts.length) showCard();
    else apply();
  };
  card.keepHere.addEventListener("click", () => choose("here"));
  card.keepThere.addEventListener("click", () => choose("there"));

  // --- the sync ------------------------------------------------------------------------------------------------
  const startSync = () => {
    if (!compared || busy) return;
    conflicts = scoped().filter((d) => d.proposal === "conflict" && !choices.has(d.id));
    at = 0;
    if (conflicts.length) showCard();
    else apply();
  };
  const apply = () => {
    const mine = turn;
    const parts = ticked();
    const chosen = scoped().filter((d) => d.proposal === "conflict" && choices.has(d.id))
      .map((d) => choices.get(d.id) + "\t" + d.id);
    busy = true;
    setView("going");
    title.textContent = "Syncing with " + nameOf();
    goingLine.textContent = "Sending the sync…";
    goingLine.dataset.tone = "running";
    goingDetail.textContent = "";
    cancel.hidden = true;
    go.hidden = true;
    say("");
    sent = { compared, choices: new Map(choices), parts, flow, sides: sidesNow(), view: null };
    drawChips(null);
    drawCounts();
    post("sync/apply", [["comparison", String(compared.comparison || "")], ["prefer", ""],
                        ["choices", chosen.join("\n")], ["parts", parts.join(",")]]).then((answer) => {
      if (mine !== turn) return;
      busy = false;
      const job = answer.ok && answer.body && objOf(answer.body.job);
      if (!job) {
        sent = null;
        setView("what");
        if (answer.status === 409) compareAgain(refusal(answer));  // the two changed since, or it is gone: afresh
        else {
          say(refusal(answer), "failed");
          drawWhat();
        }
        return;
      }
      follow(job);
      goingLine.focus({ preventScroll: true });
    }, () => {
      if (mine !== turn) return;
      busy = false;
      sent = null;
      setView("what");
      say(UNREACHABLE, "failed");
      drawWhat();
    });
  };
  go.addEventListener("click", () => {
    if (go.disabled) return;
    if (view === "done" || view === "going" || exported) close();
    else if (flow === "export") makeExport();
    else if (flow === "import" && !compared) {
      if (fileInput) fileInput.click();
    } else if (!compared) compareAgain();
    else startSync();
  });

  // --- on its way ------------------------------------------------------------------------------------------------
  const isActive = (job) => job.state === "queued" || job.state === "running";
  const drawGoing = (job) => {
    setView("going");
    check.hidden = true;
    const shownName = sent && sent.sides ? sent.sides.there.name : String(job && job.display || "")
      .replace(/^Sync with (a file from )?/, "");
    title.textContent = "Syncing with " + (sent && sent.compared ? nameOf() : shownName || "another caracole");
    sub.textContent = sent && sent.compared && source && source.address ? source.address : "";
    const line = job && objOf(job.line) ? job.line : {};
    goingLine.textContent = String(line.text || (job ? job.state : "") || "Sending the sync…");
    goingLine.dataset.tone = String(line.tone || (job && job.state) || "running");
    const steps = listOf(job && job.steps).filter((s) => objOf(s));
    const now = steps.find((s) => s.state === "running") || steps.find((s) => s.state === "failed" && s.detail);
    goingDetail.textContent = now && now.detail ? String(now.detail) : "";
    say("");
    cancel.hidden = true;
    go.hidden = false;
    go.textContent = "Hide";
    go.className = "btn";
    go.disabled = false;
    drawChips(job);
    drawCounts();
  };
  const showJob = (job) => {
    if (sent) sent.view = job;
    const line = objOf(job.line) || {};
    if (isActive(job) && line.tone !== "failed") {
      if (sheet.open && view === "going") drawGoing(job);
      return;
    }
    following = null;  // over (or the server can't answer this page any more: library.js's line says so)
    ended = { job, sent };
    if (sheet.open) drawDone();
  };
  const follow = (job) => {
    following = Number(job.id);
    showJob(job);
    if (lib) lib.track(job, { quiet: true });
  };
  document.addEventListener("caracole:job", (e) => {
    const job = e.detail;
    if (objOf(job) && following !== null && Number(job.id) === following) showJob(job);
  });

  // --- what it did ---------------------------------------------------------------------------------------------
  const byIdentity = new Map(listOf(data.songs).filter((s) => objOf(s) && s.identity)
    .map((s) => [String(s.identity), s]));
  // A unit as the summary names it: a song "Title – Artist", from the comparison, else the library's card of it, else
  // its key; anything else by its label.
  const rowName = (unit, d) => {
    const names = d && objOf(d.names);
    if (names) return String(names.title) + " – " + String(names.artist);
    const [kind, ...rest] = unit.split("/");
    const key = rest.join("/");
    const songCard = kind === "song" ? byIdentity.get(key) : null;
    if (songCard) return String(songCard.title) + " – " + String(songCard.artist);
    if (d && d.label) return String(d.label).replace(/^the songbook /, "");
    if (kind === "songbook") return key;
    if (kind === "song" || kind === "removed") {
      const cut = key.indexOf("/");
      return cut > 0 ? key.slice(cut + 1) + " – " + key.slice(0, cut) : key;
    }
    return unit;
  };
  const row = (name, said, cls) => {
    const item = el("li", cls);
    if (Array.isArray(name)) item.append(...name);
    else item.appendChild(el("span", "sync-row-name", name));
    if (said) item.appendChild(el("span", "sync-row-said", said));
    return item;
  };
  let lanes = 0;
  const section = (kind, said, way, rows) => {
    const box = el("section", "sync-section");
    box.dataset.kind = kind;
    const button = el("button", "sync-lane");
    button.type = "button";
    button.setAttribute("aria-expanded", "false");
    const words = el("span", "sync-lane-words");
    const label = el("span", "sync-lane-said");
    label.append(...(Array.isArray(said) ? said : [said]));
    const arrow = el("span", "sync-arrow");
    arrow.dataset.way = way;
    arrow.hidden = !way;
    const template = byId("sync-icon-arrow");
    if (template) arrow.appendChild(template.content.cloneNode(true));
    words.append(label, arrow);
    button.append(words, icon("chevron", "sync-chev"));
    const list = el("ul", "sync-rows");
    lanes += 1;
    list.id = "sync-rows-" + lanes;
    list.hidden = true;
    list.append(...rows);
    button.setAttribute("aria-controls", list.id);
    button.addEventListener("click", () => {
      const opened = button.getAttribute("aria-expanded") !== "true";
      button.setAttribute("aria-expanded", String(opened));
      list.hidden = !opened;
    });
    box.append(button, list);
    return box;
  };
  const signed = (n) => el("span", n < 0 ? "sync-down" : "sync-up", W.tabs(n, true) + " tabs");
  const drawDone = () => {
    if (!ended) return;
    const job = ended.job;
    const was = ended.sent;
    setView("done");
    const outcome = objOf(job.outcome) || {};
    const report = objOf(outcome.report);
    const withWhom = report ? objOf(report.with) || {} : {};
    const fromDisplay = String(job.display || "").replace(/^Sync with (a file from )?/, "");
    const file = withWhom.kind ? withWhom.kind === "file" : was ? was.flow === "import" || (was.compared && objOf(
      was.compared.peer) && was.compared.peer.kind === "file") : /^Sync with a file from /.test(String(job.display));
    const name = String(withWhom.name || (was && was.sides ? was.sides.there.name : "") || fromDisplay
                        || "the other caracole");
    const sides = W.sides(device(), file ? { kind: "file", name } : {
      kind: withWhom.kind || (device() === "phone" ? "computer" : null), name, address: withWhom.address });
    const failed = job.state === "failed" || job.state === "interrupted" || job.state === "cancelled"
      || (objOf(job.line) && job.line.tone === "failed");
    title.replaceChildren(failed ? "Not synced with: " : "Synced with: ", el("span", "sync-name", name));
    sub.textContent = W.when(report && typeof report.at === "string" ? report.at : new Date().toISOString());
    check.hidden = failed;
    devs.replaceChildren(...[sides.here, sides.there].map((side) => {
      const dev = el("div", "sync-dev");
      dev.append(icon(side.icon), el("span", null, side.name));
      return dev;
    }));
    // The comparison and the choices it was sent with, where this sheet sent it.
    const found = new Map(listOf(was && was.compared && was.compared.differences)
      .filter((d) => objOf(d) && typeof d.id === "string").map((d) => [d.id, d]));
    const chosen = was ? was.choices : new Map();
    const taken = listOf(outcome.taken).map(String);
    const given = listOf(outcome.given).map(String);
    const leftIds = new Set(listOf(outcome.left).map((e) => String(Array.isArray(e) ? e[0] : e)));
    // The conflicts it settled: those of the parts it synced, each with a side, and none it left as it was.
    const conflictIds = new Set(Array.from(found.values()).filter((d) => d.proposal === "conflict"
      && chosen.has(d.id) && inScope(d, was.parts) && !leftIds.has(d.id)).map((d) => d.id));
    const books = objOf(was && was.compared && was.compared.songbooks) || {};
    const out = [];
    // Songs (and the library's other units) taken, then given.
    for (const [kind, units, way, side] of [["taken", taken, "left", sides.there], ["given", given, "right",
                                                                                        sides.here]]) {
      const mine = units.filter((u) => !conflictIds.has(u) && !u.startsWith("songbook/")
        && !(u.startsWith("removed/") && units.indexOf("song/" + u.slice("removed/".length)) >= 0));
      if (!mine.length || (kind === "given" && file)) continue;
      const songs = mine.filter((u) => u.startsWith("song/") || u.startsWith("removed/")).length;
      const others = mine.length - songs;
      const said = [songs ? W.counted(songs, "song") : "", others ? W.counted(others, "other change") : ""]
        .filter(Boolean).join(" and ") + " " + kind;
      out.push(section(kind, said, way, mine.map((u) => {
        const d = found.get(u);
        const change = d ? listOf(d.change)[kind === "taken" ? 1 : 0] : null;
        const why = u.startsWith("removed/") ? W.changed("gone", side)
          : kind === "given" || change === "gone" ? W.changed(change, side) : "";
        return row(rowName(u, d), why);
      })));
    }
    // The conflicts, and whose version was kept.
    if (conflictIds.size) {
      const ids = Array.from(conflictIds);
      const keptSides = new Set(ids.map((u) => chosen.get(u)));
      const short = keptSides.size > 1 ? "mixed" : (chosen.get(ids[0]) === "here" ? sides.here : sides.there).short
        + " kept";
      const way = file ? "left" : keptSides.size > 1 ? "left right" : keptSides.has("here") ? "right" : "left";
      out.push(section("conflicts", W.counted(ids.length, "conflict") + " · " + short, way, ids.map((u) => {
        const which = chosen.get(u);
        const side = which === "here" ? sides.here : sides.there;
        const shown = docs.get(u);
        const lines = shown && !shown.error ? W.differ(u.split("/")[0], shown.here, shown.there) : [];
        const how = lines.map((l) => lowered(l.what) + ", " + l[which]).join("; ");
        return row(rowName(u, found.get(u)), side.whose + " version kept" + (how ? ": " + how : ""));
      })));
    }
    // The songbooks, each with what changed in it.
    const bookTaken = taken.filter((u) => u.startsWith("songbook/") && !conflictIds.has(u));
    const bookGiven = file ? [] : given.filter((u) => u.startsWith("songbook/") && !conflictIds.has(u));
    if (bookTaken.length || bookGiven.length) {
      const how = bookTaken.length && bookGiven.length ? "taken or given" : bookTaken.length ? "taken" : "given";
      const way = bookTaken.length && bookGiven.length ? "left right" : bookTaken.length ? "left" : "right";
      const rows = [];
      for (const [units, from, to] of [[bookTaken, "here", "there"], [bookGiven, "there", "here"]]) {
        for (const u of units) {
          const docsOf = objOf(books[u]) || {};
          const named = objOf(docsOf[to]) || objOf(docsOf[from]);
          const said = objOf(docsOf[to]) || objOf(docsOf[from]) ? W.bookChange(docsOf[from], docsOf[to]) : "";
          rows.push(row(named && named.name ? String(named.name) : rowName(u, found.get(u)), said));
        }
      }
      out.push(section("songbooks", W.counted(bookTaken.length + bookGiven.length, "songbook") + " " + how, way,
                       rows));
    }
    // The indexes: the tabs each site's index tracks, before and after.
    const sites = listOf(report && report.indexes).filter((s) => objOf(s));
    const indexed = sites.length ? [] : listOf(outcome.indexed).map(String);
    if (sites.length || indexed.length) {
      const directions = new Set(sites.map((s) => s.direction));
      const how = directions.size > 1 ? "taken or given" : directions.has("given") ? "given" : "taken";
      const way = directions.size > 1 ? "left right" : directions.has("given") ? "right" : "left";
      const net = sites.reduce((n, s) => n + ((Number(s.after) || 0) - (Number(s.before) || 0)), 0);
      const said = [W.counted(sites.length || indexed.length, "index", "indexes") + " " + how];
      if (sites.length) said.push(" · ", signed(net));
      if (how === "given") said.push(" for " + sides.there.the);
      const rows = sites.map((s) => {
        const change = (Number(s.after) || 0) - (Number(s.before) || 0);
        const reader = s.direction === "given" ? sides.here : sides.there;
        const words = W.tabs(s.before) + " → " + W.tabs(s.after) + " tabs tracked"
          + (change < 0 ? " · its listings no longer name them, so they would not have opened" : "")
          + (s.read ? " · read by " + reader.the + " on " + W.day(s.read) : "");
        return row([el("span", "sync-row-name", String(s.title || s.site) + " · "), signed(change)], words);
      }).concat(indexed.map((site) => row(site, "")));
      out.push(section("indexes", said, way, rows));
    }
    // What it left as it was, and why.
    const left = listOf(outcome.left).map((e) => (Array.isArray(e) ? e : [e, ""]));
    if (left.length) {
      out.push(section("left", W.counted(left.length, "change") + " left as " + (left.length === 1 ? "it was"
        : "they were"), "", left.map(([u, why]) => row(rowName(String(u), found.get(String(u))), String(why || "")))));
    }
    if (!out.length) out.push(el("p", "sync-note", failed ? "Nothing was taken or given." : "Nothing changed on "
      + "either side."));
    sections.replaceChildren(...out);
    fileNote.hidden = !file;
    if (failed) say(String(objOf(job.line) && job.line.text || "The sync failed."), "failed");
    else say("");
    cancel.hidden = true;
    go.hidden = false;
    go.textContent = "Done";
    go.className = "btn primary";
    go.disabled = false;
    chips.hidden = true;
    counts.hidden = true;
    go.focus({ preventScroll: true });
  };

  // --- export ----------------------------------------------------------------------------------------------------
  const makeExport = () => {
    const mine = turn;
    const parts = ticked();
    busy = true;
    drawWhat();
    say("Making the file…", "running");
    send("sync/export", JSON.stringify({ parts }), "application/json").then((answer) => {
      if (mine !== turn) return;
      busy = false;
      const made = answer.ok && objOf(answer.body) && typeof answer.body.export === "string" ? answer.body : null;
      if (!made) {
        say(refusal(answer), "failed");
        drawWhat();
        return;
      }
      const link = el("a", "sync-download", String(made.name || "caracole.caracole"));
      link.href = "api/sync/export?export=" + encodeURIComponent(made.export);
      link.download = String(made.name || "caracole.caracole");
      say(["Made ", link, typeof made.size === "number" ? " · " + W.size(made.size) : ""], "done");
      partsBox.disabled = true;
      go.textContent = "Done";
      go.disabled = false;
      exported = true;
      link.click();  // the browser saves it; the phone hands it to its share sheet
    }, () => {
      if (mine !== turn) return;
      busy = false;
      say(UNREACHABLE, "failed");
      drawWhat();
    });
  };

  // --- import ----------------------------------------------------------------------------------------------------
  const sending = (have, size) => "Sending the file: " + (have / 1e6).toFixed(have >= 10e6 ? 0 : 1) + " of "
    + W.size(size);
  const upload = (file) => {
    const mine = turn;
    flow = "import";
    source = { file };
    busy = true;
    drawWhat();
    say(sending(0, file.size), "running");
    send("sync/import/open", JSON.stringify({ size: file.size, name: file.name }), "application/json")
      .then((answer) => {
        if (mine !== turn) return null;
        const opened = answer.ok && objOf(answer.body) && typeof answer.body.import === "string" ? answer.body : null;
        if (!opened) {
          busy = false;
          say(refusal(answer), "failed");
          drawWhat();
          return null;
        }
        const id = opened.import;
        const part = Math.max(1, Math.min(Number(opened.part) || PART_SIZE, PART_SIZE));
        let have = 0;
        const next = () => {
          if (mine !== turn) return null;
          if (have >= file.size) {
            compareFile(id, file);
            return null;
          }
          const end = Math.min(have + part, file.size);
          return send("sync/import/part?import=" + encodeURIComponent(id) + "&at=" + have, file.slice(have, end),
                      "application/octet-stream").then((sent_) => {
            if (mine !== turn) return null;
            if (!sent_.ok || !objOf(sent_.body) || typeof sent_.body.have !== "number") {
              busy = false;
              say(refusal(sent_), "failed");
              drawWhat();
              return null;
            }
            have = sent_.body.have;
            say(sending(have, file.size), "running");
            return next();
          });
        };
        return next();
      }).catch(() => {
        if (mine !== turn) return;
        busy = false;
        say(UNREACHABLE, "failed");
        drawWhat();
      });
  };
  if (fileInput) {
    fileInput.addEventListener("change", () => {
      const file = fileInput.files && fileInput.files[0];
      if (!file) return;
      fileInput.value = "";  // the same file may be chosen again
      if (following !== null || ended) {
        open("sync");
        return;
      }
      open("import", { file });
    });
  }

  // --- the Sync tab's panels (caracole serve's page) -------------------------------------------------------------
  if (panel) {
    const address = byId("sync-address");
    const test = byId("sync-test");
    const tested = byId("sync-tested");
    const last = byId("sync-last");
    const start = byId("sync-start");
    const exporting = byId("sync-export");
    const peers = byId("sync-peers");
    const form = byId("sync-with");
    const drawLast = () => {
      if (!address || !last) return;
      const where = address.value.trim();
      const known = listOf(me && me.peers).find((p) => p && p.address === where);
      last.textContent = known && known.synced_at ? "Last synced with " + String(known.name || where) + " "
        + W.when(known.synced_at) : where && me ? "Never synced with it" : "";
      if (start) start.disabled = !where;
      if (test) test.disabled = !where;
    };
    const loadPanel = () => {
      loadMe().then((answer) => {
        if (!answer.ok) {
          if (tested) {
            tested.textContent = refusal(answer);
            tested.dataset.tone = "failed";
          }
          return;
        }
        if (address && !address.value.trim() && typeof me.address === "string") address.value = me.address;
        if (peers) {
          peers.replaceChildren(...listOf(me.peers).filter((p) => objOf(p) && p.address).map((p) => {
            const option = el("option");
            option.value = String(p.address);
            if (p.name) option.label = String(p.name);
            return option;
          }));
        }
        drawLast();
      });
    };
    if (address) {
      address.addEventListener("input", () => {
        if (tested) tested.textContent = "";
        drawLast();
      });
    }
    if (form) {
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        if (start && !start.disabled) open("sync", { address: address.value.trim() });
      });
    }
    if (test && tested && address) {
      test.addEventListener("click", () => {
        const where = address.value.trim();
        if (!where) return;
        test.disabled = true;
        tested.textContent = "Asking " + where + "…";
        tested.dataset.tone = "running";
        post("sync/test", [["address", where]]).then((answer) => {
          test.disabled = false;
          const said = answer.ok && objOf(answer.body) && typeof answer.body.said === "string" ? answer.body.said
            : null;
          tested.textContent = said ? "✓ " + said : refusal(answer);
          tested.dataset.tone = said ? "done" : "failed";
        }, () => {
          test.disabled = false;
          tested.textContent = UNREACHABLE;
          tested.dataset.tone = "failed";
        });
      });
    }
    if (start && address) start.addEventListener("click", () => open("sync", { address: address.value.trim() }));
    if (exporting) exporting.addEventListener("click", () => open("export"));
    drawLast();
    document.addEventListener("caracole:tab", (e) => {
      if (e.detail && e.detail.name === "sync") loadPanel();
    });
    if (tabs && tabs.current() === "sync") loadPanel();
  }

  // --- the address -----------------------------------------------------------------------------------------------
  const FLOWS = ["sync", "export", "import"];
  const words = (hash) => {
    try {
      return new URLSearchParams(String(hash || "").replace(/^#/, ""));
    } catch (err) {
      return new URLSearchParams();
    }
  };
  // #sheet=sync, export or import: the sheet at that flow, the word taken out of the address once it is open;
  // #tab=sync on a page with no Sync tab (the phone's, where outcome.py's Compare again leads) is #sheet=sync.
  const addressed = (hash) => {
    const params = words(hash === undefined ? location.hash : hash);
    let asked = params.get("sheet");
    if (!asked && !panel && params.get("tab") === "sync") asked = "sync";
    if (FLOWS.indexOf(asked) < 0) return false;
    params.delete("sheet");
    if (!panel && params.get("tab") === "sync") params.delete("tab");
    try {
      history.replaceState(null, "", "#" + params.toString());
    } catch (err) {
      // Some browsers refuse this for local files: the sheet opens the same.
    }
    open(asked);
    return true;
  };
  window.addEventListener("hashchange", (e) => {  // its new address, whatever tabs.js made of it since
    const to = String(e.newURL || "");
    addressed(to.indexOf("#") >= 0 ? to.slice(to.indexOf("#")) : location.hash);
  });

  // A sync on its way as the page loads (a reload, a second tab, the phone's notification): followed, never another.
  const going = listOf(server.jobs).find((v) => objOf(v) && v.kind === "sync" && isActive(v));
  if (going) {
    sent = { compared: null, choices: new Map(), parts: PARTS.slice(), flow: "sync", sides: null, view: going };
    follow(going);
  }
  // The address the page was loaded with: tabs.js, before this script, has taken out a tab this page hasn't got.
  let first = location.hash;
  try {
    const loaded = performance.getEntriesByType("navigation")[0];
    if (loaded && typeof loaded.name === "string" && loaded.name.indexOf("#") >= 0) {
      first = loaded.name.slice(loaded.name.indexOf("#"));
    }
  } catch (err) {
    first = location.hash;
  }
  if (!addressed(first) && going && panel && tabs && tabs.current() === "sync") open("sync");
})();
