# Installing caracole

caracole needs Python 3.12 or newer (tested on 3.14), ChordPro 6.050.7 and its fonts, one of them
with Chinese glyphs, and alphaTab for Guitar Pro files in the browser. Auto-chords also needs torch,
two model files and yt-dlp. The flake's packages bring all of it, for x86_64-linux.

- **On a server**, as a nightly service: [deploy.md](deploy.md), on [NixOS](deploy.md#nixos) or on
  [Ubuntu 24.04 without Nix](deploy.md#ubuntu-2404-without-nix).
- **[With Nix](#with-nix)**, on any Linux, to run it by hand.
- **[From source](#from-source)**, to change caracole and run its tests.
- **[On Android](#on-android)**, the app that keeps a copy of your library on the phone.

caracole keeps no credentials or tokens. `caracole serve` has no sign-in, so only run it on a
network you trust ([usage.md](usage.md#caracole-serve)).

## With Nix

```sh
nix run github:Danielhp95/caracole -- --help                  # once, without installing
nix profile add github:Danielhp95/caracole                    # caracole on your PATH
nix profile add 'github:Danielhp95/caracole#autochords'       # or with auto-chords (about 3 GB)
nix profile add 'github:Danielhp95/caracole#autochords-cuda'  # auto-chords on torch-bin, for an NVIDIA GPU (about 7 GB, unfree CUDA libraries)
```

On NixOS, the module's `services.caracole.autochords.cuda = true` picks the CUDA package and lets
caracole-web use the GPU ([deploy.md](deploy.md#4-auto-chords)).

Before Nix 2.30, `nix profile add` was `nix profile install`. caracole reads
`~/.config/caracole/caracole.toml` ([usage.md](usage.md#configure)).

To run it as a service on a system with Nix that isn't NixOS, install it into its own profile, so
the units get a fixed path (use `#autochords` for auto-chords). Then follow [deploy.md's Ubuntu
part](deploy.md#ubuntu-2404-without-nix) from section 6, with
`/nix/var/nix/profiles/caracole/bin/caracole` in place of `/opt/caracole/bin/caracole`. The
package's wrapper replaces section 5, and `#autochords` replaces the first two blocks of section 12;
you still write its unit. From section 1, install only `curl` (the failure alert) and `sqlite3`
(the backup).

```sh
sudo -i nix profile add --profile /nix/var/nix/profiles/caracole github:Danielhp95/caracole
sudo -i nix profile upgrade --profile /nix/var/nix/profiles/caracole --all   # to update
```

Use `sudo -i`, because Ubuntu's `sudo` resets PATH to one without Nix.

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
nix develop .#autochords-cuda -c pytest -m autochords  # the same, on torch-bin (CUDA)
```

Both shells set `CARACOLE_CJK_FONT`, `CARACOLE_PDF_FONTS` and `CARACOLE_ALPHATAB_DIR`.
`.#autochords` also sets `CARACOLE_BTC_WEIGHTS`, `CARACOLE_BEAT_CHECKPOINT`,
`CARACOLE_WHISPER_MODEL` and `CARACOLE_DEMUCS_MODEL`, and puts `demucs` on PATH. That is
demucs-rs's CPU build, which takes about 5x a song's length.

`.#autochords-cuda` sets the same, but with nixpkgs' prebuilt CUDA torch (`torch-bin`; nixpkgs' own
`torch` is CPU-only) and the GPU build of `demucs`, about 35 s for a 149 s song. It also sets
`CARACOLE_TORCH_CUDA=1`, as the `autochords-cuda` package does, so caracole says a transcription
takes a couple of minutes rather than up to half an hour.

Without Nix, on Ubuntu, first follow sections 1 to 4 of [deploy.md's Ubuntu
part](deploy.md#ubuntu-2404-without-nix) (Python, ChordPro, the fonts), then, in the checkout:

```sh
uv venv --python /opt/caracole/python/cpython-3.14.7-linux-x86_64-gnu/bin/python3.14 .venv
uv pip install --python .venv/bin/python -c /opt/caracole/constraints.txt -e . pytest pytest-xdist
PATH=/opt/caracole/perl/bin:$PATH PERL5LIB=/opt/caracole/perl/lib/perl5 \
  CARACOLE_CJK_FONT=/opt/caracole/fonts/FusionKaiJ-Regular.ttf \
  CARACOLE_PDF_FONTS=/opt/caracole/pdf-fonts CARACOLE_ALPHATAB_DIR=/opt/caracole/alphatab \
  .venv/bin/pytest -q
```

Run the tests as yourself, not as root: the permission tests skip under root. A test that can't
find a program or file it needs skips:

| Without | These tests skip |
|---|---|
| `chordpro` on PATH | the real PDFs (marked `chordpro`) |
| `CARACOLE_CJK_FONT` | the two Chinese PDFs |
| `CARACOLE_PDF_FONTS` (Adwaita's four files) | the real PDFs in Adwaita Sans, and the two-column estimates in its widths |
| `CARACOLE_ALPHATAB_DIR` (alphaTab's three files) | caracole serve's Guitar Pro page in a browser |
| torch, librosa and beat_this, or `CARACOLE_BTC_WEIGHTS` and `CARACOLE_BEAT_CHECKPOINT` | the model tests (marked `autochords`) |
| `ffmpeg`, `chromium` | one `.m4a` test; the pages in a browser |

[AGENTS.md](../AGENTS.md#development) lists every such test and variable.

## On Android

- **From F-Droid**: in the F-Droid app, Settings › Repositories › **+**, scan or paste
  `https://danielhp95.github.io/caracole/fdroid/repo?fingerprint=B34AD39AD80D6CE828F0885C68FD81816230BB3CB482C9E7BCC6DAD844500397`,
  then install caracole from its list. F-Droid keeps it updated.
- **Built yourself**: [android/README.md](../android/README.md#build).
- Then connect it to your computer: [phone.md](phone.md#install-and-connect).
