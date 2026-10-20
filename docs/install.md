# Installing caracole

caracole needs Python 3.12 or newer, ChordPro 6.050.7 for the PDFs, a font
with Chinese glyphs for Chinese sheets and, for auto-chords only, torch and
two model files. The Nix packages bring all of it. Without Nix you install
each one. The flake builds for x86_64-linux only.

- [NixOS](#nixos): the flake's module runs caracole every night.
- [Ubuntu](#ubuntu), [with Nix](#ubuntu-with-nix) or
  [without](#ubuntu-without-nix), then the same
  [systemd units](#run-it-nightly-on-ubuntu).
- [From source](#from-source), to change caracole and run its tests.

## NixOS

Add the flake to your system's `flake.nix`:

```nix
inputs.caracole.url = "github:Danielhp95/caracole";
```

Import its module and turn the service on:

```nix
{ inputs, ... }:
{
  imports = [ inputs.caracole.nixosModules.default ];

  services.caracole = {
    enable = true;
    # dataDir = "/data/caracole";   # default: /var/lib/caracole
  };
}
```

This needs `inputs` in `specialArgs`. Otherwise add
`caracole.nixosModules.default` to `modules` in `nixosSystem`. The module
runs the flake's own packages, built with the nixpkgs that caracole pins and
tests. `caracole.inputs.nixpkgs.follows = "nixpkgs";` builds them with your
nixpkgs instead.

You get `caracole.timer`, which starts a run at 03:30, up to 45 minutes late
(a run missed while the machine was off starts at the next boot). You also
get `caracole.service`, a hardened oneshot run as user `caracole`, and
`caracole-admin`, which runs any command the way the service does.
`services.caracole.settings` is `caracole.toml`, as
[usage.md](usage.md#configure) describes it, without the folder keys: those
come from the options.

**Secrets.** Give the module paths outside the Nix store, such as agenix's:

```nix
services.caracole.credentials = {
  ntfy_token = config.age.secrets.caracole-ntfy.path;
  spotify_client_secret = config.age.secrets.caracole-spotify.path;
};
```

systemd's `LoadCredential=` reads each file as root and gives the unit a
private copy in `$CREDENTIALS_DIRECTORY`. caracole reads
`$CREDENTIALS_DIRECTORY/ntfy_token` and
`$CREDENTIALS_DIRECTORY/spotify_client_secret`. The nightly unit and
`caracole-admin` get both. The auto-chords unit gets neither.

**Auto-chords:**

```nix
services.caracole.autochords.enable = true;
```

`caracole-autochords.service` then starts after each successful run, with no
network. It runs the flake's `autochords` package, whose wrapper points at
the two model files the flake downloads.

**After switching**, in this order:

```sh
sudo caracole-admin index build                 # once: UG's sitemaps, about 10 minutes
sudo caracole-admin add "Oasis" "Wonderwall"    # or edit wanted.txt in the library
sudo caracole-admin auth spotify                # only if you set up Spotify
systemctl list-timers caracole.timer            # when the next run starts
sudo systemctl start caracole.service           # one run now
journalctl -u caracole.service -e
```

Then read `_todo.md` in the library.

**Data** lives in `dataDir`, `/var/lib/caracole` unless you set it:

| Folder | Holds |
|---|---|
| `library` | sheets, lyrics, `_todo.md`, `index.html`, `wanted.txt`, `overrides.toml` |
| `music` | audio you bought, read-only, for auto-chords |
| `state` | the database, the Spotify token and the lock: back it up, don't sync it |
| `cache` | every HTTP response, kept: losing it costs only requests |

`libraryDir`, `musicDir`, `stateDir` and `cacheDir` move one folder each.
None may be under `/home`, `/root`, `/run/user`, `/tmp` or `/var/tmp`,
which the units' sandbox hides.

[deploy.md](deploy.md) covers the rest: agenix, Syncthing, restic backups,
Spotify, and how auto-chords works.

## Ubuntu

Checked on Ubuntu 24.04 and 26.04.

### Ubuntu with Nix

The recommended route: the packages bring ChordPro 6.050.7, the font and the
model files, pinned and tested together.

Install Nix with the official installer, in multi-user mode, then turn on
flakes:

```sh
sudo apt install curl xz-utils
sh <(curl --proto '=https' --tlsv1.2 -L https://nixos.org/nix/install) --daemon
echo 'experimental-features = nix-command flakes' | sudo tee -a /etc/nix/nix.conf
sudo systemctl restart nix-daemon
```

Install caracole into a profile of its own, which gives the units a fixed
path. Nix builds it and runs its tests, which takes a few minutes:

```sh
sudo -i nix profile add --profile /nix/var/nix/profiles/caracole github:Danielhp95/caracole
/nix/var/nix/profiles/caracole/bin/caracole --help
```

For auto-chords, add the `autochords` package to a second profile. With
torch, it takes about 3 GB in the store:

```sh
sudo -i nix profile add --profile /nix/var/nix/profiles/caracole-autochords 'github:Danielhp95/caracole#autochords'
```

`sudo -i` because Ubuntu's `sudo` resets PATH, and Nix isn't on the reset one.
Before Nix 2.30, `nix profile add` was `nix profile install`. To update:

```sh
sudo -i nix profile upgrade --profile /nix/var/nix/profiles/caracole --all
```

Then [run it nightly](#run-it-nightly-on-ubuntu).

### Ubuntu without Nix

**caracole.** It needs Python 3.12 or newer: Ubuntu 24.04 has 3.12, 26.04
has 3.14. Give it a virtual environment of its own:

```sh
sudo apt install python3-venv git curl
sudo python3 -m venv /opt/caracole
sudo /opt/caracole/bin/pip install "git+https://github.com/Danielhp95/caracole@caracole-v1"
/opt/caracole/bin/caracole --help
```

caracole's version stays 0.1.0 from one commit to the next, so `pip install
--upgrade` keeps the one you have. To update, reinstall it, without touching
its dependencies (torch among them):

```sh
sudo /opt/caracole/bin/pip install --force-reinstall --no-deps "git+https://github.com/Danielhp95/caracole@caracole-v1"
sudo /opt/caracole/bin/pip check   # names any dependency a new caracole needs
```

If you only run caracole by hand, as yourself, `sudo apt install pipx` and
`pipx install git+https://github.com/Danielhp95/caracole@caracole-v1` work
too, and `pipx reinstall caracole` updates it.

**ChordPro 6.050.7.** caracole makes no PDF with any later release, from
6.060 to 6.101.0: they read the `--define` values caracole passes, which
start with `%{`, as JSON, and stop. Ubuntu 24.04 has no `chordpro` package,
and 26.04's is 6.090.1, so install 6.050.7 from CPAN. apt has most of the
Perl libraries it needs, and cpanm builds and tests the rest in a few
minutes:

```sh
sudo apt install cpanminus build-essential libdata-printer-perl libfile-homedir-perl \
  libfile-loadlines-perl libimage-info-perl libobject-pad-perl libpdf-api2-perl \
  libstring-interpolate-named-perl libtext-layout-perl
sudo cpanm --from https://cpan.metacpan.org \
  https://cpan.metacpan.org/authors/id/J/JV/JV/App-Music-ChordPro-6.050.7.tar.gz
chordpro --version   # This is ChordPro core 6.050.7
```

It lands in `/usr/local/bin`, which is on the units' PATH. Anywhere else,
set `chordpro_bin` in caracole.toml.

**The font for Chinese sheets** is `FusionKaiJ-Regular.ttf` from LXGW
FusionKai 24.134, the file the Nix package uses:

```sh
sudo install -d /usr/local/share/caracole
sudo curl -fLo /usr/local/share/caracole/FusionKaiJ-Regular.ttf \
  https://raw.githubusercontent.com/lxgw/FusionKai/v24.134/FusionKaiJ-Regular.ttf
echo 'fd4eb05a8ae1480957bfe0372728bfde1171015c74b1ac349c889ae740751018  /usr/local/share/caracole/FusionKaiJ-Regular.ttf' | sha256sum -c
```

caracole reads its path from `CARACOLE_CJK_FONT`, or from `cjk_font` in
caracole.toml, which wins. The service's config below sets `cjk_font`.
Without the font, a Chinese sheet gets no PDF, and the to-do page says so.
[usage.md](usage.md#fonts-for-chinese-sheets) says which other fonts work.

**Auto-chords**, if you want it. Install torch first, from PyTorch's CPU-only
index, because the PyPI build brings several GB of CUDA libraries. Then
install the `autochords` extra. torchcodec and FFmpeg decode iTunes Store
`.m4a` files. WAV, FLAC, Ogg and MP3 need neither. The venv grows to about
1.5 GB.

```sh
sudo apt install ffmpeg
sudo /opt/caracole/bin/pip install torch torchaudio torchcodec --index-url https://download.pytorch.org/whl/cpu
sudo /opt/caracole/bin/pip install "caracole[autochords] @ git+https://github.com/Danielhp95/caracole@caracole-v1"
```

Then download the two model files that `nix/autochords.nix` pins: BTC's
large-vocabulary chord weights and beat_this's `final0` checkpoint, both MIT.

```sh
cd /usr/local/share/caracole
sudo curl -fLO https://raw.githubusercontent.com/jayg996/BTC-ISMIR19/2682317be668032e6e4b269ded36adaa2ad57df0/test/btc_model_large_voca.pt
sudo curl -fLO https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/final0.ckpt
sha256sum -c <<'EOF'
1673d23f8f9a55ae7f9e8b80a51da616debb22675b8d8b67ea6ce0ef37b0ab51  btc_model_large_voca.pt
8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331  final0.ckpt
EOF
```

caracole reads their paths from `CARACOLE_BTC_WEIGHTS` and
`CARACOLE_BEAT_CHECKPOINT`, or from `btc_weights` and `beat_checkpoint`
under `[autochords]` in caracole.toml, which win.

Then [run it nightly](#run-it-nightly-on-ubuntu).

### Run it nightly on Ubuntu

These files mirror the NixOS module: the same schedule, user, folders,
hardening and credentials. One part isn't here: the module's ntfy message
when a unit fails. caracole's own messages, a summary after each run and
alerts for blocks, still come once `[ntfy]` has a `url`.

**A user and the folders:**

```sh
sudo useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin caracole
sudo install -d -o caracole -g caracole -m 0710 /var/lib/caracole
sudo install -d -o caracole -g caracole -m 2775 /var/lib/caracole/library /var/lib/caracole/music
sudo install -d -o caracole -g caracole -m 0700 /var/lib/caracole/state /var/lib/caracole/cache
sudo install -d /etc/caracole
sudo usermod -aG caracole "$USER"   # to edit wanted.txt and read the library; log in again
```

**The config**, `/etc/caracole/caracole.toml`. Other settings are in
[usage.md](usage.md#configure).

```toml
# /etc/caracole/caracole.toml
data_dir = "/var/lib/caracole"

# Without Nix: the font and, for auto-chords, the model files.
# cjk_font = "/usr/local/share/caracole/FusionKaiJ-Regular.ttf"
#
# [autochords]
# btc_weights = "/usr/local/share/caracole/btc_model_large_voca.pt"
# beat_checkpoint = "/usr/local/share/caracole/final0.ckpt"
```

**Secrets** go in `/etc/credstore`, which only root can read. The units
load them with `LoadCredential=`, and systemd skips any whose file is
missing:

```sh
sudo install -d -m 0700 /etc/credstore
sudo sh -c 'umask 077; cat > /etc/credstore/ntfy_token'              # paste it, then Ctrl-D
sudo sh -c 'umask 077; cat > /etc/credstore/spotify_client_secret'   # only with Spotify
```

**The units.** The nightly run:

```ini
# /etc/systemd/system/caracole.service
[Unit]
Description=caracole nightly run: sync, match, fetch and write the library
Wants=network-online.target
After=network-online.target
RequiresMountsFor=/var/lib/caracole/library /var/lib/caracole/state /var/lib/caracole/cache
# With auto-chords:
#OnSuccess=caracole-autochords.service

[Service]
Type=oneshot
ExecStart=/nix/var/nix/profiles/caracole/bin/caracole --config /etc/caracole/caracole.toml run
TimeoutStartSec=3h
User=caracole
Group=caracole
UMask=0007
Environment=XDG_CACHE_HOME=/var/lib/caracole/cache NUMBA_CACHE_DIR=/var/lib/caracole/cache/numba
LoadCredential=spotify_client_secret
LoadCredential=ntfy_token
ReadWritePaths=/var/lib/caracole/library /var/lib/caracole/state /var/lib/caracole/cache
ReadOnlyPaths=-/var/lib/caracole/music
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
PrivateMounts=yes
ProtectProc=invisible
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
MemoryDenyWriteExecute=yes
LockPersonality=yes
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallFilter=~@privileged
SystemCallErrorNumber=EPERM
CapabilityBoundingSet=
```

Its timer:

```ini
# /etc/systemd/system/caracole.timer
[Unit]
Description=Nightly caracole run

[Timer]
OnCalendar=*-*-* 03:30
RandomizedDelaySec=45m
Persistent=true

[Install]
WantedBy=timers.target
```

With auto-chords, this unit too, and uncomment `OnSuccess=` in
`caracole.service`. It runs after each successful run, as the same user,
with no network and no credentials. `MemoryDenyWriteExecute` is off here
because PyTorch and numba generate code at run time.

```ini
# /etc/systemd/system/caracole-autochords.service
[Unit]
Description=caracole auto-chords: chord sheets from purchased audio, offline
After=caracole.service
RequiresMountsFor=/var/lib/caracole/library /var/lib/caracole/state /var/lib/caracole/cache

[Service]
Type=oneshot
ExecStart=/nix/var/nix/profiles/caracole-autochords/bin/caracole --config /etc/caracole/caracole.toml autochords
TimeoutStartSec=6h
CPUSchedulingPolicy=batch
IOSchedulingClass=idle
User=caracole
Group=caracole
UMask=0007
Environment=XDG_CACHE_HOME=/var/lib/caracole/cache NUMBA_CACHE_DIR=/var/lib/caracole/cache/numba
ReadWritePaths=/var/lib/caracole/library /var/lib/caracole/state /var/lib/caracole/cache
ReadOnlyPaths=-/var/lib/caracole/music
PrivateNetwork=yes
MemoryDenyWriteExecute=no
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
PrivateMounts=yes
ProtectProc=invisible
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallFilter=~@privileged
SystemCallErrorNumber=EPERM
CapabilityBoundingSet=
```

**`caracole-admin`** runs one command as the units do: as user `caracole`,
with the config, the credentials and the cache. With auto-chords from Nix,
point it at the `caracole-autochords` profile instead, so that
`caracole-admin autochords` works too.

```sh
#!/bin/sh
# /usr/local/bin/caracole-admin: run a caracole command as caracole.service does.
exec systemd-run --quiet --collect --wait --pty --pipe \
  --uid=caracole --gid=caracole --property=UMask=0007 \
  --property=LoadCredential=spotify_client_secret --property=LoadCredential=ntfy_token \
  --setenv=CARACOLE_CONFIG=/etc/caracole/caracole.toml \
  --setenv=XDG_CACHE_HOME=/var/lib/caracole/cache \
  --setenv=NUMBA_CACHE_DIR=/var/lib/caracole/cache/numba \
  /nix/var/nix/profiles/caracole/bin/caracole "$@"
```

Make it executable with `sudo chmod 0755 /usr/local/bin/caracole-admin`.
Without Nix, point both units and `caracole-admin` at the venv:

```sh
sudo sed -i 's|/nix/var/nix/profiles/caracole\(-autochords\)\?/bin/caracole|/opt/caracole/bin/caracole|' \
  /etc/systemd/system/caracole*.service /usr/local/bin/caracole-admin
```

Then start the timer:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now caracole.timer
```

The first commands are the same as [on NixOS](#nixos), from
`sudo caracole-admin index build` on. `systemd-analyze security` scores
`caracole.service` 1.4 and `caracole-autochords.service` 1.0, as on NixOS.

To keep the data elsewhere, say `/data/caracole`, create the folders there,
set `data_dir`, and change the units and `caracole-admin`:

```sh
sudo sed -i 's|/var/lib/caracole|/data/caracole|g' \
  /etc/systemd/system/caracole*.service /usr/local/bin/caracole-admin
```

## From source

```sh
git clone https://github.com/Danielhp95/caracole
cd caracole
```

With Nix:

```sh
nix develop                                         # Python, the dependencies, pytest, chordpro, ruff, sqlite3
pytest -q
pytest -q -m "not slow"                             # all but the browser, chordpro and second-process tests
nix develop .#autochords -c pytest -m autochords    # the model tests, with the model files
```

Both shells set `CARACOLE_CJK_FONT`, and `.#autochords` also sets
`CARACOLE_BTC_WEIGHTS` and `CARACOLE_BEAT_CHECKPOINT`.

Without Nix, install ChordPro and the font as [above](#ubuntu-without-nix)
first, and torch too if you want the auto-chords tests:

```sh
python3 -m venv .venv
.venv/bin/pip install -e . pytest                   # -e '.[autochords]' for auto-chords
CARACOLE_CJK_FONT=/usr/local/share/caracole/FusionKaiJ-Regular.ttf .venv/bin/pytest -q
.venv/bin/caracole --help
```

Run the tests as yourself, not as root, because the permission tests skip
under root. Tests that need a program or a file skip without it:

| Without | These tests skip |
|---|---|
| `chordpro` on PATH | the real PDFs (marked `chordpro`): in test_render.py and test_render_all.py, two in test_chordpro.py |
| `CARACOLE_CJK_FONT` | the two Chinese PDFs |
| torch, librosa and beat_this, or `CARACOLE_BTC_WEIGHTS` and `CARACOLE_BEAT_CHECKPOINT` | the model tests (marked `autochords`) |
| `ffmpeg`, `chromium` | one `.m4a` test, two `index.html` tests in a browser |

[AGENTS.md](../AGENTS.md#development) lists every such test and variable.
