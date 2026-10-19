# `nix build .#checks.x86_64-linux.module`: evaluates small NixOS systems that
# enable services.caracole and fails, naming every broken expectation, when a unit
# setting the design relies on is wrong. The build then loads the generated
# caracole.toml files with caracole's own loader (an unknown key is fatal there), and
# runs the failure notifier with ntfy unset, which must succeed quietly.
#
# The systems run a stub `caracole`, so this check neither builds nor tests the
# real package; `checks.package` does that.
{
  lib,
  pkgs,
  runCommand,
  writeShellScriptBin,
  python3,
  # The module under test: the flake's nixosModules.default.
  module,
  # What services.caracole.package and autochords.package must default to.
  defaultPackage,
  autochordsPackage,
}:
let
  # caracole's config loader, run against the generated file.
  loader = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../src/caracole/__init__.py
      ../src/caracole/config.py
    ];
  };

  stub = writeShellScriptBin "caracole" "exit 0";
  toml = pkgs.formats.toml { };

  evalSystem =
    modules:
    (pkgs.nixos (
      [
        module
        {
          boot.isContainer = true;
          system.stateVersion = lib.trivial.release;
          services.caracole.enable = true;
        }
      ]
      ++ modules
    )).config;

  stubbed.services.caracole = {
    package = stub;
    autochords.package = stub;
  };

  # ntfy, Spotify and both static secrets, as the NUC will have them.
  configured.services.caracole = {
    settings = {
      ntfy.url = "https://ntfy.example/caracole";
      spotify = {
        client_id = "abc123";
        playlists = [ "Learn" ];
      };
    };
    credentials = {
      spotify_client_secret = "/run/agenix/spotify_client_secret";
      ntfy_token = "/run/agenix/ntfy_token";
    };
  };

  autochordsOn.services.caracole.autochords = {
    enable = true;
    btcWeights = "/models/btc.pt";
    beatCheckpoint = "/models/beat_this.ckpt";
  };

  # What the packages' wrappers must default to: the fetched models, and the one
  # CJK font ChordPro 6.050.7 renders correctly (see src/caracole/render.py).
  models = pkgs.callPackage ./autochords.nix { };
  fusionKai = "${pkgs.lxgw-fusionkai}/share/fonts/truetype/FusionKaiJ-Regular.ttf";

  # Whether makeWrapperArgs holds `--set-default NAME VALUE`.
  setsDefault =
    package: name: value:
    let
      args = package.makeWrapperArgs;
    in
    lib.any (
      i:
      lib.elemAt args i == "--set-default"
      && lib.elemAt args (i + 1) == name
      && lib.elemAt args (i + 2) == value
    ) (lib.range 0 (lib.length args - 3));
  setsAny = package: name: lib.elem name package.makeWrapperArgs;

  bare = evalSystem [ stubbed ];
  nuc = evalSystem [
    stubbed
    configured
  ];
  nucAutochords = evalSystem [
    stubbed
    configured
    autochordsOn
  ];
  # Auto-chords on, with the model files left to the package.
  nucModelsFromPackage = evalSystem [
    stubbed
    configured
    { services.caracole.autochords.enable = true; }
  ];
  # caracole-web with its defaults, and on a tailnet address with a token.
  webDefault = evalSystem [
    stubbed
    { services.caracole.web.enable = true; }
  ];
  webTailnet = evalSystem [
    stubbed
    configured
    {
      services.caracole = {
        web = {
          enable = true;
          address = "100.64.0.7";
          port = 8740;
          allowedHosts = [
            "nuc.example.ts.net"
            "nuc"
          ];
          openFirewall = true;
        };
        credentials.web_token = "/run/agenix/caracole-web-token";
      };
    }
  ];
  # caracole-web on every address, with no access token.
  webOpen = evalSystem [
    stubbed
    configured
    {
      services.caracole.web = {
        enable = true;
        address = "0.0.0.0";
      };
    }
  ];
  defaults = evalSystem [ ];
  # nix/module.nix imported on its own, without the flake's wrapper.
  standalone =
    (pkgs.nixos [
      ./module.nix
      {
        boot.isContainer = true;
        system.stateVersion = lib.trivial.release;
        services.caracole.enable = true;
      }
    ]).config;
  # Everything caracole keeps in /data/caracole instead, with every unit on.
  moved = evalSystem [
    stubbed
    configured
    autochordsOn
    { services.caracole.dataDir = "/data/caracole"; }
  ];
  # The same, with the library somewhere else, on its own.
  libraryAlone = evalSystem [
    stubbed
    {
      services.caracole = {
        dataDir = "/data/caracole";
        libraryDir = "/srv/tabs";
      };
    }
  ];
  # Every folder set on its own, outside dataDir; the state at dataDir's path.
  noneInDataDir = evalSystem [
    stubbed
    {
      services.caracole = {
        libraryDir = "/srv/tabs";
        musicDir = "/srv/music";
        stateDir = "/var/lib/caracole";
        cacheDir = "/var/cache/caracole";
      };
    }
  ];

  failedAssertions = cfg: map (a: a.message) (lib.filter (a: !a.assertion) cfg.assertions);
  # The failed assertions of a system with these services.caracole settings.
  rejections =
    caracole:
    failedAssertions (evalSystem [
      stubbed
      { services.caracole = caracole; }
    ]);
  # Whether one of the messages has all of these lines or words.
  says = words: lib.any (message: lib.all (word: lib.hasInfix word message) words);

  stateDirSet = rejections { settings.state_dir = "/elsewhere"; };
  cacheDirForced = rejections { settings.cache_dir = lib.mkForce "/elsewhere"; };
  dataDirSet = rejections { settings.data_dir = "/elsewhere"; };
  libraryDirSet = rejections { settings.library_dir = "/srv/tabs"; };
  libraryInHome = rejections { libraryDir = "/home/alice/Tabs"; };
  dataInRoot = rejections { dataDir = "/root/caracole"; };
  cacheInVarTmp = rejections { cacheDir = "/var/tmp/caracole"; };
  dataRelative = rejections { dataDir = "data/caracole"; };
  stateWithSlash = rejections { stateDir = "/data/caracole/state/"; };
  musicWithDots = rejections { musicDir = "/data/caracole/../music"; };
  libraryWithSpace = rejections { libraryDir = "/srv/my tabs"; };
  stateInLibrary = rejections { stateDir = "/var/lib/caracole/library/.state"; };
  libraryInState = rejections { stateDir = "/var/lib/caracole"; };
  stateIsCache = rejections { cacheDir = "/var/lib/caracole/state"; };
  webOnPort80 = rejections {
    web = {
      enable = true;
      port = 80;
    };
  };

  # The folders a system's units must open: the library, music, state and cache.
  layout = data: {
    library = "${data}/library";
    music = "${data}/music";
    state = "${data}/state";
    cache = "${data}/cache";
  };
  defaultLayout = layout "/var/lib/caracole";
  movedLayout = layout "/data/caracole";
  libraryAloneLayout = movedLayout // {
    library = "/srv/tabs";
  };

  # Whether a system has these folders, as its options and as the settings the
  # generated caracole.toml comes from, with no data_dir there.
  hasLayout =
    system: dirs:
    let
      caracole = system.services.caracole;
    in
    caracole.libraryDir == dirs.library
    && caracole.musicDir == dirs.music
    && caracole.stateDir == dirs.state
    && caracole.cacheDir == dirs.cache
    && caracole.settings.library_dir == dirs.library
    && caracole.settings.music_dir == dirs.music
    && caracole.settings.state_dir == dirs.state
    && caracole.settings.cache_dir == dirs.cache
    && !(caracole.settings ? data_dir);

  # Whether a unit writes the library, the state and the cache and nothing
  # else, reads the music if it is there, waits for their file systems, and
  # caches in the cache folder.
  opens =
    unit: dirs:
    let
      sc = unit.serviceConfig;
      writable = [
        dirs.library
        dirs.state
        dirs.cache
      ];
    in
    sc.ReadWritePaths == writable
    && sc.ReadOnlyPaths == [ "-${dirs.music}" ]
    && unit.unitConfig.RequiresMountsFor == writable
    && unit.environment.XDG_CACHE_HOME == dirs.cache
    && unit.environment.NUMBA_CACHE_DIR == "${dirs.cache}/numba"
    # Which systemd keeps under /var/lib and /var/cache only: tmpfiles makes
    # the folders instead.
    && !(sc ? StateDirectory)
    && !(sc ? CacheDirectory);

  # The failure notifier opens no folder of caracole's.
  opensNothing =
    unit:
    let
      sc = unit.serviceConfig;
    in
    !(sc ? ReadWritePaths || sc ? ReadOnlyPaths || sc ? StateDirectory || sc ? CacheDirectory);

  # The folders tmpfiles makes: caracole's own, and dataDir when it holds any.
  makesFolders =
    system: dirs: data:
    let
      rules = system.systemd.tmpfiles.settings.caracole;
      is =
        dir: mode: owner:
        rules.${dir}.d.mode == mode && rules.${dir}.d.user == owner && rules.${dir}.d.group == owner;
    in
    lib.attrNames rules == lib.sort lib.lessThan (
      [
        dirs.library
        dirs.state
        dirs.cache
      ]
      ++ lib.optional (data != null) data
    )
    && is dirs.library "2775" "caracole"
    && is dirs.state "0700" "caracole"
    && is dirs.cache "0700" "caracole"
    # Created as caracole:caracole 0710, so the group gets through to the library
    # and the music; ":" leaves the owner and mode of one that exists alone.
    && (data == null || is data ":0710" ":caracole");

  configFile = toml.generate "caracole.toml" nuc.services.caracole.settings;
  movedConfigFile = toml.generate "caracole.toml" moved.services.caracole.settings;
  run = nuc.systemd.services.caracole;
  runSc = run.serviceConfig;
  timer = nuc.systemd.timers.caracole;
  notify = nuc.systemd.services.caracole-notify-failure;
  autochords = nucAutochords.systemd.services.caracole-autochords;
  autochordsSc = autochords.serviceConfig;
  autochordsPackageModels = nucModelsFromPackage.systemd.services.caracole-autochords;
  web = webDefault.systemd.services.caracole-web;
  webSc = web.serviceConfig;
  webConfigFile = toml.generate "caracole.toml" webDefault.services.caracole.settings;
  tailnetWeb = webTailnet.systemd.services.caracole-web;
  findAdmin =
    system: lib.findFirst (p: lib.getName p == "caracole-admin") null system.environment.systemPackages;
  admin = findAdmin nuc;
  adminAutochords = findAdmin nucAutochords;
  adminMoved = findAdmin moved;
  # The rendered tmpfiles.d file of the moved system.
  movedTmpfiles = lib.findFirst (p: p.name == "caracole.conf") null moved.systemd.tmpfiles.packages;

  hardened =
    sc:
    sc.NoNewPrivileges
    && sc.ProtectSystem == "strict"
    && sc.ProtectHome == true
    && sc.PrivateTmp
    && sc.PrivateDevices
    && sc.ProtectProc == "invisible"
    && sc.ProtectKernelTunables
    && sc.ProtectKernelModules
    && sc.ProtectControlGroups
    && sc.RestrictNamespaces
    && sc.LockPersonality
    &&
      sc.RestrictAddressFamilies == [
        "AF_INET"
        "AF_INET6"
        "AF_UNIX"
      ]
    && lib.elem "@system-service" sc.SystemCallFilter
    && sc.CapabilityBoundingSet == "";

  sameUser = sc: sc.User == "caracole" && sc.Group == "caracole" && sc.UMask == "0007";

  expectations = {
    # `--config` is a root option of the CLI (src/caracole/cli.py), so it goes
    # before the subcommand: `caracole run --config X` is a usage error there.
    "caracole.service runs `caracole --config <generated caracole.toml> run`" =
      runSc.ExecStart == "${lib.getExe stub} --config ${configFile} run";
    "caracole.service is a oneshot" = runSc.Type == "oneshot";
    "caracole.service runs as caracole, with a group-writable umask" = sameUser runSc;
    "by default, the library, music, state and cache are in /var/lib/caracole, and the generated settings name them" =
      nuc.services.caracole.dataDir == "/var/lib/caracole" && hasLayout nuc defaultLayout;
    "caracole.service writes only the library, state and cache in /var/lib/caracole, reads the music if it exists, waits for their mounts and caches there" =
      opens run defaultLayout;
    "caracole.service has MemoryDenyWriteExecute and RestrictNamespaces" =
      runSc.MemoryDenyWriteExecute && runSc.RestrictNamespaces;
    "caracole.service has the rest of the plan's hardening" = hardened runSc;
    "caracole.service loads the ntfy_token and spotify_client_secret credentials" =
      lib.elem "ntfy_token:/run/agenix/ntfy_token" runSc.LoadCredential
      && lib.elem "spotify_client_secret:/run/agenix/spotify_client_secret" runSc.LoadCredential;
    "caracole.service notifies on failure" = run.onFailure == [ "caracole-notify-failure.service" ];
    "caracole.service waits for the network" =
      lib.elem "network-online.target" run.wants && lib.elem "network-online.target" run.after;
    "caracole.service starts nothing on success without auto-chords" = run.onSuccess == [ ];
    "caracole.timer fires at the schedule, catches up and spreads the start" =
      timer.timerConfig.OnCalendar == "*-*-* 03:30"
      && timer.timerConfig.Persistent == true
      && timer.timerConfig.RandomizedDelaySec == "45m"
      && lib.elem "timers.target" timer.wantedBy;
    "caracole-notify-failure.service is a oneshot that loads only ntfy_token" =
      notify.serviceConfig.Type == "oneshot"
      && notify.serviceConfig.LoadCredential == [ "ntfy_token:/run/agenix/ntfy_token" ];
    "caracole-notify-failure.service is hardened, under a user of its own" =
      hardened notify.serviceConfig && notify.serviceConfig.DynamicUser;
    "caracole-notify-failure.service opens none of caracole's folders, wherever they are" =
      opensNothing notify && opensNothing moved.systemd.services.caracole-notify-failure;
    "caracole-autochords.service exists only when enabled" = !(nuc.systemd.services ? caracole-autochords);
    "caracole-autochords.service has PrivateNetwork and no MemoryDenyWriteExecute" =
      autochordsSc.PrivateNetwork == true && autochordsSc.MemoryDenyWriteExecute == false;
    # btc.py and librosa's numba need a writable cache; HOME is read-only.
    "caracole-autochords.service opens the same folders as caracole.service, numba's cache in the cache" =
      opens autochords defaultLayout;
    "caracole-autochords.service runs `caracole --config <generated caracole.toml> autochords`" =
      autochordsSc.ExecStart == "${lib.getExe stub} --config ${configFile} autochords";
    "caracole-autochords.service runs as caracole, with a group-writable umask" = sameUser autochordsSc;
    # It reads no secret, and its parsers (FFmpeg, libsndfile) see the most outside data.
    "caracole-autochords.service loads no credentials" =
      !(autochordsSc ? LoadCredential) || autochordsSc.LoadCredential == [ ];
    "caracole-autochords.service is otherwise hardened the same way" =
      hardened autochordsSc && autochordsSc.Type == "oneshot";
    "caracole-autochords.service gets the model paths" =
      autochords.environment.CARACOLE_BTC_WEIGHTS == "/models/btc.pt"
      && autochords.environment.CARACOLE_BEAT_CHECKPOINT == "/models/beat_this.ckpt";
    # Unset, so the package wrapper's --set-default values apply.
    "caracole-autochords.service leaves the model paths to the package when the options are null" =
      !(autochordsPackageModels.environment ? CARACOLE_BTC_WEIGHTS)
      && !(autochordsPackageModels.environment ? CARACOLE_BEAT_CHECKPOINT)
      && failedAssertions nucModelsFromPackage == [ ];
    "the auto-chords package points at the fetched BTC weights and beat_this checkpoint" =
      setsDefault autochordsPackage "CARACOLE_BTC_WEIGHTS" "${models.btcWeights}"
      && setsDefault autochordsPackage "CARACOLE_BEAT_CHECKPOINT" "${models.beatThisCheckpoint}";
    "the default package carries no model files" =
      !(setsAny defaultPackage "CARACOLE_BTC_WEIGHTS")
      && !(setsAny defaultPackage "CARACOLE_BEAT_CHECKPOINT");
    "both packages default CARACOLE_CJK_FONT to lxgw-fusionkai's FusionKaiJ-Regular.ttf" =
      setsDefault defaultPackage "CARACOLE_CJK_FONT" fusionKai
      && setsDefault autochordsPackage "CARACOLE_CJK_FONT" fusionKai;
    "caracole-autochords.service follows a successful run and notifies on failure" =
      nucAutochords.systemd.services.caracole.onSuccess == [ "caracole-autochords.service" ]
      && autochords.onFailure == [ "caracole-notify-failure.service" ];
    "caracole-web.service exists only when web.enable is set" =
      !(nuc.systemd.services ? caracole-web) && !(nucAutochords.systemd.services ? caracole-web);
    # --config is a root option of the CLI, so it precedes the subcommand.
    "caracole-web.service runs `caracole --config <generated caracole.toml> serve` on 127.0.0.1:8737 by default" =
      webSc.ExecStart == "${lib.getExe stub} --config ${webConfigFile} serve --address 127.0.0.1 --port 8737";
    "caracole-web.service listens where web.address and web.port say, answering to web.allowedHosts" =
      lib.hasSuffix " serve --address 100.64.0.7 --port 8740 --allow-host nuc.example.ts.net --allow-host nuc"
        tailnetWeb.serviceConfig.ExecStart;
    "caracole-web.service is hardened as caracole.service is, MemoryDenyWriteExecute included" =
      hardened webSc && webSc.MemoryDenyWriteExecute && webSc.RestrictNamespaces;
    "caracole-web.service runs as caracole, with a group-writable umask" = sameUser webSc;
    # Its requests run caracole commands, which write what the nightly run writes.
    "caracole-web.service writes only the library, state and cache, reads the music if it exists, waits for their mounts and caches there" =
      opens web defaultLayout;
    # Neither caracole serve nor the commands it runs (add, match, fetch, render) read Spotify or ntfy.
    "caracole-web.service loads web_token alone of the credentials, and none without it" =
      tailnetWeb.serviceConfig.LoadCredential == [ "web_token:/run/agenix/caracole-web-token" ]
      && (webOpen.systemd.services.caracole-web.serviceConfig.LoadCredential or [ ]) == [ ];
    "caracole-web listening beyond loopback without credentials.web_token is warned about, and only then" =
      says [
        "services.caracole.web listens on 0.0.0.0"
        "credentials.web_token"
      ] webOpen.warnings
      && !(says [ "credentials.web_token" ] webDefault.warnings)
      && !(says [ "credentials.web_token" ] webTailnet.warnings);
    "caracole-web.service starts at boot after the network, restarts when it fails, and notifies on failure" =
      lib.elem "multi-user.target" web.wantedBy
      && lib.elem "network-online.target" web.after
      && lib.elem "network-online.target" web.wants
      && webSc.Restart == "on-failure"
      && webSc.Type == "exec"
      && web.onFailure == [ "caracole-notify-failure.service" ];
    # RestartMode=normal goes through `failed` before each restart, which starts OnFailure=: an
    # alert every 10 seconds while a tailnet address is missing, for ever with a lasting fault.
    "caracole-web.service restarts without an alert each time, and fails once after 30 starts in 10 minutes" =
      (webSc.RestartMode or null) == "direct"
      && webSc.RestartSec == "10s"
      && web.startLimitIntervalSec == 600
      && web.startLimitBurst == 30;
    "web.openFirewall opens web.port, and only it opens it" =
      lib.elem 8740 webTailnet.networking.firewall.allowedTCPPorts
      && !(lib.elem 8737 webDefault.networking.firewall.allowedTCPPorts);
    "a web.port below 1024 is rejected" = says [
      "1024"
      "port 80"
    ] webOnPort80;
    "the caracole system user and group exist" =
      nuc.users.users.caracole.isSystemUser
      && nuc.users.users.caracole.group == "caracole"
      && nuc.users.groups ? caracole;
    "tmpfiles creates /var/lib/caracole 0710, the library 2775 and the state and cache 0700, all caracole:caracole, and leaves the music alone" =
      makesFolders nuc defaultLayout "/var/lib/caracole";
    "with dataDir = /data/caracole, the library, music, state and cache follow it, and the generated settings name them" =
      hasLayout moved movedLayout;
    "with dataDir = /data/caracole, both units write only its library, state and cache, and read its music" =
      opens moved.systemd.services.caracole movedLayout
      && opens moved.systemd.services.caracole-autochords movedLayout;
    "with dataDir = /data/caracole, tmpfiles creates it and its folders, and nothing in /var/lib" =
      makesFolders moved movedLayout
        "/data/caracole";
    "with dataDir = /data/caracole, both units run with the generated caracole.toml" =
      moved.systemd.services.caracole.serviceConfig.ExecStart
      == "${lib.getExe stub} --config ${movedConfigFile} run"
      &&
        moved.systemd.services.caracole-autochords.serviceConfig.ExecStart
        == "${lib.getExe stub} --config ${movedConfigFile} autochords";
    "libraryDir set on its own moves the library alone" =
      hasLayout libraryAlone libraryAloneLayout
      && opens libraryAlone.systemd.services.caracole libraryAloneLayout
      && makesFolders libraryAlone libraryAloneLayout "/data/caracole";
    # The state is /var/lib/caracole itself: one rule for it, 0700.
    "dataDir holding none of the folders is left alone" =
      hasLayout noneInDataDir {
        library = "/srv/tabs";
        music = "/srv/music";
        state = "/var/lib/caracole";
        cache = "/var/cache/caracole";
      }
      && makesFolders noneInDataDir {
        library = "/srv/tabs";
        state = "/var/lib/caracole";
        cache = "/var/cache/caracole";
      } null;
    "caracole-admin is installed" = admin != null && adminMoved != null;
    "the configured systems pass every assertion" = lib.all (system: failedAssertions system == [ ]) [
      nuc
      nucAutochords
      moved
      libraryAlone
      noneInDataDir
      webDefault
      webTailnet
      webOpen
    ];
    "settings.state_dir is rejected, for stateDir" = says [
      "stateDir, not settings.state_dir"
    ] stateDirSet;
    "settings.cache_dir is rejected, even when forced" = says [
      "cacheDir, not settings.cache_dir"
    ] cacheDirForced;
    "settings.data_dir is rejected, for dataDir" = says [ "dataDir, not settings.data_dir" ] dataDirSet;
    "settings.library_dir other than libraryDir is rejected" = says [
      "libraryDir, not settings.library_dir"
    ] libraryDirSet;
    "a library under /home, which the sandbox hides, is rejected" = says [
      "ProtectHome"
      ''libraryDir = "/home/alice/Tabs";''
    ] libraryInHome;
    "a dataDir under /root, which the sandbox hides, is rejected, with all it holds" = says [
      "ProtectHome"
      ''dataDir = "/root/caracole";''
      ''stateDir = "/root/caracole/state";''
    ] dataInRoot;
    "a cache under /var/tmp, which the sandbox hides, is rejected" = says [
      "PrivateTmp"
      ''cacheDir = "/var/tmp/caracole";''
    ] cacheInVarTmp;
    "a relative dataDir is rejected" = says [
      "absolute"
      ''dataDir = "data/caracole";''
    ] dataRelative;
    "a stateDir with a trailing slash is rejected" = says [
      "absolute"
      ''stateDir = "/data/caracole/state/";''
    ] stateWithSlash;
    "a musicDir with a .. part is rejected" = says [
      "absolute"
      ''musicDir = "/data/caracole/../music";''
    ] musicWithDots;
    "a libraryDir with whitespace is rejected" = says [
      "absolute"
      ''libraryDir = "/srv/my tabs";''
    ] libraryWithSpace;
    "a state folder inside the library is rejected" = says [
      "none inside another"
      ''stateDir ("/var/lib/caracole/library/.state") is inside libraryDir ("/var/lib/caracole/library")''
    ] stateInLibrary;
    "a library inside the state folder is rejected" = says [
      "none inside another"
      ''libraryDir ("/var/lib/caracole/library") is inside stateDir ("/var/lib/caracole")''
    ] libraryInState;
    "one folder for both the state and the cache is rejected" = says [
      "none inside another"
      ''stateDir and cacheDir are both "/var/lib/caracole/state"''
    ] stateIsCache;
    "the package defaults to this flake's package" =
      defaults.services.caracole.package.drvPath == defaultPackage.drvPath;
    "the auto-chords package defaults to this flake's autochords package" =
      defaults.services.caracole.autochords.package.drvPath == autochordsPackage.drvPath;
    "without the flake, the module builds the same packages from nix/package.nix" =
      standalone.services.caracole.package.drvPath == defaultPackage.drvPath
      && standalone.services.caracole.autochords.package.drvPath == autochordsPackage.drvPath;
    "the whole system evaluates" =
      nucAutochords.system.build.toplevel.drvPath != ""
      && moved.system.build.toplevel.drvPath != ""
      && webTailnet.system.build.toplevel.drvPath != "";
  };

  broken = lib.attrNames (lib.filterAttrs (_: ok: !ok) expectations);

  unitText = cfg: name: cfg.systemd.units.${name}.text;

  # The generated files, the environment each unit gives caracole, and the
  # folders caracole must then use: the file's explicit paths win over the
  # unit's XDG_CACHE_HOME.
  loads = system: dirs: {
    config = toml.generate "caracole.toml" system.services.caracole.settings;
    env = {
      HOME = "/var/empty";
      inherit (system.systemd.services.caracole.environment) XDG_CACHE_HOME NUMBA_CACHE_DIR;
    };
    paths = {
      library_dir = dirs.library;
      music_dir = dirs.music;
      state_dir = dirs.state;
      cache_dir = dirs.cache;
      wanted_file = "${dirs.library}/wanted.txt";
      overrides_file = "${dirs.library}/overrides.toml";
    };
  };
in
if broken != [ ] then
  throw ''
    caracole module check failed:
    ${lib.concatMapStrings (name: "  - ${name}\n") broken}''
else
  runCommand "caracole-module-check"
    {
      nativeBuildInputs = [ python3 ];
      inherit configFile;
      notifyUnconfigured = bare.systemd.services.caracole-notify-failure.serviceConfig.ExecStart;
      adminScript = lib.getExe admin;
      adminAutochordsScript = lib.getExe adminAutochords;
      adminMovedScript = lib.getExe adminMoved;
      movedTmpfiles = "${movedTmpfiles}/lib/tmpfiles.d/caracole.conf";
      passAsFile = [
        "loadCases"
        "runUnit"
        "timerUnit"
        "notifyUnit"
        "autochordsUnit"
        "movedRunUnit"
        "movedAutochordsUnit"
        "movedNotifyUnit"
        "webUnit"
      ];
      loadCases = builtins.toJSON [
        (loads nuc defaultLayout)
        (loads moved movedLayout)
        (loads libraryAlone libraryAloneLayout)
      ];
      runUnit = unitText nuc "caracole.service";
      timerUnit = unitText nuc "caracole.timer";
      notifyUnit = unitText nuc "caracole-notify-failure.service";
      autochordsUnit = unitText nucAutochords "caracole-autochords.service";
      movedRunUnit = unitText moved "caracole.service";
      movedAutochordsUnit = unitText moved "caracole-autochords.service";
      movedNotifyUnit = unitText moved "caracole-notify-failure.service";
      webUnit = unitText webTailnet "caracole-web.service";
    }
    ''
      # Fails the build when the file has the text: `! grep` would not, since
      # set -e ignores a command whose status is inverted.
      lacks() {
        if grep -q -- "$1" "$2"; then
          echo "$2 has $1" >&2
          exit 1
        fi
      }

      # The generated files must load with caracole's own strict loader, in the
      # units' environment, and name the folders the units open.
      PYTHONPATH=${loader}/src python3 - "$loadCasesPath" <<'EOF'
      import json
      import sys
      from pathlib import Path

      from caracole.config import load_config

      with open(sys.argv[1], encoding="utf-8") as f:
          cases = json.load(f)
      for case in cases:
          cfg = load_config(Path(case["config"]), env=case["env"])
          for key, value in case["paths"].items():
              assert getattr(cfg, key) == Path(value), (case["config"], key, getattr(cfg, key))
          print("generated caracole.toml loads:", case["config"])
      cfg = load_config(Path(cases[0]["config"]), env=cases[0]["env"])
      assert cfg.ntfy.url == "https://ntfy.example/caracole", cfg.ntfy.url
      assert cfg.spotify.client_id == "abc123" and cfg.spotify.playlists == ("Learn",)
      EOF

      # Without ntfy the notifier says so and succeeds.
      "$notifyUnconfigured" > notify.log
      grep -q "not configured" notify.log

      # caracole-admin runs as the units do: their user, folders, credentials and
      # sandbox, network included.
      grep -q -- "CARACOLE_CONFIG=$configFile" "$adminScript"
      grep -q -- "--property=User=caracole" "$adminScript"
      grep -q -- "LoadCredential=ntfy_token:/run/agenix/ntfy_token" "$adminScript"
      grep -q -- "'--setenv=NUMBA_CACHE_DIR=/var/lib/caracole/cache/numba'" "$adminScript"
      for property in \
        ProtectSystem=strict ProtectHome=yes PrivateTmp=yes PrivateDevices=yes \
        NoNewPrivileges=yes RestrictNamespaces=yes MemoryDenyWriteExecute=yes \
        LockPersonality=yes ProtectProc=invisible CapabilityBoundingSet= \
        SystemCallFilter=@system-service SystemCallFilter=~@privileged \
        RestrictAddressFamilies=AF_INET RestrictAddressFamilies=AF_UNIX \
        ReadWritePaths=/var/lib/caracole/library ReadWritePaths=/var/lib/caracole/state \
        ReadWritePaths=/var/lib/caracole/cache ReadOnlyPaths=-/var/lib/caracole/music \
        RequiresMountsFor=/var/lib/caracole/state; do
        grep -q -- "'--property=$property'" "$adminScript" \
          || { echo "caracole-admin lacks --property=$property" >&2; exit 1; }
      done
      lacks PrivateNetwork "$adminScript"
      # With the auto-chords package, as in its unit, torch may generate code.
      grep -q -- "'--property=MemoryDenyWriteExecute=no'" "$adminAutochordsScript"
      lacks MemoryDenyWriteExecute=yes "$adminAutochordsScript"

      # Moved to /data/caracole, caracole-admin opens what the units open there.
      grep -q -- "'--setenv=XDG_CACHE_HOME=/data/caracole/cache'" "$adminMovedScript"
      grep -q -- "'--setenv=NUMBA_CACHE_DIR=/data/caracole/cache/numba'" "$adminMovedScript"
      for property in \
        ReadWritePaths=/data/caracole/library ReadWritePaths=/data/caracole/state \
        ReadWritePaths=/data/caracole/cache ReadOnlyPaths=-/data/caracole/music \
        RequiresMountsFor=/data/caracole/library RequiresMountsFor=/data/caracole/state \
        RequiresMountsFor=/data/caracole/cache; do
        grep -q -- "'--property=$property'" "$adminMovedScript" \
          || { echo "caracole-admin lacks --property=$property" >&2; exit 1; }
      done
      # Nothing still names the default folders, or asks systemd for its own.
      for file in "$adminScript" "$adminMovedScript" "$movedRunUnitPath" \
        "$movedAutochordsUnitPath" "$movedNotifyUnitPath"; do
        lacks StateDirectory "$file"
        lacks CacheDirectory "$file"
      done
      for file in "$adminMovedScript" "$movedRunUnitPath" "$movedAutochordsUnitPath" \
        "$movedNotifyUnitPath" "$movedTmpfiles"; do
        lacks /var/lib/caracole "$file"
        lacks /var/cache/caracole "$file"
      done
      # The rendered tmpfiles.d lines, as systemd-tmpfiles reads them.
      grep -qx -- "'d' '/data/caracole' ':0710' ':caracole' ':caracole' '-' *" "$movedTmpfiles"
      grep -qx -- "'d' '/data/caracole/library' '2775' 'caracole' 'caracole' '-' *" "$movedTmpfiles"
      grep -qx -- "'d' '/data/caracole/state' '0700' 'caracole' 'caracole' '-' *" "$movedTmpfiles"
      grep -qx -- "'d' '/data/caracole/cache' '0700' 'caracole' 'caracole' '-' *" "$movedTmpfiles"

      # The auto-chords unit holds no secret.
      lacks LoadCredential "$autochordsUnitPath"
      grep -q -- "LoadCredential=ntfy_token:/run/agenix/ntfy_token" "$runUnitPath"

      # caracole-web, as systemd reads it: the token by credential, never on its command line.
      grep -q -- "LoadCredential=web_token:/run/agenix/caracole-web-token" "$webUnitPath"
      grep -q -- " serve --address 100.64.0.7 --port 8740 " "$webUnitPath"
      grep -qx -- "Restart=on-failure" "$webUnitPath"
      grep -qx -- "RestartMode=direct" "$webUnitPath"
      grep -qx -- "StartLimitIntervalSec=600" "$webUnitPath"
      grep -qx -- "StartLimitBurst=30" "$webUnitPath"
      lacks "--token-file" "$webUnitPath"
      lacks "ntfy_token" "$webUnitPath"
      lacks "spotify_client_secret" "$webUnitPath"

      mkdir -p $out/data-caracole
      cp "$configFile" $out/caracole.toml
      cp "$runUnitPath" $out/caracole.service
      cp "$timerUnitPath" $out/caracole.timer
      cp "$notifyUnitPath" $out/caracole-notify-failure.service
      cp "$autochordsUnitPath" $out/caracole-autochords.service
      cp "$webUnitPath" $out/caracole-web.service
      cp "$movedRunUnitPath" $out/data-caracole/caracole.service
      cp "$movedTmpfiles" $out/data-caracole/caracole-tmpfiles.conf
    ''
