"""Which library a page shows: its name, and a badge for a library that isn't the owner's usual one.

Every page caracole serve serves names the library it shows, in its header and its browser tab's title ("caracole ·
Tabs"), and so does the index.html caracole writes into the library: caracole.toml's ``name``, else the library
folder's name (``Config.library_name``). A server started on a library that isn't the usual one says so too, with a
badge beside the name on every page it writes itself, first in each title, and an icon of another colour in the tab
(``LibraryName``), so that its pages are never taken for the usual library's. The written index.html never carries
one: it is the library's own page, wherever it is opened.

``scratch_badge`` decides, once, when ``caracole serve`` starts:

- ``caracole serve --label TEXT`` names it: "Demo" (docs/screenshots/make.py's demo library), "Test"; ``--label ""``
  shows none, wherever the library is.
- Without it, a library whose config file, library folder or state folder is in a temporary folder (/tmp, /var/tmp,
  /dev/shm, or ``$TMPDIR``, ``$TEMP``, ``$TMP``: nix develop's, an agent's scratchpad, pytest's) is a scratch library
  (``SCRATCH``). The owner's libraries are never there: the NixOS service's and Ubuntu's in /var/lib/caracole, its
  caracole.toml in the Nix store or /etc, and a library run by hand in the home folder with its XDG state. A
  temporary folder that holds the home folder, or is the root, counts for nothing.

Not "the state folder isn't the service's": a library run by hand at home has its own, and is the owner's too.

The standard library alone, and page_icon.py's mark.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING

from caracole.page_icon import ACCENT, LINK, SVG

if TYPE_CHECKING:
    from caracole.config import Config

SCRATCH = "Scratch library"  # the badge of a library in a temporary folder
LABEL_LIMIT = 40  # characters of a badge
TEMPORARY = ("/tmp", "/var/tmp", "/dev/shm")
TEMPORARY_VARIABLES = ("TMPDIR", "TEMP", "TMP")
BADGE_TITLE = "Not your usual library"  # the badge's tooltip
SCRATCH_COLOUR = "#7a4c00"  # base.css's --wanted, light: the badge's colour, and its icon's
_SCRATCH_ICON = SVG.replace(ACCENT, SCRATCH_COLOUR)
SCRATCH_LINK = ('<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,'
                + base64.b64encode(_SCRATCH_ICON.encode("utf-8")).decode("ascii") + '">\n')


@dataclass(frozen=True)
class LibraryName:
    """What a page says of the library it shows: ``name``, and ``badge`` for one that isn't the usual library."""

    name: str
    badge: str | None = None

    def title(self, page: str = "") -> str:
        """A browser tab's title: "caracole · Tabs", the page's own before it ("Look up · caracole · Tabs"), and a
        badge first ("Scratch library · caracole · test-lib"), where a narrow tab still shows it."""
        return " · ".join(part for part in (self.badge, page, "caracole", self.name) if part)

    def markup(self, tag: str = "span") -> str:
        """The name, and the badge after it, for a page's header (base.css's ``.libname``), escaped."""
        badge = (f' <span class="scratch" title="{BADGE_TITLE}">{escape(self.badge, quote=True)}</span>'
                 if self.badge else "")
        return f'<{tag} class="libname"><span class="name">{escape(self.name, quote=True)}</span>{badge}</{tag}>'

    def icon(self) -> str:
        """The page's icon, for its head: caracole's, or, with a badge, the same "¿" in the badge's colour."""
        return SCRATCH_LINK if self.badge else LINK


def scratch_badge(cfg: Config, *, label: str | None = None, config_path: Path | None = None,
                  env: Mapping[str, str] | None = None) -> str | None:
    """The badge caracole serve's pages show for ``cfg``'s library: ``label`` when one is given ("" for none), else
    ``SCRATCH`` when its config file, library folder or state folder is in a temporary folder, else None."""
    if label is not None:
        return label.strip()[:LABEL_LIMIT] or None
    roots = temporary_folders(os.environ if env is None else env)
    if any(path is not None and _inside(path, roots) for path in (config_path, cfg.library_dir, cfg.state_dir)):
        return SCRATCH
    return None


def temporary_folders(env: Mapping[str, str]) -> list[str]:
    """The temporary folders, resolved: the system's and those ``env`` names, less one that holds the home folder or
    is the root."""
    home = _resolved(env["HOME"]) if env.get("HOME") else None
    found = []
    for folder in (*TEMPORARY, *(env.get(name, "") for name in TEMPORARY_VARIABLES)):
        if not folder or not os.path.isabs(folder):
            continue
        root = _resolved(folder)
        if root == os.sep or (home is not None and _within(home, root)) or root in found:
            continue
        found.append(root)
    return found


def _inside(path: Path, roots: list[str]) -> bool:
    resolved = _resolved(str(path))
    return any(_within(resolved, root) for root in roots)


def _within(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _resolved(path: str) -> str:
    return os.path.realpath(path)
