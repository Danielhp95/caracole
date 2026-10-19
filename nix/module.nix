# services.tabarr: a nightly `tabarr run` as a hardened oneshot on a timer, an
# optional auto-chords unit after it with no network, an ntfy message when
# either fails, and `tabarr-admin` for the interactive commands.
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

  # Who tabarr runs as and what it keeps: both units and tabarr-admin.
  identity = {
    User = "tabarr";
    Group = "tabarr";
    StateDirectory = "tabarr";
    CacheDirectory = "tabarr";
    # The database and the Spotify token stay with the tabarr user alone...
    StateDirectoryMode = "0700";
    CacheDirectoryMode = "0700";
    # ...while the files it writes are group-writable: Syncthing, in group
    # tabarr, syncs the library both ways (the inbox, edits from a phone).
    UMask = "0007";
    LoadCredential = credentials;
  };

  paths = {
    ReadWritePaths = [ cfg.libraryDir ];
    # "-": the music folder may not exist yet.
    ReadOnlyPaths = [ "-${cfg.musicDir}" ];
  };

  # HOME (/var/empty) is read-only, and librosa's numba refuses to import
  # without a writable cache ("no locator available"); torch caches there too.
  # tabarr's own cache comes from $CACHE_DIRECTORY, which wins over these.
  cacheEnv = {
    XDG_CACHE_HOME = "/var/cache/tabarr";
    NUMBA_CACHE_DIR = "/var/cache/tabarr/numba";
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
  # commands: a transient unit under the tabarr user, with the same state,
  # cache, credentials and generated config. With the auto-chords package when
  # that is on, so `tabarr-admin autochords` works too.
  adminPackage = if cfg.autochords.enable then cfg.autochords.package else cfg.package;
  adminEnv = {
    TABARR_CONFIG = configFile;
  }
  // cacheEnv
  // lib.optionalAttrs cfg.autochords.enable modelEnv;
  adminArgs =
    lib.mapAttrsToList (name: value: "--setenv=${name}=${value}") adminEnv
    ++ lib.concatLists (
      lib.mapAttrsToList (name: value: map (v: "--property=${name}=${v}") (lib.toList value)) identity
    );
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

    libraryDir = lib.mkOption {
      # A string, so it is never copied to the store.
      type = lib.types.str;
      default = "/srv/tabs";
      description = ''
        The library tabarr writes: sheets, lyrics, guitar parts, `_todo.md`,
        `wanted.txt` and `overrides.toml`. It is created setgid, group `tabarr`,
        mode 2775, so a Syncthing user in that group can share it.
      '';
    };

    musicDir = lib.mkOption {
      type = lib.types.str;
      default = "/srv/music";
      description = "Purchased audio, read-only, for auto-chords. It may not exist yet.";
    };

    schedule = lib.mkOption {
      type = lib.types.str;
      default = "*-*-* 03:30";
      description = "When `tabarr run` starts (systemd.time(7) calendar event), give or take 45 minutes.";
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
        there. `library_dir` and `music_dir` come from the options above; state
        and cache live in /var/lib/tabarr and /var/cache/tabarr. Secrets go in
        `credentials`, not here.
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
        are read as root, so they can stay root-only.
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
    assertions = [
      {
        assertion = !(cfg.settings ? state_dir || cfg.settings ? cache_dir);
        message = ''
          services.tabarr: state and cache live in the units' StateDirectory and
          CacheDirectory (/var/lib/tabarr, /var/cache/tabarr), the only places
          the sandbox lets tabarr write; remove settings.state_dir and
          settings.cache_dir.
        '';
      }
      {
        assertion = lib.all (dir: builtins.match "/[^[:space:]]*" dir != null) [
          cfg.libraryDir
          cfg.musicDir
        ];
        message = "services.tabarr: libraryDir and musicDir must be absolute paths without whitespace.";
      }
      {
        assertion =
          let
            hidden =
              dir:
              lib.any (top: dir == top || lib.hasPrefix "${top}/" dir) [
                "/home"
                "/root"
                "/run/user"
              ];
          in
          !(hidden cfg.libraryDir || hidden cfg.musicDir);
        message = ''
          services.tabarr: libraryDir and musicDir must be outside /home, /root
          and /run/user, which the units' sandbox hides (ProtectHome).
        '';
      }
    ];

    # The generated file always names the directories the sandbox opens; a
    # different value in settings is a conflicting definition.
    services.tabarr.settings = {
      library_dir = cfg.libraryDir;
      music_dir = cfg.musicDir;
    };

    users.users.tabarr = {
      isSystemUser = true;
      group = "tabarr";
      description = "tabarr";
    };
    users.groups.tabarr = { };

    # setgid, so whatever Syncthing or tabarr creates inside stays in group tabarr.
    systemd.tmpfiles.settings.tabarr.${cfg.libraryDir}.d = {
      user = "tabarr";
      group = "tabarr";
      mode = "2775";
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
      unitConfig.RequiresMountsFor = [ cfg.libraryDir ];
      environment = cacheEnv;
      serviceConfig =
        sandbox
        // identity
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
      unitConfig.RequiresMountsFor = [ cfg.libraryDir ];
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
