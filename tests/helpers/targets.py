"""What a thumb needs of a page's controls, measured in Chromium (helpers/browser.py).

``small_targets(exempt)`` lists every control shown that is less than 44 px either way: a link, a
button, a field, a menu or a fold's summary (a box or a radio counts as its label, the Select mode's
box as its frame). A link in a line of text is left out, as WCAG 2.5.8 leaves it out, and so is
whatever the CSS selector ``exempt`` matches.

It is a JavaScript expression whose value is that list, for ``Browser.js``, or for ``noting``: a
script a test adds to the page (``with_script``), which writes the value into an attribute of the
body for ``noted`` to read back from ``dump_dom``. ``UNFOLD`` opens every fold and every row's "⋯"
first, so that what they hold is measured too.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

# What a test names each control by: its tag and classes, and its parent's first class.
_NAME = r"""
const name = (node) => {
  const classes = (n) => (typeof n.className === "string" ? n.className.trim().split(/\s+/).filter(Boolean) : []);
  const own = classes(node);
  const up = node.parentElement ? classes(node.parentElement) : [];
  return node.tagName.toLowerCase() + (own.length ? "." + own.join(".") : "") + (up.length ? " in ." + up[0] : "");
};
const said = (node) => String(node.getAttribute("aria-label") || node.textContent || node.value || "").trim()
  .replace(/\s+/g, " ").slice(0, 32);
"""

_SMALL = r"""
((exempt) => {
  __NAME__
  // A link among words of its own, in a line of text: WCAG 2.5.8 exempts it.
  const inText = (node) => node.tagName === "A" && getComputedStyle(node).display === "inline" &&
    node.parentElement.textContent.trim() !== node.textContent.trim();
  const short = [];
  for (const node of document.querySelectorAll('a[href], button, input:not([type="hidden"]), select, textarea, summary')) {
    if (!node.checkVisibility() || (exempt && node.matches(exempt)) || inText(node)) continue;
    const target = node.matches(".pick input") ? node.parentElement
      : node.matches('input[type="checkbox"], input[type="radio"]') ? node.closest("label") || node : node;
    const box = target.getBoundingClientRect();
    if (box.width < 43.5 || box.height < 43.5) {
      short.push({ what: name(node), said: said(node), width: Math.round(box.width), height: Math.round(box.height) });
    }
  }
  return short;
})
"""

UNFOLD = """
for (const fold of document.querySelectorAll("details")) fold.open = true;
for (const panel of document.querySelectorAll(".row-panel")) panel.hidden = false;
"""


def small_targets(exempt: str = "") -> str:
    """An expression: the controls shown that are less than 44 px either way (``exempt`` left out)."""
    return _SMALL.replace("__NAME__", _NAME) + f"({json.dumps(exempt)})"


def noting(attribute: str, expression: str) -> str:
    """A statement that writes the expression's value, as JSON, into an attribute of the body."""
    return f"document.body.setAttribute({json.dumps(attribute)}, JSON.stringify({expression}));\n"


def noted(dom: str, attribute: str) -> Any:
    """What ``noting`` wrote into ``attribute``, read back from a DOM dump."""
    found = re.search(rf'{re.escape(attribute)}="([^"]*)"', dom)
    assert found, f"the page noted no {attribute}: {dom[-1500:]}"
    return json.loads(html.unescape(found.group(1)))
