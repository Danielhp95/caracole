# Installing caracole

caracole needs Python 3.12 or newer (it is tested on 3.14), ChordPro 6.050.7
for the PDFs, the fonts they are set in and one with Chinese glyphs, alphaTab
for Guitar Pro files in the browser and, for auto-chords alone, torch, two
model files and yt-dlp. The flake's packages bring all of it, for x86_64-linux.

- **On a server**, as a nightly service: [deploy.md](deploy.md), on
  [NixOS](deploy.md#nixos) or on [Ubuntu 24.04 without
  Nix](deploy.md#ubuntu-2404-without-nix).
- **[With Nix](#with-nix)**, on any Linux, to run it by hand.
- **[From source](#from-source)**, to change caracole and run its tests.

caracole keeps no secret: no credential and no token. `caracole serve` has no
sign-in, so it listens only on a network you trust
([usage.md](usage.md#caracole-serve)).

## With Nix

```sh
nix run github:Danielhp95/caracole -- --help                  # once, without installing
nix profile add github:Danielhp95/caracole                    # caracole on your PATH
nix profile add 'github:Danielhp95/caracole#autochords'       # or with auto-chords (about 3 GB)
```

Before Nix 2.30, `nix profile add` was `nix profile install`. caracole then
reads `~/.config/caracole/caracole.toml` ([usage.md](usage.md#configure)).

To run it as a service on a system with Nix that isn't NixOS, install it into
a profile of its own, which gives the units a fixed path (`#autochords` for
auto-chords), then follow [deploy.md's Ubuntu
part](deploy.md#ubuntu-2404-without-nix) from section 6, with
`/nix/var/nix/profiles/caracole/bin/caracole` in place of
`/opt/caracole/bin/caracole`. The package's wrapper does what section 5's
does, and brings what section 12 installs. Of section 1's packages, install
`curl` (the failure alert) and `sqlite3` (the backup).

```sh
sudo -i nix profile add --profile /nix/var/nix/profiles/caracole github:Danielhp95/caracole
sudo -i nix profile upgrade --profile /nix/var/nix/profiles/caracole --all   # to update
```

`sudo -i`, as Ubuntu's `sudo` resets PATH to one without Nix.

## From source

```sh
git clone https://github.com/Danielhp95/caracole
cd caracole
```

With Nix:

```sh
nix develop                                         # Python, the dependencies, pytest, pytest-xdist, chordpro, ruff, sqlite3
pytest -q                                           # every test, on up to 12 cores
pytest -q -m "not slow"                             # all but the browser, chordpro, model and second-process tests
nix develop .#autochords -c pytest -m autochords    # the model tests, with the model files
```

Both shells set `CARACOLE_CJK_FONT`, `CARACOLE_PDF_FONTS` and `CARACOLE_ALPHATAB_DIR`, and
`.#autochords` also sets `CARACOLE_BTC_WEIGHTS` and `CARACOLE_BEAT_CHECKPOINT`.

Without Nix, on Ubuntu, first sections 1 to 4 of [deploy.md's Ubuntu
part](deploy.md#ubuntu-2404-without-nix) (Python, ChordPro, the fonts), then,
in the checkout:

```sh
uv venv --python /opt/caracole/python/cpython-3.14.7-linux-x86_64-gnu/bin/python3.14 .venv
uv pip install --python .venv/bin/python -c /opt/caracole/constraints.txt -e . pytest pytest-xdist
PATH=/opt/caracole/perl/bin:$PATH PERL5LIB=/opt/caracole/perl/lib/perl5 \
  CARACOLE_CJK_FONT=/opt/caracole/fonts/FusionKaiJ-Regular.ttf \
  CARACOLE_PDF_FONTS=/opt/caracole/pdf-fonts CARACOLE_ALPHATAB_DIR=/opt/caracole/alphatab \
  .venv/bin/pytest -q
```

Run the tests as yourself, not as root: the permission tests skip under root.
A test that needs a program or a file it can't find skips:

| Without | These tests skip |
|---|---|
| `chordpro` on PATH | the real PDFs (marked `chordpro`) |
| `CARACOLE_CJK_FONT` | the two Chinese PDFs |
| `CARACOLE_PDF_FONTS` (Adwaita's four files) | the real PDFs in Adwaita Sans, and the two-column estimates in its widths |
| `CARACOLE_ALPHATAB_DIR` (alphaTab's three files) | caracole serve's Guitar Pro page in a browser |
| torch, librosa and beat_this, or `CARACOLE_BTC_WEIGHTS` and `CARACOLE_BEAT_CHECKPOINT` | the model tests (marked `autochords`) |
| `ffmpeg`, `chromium` | one `.m4a` test; the pages in a browser |

[AGENTS.md](../AGENTS.md#development) lists every such test and variable.
