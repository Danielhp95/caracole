# services.caracole: a nightly `caracole run` as a hardened oneshot on a timer, an
# optional auto-chords unit after it with no network, an optional caracole-web
# (`caracole serve`: the library page and song requests), an ntfy message when
# one fails, and `caracole-admin` for the interactive commands. Everything
# caracole keeps sits in one folder, dataDir, unless an option moves a part.
{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.caracole;
  toml = pkgs.formats.toml { };
  configFile = toml.generate "caracole.toml" cfg.settings;

  credentials = lib.mapAttrsToList (name: path: "${name}:${path}") cfg.credentials;

  # The four folders by option, and dataDir, which holds them by default.
  folders = [
    "libraryDir"
    "musicDir"
    "stateDir"
    "cacheDir"
  ];
  dirs = [ "dataDir" ] ++ folders;
  # The caracole.toml key of each.
  keys = {
    dataDir = "data_dir";
    libraryDir = "library_dir";
    musicDir = "music_dir";
    stateDir = "state_dir";
    cacheDir = "cache_dir";
  };
  # The folders as the generated caracole.toml names them: the paths the units'
  # sandbox opens. Not data_dir, which these four would win over.
  dirSettings = lib.listToAttrs (map (name: lib.nameValuePair keys.${name} cfg.${name}) folders);

  inside = parent: dir: lib.hasPrefix "${parent}/" dir;
  # Options with their paths, one per line, for a message.
  listed = lib.concatMapStrings (name: "\n  ${name} = \"${cfg.${name}}\";");

  # What caracole writes. The hardened units may write there and nowhere else.
  writable = [
    cfg.libraryDir
    cfg.stateDir
    cfg.cacheDir
  ];

  # Hardening every unit here shares: plan §6 plus the usual extras. RemoveIPC
  # is left out because the caracole units and caracole-admin share one user.
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

  # Who caracole runs as: both units and caracole-admin.
  identity = {
    User = "caracole";
    Group = "caracole";
    # The files it writes are group-writable: Syncthing, in group caracole, syncs
    # the library both ways (the inbox, edits from a phone). The database and
    # the Spotify token stay with the caracole user alone, in a folder of mode
    # 0700.
    UMask = "0007";
  };

  # The static secrets, for the nightly run and caracole-admin (`auth spotify`,
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
  # caracole's own cache is cache_dir in the generated file, which wins over these.
  cacheEnv = {
    XDG_CACHE_HOME = cfg.cacheDir;
    NUMBA_CACHE_DIR = "${cfg.cacheDir}/numba";
  };

  # The model files for auto-chords. Null ones stay unset, so the package
  # wrapper's --set-default values apply; settings.autochords wins over both.
  modelEnv = lib.filterAttrs (_: value: value != null) {
    CARACOLE_BTC_WEIGHTS = cfg.autochords.btcWeights;
    CARACOLE_BEAT_CHECKPOINT = cfg.autochords.beatCheckpoint;
  };

  # `caracole serve`'s options, from services.caracole.web. Their types allow no
  # whitespace or quote, so they need no quoting on the ExecStart line.
  webArgs = lib.concatStringsSep " " (
    [
      "--address"
      cfg.web.address
      "--port"
      (toString cfg.web.port)
    ]
    ++ lib.concatMap (host: [
      "--allow-host"
      host
    ]) cfg.web.allowedHosts
  );

  ntfyUrl = cfg.settings.ntfy.url or "";

  notifyFailure = pkgs.writeShellApplication {
    name = "caracole-notify-failure";
    runtimeInputs = [ pkgs.curl ];
    text = ''
      url=${lib.escapeShellArg ntfyUrl}
      if [ -z "$url" ]; then
        echo "a caracole unit failed; ntfy is not configured (services.caracole.settings.ntfy.url), so nothing was sent"
        exit 0
      fi

      # systemd sets MONITOR_* for a unit started through OnFailure=.
      unit=''${MONITOR_UNIT:-caracole.service}
      result=''${MONITOR_SERVICE_RESULT:-failed}
      args=(
        --silent --show-error --fail-with-body --max-time 30 --retry 3
        --header "Title: caracole: $unit failed"
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

  # caracole as its units run it, for `auth spotify`, `index build` and one-off
  # commands: a transient unit under the caracole user, in the units' sandbox,
  # with the same folders, credentials and generated config. It keeps the
  # network (`auth spotify` and `index build` need it). With the auto-chords
  # package when that is on, so `caracole-admin autochords` works too, and then,
  # as in that unit, without MemoryDenyWriteExecute.
  adminPackage = if cfg.autochords.enable then cfg.autochords.package else cfg.package;
  adminEnv = {
    CARACOLE_CONFIG = configFile;
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
  caracoleAdmin = pkgs.writeShellApplication {
    name = "caracole-admin";
    runtimeInputs = [ config.systemd.package ];
    text = ''
      if [ "$EUID" -ne 0 ]; then
        echo "caracole-admin starts a system unit as the caracole user: run it with sudo" >&2
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
  options.services.caracole = {
    enable = lib.mkEnableOption "caracole, the nightly chord sheet, lyrics and guitar part library";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ./package.nix { };
      defaultText = lib.literalExpression "pkgs.callPackage ./package.nix { }";
      description = "The caracole package. The flake's module sets it to the flake's build.";
    };

    dataDir = lib.mkOption {
      # A string, as are the folders below, so it is never copied to the store.
      type = lib.types.str;
      default = "/var/lib/caracole";
      example = "/data/caracole";
      description = ''
        The folder that holds everything caracole keeps: `library`, `music`,
        `state` and `cache`, unless libraryDir, musicDir, stateDir or cacheDir
        puts one elsewhere. When missing, it is created as `caracole:caracole`, mode
        0710, so that the group gets through to the library and the music. An
        existing folder keeps its owner and mode, so it can be one that other
        things share, such as a disk's root; it must then let `caracole` and its
        group through.
      '';
    };

    libraryDir = lib.mkOption {
      type = lib.types.str;
      default = "${cfg.dataDir}/library";
      defaultText = lib.literalExpression ''"''${config.services.caracole.dataDir}/library"'';
      description = ''
        The library caracole writes: sheets, lyrics, guitar parts, `_todo.md`,
        `wanted.txt` and `overrides.toml`. It is created setgid, group `caracole`,
        mode 2775, so a Syncthing user in that group can share it.
      '';
    };

    musicDir = lib.mkOption {
      type = lib.types.str;
      default = "${cfg.dataDir}/music";
      defaultText = lib.literalExpression ''"''${config.services.caracole.dataDir}/music"'';
      description = ''
        Purchased audio, read-only, for auto-chords. It may not exist yet:
        whoever fills it creates it.
      '';
    };

    stateDir = lib.mkOption {
      type = lib.types.str;
      default = "${cfg.dataDir}/state";
      defaultText = lib.literalExpression ''"''${config.services.caracole.dataDir}/state"'';
      description = ''
        The database, the Spotify token and caracole's lock: back it up, but don't
        share it. It is created as `caracole:caracole`, mode 0700.
      '';
    };

    cacheDir = lib.mkOption {
      type = lib.types.str;
      default = "${cfg.dataDir}/cache";
      defaultText = lib.literalExpression ''"''${config.services.caracole.dataDir}/cache"'';
      description = ''
        Every raw HTTP response, kept forever, the private folders PDFs are made
        in, and numba's and torch's caches. It is created as `caracole:caracole`,
        mode 0700. Losing it costs only requests.
      '';
    };

    schedule = lib.mkOption {
      type = lib.types.str;
      default = "*-*-* 03:30";
      description = "When `caracole run` starts (systemd.time(7) calendar event), up to 45 minutes late.";
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
          ntfy.url = "https://ntfy.sh/my-caracole-topic";
          providers.ug.budget = 40;
        }
      '';
      description = ''
        caracole.toml, as src/caracole/config.py reads it. Unknown keys are fatal
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
          spotify_client_secret = config.age.secrets.caracole-spotify.path;
          ntfy_token = config.age.secrets.caracole-ntfy.path;
        }
      '';
      description = ''
        Files systemd passes to caracole through `LoadCredential`, by credential
        name. caracole reads `spotify_client_secret`, `ntfy_token` and
        `web_token` (the access token caracole-web asks each browser for). The
        files are read as root, so they can stay root-only. The nightly run and
        `caracole-admin` get them; caracole-web gets `web_token` alone, and the
        auto-chords unit, which reads none, gets none.
      '';
    };

    web = {
      enable = lib.mkEnableOption ''
        caracole-web: `caracole serve`, the library page over HTTP with a form to
        request songs, each request run as caracole commands, one at a time,
        under caracole's lock'';

      address = lib.mkOption {
        type = lib.types.strMatching "[^[:space:]\"'\\\\]+";
        default = "127.0.0.1";
        example = "100.64.0.7";
        description = ''
          Where caracole-web listens. 127.0.0.1, the default, is this machine
          alone (reach it through `ssh -L` or a reverse proxy). The host's tailnet
          or LAN address opens it to those networks, and 0.0.0.0 to every
          network. Beyond this machine, set `credentials.web_token` so each
          browser gives an access token once, and see `openFirewall`.
        '';
      };

      port = lib.mkOption {
        type = lib.types.port;
        default = 8737;
        description = "The port caracole-web listens on, 1024 or above: the unit has no capabilities.";
      };

      allowedHosts = lib.mkOption {
        type = lib.types.listOf (lib.types.strMatching "[A-Za-z0-9._:-]+");
        default = [ ];
        example = [ "nuc.example-tailnet.ts.net" ];
        description = ''
          More names caracole-web answers to, such as its full tailnet name. It
          answers to localhost, any IP address, and the host's name and its
          `.local` name already, and refuses every other name a browser sends,
          so that no other site can reach it under a name of its own (DNS
          rebinding).
        '';
      };

      openFirewall = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = ''
          Open `port` in the firewall on every interface, for a LAN address. A
          tailnet whose interface is in `networking.firewall.trustedInterfaces`
          needs no opening.
        '';
      };
    };

    autochords = {
      enable = lib.mkEnableOption "the caracole-autochords unit, run after each successful caracole run";

      package = lib.mkOption {
        type = lib.types.package;
        default = cfg.package.override { withAutochords = true; };
        defaultText = lib.literalExpression "config.services.caracole.package.override { withAutochords = true; }";
        description = ''
          caracole with the autochords extra (torch, beat-this, librosa). Its
          wrapper defaults CARACOLE_BTC_WEIGHTS and CARACOLE_BEAT_CHECKPOINT to the
          model files fetched by nix/autochords.nix, so the offline unit needs
          nothing else.
        '';
      };

      btcWeights = lib.mkOption {
        type = lib.types.nullOr lib.types.path;
        default = null;
        description = ''
          Other BTC chord model weights, as CARACOLE_BTC_WEIGHTS. Null leaves the
          package's own; settings.autochords.btc_weights wins over both.
        '';
      };

      beatCheckpoint = lib.mkOption {
        type = lib.types.nullOr lib.types.path;
        default = null;
        description = ''
          Another beat_this checkpoint, as CARACOLE_BEAT_CHECKPOINT. Null leaves
          the package's own; settings.autochords.beat_checkpoint wins over both.
        '';
      };
    };
  };

  config = lib.mkIf cfg.enable {
    assertions =
      let
        # The options whose caracole.toml key settings sets to a path of its own.
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
            services.caracole: the units' sandbox opens the folders the options
            name, and the generated caracole.toml names them, so set the options
            instead of their keys in settings:${
              lib.concatMapStrings (name: "\n  ${name}, not settings.${keys.${name}}") stray
            }
          '';
        }
        {
          assertion = notPlain == [ ];
          message = ''
            services.caracole: these must be absolute paths without whitespace, a
            trailing slash or a "." or ".." part, such as "/data/caracole":${listed notPlain}
          '';
        }
        {
          assertion = hidden == [ ];
          message = ''
            services.caracole: the units' sandbox hides /home, /root and /run/user
            (ProtectHome) and /tmp and /var/tmp (PrivateTmp), so these must be
            elsewhere:${listed hidden}
          '';
        }
        {
          assertion = !cfg.web.enable || cfg.web.port >= 1024;
          message = ''
            services.caracole.web.port must be 1024 or above: caracole-web runs
            without capabilities, so it can't listen on port ${toString cfg.web.port}.
          '';
        }
        {
          assertion = tangles == [ ];
          message = ''
            services.caracole: libraryDir, musicDir, stateDir and cacheDir must be
            four folders, none inside another: the state and the cache are
            caracole's alone, while Syncthing writes the library and the music.${
              lib.concatMapStrings (tangle: "\n  ${tangle}") tangles
            }
          '';
        }
      ];

    # The generated file names the folders the sandbox opens. At default
    # priority, so that a value settings sets shows, for the assertion above.
    services.caracole.settings = lib.mapAttrs (_: lib.mkDefault) dirSettings;

    users.users.caracole = {
      isSystemUser = true;
      group = "caracole";
      description = "caracole";
    };
    users.groups.caracole = { };

    systemd.tmpfiles.settings.caracole = {
      # setgid, so whatever Syncthing or caracole creates inside stays in group caracole.
      ${cfg.libraryDir}.d = {
        user = "caracole";
        group = "caracole";
        mode = "2775";
      };
      # The database, the Spotify token, the lock and every response.
      ${cfg.stateDir}.d = {
        user = "caracole";
        group = "caracole";
        mode = "0700";
      };
      ${cfg.cacheDir}.d = {
        user = "caracole";
        group = "caracole";
        mode = "0700";
      };
    }
    # dataDir, when it holds any of the four: the group gets through to the
    # library and the music, and no further. ":" applies the owner and mode
    # only to a folder tmpfiles creates, so one that exists keeps its own.
    // lib.optionalAttrs (lib.any (name: inside cfg.dataDir cfg.${name}) folders) {
      ${cfg.dataDir}.d = {
        user = ":caracole";
        group = ":caracole";
        mode = ":0710";
      };
    };

    systemd.services.caracole = {
      description = "caracole nightly run: sync, match, fetch and write the library";
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      onFailure = [ "caracole-notify-failure.service" ];
      # OnSuccess rather than Wants/After: auto-chords follows only a run that
      # finished, and can still be started on its own without starting a run.
      onSuccess = lib.optional cfg.autochords.enable "caracole-autochords.service";
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

    systemd.timers.caracole = {
      description = "Nightly caracole run";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = cfg.schedule;
        Persistent = true;
        RandomizedDelaySec = "45m";
      };
    };

    systemd.services.caracole-autochords = lib.mkIf cfg.autochords.enable {
      description = "caracole auto-chords: chord sheets from purchased audio, offline";
      after = [ "caracole.service" ];
      onFailure = [ "caracole-notify-failure.service" ];
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

    # The library page, and song requests: `caracole serve`. A request runs
    # caracole commands in this unit, one at a time, each under caracole's lock,
    # so it has the nightly run's folders, network and sandbox. Of the
    # credentials it gets web_token alone: neither the server nor the commands
    # it runs (add, match, fetch, render) read Spotify or ntfy.
    systemd.services.caracole-web = lib.mkIf cfg.web.enable {
      description = "caracole web: the library page and song requests";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      onFailure = [ "caracole-notify-failure.service" ];
      # A fault that lasts (the port taken, the address gone) fails the unit for
      # good after 30 starts in 10 minutes, about 5 minutes of retries, with one
      # alert.
      startLimitIntervalSec = 600;
      startLimitBurst = 30;
      unitConfig.RequiresMountsFor = writable;
      environment = cacheEnv;
      serviceConfig =
        sandbox
        // identity
        // paths
        // {
          Type = "exec";
          ExecStart = "${lib.getExe cfg.package} --config ${configFile} serve ${webArgs}";
          LoadCredential = lib.optional (
            cfg.credentials ? web_token
          ) "web_token:${cfg.credentials.web_token}";
          # A tailnet address may not exist yet at boot: try again until it does.
          Restart = "on-failure";
          RestartSec = "10s";
          # Straight back to starting, not through `failed`, which would start
          # OnFailure= and send an alert on every try.
          RestartMode = "direct";
        };
    };

    warnings =
      lib.optional
        (
          cfg.web.enable
          && !(lib.elem cfg.web.address [
            "127.0.0.1"
            "::1"
            "localhost"
          ])
          && !(cfg.credentials ? web_token)
        )
        "services.caracole.web listens on ${cfg.web.address} without credentials.web_token: anyone who reaches it can read the library and request songs.";

    networking.firewall.allowedTCPPorts = lib.mkIf (cfg.web.enable && cfg.web.openFirewall) [
      cfg.web.port
    ];

    systemd.services.caracole-notify-failure = {
      description = "Tell ntfy that a caracole unit failed";
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      serviceConfig = sandbox // {
        Type = "oneshot";
        # Its own throwaway user: it needs nothing of caracole's but the token.
        DynamicUser = true;
        ExecStart = lib.getExe notifyFailure;
        LoadCredential = lib.optional (
          cfg.credentials ? ntfy_token
        ) "ntfy_token:${cfg.credentials.ntfy_token}";
      };
    };

    environment.systemPackages = [ caracoleAdmin ];
  };
}
