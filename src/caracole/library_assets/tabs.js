// The page's tabs: body.html's tablist in the masthead, Library, Songbooks, Sites and, served, Requests, then on
// caracole serve's page Sync, the last (the phone's page has none: its sync is a sheet, sync.js). Each is a button of
// the tablist whose id is "tab-NAME" and whose aria-controls names its panel; the first, the library, is the page as
// it opens. A tab put in body.html is one more here, with no change to this script.
// The address says which shows: #tab=NAME, none for the first, beside the library's own words. A tab clicked, or
// reached with the tablist's own keys (← → Home End, the focus roving with them), shows its panel and hides the
// others; so does a link to this page whose address names a tab (#tab=requests&job=4: a request line's Details, the
// list of requests'), which leaves the page where it is, and Back or Forward to an address that names another one
// (or none: the library). Every script that draws a tab hears it shown ("caracole:tab": its name, the one before,
// and the words of the address that asked for it, as requests.js reads job=N), and may show one itself
// (window.caracoleTabs.show).
// Back: leaving the library for another tab is a step of the browser's history, an entry of this script's own
// ({ tab: 1 }, with search mode's count beside it while body.search-mode is on: one more of its steps), so Back
// returns to the library; between the other tabs each replaces the one before, and the library's tab pressed (or
// reached with the keys) while that step is there takes it back (history.back()) rather than adding another. An
// address that names a tab, as the page opens or with Back or Forward, shows it with no step; a browser that refuses
// the step (a local file's) changes the tab all the same. Every address written in place keeps the entry's state.
(() => {
  "use strict";
  const list = document.querySelector(".masthead .tabs[role=tablist]");
  if (!list) return;
  const tabs = Array.from(list.querySelectorAll("[role=tab]")).filter((tab) => /^tab-./.test(tab.id));
  if (!tabs.length) return;
  const nameOf = (tab) => tab.id.slice("tab-".length);
  const names = tabs.map(nameOf);
  const first = names[0];
  const panelOf = (tab) => document.getElementById(tab.getAttribute("aria-controls") || "");
  const words = (hash) => {
    try {
      return new URLSearchParams(String(hash || "").replace(/^#/, ""));
    } catch (err) {
      return new URLSearchParams();  // a malformed address: no words
    }
  };
  const named = (params) => (names.indexOf(params.get("tab")) >= 0 ? params.get("tab") : first);
  let current = "";
  let fromLibrary = false;  // the step this script took out of the library is the one before this entry
  let refocus = false;  // the library's tab takes the focus once Back shows it (its keys asked for it)
  // ``how``: "push", a step out of the library (an entry of this script's own, marked ``tab``); else in place.
  const save = (how) => {
    const params = words(location.hash);
    params.delete("tab");
    if (current !== first) params.set("tab", current);
    const url = "#" + params.toString();
    if (how === "push") {
      const entry = { tab: 1 };
      if (document.body.classList.contains("search-mode")) {
        entry.search = (Number(history.state && history.state.search) || 0) + 1;
      }
      try {
        history.pushState(entry, "", url);
        fromLibrary = true;
        return;
      } catch (err) {
        // A browser that refuses the step (a local file's): the tab changes in place, with none to go back to.
      }
    }
    try {
      history.replaceState(history.state, "", url);
    } catch (err) {
      // Some browsers refuse this for local files: the page works the same.
    }
  };
  // ``options``: ``focus``, the tab takes the focus (its keys); ``words``, the address that asked for it; ``pop``,
  // Back or Forward showed it, and ``load``, the page opened at it: no step either way.
  const show = (name, options) => {
    const opts = options || {};
    const to = names.indexOf(name) >= 0 ? name : first;
    for (const tab of tabs) {
      const on = nameOf(tab) === to;
      tab.setAttribute("aria-selected", String(on));
      tab.tabIndex = on ? 0 : -1;
      const panel = panelOf(tab);
      if (panel) panel.hidden = !on;
    }
    document.body.dataset.tab = to;
    const from = current;
    current = to;
    save(from === first && to !== first && !opts.pop && !opts.load ? "push" : "replace");
    if (to === first) fromLibrary = false;  // back in the library however it came: no step of it to take back
    if (opts.focus) tabs[names.indexOf(to)].focus({ preventScroll: true });
    // A row that scrolls sideways shows the chosen tab whole (the row alone: scrollIntoView would move the page).
    const chosen = tabs[names.indexOf(to)];
    if (list.scrollWidth > list.clientWidth) {
      const row = list.getBoundingClientRect();
      const box = chosen.getBoundingClientRect();
      if (box.left < row.left) list.scrollLeft += box.left - row.left;
      else if (box.right > row.right) list.scrollLeft += box.right - row.right;
    }
    // A tab's script may write the address in place as it hears the tab shown: the entry keeps its state all the
    // same (songbooks.js's own address writes pass none).
    const kept = history.state;
    document.dispatchEvent(new CustomEvent("caracole:tab", { detail: { name: to, from, words: opts.words || null } }));
    if (kept !== null && history.state === null) {
      try {
        history.replaceState(kept, "", location.href);
      } catch (err) {
        // Some browsers refuse this for local files: the page works the same.
      }
    }
  };
  // The library's tab while the step out of it is there: that step taken back, and nothing else (popstate shows it).
  // Pressed again before Back is heard (a double click), it is the same Back: a second would leave the page.
  let backing = false;
  const back = (focus) => {
    if (backing) {
      refocus = refocus || Boolean(focus);
      return true;
    }
    if (!fromLibrary || current === first) return false;
    backing = true;
    refocus = Boolean(focus);
    history.back();
    return true;
  };
  for (const tab of tabs) {
    tab.addEventListener("click", () => {
      if (nameOf(tab) === first && back(false)) return;
      show(nameOf(tab));
    });
  }
  list.addEventListener("keydown", (e) => {
    const at = tabs.indexOf(document.activeElement);
    if (at < 0) return;
    const step = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
    const to = step ? (at + step + tabs.length) % tabs.length : e.key === "Home" ? 0 : e.key === "End"
      ? tabs.length - 1 : -1;
    if (to < 0) return;
    e.preventDefault();
    if (names[to] === first && back(true)) return;
    show(names[to], { focus: true });
  });
  // A link to this very page that names a tab: that tab, the page staying where it is (a link to open in another
  // tab or window goes there, as any link does).
  document.addEventListener("click", (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target instanceof Element ? e.target.closest("a[href]") : null;
    if (!a || (a.target && a.target !== "_self")) return;
    if (a.origin !== location.origin || a.pathname !== location.pathname || a.search !== location.search) return;
    const params = words(a.hash);
    if (names.indexOf(params.get("tab")) < 0) return;
    e.preventDefault();
    show(params.get("tab"), { words: params });
  });
  window.addEventListener("popstate", () => {
    fromLibrary = false;
    backing = false;
    const focus = refocus;
    refocus = false;
    const params = words(location.hash);
    if (named(params) !== current) show(named(params), { words: params, pop: true, focus });
  });
  window.caracoleTabs = Object.freeze({
    show,
    current: () => current,
    names: names.slice(),
  });
  show(named(words(location.hash)), { words: words(location.hash), load: true });
})();
