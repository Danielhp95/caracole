# Deploying tabarr on the NUC

tabarr ships a NixOS module (`nixosModules.default` in this flake). Enabled, it
gives the machine:

| What | Does |
|---|---|
| `tabarr.timer` | Starts the nightly run at 03:30, up to 45 minutes late, and catches up after downtime |
| `tabarr.service` | `tabarr --config <generated tabarr.toml> run`, a hardened oneshot as user `tabarr` |
| `tabarr-autochords.service` | Optional. After each successful run, writes `sheet (auto).txt` from audio you bought, with no network at all |
| `tabarr-notify-failure.service` | POSTs to your ntfy topic when either unit fails |
| `tabarr-admin` | Runs any `tabarr` command as the units do: `sudo tabarr-admin auth spotify` |
| `/var/lib/tabarr/state` | The database, the Spotify token and tabarr's lock, readable by `tabarr` alone |
| `/var/lib/tabarr/cache` | Every raw HTTP response, kept forever, and the private folders PDFs are made in |
| `/var/lib/tabarr/library` | The library: sheets, lyrics, guitar parts, `_todo.md`, `wanted.txt`, `overrides.toml` |
| `/var/lib/tabarr/music` | Audio you bought, read-only, for auto-chords |

The four folders sit in `services.tabarr.dataDir`, `/var/lib/tabarr` unless
you set it, say to `/data/tabarr` on a data disk. `stateDir`, `cacheDir`,
`libraryDir` and `musicDir` each put one elsewhere.

The rest of this page sets that up in `/etc/nixos`, which has no NUC host
yet. The snippets follow that repository's conventions: a module is on because
it is imported, inputs follow `nixpkgs`, and comments say why.

## 1. Add the flake and a host

In `/etc/nixos/flake.nix`, add the input:

```nix
    # The chord sheet library; nixosModules.default runs it nightly (hosts/nuc).
    tabarr.url = "github:Danielhp95/tabarr";
    tabarr.inputs.nixpkgs.follows = "nixpkgs";
```

Once the repository has a remote, point `tabarr.url` there instead. A commit
in `~/Projects/tabarr` reaches a rebuild only after `nix flake update tabarr`.

Then add the host to the list: `nixpkgs.lib.genAttrs [ "laptop" "nuc" ]`. The
flake passes every host its `facts.nix`, so the NUC needs one, even an empty
`{ }`.

The shared `nixos/` list is the desktop: Home Manager, the greeter, audio. A
headless NUC imports only what it needs:

```nix
# hosts/nuc/default.nix
# The NUC: headless, on the tailnet, running tabarr (./tabarr.nix).
{ hostName, ... }:
{
  imports = [
    ./hardware.nix # nixos-generate-config on the NUC
    ./tabarr.nix
    ../../nixos/tailscale.nix
    ../../nixos/locale.nix
  ];

  networking.hostName = hostName;

  # Reached over the tailnet only (tailscale0 is trusted in tailscale.nix).
  # agenix also decrypts with this machine's SSH host key.
  services.openssh = {
    enable = true;
    openFirewall = false;
  };

  # The release this disk was installed with; never bump it.
  system.stateVersion = "26.11";
}
```

The module itself, with no Spotify yet (`wanted.txt` alone is enough):

```nix
# hosts/nuc/tabarr.nix
# tabarr (~/Projects/tabarr): the nightly chord sheet library, its secrets,
# Syncthing for the library and the music, and restic.
{
  config,
  inputs,
  lib,
  pkgs,
  ...
}:
let
  tabarr = config.services.tabarr;
in
{
  imports = [
    inputs.tabarr.nixosModules.default
    inputs.agenix.nixosModules.default
  ];

  services.tabarr = {
    enable = true;
    # Defaults: dataDir = "/var/lib/tabarr", with the library, music, state
    # and cache in it; schedule = "*-*-* 03:30". Keep the folders out of
    # /home and /tmp: the units' sandbox hides both, and the module refuses
    # such a path.
    settings = {
      # A long random topic: anyone who knows it can read it.
      ntfy.url = "https://ntfy.sh/tabarr-change-me";
    };
    credentials = {
      ntfy_token = config.age.secrets.tabarr-ntfy.path;
    };
  };

  # Sections 2 to 4 add age.secrets, Syncthing and restic here.
}
```

It refers to the `tabarr-ntfy` secret, so it evaluates once section 2 has
declared the secrets.

`settings` is `tabarr.toml`, as `src/tabarr/config.py` reads it, and unknown
keys are fatal there. The module adds `library_dir`, `music_dir`, `state_dir`
and `cache_dir` from its options: the library, the state and the cache are the
only places the sandbox lets tabarr write, and the music the only other one it
reads. The module rejects those keys and `data_dir` in `settings`, and names
the option to set instead. `systemctl cat tabarr` shows the generated file's
store path.

## 2. Secrets with agenix

Static secrets reach tabarr through systemd's `LoadCredential`: systemd reads
each file as root and hands the unit a private copy in
`$CREDENTIALS_DIRECTORY`. The secret files can stay root-only, which is
agenix's default. tabarr reads two credentials, `spotify_client_secret` and
`ntfy_token`; the nightly unit and `tabarr-admin` get them, and the auto-chords
unit, which reads neither, gets none. The Spotify token itself is not a static
secret: it lives in the state folder, written by `tabarr auth spotify`.

Add agenix, which the flake registry already knows as `agenix`:

```nix
    agenix.url = "github:ryantm/agenix";
    agenix.inputs.nixpkgs.follows = "nixpkgs";
    agenix.inputs.home-manager.follows = "home-manager";
    # No macOS here: drop that input instead of locking it.
    agenix.inputs.darwin.follows = "";
```

List who may decrypt what in `secrets/secrets.nix`:

```nix
# Who can decrypt each secret: you (to edit) and the NUC (its SSH host key).
let
  me = "ssh-ed25519 AAAA… me@laptop"; # ~/.ssh/id_ed25519.pub
  nuc = "ssh-ed25519 AAAA… root@nuc"; # ssh-keyscan -t ed25519 nuc
in
{
  "tabarr-spotify.age".publicKeys = [ me nuc ];
  "tabarr-ntfy.age".publicKeys = [ me nuc ];
}
```

Write each one (your `$EDITOR` opens; a trailing newline is fine, since tabarr
strips it):

```sh
cd /etc/nixos/secrets
nix run agenix -- -e tabarr-ntfy.age          # the ntfy access token, tk_…
nix run agenix -- -e tabarr-spotify.age       # only if you use Spotify (section 5)
nix run agenix -- -e restic-password.age
```

Then declare them in `hosts/nuc/tabarr.nix`:

```nix
  age.secrets = {
    tabarr-ntfy.file = ../../secrets/tabarr-ntfy.age;
    tabarr-spotify.file = ../../secrets/tabarr-spotify.age;
    restic-password.file = ../../secrets/restic-password.age;
  };
```

`credentials` takes only paths outside the store, such as
`config.age.secrets.<name>.path` (`/run/agenix/<name>`). A path literal like
`./token` would be copied into the world-readable store, so the module rejects
it.

The failure notice comes from `tabarr-notify-failure.service`. It adds the
bearer token when `credentials.ntfy_token` is set, and when
`settings.ntfy.url` is unset it logs that nothing was sent and succeeds.

## 3. Syncthing for the library and the music

The library is shared through the `tabarr` group. The module creates the
library as `tabarr:tabarr`, mode 2775, and `dataDir`, if it is missing, as
`tabarr:tabarr`, mode 0710: the group gets through to the library and the
music, while the state and the cache, mode 0700, stay tabarr's. The setgid bit
keeps everything created in the library in group `tabarr`, and tabarr writes
with umask 0007, so its files are group-writable. Syncthing joins that group
and writes the same way.
Both directions then work: you drop Guitar Pro files into `_inbox/` on the
laptop and tabarr files them, and you edit `wanted.txt` on the phone.

```nix
  services.syncthing = {
    enable = true;
    # The GUI stays on localhost: ssh -L 8384:localhost:8384 nuc
    settings = {
      devices = {
        laptop.id = "…"; # on the laptop: syncthing --device-id
        phone.id = "…";
      };
      folders = {
        tabs = {
          path = tabarr.libraryDir;
          devices = [ "laptop" "phone" ];
          # New files get 0666 and 0777 minus Syncthing's umask (0007, below)
          # instead of the sender's mode bits. The laptop's 0644 would drop
          # the group write bit that tabarr needs to file the inbox and to
          # rewrite wanted.txt and overrides.toml.
          ignorePerms = true;
        };
        music = {
          path = tabarr.musicDir;
          devices = [ "laptop" ];
          ignorePerms = true;
        };
      };
    };
  };

  # Syncthing writes into tabarr's group-owned folders...
  users.users.syncthing.extraGroups = [ "tabarr" ];
  # ...as group-writable files: the unit's default umask is 0022.
  systemd.services.syncthing.serviceConfig.UMask = "0007";

  # Syncthing fills the music folder, and tabarr reads it through the group.
  systemd.tmpfiles.settings.tabarr-music.${tabarr.musicDir}.d = {
    user = "syncthing";
    group = "tabarr";
    mode = "2770";
  };
```

Group membership applies when a process starts, so restart Syncthing once
after the first switch: `sudo systemctl restart syncthing`. Over the tailnet
the devices can connect without opening ports, because `tailscale0` is a
trusted interface; if discovery does not find the laptop, give its device an
`addresses = [ "tcp://laptop:22000" ]`. On the laptop, Home Manager's
`services.syncthing.enable = true` is enough. On the phone, use Syncthing-Fork,
with the `tabs` folder as Send & Receive so that `wanted.txt` can be edited
there.

The state directory is not synced, and should not be: it holds the Spotify
token.

Keep `wanted.txt`, `overrides.toml` and the downloads in `_inbox/` regular
files on every device. Whoever can write to the library could point a
symbolic link at tabarr's private files, so tabarr refuses a link there
instead of following it, and the to-do page or the journal says so.

## 4. Backups with restic

Back up the state, the library and the music. The live database can be
mid-write at any moment, so `backupPrepareCommand` takes a consistent copy with
SQLite's online backup, and that copy is what gets backed up:

```nix
  services.restic.backups.tabarr = {
    initialize = true;
    # Any restic repository: a local disk, sftp:host:/path, rclone:…, s3:…
    repository = "/mnt/backup/restic/tabarr";
    passwordFile = config.age.secrets.restic-password.path;
    paths = [
      tabarr.stateDir
      tabarr.libraryDir
      tabarr.musicDir
    ];
    # The live database; tabarr-backup.sqlite stands in for it.
    exclude = [ "${tabarr.stateDir}/tabarr.sqlite*" ];
    # Guarded: before the first run there is no database, and sqlite3 would
    # create an empty, root-owned one that tabarr could not open.
    backupPrepareCommand = ''
      if [ -f ${tabarr.stateDir}/tabarr.sqlite ]; then
        ${lib.getExe' pkgs.sqlite "sqlite3"} ${tabarr.stateDir}/tabarr.sqlite ".backup ${tabarr.stateDir}/tabarr-backup.sqlite"
      fi
    '';
    # After the nightly run (03:30, up to 45 minutes late, about 30 long).
    timerConfig = {
      OnCalendar = "*-*-* 05:30";
      Persistent = true;
      RandomizedDelaySec = "30m";
    };
    pruneOpts = [
      "--keep-daily 7"
      "--keep-weekly 5"
      "--keep-monthly 12"
    ];
  };
```

To restore, stop the timer (`sudo systemctl stop tabarr.timer`), restore the
three paths with `restic-tabarr restore latest --target /`, then put the
database back (here in the default state folder):

```sh
sudo install -o tabarr -g tabarr -m 0600 \
  /var/lib/tabarr/state/tabarr-backup.sqlite /var/lib/tabarr/state/tabarr.sqlite
sudo systemctl start tabarr.timer
```

The cache is left out. Losing it costs only requests:
the index lives in the database, so nothing needs building again, and the
pages tabarr had cached are fetched again as songs need them, within the
nightly budget.

## 5. The first run

Switch to the new configuration (on the NUC, or from the laptop with
`nixos-rebuild switch --flake .#nuc --target-host nuc --sudo`).

**Build the index once.** It downloads Ultimate Guitar's 41 tab sitemaps, 10–20
seconds apart: about 70 MB and 10 minutes. After this, each night refreshes
only the newest ones.

```sh
sudo tabarr-admin index build
```

**Say what you want to learn.** `wanted.txt` sits in the library, so you can
edit it on the laptop or the phone. One song per line, as `Artist - Title`,
optionally followed by ` | Album` and/or ` | m:ss`; `#` starts a comment:

```
# Artist - Title | Album | m:ss
宋冬野 - 斑马斑马 | 安和桥北 | 4:13
Soda Stereo - De Música Ligera
```

The album and duration are optional; they make the lyrics lookup exact.
`sudo tabarr-admin add "宋冬野" "斑马斑马" --album "安和桥北" --duration 4:13`
appends the same line.

**Spotify, optionally.** Liked Songs and the playlists you name join
`wanted.txt` as sources. Without a client id the Spotify step is skipped
silently, so you can add it any time:

1. Create an app at developer.spotify.com (Development Mode; the owner needs
   Premium). Add the redirect URI `http://127.0.0.1:8888/callback` exactly:
   `localhost` is rejected.
2. Put the client secret in `tabarr-spotify.age` (section 2), and add to
   `services.tabarr`:

   ```nix
   settings.spotify = {
     client_id = "…"; # not a secret
     playlists = [ "Learn" ];
   };
   credentials.spotify_client_secret = config.age.secrets.tabarr-spotify.path;
   ```

3. Switch, then authorize:

   ```sh
   sudo tabarr-admin auth spotify
   ```

   Open the URL it prints on the laptop and log in. The browser then fails to
   load `http://127.0.0.1:8888/callback?code=…`, which is expected: copy that
   whole URL from the address bar and paste it back. The token is saved in
   the state folder. Refresh tokens expire after about six months; tabarr then
   sends an ntfy message, and you run this step again.

**Check the timer, and run once now:**

```sh
systemctl list-timers tabarr.timer        # the next start, 03:30 plus up to 45 min
sudo systemctl start tabarr.service       # a full run now; returns when it ends
journalctl -u tabarr.service -e           # what it did
```

Then read `_todo.md` in the library: setup problems first, if any, then
review items, partial sheets, the buy list, Guitar Pro pages to download by
hand, and provider health. A block or an exhausted budget is not a failure:
the run exits 0 and the song stays pending. Only an unexpected error, an
`overrides.toml` tabarr can't read, or a database it can't open fails the
unit, and that sends the ntfy message.

**`tabarr-admin`** runs any command as the units run it: a transient unit as
user `tabarr`, with the same state and cache directories, the same credentials,
library and music paths, the generated config, and the units' sandbox. Only
the network stays open, which `auth spotify` and `index build` need. Use it
for `auth spotify`, `index build`, `match --dry-run` and the like. It needs
sudo. A file you pass it must be readable by the `tabarr` user and sit where
the sandbox shows it: not under `/home`, `/root` or `/tmp`, which it hides, so
`index build --from` reads sitemaps from somewhere like `/srv/sitemaps`.

**One tabarr at a time.** The nightly run holds tabarr's lock, `tabarr.lock`
in the state folder, from start to end, and every command that asks
the sites for pages or writes the library holds it while it works. One
started meanwhile waits, and says which it waits for (`Another tabarr is
running (pid …: run); waiting for it to finish.`): a `tabarr-admin fetch`
started during the nightly run waits for it, and the run waits for a
`tabarr-admin index build`. `tabarr-admin review` takes the lock only after
your answers, so the run never waits for you, and `search`,
`match --dry-run` and `index stats` never wait. A command that waited for a
run that got blocked sends that site nothing: it is cooling down. Each
process's first request to a site also waits out the pause after the last
request any tabarr sent there, so a run that starts right after a command may
pause up to 20 seconds per site, and the 10–20 second pauses hold for the
machine, not per process. The lock goes with the process holding it, whatever
ends it.

## 6. Auto-chords

For a song nobody has charted, buy the track (DRM-free: the buy list on the
to-do page links Bandcamp, Qobuz and the iTunes Store), drop it into the music
folder on the laptop, and let a local model write `sheet (auto).txt`:

```nix
  services.tabarr.autochords.enable = true;
```

`tabarr-autochords.service` then starts after every successful
`tabarr.service` run (`OnSuccess=`). It runs `tabarr --config … autochords`
with the `autochords` package (torch, beat-this, librosa) as the same user, in
the same sandbox, except that it has no network at all (`PrivateNetwork`), no
credentials (it reads no secret), and may generate code
(`MemoryDenyWriteExecute` off, because PyTorch's CPU kernels
and librosa's numba compile at run time: with it on, every song fails, BTC with
"cannot allocate executable memory" as numba loads, and beat_this with "could
not create a primitive"). numba caches what it compiles in `numba` in the
cache folder, since the unit's home is read-only.

**What a run does.** It links new files in the music folder to your songs,
as the nightly run does, then writes an auto sheet for every song that has its
audio file, has no human sheet (`sheet.txt`), isn't ignored, and whose audio
changed since its last auto sheet. A sheet made before the song's lyrics
arrived is made once more when they do. Everything else is left alone, so a
night with no new purchases loads no model. Then it rewrites `_todo.md` and
`index.html`, which the nightly run wrote before it, so both show its sheets
and the purchases it couldn't read the same night. The PDF of a new auto
sheet comes with the next night's render. It holds tabarr's lock while it
works, as the nightly run does, so a `tabarr-admin` command started meanwhile
waits for it.

BTC finds the chords and beat_this the beats and bars. The chords then go over
LRCLIB's timed lyrics when LRCLIB's duration matches the file's within 2
seconds; otherwise the sheet is a chord chart by bars followed by the plain
lyrics, which is what 斑马斑马 gets (LRCLIB has no timed lyrics for it). The
sheet starts with "auto-generated, unverified", and the song counts as found.
Once a human sheet is kept for the song, auto-chords no longer touches it.
WAV, FLAC, Ogg and MP3 files are read with libsndfile, anything else (such as
the AAC in an iTunes Store `.m4a`) with torchaudio's FFmpeg. Expect about half
a minute per four-minute song on a NUC-class CPU, most of it beat tracking (an
estimate: on the laptop it takes about 7 seconds, 6 of them beat tracking).

**The model files ship with the package.** `nix/autochords.nix` fetches them
when the package is built, as fixed-output downloads:

- the BTC large-vocabulary weights (170 chord classes; MIT), from the
  BTC-ISMIR19 repository at a pinned commit;
- beat_this's `final0` checkpoint (MIT), from JKU's server, pinned by hash.

The `autochords` package's wrapper points `TABARR_BTC_WEIGHTS` and
`TABARR_BEAT_CHECKPOINT` at them, as defaults. To use other files, set
`services.tabarr.autochords.btcWeights` or `beatCheckpoint`, which go into the
unit's environment and win over the wrapper; `settings.autochords.btc_weights`
and `beat_checkpoint` win over both.

JKU publishes the checkpoint at an unversioned URL. If it ever moves, a machine
that already has the file in its store keeps building; elsewhere, add a copy of
the file under its store name, and Nix finds it by its hash:

```sh
cp final0.ckpt beat_this-final0.ckpt
nix-store --add-fixed sha256 beat_this-final0.ckpt
# /nix/store/vvm1q1xipnvz4a0yxh68nxd5zvf1s095-beat_this-final0.ckpt
```

To run it now, without waiting for the night, for instance right after
dropping in a purchase:

```sh
sudo systemctl start tabarr-autochords.service
journalctl -u tabarr-autochords.service -e
```

The command prints a count such as `auto-chords: 1 generated, 4 skipped,
0 failed`. A purchase it can't read, say because its file won't decode, fails
that song alone: the journal names it with the reason, the to-do page lists it
under "Auto-chords couldn't read these purchases", and it is tried again once
the file changes. The unit still exits 0, so a file that will never decode
doesn't alert you every night. Only a setup problem exits 1, so that ntfy
tells you: the model packages or model files missing, a model failing its test
tone, or a sheet that can't be written into the library. Missing model files
fail every song due, and the journal says so once. `sudo tabarr-admin
autochords` runs the same command with the `autochords` package when
auto-chords is enabled; the default package has no torch, and says so if
asked.

On the laptop, `nix develop .#autochords -c pytest -m autochords` runs the
model tests against the same model files. `nix flake check` builds both
packages, each running the test suite (the model tests aside) and then
`tabarr autochords` on the wrapped program, and evaluates the module.

## 7. Chinese sheets in the PDFs

ChordPro's built-in PDF fonts have no Chinese glyphs, so the packages' wrapper
points `TABARR_CJK_FONT` at lxgw-fusionkai's `FusionKaiJ-Regular.ttf`, a Kai
(brush-style) face. The choice is narrow with ChordPro 6.050.7:

- it cannot open `.ttc` collections, which is all nixpkgs ships of Noto CJK
  and Source Han Sans;
- its PDF library corrupts the glyph subsets it embeds from TrueType fonts
  with odd-length glyph records, which most CJK TTFs have (LXGW Neo XiHei and
  WenKai among them): the PDF shows blank glyphs, although its text can still
  be copied. tabarr refuses such a font with an error instead of writing that
  PDF.

FusionKaiJ has no odd-length records and gives PDFs of a few hundred KB. To
use another font, set `settings.cjk_font` to a single `.ttf` that passes the
same check, or to a CFF-based `.otf` (embedded whole, so the PDFs are larger),
or build the package with `tabarr.override { cjkFont = "…"; }`.

## When something is wrong

- **ntfy says a unit failed:** `journalctl -u tabarr.service -e` (or
  `tabarr-autochords.service`).
- **`_todo.md` leads with "overrides.toml can't be read":** the nightly run
  stopped before its first step. The error names the table and the entry; a
  table declared twice says to merge the two sections. Fix the file, then
  `sudo systemctl start tabarr.service`, or wait for the next night.
- **A command says the database "is at schema version N, but this tabarr
  knows up to M":** a newer tabarr migrated it, and an older one runs now,
  after a rollback say. Switch back to the newer tabarr, or restore the copy
  saved before the migration, `tabarr.sqlite.vM.bak` in the state folder,
  which the message names when it is there. Until then the commands that use
  the database exit 2, and so does the nightly unit.
- **A command waits with "Another tabarr is running":** the message names the
  process and what it is doing; the nightly run takes about half an hour.
- **Auto-chords can't read a purchase:** the to-do page lists it, with the
  error, and `journalctl -u tabarr-autochords.service` names it too.
  Re-download the file, or convert it (to FLAC, say) and replace the original:
  a changed file is tried again on the next run.
- **Syncthing reports "permission denied":** check that
  `ls -ld /var/lib/tabarr/library` (or your `libraryDir`) shows
  `drwxrwsr-x tabarr tabarr`, that the folders above it let group `tabarr`
  through, and that `id syncthing` lists `tabarr`. Restart Syncthing after the
  group change, and check that the folder has `ignorePerms`.
- **Nothing ran last night:** `systemctl list-timers tabarr.timer`. A missed
  start runs at the next boot, because the timer is persistent.
- **The hardening, scored:** `systemd-analyze security tabarr.service` gives
  1.4 ("OK"), and 1.0 for `tabarr-autochords.service`. What is left open is
  the network, which the run needs, and the group-writable umask, which
  Syncthing needs.
