// The Requests tab, on the page caracole serve serves (the file on disk has none): every request the server
// remembers, as /requests.json gives them (web/feed.py). Under Now, the request that runs, with how long ago it
// started, its line and its steps (library.js's list of them, as a song's open card draws it), and those queued under it, each
// with Cancel; then what ended, newest first under Today and Earlier, each with its outcome as a coloured word, its
// reason, its next step (a link, or a form) and when it ended. Every request keeps its Output folded away: what it
// ran, and what each command printed, which the tab asks for once it is opened (?open=N). #tab=requests&job=N opens
// that request's output and brings it into view (a request line's Details, the server sending a form back here).
// Shown, the tab asks again every 1.5 s while a request waits or runs, every 10 s otherwise, and not at all once
// another tab shows; each answer draws again only the requests that changed, each where it was, its Output open or
// shut as you left it. Cancel, Try again and Get it from there post with fetch(), the page staying where it is: the
// song's line follows the request they queue (library.js's ``track``); a failed removal's Try again asks what goes
// on the server's own page. A song offered a transcription of its lyrics (library.js's word: the data's
// ``server.transcribe``, read again once a song's job is over) has Transcribe the lyrics on its newest request that
// ended Ready, as its card has it, posted the same way and then gone from both; a request seen over tells library.js,
// which reads the offer again when it may have changed, and the tab is drawn again when it did. Every text is put in
// with textContent.
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const panel = byId("requests");
  const tab = byId("tab-requests");
  const tabs = window.caracoleTabs || null;
  let data;
  try {
    data = JSON.parse(byId("songs").textContent);
  } catch (err) {
    return;
  }
  const server = data.server && typeof data.server === "object" ? data.server : null;
  if (!panel || !tab || !tabs || !server) return;
  const lib = window.caracoleLibrary || null;  // library.js: a request followed on its song's line
  const listOf = (value) => (Array.isArray(value) ? value : []);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const hidden = (name, value) => {
    const field = el("input");
    field.setAttribute("type", "hidden");
    field.setAttribute("name", name);
    field.setAttribute("value", String(value));
    return field;
  };
  // A timer of the page's, in ms: its own, unless the tests that drive it on real time set it (WebControls.timers).
  const paced = (name, ms) => {
    const set = server.timers && typeof server.timers === "object" ? Number(server.timers[name]) : NaN;
    return set > 0 && set < Infinity ? set : ms;
  };
  const POLL = paced("poll", 1500);  // while a request waits or runs
  const IDLE = paced("idle", 10000);  // while none does: one from another device shows within seconds
  const UNREACHABLE = "No answer from caracole serve. Trying again…";
  // The forms the server answers with data, so the page stays where it is; any other (a failed removal's Try again,
  // POST /remove) posts as a form, and the server asks what goes on a page of its own.
  const SENT = ["/jobs/cancel", "/jobs/again", "/lookup"];
  // Lyrics transcribed from a song's audio (web/transcribe_routes.py): where this caracole transcribes, the song a
  // request names (``display``, as the song's card names it) when it is offered one now: library.js's word, which it
  // reads again; without library.js, the songs offered when the page was made.
  const TRANSCRIBE = server.transcribe && typeof server.transcribe === "object" && server.transcribe.ok === true
    ? server.transcribe : null;
  const offered = new Map();  // without library.js: a song's "Artist - Title" -> its card, for each song offered one
  if (TRANSCRIBE && !(lib && typeof lib.offeredSong === "function")) {
    const ids = new Set(listOf(TRANSCRIBE.songs).map(Number));
    for (const s of listOf(data.songs)) {
      if (s && typeof s === "object" && ids.has(Number(s.id))) offered.set(String(s.display || ""), s);
    }
  }
  const transcribed = new Set();  // without library.js: the songs asked for from this tab
  let going = new Set();  // the requests that waited or ran in the last answer, which tell library.js once over

  const status = el("p", "reqs-status");
  status.setAttribute("role", "status");
  const empty = el("p", "reqs-empty", "Nothing asked yet. Ask for a song from ");
  const toLibrary = el("a", null, "the logbook");
  toLibrary.href = "#tab=library";
  empty.append(toLibrary, ".");
  empty.hidden = true;
  const groupsBox = el("div", "req-groups");
  panel.append(status, empty, groupsBox);

  const opened = new Set();  // the requests whose Output is open
  const items = new Map();  // request id -> { key, node, ago }: what it was drawn from, and its line
  const sections = new Map();  // a group's name -> { node, list }
  let fed = null;  // the last answer
  let timer = 0;
  let asking = false;
  let again = false;
  let want = null;  // the request job=N asked for: opened and brought into view once drawn

  const count = (n) => {
    const badge = tab.querySelector(".n");
    if (badge) badge.textContent = n ? String(n) : "";
  };
  const say = (text) => {
    if (status.textContent !== text) status.textContent = text;
  };
  // Puts ``nodes`` in ``parent`` in that order, moving only those out of place, so that a request drawn as it was
  // keeps its place, its focus and its Output open; whatever else is there goes.
  const place = (parent, nodes) => {
    nodes.forEach((node, i) => {
      if (parent.children[i] !== node) parent.insertBefore(node, parent.children[i] || null);
    });
    while (parent.children.length > nodes.length) parent.lastElementChild.remove();
  };

  // A request's steps (outcome.py's): the list library.js draws under a song's open card, one line a step (its
  // ``stepList``, never a copy of it here); a finished request's skipped steps folded into one last line. Without
  // library.js, their names as plain words.
  const stepsOf = (chips, over) => {
    if (lib && typeof lib.stepList === "function") return lib.stepList(chips, over);
    return el("p", "req-reason", chips.map((c) => String(c.name)).join(", "));
  };

  const refuse = (item, text) => {
    if (!item) return;
    let line = item.querySelector(".req-error");
    if (!line) {
      line = el("p", "req-error");
      line.setAttribute("role", "alert");
      (item.querySelector(".req-next") || item).appendChild(line);
    }
    line.textContent = text;
  };
  // A next step posted as the page's script: the request it queues is followed on its song's line, and the tab asks
  // again at once; a refusal says why, under the request. ``done``: told once the server queued it.
  const post = (form, go, done) => {
    const item = form.closest("li.req");
    go.disabled = true;
    fetch(form.getAttribute("action"), {
      method: "POST", body: new URLSearchParams(new FormData(form)), headers: { Accept: "application/json" },
    }).then((r) => r.json().catch(() => null).then((body) => ({ ok: r.ok, status: r.status, body })))
      .then((answer) => {
        go.disabled = false;
        const body = answer.body && typeof answer.body === "object" ? answer.body : null;
        if (!answer.ok || !body || body.error) {
          refuse(item, (body && body.error) || "caracole serve answered " + answer.status + ". Reload the page.");
          return;
        }
        const view = body.view && typeof body.view === "object" ? body.view
          : body.job && typeof body.job === "object" ? body.job : null;
        if (view && lib) lib.track(view);
        if (done) done();
        ask();
      }, () => {
        go.disabled = false;
        refuse(item, "No answer from caracole serve. Is it running?");
      });
  };
  // A next step: a link (an address of the server's, or a site's), or a one-button form posted with the form token.
  const actionOf = (a) => {
    if (!a || typeof a !== "object" || !a.label) return null;
    const cls = "btn act" + (a.primary === true ? " primary" : "");
    if (typeof a.href === "string") {
      const link = el("a", cls, a.label);
      link.href = /^(\/|https?:\/\/)/i.test(a.href) ? a.href : "#";
      if (a.aria) link.setAttribute("aria-label", String(a.aria));
      link.dataset.focus = "act:" + a.label;
      return link;
    }
    if (typeof a.post !== "string" || !/^\/[\w/-]*$/.test(a.post)) return null;
    const form = el("form", "req-form");
    form.setAttribute("method", "post");
    form.setAttribute("action", a.post);
    form.appendChild(hidden("csrf", String(server.csrf || "")));
    const fields = a.fields && typeof a.fields === "object" ? a.fields : {};
    for (const name of Object.keys(fields)) form.appendChild(hidden(name, fields[name]));
    const go = el("button", cls, a.label);
    go.type = "submit";
    if (a.aria) go.setAttribute("aria-label", String(a.aria));
    go.dataset.focus = "act:" + a.label;
    form.appendChild(go);
    if (SENT.indexOf(a.post) >= 0) {
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        post(form, go);
      });
    }
    return form;
  };
  // The song a request names when it is offered a transcription now: as its card offers it (library.js's word: not
  // while a request of it waits or runs, nor once asked for, here or on its card, until it reads the offer again once
  // that request is over: a transcription that failed is offered again in both); without library.js, as the page was
  // made, and not once asked for from here. Else null.
  const offeredFor = (name) => {
    if (lib && typeof lib.offeredSong === "function") return lib.offeredSong(name);
    const s = offered.get(name) || null;
    return s && !transcribed.has(Number(s.id)) ? s : null;
  };
  // The requests that offer one, by id, each its song's card: a song's newest that ended Ready, while none of the song
  // waits or runs.
  const offersIn = (groups) => {
    const found = new Map();
    if (!TRANSCRIBE) return found;
    const all = [];
    for (const g of groups) for (const r of listOf(g.requests)) if (r && typeof r === "object") all.push(r);
    const running = new Set(all.filter((r) => r.state === "queued" || r.state === "running")
      .map((r) => String(r.display || "")));
    const seen = new Set();
    for (const r of all) {
      const name = String(r.display || "");
      const says = r.says && typeof r.says === "object" ? r.says : {};
      if (seen.has(name) || running.has(name) || says.tone !== "ready" || says.text !== "Ready") continue;
      seen.add(name);
      const s = offeredFor(name);
      if (s) found.set(Number(r.id), s);
    }
    return found;
  };
  // The requests over since the last answer, each told to library.js by its song's name, which reads the offer again
  // when the song may be offered one now, or no more.
  const overNow = (groups) => {
    const now = new Set();
    for (const g of groups) {
      for (const r of listOf(g.requests)) {
        if (!r || typeof r !== "object") continue;
        if (r.state === "queued" || r.state === "running") now.add(Number(r.id));
        else if (going.has(Number(r.id)) && lib && typeof lib.requestOver === "function") lib.requestOver(r.display);
      }
    }
    going = now;
  };
  // Transcribe the lyrics, the card's form (library.js's ``transcribeOffer``): the song by its id and its identity key,
  // and how long it takes here.
  const transcribeForm = (s) => {
    const form = el("form", "transcribe");
    form.setAttribute("method", "post");
    form.setAttribute("action", "/transcribe");
    form.appendChild(hidden("csrf", String(server.csrf || "")));
    form.appendChild(hidden("song", Number(s.id)));
    if (s.identity) form.appendChild(hidden("identity", String(s.identity)));
    const go = el("button", "btn small", "Transcribe the lyrics");
    go.type = "submit";
    go.setAttribute("aria-label", "Transcribe the lyrics of " + String(s.title) + " by " + String(s.artist) +
      " from its audio");
    go.title = "Whisper hears the words, and the auto sheet is made again with its chords over them.";
    go.dataset.focus = "act:Transcribe the lyrics";
    form.append(go, el("p", "hint", lib && typeof lib.transcribeHint === "function" ? lib.transcribeHint()
      : "From the audio, " + String(TRANSCRIBE.time || "") + "."));
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      post(form, go, () => {
        transcribed.add(Number(s.id));
        if (lib && typeof lib.transcribing === "function") lib.transcribing(Number(s.id));
      });
    });
    return form;
  };
  // What a request ran: a lookup's stages, or its commands, each with how it went (a badge), why, and what it printed.
  const stepsList = (entries, cls) => {
    const list = el("ol", cls);
    for (const s of entries) {
      if (!s || typeof s !== "object") continue;
      const li = el("li", "req-step");
      const head = el("div", "req-step-head");
      const badge = s.badge && typeof s.badge === "object" ? s.badge : {};
      const mark = el("span", "badge " + String(badge.tone || "").replace(/[^a-z]/g, ""), badge.text || "");
      head.append(el("span", null, s.label || ""), mark);
      li.appendChild(head);
      if (s.note) li.appendChild(el("p", "req-note", s.note));
      if (s.detail) li.appendChild(el("p", "req-meta", s.detail));
      if (listOf(s.lines).length) li.appendChild(el("pre", null, listOf(s.lines).map(String).join("\n")));
      list.appendChild(li);
    }
    return list;
  };
  // Output, folded: its title and when it was asked for, its stages and its commands. Opened, the tab asks for what
  // each command printed, unless this answer has it.
  const outputOf = (id, given) => {
    const o = given && typeof given === "object" ? given : {};
    const box = el("details", "req-output");
    const summary = el("summary", null, "Output");
    summary.dataset.focus = "output";
    box.appendChild(summary);
    box.appendChild(el("p", "req-meta", o.meta || ""));
    if (listOf(o.stages).length) box.appendChild(stepsList(listOf(o.stages), "req-steps stages"));
    box.appendChild(stepsList(listOf(o.steps), "req-steps"));
    box.open = opened.has(id);
    box.addEventListener("toggle", () => {
      if (!box.open) {
        opened.delete(id);
      } else if (!opened.has(id) || o.opened !== true) {
        opened.add(id);
        if (o.opened !== true) ask();
      }
    });
    return box;
  };
  const makeItem = (r, offer) => {
    const id = Number(r.id);
    const state = String(r.state || "");
    const item = el("li", "req " + (state === "running" ? "running" : state === "queued" ? "queued" : "over"));
    item.id = "req-" + id;
    item.dataset.state = state;
    item.tabIndex = -1;
    const line = el("p", "req-line");
    line.appendChild(el("span", "req-song", r.display || ""));
    let ago = null;
    if (typeof r.ago === "string") {
      ago = el("span", "req-ago", r.ago);
      line.appendChild(ago);
    }
    const says = r.says && typeof r.says === "object" ? r.says : {};
    const word = el("span", "req-says", says.text || "");
    word.dataset.tone = String(says.tone || "");
    line.appendChild(word);
    item.appendChild(line);
    if (typeof r.reason === "string" && r.reason) item.appendChild(el("p", "req-reason", r.reason));
    const chips = listOf(r.steps).filter((c) => c && typeof c === "object" && c.name);
    if (chips.length) item.appendChild(stepsOf(chips, state !== "running" && state !== "queued"));
    if (offer) item.appendChild(transcribeForm(offer));
    const actions = listOf(r.actions).map(actionOf).filter(Boolean);
    const when = r.when && typeof r.when === "object" ? r.when : null;
    if (actions.length || when) {
      const next = el("div", "req-next");
      next.append(...actions);
      if (when) {
        const time = el("time", "req-when", when.text || "");
        if (when.stamp) time.setAttribute("datetime", String(when.stamp));
        next.appendChild(time);
      }
      item.appendChild(next);
    }
    item.appendChild(outputOf(id, r.output));
    return { node: item, ago };
  };
  // A request's element: the one drawn before while it says the same (how long ago it started is written in place)
  // and offers the same (``offer``: its song's card, when it offers a transcription), else drawn again.
  const itemFor = (r, offer) => {
    const id = Number(r.id);
    const key = JSON.stringify(Object.assign({}, r, { ago: null, offer: offer ? Number(offer.id) : null }));
    const had = items.get(id);
    if (had && had.key === key) {
      if (had.ago && typeof r.ago === "string" && had.ago.textContent !== r.ago) had.ago.textContent = r.ago;
      return had.node;
    }
    const made = makeItem(r, offer);
    items.set(id, { key, node: made.node, ago: made.ago });
    return made.node;
  };
  const sectionOf = (name) => {
    if (!sections.has(name)) {
      const slug = name.toLowerCase().replace(/[^a-z]+/g, "-");
      const node = el("section", "req-group " + slug);
      const head = el("h2", "req-head", name);
      head.id = "req-h-" + slug;
      node.setAttribute("aria-labelledby", head.id);
      const list = el("ol", "req-list");
      node.append(head, list);
      sections.set(name, { node, list });
    }
    return sections.get(name);
  };
  const reveal = (id) => {
    const at = items.get(id);
    if (!at) return;
    const box = at.node.querySelector("details.req-output");
    if (box) box.open = true;
    at.node.scrollIntoView({ block: "start" });
    at.node.focus({ preventScroll: true });
    try {
      const params = new URLSearchParams(location.hash.slice(1));
      if (params.has("job")) {
        params.delete("job");
        history.replaceState(history.state, "", "#" + params.toString());
      }
    } catch (err) {
      // A malformed address, or a local file: nothing to drop.
    }
  };
  const draw = (given) => {
    fed = given;
    count(Number(given.active) || 0);
    // Where the focus is, by its request and what it is there (its Output, a next step), to find it again in the
    // request drawn again.
    const at = panel.contains(document.activeElement) ? document.activeElement.closest("li.req") : null;
    const focusId = at ? Number(at.id.replace(/^req-/, "")) : null;
    const focusWhat = at && document.activeElement.dataset ? document.activeElement.dataset.focus || "" : "";
    const groups = listOf(given.groups).filter((g) => g && typeof g === "object" && g.name);
    overNow(groups);
    const offering = offersIn(groups);
    const seen = new Set();
    const shown = groups.map((g) => {
      const section = sectionOf(String(g.name));
      place(section.list, listOf(g.requests).filter((r) => r && typeof r === "object" && Number(r.id) > 0)
        .map((r) => {
          seen.add(Number(r.id));
          return itemFor(r, offering.get(Number(r.id)) || null);
        }));
      return section.node;
    });
    place(groupsBox, shown);
    empty.hidden = shown.length > 0;
    for (const id of Array.from(items.keys())) if (!seen.has(id)) items.delete(id);
    for (const id of Array.from(opened)) if (!seen.has(id)) opened.delete(id);
    if (focusId !== null && !panel.contains(document.activeElement) && items.has(focusId)) {
      const node = items.get(focusId).node;
      const same = focusWhat ? Array.from(node.querySelectorAll("[data-focus]"))
        .find((n) => n.dataset.focus === focusWhat) : null;
      (same || node).focus({ preventScroll: true });
    }
    if (want !== null && items.has(want)) {
      reveal(want);
      want = null;
    }
  };
  const later = (delay) => {
    clearTimeout(timer);
    timer = 0;
    if (tabs.current() !== "requests") return;
    const busy = fed && Number(fed.active) > 0;
    timer = setTimeout(ask, delay !== undefined ? delay : busy && !document.hidden ? POLL : IDLE);
  };
  const ask = () => {
    clearTimeout(timer);
    timer = 0;
    if (asking) {
      again = true;
      return;
    }
    asking = true;
    const open = Array.from(new Set(Array.from(opened).concat(want !== null ? [want] : [])));
    fetch("requests.json" + (open.length ? "?open=" + open.join(",") : ""), {
      cache: "no-store",
      headers: { Accept: "application/json", "X-Caracole-Form-Token": String(server.csrf || "") },
    }).then((r) => r.json().catch(() => null).then((body) => ({ ok: r.ok, status: r.status, body })))
      .then((answer) => {
        asking = false;
        const body = answer.body && typeof answer.body === "object" ? answer.body : null;
        if (!answer.ok || !body || !Array.isArray(body.groups)) {
          say((body && typeof body.error === "string" ? body.error : "caracole serve answered " + answer.status +
            ". Reload the page.") + (answer.status === 403 ? "" : " Trying again…"));
          if (answer.status !== 403) later(IDLE);  // 403: the server restarted since this page was loaded
          return;
        }
        say("");
        draw(body);
        if (again) {
          again = false;
          ask();
        } else {
          later();
        }
      }, () => {
        asking = false;
        say(UNREACHABLE);
        later(IDLE);
      });
  };
  // Shown: asked at once, with the request the address names (job=N) opened.
  const start = (words) => {
    const job = Number(words && typeof words.get === "function" ? words.get("job") : NaN);
    if (Number.isInteger(job) && job > 0) {
      want = job;
      opened.add(job);
    }
    ask();
  };
  document.addEventListener("caracole:tab", (e) => {
    const said = e.detail || {};
    if (said.name === "requests") start(said.words);
    else later();  // another tab: no more asking
  });
  document.addEventListener("caracole:transcribe", () => {  // library.js read the offer again, and it changed
    if (fed) draw(fed);
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && tabs.current() === "requests") ask();
  });
  if (tabs.current() === "requests") {
    let words = null;
    try {
      words = new URLSearchParams(location.hash.slice(1));
    } catch (err) {
      // A malformed address: no request to open.
    }
    start(words);
  }
})();
