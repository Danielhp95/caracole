# Deploying caracole

caracole runs on a server as a nightly service, with its library page on your
network. Two ways to set it up:

- **[NixOS](#nixos)**: the flake's module, `nixosModules.default`.
- **[Ubuntu 24.04 without Nix](#ubuntu-2404-without-nix)**: apt, a few
  downloads checked against their SHA-256, and systemd units that do what the
  module does.

[The first run](#the-first-run), [Logs](#logs) and [When something is
wrong](#when-something-is-wrong) are the same for both. Either way the machine
gets:

| What | Does |
|---|---|
| `caracole.timer` | Starts the nightly run at 03:30, up to 45 minutes late; a run missed while the machine was off starts at the next boot |
| `caracole.service` | `caracole run`, a hardened oneshot as user `caracole` |
| `caracole-web.service` | `caracole serve`: the library page, its search and song requests |
| `caracole-autochords.service` | Optional. After each successful run, chord sheets from audio, with no network |
| `caracole-notify-failure` | Posts to your ntfy topic when one of the units fails |
| `caracole-admin` | Runs any `caracole` command as the units do: `sudo caracole-admin index build` |

And a data folder, `/var/lib/caracole` unless you choose another, never under
`/home`, `/root`, `/run/user`, `/tmp` or `/var/tmp`, which the units' sandbox
hides:

| Folder | Holds |
|---|---|
| `library` | sheets, lyrics, guitar parts, `_todo.md`, `index.html`, `wanted.txt`, `overrides.toml`, `songbooks.toml`, `_inbox/`: synced to your devices |
| `music` | audio you bought, read-only, for auto-chords |
| `state` | the database and caracole's lock, `caracole`'s alone: back it up, never sync it |
| `cache` | every raw HTTP response, kept forever: losing it costs only requests |

caracole keeps no secret: no credential, no token, no sign-in. ntfy is a
topic's URL alone, which anyone who knows it can read: make it long and random.
The library page has no sign-in either: whoever reaches it can read the library
and request songs, so it listens only on a network you trust, your LAN or your
tailnet, never the internet.

## NixOS

### 1. The flake and the module

In your system flake's `flake.nix`:

```nix
    # The chord sheet library; its nixosModules.default runs it nightly.
    caracole.url = "github:Danielhp95/caracole";
    caracole.inputs.nixpkgs.follows = "nixpkgs";
```

A new commit on caracole's default branch, `caracole-v1`, reaches the host
after `nix flake update caracole` and a switch. Then, in the host's
configuration (with `inputs` in `specialArgs`):

```nix
# hosts/nuc/caracole.nix: caracole, and (sections 2 and 3) Syncthing and restic.
{ config, inputs, lib, pkgs, ... }:
let
  caracole = config.services.caracole;
in
{
  imports = [ inputs.caracole.nixosModules.default ];

  services.caracole = {
    enable = true;
    # caracole.toml (docs/usage.md, "Configure"), less the folders, which are options.
    settings.ntfy.url = "https://ntfy.sh/caracole-change-me"; # a long random topic
    web = {
      enable = true;
      address = "100.64.0.7"; # the tailnet address (tailscale ip -4), or the LAN's: section 5
      allowedHosts = [ "nuc.example-tailnet.ts.net" ];
    };
  };
}
```

Every option of `nix/module.nix`:

| Option | Default | What |
|---|---|---|
| `dataDir` | `"/var/lib/caracole"` | the data folder, created `caracole:caracole` 0710 when missing |
| `libraryDir`, `musicDir`, `stateDir`, `cacheDir` | in `dataDir` | one folder each, elsewhere; none inside another |
| `schedule` | `"*-*-* 03:30"` | when the run starts (systemd.time(7)), up to 45 minutes late |
| `settings` | `{ }` | caracole.toml; unknown keys are fatal, and the folder keys come from the options |
| `web.enable` | `false` | caracole-web |
| `web.address`, `web.port` | `"127.0.0.1"`, `8737` | where it listens (a port of 1024 or above) |
| `web.allowedHosts` | `[ ]` | names it answers to beyond localhost, the host's name and its `.local` name |
| `web.openFirewall` | `false` | opens `web.port` on every interface, for a LAN address |
| `autochords.enable` | `false` | auto-chords (section 4) |
| `autochords.btcWeights`, `autochords.beatCheckpoint` | `null` | model files other than the package's |
| `package`, `autochords.package` | the flake's builds | |

A configuration that still sets `services.caracole.credentials`, an older
caracole's, fails to evaluate: delete it.

### 2. Syncthing for the library and the music

The library is `caracole:caracole`, mode 2775, setgid, and caracole writes with
umask 0007; Syncthing, in group `caracole` with the same umask, writes there
too. Add to `hosts/nuc/caracole.nix`:

```nix
  services.syncthing = {
    enable = true;
    # The GUI stays on localhost: ssh -L 8384:localhost:8384 nuc
    settings = {
      devices.laptop.id = "…"; # syncthing --device-id, on the laptop
      devices.phone.id = "…";
      # ignorePerms: a new file gets 0666 minus Syncthing's umask, not the
      # sender's 0644, which would take the group's write bit from caracole.
      folders.tabs = { path = caracole.libraryDir; devices = [ "laptop" "phone" ]; ignorePerms = true; };
      folders.music = { path = caracole.musicDir; devices = [ "laptop" ]; ignorePerms = true; };
    };
  };
  users.users.syncthing.extraGroups = [ "caracole" ];
  systemd.services.syncthing.serviceConfig.UMask = "0007";
  # Syncthing fills the music folder; caracole reads it through the group.
  systemd.tmpfiles.settings.caracole-music.${caracole.musicDir}.d = {
    user = "syncthing";
    group = "caracole";
    mode = "2770";
  };
```

After the first switch, `sudo systemctl restart syncthing`, so that it runs in
its new group.

### 3. Backups with restic

The state, the library and the music; the live database through a consistent
copy, made with SQLite's online backup:

```nix
  services.restic.backups.caracole = {
    initialize = true;
    repository = "/mnt/backup/restic/caracole"; # or sftp:host:/path, s3:…
    passwordFile = "/etc/restic/caracole-password";
    paths = [ caracole.stateDir caracole.libraryDir caracole.musicDir ];
    exclude = [ "${caracole.stateDir}/caracole.sqlite*" ];
    backupPrepareCommand = ''
      if [ -f ${caracole.stateDir}/caracole.sqlite ]; then
        ${lib.getExe' pkgs.sqlite "sqlite3"} ${caracole.stateDir}/caracole.sqlite \
          ".backup ${caracole.stateDir}/caracole-backup.sqlite"
      fi
    '';
    timerConfig = { OnCalendar = "*-*-* 05:30"; Persistent = true; RandomizedDelaySec = "30m"; };
    pruneOpts = [ "--keep-daily 7" "--keep-weekly 5" "--keep-monthly 12" ];
  };
```

The password is restic's own. Make it once, and keep a copy elsewhere:

```sh
sudo install -d -m 0700 /etc/restic
sudo sh -c 'umask 077; openssl rand -base64 32 > /etc/restic/caracole-password'
```

To restore, stop caracole, restore, and put the copy back as the database:

```sh
sudo systemctl stop caracole.timer caracole-web.service
sudo restic-caracole restore latest --target /
cd /var/lib/caracole/state
sudo rm -f caracole.sqlite-wal caracole.sqlite-shm
sudo install -o caracole -g caracole -m 0600 caracole-backup.sqlite caracole.sqlite
sudo systemctl start caracole.timer caracole-web.service
```

### 4. Auto-chords

For a song nobody has charted, a local model writes `sheet (auto).txt` from its
audio: a track you bought, dropped into the music folder, or audio the nightly
run takes from YouTube.

```nix
  services.caracole.autochords.enable = true;
```

`caracole-autochords.service` then runs after each run that succeeds, with no
network. The nightly run, caracole-web and `caracole-admin` run the
`autochords` package, which has torch, the model files and yt-dlp, and the run
takes the audio of up to three songs a night that have no human sheet from
YouTube: against YouTube's robots.txt and terms, the owner's choice, on the
terms [usage.md](usage.md#audio-from-youtube) gives. For purchases alone:

```nix
  services.caracole.settings.providers.youtube.enabled = false;
```

To run it now: `sudo systemctl start caracole-autochords.service`.

### 5. The library page on your network

`web.address` decides who reaches it:

- `127.0.0.1`, the default: this machine alone. From the laptop,
  `ssh -L 8737:127.0.0.1:8737 nuc`, then `http://127.0.0.1:8737/`.
- The tailnet address: the tailnet. A tailnet whose interface is in
  `networking.firewall.trustedInterfaces` needs no opening.
- The LAN address, with `web.openFirewall = true`: the LAN, everyone on it.

It answers to its IP addresses and the names it knows: a full tailnet name goes
in `allowedHosts`, or the browser gets 421. A tailnet address that doesn't
exist yet at boot is tried again every 10 seconds.
[usage.md](usage.md#caracole-serve) says what the page does.

## Ubuntu 24.04 without Nix

The same service, with no Nix: what the Nix package brings goes under
`/opt/caracole`, and the units are the module's. Run the blocks in order, in
one shell, as a user with sudo: later blocks use `$PY` and `$REV`. Each
download is checked against its SHA-256: stop at a `FAILED`.

### 1. Packages from apt

```sh
sudo apt update
sudo apt install git curl xz-utils sqlite3 build-essential cpanminus \
  libpdf-api2-perl libfont-ttf-perl libobject-pad-perl libdata-printer-perl \
  libfile-loadlines-perl libimage-info-perl libstring-interpolate-named-perl \
  libfile-homedir-perl libio-string-perl libfile-which-perl libfile-slurper-perl \
  libextutils-makemaker-cpanfile-perl libtest-deep-perl libtypes-serialiser-perl \
  libtest-fatal-perl libtest-failwarnings-perl
```

### 2. Python and caracole

uv installs CPython 3.14.7, which caracole is tested on, where the units can
read it:

```sh
cd "$(mktemp -d)"
curl -fsSLO https://github.com/astral-sh/uv/releases/download/0.13.0/uv-x86_64-unknown-linux-gnu.tar.gz
echo '1468ebd5a5541121837c5a2817b9972ba6090fa6caa3d142620850a47fb75154  uv-x86_64-unknown-linux-gnu.tar.gz' | sha256sum -c
tar -xzf uv-x86_64-unknown-linux-gnu.tar.gz
sudo install -m 0755 uv-x86_64-unknown-linux-gnu/uv /usr/local/bin/uv
sudo install -d /opt/caracole/bin /opt/caracole/releases
sudo uv python install --install-dir /opt/caracole/python --no-bin 3.14.7
PY=/opt/caracole/python/cpython-3.14.7-linux-x86_64-gnu/bin/python3.14
```

caracole's dependencies come from PyPI, held to the Nix package's versions,
which the tests pass with (PyPI's latest tomlkit breaks renaming a songbook):

```sh
sudo tee /opt/caracole/constraints.txt > /dev/null <<'EOF'
# The Nix package's versions: nixpkgs, as caracole's flake.lock pins it.
httpx==0.28.1
selectolax==1.0.0
rapidfuzz==3.14.5
typer==0.25.1
click==8.3.3
mutagen==1.48.1
tomlkit==0.15.0
pypinyin==0.55.0
# Auto-chords' (section 12).
torch==2.13.0
torchaudio==2.11.0
torchcodec==0.17.0
beat-this==1.1.0
librosa==1.0.0
numba==0.67.0
numpy==2.5.2
scipy==1.18.1
soundfile==0.13.1
pyyaml==6.0.3
EOF
```

Then caracole, at the head of `caracole-v1`, in a virtual environment of that
commit:

```sh
REV=$(git ls-remote https://github.com/Danielhp95/caracole refs/heads/caracole-v1 | cut -f1)
sudo uv venv --python $PY /opt/caracole/releases/$REV
sudo uv pip install --python /opt/caracole/releases/$REV/bin/python \
  -c /opt/caracole/constraints.txt "caracole @ git+https://github.com/Danielhp95/caracole@$REV"
sudo ln -sfn releases/$REV /opt/caracole/current
```

### 3. ChordPro 6.050.7

caracole makes no PDF with a later ChordPro, and Ubuntu has none. cpanm builds
it into `/opt/caracole/perl`, with JavaScript::QuickJS, which apt hasn't got,
and Text::Layout 0.037, newer than apt's; the rest is apt's:

```sh
cd "$(mktemp -d)"
curl -fsSLO https://cpan.metacpan.org/authors/id/F/FE/FELIPE/JavaScript-QuickJS-0.21.tar.gz
curl -fsSLO https://cpan.metacpan.org/authors/id/J/JV/JV/Text-Layout-0.037.tar.gz
curl -fsSLO https://cpan.metacpan.org/authors/id/J/JV/JV/App-Music-ChordPro-6.050.7.tar.gz
sha256sum -c <<'EOF'
1cfdf3fb952ff4865ff2d55a203d58cbe5d8cb41571a35890b834f1eb5442a84  JavaScript-QuickJS-0.21.tar.gz
58279341247c48187404876400f06ad7daa6fe71629558185df3673df09b9cea  Text-Layout-0.037.tar.gz
b6936caa1a1638f230a6b2b7a2ee6d6fda172a28771c44239bfd9ce45f6b3a84  App-Music-ChordPro-6.050.7.tar.gz
EOF
sudo cpanm -l /opt/caracole/perl \
  ./JavaScript-QuickJS-0.21.tar.gz ./Text-Layout-0.037.tar.gz ./App-Music-ChordPro-6.050.7.tar.gz
```

### 4. The fonts and alphaTab

The PDFs' fonts, Adwaita Sans and Mono, made by caracole's `nix/pdf-fonts.py`
as the Nix package makes them; LXGW FusionKai for Chinese words; alphaTab, for
Guitar Pro files in the browser:

```sh
cd "$(mktemp -d)"
curl -fsSLO https://raw.githubusercontent.com/lxgw/FusionKai/v24.134/FusionKaiJ-Regular.ttf
curl -fsSLO https://download.gnome.org/sources/adwaita-fonts/50/adwaita-fonts-50.0.tar.xz
curl -fsSLO https://registry.npmjs.org/@coderline/alphatab/-/alphatab-1.8.4.tgz
curl -fsSLO https://raw.githubusercontent.com/Danielhp95/caracole/$REV/nix/pdf-fonts.py
sha256sum -c <<'EOF'
fd4eb05a8ae1480957bfe0372728bfde1171015c74b1ac349c889ae740751018  FusionKaiJ-Regular.ttf
4c927fbfeec1c503801ba510c2c94e0054c82c522cf7ba0d3be5d4d41fcf5c86  adwaita-fonts-50.0.tar.xz
70b2c77abc9698a055d90a11d77308b6b41247936476e969d85770e3d4db4602  alphatab-1.8.4.tgz
EOF
tar -xJf adwaita-fonts-50.0.tar.xz && tar -xzf alphatab-1.8.4.tgz
uv venv --python $PY fonttools && uv pip install --python fonttools/bin/python fonttools==4.63.0
fonttools/bin/python -I pdf-fonts.py adwaita-fonts-50.0/sans pdf-fonts
sha256sum -c <<'EOF'
aaacd46260916dfa4a15954c61f253b58e2b86d24a0e63de120103b5d9091561  pdf-fonts/regular.ttf
e4360458b36345158029a81888b765344b73a1767ce63c3ad4d777bb2f069a9f  pdf-fonts/bold.ttf
afc8acbb3d1f066abfaee99c130ac92df9aa21cb5e5f129f7a86c6f21cb0d9c9  pdf-fonts/italic.ttf
EOF
sudo install -d /opt/caracole/fonts /opt/caracole/pdf-fonts /opt/caracole/alphatab
sudo install -m 0644 FusionKaiJ-Regular.ttf /opt/caracole/fonts/
sudo install -m 0644 pdf-fonts/regular.ttf pdf-fonts/bold.ttf pdf-fonts/italic.ttf /opt/caracole/pdf-fonts/
sudo install -m 0644 adwaita-fonts-50.0/mono/AdwaitaMono-Regular.ttf /opt/caracole/pdf-fonts/mono.ttf
sudo install -m 0644 package/dist/alphaTab.min.js package/dist/font/Bravura.woff2 \
  package/dist/soundfont/sonivox.sf3 /opt/caracole/alphatab/
```

### 5. The wrapper

As the Nix package's wrapper: ChordPro on PATH, and the fonts', alphaTab's and
the model files' paths as defaults, which a variable already set overrides:

```sh
sudo tee /opt/caracole/bin/caracole > /dev/null <<'EOF'
#!/bin/sh
# caracole as the Nix package's wrapper runs it.
PATH=/opt/caracole/bin:/opt/caracole/perl/bin:$PATH
PERL5LIB=/opt/caracole/perl/lib/perl5${PERL5LIB:+:$PERL5LIB}
: "${CARACOLE_CJK_FONT=/opt/caracole/fonts/FusionKaiJ-Regular.ttf}"
: "${CARACOLE_PDF_FONTS=/opt/caracole/pdf-fonts}"
: "${CARACOLE_ALPHATAB_DIR=/opt/caracole/alphatab}"
: "${CARACOLE_BTC_WEIGHTS=/opt/caracole/models/btc_model_large_voca.pt}"
: "${CARACOLE_BEAT_CHECKPOINT=/opt/caracole/models/final0.ckpt}"
export PATH PERL5LIB CARACOLE_CJK_FONT CARACOLE_PDF_FONTS CARACOLE_ALPHATAB_DIR \
  CARACOLE_BTC_WEIGHTS CARACOLE_BEAT_CHECKPOINT
exec /opt/caracole/current/bin/caracole "$@"
EOF
sudo chmod 0755 /opt/caracole/bin/caracole
/opt/caracole/bin/caracole --version   # caracole 0.1.0
```

### 6. The user, the folders and the config

The folders as the NixOS module makes them, and caracole.toml (put your own
ntfy topic in it, or leave `[ntfy]` out):

```sh
sudo useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin caracole
sudo tee /etc/tmpfiles.d/caracole.conf > /dev/null <<'EOF'
d /var/lib/caracole          :0710 :caracole :caracole -
d /var/lib/caracole/library   2775 caracole caracole -
d /var/lib/caracole/state     0700 caracole caracole -
d /var/lib/caracole/cache     0700 caracole caracole -
EOF
sudo systemd-tmpfiles --create /etc/tmpfiles.d/caracole.conf
sudo install -d /etc/caracole
sudo tee /etc/caracole/caracole.toml > /dev/null <<'EOF'
# As docs/usage.md's "Configure" says. No secret goes here.
data_dir = "/var/lib/caracole"

[ntfy]
url = "https://ntfy.sh/caracole-change-me"   # a long random topic
EOF
```

To keep the data elsewhere, put its path in place of `/var/lib/caracole` in
every file of this part.

### 7. The units

The module's user, folders and sandbox are one file, which each caracole unit
takes as a drop-in, and `caracole-admin` reads too:

```sh
sudo tee /etc/caracole/units.conf > /dev/null <<'EOF'
# The user, the folders, the config and the sandbox of every caracole unit.
[Unit]
RequiresMountsFor=/var/lib/caracole/library /var/lib/caracole/state /var/lib/caracole/cache

[Service]
User=caracole
Group=caracole
UMask=0007
Environment=CARACOLE_CONFIG=/etc/caracole/caracole.toml
Environment=XDG_CACHE_HOME=/var/lib/caracole/cache NUMBA_CACHE_DIR=/var/lib/caracole/cache/numba
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
LockPersonality=yes
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallFilter=~@privileged
SystemCallErrorNumber=EPERM
CapabilityBoundingSet=
EOF
```

The nightly run, its timer, and the library page (on this machine alone until
section 11):

```sh
sudo tee /etc/systemd/system/caracole.service > /dev/null <<'EOF'
[Unit]
Description=caracole nightly run: sync, match, fetch and write the library
Wants=network-online.target
After=network-online.target
OnFailure=caracole-notify-failure@%n.service
#OnSuccess=caracole-autochords.service

[Service]
Type=oneshot
ExecStart=/opt/caracole/bin/caracole run
TimeoutStartSec=3h
MemoryDenyWriteExecute=yes
EOF
sudo tee /etc/systemd/system/caracole.timer > /dev/null <<'EOF'
[Unit]
Description=Nightly caracole run

[Timer]
OnCalendar=*-*-* 03:30
Persistent=true
RandomizedDelaySec=45m

[Install]
WantedBy=timers.target
EOF
sudo tee /etc/systemd/system/caracole-web.service > /dev/null <<'EOF'
[Unit]
Description=caracole web: the library page and song requests
Wants=network-online.target
After=network-online.target
OnFailure=caracole-notify-failure@%n.service
StartLimitIntervalSec=600
StartLimitBurst=30

[Service]
Type=exec
ExecStart=/opt/caracole/bin/caracole serve --address 127.0.0.1 --port 8737
Restart=on-failure
RestartSec=10s
RestartMode=direct
MemoryDenyWriteExecute=yes

[Install]
WantedBy=multi-user.target
EOF
```

The failure alert, to the ntfy topic of caracole.toml, whose URL goes on its
last line (for none, leave out this unit and the `OnFailure=` lines):

```sh
sudo tee /etc/systemd/system/caracole-notify-failure@.service > /dev/null <<'EOF'
[Unit]
Description=Tell ntfy that %i failed
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
DynamicUser=yes
ExecStart=/usr/bin/curl --silent --show-error --fail-with-body --max-time 30 --retry 3 \
  --header "Title: caracole: %i failed" --header "Priority: high" --header "Tags: warning" \
  --data-binary "%i failed on %H (${MONITOR_SERVICE_RESULT}). See: journalctl -u %i" \
  https://ntfy.sh/caracole-change-me
EOF
```

Then the shared file for both caracole units, a check, and the start:

```sh
for unit in caracole caracole-web; do
  sudo mkdir -p /etc/systemd/system/$unit.service.d
  sudo ln -sfn /etc/caracole/units.conf /etc/systemd/system/$unit.service.d/caracole.conf
done
sudo systemd-analyze verify caracole.service caracole.timer caracole-web.service \
  caracole-notify-failure@caracole.service.service   # silent when all is well
sudo systemctl daemon-reload
sudo systemctl enable --now caracole.timer caracole-web.service
```

### 8. caracole-admin

A command run as the units run it: a transient unit with their settings, and
the network.

```sh
sudo tee /usr/local/sbin/caracole-admin > /dev/null <<'EOF'
#!/bin/bash
# Runs a caracole command as the caracole units do.
if [ "$EUID" -ne 0 ]; then
  echo "caracole-admin starts a system unit as the caracole user: run it with sudo" >&2
  exit 1
fi
# Each setting of units.conf, as a --property; with auto-chords, MemoryDenyWriteExecute=no.
mapfile -t properties < <(sed -n 's/^[A-Z]/--property=&/p' /etc/caracole/units.conf)
# --pty on a terminal (review and remove ask questions), --pipe otherwise.
exec systemd-run --quiet --collect --wait --pty --pipe "${properties[@]}" \
  --property=MemoryDenyWriteExecute=yes -- /opt/caracole/bin/caracole "$@"
EOF
sudo chmod 0755 /usr/local/sbin/caracole-admin
sudo caracole-admin --version   # caracole 0.1.0
```

### 9. Syncthing

As on NixOS (section 2): Syncthing as its own user, in group `caracole`, with
umask 0007, and the music folder its own.

```sh
sudo apt install syncthing
sudo useradd --system --user-group --create-home --home-dir /var/lib/syncthing \
  --shell /usr/sbin/nologin syncthing
sudo usermod -aG caracole syncthing
echo 'd /var/lib/caracole/music 2770 syncthing caracole -' | sudo tee /etc/tmpfiles.d/caracole-music.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/caracole-music.conf
sudo mkdir -p /etc/systemd/system/syncthing@syncthing.service.d
printf '[Service]\nUMask=0007\n' | sudo tee /etc/systemd/system/syncthing@syncthing.service.d/caracole.conf
sudo systemctl daemon-reload
sudo systemctl enable --now syncthing@syncthing.service
```

Its GUI listens on the machine alone: `ssh -L 8384:localhost:8384 server`, then
`http://localhost:8384`. Add your devices, and two folders, `tabs` at
`/var/lib/caracole/library` and `music` at `/var/lib/caracole/music`, each with
Ignore Permissions ticked under Advanced. With ufw on, `sudo ufw allow syncthing`.

### 10. Backups with restic

The NixOS backup (section 3), as a unit and a timer. Put your repository in
place of `/mnt/backup/restic/caracole`:

```sh
sudo apt install restic
sudo install -d -m 0700 /etc/restic
sudo sh -c 'umask 077; openssl rand -base64 32 > /etc/restic/caracole-password'   # keep a copy elsewhere
sudo restic -r /mnt/backup/restic/caracole -p /etc/restic/caracole-password init
sudo tee /etc/systemd/system/caracole-backup.service > /dev/null <<'EOF'
[Unit]
Description=Back up caracole's state, library and music with restic

[Service]
Type=oneshot
ExecStartPre=/bin/sh -c 'cd /var/lib/caracole/state && if [ -f caracole.sqlite ]; then sqlite3 caracole.sqlite ".backup caracole-backup.sqlite"; fi'
ExecStart=/usr/bin/restic -r /mnt/backup/restic/caracole -p /etc/restic/caracole-password \
  backup --exclude=/var/lib/caracole/state/caracole.sqlite* \
  /var/lib/caracole/state /var/lib/caracole/library /var/lib/caracole/music
ExecStartPost=/usr/bin/restic -r /mnt/backup/restic/caracole -p /etc/restic/caracole-password \
  forget --prune --keep-daily 7 --keep-weekly 5 --keep-monthly 12
EOF
sudo tee /etc/systemd/system/caracole-backup.timer > /dev/null <<'EOF'
[Unit]
Description=Nightly backup of caracole

[Timer]
OnCalendar=*-*-* 05:30
Persistent=true
RandomizedDelaySec=30m

[Install]
WantedBy=timers.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable --now caracole-backup.timer
```

To restore, as on NixOS, with `sudo restic -r /mnt/backup/restic/caracole -p
/etc/restic/caracole-password` for `sudo restic-caracole`.

### 11. The library page on your network

caracole-web listens on 127.0.0.1: from the laptop,
`ssh -L 8737:127.0.0.1:8737 server`, then `http://127.0.0.1:8737/`. For your
LAN, give it the machine's LAN address (`ip -4 addr`, fixed by a DHCP
reservation in the router), or its tailnet address:

```sh
sudo sed -i 's/--address 127.0.0.1/--address 192.168.1.20/' /etc/systemd/system/caracole-web.service
sudo systemctl daemon-reload && sudo systemctl restart caracole-web.service
sudo ufw allow from 192.168.1.0/24 to any port 8737 proto tcp   # with ufw on: the LAN alone
```

`--allow-host NAME`, added to its `ExecStart=`, is another name it answers to,
such as a full tailnet name.

### 12. Auto-chords

Optional, as on NixOS (section 4). torch comes from PyTorch's CPU-only index
(PyPI's brings GB of CUDA), then caracole's `autochords` extra:

```sh
sudo apt install ffmpeg unzip
sudo uv pip install --python /opt/caracole/releases/$REV/bin/python -c /opt/caracole/constraints.txt \
  --index-url https://download.pytorch.org/whl/cpu torch torchaudio torchcodec
sudo uv pip install --python /opt/caracole/releases/$REV/bin/python -c /opt/caracole/constraints.txt \
  "caracole[autochords] @ git+https://github.com/Danielhp95/caracole@$REV"
```

The model files `nix/autochords.nix` pins (JKU's server is sometimes down: try
again later), then deno and yt-dlp, for audio from YouTube; Ubuntu's yt-dlp is
too old for it. For purchases alone, leave those two out, and set
`enabled = false` under `[providers.youtube]` in caracole.toml:

```sh
cd "$(mktemp -d)"
curl -fsSLO https://raw.githubusercontent.com/jayg996/BTC-ISMIR19/2682317be668032e6e4b269ded36adaa2ad57df0/test/btc_model_large_voca.pt
curl -fsSLO https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/final0.ckpt
curl -fsSLO https://github.com/denoland/deno/releases/download/v2.9.7/deno-x86_64-unknown-linux-gnu.zip
sha256sum -c <<'EOF'
1673d23f8f9a55ae7f9e8b80a51da616debb22675b8d8b67ea6ce0ef37b0ab51  btc_model_large_voca.pt
8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331  final0.ckpt
c6527f24f4b16031d3ae4fa9f658d5f11534c8d84ce7dc8502420280919c3490  deno-x86_64-unknown-linux-gnu.zip
EOF
sudo install -d /opt/caracole/models
sudo install -m 0644 btc_model_large_voca.pt final0.ckpt /opt/caracole/models/
sudo unzip -o deno-x86_64-unknown-linux-gnu.zip deno -d /opt/caracole/bin
sudo uv venv --python $PY /opt/caracole/yt-dlp
sudo uv pip install --python /opt/caracole/yt-dlp/bin/python 'yt-dlp[default]'
sudo ln -sfn ../yt-dlp/bin/yt-dlp /opt/caracole/bin/yt-dlp
```

The unit runs after each run that succeeds, with no network, and may generate
code, as PyTorch and numba do; `caracole-admin` may too:

```sh
sudo tee /etc/systemd/system/caracole-autochords.service > /dev/null <<'EOF'
[Unit]
Description=caracole auto-chords: chord sheets from purchased audio, offline
After=caracole.service
OnFailure=caracole-notify-failure@%n.service

[Service]
Type=oneshot
ExecStart=/opt/caracole/bin/caracole autochords
TimeoutStartSec=6h
CPUSchedulingPolicy=batch
IOSchedulingClass=idle
PrivateNetwork=yes
MemoryDenyWriteExecute=no
EOF
sudo mkdir -p /etc/systemd/system/caracole-autochords.service.d
sudo ln -sfn /etc/caracole/units.conf /etc/systemd/system/caracole-autochords.service.d/caracole.conf
sudo sed -i 's/^#OnSuccess=/OnSuccess=/' /etc/systemd/system/caracole.service
sudo sed -i 's/MemoryDenyWriteExecute=yes/MemoryDenyWriteExecute=no/' /usr/local/sbin/caracole-admin
sudo systemctl daemon-reload && sudo systemctl restart caracole-web.service
sudo caracole-admin autochords   # auto-chords: 0 generated, 0 skipped, 0 failed
```

### 13. Upgrades

A new commit gets a virtual environment of its own, and the link moves once it
is ready:

```sh
PY=/opt/caracole/python/cpython-3.14.7-linux-x86_64-gnu/bin/python3.14
REV=$(git ls-remote https://github.com/Danielhp95/caracole refs/heads/caracole-v1 | cut -f1)
sudo uv venv --python $PY /opt/caracole/releases/$REV
sudo uv pip install --python /opt/caracole/releases/$REV/bin/python \
  -c /opt/caracole/constraints.txt "caracole @ git+https://github.com/Danielhp95/caracole@$REV"
# With auto-chords, section 12's two uv pip install lines too.
sudo ln -sfn releases/$REV /opt/caracole/current
sudo systemctl restart caracole-web.service
```

yt-dlp falls behind when YouTube changes:
`sudo uv pip install --python /opt/caracole/yt-dlp/bin/python -U 'yt-dlp[default]'`.

To roll back, point `current` at the commit before, and restart caracole-web.
A commit that moves `flake.lock`, `nix/pdf-fonts.py`, `nix/alphatab.nix` or
`nix/autochords.nix` moves the versions or files of sections 2, 4 or 12 too.

## The first run

On either system:

```sh
sudo caracole-admin index build              # once: Ultimate Guitar's sitemaps, about 10 minutes
sudo caracole-admin add "Soda Stereo - De Música Ligera"   # or a line in wanted.txt
sudo caracole-admin get "Radiohead - Creep"  # one song looked up now, its sheet in seconds
systemctl list-timers caracole.timer         # when the next run starts
sudo systemctl start caracole.service        # a whole run now; it returns when the run ends
journalctl -u caracole.service -e
```

`wanted.txt`, in the library, lists your songs, one a line: `Artist - Title`,
then optionally ` | Album` and ` | m:ss`, which make the lyrics exact
([usage.md](usage.md#wantedtxt)). Edit it on any device, or ask for a song on
the library page. Then read `_todo.md` in the library, or the library page: what
needs you comes first.

A file you pass `caracole-admin` must be one user `caracole` can read, outside
`/home`, `/root` and `/tmp`, which the sandbox hides. One caracole works at a
time: a command started during the nightly run waits for it, but a lookup
(`get`, or a song asked for on the library page) only for the run's next pause
([usage.md](usage.md#one-step-at-a-time)).

## Logs

The units write to the journal, each line under its priority
([usage.md](usage.md#what-caracole-prints)):

```sh
journalctl -u caracole -p warning     # only what needs you or went wrong
journalctl -u caracole -b -o cat      # the lines as caracole wrote them, the summary among them
sudo caracole-admin -v run            # a run now, a line per request, on the terminal
```

A block, a cooldown or a spent budget is no failure: the run exits 0 and the
songs wait for the next one. A bug exits 1, and ntfy says the unit failed
([usage.md](usage.md#caracole-run)).

## When something is wrong

- **ntfy says a unit failed:** `journalctl -u UNIT -e`, for the unit it names.
- **ntfy says a site blocked caracole:** nothing to do or work around. The
  message says until when caracole leaves the site alone; nothing was marked
  not found, and the songs wait.
- **`_todo.md` leads with "overrides.toml can't be read":** the run stopped
  before its first step; the error names the line. `Permission denied`: give
  the file group `caracole` and `chmod g+rw`. Then
  `sudo systemctl start caracole.service`.
- **"Another caracole is running":** the message names the process. A nightly
  run takes up to an hour, and with auto-chords up to another for YouTube.
- **"is at schema version N, but this caracole knows up to M":** a newer
  caracole migrated the database. Go back to it, or restore the copy saved
  before the migration, which the message names.
- **The library page doesn't load:** `journalctl -u caracole-web -e`; "can't
  listen on" says why. A 421: add the name the browser used to
  `web.allowedHosts` (`--allow-host`). "caracole serve has restarted since this
  page was opened": reload it.
- **Syncthing says "permission denied":** `ls -ld /var/lib/caracole/library`
  shows `drwxrwsr-x caracole caracole`, and `id syncthing` lists `caracole`?
  Restart Syncthing after a group change, and tick Ignore Permissions.
- **Auto-chords can't read a purchase:** the to-do page says why; replace the
  file (as FLAC, say). For audio from YouTube, put another video under
  `[youtube]` in overrides.toml.
- **The NixOS build can't fetch beat_this's checkpoint:** add a copy of
  `final0.ckpt` to the store, which Nix finds by its hash:
  `cp final0.ckpt beat_this-final0.ckpt && nix-store --add-fixed sha256 beat_this-final0.ckpt`.
