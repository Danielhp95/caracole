
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const list = byId("list");
  const toolbar = document.querySelector(".toolbar");
  let data;
  try {
    data = JSON.parse(byId("songs").textContent);
  } catch (err) {
    return;
  }
  const songs = new Map((Array.isArray(data.songs) ? data.songs : []).map((s) => [String(s.id), s]));
  if (!list || !toolbar || !songs.size) return;
  const server = data.server && typeof data.server === "object" ? data.server : null;
  const names = (list) => (Array.isArray(list) ? list : []).map((b) => String(b && b.name || "")).filter(Boolean);
  const books = names(data.songbooks && data.songbooks.books);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  // Each word in single quotes, each ' written '\'': bash and zsh expand ! even in double quotes.
  const shellQuote = (text) => "'" + String(text).replace(/'/g, "'\\''") + "'";
  const picked = [];  // song ids, in the order they were picked: the songbook's order
  let sending = false;  // on caracole serve, until the server answers the bar's form

  const toggle = el("button", "chip pick-toggle", "Select");
  toggle.type = "button";
  toggle.title = "Pick songs for a songbook";
  toggle.setAttribute("aria-pressed", "false");
  (toolbar.querySelector(".controls") || toolbar).prepend(toggle);

  const bar = el("section", "pickbar");
  bar.hidden = true;
  bar.setAttribute("aria-label", "Make a songbook");
  const inner = el("div", "pickbar-in");
  // The way out, as the Select button is, which the page has scrolled away by now: the picks stay.
  const done = el("button", "pick-done");
  done.type = "button";
  done.setAttribute("aria-label", "Leave Select");
  done.title = "Leave Select (the picks stay)";
  const cross = el("span", null, "×");
  cross.setAttribute("aria-hidden", "true");
  done.appendChild(cross);
  const count = el("p", "pick-count");
  count.setAttribute("aria-live", "polite");
  const form = el("form", "pickbar-form");
  form.id = "pickbar-form";
  // On a phone the menu and the name wait under this button, so that the bar is one line while you pick.
  const unfold = el("button", "btn primary pick-open");
  unfold.type = "button";
  unfold.setAttribute("aria-expanded", "false");
  unfold.setAttribute("aria-controls", form.id);
  const unfoldText = el("span", "pick-open-text", "Make songbook…");
  unfold.appendChild(unfoldText);
  const into = el("select", "pick-into");
  into.setAttribute("aria-label", "Into which songbook");
  into.appendChild(new Option("New songbook", ""));
  for (const name of books) into.appendChild(new Option(name, name));
  const intoLabel = el("label");
  intoLabel.appendChild(into);
  intoLabel.hidden = !books.length;
  const nameLabel = el("label");
  const nameInput = el("input", "pick-name");
  nameInput.type = "text";
  nameInput.maxLength = 80;
  nameInput.placeholder = "Songbook name";
  nameInput.autocomplete = "off";
  nameInput.setAttribute("aria-label", "The songbook's name");
  nameLabel.appendChild(nameInput);
  const submit = el("button", "btn primary", "Make songbook");
  submit.type = "submit";
  const clear = el("button", "btn", "Clear");
  clear.type = "button";
  const error = el("p", "pick-error");
  error.setAttribute("role", "alert");
  // The file's command, folded: one line of the bar, which Copy copies without unfolding it.
  const command = el("div", "pick-command");
  command.hidden = true;
  const commandFold = el("details");
  commandFold.appendChild(el("summary", null, "The command to run"));
  commandFold.appendChild(el("p", "hint", "Run it where caracole runs:"));
  const commandText = el("code");
  commandFold.appendChild(commandText);
  const copy = el("button", "btn small", "Copy");
  copy.type = "button";
  copy.setAttribute("aria-label", "Copy the command");
  copy.title = "Copy the command, to run where caracole runs";
  command.append(commandFold, copy);
  const fields = {};
  if (server) {
    form.method = "post";
    form.setAttribute("action", "/songbook/make");
    for (const name of ["csrf", "name", "songs"]) {
      const field = el("input");
      field.type = "hidden";
      field.name = name;
      form.appendChild(field);
      fields[name] = field;
    }
    fields.csrf.value = String(server.csrf || "");
  }
  form.append(intoLabel, nameLabel, submit, clear, error);
  inner.append(done, count, unfold, form, command);
  bar.appendChild(inner);
  document.body.appendChild(bar);

  const ordinal = (n) => {
    const tens = n % 100;
    return n + (tens >= 11 && tens <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" })[n % 10] || "th");
  };
  // Only what changed is touched: the list's observer sees every change to a line's children.
  const paint = (line) => {
    const at = picked.indexOf(line.dataset.id);
    const box = line.querySelector(".pick input");
    if (box && box.checked !== (at >= 0)) box.checked = at >= 0;
    const n = line.querySelector(".pick-n");
    const number = at >= 0 ? String(at + 1) : "";
    if (n && n.textContent !== number) n.textContent = number;
    // The box's name says its place too: the number on it is hidden from a screen reader.
    const said = line.querySelector(".pick-label");
    const s = songs.get(line.dataset.id);
    const name = s ? "Pick " + s.title + " by " + s.artist + (at >= 0 ? ", " + ordinal(at + 1) : "") : "";
    if (said && s && said.textContent !== name) said.textContent = name;
    if (line.classList.contains("picked") !== (at >= 0)) line.classList.toggle("picked", at >= 0);
  };
  const paintAll = () => {
    for (const line of list.querySelectorAll("[data-picker]")) paint(line);
    count.textContent = picked.length + " selected";
    submit.disabled = sending || !picked.length;
    const existing = into.value;
    submit.textContent = existing ? "Add to " + existing : "Make songbook";
    unfoldText.textContent = submit.textContent + "…";
    nameLabel.hidden = Boolean(existing);
    command.hidden = true;
  };
  const pick = (id, on) => {
    const at = picked.indexOf(id);
    if (on && at < 0) picked.push(id);
    if (!on && at >= 0) picked.splice(at, 1);
    error.textContent = "";
    paintAll();
  };
  // A box on each song's line, as the page's script puts them in the list (it keeps each line it made), once
  // Select is pressed: until then a line holds nothing to tick (the file's sends nothing, and a review's
  // picker is the line's only choice).
  const selecting = () => document.body.classList.contains("selecting");
  const decorate = () => {
    if (!selecting()) return;
    for (const line of list.querySelectorAll("[data-id]")) {
      const id = line.dataset.id;
      if (!songs.has(id)) continue;
      if (!line.dataset.picker) {
        line.dataset.picker = "1";
        const s = songs.get(id);
        const label = el("label", "pick");
        const box = el("input");
        box.type = "checkbox";
        const order = el("span", "pick-n");
        order.setAttribute("aria-hidden", "true");
        label.append(box, order, el("span", "visually-hidden pick-label", "Pick " + s.title + " by " + s.artist));
        box.addEventListener("change", () => pick(id, box.checked));
        line.prepend(label);
      }
      paint(line);
    }
  };
  new MutationObserver(decorate).observe(list, { childList: true, subtree: true });
  // A tap anywhere on a line while selecting: the stylesheet lets it through to the line itself, all but a
  // tap on its box, which ticks it alone. A key pressed on the line's artist, say, has that for its target, and
  // does what the artist's button says.
  list.addEventListener("click", (e) => {
    const line = e.target;
    if (!selecting() || !(line instanceof HTMLElement) || !line.dataset.picker) return;
    const box = line.querySelector(".pick input");
    if (box) box.click();  // its change event picks the song, or lets it go
  });

  // On a phone: whether the menu and the name show, unfolded under the bar's line by its button.
  const folds = () => getComputedStyle(unfold).display !== "none";
  const setOpen = (on, focus) => {
    bar.classList.toggle("open", on);
    unfold.setAttribute("aria-expanded", on ? "true" : "false");
    unfold.className = on ? "btn pick-open" : "btn primary pick-open";  // open, the button that makes it leads
    if (on && focus) (nameLabel.hidden ? into : nameInput).focus();
  };
  unfold.addEventListener("click", () => setOpen(!bar.classList.contains("open"), true));
  bar.addEventListener("keydown", (e) => {
    // A name may hold a "/", which elsewhere on the page goes to the search box.
    if (e.key === "/" && e.target === nameInput) e.stopPropagation();
    if (e.key === "Escape" && bar.classList.contains("open") && folds()) {
      setOpen(false);
      unfold.focus();
    }
  });

  const setMode = (on) => {
    document.body.classList.toggle("selecting", on);
    toggle.setAttribute("aria-pressed", on ? "true" : "false");  // its name stays "Select": pressed or not
    const inBar = bar.contains(document.activeElement);
    bar.hidden = !on;
    setOpen(false);
    if (!on && inBar) toggle.focus({ preventScroll: true });  // not lost with the bar
    decorate();
    paintAll();
  };
  toggle.addEventListener("click", () => setMode(!selecting()));
  done.addEventListener("click", () => setMode(false));
  // A line's "Add to a songbook…" (library.js): Select, that song picked, and the bar's menu or name field to
  // say which songbook (unfolded on a phone).
  document.addEventListener("caracole:pick", (e) => {
    const id = String(e.detail && e.detail.id);
    if (!songs.has(id)) return;
    if (!selecting()) setMode(true);
    pick(id, true);
    if (folds()) setOpen(true, true);
    else (intoLabel.hidden ? nameInput : into).focus();
  });
  // The Songbooks tab's + New songbook (songbooks.js, which has shown the library): Select, the bar ready for a new
  // songbook's name, its songs to pick.
  document.addEventListener("caracole:new-songbook", () => {
    if (!selecting()) setMode(true);
    into.value = "";
    paintAll();
    if (folds()) setOpen(true, true);
    else nameInput.focus();
  });
  clear.addEventListener("click", () => {
    picked.length = 0;
    paintAll();
  });
  into.addEventListener("change", paintAll);
  // The songbooks there are now, once a songbook's change is over (library.js): the menu keeps its choice.
  document.addEventListener("caracole:songbooks", (e) => {
    const now = names(e.detail && e.detail.songbooks && e.detail.songbooks.books);
    const chosen = into.value;
    while (into.options.length > 1) into.remove(1);
    for (const name of now) into.appendChild(new Option(name, name));
    into.value = now.indexOf(chosen) >= 0 ? chosen : "";
    intoLabel.hidden = !now.length;
    paintAll();
  });
  // The server's answer to the bar's form: on its way, the picks go and the mode ends (the page shows the
  // songbook in its tab, songbooks.js); refused, the bar says why, and the picks stay.
  form.addEventListener("caracole:sent", (e) => {
    sending = false;
    if (e.detail && e.detail.ok) {
      picked.length = 0;
      nameInput.value = "";
      into.value = "";
      setMode(false);
    } else {
      error.textContent = String(e.detail && e.detail.error || "");
      paintAll();
    }
  });
  copy.addEventListener("click", () => {
    // Without the clipboard (refused, or none), the command unfolds, selected, to copy by hand.
    const byHand = () => {
      commandFold.open = true;
      const range = document.createRange();
      range.selectNodeContents(commandText);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(commandText.textContent).then(() => { copy.textContent = "Copied"; }, byHand);
    } else {
      byHand();
    }
  });
  form.addEventListener("submit", (e) => {
    const existing = into.value;
    const name = existing || nameInput.value.split(/\s+/).filter(Boolean).join(" ");
    error.textContent = "";
    if (!picked.length) {
      e.preventDefault();
      error.textContent = "Pick a song or more first.";
      return;
    }
    if (!name || name.startsWith(".")) {
      e.preventDefault();
      error.textContent = name ? "A songbook's name can't start with a dot." : "Give the songbook a name.";
      nameInput.focus();
      return;
    }
    if (server) {
      form.setAttribute("action", existing ? "/songbook/add" : "/songbook/make");
      fields.name.value = name;
      fields.songs.value = picked.join(",");
      sending = true;
      submit.disabled = true;
      return;  // the Songbooks tab's script posts it, and its songbook says how it goes
    }
    e.preventDefault();
    const words = ["caracole songbook", existing ? "add" : "make", shellQuote(name)];
    for (const id of picked) words.push(shellQuote(songs.get(id).display));
    commandText.textContent = words.join(" ");
    commandFold.open = false;
    command.hidden = false;
    copy.textContent = "Copy";
  });
})();
