# Deploying caracole on the NUC

caracole ships a NixOS module (`nixosModules.default` in this flake). Enabled, it
gives the machine:

| What | Does |
|---|---|
| `caracole.timer` | Starts the nightly run at 03:30, up to 45 minutes late, and catches up after downtime |
| `caracole.service` | `caracole --config <generated caracole.toml> run`, a hardened oneshot as user `caracole` |
| `caracole-autochords.service` | Optional. After each successful run, writes `sheet (auto).txt` from audio you bought, with no network at all |
| `caracole-web.service` | Optional. `caracole serve`: the library page over HTTP, with a form to request songs and fetch them now (section 8) |
| `caracole-notify-failure.service` | POSTs to your ntfy topic when one of the units fails |
| `caracole-admin` | Runs any `caracole` command as the units do: `sudo caracole-admin auth spotify` |
| `/var/lib/caracole/state` | The database, the Spotify token and caracole's lock, readable by `caracole` alone |
| `/var/lib/caracole/cache` | Every raw HTTP response, kept forever, and the private folders PDFs are made in |
| `/var/lib/caracole/library` | The library: sheets, lyrics, guitar parts, `_todo.md`, `wanted.txt`, `overrides.toml` |
| `/var/lib/caracole/music` | Audio you bought, read-only, for auto-chords |

The four folders sit in `services.caracole.dataDir`, `/var/lib/caracole` unless
you set it, say to `/data/caracole` on a data disk. `stateDir`, `cacheDir`,
`libraryDir` and `musicDir` each put one elsewhere.

The rest of this page sets that up in `/etc/nixos`, which has no NUC host
yet. The snippets follow that repository's conventions: a module is on because
it is imported, inputs follow `nixpkgs`, and comments say why.

## 1. Add the flake and a host

In `/etc/nixos/flake.nix`, add the input:

```nix
    # The chord sheet library; nixosModules.default runs it nightly (hosts/nuc).
    caracole.url = "github:Danielhp95/caracole";
    caracole.inputs.nixpkgs.follows = "nixpkgs";
```

Once the repository has a remote, point `caracole.url` there instead. A commit
in `~/Projects/caracole` reaches a rebuild only after `nix flake update caracole`.

Then add the host to the list: `nixpkgs.lib.genAttrs [ "laptop" "nuc" ]`. The
flake passes every host its `facts.nix`, so the NUC needs one, even an empty
`{ }`.

The shared `nixos/` list is the desktop: Home Manager, the greeter, audio. A
headless NUC imports only what it needs:

```nix
# hosts/nuc/default.nix
# The NUC: headless, on the tailnet, running caracole (./caracole.nix).
{ hostName, ... }:
{
  imports = [
    ./hardware.nix # nixos-generate-config on the NUC
    ./caracole.nix
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
# hosts/nuc/caracole.nix
# caracole (~/Projects/caracole): the nightly chord sheet library, its secrets,
# Syncthing for the library and the music, and restic.
{
  config,
  inputs,
  lib,
  pkgs,
  ...
}:
let
  caracole = config.services.caracole;
in
{
  imports = [
    inputs.caracole.nixosModules.default
    inputs.agenix.nixosModules.default
  ];

  services.caracole = {
    enable = true;
    # Defaults: dataDir = "/var/lib/caracole", with the library, music, state
    # and cache in it; schedule = "*-*-* 03:30". Keep the folders out of
    # /home and /tmp: the units' sandbox hides both, and the module refuses
    # such a path.
    settings = {
      # A long random topic: anyone who knows it can read it.
      ntfy.url = "https://ntfy.sh/caracole-change-me";
    };
    credentials = {
      ntfy_token = config.age.secrets.caracole-ntfy.path;
    };
  };

  # Sections 2 to 4 add age.secrets, Syncthing and restic here.
}
```

It refers to the `caracole-ntfy` secret, so it evaluates once section 2 has
declared the secrets.

`settings` is `caracole.toml`, as `src/caracole/config.py` reads it, and unknown
keys are fatal there. The module adds `library_dir`, `music_dir`, `state_dir`
and `cache_dir` from its options: the library, the state and the cache are the
only places the sandbox lets caracole write, and the music the only other one it
reads. The module rejects those keys and `data_dir` in `settings`, and names
the option to set instead. `systemctl cat caracole` shows the generated file's
store path.

## 2. Secrets with agenix

Static secrets reach caracole through systemd's `LoadCredential`: systemd reads
each file as root and hands the unit a private copy in
`$CREDENTIALS_DIRECTORY`. The secret files can stay root-only, which is
agenix's default. caracole reads three credentials, `spotify_client_secret`,
`ntfy_token` and `web_token` (caracole-web's access token, section 8); the
nightly unit and `caracole-admin` get them, caracole-web gets `web_token`
alone, and the auto-chords unit, which reads none, gets none. The Spotify token itself is not a static
secret: it lives in the state folder, written by `caracole auth spotify`.

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
  "caracole-spotify.age".publicKeys = [ me nuc ];
  "caracole-ntfy.age".publicKeys = [ me nuc ];
}
```

Write each one (your `$EDITOR` opens; a trailing newline is fine, since caracole
strips it):

```sh
cd /etc/nixos/secrets
nix run agenix -- -e caracole-ntfy.age          # the ntfy access token, tk_…
nix run agenix -- -e caracole-spotify.age       # only if you use Spotify (section 5)
nix run agenix -- -e restic-password.age
```

Then declare them in `hosts/nuc/caracole.nix`:

```nix
  age.secrets = {
    caracole-ntfy.file = ../../secrets/caracole-ntfy.age;
    caracole-spotify.file = ../../secrets/caracole-spotify.age;
    restic-password.file = ../../secrets/restic-password.age;
  };
```

`credentials` takes only paths outside the store, such as
`config.age.secrets.<name>.path` (`/run/agenix/<name>`). A path literal like
`./token` would be copied into the world-readable store, so the module rejects
it.

The failure notice comes from `caracole-notify-failure.service`. It adds the
bearer token when `credentials.ntfy_token` is set, and when
`settings.ntfy.url` is unset it logs that nothing was sent and succeeds.

## 3. Syncthing for the library and the music

The library is shared through the `caracole` group. The module creates the
library as `caracole:caracole`, mode 2775, and `dataDir`, if it is missing, as
`caracole:caracole`, mode 0710: the group gets through to the library and the
music, while the state and the cache, mode 0700, stay caracole's. The setgid bit
keeps everything created in the library in group `caracole`, and caracole writes
with umask 0007, so its files are group-writable. Syncthing joins that group
and writes the same way.
Both directions then work: you drop Guitar Pro files and MuseScore scores into
`_inbox/` on the laptop and caracole files them, and you edit `wanted.txt` on
the phone.

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
          path = caracole.libraryDir;
          devices = [ "laptop" "phone" ];
          # New files get 0666 and 0777 minus Syncthing's umask (0007, below)
          # instead of the sender's mode bits. The laptop's 0644 would drop
          # the group write bit that caracole needs to file the inbox and to
          # rewrite wanted.txt and overrides.toml.
          ignorePerms = true;
        };
        music = {
          path = caracole.musicDir;
          devices = [ "laptop" ];
          ignorePerms = true;
        };
      };
    };
  };

  # Syncthing writes into caracole's group-owned folders...
  users.users.syncthing.extraGroups = [ "caracole" ];
  # ...as group-writable files: the unit's default umask is 0022.
  systemd.services.syncthing.serviceConfig.UMask = "0007";

  # Syncthing fills the music folder, and caracole reads it through the group.
  systemd.tmpfiles.settings.caracole-music.${caracole.musicDir}.d = {
    user = "syncthing";
    group = "caracole";
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

Keep `wanted.txt`, `overrides.toml`, `_inbox/` and the downloads in it
regular files and folders on every device. Whoever can write to the library
could point a symbolic link at caracole's private files, so caracole refuses a
link there instead of following it, and the to-do page or the journal says
so; through an `_inbox` that is a link, nothing is filed or deleted. The
sheets, tabs, PDFs and sheet viewers caracole keeps are its own: one deleted, edited or
replaced on a device is written again at the next run, so keep your
annotations in a copy under another name.

## 4. Backups with restic

Back up the state, the library and the music. The live database can be
mid-write at any moment, so `backupPrepareCommand` takes a consistent copy with
SQLite's online backup, and that copy is what gets backed up:

```nix
  services.restic.backups.caracole = {
    initialize = true;
    # Any restic repository: a local disk, sftp:host:/path, rclone:…, s3:…
    repository = "/mnt/backup/restic/caracole";
    passwordFile = config.age.secrets.restic-password.path;
    paths = [
      caracole.stateDir
      caracole.libraryDir
      caracole.musicDir
    ];
    # The live database; caracole-backup.sqlite stands in for it.
    exclude = [ "${caracole.stateDir}/caracole.sqlite*" ];
    # Guarded: before the first run there is no database, and sqlite3 would
    # create an empty, root-owned one that caracole could not open.
    backupPrepareCommand = ''
      if [ -f ${caracole.stateDir}/caracole.sqlite ]; then
        ${lib.getExe' pkgs.sqlite "sqlite3"} ${caracole.stateDir}/caracole.sqlite ".backup ${caracole.stateDir}/caracole-backup.sqlite"
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

To restore, stop the timer (`sudo systemctl stop caracole.timer`), restore the
three paths with `restic-caracole restore latest --target /`, then put the
database back (here in the default state folder):

```sh
sudo install -o caracole -g caracole -m 0600 \
  /var/lib/caracole/state/caracole-backup.sqlite /var/lib/caracole/state/caracole.sqlite
sudo systemctl start caracole.timer
```

The cache is left out. Losing it costs only requests:
the index lives in the database, so nothing needs building again, and the
pages caracole had cached are fetched again as songs need them, within the
nightly budget.

## 5. The first run

Switch to the new configuration (on the NUC, or from the laptop with
`nixos-rebuild switch --flake .#nuc --target-host nuc --sudo`).

**Build the index once.** It downloads Ultimate Guitar's 41 tab sitemaps, 10–20
seconds apart: about 70 MB and 10 minutes. After this, each night refreshes
only the newest ones.

```sh
sudo caracole-admin index build
```

gtptabs.com needs no build: the first nightly run reads its sitemaps, seven
of its 20 requests, and from then on each run downloads Guitar Pro files for
the songs that have none. To leave gtptabs.com out, set
`settings.providers.gtptabs.enabled = false;` in `services.caracole`.

MuseScore's song sitemaps are read the same way, ten requests a night, for the
to-do page's links to its pages. Its Cloudflare protection may answer with a
challenge, as it did in October 2026: that is a block, so ntfy says so once and
caracole leaves MuseScore alone for a day or more, doubling with each block in
a row. To leave MuseScore out, set `settings.providers.musescore.enabled = false;`.

**Say what you want to learn.** `wanted.txt` sits in the library, so you can
edit it on the laptop or the phone. One song per line, as `Artist - Title`,
optionally followed by ` | Album` and/or ` | m:ss`; `#` starts a comment:

```
# Artist - Title | Album | m:ss
宋冬野 - 斑马斑马 | 安和桥北 | 4:13
Soda Stereo - De Música Ligera
```

The album and duration are optional; they make the lyrics lookup exact.
`sudo caracole-admin add "宋冬野" "斑马斑马" --album "安和桥北" --duration 4:13`
appends the same line. `sudo caracole-admin remove "宋冬野 - 斑马斑马"` takes a
song out for good, its line and the files caracole wrote, until you add it
again ([usage.md](usage.md), "caracole remove").

**Spotify, optionally.** Liked Songs and the playlists you name join
`wanted.txt` as sources. Without a client id the Spotify step is skipped
silently, so you can add it any time:

1. Create an app at developer.spotify.com (Development Mode; the owner needs
   Premium). Add the redirect URI `http://127.0.0.1:8888/callback` exactly:
   `localhost` is rejected.
2. Put the client secret in `caracole-spotify.age` (section 2), and add to
   `services.caracole`:

   ```nix
   settings.spotify = {
     client_id = "…"; # not a secret
     playlists = [ "Learn" ];
   };
   credentials.spotify_client_secret = config.age.secrets.caracole-spotify.path;
   ```

3. Switch, then authorize:

   ```sh
   sudo caracole-admin auth spotify
   ```

   Open the URL it prints on the laptop and log in. The browser then fails to
   load `http://127.0.0.1:8888/callback?code=…`, which is expected: copy that
   whole URL from the address bar and paste it back. The token is saved in
   the state folder. Refresh tokens expire after about six months; caracole then
   sends an ntfy message, and you run this step again.

**Check the timer, and run once now:**

```sh
systemctl list-timers caracole.timer        # the next start, 03:30 plus up to 45 min
sudo systemctl start caracole.service       # a full run now; returns when it ends
journalctl -u caracole.service -e           # what it did
```

Then read `_todo.md` in the library: setup problems first, if any, then
review items, partial sheets, the buy list, the Guitar Pro files gtptabs.com
gave this week, Guitar Pro pages to download by hand, MuseScore pages to open
(or that MuseScore is blocking caracole), and provider health. A block or an
exhausted budget is not a failure:
the run exits 0 and the song stays pending. After a block, ntfy says until
when caracole leaves that site alone: the next night's run skips it, the next
two after a second block in a row, the next four after a third
([usage.md](usage.md#caracole-run)). Only an unexpected error, an
`overrides.toml` caracole can't read, or a database it can't open fails the
unit, and that sends the ntfy message.

**`caracole-admin`** runs any command as the units run it: a transient unit as
user `caracole`, with the same state and cache directories, the same credentials,
library and music paths, the generated config, and the units' sandbox. Only
the network stays open, which `auth spotify` and `index build` need. Use it
for `auth spotify`, `index build`, `match --dry-run` and the like. It needs
sudo. A file you pass it must be readable by the `caracole` user and sit where
the sandbox shows it: not under `/home`, `/root` or `/tmp`, which it hides, so
`index build --from` reads sitemaps from somewhere like `/srv/sitemaps`.

**One caracole at a time.** The nightly run holds caracole's lock, `caracole.lock`
in the state folder, from start to end, and every command that asks
the sites for pages or writes the library holds it while it works. One
started meanwhile waits, and says which it waits for (`Another caracole is
running (pid …: run); waiting for it to finish.`): a `caracole-admin fetch`
started during the nightly run waits for it, and the run waits for a
`caracole-admin index build`. `caracole-admin review` and `caracole-admin remove`
take the lock only after your answers, so the run never waits for you, and
`search`, `match --dry-run`, `index stats` and `remove --list` never wait. A command that waited for a
run that got blocked sends that site nothing: it is cooling down. Each
process's first request to a site also waits out the pause after the last
request any caracole sent there, so a run that starts right after a command may
pause up to 20 seconds per site, and the 10–20 second pauses hold for the
machine, not per process. The lock goes with the process holding it, whatever
ends it.

## 6. Auto-chords

For a song nobody has charted, buy the track (DRM-free: the buy list on the
to-do page links Bandcamp, Qobuz and the iTunes Store), drop it into the music
folder on the laptop, and let a local model write `sheet (auto).txt`:

```nix
  services.caracole.autochords.enable = true;
```

`caracole-autochords.service` then starts after every successful
`caracole.service` run (`OnSuccess=`). It runs `caracole --config … autochords`
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
sheet comes with the next night's render. It holds caracole's lock while it
works, as the nightly run does, so a `caracole-admin` command started meanwhile
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

The `autochords` package's wrapper points `CARACOLE_BTC_WEIGHTS` and
`CARACOLE_BEAT_CHECKPOINT` at them, as defaults. To use other files, set
`services.caracole.autochords.btcWeights` or `beatCheckpoint`, which go into the
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
sudo systemctl start caracole-autochords.service
journalctl -u caracole-autochords.service -e
```

The command prints a count such as `auto-chords: 1 generated, 4 skipped,
0 failed`. A purchase it can't read, say because its file won't decode, fails
that song alone: the journal names it with the reason, the to-do page lists it
under "Auto-chords couldn't read these purchases", and it is tried again once
the file changes. The unit still exits 0, so a file that will never decode
doesn't alert you every night. Only a setup problem exits 1, so that ntfy
tells you: the model packages or model files missing, a model failing its test
tone, or a sheet that can't be written into the library. Missing model files
fail every song due, and the journal says so once. `sudo caracole-admin
autochords` runs the same command with the `autochords` package when
auto-chords is enabled; the default package has no torch, and says so if
asked.

On the laptop, `nix develop .#autochords -c pytest -m autochords` runs the
model tests against the same model files. `nix flake check` builds both
packages, each running the test suite (the model tests aside) and then
`caracole autochords` on the wrapped program, and evaluates the module.

## 7. Chinese sheets in the PDFs

ChordPro's built-in PDF fonts have no Chinese glyphs, so the packages' wrapper
points `CARACOLE_CJK_FONT` at lxgw-fusionkai's `FusionKaiJ-Regular.ttf`, a Kai
(brush-style) face. The choice is narrow with ChordPro 6.050.7:

- it cannot open `.ttc` collections, which is all nixpkgs ships of Noto CJK
  and Source Han Sans;
- its PDF library corrupts the glyph subsets it embeds from TrueType fonts
  with odd-length glyph records, which most CJK TTFs have (LXGW Neo XiHei and
  WenKai among them): the PDF shows blank glyphs, although its text can still
  be copied. caracole refuses such a font with an error instead of writing that
  PDF.

FusionKaiJ has no odd-length records and gives PDFs of a few hundred KB. To
use another font, set `settings.cjk_font` to a single `.ttf` that passes the
same check, or to a CFF-based `.otf` (embedded whole, so the PDFs are larger),
or build the package with `caracole.override { cjkFont = "…"; }`. The sheet
viewers (`sheet.html`) need no font file: the phone's browser draws them with
its own fonts, so a Chinese sheet has one even while its PDF waits for a font.

## 8. The library page over HTTP

`services.caracole.web` runs `caracole serve` as `caracole-web.service`: the
library page, a form to request songs, a Fetch now button on each wanted
song, a picker on each song that needs review, and a Remove… button on each
card, which asks first ([usage.md](usage.md), "caracole serve"). A request
runs caracole commands
in the unit, one at a time and each under caracole's lock, so the unit has the
nightly run's sandbox, folders and network. Of the credentials it gets
`web_token` alone: neither the server nor the commands it runs read Spotify or
ntfy. It starts at boot and restarts when it fails.

On the tailnet, with an access token:

```nix
  services.caracole = {
    web = {
      enable = true;
      # The NUC's tailnet address (tailscale ip -4). The default, 127.0.0.1,
      # is the NUC alone: reach it with ssh -L 8737:127.0.0.1:8737 nuc.
      address = "100.64.0.7";
      # port = 8737;
      # The full MagicDNS name, if you browse to it; the short one, the host's
      # name, is allowed already.
      allowedHosts = [ "nuc.example-tailnet.ts.net" ];
    };
    credentials.web_token = config.age.secrets.caracole-web-token.path;
  };
  age.secrets.caracole-web-token.file = ../../secrets/caracole-web-token.age;
```

Make the token with `openssl rand -base64 24` and store it with
`nix run agenix -- -e caracole-web-token.age`, after adding that file to
`secrets/secrets.nix`. Each browser asks for it once and remembers it.

- **Who can reach it.** It answers to an IP address and only to the names it
  knows (localhost, the host's name and its `.local` name, and
  `allowedHosts`), so no other site can reach it under a name of its own, and
  a form is refused unless it comes from its own page. A tailnet whose interface is trusted needs no firewall opening; for a
  LAN address, set `web.openFirewall = true` and keep the token: anyone on
  the LAN could otherwise read the library and request songs. An address
  beyond this machine without `credentials.web_token` gets a warning when the
  system builds.
- **At boot.** A tailnet address may not exist when the unit starts; it fails
  and tries again every 10 seconds, with no ntfy alert for each try
  (`RestartMode=direct`). A fault that lasts, such as the port in use or the
  address gone, stops it after 30 starts in 10 minutes, about 5 minutes of
  tries: then the unit is `failed`, ntfy says so once, and
  `sudo systemctl restart caracole-web` starts it again once it's fixed.
- **Politeness.** The server sends no request of its own. Fetch now runs
  `caracole match`, `caracole fetch --song` and `caracole render`, which wait
  behind a nightly run, keep the pauses between requests and the budgets, and
  leave a site alone while it cools down. A pick runs `caracole review --song`
  first, which writes overrides.toml in the library, under the same lock.
  The song's card says how it goes, on one line; `/jobs` keeps what each
  command printed, at `-v`.

## Logs

The units write to the journal: the run's summary from stdout, the log from
stderr. caracole starts each line of both with its syslog priority, which
journald files the line under, and adds no timestamp, as the journal keeps
its own:

| Priority | Lines |
|---|---|
| 3, `err` | an error a command stops on; a bug, its traceback included, and its line in the summary |
| 4, `warning` | a problem: a site that failed, a file caracole couldn't read; and the summary's lines that need you or say what went wrong |
| 6, `info` | the rest of the summary: what each step did, the requests, the time; with `-v`, caracole's information |
| 7, `debug` | with `-vv`: debugging, and the libraries' own logs |

```sh
journalctl -u caracole -p warning     # only what needs you or went wrong
journalctl -u caracole -b -o cat      # the lines as caracole wrote them, the summary among them
sudo caracole-admin -v run            # a run now, a line per request, on the terminal
```

The run exits 0 after a block, a cooldown or a spent budget, and 1 for a bug
(the unit fails, and its `OnFailure` sends the ntfy alert); see
[usage.md](usage.md#caracole-run) for every status.

No secret reaches the journal, at any priority (see
[usage.md](usage.md#what-caracole-prints)).

## When something is wrong

- **ntfy says a unit failed:** `journalctl -u caracole.service -e` (or
  `caracole-autochords.service`).
- **`_todo.md` leads with "overrides.toml can't be read":** the nightly run
  stopped before its first step. The error names the table and the entry; a
  table declared twice says to merge the two sections.
  `can't read it: Permission denied` means the `caracole` user may not read the
  file: give it group `caracole` and `chmod g+rw`. `line N is not valid UTF-8`
  means an editor saved it in another encoding: save it as UTF-8. Fix the
  file, then `sudo systemctl start caracole.service`, or wait for the next
  night.
- **ntfy says a site blocked caracole** ("caracole: Ultimate Guitar blocked"): nothing to do,
  and nothing to work around. The message says until when caracole leaves the
  site alone, and the to-do page's Provider health shows it too. Nothing was
  marked not found: the songs wait for a run after that.
- **A power cut during the night:** nothing to clean up. A file caracole was
  replacing is the old one or the new one, never an empty one, and the next
  run writes again any sheet, tab or PDF that isn't as caracole wrote it.
- **A command says the database "is at schema version N, but this caracole
  knows up to M":** a newer caracole migrated it, and an older one runs now,
  after a rollback say. Switch back to the newer caracole, or restore the copy
  saved before the migration, `caracole.sqlite.vM.bak` in the state folder,
  which the message names when it is there. Until then the commands that use
  the database exit 2, and so does the nightly unit.
- **A command waits with "Another caracole is running":** the message names the
  process and what it is doing; the nightly run takes about half an hour.
- **Auto-chords can't read a purchase:** the to-do page lists it, with the
  error, and `journalctl -u caracole-autochords.service` names it too.
  Re-download the file, or convert it (to FLAC, say) and replace the original:
  a changed file is tried again on the next run.
- **Syncthing reports "permission denied":** check that
  `ls -ld /var/lib/caracole/library` (or your `libraryDir`) shows
  `drwxrwsr-x caracole caracole`, that the folders above it let group `caracole`
  through, and that `id syncthing` lists `caracole`. Restart Syncthing after the
  group change, and check that the folder has `ignorePerms`.
- **The web page doesn't load:** `journalctl -u caracole-web.service -e`.
  "can't listen on" names the address and why; "421" in a browser means it
  reached the server under a name it doesn't answer to: add the name to
  `web.allowedHosts`. A form refused as "older than the server", or a card
  that says "caracole serve has restarted since this page was opened", was
  opened before the unit last restarted: reload the page.
- **Nothing ran last night:** `systemctl list-timers caracole.timer`. A missed
  start runs at the next boot, because the timer is persistent.
- **The hardening, scored:** `systemd-analyze security caracole.service` gives
  1.4 ("OK"), and 1.0 for `caracole-autochords.service`. What is left open is
  the network, which the run needs, and the group-writable umask, which
  Syncthing needs.
