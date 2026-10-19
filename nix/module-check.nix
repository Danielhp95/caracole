# `nix build .#checks.x86_64-linux.module`: evaluates small NixOS systems that
# enable services.tabarr and fails, naming every broken expectation, when a unit
# setting the design relies on is wrong. The build then loads the generated
# tabarr.toml with tabarr's own loader (an unknown key is fatal there), and runs
# the failure notifier with ntfy unset, which must succeed quietly.
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
  stateDirSet = evalSystem [
    stubbed
    { services.tabarr.settings.state_dir = "/elsewhere"; }
  ];
  libraryInHome = evalSystem [
    stubbed
    { services.tabarr.libraryDir = "/home/alice/Tabs"; }
  ];

  failedAssertions = cfg: map (a: a.message) (lib.filter (a: !a.assertion) cfg.assertions);

  configFile = toml.generate "tabarr.toml" nuc.services.tabarr.settings;
  run = nuc.systemd.services.tabarr;
  runSc = run.serviceConfig;
  timer = nuc.systemd.timers.tabarr;
  notify = nuc.systemd.services.tabarr-notify-failure;
  autochords = nucAutochords.systemd.services.tabarr-autochords;
  autochordsSc = autochords.serviceConfig;
  autochordsPackageModels = nucModelsFromPackage.systemd.services.tabarr-autochords;
  libraryRule = nuc.systemd.tmpfiles.settings.tabarr."/srv/tabs".d;
  findAdmin =
    system: lib.findFirst (p: lib.getName p == "tabarr-admin") null system.environment.systemPackages;
  admin = findAdmin nuc;
  adminAutochords = findAdmin nucAutochords;

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

  sameUserAndPaths =
    sc:
    sc.User == "tabarr"
    && sc.Group == "tabarr"
    && sc.StateDirectory == "tabarr"
    && sc.CacheDirectory == "tabarr"
    && sc.ReadWritePaths == [ "/srv/tabs" ]
    && sc.ReadOnlyPaths == [ "-/srv/music" ];

  expectations = {
    # `--config` is a root option of the CLI (src/tabarr/cli.py), so it goes
    # before the subcommand: `tabarr run --config X` is a usage error there.
    "tabarr.service runs `tabarr --config <generated tabarr.toml> run`" =
      runSc.ExecStart == "${lib.getExe stub} --config ${configFile} run";
    "tabarr.service is a oneshot" = runSc.Type == "oneshot";
    "tabarr.service runs as tabarr with its state, cache, library and music paths" =
      sameUserAndPaths runSc;
    "tabarr.service has MemoryDenyWriteExecute and RestrictNamespaces" =
      runSc.MemoryDenyWriteExecute && runSc.RestrictNamespaces;
    "tabarr.service has the rest of the plan's hardening" = hardened runSc;
    "tabarr.service reads only /srv/music, and only if it exists" =
      runSc.ReadOnlyPaths == [ "-/srv/music" ];
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
    # librosa's numba will not even import without a writable cache.
    "the tabarr units cache under /var/cache/tabarr, not the read-only HOME" =
      run.environment.NUMBA_CACHE_DIR == "/var/cache/tabarr/numba"
      && autochords.environment.NUMBA_CACHE_DIR == "/var/cache/tabarr/numba"
      && autochords.environment.XDG_CACHE_HOME == "/var/cache/tabarr";
    "tabarr-autochords.service exists only when enabled" = !(nuc.systemd.services ? tabarr-autochords);
    "tabarr-autochords.service has PrivateNetwork and no MemoryDenyWriteExecute" =
      autochordsSc.PrivateNetwork == true && autochordsSc.MemoryDenyWriteExecute == false;
    # btc.py and librosa's numba need a writable cache; HOME is read-only.
    "tabarr-autochords.service has the tabarr cache directory, with numba's cache in it" =
      autochordsSc.CacheDirectory == "tabarr"
      && lib.hasPrefix "/var/cache/tabarr/" autochords.environment.NUMBA_CACHE_DIR;
    "tabarr-autochords.service runs `tabarr --config <generated tabarr.toml> autochords`" =
      autochordsSc.ExecStart == "${lib.getExe stub} --config ${configFile} autochords";
    "tabarr-autochords.service runs as tabarr with the same paths" = sameUserAndPaths autochordsSc;
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
    "tmpfiles creates the library as tabarr:tabarr 2775" =
      libraryRule.mode == "2775" && libraryRule.user == "tabarr" && libraryRule.group == "tabarr";
    "the generated settings carry libraryDir and musicDir" =
      nuc.services.tabarr.settings.library_dir == "/srv/tabs"
      && nuc.services.tabarr.settings.music_dir == "/srv/music";
    "tabarr-admin is installed" = admin != null;
    "the configured systems pass every assertion" =
      failedAssertions nuc == [ ] && failedAssertions nucAutochords == [ ];
    "settings.state_dir is rejected" = lib.any (lib.hasInfix "state_dir") (
      failedAssertions stateDirSet
    );
    "a library under /home, which the sandbox hides, is rejected" =
      lib.any (lib.hasInfix "ProtectHome") (failedAssertions libraryInHome);
    "the package defaults to this flake's package" =
      defaults.services.tabarr.package.drvPath == defaultPackage.drvPath;
    "the auto-chords package defaults to this flake's autochords package" =
      defaults.services.tabarr.autochords.package.drvPath == autochordsPackage.drvPath;
    "without the flake, the module builds the same packages from nix/package.nix" =
      standalone.services.tabarr.package.drvPath == defaultPackage.drvPath
      && standalone.services.tabarr.autochords.package.drvPath == autochordsPackage.drvPath;
    "the whole system evaluates" = nucAutochords.system.build.toplevel.drvPath != "";
  };

  broken = lib.attrNames (lib.filterAttrs (_: ok: !ok) expectations);

  unitText = cfg: name: cfg.systemd.units.${name}.text;
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
      passAsFile = [
        "runUnit"
        "timerUnit"
        "notifyUnit"
        "autochordsUnit"
      ];
      runUnit = unitText nuc "tabarr.service";
      timerUnit = unitText nuc "tabarr.timer";
      notifyUnit = unitText nuc "tabarr-notify-failure.service";
      autochordsUnit = unitText nucAutochords "tabarr-autochords.service";
    }
    ''
      # The generated file must load with tabarr's own strict loader, with the
      # directories systemd hands the unit.
      PYTHONPATH=${loader}/src python3 - "$configFile" <<'EOF'
      import sys
      from pathlib import Path

      from tabarr.config import load_config

      env = {
          "HOME": "/var/empty",
          "STATE_DIRECTORY": "/var/lib/tabarr",
          "CACHE_DIRECTORY": "/var/cache/tabarr",
      }
      cfg = load_config(Path(sys.argv[1]), env=env)
      assert cfg.library_dir == Path("/srv/tabs"), cfg.library_dir
      assert cfg.music_dir == Path("/srv/music"), cfg.music_dir
      assert cfg.state_dir == Path("/var/lib/tabarr"), cfg.state_dir
      assert cfg.cache_dir == Path("/var/cache/tabarr"), cfg.cache_dir
      assert cfg.wanted_file == Path("/srv/tabs/wanted.txt"), cfg.wanted_file
      assert cfg.overrides_file == Path("/srv/tabs/overrides.toml"), cfg.overrides_file
      assert cfg.ntfy.url == "https://ntfy.example/tabarr", cfg.ntfy.url
      assert cfg.spotify.client_id == "abc123" and cfg.spotify.playlists == ("Learn",)
      print("generated tabarr.toml loads:", sys.argv[1])
      EOF

      # Without ntfy the notifier says so and succeeds.
      "$notifyUnconfigured" > notify.log
      grep -q "not configured" notify.log

      # tabarr-admin runs as the units do: their user, state, credentials and
      # paths, and their sandbox, network included.
      grep -q -- "TABARR_CONFIG=$configFile" "$adminScript"
      grep -q -- "--property=User=tabarr" "$adminScript"
      grep -q -- "--property=StateDirectory=tabarr" "$adminScript"
      grep -q -- "--property=CacheDirectory=tabarr" "$adminScript"
      grep -q -- "LoadCredential=ntfy_token:/run/agenix/ntfy_token" "$adminScript"
      grep -q -- "NUMBA_CACHE_DIR=/var/cache/tabarr/numba" "$adminScript"
      for property in \
        ProtectSystem=strict ProtectHome=yes PrivateTmp=yes PrivateDevices=yes \
        NoNewPrivileges=yes RestrictNamespaces=yes MemoryDenyWriteExecute=yes \
        LockPersonality=yes ProtectProc=invisible CapabilityBoundingSet= \
        SystemCallFilter=@system-service SystemCallFilter=~@privileged \
        RestrictAddressFamilies=AF_INET RestrictAddressFamilies=AF_UNIX \
        ReadWritePaths=/srv/tabs ReadOnlyPaths=-/srv/music; do
        grep -q -- "'--property=$property'" "$adminScript" \
          || { echo "tabarr-admin lacks --property=$property" >&2; exit 1; }
      done
      ! grep -q -- "PrivateNetwork" "$adminScript"
      # With the auto-chords package, as in its unit, torch may generate code.
      grep -q -- "'--property=MemoryDenyWriteExecute=no'" "$adminAutochordsScript"
      ! grep -q -- "MemoryDenyWriteExecute=yes" "$adminAutochordsScript"

      # The auto-chords unit holds no secret.
      ! grep -q -- "LoadCredential" "$autochordsUnitPath"
      grep -q -- "LoadCredential=ntfy_token:/run/agenix/ntfy_token" "$runUnitPath"

      mkdir -p $out
      cp "$configFile" $out/tabarr.toml
      cp "$runUnitPath" $out/tabarr.service
      cp "$timerUnitPath" $out/tabarr.timer
      cp "$notifyUnitPath" $out/tabarr-notify-failure.service
      cp "$autochordsUnitPath" $out/tabarr-autochords.service
    ''
