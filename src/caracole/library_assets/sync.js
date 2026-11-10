// The Sync tab (sync-tab.html, sync-panel.html), on the page caracole serve serves and on the phone's alike (the file
// on disk has neither tab nor panel): where this caracole and another compare their libraries, unit by unit (a song, a
// removal, a songbook, an artist's alias or UG page, a blocked tab: peer_sync.py), and each takes what the other
// changed.
//
// Shown, the tab asks GET /api/sync once: this library's name, the address it synced with last (put in the field),
// and the caracoles it synced with before, each a button that compares with it. Compare posts the address (POST
// /sync/compare); the answer is the comparison's id, the other side, and every unit the two hold differently, each with
// its label, its kind, why it differs and what the sync proposes (peer_sync.compare: this side's, "mine", the other's,
// "theirs", or a conflict). They are drawn grouped by kind, each with its proposal in words (ours goes there, theirs
// comes here, Both books changed it) and a choice of three: Ours, Theirs or Skip, the proposal's side chosen at first,
// none for a conflict. Two
// buttons settle every conflict at once. Sync waits until every conflict has a choice, then posts the comparison's id
// and the choices that aren't the proposal's (every conflict's, and each one flipped or skipped), one line each in one
// field (POST /sync/apply): the differences and the choices travel, never a unit's document, which the two caracoles
// send each other themselves. With nothing to take or give (nothing differs, or every difference skipped) Sync is
// offered all the same: it keeps what the two agree on, and the phone's brings the computer's newer pages and
// indexes. A comparison done again keeps the choices of each difference that is as it was.
//
// The sync is a request of caracole serve's, as any (the phone's queue answers the same): its view, followed as the
// page follows every request (library.js's ``track``, quietly: this tab says how it goes, not the list of requests),
// told back here with each poll ("caracole:job"). The tab shows its line and its stages (steps.css's chips: compare,
// take, give, agree, and on the phone mirror and index), then, over, what it took here, gave there and left as it
// was, with why (the view's ``outcome``), and Reload: the page's songs are as they were before it. A sync that waits
// or runs as the page loads (the server's ``jobs``) shows at once. Every text is put in with textContent.
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const panel = byId("sync");
  if (!panel) return;
  let data;
  try {
    data = JSON.parse(byId("songs").textContent);
  } catch (err) {
    return;
  }
  const server = data.server && typeof data.server === "object" ? data.server : null;
  const tabs = window.caracoleTabs || null;
  if (!server || !tabs) return;
  const lib = window.caracoleLibrary || null;  // library.js: a request followed, its views told back
  const own = Object.prototype.hasOwnProperty;
  const listOf = (value) => (Array.isArray(value) ? value : []);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const plural = (n, word, many) => n + " " + (n === 1 ? word : many || word + "s");

  const form = byId("sync-with");
  const address = byId("sync-address");
  const compareButton = byId("sync-compare");
  const peersBox = byId("sync-peers");
  const peerList = byId("sync-peer-list");
  const status = byId("sync-status");
  const found = byId("sync-found");
  const sides = byId("sync-sides");
  const bulk = byId("sync-bulk");
  const allHere = byId("sync-all-here");
  const allThere = byId("sync-all-there");
  const groups = byId("sync-groups");
  const plan = byId("sync-plan");
  const go = byId("sync-go");
  const job = byId("sync-job");
  const jobName = byId("sync-job-name");
  const jobLine = byId("sync-job-line");
  const steps = byId("sync-steps");
  const jobDetail = byId("sync-job-detail");
  const outcome = byId("sync-outcome");
  const reload = byId("sync-reload");
  if (!form || !address || !compareButton || !status || !found || !groups || !plan || !go || !job || !jobName
      || !jobLine || !steps || !jobDetail || !outcome || !reload) return;

  // Each kind of unit, in the order peer_sync.compare lists them, under the name its group has.
  const KINDS = [["song", "Songs"], ["removed", "Removed"], ["songbook", "Songbooks"], ["alias", "Artists' aliases"],
                 ["artist_url", "Artists' UG pages"], ["block", "Blocked tabs"]];
  const PROPOSED = { mine: "ours goes there", theirs: "theirs comes here", conflict: "Both books changed it" };
  const SIDE_OF = { mine: "here", theirs: "there" };  // the choice a proposal makes; a conflict makes none
  const CHOICES = [["here", "Ours", "keep ours"], ["there", "Theirs", "take theirs"],
                   ["skip", "Skip", "leave both as they are"]];
  const UNREACHABLE = "No answer from caracole serve. Is it running?";
  // What a sync that takes and gives nothing still does: the agreement kept, and on the phone the computer's newer
  // pages and indexes brought (§5.3's mirror and index stages).
  const AGREES = "Share still notes that the books agree, and brings newer pages and indexes.";

  let me = null;  // GET /api/sync's answer: this library, the address remembered, the peers synced before
  let loaded = false;
  let compared = null;  // POST /sync/compare's answer, drawn
  let comparing = false;
  let sending = false;
  let following = null;  // the sync's job id, once it is queued
  let running = false;  // while it waits or runs: no other comparison, no other sync
  const choices = new Map();  // unit id -> "here", "there", "skip", or null (a conflict not chosen yet)
  const kept = new Map();  // a difference as it was compared (id, here, there) -> its choice, for the next comparison
  const labels = new Map();  // unit id -> its label, for what a sync took, gave and left
  const rows = new Map();  // unit id -> its row

  const say = (text, tone) => {
    status.textContent = text || "";
    status.dataset.tone = tone || "";
  };
  const answerOf = (r) => r.json().catch(() => null).then((body) => ({ ok: r.ok, status: r.status, body }));
  const refusal = (answer) => (answer.body && typeof answer.body.error === "string" && answer.body.error
    ? answer.body.error : "caracole serve answered " + answer.status + ". Reload the page.");
  // A form posted as the page's script: its answer as data, never a page.
  const post = (path, fields) => {
    const body = new URLSearchParams({ csrf: String(server.csrf || "") });
    for (const [name, value] of fields) body.set(name, value);
    return fetch(path, { method: "POST", body, headers: { Accept: "application/json" } }).then(answerOf);
  };
  // A time as the pages write one: dd/mm/yy and the 24-hour clock, in the browser's own zone.
  const when = (text) => {
    const at = new Date(String(text || ""));
    if (!text || Number.isNaN(at.getTime())) return "";
    const two = (n) => String(n).padStart(2, "0");
    return two(at.getDate()) + "/" + two(at.getMonth() + 1) + "/" + two(at.getFullYear() % 100) + " " +
      two(at.getHours()) + ":" + two(at.getMinutes());
  };
  const timeOf = (text) => {
    const shown = when(text);
    if (!shown) return null;
    const t = el("time", null, shown);
    t.setAttribute("datetime", String(text));
    return t;
  };
  const quiet = () => comparing || sending || running;
  const ready = () => {
    compareButton.disabled = quiet() || !address.value.trim();
    for (const b of peerList ? peerList.querySelectorAll("button") : []) b.disabled = quiet();
  };

  // --- what this library synced with before ---------------------------------------------------------------------
  const drawPeers = () => {
    if (!peersBox || !peerList) return;
    const peers = listOf(me && me.peers).filter((p) => p && typeof p === "object" && p.address);
    peerList.replaceChildren(...peers.map((p) => {
      const item = el("li");
      const button = el("button", "sync-peer");
      button.type = "button";
      button.appendChild(el("span", "sync-peer-name", p.name || p.address));
      const where = el("span", "sync-peer-where", p.name ? String(p.address) : "");
      const at = timeOf(p.synced_at);
      if (at) where.append(where.textContent ? " · shared " : "shared ", at);
      button.appendChild(where);
      button.setAttribute("aria-label", "Compare with " + String(p.name || p.address) + " at " + String(p.address));
      button.addEventListener("click", () => {
        address.value = String(p.address);
        compare();
      });
      item.appendChild(button);
      return item;
    }));
    peersBox.hidden = !peers.length;
    ready();
  };
  const load = () => {
    if (loaded) return;
    loaded = true;
    fetch("api/sync", { cache: "no-store", headers: { Accept: "application/json" } }).then(answerOf)
      .then((answer) => {
        if (!answer.ok || !answer.body || typeof answer.body !== "object") {
          say(refusal(answer), "failed");
          return;
        }
        me = answer.body;
        if (!address.value.trim() && typeof me.address === "string") address.value = me.address;
        drawPeers();
      }, () => say(UNREACHABLE, "failed"));
  };

  // --- the comparison ----------------------------------------------------------------------------------------
  const keyOf = (d) => [d.id, d.here === null || d.here === undefined ? "" : d.here,
                        d.there === null || d.there === undefined ? "" : d.there, d.proposal].join("\n");
  const differences = () => listOf(compared && compared.differences)
    .filter((d) => d && typeof d === "object" && typeof d.id === "string");
  const proposalOf = (d) => (own.call(PROPOSED, d.proposal) ? d.proposal : "conflict");
  const known = (kind) => KINDS.some(([k]) => k === kind);
  const kindOf = (d) => {  // its kind, else its id's: a kind this page doesn't know never hides a known id's
    if (typeof d.kind === "string" && known(d.kind)) return d.kind;
    const kind = d.id.split("/")[0];
    return known(kind) ? kind : "other";
  };
  // What Sync sends: each difference whose choice isn't its proposal's, a conflict's always.
  const sent = () => differences()
    .filter((d) => proposalOf(d) === "conflict" || choices.get(d.id) !== SIDE_OF[d.proposal])
    .map((d) => choices.get(d.id) + "\t" + d.id);
  const tally = () => {
    const n = { here: 0, there: 0, skip: 0, open: 0 };
    for (const d of differences()) {
      const side = choices.get(d.id);
      if (side === "here" || side === "there" || side === "skip") n[side] += 1;
      else n.open += 1;
    }
    return n;
  };
  const refresh = () => {
    const n = tally();
    for (const d of differences()) {
      const row = rows.get(d.id);
      if (!row) continue;
      const side = choices.get(d.id);
      row.classList.toggle("unchosen", !side);
      row.classList.toggle("flipped", Boolean(side) && proposalOf(d) !== "conflict" && side !== SIDE_OF[d.proposal]);
      for (const input of row.querySelectorAll("input[type=radio]")) input.checked = input.value === side;
    }
    const conflicts = differences().filter((d) => proposalOf(d) === "conflict").length;
    if (bulk) bulk.hidden = !conflicts;
    if (n.open) {
      plan.textContent = "Choose a side for " + plural(n.open, "conflict") + " first.";
    } else if (!n.here && !n.there) {
      plan.textContent = (n.skip ? "Nothing to take or give: all skipped. "
        : "Nothing to take or give. ") + AGREES;
    } else {
      const parts = [];
      if (n.there) parts.push("takes " + n.there);
      if (n.here) parts.push("gives " + n.here);
      plan.textContent = "Share " + parts.join(", ") + (n.skip ? "; " + n.skip + " skipped." : ".");
    }
    go.disabled = quiet() || n.open > 0;
  };
  const choose = (id, side) => {
    choices.set(id, side);
    const d = differences().find((x) => x.id === id);
    if (d) kept.set(keyOf(d), side);
    refresh();
  };
  let named = 0;
  const rowOf = (d) => {
    const proposal = proposalOf(d);
    const row = el("li", "sync-diff " + proposal);
    row.dataset.id = d.id;
    const what = el("div", "sync-what");
    const label = el("span", "sync-label", d.label || d.id);
    label.id = "sync-d" + (named += 1);
    const said = el("span", "sync-proposal", PROPOSED[proposal]);
    said.dataset.proposal = proposal;
    what.append(label, said);
    if (d.why) what.appendChild(el("span", "sync-why", d.why));
    const pick = el("div", "sync-choice");
    pick.setAttribute("role", "radiogroup");
    pick.setAttribute("aria-labelledby", label.id);
    for (const [side, text, words] of CHOICES) {
      const option = el("label", "sync-side " + side);
      const input = el("input");
      input.type = "radio";
      input.name = label.id;
      input.value = side;
      input.setAttribute("aria-label", text + ": " + words);
      input.addEventListener("change", () => {
        if (input.checked) choose(d.id, side);
      });
      option.append(input, el("span", null, text));
      pick.appendChild(option);
    }
    row.append(what, pick);
    return row;
  };
  const draw = () => {
    rows.clear();
    choices.clear();
    const all = differences();
    for (const d of all) {
      labels.set(d.id, d.label || d.id);
      const was = kept.get(keyOf(d));
      choices.set(d.id, was !== undefined ? was : own.call(SIDE_OF, d.proposal) ? SIDE_OF[d.proposal] : null);
    }
    const peer = compared.peer && typeof compared.peer === "object" ? compared.peer : {};
    const here = me && me.name ? String(me.name) : "this book";
    const there = String(peer.name || peer.address || "the other horde");
    if (sides) {
      const side = (name, text) => {
        const part = el("span", "sync-side-name");
        part.append(el("b", null, name), " " + text);
        return part;
      };
      const before = compared.synced_before;
      const at = typeof before === "string" ? timeOf(before) : null;
      const last = el("span", "sync-last");
      if (at) last.append("Last shared ", at);
      else if (before) last.textContent = "Shared before";
      else last.textContent = "Never shared: where both books hold a song differently, you choose";
      sides.replaceChildren(side("This book", here), side("Their book", there + (peer.address && peer.name ? " · " +
                            peer.address : "")), last);
    }
    const boxes = [];
    for (const [kind, name] of KINDS.concat([["other", "Other"]])) {
      const mine = all.filter((d) => kindOf(d) === kind);
      if (!mine.length) continue;
      const box = el("section", "sync-group");
      const head = el("h3", "sync-group-head", name + " ");
      head.appendChild(el("span", "n", String(mine.length)));
      const conflicts = mine.filter((d) => proposalOf(d) === "conflict").length;
      if (conflicts) head.appendChild(el("span", "sync-group-conflicts", conflicts + " changed in both"));
      const list = el("ul", "sync-list");
      list.setAttribute("aria-label", name);
      for (const d of mine) {
        const row = rowOf(d);
        rows.set(d.id, row);
        list.appendChild(row);
      }
      box.append(head, list);
      boxes.push(box);
    }
    groups.replaceChildren(...boxes);
    groups.hidden = !all.length;
    found.hidden = false;  // nothing differing, Sync still keeps the agreement and brings what is newer
    say(all.length ? plural(all.length, "difference") + " with " + there + "'s book."
      : here + " and " + there + " agree, line for line.", all.length ? "" : "done");
    refresh();
  };
  const compare = () => {
    const where = address.value.trim();
    if (!where || quiet()) return;
    comparing = true;
    ready();
    refresh();
    say("Reading " + where + "'s book…", "running");
    post("sync/compare", [["address", where]]).then((answer) => {
      comparing = false;
      const body = answer.body && typeof answer.body === "object" ? answer.body : null;
      if (!answer.ok || !body || body.error || !Array.isArray(body.differences)) {
        say(refusal(answer), "failed");
        ready();
        refresh();
        return;
      }
      compared = Object.assign({ address: where }, body);
      job.hidden = true;  // a sync over before it: this comparison is after it
      draw();
      ready();
    }, () => {
      comparing = false;
      say(UNREACHABLE, "failed");
      ready();
      refresh();
    });
  };
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    compare();
  });
  address.addEventListener("input", ready);
  const everyConflict = (side) => {
    for (const d of differences()) {
      if (proposalOf(d) !== "conflict") continue;
      choices.set(d.id, side);
      kept.set(keyOf(d), side);
    }
    refresh();
  };
  if (allHere) allHere.addEventListener("click", () => everyConflict("here"));
  if (allThere) allThere.addEventListener("click", () => everyConflict("there"));

  // --- the sync ------------------------------------------------------------------------------------------------
  go.addEventListener("click", () => {
    if (go.disabled || !compared) return;
    sending = true;
    refresh();
    ready();
    say("Sending…", "running");
    post("sync/apply", [["comparison", String(compared.comparison || "")], ["prefer", ""],
                        ["choices", sent().join("\n")]]).then((answer) => {
      sending = false;
      const body = answer.body && typeof answer.body === "object" ? answer.body : null;
      const view = body && body.job && typeof body.job === "object" ? body.job : null;
      if (!answer.ok || !view) {
        say(refusal(answer), "failed");
        refresh();
        ready();
        return;
      }
      say("");
      follow(view);
      jobLine.focus({ preventScroll: true });  // Sync is gone with the differences: the line says how it goes
    }, () => {
      sending = false;
      say(UNREACHABLE, "failed");
      refresh();
      ready();
    });
  });

  // The job's stages, as steps.css's chips (a lookup's markup): those done ticked, the one that runs lit, those to
  // come grey, a failed one crossed, one skipped (no index newer, say) dashed.
  const MARKS = { done: "✓ ", failed: "✕ " };
  const STATE_OF = { waiting: "waiting", queued: "waiting", running: "running", done: "done", failed: "failed",
                     interrupted: "failed", skipped: "plain", cancelled: "plain" };
  const drawSteps = (view) => {
    const chips = listOf(view.steps).filter((s) => s && typeof s === "object" && (s.label || s.name));
    steps.replaceChildren(...chips.map((s) => {
      const state = own.call(STATE_OF, s.state) ? STATE_OF[s.state] : "waiting";
      const chip = el("li", "step-chip " + state);
      if (state === "running") chip.setAttribute("aria-current", "step");
      if (own.call(MARKS, state)) {
        const mark = el("span", null, MARKS[state]);
        mark.setAttribute("aria-hidden", "true");
        chip.appendChild(mark);
      }
      chip.appendChild(document.createTextNode(String(s.label || s.name)));
      chip.appendChild(el("span", "visually-hidden", ": " + String(s.state || "waiting")));
      return chip;
    }));
    steps.hidden = !chips.length;
    const now = chips.find((s) => s.state === "running") || chips.find((s) => s.state === "failed" && s.detail);
    jobDetail.textContent = now && now.detail ? String(now.detail) : "";
  };
  const unitList = (title, entries, cls) => {
    const box = el("section", "sync-done " + cls);
    box.appendChild(el("h3", null, title + " "));
    box.firstChild.appendChild(el("span", "n", String(entries.length)));
    const list = el("ul");
    for (const [id, why] of entries) {
      const item = el("li", null, labels.get(id) || id);
      if (why) item.appendChild(el("span", "sync-why", " · " + why));
      list.appendChild(item);
    }
    box.appendChild(list);
    return box;
  };
  const drawOutcome = (said) => {
    const parts = [];
    if (said && typeof said === "object") {
      const taken = listOf(said.taken).map((id) => [String(id), ""]);
      const given = listOf(said.given).map((id) => [String(id), ""]);
      const left = listOf(said.left).map((e) => (Array.isArray(e) ? [String(e[0]), String(e[1] || "")]
        : [String(e), ""]));
      if (taken.length) parts.push(unitList("Taken", taken, "taken"));
      if (given.length) parts.push(unitList("Given", given, "given"));
      if (left.length) parts.push(unitList("Left as they were", left, "left"));
      if (!taken.length && !given.length && !left.length) {
        parts.push(el("p", "sync-none", "Neither book changed."));
      }
      const indexed = listOf(said.indexed).map(String);
      if (indexed.length) parts.push(el("p", "sync-note", "Indexes updated: " + indexed.join(", ") + "."));
      if (Number.isInteger(said.agreed)) {
        parts.push(el("p", "sync-note", "The books agree on " + plural(said.agreed, "entry", "entries") + "."));
      }
    }
    outcome.replaceChildren(...parts);
    outcome.hidden = !parts.length;
  };
  const isActive = (view) => view.state === "queued" || view.state === "running";
  // Where the job's output is, when its line names a tab this page has (the computer's Requests tab; none on the
  // phone, whose line names this one).
  const detailsLink = (view) => {
    const line = view.line && typeof view.line === "object" ? view.line : {};
    const href = typeof line.details === "string" ? line.details : "";
    let tab;
    try {
      tab = new URLSearchParams(href.replace(/^#/, "")).get("tab");
    } catch (err) {
      return null;
    }
    if (!tab || tab === "sync" || tabs.names.indexOf(tab) < 0) return null;
    const a = el("a", null, "Journal");
    a.href = "#" + href.replace(/^#/, "");
    return a;
  };
  const showJob = (view) => {
    if (!view || typeof view !== "object") return;
    following = Number(view.id);
    const line = view.line && typeof view.line === "object" ? view.line : {};
    // Over, or the server can't answer this page any more (library.js's line: restarted since it loaded)
    const over = !isActive(view) || line.tone === "failed";
    running = !over;
    job.hidden = false;
    found.hidden = true;
    jobName.textContent = String(view.display || "Share");
    jobLine.dataset.tone = String(line.tone || view.state || "");
    jobLine.replaceChildren(el("span", null, line.text || view.state || ""));
    const more = detailsLink(view);
    if (more) {
      const dot = el("span", "dot", " · ");
      dot.setAttribute("aria-hidden", "true");
      jobLine.append(dot, more);
    }
    drawSteps(view);
    if (over) drawOutcome(view.outcome);
    else outcome.hidden = true;
    reload.hidden = !over;
    ready();
  };
  const follow = (view) => {
    showJob(view);
    if (lib) lib.track(view, { quiet: true });
  };
  document.addEventListener("caracole:job", (e) => {
    const view = e.detail;
    if (view && typeof view === "object" && following !== null && Number(view.id) === following) showJob(view);
  });
  if (reload) reload.addEventListener("click", () => location.reload());
  // A sync that waits or runs as the page loads: library.js follows it already (the server's ``jobs``).
  const going = listOf(server.jobs).find((v) => v && typeof v === "object" && v.kind === "sync" && isActive(v));
  if (going) follow(going);  // quietly too: this tab says how it goes, not the list of requests

  ready();
  document.addEventListener("caracole:tab", (e) => {
    if (e.detail && e.detail.name === "sync") load();
  });
  if (tabs.current() === "sync") load();
})();
