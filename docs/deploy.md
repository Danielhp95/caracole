# Deploying tabarr on the NUC

tabarr ships a NixOS module (`nixosModules.default` in this flake). Enabled, it
gives the machine:

| What | Does |
|---|---|
| `tabarr.timer` | Starts the nightly run at 03:30, give or take 45 minutes, and catches up after downtime |
| `tabarr.service` | `tabarr --config <generated tabarr.toml> run`, a hardened oneshot as user `tabarr` |
| `tabarr-autochords.service` | Optional. Runs after each successful run, with no network at all |
| `tabarr-notify-failure.service` | POSTs to your ntfy topic when either unit fails |
| `tabarr-admin` | Runs any `tabarr` command as the units do: `sudo tabarr-admin auth spotify` |
| `/var/lib/tabarr` | The database and the Spotify token, readable by `tabarr` alone |
| `/var/cache/tabarr` | Every raw HTTP response, kept forever |
| `/srv/tabs` | The library: sheets, lyrics, guitar parts, `_todo.md`, `wanted.txt`, `overrides.toml` |
| `/srv/music` | Audio you bought, read-only, for auto-chords |

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
    # Defaults: libraryDir = "/srv/tabs"; musicDir = "/srv/music";
    # schedule = "*-*-* 03:30". Keep both directories out of /home: the
    # units' sandbox hides it, and the module refuses such a path.
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

`settings` is `tabarr.toml`, as `src/tabarr/config.py` reads it, and unknown
keys are fatal there. The module adds `library_dir` and `music_dir` from its
options. State and cache always live in `/var/lib/tabarr` and
`/var/cache/tabarr`, the only places the sandbox lets tabarr write besides the
library; the module rejects `settings.state_dir` and `settings.cache_dir`.
`systemctl cat tabarr` shows the generated file's store path.

## 2. Secrets with agenix

Static secrets reach tabarr through systemd's `LoadCredential`: systemd reads
each file as root and hands the unit a private copy in
`$CREDENTIALS_DIRECTORY`. The secret files can stay root-only, which is
agenix's default. tabarr reads two credentials, `spotify_client_secret` and
`ntfy_token`. The Spotify token itself is not a static secret: it lives in
`/var/lib/tabarr`, written by `tabarr auth spotify`.

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

The library is shared through the `tabarr` group. The module creates
`/srv/tabs` as `tabarr:tabarr`, mode 2775. The setgid bit keeps everything
created inside in group `tabarr`, and tabarr writes with umask 0007, so its
files are group-writable. Syncthing joins that group and writes the same way.
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
      "/var/lib/tabarr"
      tabarr.libraryDir
      tabarr.musicDir
    ];
    # The live database; tabarr-backup.sqlite stands in for it.
    exclude = [ "/var/lib/tabarr/tabarr.sqlite*" ];
    # Guarded: before the first run there is no database, and sqlite3 would
    # create an empty, root-owned one that tabarr could not open.
    backupPrepareCommand = ''
      if [ -f /var/lib/tabarr/tabarr.sqlite ]; then
        ${lib.getExe' pkgs.sqlite "sqlite3"} /var/lib/tabarr/tabarr.sqlite ".backup /var/lib/tabarr/tabarr-backup.sqlite"
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
database back:

```sh
sudo install -o tabarr -g tabarr -m 0600 \
  /var/lib/tabarr/tabarr-backup.sqlite /var/lib/tabarr/tabarr.sqlite
sudo systemctl start tabarr.timer
```

The cache in `/var/cache/tabarr` is left out. Losing it costs one
`tabarr index build` and some re-fetching, within the nightly budget.

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
   `/var/lib/tabarr`. Refresh tokens expire after about six months; tabarr then
   sends an ntfy message, and you run this step again.

**Check the timer, and run once now:**

```sh
systemctl list-timers tabarr.timer        # the next start, 03:30 plus up to 45 min
sudo systemctl start tabarr.service       # a full run now; returns when it ends
journalctl -u tabarr.service -e           # what it did
```

Then read `_todo.md` in the library: review items, partial sheets, the buy
list, Guitar Pro pages to download by hand, and provider health. A block or an
exhausted budget is not a failure: the run exits 0 and the song stays pending.
Only an unexpected error fails the unit, and that sends the ntfy message.

**`tabarr-admin`** runs any command as the units run it: a transient unit as
user `tabarr`, with the same state and cache directories, the same credentials
and the generated config. Use it for `auth spotify`, `index build`,
`match --dry-run` and the like. It needs sudo, and a file you pass it must be
readable by the `tabarr` user.

## 6. Auto-chords

For a song nobody has charted, buy the track, drop it into the music folder
on the laptop, and let a local model write `sheet (auto).txt`:

```nix
  services.tabarr.autochords.enable = true;
```

`tabarr-autochords.service` then starts after every successful
`tabarr.service` run (`OnSuccess=`). It runs `tabarr --config … autochords`
with the `autochords` package (torch, beat-this, librosa) as the same user, in
the same sandbox, except that it has no network at all (`PrivateNetwork`) and
may generate code (`MemoryDenyWriteExecute` off, for PyTorch's CPU kernels).
It only touches songs whose audio is new.

The flake's `autochords` package is meant to point at the model files itself
(fixed-output downloads, `nix/autochords.nix`). To use other files, or until
it does, set `services.tabarr.autochords.btcWeights` and `beatCheckpoint`
(and `btcConfig` if needed). They become `TABARR_BTC_WEIGHTS`,
`TABARR_BEAT_CHECKPOINT` and `TABARR_BTC_CONFIG`, and `settings.autochords`
still overrides them.

To run it now, without waiting for the night:

```sh
sudo systemctl start tabarr-autochords.service
journalctl -u tabarr-autochords.service -e
```

## When something is wrong

- **ntfy says a unit failed:** `journalctl -u tabarr.service -e` (or
  `tabarr-autochords.service`).
- **Syncthing reports "permission denied":** check that `ls -ld /srv/tabs`
  shows `drwxrwsr-x tabarr tabarr`, and that `id syncthing` lists `tabarr`.
  Restart Syncthing after the group change, and check that the folder has
  `ignorePerms`.
- **Nothing ran last night:** `systemctl list-timers tabarr.timer`. A missed
  start runs at the next boot, because the timer is persistent.
- **The hardening, scored:** `systemd-analyze security tabarr.service` gives
  1.4 ("OK"), and 1.0 for `tabarr-autochords.service`. What is left open is
  the network, which the run needs, and the group-writable umask, which
  Syncthing needs.
