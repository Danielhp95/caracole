# `nix build .#checks.x86_64-linux.module`: evaluates small NixOS systems that
# enable services.tabarr and fails, naming every broken expectation, when a unit
# setting the design relies on is wrong. The build then loads the generated
# tabarr.toml files with tabarr's own loader (an unknown key is fatal there), and
# runs the failure notifier with ntfy unset, which must succeed quietly.
#
# The systems run a stub `tabarr`, so this check neither builds nor tests the
# real package; `checks.package` does that.
{
  lib,
  pkgs,
  runCommand,
  writeShellScriptBin,
  python3,
  # The module under test: the flake's nixosModules.default.
  module,
  # What services.tabarr.package and autochords.package must default to.
  defaultPackage,
  autochordsPackage,
}:
let
  # tabarr's config loader, run against the generated file.
  loader = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../src/tabarr/__init__.py
      ../src/tabarr/config.py
    ];
  };

  stub = writeShellScriptBin "tabarr" "exit 0";
  toml = pkgs.formats.toml { };

  evalSystem =
    modules:
    (pkgs.nixos (
      [
        module
        {
          boot.isContainer = true;
          system.stateVersion = lib.trivial.release;
          services.tabarr.enable = true;
        }
      ]
      ++ modules
    )).config;

  stubbed.services.tabarr = {
    package = stub;
    autochords.package = stub;
  };

  # ntfy, Spotify and both static secrets, as the NUC will have them.
  configured.services.tabarr = {
    settings = {
      ntfy.url = "https://ntfy.example/tabarr";
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

  autochordsOn.services.tabarr.autochords = {
    enable = true;
    btcWeights = "/models/btc.pt";
    beatCheckpoint = "/models/beat_this.ckpt";
  };

  # What the packages' wrappers must default to: the fetched models, and the one
  # CJK font ChordPro 6.050.7 renders correctly (see src/tabarr/render.py).
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
    { services.tabarr.autochords.enable = true; }
  ];
  defaults = evalSystem [ ];
  # nix/module.nix imported on its own, without the flake's wrapper.
  standalone =
    (pkgs.nixos [
      ./module.nix
      {
        boot.isContainer = true;
        system.stateVersion = lib.trivial.release;
        services.tabarr.enable = true;
      }
    ]).config;
  # Everything tabarr keeps in /data/tabarr instead, with every unit on.
  moved = evalSystem [
    stubbed
    configured
    autochordsOn
    { services.tabarr.dataDir = "/data/tabarr"; }
  ];
  # The same, with the library somewhere else, on its own.
  libraryAlone = evalSystem [
    stubbed
    {
      services.tabarr = {
        dataDir = "/data/tabarr";
        libraryDir = "/srv/tabs";
      };
    }
  ];
  # Every folder set on its own, outside dataDir; the state at dataDir's path.
  noneInDataDir = evalSystem [
    stubbed
    {
      services.tabarr = {
        libraryDir = "/srv/tabs";
        musicDir = "/srv/music";
        stateDir = "/var/lib/tabarr";
        cacheDir = "/var/cache/tabarr";
      };
    }
  ];

  failedAssertions = cfg: map (a: a.message) (lib.filter (a: !a.assertion) cfg.assertions);
  # The failed assertions of a system with these services.tabarr settings.
  rejections =
    tabarr:
    failedAssertions (evalSystem [
      stubbed
      { services.tabarr = tabarr; }
    ]);
  # Whether one of the messages has all of these lines or words.
  says = words: lib.any (message: lib.all (word: lib.hasInfix word message) words);

  stateDirSet = rejections { settings.state_dir = "/elsewhere"; };
  cacheDirForced = rejections { settings.cache_dir = lib.mkForce "/elsewhere"; };
  dataDirSet = rejections { settings.data_dir = "/elsewhere"; };
  libraryDirSet = rejections { settings.library_dir = "/srv/tabs"; };
  libraryInHome = rejections { libraryDir = "/home/alice/Tabs"; };
  dataInRoot = rejections { dataDir = "/root/tabarr"; };
  cacheInVarTmp = rejections { cacheDir = "/var/tmp/tabarr"; };
  dataRelative = rejections { dataDir = "data/tabarr"; };
  stateWithSlash = rejections { stateDir = "/data/tabarr/state/"; };
  musicWithDots = rejections { musicDir = "/data/tabarr/../music"; };
  libraryWithSpace = rejections { libraryDir = "/srv/my tabs"; };
  stateInLibrary = rejections { stateDir = "/var/lib/tabarr/library/.state"; };
  libraryInState = rejections { stateDir = "/var/lib/tabarr"; };
  stateIsCache = rejections { cacheDir = "/var/lib/tabarr/state"; };

  # The folders a system's units must open: the library, music, state and cache.
  layout = data: {
    library = "${data}/library";
    music = "${data}/music";
    state = "${data}/state";
    cache = "${data}/cache";
  };
  defaultLayout = layout "/var/lib/tabarr";
  movedLayout = layout "/data/tabarr";
  libraryAloneLayout = movedLayout // {
    library = "/srv/tabs";
  };

  # Whether a system has these folders, as its options and as the settings the
  # generated tabarr.toml comes from, with no data_dir there.
  hasLayout =
    system: dirs:
    let
      tabarr = system.services.tabarr;
    in
    tabarr.libraryDir == dirs.library
    && tabarr.musicDir == dirs.music
    && tabarr.stateDir == dirs.state
    && tabarr.cacheDir == dirs.cache
    && tabarr.settings.library_dir == dirs.library
    && tabarr.settings.music_dir == dirs.music
    && tabarr.settings.state_dir == dirs.state
    && tabarr.settings.cache_dir == dirs.cache
    && !(tabarr.settings ? data_dir);

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

  # The failure notifier opens no folder of tabarr's.
  opensNothing =
    unit:
    let
      sc = unit.serviceConfig;
    in
    !(sc ? ReadWritePaths || sc ? ReadOnlyPaths || sc ? StateDirectory || sc ? CacheDirectory);

  # The folders tmpfiles makes: tabarr's own, and dataDir when it holds any.
  makesFolders =
    system: dirs: data:
    let
      rules = system.systemd.tmpfiles.settings.tabarr;
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
    && is dirs.library "2775" "tabarr"
    && is dirs.state "0700" "tabarr"
    && is dirs.cache "0700" "tabarr"
    # Created as tabarr:tabarr 0710, so the group gets through to the library
    # and the music; ":" leaves the owner and mode of one that exists alone.
    && (data == null || is data ":0710" ":tabarr");

  configFile = toml.generate "tabarr.toml" nuc.services.tabarr.settings;
  movedConfigFile = toml.generate "tabarr.toml" moved.services.tabarr.settings;
  run = nuc.systemd.services.tabarr;
  runSc = run.serviceConfig;
  timer = nuc.systemd.timers.tabarr;
  notify = nuc.systemd.services.tabarr-notify-failure;
  autochords = nucAutochords.systemd.services.tabarr-autochords;
  autochordsSc = autochords.serviceConfig;
  autochordsPackageModels = nucModelsFromPackage.systemd.services.tabarr-autochords;
  findAdmin =
    system: lib.findFirst (p: lib.getName p == "tabarr-admin") null system.environment.systemPackages;
  admin = findAdmin nuc;
  adminAutochords = findAdmin nucAutochords;
  adminMoved = findAdmin moved;
  # The rendered tmpfiles.d file of the moved system.
  movedTmpfiles = lib.findFirst (p: p.name == "tabarr.conf") null moved.systemd.tmpfiles.packages;

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

  sameUser = sc: sc.User == "tabarr" && sc.Group == "tabarr" && sc.UMask == "0007";

  expectations = {
    # `--config` is a root option of the CLI (src/tabarr/cli.py), so it goes
    # before the subcommand: `tabarr run --config X` is a usage error there.
    "tabarr.service runs `tabarr --config <generated tabarr.toml> run`" =
      runSc.ExecStart == "${lib.getExe stub} --config ${configFile} run";
    "tabarr.service is a oneshot" = runSc.Type == "oneshot";
    "tabarr.service runs as tabarr, with a group-writable umask" = sameUser runSc;
    "by default, the library, music, state and cache are in /var/lib/tabarr, and the generated settings name them" =
      nuc.services.tabarr.dataDir == "/var/lib/tabarr" && hasLayout nuc defaultLayout;
    "tabarr.service writes only the library, state and cache in /var/lib/tabarr, reads the music if it exists, waits for their mounts and caches there" =
      opens run defaultLayout;
    "tabarr.service has MemoryDenyWriteExecute and RestrictNamespaces" =
      runSc.MemoryDenyWriteExecute && runSc.RestrictNamespaces;
    "tabarr.service has the rest of the plan's hardening" = hardened runSc;
    "tabarr.service loads the ntfy_token and spotify_client_secret credentials" =
      lib.elem "ntfy_token:/run/agenix/ntfy_token" runSc.LoadCredential
      && lib.elem "spotify_client_secret:/run/agenix/spotify_client_secret" runSc.LoadCredential;
    "tabarr.service notifies on failure" = run.onFailure == [ "tabarr-notify-failure.service" ];
    "tabarr.service waits for the network" =
      lib.elem "network-online.target" run.wants && lib.elem "network-online.target" run.after;
    "tabarr.service starts nothing on success without auto-chords" = run.onSuccess == [ ];
    "tabarr.timer fires at the schedule, catches up and spreads the start" =
      timer.timerConfig.OnCalendar == "*-*-* 03:30"
      && timer.timerConfig.Persistent == true
      && timer.timerConfig.RandomizedDelaySec == "45m"
      && lib.elem "timers.target" timer.wantedBy;
    "tabarr-notify-failure.service is a oneshot that loads only ntfy_token" =
      notify.serviceConfig.Type == "oneshot"
      && notify.serviceConfig.LoadCredential == [ "ntfy_token:/run/agenix/ntfy_token" ];
    "tabarr-notify-failure.service is hardened, under a user of its own" =
      hardened notify.serviceConfig && notify.serviceConfig.DynamicUser;
    "tabarr-notify-failure.service opens none of tabarr's folders, wherever they are" =
      opensNothing notify && opensNothing moved.systemd.services.tabarr-notify-failure;
    "tabarr-autochords.service exists only when enabled" = !(nuc.systemd.services ? tabarr-autochords);
    "tabarr-autochords.service has PrivateNetwork and no MemoryDenyWriteExecute" =
      autochordsSc.PrivateNetwork == true && autochordsSc.MemoryDenyWriteExecute == false;
    # btc.py and librosa's numba need a writable cache; HOME is read-only.
    "tabarr-autochords.service opens the same folders as tabarr.service, numba's cache in the cache" =
      opens autochords defaultLayout;
    "tabarr-autochords.service runs `tabarr --config <generated tabarr.toml> autochords`" =
      autochordsSc.ExecStart == "${lib.getExe stub} --config ${configFile} autochords";
    "tabarr-autochords.service runs as tabarr, with a group-writable umask" = sameUser autochordsSc;
    # It reads no secret, and its parsers (FFmpeg, libsndfile) see the most outside data.
    "tabarr-autochords.service loads no credentials" =
      !(autochordsSc ? LoadCredential) || autochordsSc.LoadCredential == [ ];
    "tabarr-autochords.service is otherwise hardened the same way" =
      hardened autochordsSc && autochordsSc.Type == "oneshot";
    "tabarr-autochords.service gets the model paths" =
      autochords.environment.TABARR_BTC_WEIGHTS == "/models/btc.pt"
      && autochords.environment.TABARR_BEAT_CHECKPOINT == "/models/beat_this.ckpt";
    # Unset, so the package wrapper's --set-default values apply.
    "tabarr-autochords.service leaves the model paths to the package when the options are null" =
      !(autochordsPackageModels.environment ? TABARR_BTC_WEIGHTS)
      && !(autochordsPackageModels.environment ? TABARR_BEAT_CHECKPOINT)
      && failedAssertions nucModelsFromPackage == [ ];
    "the auto-chords package points at the fetched BTC weights and beat_this checkpoint" =
      setsDefault autochordsPackage "TABARR_BTC_WEIGHTS" "${models.btcWeights}"
      && setsDefault autochordsPackage "TABARR_BEAT_CHECKPOINT" "${models.beatThisCheckpoint}";
    "the default package carries no model files" =
      !(setsAny defaultPackage "TABARR_BTC_WEIGHTS")
      && !(setsAny defaultPackage "TABARR_BEAT_CHECKPOINT");
    "both packages default TABARR_CJK_FONT to lxgw-fusionkai's FusionKaiJ-Regular.ttf" =
      setsDefault defaultPackage "TABARR_CJK_FONT" fusionKai
      && setsDefault autochordsPackage "TABARR_CJK_FONT" fusionKai;
    "tabarr-autochords.service follows a successful run and notifies on failure" =
      nucAutochords.systemd.services.tabarr.onSuccess == [ "tabarr-autochords.service" ]
      && autochords.onFailure == [ "tabarr-notify-failure.service" ];
    "the tabarr system user and group exist" =
      nuc.users.users.tabarr.isSystemUser
      && nuc.users.users.tabarr.group == "tabarr"
      && nuc.users.groups ? tabarr;
    "tmpfiles creates /var/lib/tabarr 0710, the library 2775 and the state and cache 0700, all tabarr:tabarr, and leaves the music alone" =
      makesFolders nuc defaultLayout "/var/lib/tabarr";
    "with dataDir = /data/tabarr, the library, music, state and cache follow it, and the generated settings name them" =
      hasLayout moved movedLayout;
    "with dataDir = /data/tabarr, both units write only its library, state and cache, and read its music" =
      opens moved.systemd.services.tabarr movedLayout
      && opens moved.systemd.services.tabarr-autochords movedLayout;
    "with dataDir = /data/tabarr, tmpfiles creates it and its folders, and nothing in /var/lib" =
      makesFolders moved movedLayout
        "/data/tabarr";
    "with dataDir = /data/tabarr, both units run with the generated tabarr.toml" =
      moved.systemd.services.tabarr.serviceConfig.ExecStart
      == "${lib.getExe stub} --config ${movedConfigFile} run"
      &&
        moved.systemd.services.tabarr-autochords.serviceConfig.ExecStart
        == "${lib.getExe stub} --config ${movedConfigFile} autochords";
    "libraryDir set on its own moves the library alone" =
      hasLayout libraryAlone libraryAloneLayout
      && opens libraryAlone.systemd.services.tabarr libraryAloneLayout
      && makesFolders libraryAlone libraryAloneLayout "/data/tabarr";
    # The state is /var/lib/tabarr itself: one rule for it, 0700.
    "dataDir holding none of the folders is left alone" =
      hasLayout noneInDataDir {
        library = "/srv/tabs";
        music = "/srv/music";
        state = "/var/lib/tabarr";
        cache = "/var/cache/tabarr";
      }
      && makesFolders noneInDataDir {
        library = "/srv/tabs";
        state = "/var/lib/tabarr";
        cache = "/var/cache/tabarr";
      } null;
    "tabarr-admin is installed" = admin != null && adminMoved != null;
    "the configured systems pass every assertion" = lib.all (system: failedAssertions system == [ ]) [
      nuc
      nucAutochords
      moved
      libraryAlone
      noneInDataDir
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
      ''dataDir = "/root/tabarr";''
      ''stateDir = "/root/tabarr/state";''
    ] dataInRoot;
    "a cache under /var/tmp, which the sandbox hides, is rejected" = says [
      "PrivateTmp"
      ''cacheDir = "/var/tmp/tabarr";''
    ] cacheInVarTmp;
    "a relative dataDir is rejected" = says [
      "absolute"
      ''dataDir = "data/tabarr";''
    ] dataRelative;
    "a stateDir with a trailing slash is rejected" = says [
      "absolute"
      ''stateDir = "/data/tabarr/state/";''
    ] stateWithSlash;
    "a musicDir with a .. part is rejected" = says [
      "absolute"
      ''musicDir = "/data/tabarr/../music";''
    ] musicWithDots;
    "a libraryDir with whitespace is rejected" = says [
      "absolute"
      ''libraryDir = "/srv/my tabs";''
    ] libraryWithSpace;
    "a state folder inside the library is rejected" = says [
      "none inside another"
      ''stateDir ("/var/lib/tabarr/library/.state") is inside libraryDir ("/var/lib/tabarr/library")''
    ] stateInLibrary;
    "a library inside the state folder is rejected" = says [
      "none inside another"
      ''libraryDir ("/var/lib/tabarr/library") is inside stateDir ("/var/lib/tabarr")''
    ] libraryInState;
    "one folder for both the state and the cache is rejected" = says [
      "none inside another"
      ''stateDir and cacheDir are both "/var/lib/tabarr/state"''
    ] stateIsCache;
    "the package defaults to this flake's package" =
      defaults.services.tabarr.package.drvPath == defaultPackage.drvPath;
    "the auto-chords package defaults to this flake's autochords package" =
      defaults.services.tabarr.autochords.package.drvPath == autochordsPackage.drvPath;
    "without the flake, the module builds the same packages from nix/package.nix" =
      standalone.services.tabarr.package.drvPath == defaultPackage.drvPath
      && standalone.services.tabarr.autochords.package.drvPath == autochordsPackage.drvPath;
    "the whole system evaluates" =
      nucAutochords.system.build.toplevel.drvPath != "" && moved.system.build.toplevel.drvPath != "";
  };

  broken = lib.attrNames (lib.filterAttrs (_: ok: !ok) expectations);

  unitText = cfg: name: cfg.systemd.units.${name}.text;

  # The generated files, the environment each unit gives tabarr, and the
  # folders tabarr must then use: the file's explicit paths win over the
  # unit's XDG_CACHE_HOME.
  loads = system: dirs: {
    config = toml.generate "tabarr.toml" system.services.tabarr.settings;
    env = {
      HOME = "/var/empty";
      inherit (system.systemd.services.tabarr.environment) XDG_CACHE_HOME NUMBA_CACHE_DIR;
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
    tabarr module check failed:
    ${lib.concatMapStrings (name: "  - ${name}\n") broken}''
else
  runCommand "tabarr-module-check"
    {
      nativeBuildInputs = [ python3 ];
      inherit configFile;
      notifyUnconfigured = bare.systemd.services.tabarr-notify-failure.serviceConfig.ExecStart;
      adminScript = lib.getExe admin;
      adminAutochordsScript = lib.getExe adminAutochords;
      adminMovedScript = lib.getExe adminMoved;
      movedTmpfiles = "${movedTmpfiles}/lib/tmpfiles.d/tabarr.conf";
      passAsFile = [
        "loadCases"
        "runUnit"
        "timerUnit"
        "notifyUnit"
        "autochordsUnit"
        "movedRunUnit"
        "movedAutochordsUnit"
        "movedNotifyUnit"
      ];
      loadCases = builtins.toJSON [
        (loads nuc defaultLayout)
        (loads moved movedLayout)
        (loads libraryAlone libraryAloneLayout)
      ];
      runUnit = unitText nuc "tabarr.service";
      timerUnit = unitText nuc "tabarr.timer";
      notifyUnit = unitText nuc "tabarr-notify-failure.service";
      autochordsUnit = unitText nucAutochords "tabarr-autochords.service";
      movedRunUnit = unitText moved "tabarr.service";
      movedAutochordsUnit = unitText moved "tabarr-autochords.service";
      movedNotifyUnit = unitText moved "tabarr-notify-failure.service";
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

      # The generated files must load with tabarr's own strict loader, in the
      # units' environment, and name the folders the units open.
      PYTHONPATH=${loader}/src python3 - "$loadCasesPath" <<'EOF'
      import json
      import sys
      from pathlib import Path

      from tabarr.config import load_config

      with open(sys.argv[1], encoding="utf-8") as f:
          cases = json.load(f)
      for case in cases:
          cfg = load_config(Path(case["config"]), env=case["env"])
          for key, value in case["paths"].items():
              assert getattr(cfg, key) == Path(value), (case["config"], key, getattr(cfg, key))
          print("generated tabarr.toml loads:", case["config"])
      cfg = load_config(Path(cases[0]["config"]), env=cases[0]["env"])
      assert cfg.ntfy.url == "https://ntfy.example/tabarr", cfg.ntfy.url
      assert cfg.spotify.client_id == "abc123" and cfg.spotify.playlists == ("Learn",)
      EOF

      # Without ntfy the notifier says so and succeeds.
      "$notifyUnconfigured" > notify.log
      grep -q "not configured" notify.log

      # tabarr-admin runs as the units do: their user, folders, credentials and
      # sandbox, network included.
      grep -q -- "TABARR_CONFIG=$configFile" "$adminScript"
      grep -q -- "--property=User=tabarr" "$adminScript"
      grep -q -- "LoadCredential=ntfy_token:/run/agenix/ntfy_token" "$adminScript"
      grep -q -- "'--setenv=NUMBA_CACHE_DIR=/var/lib/tabarr/cache/numba'" "$adminScript"
      for property in \
        ProtectSystem=strict ProtectHome=yes PrivateTmp=yes PrivateDevices=yes \
        NoNewPrivileges=yes RestrictNamespaces=yes MemoryDenyWriteExecute=yes \
        LockPersonality=yes ProtectProc=invisible CapabilityBoundingSet= \
        SystemCallFilter=@system-service SystemCallFilter=~@privileged \
        RestrictAddressFamilies=AF_INET RestrictAddressFamilies=AF_UNIX \
        ReadWritePaths=/var/lib/tabarr/library ReadWritePaths=/var/lib/tabarr/state \
        ReadWritePaths=/var/lib/tabarr/cache ReadOnlyPaths=-/var/lib/tabarr/music \
        RequiresMountsFor=/var/lib/tabarr/state; do
        grep -q -- "'--property=$property'" "$adminScript" \
          || { echo "tabarr-admin lacks --property=$property" >&2; exit 1; }
      done
      lacks PrivateNetwork "$adminScript"
      # With the auto-chords package, as in its unit, torch may generate code.
      grep -q -- "'--property=MemoryDenyWriteExecute=no'" "$adminAutochordsScript"
      lacks MemoryDenyWriteExecute=yes "$adminAutochordsScript"

      # Moved to /data/tabarr, tabarr-admin opens what the units open there.
      grep -q -- "'--setenv=XDG_CACHE_HOME=/data/tabarr/cache'" "$adminMovedScript"
      grep -q -- "'--setenv=NUMBA_CACHE_DIR=/data/tabarr/cache/numba'" "$adminMovedScript"
      for property in \
        ReadWritePaths=/data/tabarr/library ReadWritePaths=/data/tabarr/state \
        ReadWritePaths=/data/tabarr/cache ReadOnlyPaths=-/data/tabarr/music \
        RequiresMountsFor=/data/tabarr/library RequiresMountsFor=/data/tabarr/state \
        RequiresMountsFor=/data/tabarr/cache; do
        grep -q -- "'--property=$property'" "$adminMovedScript" \
          || { echo "tabarr-admin lacks --property=$property" >&2; exit 1; }
      done
      # Nothing still names the default folders, or asks systemd for its own.
      for file in "$adminScript" "$adminMovedScript" "$movedRunUnitPath" \
        "$movedAutochordsUnitPath" "$movedNotifyUnitPath"; do
        lacks StateDirectory "$file"
        lacks CacheDirectory "$file"
      done
      for file in "$adminMovedScript" "$movedRunUnitPath" "$movedAutochordsUnitPath" \
        "$movedNotifyUnitPath" "$movedTmpfiles"; do
        lacks /var/lib/tabarr "$file"
        lacks /var/cache/tabarr "$file"
      done
      # The rendered tmpfiles.d lines, as systemd-tmpfiles reads them.
      grep -qx -- "'d' '/data/tabarr' ':0710' ':tabarr' ':tabarr' '-' *" "$movedTmpfiles"
      grep -qx -- "'d' '/data/tabarr/library' '2775' 'tabarr' 'tabarr' '-' *" "$movedTmpfiles"
      grep -qx -- "'d' '/data/tabarr/state' '0700' 'tabarr' 'tabarr' '-' *" "$movedTmpfiles"
      grep -qx -- "'d' '/data/tabarr/cache' '0700' 'tabarr' 'tabarr' '-' *" "$movedTmpfiles"

      # The auto-chords unit holds no secret.
      lacks LoadCredential "$autochordsUnitPath"
      grep -q -- "LoadCredential=ntfy_token:/run/agenix/ntfy_token" "$runUnitPath"

      mkdir -p $out/data-tabarr
      cp "$configFile" $out/tabarr.toml
      cp "$runUnitPath" $out/tabarr.service
      cp "$timerUnitPath" $out/tabarr.timer
      cp "$notifyUnitPath" $out/tabarr-notify-failure.service
      cp "$autochordsUnitPath" $out/tabarr-autochords.service
      cp "$movedRunUnitPath" $out/data-tabarr/tabarr.service
      cp "$movedTmpfiles" $out/data-tabarr/tabarr-tmpfiles.conf
    ''
