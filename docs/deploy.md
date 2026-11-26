# Deploying caracole

caracole runs on a server as a nightly service, with its library page on your network. There are
two ways to set it up:

- **[NixOS](#nixos)**: the flake's module, `nixosModules.default`.
- **[Ubuntu 24.04 without Nix](#ubuntu-2404-without-nix)**: apt, a few downloads checked against
  their SHA-256, and systemd units that do what the module does.

[The first run](#the-first-run), [Checking auto-chords](#checking-auto-chords), [Logs](#logs),
[Moving an index into the service](#moving-an-index-into-the-service), [Restoring the
database](#restoring-the-database) and [When something is wrong](#when-something-is-wrong) apply
to both. Either way the machine gets:

| What | Does |
|---|---|
| `caracole.timer` | Starts the nightly run at 03:30, up to 45 minutes late; a run missed while the machine was off starts at the next boot |
| `caracole.service` | `caracole run`, a hardened oneshot as user `caracole` |
| `caracole-web.service` | `caracole serve`: the library page, its search and song requests |
| `caracole-autochords.service` | Optional. After each successful run, chord sheets from audio, with no network |
| `caracole-notify-failure` | Posts to your ntfy topic when one of the units fails |
| `caracole-admin` | Runs any `caracole` command as the units do: `sudo caracole-admin index build` |

It also gets a data folder, `/var/lib/caracole` unless you choose another. Don't put it under
`/home`, `/root`, `/run/user`, `/tmp` or `/var/tmp`: the units' sandbox hides those.

| Folder | Holds |
|---|---|
| `library` | sheets, lyrics, guitar parts, `_todo.md`, `index.html`, `wanted.txt`, `overrides.toml`, `songbooks.toml`, `_inbox/`: synced to your devices |
| `music` | audio you bought, read-only, for auto-chords |
| `state` | the database, its last three copies (`backups/`, made at the end of each nightly run), the audio files you give caracole (`audio/`) and caracole's lock, `caracole`'s alone: back it up, never sync it |
| `cache` | every raw HTTP response, kept forever: losing it costs only requests |

caracole keeps no credentials. ntfy is only a topic URL, readable by anyone who knows it and by
every user of the host (on NixOS, it's in the Nix store), so make it long and random. The library
page has no sign-in: anyone who reaches it can read the library and request songs. Keep it on your
LAN or tailnet, never the internet.

## NixOS

### 1. The flake and the module

In your system flake's `flake.nix`:

```nix
    # The chord sheet library; its nixosModules.default runs it nightly.
    caracole.url = "github:Danielhp95/caracole";
    caracole.inputs.nixpkgs.follows = "nixpkgs";
```

A new commit on caracole's `main` reaches the host after `nix flake update caracole` and a switch.
With `follows`, caracole builds and runs its tests with your nixpkgs. If your tomlkit or ChordPro is
newer than caracole supports yet (tomlkit 0.15.1, ChordPro 6.060), the build fails. Without the
line, caracole builds with its own nixpkgs. Then, in the host's configuration (with `inputs` in
`specialArgs`):

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
| `autochords.cuda` | `false` | the GPU for transcriptions from the audio, in caracole-web and `caracole-admin` alone, with `autochords.enable` (section 4) |
| `autochords.btcWeights`, `autochords.beatCheckpoint`, `autochords.whisperModel`, `autochords.separatorModel` | `null` | model files other than the package's |
| `package`, `autochords.package` | the flake's builds | |

### 2. Syncthing for the library and the music

The library is `caracole:caracole`, mode 2775 with setgid, and caracole writes with umask 0007.
Syncthing joins group `caracole` with the same umask, so it can write there too. Add to
`hosts/nuc/caracole.nix`:

```nix
  services.syncthing = {
    enable = true;
    # For devices on the LAN; over a tailnet whose interface is trusted, it needs none.
    openDefaultPorts = true;
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

After the first switch, run `sudo systemctl restart syncthing` so it picks up its new group.

### 3. Backups with restic

This backs up the state, the library and the music. The live database goes in as a consistent
copy, made with SQLite's online backup:

```nix
  services.restic.backups.caracole = {
    initialize = true;
    repository = "/mnt/backup/restic/caracole"; # or sftp:host:/path, s3:…
    passwordFile = "/etc/restic/caracole-password";
    paths = [ caracole.stateDir caracole.libraryDir caracole.musicDir ];
    # The live database goes in as the copy below; backups/ holds caracole's own nightly copies.
    exclude = [ "${caracole.stateDir}/caracole.sqlite*" "${caracole.stateDir}/backups" ];
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
sudo systemctl stop caracole.timer caracole-web.service caracole.service   # and caracole-autochords.service
sudo restic-caracole restore latest --target /
cd /var/lib/caracole/state
sudo rm -f caracole.sqlite-wal caracole.sqlite-shm
sudo install -o caracole -g caracole -m 0600 caracole-backup.sqlite caracole.sqlite
sudo systemctl start caracole.timer caracole-web.service
```

### 4. Auto-chords

For a song nobody has charted, a local model writes `sheet (auto).txt` from its audio. The audio
can be a track you bought and dropped into the music folder, audio the nightly run takes from
YouTube, or a video you paste on the library page. See [autochords.md](autochords.md).

```nix
  services.caracole.autochords.enable = true;
```

This builds the `autochords` package, about 3 GB more: torch, librosa, beat_this, and yt-dlp with
ffmpeg and deno. It uses the two model files `nix/autochords.nix` fetches, checked by their hashes.
JKU's server is sometimes down: see [When something is wrong](#when-something-is-wrong). Then:

- `caracole-autochords.service` runs after each successful run, with no network, on the CPU, a few
  minutes a song.
- The nightly run takes the audio of up to three songs a night with no human sheet from YouTube.
  This goes against YouTube's robots.txt and terms, on the terms
  [usage.md](usage.md#audio-from-youtube) gives.
- caracole-web can make a sheet from a YouTube video, pasted in the request form or suggested for a
  search. The models run inside it, so caracole-web and `caracole-admin` run without
  `MemoryDenyWriteExecute`. The nightly run keeps it.

With an NVIDIA GPU (the host's driver set up with `hardware.graphics` and `hardware.nvidia`), lyrics
transcription can run on it:

```nix
  services.caracole.autochords.cuda = true;
```

This uses the flake's `autochords-cuda` build (about 6.7 GiB, unfree CUDA libraries). Whisper runs
on CUDA and demucs-rs on Vulkan. Only caracole-web and `caracole-admin` get the GPU devices; the
nightly units don't, and the chord models stay on the CPU. It needs `autochords.enable`, or it does
nothing and the build warns. If you import nix/module.nix without the flake, set
`autochords.package` to a CUDA build yourself.

For purchases only, with no yt-dlp and no YouTube on the library page:

```nix
  services.caracole.settings.providers.youtube.enabled = false;
```

Suggested videos show a thumbnail from `i.ytimg.com`, a provider of its own:
`settings.providers.ytimg.enabled = false` drops only the thumbnails. Then [check that it
works](#checking-auto-chords).

### 5. The library page on your network

`web.address` decides who can reach it:

- `127.0.0.1`, the default: this machine only. From the laptop,
  `ssh -L 8737:127.0.0.1:8737 nuc`, then `http://127.0.0.1:8737/`.
- The tailnet address: your tailnet. A tailnet whose interface is in
  `networking.firewall.trustedInterfaces` needs no firewall opening.
- The LAN address, with `web.openFirewall = true`: everyone on the LAN.

It answers to its IP addresses and the names it knows. Put a full tailnet name in `allowedHosts`, or
the browser gets a 421. If the tailnet address doesn't exist yet at boot, it retries every 10
seconds. [usage.md](usage.md#caracole-serve) says what the page does.

### 6. Publishing the site indexes

`services.caracole.publish.enable = true` adds `caracole-publish.service` and its timer
(`publish.calendar`, `Sun 05:00` by default). It runs `caracole index publish` with no network and
writes a gzip of every site index into `publish.folder` (`/var/lib/caracole/publish`, mode 2750, group
`caracole`, so a user in that group can read it).

Uploading to GitHub is your own user's job, with your own `gh` login: the module holds no token.
`publish.uploadUser = "<login>";` makes a publish that succeeds start your user service,
`caracole-upload.service`, in your user manager. Define it in your own configuration, with a weekly
timer to catch up (the example assumes your user is in group `caracole` and `gh auth login` is done):

```nix
  services.caracole.publish.uploadUser = "<login>";

  systemd.user.services.caracole-upload = {
    description = "Upload the site indexes to GitHub";
    unitConfig.ConditionPathExists = "/var/lib/caracole/publish/published.json";
    path = [ pkgs.gh ];
    script = ''
      export GH_TOKEN=$(gh auth token --user <account>)
      exec ${caracole.packages.${pkgs.stdenv.hostPlatform.system}.publish-indexes}/bin/publish-indexes /var/lib/caracole/publish
    '';
  };
  systemd.user.timers.caracole-upload = {
    wantedBy = [ "timers.target" ];
    timerConfig = { OnCalendar = "Mon 06:00"; Persistent = true; };
  };
```

`<login>` is your user on this machine, `<account>` the GitHub account that owns the repository
(`gh`'s active account may be another). Once a publish succeeds, `caracole-publish-upload-notify.service`
asks whether your user manager runs, and starts the upload in it only if it does: it never starts one,
since an upload in a manager with no session would find `gh`'s keyring locked. When it doesn't run,
the notifier says so in one line, succeeds, and the timer catches up at your next login (`Persistent`);
any other failure (no such user, no `caracole-upload.service`) fails the notifier, never the publish.
An upload of a file already there says "already published" and changes nothing; one GitHub lists
with no digest can't be checked, so it is deleted and uploaded again. `gh` may keep its
token in a login keyring, locked without a session, which is why the example doesn't enable linger.

Only the service's run starts the upload. After a publish by hand (`sudo caracole-admin index publish
/var/lib/caracole/publish`), upload it yourself with `systemctl --user start caracole-upload`.

The upload says each step as it begins, and every 30 seconds while `gh` sends the file, how far it has
read it (`publish-indexes: uploading · 31 of 80 MB · 3 min so far, about 5 min left`; where it can't
tell, the time so far and the file's size). An 80 MB file can take several minutes. Watch it with
`journalctl --user -fu caracole-upload`.

There is no user path unit watching `published.json`: systemd watches every folder from `/` down to
the file, and your user can't read `/var/lib/caracole` (mode 0710), so such a unit never fires.

`caracole` is the flake input. `publish-indexes DIR` checks what GitHub holds and prunes old files.

## Ubuntu 24.04 without Nix

The same service, without Nix, on an x86-64 machine. What the Nix package brings goes under
`/opt/caracole`, and the units match the module's. Run the blocks in order, in one shell, as a user
with sudo: later blocks use `$PY` and `$REV`. Each download is checked against its SHA-256: stop if
you see `FAILED`.

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

uv installs CPython 3.14.7, which caracole is tested on, where the units can read it:

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

caracole's dependencies come from PyPI, pinned to the Nix package's versions, which the tests pass
with (PyPI's latest tomlkit breaks renaming a songbook). Their own dependencies are PyPI's latest:

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
opencc==1.4.1
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
openai-whisper==20250625
triton==3.7.1
tiktoken==0.12.0
more-itertools==11.1.0
tqdm==4.68.4
EOF
```

Then install caracole at the head of `main`, in a virtual environment for that commit. It is
compiled ahead, since the units can't write `.pyc` files there, and linked as `current` once
complete:

```sh
REV=$(git ls-remote https://github.com/Danielhp95/caracole refs/heads/main | cut -f1)
test -n "$REV" &&
sudo uv venv --allow-existing --python $PY /opt/caracole/releases/$REV &&
sudo uv pip install --compile-bytecode --python /opt/caracole/releases/$REV/bin/python \
  -c /opt/caracole/constraints.txt "caracole @ git+https://github.com/Danielhp95/caracole@$REV" &&
sudo ln -sfn releases/$REV /opt/caracole/current
```

### 3. ChordPro 6.050.7

caracole makes no PDF with a later ChordPro, and Ubuntu has none. cpanm builds it into
`/opt/caracole/perl`, with JavaScript::QuickJS (not in apt) and Text::Layout 0.037 (newer than
apt's). The rest comes from apt:

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

The PDF fonts, Adwaita Sans and Mono, made by caracole's `nix/pdf-fonts.py` as the Nix package
makes them. LXGW FusionKai for Chinese words. alphaTab for Guitar Pro files in the browser:

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

Like the Nix package's wrapper: it puts ChordPro on PATH and sets default paths for the fonts,
alphaTab and the model files. A variable you already set wins.

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

The folders as the NixOS module makes them, and caracole.toml. Put your own ntfy topic in it, or
leave `[ntfy]` out:

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
sudo tee /etc/caracole/service > /dev/null <<'EOF'
# caracole runs here as a service: `sudo caracole-admin COMMAND` runs a command on its library.
# caracole started without --config reads this file (docs/usage.md, "The service's library").
state_dir = "/var/lib/caracole/state"
library_dir = "/var/lib/caracole/library"
EOF
```

The last file, which the NixOS module writes too, tells a caracole you start yourself without
`--config` that this machine runs caracole as a service. That caracole builds no index into your
home folders, and warns before it writes there
([usage.md](usage.md#the-services-library-and-your-homes)).

To keep the data elsewhere, replace `/var/lib/caracole` with its path in every file of this part.

### 7. The units

One file holds the user and folders, another the sandbox. Each caracole unit takes both as
drop-ins, and `caracole-admin` reads them too. The failure alert takes only the sandbox:

```sh
sudo tee /etc/caracole/units.conf > /dev/null <<'EOF'
# The user, the folders and the config of every caracole unit.
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
EOF
sudo tee /etc/caracole/sandbox.conf > /dev/null <<'EOF'
# The sandbox of every caracole unit, and of the failure alert.
[Service]
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

The failure alert posts to your ntfy topic, whose URL is on its last line. It repeats the URL in
caracole.toml's `[ntfy]`, so a new topic means editing both. Without ntfy, skip this block, leave
the `OnFailure=` lines out of the units below, and leave the alert out of the check after them.

```sh
sudo tee /etc/systemd/system/caracole-notify-failure@.service > /dev/null <<'EOF'
[Unit]
Description=Tell ntfy that %i failed
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
DynamicUser=yes
MemoryDenyWriteExecute=yes
ExecStart=/usr/bin/curl --silent --show-error --fail-with-body --max-time 30 --retry 3 \
  --header "Title: caracole: %i failed" --header "Priority: high" --header "Tags: warning" \
  --data-binary "%i failed on %H (${MONITOR_SERVICE_RESULT}). See: journalctl -u %i" \
  https://ntfy.sh/caracole-change-me
EOF
sudo mkdir -p /etc/systemd/system/caracole-notify-failure@.service.d
sudo ln -sfn /etc/caracole/sandbox.conf /etc/systemd/system/caracole-notify-failure@.service.d/sandbox.conf
```

The nightly run, its timer, and the library page (on this machine only until section 11):

```sh
sudo tee /etc/systemd/system/caracole.service > /dev/null <<'EOF'
[Unit]
Description=caracole nightly run: sync, match, fetch and write the library
Wants=network-online.target
After=network-online.target
OnFailure=caracole-notify-failure@%n.service

[Service]
Type=oneshot
ExecStart=/opt/caracole/bin/caracole run
NotifyAccess=main
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

Then link the shared files for both caracole units, check, and start:

```sh
for unit in caracole caracole-web; do
  sudo mkdir -p /etc/systemd/system/$unit.service.d
  sudo ln -sfn /etc/caracole/units.conf /etc/systemd/system/$unit.service.d/caracole.conf
  sudo ln -sfn /etc/caracole/sandbox.conf /etc/systemd/system/$unit.service.d/sandbox.conf
done
sudo systemd-analyze verify caracole.service caracole.timer caracole-web.service \
  caracole-notify-failure@caracole.service.service   # silent when all is well
sudo systemctl daemon-reload
sudo systemctl enable --now caracole.timer caracole-web.service
```

### 8. caracole-admin

Runs a command as the units do: a transient unit with their settings, plus the network.

```sh
sudo tee /usr/local/sbin/caracole-admin > /dev/null <<'EOF'
#!/bin/bash
# Runs a caracole command as the caracole units do.
if [ "$EUID" -ne 0 ]; then
  echo "caracole-admin starts a system unit as the caracole user: run it with sudo" >&2
  exit 1
fi
# Each setting of units.conf and sandbox.conf, as a --property.
mapfile -t properties < <(sed -n 's/^[A-Z]/--property=&/p' /etc/caracole/units.conf /etc/caracole/sandbox.conf)
# With auto-chords (section 12), as its unit, without MemoryDenyWriteExecute: PyTorch generates code.
mdwe=yes
if [ -e /etc/systemd/system/caracole-autochords.service ]; then mdwe=no; fi
# --pty on a terminal (review and remove ask questions), --pipe otherwise.
exec systemd-run --quiet --collect --wait --pty --pipe "${properties[@]}" \
  --property=MemoryDenyWriteExecute=$mdwe -- /opt/caracole/bin/caracole "$@"
EOF
sudo chmod 0755 /usr/local/sbin/caracole-admin
sudo caracole-admin --version   # caracole 0.1.0
```

### 9. Syncthing

As on NixOS (section 2): Syncthing as its own user, in group `caracole`, with umask 0007, and
owning the music folder.

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

Its GUI listens on the machine only: `ssh -L 8384:localhost:8384 server`, then
`http://localhost:8384`. Add your devices and two folders, `tabs` at `/var/lib/caracole/library`
and `music` at `/var/lib/caracole/music`. Tick **Ignore Permissions** under Advanced for each. With
ufw on, run `sudo ufw allow syncthing`.

### 10. Backups with restic

The NixOS backup (section 3), as a unit and a timer. Replace `/mnt/backup/restic/caracole` with
your repository:

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
  backup --exclude=/var/lib/caracole/state/caracole.sqlite* --exclude=/var/lib/caracole/state/backups \
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

To restore, do as on NixOS, with `sudo restic -r /mnt/backup/restic/caracole -p
/etc/restic/caracole-password` in place of `sudo restic-caracole`.

### 11. The library page on your network

caracole-web listens on 127.0.0.1: from the laptop, `ssh -L 8737:127.0.0.1:8737 server`, then
`http://127.0.0.1:8737/`. For your LAN, give it the machine's LAN address (`ip -4 addr`, fixed by a
DHCP reservation in the router), or its tailnet address:

```sh
sudo sed -i 's/--address 127.0.0.1/--address 192.168.1.20/' /etc/systemd/system/caracole-web.service
sudo systemctl daemon-reload && sudo systemctl restart caracole-web.service
sudo ufw allow from 192.168.1.0/24 to any port 8737 proto tcp   # with ufw on: the LAN alone
```

Add `--allow-host NAME` to its `ExecStart=` for each other name it should answer to, such as a full
tailnet name.

### 12. Auto-chords

Optional, as on NixOS (section 4). torch comes from PyTorch's CPU-only index (PyPI's brings GBs of
CUDA), then caracole's `autochords` extra, both at section 2's versions:

```sh
sudo apt install ffmpeg unzip
PY=/opt/caracole/python/cpython-3.14.7-linux-x86_64-gnu/bin/python3.14
VENV=$(readlink -f /opt/caracole/current)   # the commit caracole runs now
sudo uv pip install --compile-bytecode --python $VENV/bin/python -c /opt/caracole/constraints.txt \
  --index-url https://download.pytorch.org/whl/cpu torch torchaudio torchcodec
sudo uv pip install --compile-bytecode --python $VENV/bin/python -c /opt/caracole/constraints.txt \
  "caracole[autochords] @ git+https://github.com/Danielhp95/caracole@$(basename $VENV)"
```

Next, the model files `nix/autochords.nix` pins (JKU's server is sometimes down: try again later).
For audio from YouTube you also need yt-dlp and deno, the JavaScript runtime it uses for YouTube's
player: deno at nixpkgs' version, yt-dlp at its latest (Ubuntu's is too old). For purchases only,
leave those two out and turn YouTube off:
`printf '\n[providers.youtube]\nenabled = false\n' | sudo tee -a /etc/caracole/caracole.toml`.

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
sudo uv venv --allow-existing --python $PY /opt/caracole/yt-dlp
sudo uv pip install --compile-bytecode --python /opt/caracole/yt-dlp/bin/python 'yt-dlp[default]'
sudo ln -sfn ../yt-dlp/bin/yt-dlp /opt/caracole/bin/yt-dlp
```

The Ubuntu install doesn't transcribe lyrics from audio. That needs Whisper large-v3 and HTDemucs
(the Nix package's are checked against
`e5b1a55b89c1367dacf97e3e19bfd829a01529dbfdeefa8caeb59b3f1b81dadb` for `large-v3.pt` and
`8193504cdfb3943adaf039b8acb524a46e87ebf232c383ac7a32c80a6578423e` for `htdemucs.safetensors`)
and a CPU build of demucs-rs, none of which this section installs. `openai-whisper` comes with the
extra but goes unused.

The unit runs after each successful run, with no network, and without `MemoryDenyWriteExecute`
because PyTorch and numba generate code. Two drop-ins start it after caracole.service and lift
`MemoryDenyWriteExecute` for caracole-web; `caracole-admin` lifts it once this unit exists:

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
sudo ln -sfn /etc/caracole/sandbox.conf /etc/systemd/system/caracole-autochords.service.d/sandbox.conf
printf '[Unit]\nOnSuccess=caracole-autochords.service\n' |
  sudo tee /etc/systemd/system/caracole.service.d/autochords.conf > /dev/null
printf '[Service]\nMemoryDenyWriteExecute=no\n' |
  sudo tee /etc/systemd/system/caracole-web.service.d/autochords.conf > /dev/null
sudo systemd-analyze verify caracole.service caracole-web.service caracole-autochords.service \
  caracole-notify-failure@caracole-autochords.service.service   # silent when all is well
sudo systemctl daemon-reload && sudo systemctl restart caracole-web.service
sudo caracole-admin autochords   # auto-chords: 0 generated, 0 skipped, 0 failed
```

Then [check that it works](#checking-auto-chords).

### 13. Publishing the site indexes

The publish folder beside the others, which the units and `caracole-admin` may write, and the upload
script, which needs `gh` and `jq`. Your user reads the folder as a member of group `caracole`:

```sh
echo 'd /var/lib/caracole/publish 2750 caracole caracole -' | sudo tee -a /etc/tmpfiles.d/caracole.conf > /dev/null
sudo systemd-tmpfiles --create /etc/tmpfiles.d/caracole.conf
sudo sed -i '/^ReadWritePaths=/s|$| /var/lib/caracole/publish|' /etc/caracole/units.conf
sudo systemctl daemon-reload
sudo apt install gh jq
sudo curl -fsSLo /usr/local/bin/publish-indexes \
  https://raw.githubusercontent.com/Danielhp95/caracole/$REV/nix/publish-indexes.sh
sudo chmod 0755 /usr/local/bin/publish-indexes
sudo usermod -aG caracole "$USER"   # then log in again
```

There is no timer here. To publish, then upload, logged in with `gh auth login` (or with `GH_TOKEN`
as `gh auth token` prints it):

```sh
sudo caracole-admin index publish /var/lib/caracole/publish
PATH=/opt/caracole/bin:$PATH publish-indexes /var/lib/caracole/publish
```

The publish needs `caracole-admin`, so sudo; the upload is your user's, with your `gh` login. Both
say what they do as they go; the upload, every 30 seconds, how much of the file `gh` has sent.

### 14. Upgrades

Each new commit gets its own virtual environment, and the link moves once it is ready:

```sh
PY=/opt/caracole/python/cpython-3.14.7-linux-x86_64-gnu/bin/python3.14
REV=$(git ls-remote https://github.com/Danielhp95/caracole refs/heads/main | cut -f1)
VENV=/opt/caracole/releases/$REV
test -n "$REV" &&
sudo uv venv --allow-existing --python $PY $VENV &&
sudo uv pip install --compile-bytecode --python $VENV/bin/python \
  -c /opt/caracole/constraints.txt "caracole @ git+https://github.com/Danielhp95/caracole@$REV" &&
if [ -e /etc/systemd/system/caracole-autochords.service ]; then   # with auto-chords, section 12's two installs
  sudo uv pip install --compile-bytecode --python $VENV/bin/python -c /opt/caracole/constraints.txt \
    --index-url https://download.pytorch.org/whl/cpu torch torchaudio torchcodec &&
  sudo uv pip install --compile-bytecode --python $VENV/bin/python -c /opt/caracole/constraints.txt \
    "caracole[autochords] @ git+https://github.com/Danielhp95/caracole@$REV"
fi &&
sudo ln -sfn releases/$REV /opt/caracole/current &&
sudo systemctl restart caracole-web.service
```

yt-dlp falls behind when YouTube changes:
`sudo uv pip install --compile-bytecode --python /opt/caracole/yt-dlp/bin/python -U 'yt-dlp[default]'`.

To roll back, point `current` at the previous commit and restart caracole-web. A commit that
changes `flake.lock`, `nix/pdf-fonts.py`, `nix/alphatab.nix` or `nix/autochords.nix` also changes
the versions or files of sections 2, 4 or 12.

## The first run

On either system:

```sh
sudo caracole-admin index build              # once: Ultimate Guitar's sitemaps, about 4 minutes
sudo caracole-admin ug --directory           # once: UG's artist directory, about an hour (usage.md)
sudo caracole-admin add "Soda Stereo - De Música Ligera"   # or a line in wanted.txt
sudo caracole-admin get "Radiohead - Creep"  # one song looked up now, its sheet in seconds
systemctl list-timers caracole.timer         # when the next run starts
sudo systemctl start caracole.service        # a whole run now; it returns when the run ends
journalctl -u caracole.service -e
```

`wanted.txt`, in the library, lists your songs, one per line: `Artist - Title`, then optionally
` | Album` and ` | m:ss`, which make the lyrics exact ([usage.md](usage.md#wantedtxt)). Edit it on
any device, or ask for a song on the library page. Then read `_todo.md` in the library, or the
library page: what needs you comes first.

Files you pass to `caracole-admin` must be readable by user `caracole` and outside `/home`,
`/root` and `/tmp`. A `caracole` you run yourself without `--config` uses your home folders, warns
you about it, and builds no index unless you add `--home`
([usage.md](usage.md#the-services-library-and-your-homes)).

One caracole works at a time. A command started during the nightly run waits for it to end, but a
lookup waits only for the run's next pause ([usage.md](usage.md#one-step-at-a-time)).

## Checking auto-chords

On either system, once it is on (NixOS section 4, Ubuntu section 12):

```sh
systemctl show -p OnSuccess caracole.service                    # OnSuccess=caracole-autochords.service
systemctl show -p MemoryDenyWriteExecute caracole-web.service   # MemoryDenyWriteExecute=no
sudo systemctl start --no-block caracole-autochords.service     # now, rather than after the next run
journalctl -u caracole-autochords -f                            # its last line: auto-chords: 0 generated, 0 skipped, 0 failed
```

The library page's request form then has a **YouTube video** field, and after the next nightly run
the Sites tab's YouTube line counts its yt-dlp runs. If the field is missing, the form says why
("No sheets from YouTube here: …"), and so does the Sites tab's YouTube line once opened:

| It says | Then |
|---|---|
| auto-chords isn't installed | NixOS: `autochords.enable`. Ubuntu: section 12's two installs, which an upgrade makes again in each new commit (section 14) |
| auto-chords' model files are missing | `CARACOLE_BTC_WEIGHTS` or `CARACOLE_BEAT_CHECKPOINT` names no file: on Ubuntu, section 12's downloads |
| yt-dlp is missing | Ubuntu: section 12's yt-dlp, linked into `/opt/caracole/bin` |
| YouTube is turned off | `[providers.youtube] enabled = false`: auto-chords for purchases alone |

Then try one song end to end: one nobody has charted, from a video of it. It goes into wanted.txt
if the library doesn't have it. Its audio, lyrics, chords, PDF and viewer arrive in a few minutes,
one line per stage, then `Done in …`:

```sh
sudo caracole-admin youtube --song "Artist - Title" --url "https://www.youtube.com/watch?v=…" --sheet
```

On the library page, you can do the same by pasting a video in the request form, or with **Make the
sheet** on the video suggested for a search that found no sheet. Either way the sheet opens in the
viewer like any other.

## Logs

The units write to the journal, each line at its priority
([usage.md](usage.md#what-caracole-prints)):

```sh
journalctl -u caracole -f             # a run as it goes
systemctl status caracole             # Status: the step under way, and how far it is
journalctl -u caracole -p warning     # only what needs you or went wrong
journalctl -u caracole -b -o cat      # the lines as caracole wrote them, the summary among them
journalctl -u caracole-web | grep 'library page'   # each library page served: its songs, the database it read
sudo caracole-admin -v run            # a run now, a line per request, on the terminal
```

While a run goes, the journal gets a line as each step starts and ends, and in between, at most a
line a minute saying how far the step is (requests against its budget, UG's directory's pages, the
PDFs made). `systemctl status caracole` shows that as its `Status:` line, updated every few
seconds, and once the run is over, what it came to: `Finished in 12 min 3 s · ` and the summary's
first line ([usage.md](usage.md#what-caracole-prints)):

    [6/20] lyrics…
    [6/20] lyrics · LRCLIB · 120 of up to 200 requests  up to about 1 min left
    [6/20] lyrics: 12 found, 3 missing, 0 instrumental, 0 errors (1 min 32 s)

A block, a cooldown or a spent budget is not a failure: the run exits 0 and the songs wait for the
next one. A bug exits 1, and ntfy says the unit failed ([usage.md](usage.md#caracole-run)).

## Moving an index into the service

You can move an index built by your own `caracole` (in `~/.local/state/caracole`) into the
service's database. Export it as yourself, put it where user `caracole` can read it (the sandbox
hides `/home` and `/tmp`), merge it, and delete it:

```sh
caracole index export /tmp/caracole-indexes.sqlite        # add --site harptabs, say, for one site's
sudo install -o caracole -g caracole -m 0600 /tmp/caracole-indexes.sqlite /var/lib/caracole/state/indexes.sqlite
sudo caracole-admin index merge /var/lib/caracole/state/indexes.sqlite
sudo rm /var/lib/caracole/state/indexes.sqlite && rm /tmp/caracole-indexes.sqlite
```

The merge takes whatever the file read more recently, page by page and sitemap by sitemap, and
leaves the rest alone. It saves a copy of the database in `backups/` first
([usage.md](usage.md#caracole-index-export-and-merge)). Both caracoles must be at the same schema
version; otherwise the merge says so and changes nothing.

## Restoring the database

Each successful nightly run ends with a full copy of the database in
`/var/lib/caracole/state/backups/`, keeping the last three ([usage.md](usage.md#caracole-backup)).
`sudo caracole-admin backup` makes one now.

To put one back, stop caracole, move the database aside with its `-wal` and `-shm` files (a
leftover `-wal` would be read into the restored database), and copy the backup into its place:

```sh
sudo systemctl stop caracole.timer caracole-web.service caracole.service   # and caracole-autochords.service
sudo caracole-admin backup --list   # the copies, the newest last
sudo sh -c 'cd /var/lib/caracole/state && mkdir -p -m 0700 before-restore &&
  for f in caracole.sqlite caracole.sqlite-wal caracole.sqlite-shm; do
    if [ -e "$f" ]; then mv "$f" before-restore/; fi
  done &&
  install -o caracole -g caracole -m 0600 backups/caracole-2026-10-29T034512Z.sqlite caracole.sqlite'
sudo systemctl start caracole.timer caracole-web.service
```

The following nightly runs redo what the nights since the copy did, from the HTTP cache where they
can. A copy made by a newer caracole stops every command with status 2. An older one is migrated
as an upgrade would. Delete `before-restore/` once all is well. Restore restic's copy (NixOS
section 3, Ubuntu section 10) the same way.

## When something is wrong

| Symptom | What to do |
|---|---|
| ntfy says a unit failed | `journalctl -u UNIT -e`, for the unit it names. |
| ntfy says a site blocked caracole | Nothing. The message says until when caracole leaves the site alone. No song was marked not found; they wait. |
| `_todo.md` leads with "overrides.toml can't be read" | The run stopped before its first step, and the error names the line. For `Permission denied`, give the file group `caracole` and `chmod g+rw`. Then `sudo systemctl start caracole.service`. |
| "Another caracole is running" | The message names the process. A nightly run takes up to an hour, plus up to another with auto-chords for YouTube. |
| "is at schema version N, but this caracole knows up to M" | A newer caracole migrated the database. Go back to it, or restore the pre-migration copy the message names. |
| The library page shows no songs | `journalctl -u caracole-web \| grep 'library page'`. A page with no songs logs a warning naming the database it opened, its size, owner, schema version and `songs` rows, and the uid caracole-web runs as. Use `-u caracole` for the `index.html` the nightly run wrote ([usage.md](usage.md#what-caracole-prints)). |
| The library page doesn't load | `journalctl -u caracole-web -e`: "can't listen on" says why. For a 421, add the name the browser used to `web.allowedHosts` (`--allow-host`). For "caracole serve has restarted since this page was opened", reload. |
| Syncthing says "permission denied" | Check that `ls -ld /var/lib/caracole/library` shows `drwxrwsr-x caracole caracole` and `id syncthing` lists `caracole`. Restart Syncthing after a group change, and tick Ignore Permissions. |
| Auto-chords can't read a purchase | The to-do page says why. Replace the file (as FLAC, say). For audio from YouTube, put another video under `[youtube]` in overrides.toml. |
| The NixOS build can't fetch beat_this's checkpoint | Add a copy of `final0.ckpt` to the store, where Nix finds it by its hash: `cp final0.ckpt beat_this-final0.ckpt && nix-store --add-fixed sha256 beat_this-final0.ckpt`. |

To tell which server a page comes from, look at the library name after "caracole" in its header
(`name` in caracole.toml, else the library folder's name). A **Scratch library** badge means another
caracole serve on a temporary library; caracole-web's pages have none
([usage.md](usage.md#caracole-serve)). The Journal keeps each request across restarts, in
`/var/lib/caracole/state/requests.jsonl`.
