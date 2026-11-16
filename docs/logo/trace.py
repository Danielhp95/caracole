"""caracole's logo as vectors: a master's black and its copper, each traced into one path, for the pages' icon
(src/caracole/page_icon.py, from caracole_icon.png) and the Android app's launcher icon
(android/app/src/main/res/drawable/ic_launcher_*.xml, from app_logo.png).

    python docs/logo/trace.py page docs/logo/caracole_icon.png
    python docs/logo/trace.py launcher docs/logo/app_logo.png

It needs ImageMagick's ``magick`` and ``potrace`` on PATH (``nix shell nixpkgs#imagemagick nixpkgs#potrace``). The
master is split by colour (copper: red well over blue; black: the rest of what is dark, or of what is opaque in a
master with no background), each part traced by potrace, then written in whole units of its target:

- ``page``: a square of 640 around the drawing, which fills 95 % of its height; and the drawing's own box, the bar's
  mark's viewBox;
- ``launcher``: an adaptive icon's 108 dp as 1080 units, the drawing centred and within 32.5 dp of the centre, inside
  the 66 dp circle every launcher's mask keeps.

It prints the two paths, black first. The colours are set where the paths go, read off the masters by hand.
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PARTS = {  # where each part is, as ImageMagick's -fx conditions: (black, copper)
    "page": ("(r-b)<=0.17 && (r+g+b)/3<0.5", "(r-b)>0.17"),
    "launcher": ("a>0.5 && (r-b)<=0.17", "a>0.5 && (r-b)>0.17"),
}
COMMANDS = set("MmLlCcZz")


def traced(master: Path, where: str, folder: Path) -> list[tuple]:
    """The part of ``master`` where ``where`` holds, as potrace draws it: ("M", p), ("L", p), ("C", p, q, r) and
    ("Z",), each point in the master's pixels."""
    bitmap, drawing = folder / "part.pbm", folder / "part.svg"
    subprocess.run(["magick", master, "-fx", f"({where}) ? 0 : 1", "-alpha", "off", "-colorspace", "gray",
                    "-threshold", "50%", bitmap], check=True)
    subprocess.run(["potrace", "-s", "--flat", "-t", "40", "-a", "1", "-O", "1", "-o", drawing, bitmap], check=True)
    svg = drawing.read_text()
    tx, ty, sx, sy = map(float, re.search(r"translate\(([-\d.]+),([-\d.]+)\) scale\(([-\d.]+),([-\d.]+)\)",
                                          svg).groups())
    tokens = re.findall(r"[MmLlCcZz]|-?[\d.]+", " ".join(re.findall(r' d="([^"]+)"', svg)))
    out, here, start, command, i = [], (0.0, 0.0), (0.0, 0.0), "", 0
    while i < len(tokens):
        if tokens[i] in COMMANDS:
            command, i = tokens[i], i + 1
            if command in "Zz":
                out.append(("Z",))
                here = start
                continue
        n = 6 if command in "Cc" else 2
        values = [float(v) for v in tokens[i:i + n]]
        i += n
        points = [(here[0] + values[k], here[1] + values[k + 1]) if command.islower() else (values[k], values[k + 1])
                  for k in range(0, n, 2)]
        here = points[-1]
        if command in "Mm":
            start = here
            out.append(("M", here))
            command = "l" if command == "m" else "L"
        else:
            out.append(("C" if n == 6 else "L", *points))
    return [(s[0], *((tx + sx * x, ty + sy * y) for x, y in s[1:])) for s in out]


def written(segments: list[tuple], x0: float, y0: float, scale: float) -> str:
    """The path in the target's whole units: an absolute M a subpath, then relative c and l, each from the point as
    written, so rounding never drifts."""
    def at(p):
        return round((p[0] - x0) * scale), round((p[1] - y0) * scale)

    def numbers(*pairs):
        text = ""
        for n in (str(v) for pair in pairs for v in pair):
            text += n if not text or n.startswith("-") else " " + n
        return text

    d, here, begin, last = [], (0, 0), (0, 0), ""
    for kind, *points in segments:
        if kind == "Z":
            d.append("z")
            here, last = begin, "z"
            continue
        points = [at(p) for p in points]
        if kind == "M":
            d.append("M" + numbers(points[0]))
            here = begin = points[0]
            last = "M"
            continue
        moves = [(x - here[0], y - here[1]) for x, y in points]
        if not any(any(m) for m in moves):
            continue
        letter, body = ("c" if kind == "C" else "l"), numbers(*moves)
        d.append(body if letter == last and body.startswith("-") else (" " if letter == last else letter) + body)
        here, last = points[-1], letter
    return "".join(d)


def main(target: str, master: Path) -> None:
    with tempfile.TemporaryDirectory() as folder:
        parts = [traced(master, where, Path(folder)) for where in PARTS[target]]
    points = [p for part in parts for _, *ps in part for p in ps]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    if target == "page":
        side = max(max(xs) - min(xs), max(ys) - min(ys)) / 0.95
        scale, x0, y0 = 640 / side, cx - side / 2, cy - side / 2
        left, top = math.floor((min(xs) - x0) * scale), math.floor((min(ys) - y0) * scale)
        right, bottom = math.ceil((max(xs) - x0) * scale), math.ceil((max(ys) - y0) * scale)
        print(f"mark viewBox: {left} {top} {right - left} {bottom - top}")
    else:
        scale = 325 / max(math.dist((cx, cy), p) for p in points)
        x0, y0 = cx - 540 / scale, cy - 540 / scale
    for name, part in zip(("black", "copper"), parts, strict=True):
        print(f"{name}: {written(part, x0, y0, scale)}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in PARTS:
        sys.exit(__doc__)
    main(sys.argv[1], Path(sys.argv[2]))
