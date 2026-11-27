"""``FakeGh``: a stand-in for the GitHub CLI, a script in the test's folder over a JSON state file
(``state.json``), so no test reaches GitHub. It answers what nix/publish-indexes.sh asks:

- ``release view TAG`` (exit 1 when there is no release), ``release create TAG ...`` (a prerelease with
  ``--prerelease``), ``release edit TAG --prerelease``, ``release upload TAG FILE`` (no ``--clobber``: an
  existing name fails);
- ``api repos/R/releases/tags/TAG`` (the release, with its ``id`` and ``prerelease``), ``api repos/R/releases/ID/assets``
  (``--paginate``: one JSON array a page of two; the REST asset shape: numeric ``id``, ``name``,
  ``size``, ``state``, ``digest``)
  and ``api -X DELETE repos/R/releases/assets/ID``.

Every path checks the repository and the release's tag it is asked for against the fake's own (``FakeGh(root, tag=,
repo=)``: ``indexes`` and ``o/r`` by default): another answers as GitHub would one it lacks (exit 1, "HTTP 404"), so a
script that names the wrong release or repository fails its test. Every call is logged to ``calls.jsonl`` with
``GH_TOKEN``. ``FAKE_GH_FAIL=<kind>:<n>`` makes the
n-th call of that kind fail (exit 1, nothing changed); kinds: ``create``, ``edit``, ``upload``, and ``api`` for the
changing api calls (DELETE) alone. A state's ``corrupt_upload`` makes an upload list a digest that is not the file's,
``no_digest`` none at all.

An upload reads its file as gh does, through one open file: ``FAKE_GH_SLOW=<seconds>`` reads it a quarter at a time,
that long after each (so its position, /proc's fdinfo ``pos``, moves as an upload's would);
``FAKE_GH_WAIT=<seconds>`` waits that long before it opens the file (no position to read meanwhile).
"""

from __future__ import annotations

import hashlib
import json
import stat
import sys
from pathlib import Path
from typing import Any

SCRIPT = r'''
import base64, hashlib, json, os, sys, time
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

def wrong(why):
    save()
    sys.stderr.write(f"HTTP 404: {why}\n")
    sys.exit(1)

# The repository and the tag every path names must be the fake's own.
if argv[:1] == ["release"]:
    if option("--repo") != state["repo"]:
        wrong(f"no repository {option('--repo')}")
    if argv[2] != state["tag"] and argv[1] != "create":
        wrong(f"no release {argv[2]}")
    if argv[1] == "create" and argv[2] != state["tag"]:
        wrong(f"a release {argv[2]} isn't the one this test expects")
elif argv[:1] == ["api"]:
    route = next(x for x in argv[1:] if x.startswith("repos/"))
    if not route.startswith("repos/" + state["repo"] + "/"):
        wrong(f"no repository in {route}")
    if "/releases/tags/" in route and route.rsplit("/", 1)[1] != state["tag"]:
        wrong(f"no release in {route}")

if argv[:2] == ["release", "view"]:
    sys.exit(0 if state["release"] else 1)
if argv[:2] == ["release", "create"]:
    fails("create")
    state["release"] = {"tag": argv[2], "args": argv[3:], "prerelease": "--prerelease" in argv}
elif argv[:2] == ["release", "edit"]:
    if not state["release"]:
        sys.exit(1)
    fails("edit")
    if "--prerelease" in argv:
        state["release"]["prerelease"] = True
elif argv[:2] == ["release", "upload"]:
    if not state["release"]:
        sys.exit(1)
    fails("upload")
    path = Path(argv[-1])
    time.sleep(float(os.environ.get("FAKE_GH_WAIT") or 0))
    slow = float(os.environ.get("FAKE_GH_SLOW") or 0)
    with open(path, "rb", buffering=0) as f:
        size = os.fstat(f.fileno()).st_size
        parts = []
        while chunk := f.read(max(1, size // 4) if slow else -1):
            parts.append(chunk)
            time.sleep(slow)
    data = b"".join(parts)
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
            print(json.dumps({"tag_name": state["tag"], "id": 7,
                              "prerelease": bool(state["release"].get("prerelease")), "assets": shown}))
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
    def __init__(self, root: Path, *, tag: str = "indexes", repo: str = "o/r"):
        self.root = root
        self.tag = tag
        root.mkdir(parents=True, exist_ok=True)
        self.state: dict[str, Any] = {"release": None, "assets": [], "next_id": 100, "counts": {},
                                      "corrupt_upload": False, "tag": tag, "repo": repo}
        (root / "gh").write_text("#!" + sys.executable + "\n" + SCRIPT, encoding="utf-8")
        (root / "gh").chmod((root / "gh").stat().st_mode | stat.S_IXUSR)
        self.save()

    def save(self) -> None:
        (self.root / "state.json").write_text(json.dumps(self.state), encoding="utf-8")

    def load(self) -> None:
        self.state = json.loads((self.root / "state.json").read_text(encoding="utf-8"))

    def release(self, *, prerelease: bool = True) -> FakeGh:
        """The release, made as the script makes it (a prerelease), or ``prerelease=False`` as it was made once."""
        self.state["release"] = {"tag": self.tag, "args": [], "prerelease": prerelease}
        self.save()
        return self

    def asset(self, name: str, data: bytes = b"x", *, state: str = "uploaded", size: int | None = None,
              digest: str | None = None, no_digest: bool = False) -> FakeGh:
        import base64

        self.state["release"] = self.state["release"] or {"tag": self.tag, "args": [], "prerelease": True}
        self.state["next_id"] += 1
        self.state["assets"].append({
            "id": self.state["next_id"], "name": name, "size": len(data) if size is None else size,
            "state": state, "digest": None if no_digest else digest or "sha256:" + hashlib.sha256(data).hexdigest(),
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
