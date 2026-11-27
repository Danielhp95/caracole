# ONNX Runtime 1.27.1 for the phone's chords (the chords-on-the-phone design's §3.5, Gate R: the owner's "Build 1.27.1"
# of 2026-11-27), built from its source with no network: android/scripts/build-onnxruntime.sh for each ABI the app ships,
# then an AAR of the two (its Java bindings compiled from the same tree) in a Maven folder of its own, which
# android/settings.gradle.kts reads in Maven Central's place (the variable android/flake.nix sets for every shell).
#
# The source is nixpkgs' pin of the tag v1.27.1 (its fixed-output hash, below), which cache.nixos.org serves:
# github.com/microsoft/onnxruntime answers 404 since 2026-11. Each CMake dependency is the zip deps.txt names, pinned
# here by its SHA-256 (CMake checks deps.txt's SHA-1 again as it unpacks it), in the local mirror ORT's CMake reads.
{
  lib,
  stdenv,
  fetchFromGitHub,
  fetchurl,
  linkFarm,
  runCommand,
  cmake,
  ninja,
  python3,
  protobuf_21,
  jdk17_headless,
  # The NDK, r28c (android/flake.nix's ndkVersion).
  ndk,
  abis ? [
    "arm64-v8a"
    "x86_64"
  ],
}:

let
  version = "1.27.1";

  src = fetchFromGitHub {
    owner = "microsoft";
    repo = "onnxruntime";
    tag = "v${version}";
    fetchSubmodules = true;
    hash = "sha256-i2u/JnfbJ/srsZY3ATb2YsBBXEhTGhatsr3+9eHVV3M=";
  };

  # deps.txt's zips that a CPU build for Android unpacks.
  deps = [
    { url = "https://github.com/abseil/abseil-cpp/archive/refs/tags/20250814.0.zip"; hash = "sha256-sr3PZoLYy1PfNlvMXWwxiiLlWCHZl4oQ/bYUBMAm2v8="; }
    { url = "https://github.com/HowardHinnant/date/archive/refs/tags/v3.0.1.zip"; hash = "sha256-9DALlvejBNTvm/bg+j3tchWffy0PYFvd4+AwoNunz58="; }
    { url = "https://github.com/eigen-mirror/eigen/archive/1d8b82b0740839c0de7f1242a3585e3390ff5f33/eigen-1d8b82b0740839c0de7f1242a3585e3390ff5f33.zip"; hash = "sha256-amDXY1H5cTJmna7rch1r8UsAgQGIOtLWh6MgHFxGHrA="; }
    { url = "https://github.com/google/flatbuffers/archive/refs/tags/v23.5.26.zip"; hash = "sha256-V71YDAdy/RpybDSri/BTJSk7xfnBZQYKiYr6H+7rleE="; }
    { url = "https://github.com/nlohmann/json/archive/refs/tags/v3.11.3.zip"; hash = "sha256-BAIrBdgG61/3MCPCgLaGl9Erk+G3JnoLIqGjnsdXgGk="; }
    { url = "https://github.com/microsoft/GSL/archive/refs/tags/v4.2.1.zip"; hash = "sha256-ySkdlfX25cVhmQ0GpYmwHYnlU9DzZvDOcj3ReI56YHY="; }
    { url = "https://github.com/boostorg/mp11/archive/refs/tags/boost-1.82.0.zip"; hash = "sha256-gUMb3ETEOaMk4CwH7QZ/j1VkGf2G8ti0hv9WjfaqyJk="; }
    { url = "https://github.com/onnx/onnx/archive/refs/tags/v1.21.0.zip"; hash = "sha256-uLVlcNlOzOSf7pTmOA20VrtCA1ciuWcBXJ3WRZNZQz4="; }
    { url = "https://github.com/protocolbuffers/protobuf/archive/refs/tags/v21.12.zip"; hash = "sha256-ajG2Yt6usKw15ih72i8zabGYNubJ+IKNTaRENG9CApg="; }
    { url = "https://github.com/pytorch/cpuinfo/archive/403d652dca4c1046e8145950b1c0997a9f748b57.zip"; hash = "sha256-NX2YJLjT9MBfCyKH5FtODZgkIsJ7Z7lo6yOmQ9xSteI="; }
    { url = "https://github.com/google/re2/archive/refs/tags/2024-07-02.zip"; hash = "sha256-qDX+Vfvc2OgPOFhKsi0IQGYsZ/L+s2vWeUAtqWQdxx4="; }
    { url = "https://github.com/dcleblanc/SafeInt/archive/refs/tags/3.0.28.zip"; hash = "sha256-P/vZov3/Rdp32j5yaemqUS6kO+1cOM6P2PPRBooDLD8="; }
    { url = "https://github.com/dmlc/dlpack/archive/5c210da409e7f1e51ddf445134a4376fdbd70d7d.zip"; hash = "sha256-FOiz8Dq3Rh9Ws/p//UrPtuamX4ldxLUFSMqyWSKa/L0="; }
  ];

  mirror = linkFarm "onnxruntime-${version}-deps" (
    map (d: {
      name = lib.removePrefix "https://" d.url;
      path = fetchurl { inherit (d) url hash; };
    }) deps
  );

  # reduce_op_kernels.py reads its config through ORT's tools, which import flatbuffers.
  python = python3.withPackages (ps: [ ps.flatbuffers ]);

  ops = ../android/ml/onnxruntime-ops.config;
  script = ../android/scripts/build-onnxruntime.sh;
  # Any fixed time (1980-01-01T00:00:02Z, the earliest a jar takes): the outputs never depend on the clock.
  epoch = "315532802";

  native =
    abi:
    stdenv.mkDerivation {
      pname = "onnxruntime-android-${abi}";
      inherit version;
      dontUnpack = true;
      nativeBuildInputs = [
        cmake
        ninja
        python
        jdk17_headless
      ];
      dontUseCmakeConfigure = true;
      dontUseNinjaBuild = true;
      dontUseNinjaInstall = true;
      buildPhase = ''
        runHook preBuild
        export SOURCE_DATE_EPOCH=${epoch} HOME=$TMPDIR
        bash ${script} --source ${src} --mirror ${mirror} --ndk ${ndk} --protoc ${lib.getExe protobuf_21} \
          --ops ${ops} --abi ${abi} --work $TMPDIR/ort --out $out --jobs ''${NIX_BUILD_CORES:-8}
        runHook postBuild
      '';
      dontInstall = true;
      # Android's ELF files, stripped already: no patchelf, no host strip.
      dontFixup = true;
    };

  natives = lib.genAttrs abis native;

  group = "io.github.danielhp95.caracole";
  artifact = "onnxruntime-android";
  folder = "maven/${lib.replaceStrings [ "." ] [ "/" ] group}/${artifact}/${version}";
in
runCommand "onnxruntime-android-${version}"
  {
    nativeBuildInputs = [
      python3
      jdk17_headless
    ];
    passthru = {
      inherit
        version
        src
        mirror
        natives
        group
        artifact
        ;
    };
  }
  ''
    export SOURCE_DATE_EPOCH=${epoch} LC_ALL=C
    work=$TMPDIR/aar
    mkdir -p $work/classes $work/aar/jni $out/${folder}
    find ${src}/java/src/main/java ${src}/java/src/main/android -name '*.java' | sort > $work/sources
    javac --release 17 -encoding UTF-8 -nowarn -d $work/classes @$work/sources
    jar --create --date=1980-01-01T00:00:02Z --file $work/aar/classes.jar -C $work/classes .
    ${lib.concatMapStrings (abi: ''
      mkdir -p $work/aar/jni/${abi}
      cp ${natives.${abi}}/jni/${abi}/*.so $work/aar/jni/${abi}/
    '') abis}
    # No provider, no permission: this build sends nothing anywhere.
    cat > $work/aar/AndroidManifest.xml <<'EOF'
    <?xml version="1.0" encoding="utf-8"?>
    <manifest xmlns:android="http://schemas.android.com/apk/res/android" package="ai.onnxruntime">
        <uses-sdk android:minSdkVersion="26" />
    </manifest>
    EOF
    # The JNI side makes and reads ai.onnxruntime's objects by name.
    echo '-keep class ai.onnxruntime.** { *; }' > $work/aar/proguard.txt
    : > $work/aar/R.txt
    mkdir -p $work/aar/META-INF/com/android/build/gradle
    printf 'aarFormatVersion=1.0\naarMetadataVersion=1.0\nminCompileSdk=1\n' \
      > $work/aar/META-INF/com/android/build/gradle/aar-metadata.properties
    cp ${src}/LICENSE $work/aar/LICENSE
    cp ${src}/ThirdPartyNotices.txt $work/aar/ThirdPartyNotices.txt
    python3 -B - $work/aar $out/${folder}/${artifact}-${version}.aar <<'EOF'
    import os, sys, zipfile
    root, target = sys.argv[1], sys.argv[2]
    names = sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs)
    with zipfile.ZipFile(target, "w") as z:
        for name in names:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            stored = name.endswith(".so")
            info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
            with open(os.path.join(root, name), "rb") as f:
                z.writestr(info, f.read())
    EOF
    cat > $out/${folder}/${artifact}-${version}.pom <<'EOF'
    <?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
      <modelVersion>4.0.0</modelVersion>
      <groupId>${group}</groupId>
      <artifactId>${artifact}</artifactId>
      <version>${version}</version>
      <packaging>aar</packaging>
    </project>
    EOF
    ${lib.concatMapStrings (abi: ''
      mkdir -p $out/jni/${abi}
      cp ${natives.${abi}}/jni/${abi}/*.so $out/jni/${abi}/
    '') abis}
  ''
