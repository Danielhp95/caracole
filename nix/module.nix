# services.tabarr: a nightly `tabarr run` as a hardened oneshot on a timer, an
# optional auto-chords unit after it with no network, an ntfy message when
# either fails, and `tabarr-admin` for the interactive commands. Everything
# tabarr keeps sits in one folder, dataDir, unless an option moves a part.
{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.tabarr;
  toml = pkgs.formats.toml { };
  configFile = toml.generate "tabarr.toml" cfg.settings;

  credentials = lib.mapAttrsToList (name: path: "${name}:${path}") cfg.credentials;

  # The four folders by option, and dataDir, which holds them by default.
  folders = [
    "libraryDir"
    "musicDir"
    "stateDir"
    "cacheDir"
  ];
  dirs = [ "dataDir" ] ++ folders;
  # The tabarr.toml key of each.
  keys = {
    dataDir = "data_dir";
    libraryDir = "library_dir";
    musicDir = "music_dir";
    stateDir = "state_dir";
    cacheDir = "cache_dir";
  };
  # The folders as the generated tabarr.toml names them: the paths the units'
  # sandbox opens. Not data_dir, which these four would win over.
  dirSettings = lib.listToAttrs (map (name: lib.nameValuePair keys.${name} cfg.${name}) folders);

  inside = parent: dir: lib.hasPrefix "${parent}/" dir;
  # Options with their paths, one per line, for a message.
  listed = lib.concatMapStrings (name: "\n  ${name} = \"${cfg.${name}}\";");

  # What tabarr writes. The hardened units may write there and nowhere else.
  writable = [
    cfg.libraryDir
    cfg.stateDir
    cfg.cacheDir
  ];

  # Hardening every unit here shares: plan §6 plus the usual extras. RemoveIPC
  # is left out because the tabarr units and tabarr-admin share one user.
  sandbox = {
    NoNewPrivileges = true;
    ProtectSystem = "strict";
    ProtectHome = true;
    PrivateTmp = true;
    PrivateDevices = true;
    PrivateMounts = true;
    ProtectProc = "invisible";
    ProtectKernelTunables = true;
    ProtectKernelModules = true;
    ProtectKernelLogs = true;
    ProtectControlGroups = true;
    ProtectClock = true;
    ProtectHostname = true;
    RestrictAddressFamilies = [
      "AF_INET"
      "AF_INET6"
      "AF_UNIX"
    ];
    RestrictNamespaces = true;
    RestrictRealtime = true;
    RestrictSUIDSGID = true;
    MemoryDenyWriteExecute = true;
    LockPersonality = true;
    SystemCallArchitectures = "native";
    SystemCallFilter = [
      "@system-service"
      "~@privileged"
    ];
    SystemCallErrorNumber = "EPERM";
    CapabilityBoundingSet = "";
  };

  # Who tabarr runs as: both units and tabarr-admin.
  identity = {
    User = "tabarr";
    Group = "tabarr";
    # The files it writes are group-writable: Syncthing, in group tabarr, syncs
    # the library both ways (the inbox, edits from a phone). The database and
    # the Spotify token stay with the tabarr user alone, in a folder of mode
    # 0700.
    UMask = "0007";
  };

  # The static secrets, for the nightly run and tabarr-admin (`auth spotify`,
  # `sync`). The auto-chords unit reads none, so it gets none.
  secrets.LoadCredential = credentials;

  # No StateDirectory or CacheDirectory: systemd keeps those in /var/lib and
  # /var/cache only, so tmpfiles creates the folders and the state and cache
  # are opened like the library.
  paths = {
    ReadWritePaths = writable;
    # "-": the music folder may not exist yet.
    ReadOnlyPaths = [ "-${cfg.musicDir}" ];
  };

  # HOME (/var/empty) is read-only, and librosa's numba refuses to import
  # without a writable cache ("no locator available"); torch caches there too.
  # tabarr's own cache is cache_dir in the generated file, which wins over these.
  cacheEnv = {
    XDG_CACHE_HOME = cfg.cacheDir;
    NUMBA_CACHE_DIR = "${cfg.cacheDir}/numba";
  };

  # The model files for auto-chords. Null ones stay unset, so the package
  # wrapper's --set-default values apply; settings.autochords wins over both.
  modelEnv = lib.filterAttrs (_: value: value != null) {
    TABARR_BTC_WEIGHTS = cfg.autochords.btcWeights;
    TABARR_BEAT_CHECKPOINT = cfg.autochords.beatCheckpoint;
  };

  ntfyUrl = cfg.settings.ntfy.url or "";

  notifyFailure = pkgs.writeShellApplication {
    name = "tabarr-notify-failure";
    runtimeInputs = [ pkgs.curl ];
    text = ''
      url=${lib.escapeShellArg ntfyUrl}
      if [ -z "$url" ]; then
        echo "a tabarr unit failed; ntfy is not configured (services.tabarr.settings.ntfy.url), so nothing was sent"
        exit 0
      fi

      # systemd sets MONITOR_* for a unit started through OnFailure=.
      unit=''${MONITOR_UNIT:-tabarr.service}
      result=''${MONITOR_SERVICE_RESULT:-failed}
      args=(
        --silent --show-error --fail-with-body --max-time 30 --retry 3
        --header "Title: tabarr: $unit failed"
        --header "Priority: high"
        --header "Tags: warning"
        --data-binary "$unit failed on ${config.networking.hostName} ($result). See: journalctl -u $unit"
      )

      token_file=''${CREDENTIALS_DIRECTORY:-/nonexistent}/ntfy_token
      if [ -r "$token_file" ]; then
        # As curl config on stdin, so the token never shows in a process list.
        printf 'header = "Authorization: Bearer %s"\n' "$(< "$token_file")" \
          | curl --config - "''${args[@]}" "$url"
      else
        curl "''${args[@]}" "$url"
      fi
    '';
  };

  # tabarr as its units run it, for `auth spotify`, `index build` and one-off
  # commands: a transient unit under the tabarr user, in the units' sandbox,
  # with the same folders, credentials and generated config. It keeps the
  # network (`auth spotify` and `index build` need it). With the auto-chords
  # package when that is on, so `tabarr-admin autochords` works too, and then,
  # as in that unit, without MemoryDenyWriteExecute.
  adminPackage = if cfg.autochords.enable then cfg.autochords.package else cfg.package;
  adminEnv = {
    TABARR_CONFIG = configFile;
  }
  // cacheEnv
  // lib.optionalAttrs cfg.autochords.enable modelEnv;
  adminProperties =
    sandbox
    // identity
    // secrets
    // paths
    // {
      # As the units: started once the folders' file systems are mounted.
      RequiresMountsFor = writable;
    }
    // lib.optionalAttrs cfg.autochords.enable { MemoryDenyWriteExecute = false; };
  # One --property per list item, as a unit file gets one line per item (for
  # SystemCallFilter, the order is the units' too); booleans as yes or no.
  property =
    name: value:
    map (v: "--property=${name}=${if lib.isBool v then (if v then "yes" else "no") else toString v}") (
      lib.toList value
    );
  adminArgs =
    lib.mapAttrsToList (name: value: "--setenv=${name}=${value}") adminEnv
    ++ lib.concatLists (lib.mapAttrsToList property adminProperties);
  tabarrAdmin = pkgs.writeShellApplication {
    name = "tabarr-admin";
    runtimeInputs = [ config.systemd.package ];
    text = ''
      if [ "$EUID" -ne 0 ]; then
        echo "tabarr-admin starts a system unit as the tabarr user: run it with sudo" >&2
        exit 1
      fi
      # --pty on a terminal (auth spotify asks for a pasted URL), --pipe otherwise.
      exec systemd-run --quiet --collect --wait --pty --pipe \
        ${lib.escapeShellArgs adminArgs} \
        -- ${lib.getExe adminPackage} "$@"
    '';
  };
in
{
  options.services.tabarr = {
    enable = lib.mkEnableOption "tabarr, the nightly chord sheet, lyrics and guitar part library";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ./package.nix { };
      defaultText = lib.literalExpression "pkgs.callPackage ./package.nix { }";
      description = "The tabarr package. The flake's module sets it to the flake's build.";
    };

    dataDir = lib.mkOption {
      # A string, as are the folders below, so it is never copied to the store.
      type = lib.types.str;
      default = "/var/lib/tabarr";
      example = "/data/tabarr";
      description = ''
        The folder that holds everything tabarr keeps: `library`, `music`,
        `state` and `cache`, unless libraryDir, musicDir, stateDir or cacheDir
        puts one elsewhere. When missing, it is created as `tabarr:tabarr`, mode
        0710, so that the group gets through to the library and the music. An
        existing folder keeps its owner and mode, so it can be one that other
        things share, such as a disk's root; it must then let `tabarr` and its
        group through.
      '';
    };

    libraryDir = lib.mkOption {
      type = lib.types.str;
      default = "${cfg.dataDir}/library";
      defaultText = lib.literalExpression ''"''${config.services.tabarr.dataDir}/library"'';
      description = ''
        The library tabarr writes: sheets, lyrics, guitar parts, `_todo.md`,
        `wanted.txt` and `overrides.toml`. It is created setgid, group `tabarr`,
        mode 2775, so a Syncthing user in that group can share it.
      '';
    };

    musicDir = lib.mkOption {
      type = lib.types.str;
      default = "${cfg.dataDir}/music";
      defaultText = lib.literalExpression ''"''${config.services.tabarr.dataDir}/music"'';
      description = ''
        Purchased audio, read-only, for auto-chords. It may not exist yet:
        whoever fills it creates it.
      '';
    };

    stateDir = lib.mkOption {
      type = lib.types.str;
      default = "${cfg.dataDir}/state";
      defaultText = lib.literalExpression ''"''${config.services.tabarr.dataDir}/state"'';
      description = ''
        The database, the Spotify token and tabarr's lock: back it up, but don't
        share it. It is created as `tabarr:tabarr`, mode 0700.
      '';
    };

    cacheDir = lib.mkOption {
      type = lib.types.str;
      default = "${cfg.dataDir}/cache";
      defaultText = lib.literalExpression ''"''${config.services.tabarr.dataDir}/cache"'';
      description = ''
        Every raw HTTP response, kept forever, the private folders PDFs are made
        in, and numba's and torch's caches. It is created as `tabarr:tabarr`,
        mode 0700. Losing it costs only requests.
      '';
    };

    schedule = lib.mkOption {
      type = lib.types.str;
      default = "*-*-* 03:30";
      description = "When `tabarr run` starts (systemd.time(7) calendar event), up to 45 minutes late.";
    };

    settings = lib.mkOption {
      inherit (toml) type;
      default = { };
      example = lib.literalExpression ''
        {
          spotify = {
            client_id = "0123456789abcdef";
            playlists = [ "Learn" ];
          };
          ntfy.url = "https://ntfy.sh/my-tabarr-topic";
          providers.ug.budget = 40;
        }
      '';
      description = ''
        tabarr.toml, as src/tabarr/config.py reads it. Unknown keys are fatal
        there. `library_dir`, `music_dir`, `state_dir` and `cache_dir` come from
        the options above, the folders the units' sandbox opens: set those, not
        these keys or `data_dir`. Secrets go in `credentials`, not here.
      '';
    };

    credentials = lib.mkOption {
      # Not in the store: these are secrets, such as agenix paths.
      type = lib.types.attrsOf lib.types.externalPath;
      default = { };
      example = lib.literalExpression ''
        {
          spotify_client_secret = config.age.secrets.tabarr-spotify.path;
          ntfy_token = config.age.secrets.tabarr-ntfy.path;
        }
      '';
      description = ''
        Files systemd passes to tabarr through `LoadCredential`, by credential
        name. tabarr reads `spotify_client_secret` and `ntfy_token`. The files
        are read as root, so they can stay root-only. The nightly run and
        `tabarr-admin` get them; the auto-chords unit, which reads none, doesn't.
      '';
    };

    autochords = {
      enable = lib.mkEnableOption "the tabarr-autochords unit, run after each successful tabarr run";

      package = lib.mkOption {
        type = lib.types.package;
        default = cfg.package.override { withAutochords = true; };
        defaultText = lib.literalExpression "config.services.tabarr.package.override { withAutochords = true; }";
        description = ''
          tabarr with the autochords extra (torch, beat-this, librosa). Its
          wrapper defaults TABARR_BTC_WEIGHTS and TABARR_BEAT_CHECKPOINT to the
          model files fetched by nix/autochords.nix, so the offline unit needs
          nothing else.
        '';
      };

      btcWeights = lib.mkOption {
        type = lib.types.nullOr lib.types.path;
        default = null;
        description = ''
          Other BTC chord model weights, as TABARR_BTC_WEIGHTS. Null leaves the
          package's own; settings.autochords.btc_weights wins over both.
        '';
      };

      beatCheckpoint = lib.mkOption {
        type = lib.types.nullOr lib.types.path;
        default = null;
        description = ''
          Another beat_this checkpoint, as TABARR_BEAT_CHECKPOINT. Null leaves
          the package's own; settings.autochords.beat_checkpoint wins over both.
        '';
      };
    };
  };

  config = lib.mkIf cfg.enable {
    assertions =
      let
        # The options whose tabarr.toml key settings sets to a path of its own.
        stray = lib.filter (
          name:
          let
            key = keys.${name};
          in
          cfg.settings ? ${key} && cfg.settings.${key} != dirSettings.${key} or null
        ) dirs;
        # Absolute, without whitespace, a trailing slash or an empty, "." or
        # ".." part: one spelling per folder, so that the checks below can
        # compare paths as strings.
        plain =
          dir:
          builtins.match "(/[^/[:space:]]+)+" dir != null
          && !(lib.elem "." (lib.splitString "/" dir) || lib.elem ".." (lib.splitString "/" dir));
        notPlain = lib.filter (name: !plain cfg.${name}) dirs;
        # The ones the units' sandbox hides.
        hidden = lib.filter (
          name:
          lib.any (top: cfg.${name} == top || inside top cfg.${name}) [
            "/home"
            "/root"
            "/run/user"
            "/tmp"
            "/var/tmp"
          ]
        ) dirs;
        # Each pair of the four that is one folder, or one inside the other.
        pairs = lib.concatLists (
          lib.imap0 (i: a: map (b: { inherit a b; }) (lib.drop (i + 1) folders)) folders
        );
        tangle =
          { a, b }:
          let
            shown = name: "${name} (\"${cfg.${name}}\")";
          in
          if cfg.${a} == cfg.${b} then
            [ "${a} and ${b} are both \"${cfg.${a}}\"" ]
          else if inside cfg.${a} cfg.${b} then
            [ "${shown b} is inside ${shown a}" ]
          else if inside cfg.${b} cfg.${a} then
            [ "${shown a} is inside ${shown b}" ]
          else
            [ ];
        tangles = lib.concatMap tangle pairs;
      in
      [
        {
          assertion = stray == [ ];
          message = ''
            services.tabarr: the units' sandbox opens the folders the options
            name, and the generated tabarr.toml names them, so set the options
            instead of their keys in settings:${
              lib.concatMapStrings (name: "\n  ${name}, not settings.${keys.${name}}") stray
            }
          '';
        }
        {
          assertion = notPlain == [ ];
          message = ''
            services.tabarr: these must be absolute paths without whitespace, a
            trailing slash or a "." or ".." part, such as "/data/tabarr":${listed notPlain}
          '';
        }
        {
          assertion = hidden == [ ];
          message = ''
            services.tabarr: the units' sandbox hides /home, /root and /run/user
            (ProtectHome) and /tmp and /var/tmp (PrivateTmp), so these must be
            elsewhere:${listed hidden}
          '';
        }
        {
          assertion = tangles == [ ];
          message = ''
            services.tabarr: libraryDir, musicDir, stateDir and cacheDir must be
            four folders, none inside another: the state and the cache are
            tabarr's alone, while Syncthing writes the library and the music.${
              lib.concatMapStrings (tangle: "\n  ${tangle}") tangles
            }
          '';
        }
      ];

    # The generated file names the folders the sandbox opens. At default
    # priority, so that a value settings sets shows, for the assertion above.
    services.tabarr.settings = lib.mapAttrs (_: lib.mkDefault) dirSettings;

    users.users.tabarr = {
      isSystemUser = true;
      group = "tabarr";
      description = "tabarr";
    };
    users.groups.tabarr = { };

    systemd.tmpfiles.settings.tabarr = {
      # setgid, so whatever Syncthing or tabarr creates inside stays in group tabarr.
      ${cfg.libraryDir}.d = {
        user = "tabarr";
        group = "tabarr";
        mode = "2775";
      };
      # The database, the Spotify token, the lock and every response.
      ${cfg.stateDir}.d = {
        user = "tabarr";
        group = "tabarr";
        mode = "0700";
      };
      ${cfg.cacheDir}.d = {
        user = "tabarr";
        group = "tabarr";
        mode = "0700";
      };
    }
    # dataDir, when it holds any of the four: the group gets through to the
    # library and the music, and no further. ":" applies the owner and mode
    # only to a folder tmpfiles creates, so one that exists keeps its own.
    // lib.optionalAttrs (lib.any (name: inside cfg.dataDir cfg.${name}) folders) {
      ${cfg.dataDir}.d = {
        user = ":tabarr";
        group = ":tabarr";
        mode = ":0710";
      };
    };

    systemd.services.tabarr = {
      description = "tabarr nightly run: sync, match, fetch and write the library";
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      onFailure = [ "tabarr-notify-failure.service" ];
      # OnSuccess rather than Wants/After: auto-chords follows only a run that
      # finished, and can still be started on its own without starting a run.
      onSuccess = lib.optional cfg.autochords.enable "tabarr-autochords.service";
      # A switch never cuts a run short; the next run uses the new unit.
      restartIfChanged = false;
      unitConfig.RequiresMountsFor = writable;
      environment = cacheEnv;
      serviceConfig =
        sandbox
        // identity
        // secrets
        // paths
        // {
          Type = "oneshot";
          # --config is a root option of the CLI, so it precedes the subcommand.
          ExecStart = "${lib.getExe cfg.package} --config ${configFile} run";
          # About 30 minutes of polite requests at most; a hung run must not
          # hold the next night's.
          TimeoutStartSec = "3h";
        };
    };

    systemd.timers.tabarr = {
      description = "Nightly tabarr run";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = cfg.schedule;
        Persistent = true;
        RandomizedDelaySec = "45m";
      };
    };

    systemd.services.tabarr-autochords = lib.mkIf cfg.autochords.enable {
      description = "tabarr auto-chords: chord sheets from purchased audio, offline";
      after = [ "tabarr.service" ];
      onFailure = [ "tabarr-notify-failure.service" ];
      restartIfChanged = false;
      unitConfig.RequiresMountsFor = writable;
      environment = cacheEnv // modelEnv;
      serviceConfig =
        sandbox
        // identity
        // paths
        // {
          Type = "oneshot";
          ExecStart = "${lib.getExe cfg.autochords.package} --config ${configFile} autochords";
          # The model files ship with the package: no network at all.
          PrivateNetwork = true;
          # PyTorch's CPU kernels generate code at run time.
          MemoryDenyWriteExecute = false;
          # A first backlog of purchases can take a while on a CPU.
          TimeoutStartSec = "6h";
          CPUSchedulingPolicy = "batch";
          IOSchedulingClass = "idle";
        };
    };

    systemd.services.tabarr-notify-failure = {
      description = "Tell ntfy that a tabarr unit failed";
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      serviceConfig = sandbox // {
        Type = "oneshot";
        # Its own throwaway user: it needs nothing of tabarr's but the token.
        DynamicUser = true;
        ExecStart = lib.getExe notifyFailure;
        LoadCredential = lib.optional (
          cfg.credentials ? ntfy_token
        ) "ntfy_token:${cfg.credentials.ntfy_token}";
      };
    };

    environment.systemPackages = [ tabarrAdmin ];
  };
}
