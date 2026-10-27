"""``FakeYtDlp``: a stand-in for yt-dlp, written as a script in the test's folder, so no test
reaches YouTube.

caracole runs yt-dlp as a program (youtube.py), so the fake is a program too: a short
Python script, run with the tests' own interpreter, that answers from a plan the test
writes (``plan.json`` beside it) and logs every call it gets (``calls.jsonl``): its
arguments, the environment variables caracole sets (``watch_env``), the names of all it
was given, and its process id.

- A search (``ytsearchN:<query>``) prints the playlist JSON yt-dlp's ``--flat-playlist
  --dump-single-json`` prints: the entries the plan lists for the query, at most N.
- A download (a watch URL) writes the video's bytes where ``-o`` says, the extension
  filled in, and prints the fields of its ``--print after_move:`` template as JSON.
- Either can instead fail as yt-dlp does (``ERROR: ...`` on stderr, exit 1), or hang a while
  (``sleep``): a run that sleeps it out says so (``woke``), one stopped first never does.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

SCRIPT = r'''
import json, os, re, sys, time
from pathlib import Path

here = Path(__file__).resolve().parent
plan = json.loads((here / "plan.json").read_text(encoding="utf-8"))
argv = sys.argv[1:]
with open(here / "calls.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": argv, "env": {k: os.environ.get(k) for k in plan["watch_env"]},
                          "env_names": sorted(os.environ), "pid": os.getpid()}) + "\n")
target = argv[argv.index("--") + 1] if "--" in argv else argv[-1]

def answer(spec):
    if spec.get("sleep"):
        time.sleep(spec["sleep"])
        with open(here / "woke.jsonl", "a", encoding="utf-8") as log:
            log.write(json.dumps({"pid": os.getpid()}) + "\n")
    if spec.get("stderr"):
        sys.stderr.write(spec["stderr"] + "\n")
    if spec.get("exit"):
        sys.exit(spec["exit"])

m = re.fullmatch(r"ytsearch(\d+):(.*)", target, re.S)
if m:
    spec = plan["searches"].get(m.group(2))
    if spec is None:
        spec = {"entries": []}
    answer(spec)
    entries = spec.get("entries", [])[: int(m.group(1))]
    print(json.dumps({"_type": "playlist", "id": m.group(2), "title": m.group(2), "entries": entries}))
    sys.exit(0)

vid = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", target)
spec = plan["videos"].get(vid.group(1) if vid else target)
if spec is None:
    sys.stderr.write("ERROR: [youtube] %s: Video unavailable\n" % (vid.group(1) if vid else target))
    sys.exit(1)
answer(spec)
template = argv[argv.index("-o") + 1]
path = Path(template.replace("%(ext)s", spec.get("ext", "m4a")))
path.write_bytes(spec.get("data", "fake audio").encode("utf-8"))
info = {k: spec[k] for k in ("id", "title", "channel", "uploader", "duration") if k in spec}
info["filepath"] = spec.get("print_path", str(path))
print(json.dumps(info))
'''


def entry(video_id: str, title: str, channel: str, duration: float | None = 200, **more: Any) -> dict[str, Any]:
    """One search result as yt-dlp's flat search lists it."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    return {"_type": "url", "ie_key": "Youtube", "id": video_id, "url": url, "title": title,
            "duration": duration, "channel": channel, "uploader": channel, **more}


class FakeYtDlp:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "yt-dlp"
        self.searches: dict[str, dict[str, Any]] = {}
        self.videos: dict[str, dict[str, Any]] = {}
        self.path.write_text(f"#!{sys.executable}\n{SCRIPT}", encoding="utf-8")
        self.path.chmod(self.path.stat().st_mode | stat.S_IXUSR)
        self.save()

    @property
    def bin(self) -> str:
        return str(self.path)

    def save(self) -> None:
        plan = {"searches": self.searches, "videos": self.videos, "watch_env": ["DENO_V8_FLAGS", "HOME"]}
        (self.root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")

    def search(self, query: str, *entries: dict[str, Any], **spec: Any) -> FakeYtDlp:
        """What a search for ``query`` answers: these entries, or ``stderr`` and ``exit``."""
        self.searches[query] = {"entries": list(entries), **spec}
        self.save()
        return self

    def video(self, video_id: str, title: str = "A video", channel: str = "A channel", duration: float = 200,
              **spec: Any) -> FakeYtDlp:
        """What a download of the video does: its file and fields, or ``stderr`` and ``exit``."""
        self.videos[video_id] = {"id": video_id, "title": title, "channel": channel, "uploader": channel,
                                 "duration": duration, **spec}
        self.save()
        return self

    def calls(self) -> list[dict[str, Any]]:
        log = self.root / "calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]

    def argvs(self) -> list[list[str]]:
        return [c["argv"] for c in self.calls()]

    def woke(self) -> list[int]:
        """The process ids of the runs that slept their ``sleep`` out: none that was stopped before."""
        log = self.root / "woke.jsonl"
        if not log.exists():
            return []
        return [json.loads(line)["pid"] for line in log.read_text(encoding="utf-8").splitlines() if line]


def route_on(cfg, tmp_path: Path, monkeypatch, fake: FakeYtDlp | None = None):
    """``cfg`` for a caracole with auto-chords (its packages taken to be there), model files
    in tmp_path and ``fake`` as yt-dlp: the YouTube route is on. Returns (config, fake)."""
    import dataclasses

    import caracole.youtube_fetch as yf
    from caracole.config import AutochordsConfig

    monkeypatch.setattr(yf, "autochords_missing", lambda: [])
    models = tmp_path / "models"
    models.mkdir(exist_ok=True)
    for name in ("btc.pt", "beat.ckpt"):
        (models / name).write_bytes(b"m")
    fake = fake or FakeYtDlp(tmp_path / "bin")
    on = dataclasses.replace(cfg, ytdlp_bin=fake.bin,
                             autochords=AutochordsConfig(models / "btc.pt", models / "beat.ckpt"))
    return on, fake


def no_ytdlp_on_path(monkeypatch) -> None:
    """Keep a real yt-dlp, if the machine has one, out of reach of the code under test."""
    monkeypatch.setenv("PATH", os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep)
                                               if not (Path(p) / "yt-dlp").exists()))
