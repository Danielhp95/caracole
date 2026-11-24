"""``FakeGh``: a stand-in for the GitHub CLI, a script in the test's folder over a JSON state file
(``state.json``), so no test reaches GitHub. It answers what nix/publish-indexes.sh asks:

- ``release view TAG`` (exit 1 when there is no release), ``release create TAG ...``,
  ``release upload TAG FILE`` (no ``--clobber``: an existing name fails);
- ``api repos/R/releases/tags/TAG`` (the release, with its ``id``), ``api repos/R/releases/ID/assets``
  (``--paginate``: one JSON array a page of two; the REST asset shape: numeric ``id``, ``name``,
  ``size``, ``state``, ``digest``)
  and ``api -X DELETE repos/R/releases/assets/ID``.

Every call is logged to ``calls.jsonl`` with ``GH_TOKEN``. ``FAKE_GH_FAIL=<kind>:<n>`` makes the
n-th call of that kind fail (exit 1, nothing changed); kinds: ``create``, ``upload``, and ``api`` for the changing api calls (DELETE) alone. A state's
``corrupt_upload`` makes an upload list a digest that is not the file's, ``no_digest`` none at all.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

SCRIPT = r'''
import base64, hashlib, json, os, sys
from pathlib import Path

here = Path(__file__).resolve().parent
state_file = here / "state.json"
state = json.loads(state_file.read_text())
argv = sys.argv[1:]
with open(here / "calls.jsonl", "a") as log:
    log.write(json.dumps({"argv": argv, "token": os.environ.get("GH_TOKEN")}) + "\n")

def save():
    state_file.write_text(json.dumps(state))

def fails(kind):
    state["counts"][kind] = state["counts"].get(kind, 0) + 1
    want = os.environ.get("FAKE_GH_FAIL", "")
    if want == f"{kind}:{state['counts'][kind]}":
        save()
        sys.stderr.write(f"fake gh: {kind} failed\n")
        sys.exit(1)

def asset_by(id=None, name=None):
    for a in state["assets"]:
        if (id is not None and str(a["id"]) == str(id)) or (name is not None and a["name"] == name):
            return a
    return None

def option(flag):
    return argv[argv.index(flag) + 1] if flag in argv else None

def remove(a):
    state["assets"].remove(a)

if argv[:2] == ["release", "view"]:
    sys.exit(0 if state["release"] else 1)
if argv[:2] == ["release", "create"]:
    fails("create")
    state["release"] = {"tag": argv[2], "args": argv[3:]}
elif argv[:2] == ["release", "upload"]:
    if not state["release"]:
        sys.exit(1)
    fails("upload")
    path = Path(argv[-1])
    data = path.read_bytes()
    if asset_by(name=path.name):
        sys.stderr.write("fake gh: an asset of that name exists\n")
        sys.exit(1)
    digest = hashlib.sha256(data).hexdigest()
    if state.get("corrupt_upload"):
        digest = "0" * 64
    state["next_id"] += 1
    state["assets"].append({"id": state["next_id"], "name": path.name, "size": len(data), "state": "uploaded",
                            "digest": None if state.get("no_digest") else "sha256:" + digest, "content": base64.b64encode(data).decode()})
elif argv[0] == "api":
    method = option("-X") or "GET"
    endpoint = next(x for x in argv[1:] if x.startswith("repos/"))
    if method == "GET":
        if not state["release"]:
            sys.stderr.write("HTTP 404\n")
            sys.exit(1)
        shown = [{k: v for k, v in a.items() if k != "content"} for a in state["assets"]]
        if "/assets" in endpoint:
            # --paginate: one array a page, two assets a page, as GitHub's pages are
            for n in range(0, max(len(shown), 1), 2):
                print(json.dumps(shown[n:n + 2]))
        else:
            print(json.dumps({"tag_name": "indexes", "id": 7, "assets": shown}))
        sys.exit(0)
    fails("api")
    a = asset_by(id=endpoint.rsplit("/", 1)[1])
    if not a:
        sys.exit(1)
    if method == "DELETE":
        remove(a)
else:
    sys.exit(2)
save()
'''


class FakeGh:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.state: dict[str, Any] = {"release": None, "assets": [], "next_id": 100, "counts": {},
                                      "corrupt_upload": False}
        (root / "gh").write_text("#!" + sys.executable + "\n" + SCRIPT, encoding="utf-8")
        (root / "gh").chmod((root / "gh").stat().st_mode | stat.S_IXUSR)
        self.save()

    def save(self) -> None:
        (self.root / "state.json").write_text(json.dumps(self.state), encoding="utf-8")

    def load(self) -> None:
        self.state = json.loads((self.root / "state.json").read_text(encoding="utf-8"))

    def release(self) -> FakeGh:
        self.state["release"] = {"tag": "indexes", "args": []}
        self.save()
        return self

    def asset(self, name: str, data: bytes = b"x", *, state: str = "uploaded", size: int | None = None,
              digest: str | None = None) -> FakeGh:
        import base64

        self.state["release"] = self.state["release"] or {"tag": "indexes", "args": []}
        self.state["next_id"] += 1
        self.state["assets"].append({
            "id": self.state["next_id"], "name": name, "size": len(data) if size is None else size,
            "state": state, "digest": digest or "sha256:" + hashlib.sha256(data).hexdigest(),
            "content": base64.b64encode(data).decode()})
        self.save()
        return self

    def names(self) -> list[str]:
        self.load()
        return sorted(a["name"] for a in self.state["assets"])

    def content(self, name: str) -> bytes:
        import base64

        self.load()
        return base64.b64decode(next(a for a in self.state["assets"] if a["name"] == name)["content"])

    def calls(self) -> list[dict[str, Any]]:
        path = self.root / "calls.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
