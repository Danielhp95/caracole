// The page's tabs: body.html's tablist in the masthead, Library, Songbooks and, served, Requests, the last. Each is a
// button of the tablist whose id is "tab-NAME" and whose aria-controls names its panel; the first, the library, is the
// page as it opens. A tab put in body.html (before Requests) is one more here, with no change to this script.
// The address says which shows: #tab=NAME, none for the first, beside the library's own words. A tab clicked, or
// reached with the tablist's own keys (← → Home End, the focus roving with them), shows its panel and hides the
// others; so does a link to this page whose address names a tab (#tab=requests&job=4: a request line's Details, the
// list of requests'), which leaves the page where it is, and Back or Forward to an address that names another one
// (or none: the library). Every script that draws a tab hears it shown ("caracole:tab": its name, the one before,
// and the words of the address that asked for it, as requests.js reads job=N), and may show one itself
// (window.caracoleTabs.show).
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
  const save = () => {
    const params = words(location.hash);
    params.delete("tab");
    if (current !== first) params.set("tab", current);
    try {
      history.replaceState(null, "", "#" + params.toString());
    } catch (err) {
      // Some browsers refuse this for local files: the page works the same.
    }
  };
  // ``options``: ``focus``, the tab takes the focus (its keys); ``words``, the address that asked for it.
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
    save();
    if (opts.focus) tabs[names.indexOf(to)].focus();
    document.dispatchEvent(new CustomEvent("caracole:tab", { detail: { name: to, from, words: opts.words || null } }));
  };
  for (const tab of tabs) tab.addEventListener("click", () => show(nameOf(tab)));
  list.addEventListener("keydown", (e) => {
    const at = tabs.indexOf(document.activeElement);
    if (at < 0) return;
    const step = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
    const to = step ? (at + step + tabs.length) % tabs.length : e.key === "Home" ? 0 : e.key === "End"
      ? tabs.length - 1 : -1;
    if (to < 0) return;
    e.preventDefault();
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
    const params = words(location.hash);
    if (named(params) !== current) show(named(params), { words: params });
  });
  window.caracoleTabs = Object.freeze({
    show,
    current: () => current,
    names: names.slice(),
  });
  show(named(words(location.hash)), { words: words(location.hash) });
})();
