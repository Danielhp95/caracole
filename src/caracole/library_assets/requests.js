// The Requests tab, on the page caracole serve serves (the file on disk has none): every request the server
// remembers, as /requests.json gives them (web/feed.py). Under Now, the request that runs, with how long ago it
// started, its line and its steps (steps.css's chips, as a song's line draws them), and those queued under it, each
// with Cancel; then what ended, newest first under Today and Earlier, each with its outcome as a coloured word, its
// reason, its next step (a link, or a form) and when it ended. Every request keeps its Output folded away: what it
// ran, and what each command printed, which the tab asks for once it is opened (?open=N). #tab=requests&job=N opens
// that request's output and brings it into view (a request line's Details, the server sending a form back here).
// Shown, the tab asks again every 1.5 s while a request waits or runs, every 10 s otherwise, and not at all once
// another tab shows; each answer draws again only the requests that changed, each where it was, its Output open or
// shut as you left it. Cancel, Try again and Get it from there post with fetch(), the page staying where it is: the
// song's line follows the request they queue (library.js's ``track``); a failed removal's Try again asks what goes
// on the server's own page. Every text is put in with textContent.
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
  const UNREACHABLE = "caracole serve can't be reached; trying again…";
  // The forms the server answers with data, so the page stays where it is; any other (a failed removal's Try again,
  // POST /remove) posts as a form, and the server asks what goes on a page of its own.
  const SENT = ["/jobs/cancel", "/jobs/again", "/lookup"];

  const status = el("p", "reqs-status");
  status.setAttribute("role", "status");
  const empty = el("p", "reqs-empty", "No requests yet. Request a song from ");
  const toLibrary = el("a", null, "the library");
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

  // A running lookup's steps (outcome.py's), as library.js draws them under a song's line: those done ticked, the
  // one that runs lit and the current step, those to come grey, a failed one crossed; a plain one its name alone.
  const MARKS = { done: "✓ ", failed: "✕ " };
  const STATES = ["waiting", "running", "done", "failed", "plain"];
  const stepChips = (chips) => {
    const box = el("ol", "step-chips");
    box.setAttribute("aria-label", "Steps");
    for (const c of chips) {
      const state = STATES.indexOf(c.state) >= 0 ? String(c.state) : "waiting";
      const chip = el("li", "step-chip " + state);
      if (state === "running") chip.setAttribute("aria-current", "step");
      if (MARKS[state]) {
        const mark = el("span", null, MARKS[state]);
        mark.setAttribute("aria-hidden", "true");
        chip.appendChild(mark);
      }
      chip.appendChild(document.createTextNode(String(c.name)));
      if (c.source) chip.append(" ", el("b", null, String(c.source)));
      if (state !== "plain") chip.appendChild(el("span", "visually-hidden", ": " + state));
      box.appendChild(chip);
    }
    return box;
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
  // again at once; a refusal says why, under the request.
  const post = (form, go) => {
    const item = form.closest("li.req");
    go.disabled = true;
    fetch(form.getAttribute("action"), {
      method: "POST", body: new URLSearchParams(new FormData(form)), headers: { Accept: "application/json" },
    }).then((r) => r.json().catch(() => null).then((body) => ({ ok: r.ok, status: r.status, body })))
      .then((answer) => {
        go.disabled = false;
        const body = answer.body && typeof answer.body === "object" ? answer.body : null;
        if (!answer.ok || !body || body.error) {
          refuse(item, (body && body.error) || "caracole serve answered " + answer.status + ": reload the page.");
          return;
        }
        const view = body.view && typeof body.view === "object" ? body.view
          : body.job && typeof body.job === "object" ? body.job : null;
        if (view && lib) lib.track(view);
        ask();
      }, () => {
        go.disabled = false;
        refuse(item, "caracole serve can't be reached: is it running?");
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
  const makeItem = (r) => {
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
    if (chips.length) item.appendChild(stepChips(chips));
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
  // A request's element: the one drawn before while it says the same (how long ago it started is written in place),
  // else drawn again.
  const itemFor = (r) => {
    const id = Number(r.id);
    const key = JSON.stringify(Object.assign({}, r, { ago: null }));
    const had = items.get(id);
    if (had && had.key === key) {
      if (had.ago && typeof r.ago === "string" && had.ago.textContent !== r.ago) had.ago.textContent = r.ago;
      return had.node;
    }
    const made = makeItem(r);
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
        history.replaceState(null, "", "#" + params.toString());
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
    const seen = new Set();
    const shown = groups.map((g) => {
      const section = sectionOf(String(g.name));
      place(section.list, listOf(g.requests).filter((r) => r && typeof r === "object" && Number(r.id) > 0)
        .map((r) => {
          seen.add(Number(r.id));
          return itemFor(r);
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
            ": reload the page.") + (answer.status === 403 ? "" : " Trying again…"));
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
