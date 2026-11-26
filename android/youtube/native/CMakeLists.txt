# libqjs.so: QuickJS-NG's `qjs` command (MIT, its LICENSE in the source), yt-dlp's JavaScript runtime on the phone
# (the phone-youtube design's §3.1), an executable under a library's name: Android runs no file the app writes, but
# one from its native library folder (applicationInfo.nativeLibraryDir), where the package manager extracts a `lib*.so`
# of the APK (useLegacyPackaging, app/build.gradle.kts). Built by the NDK for arm64-v8a and x86_64 (youtube/
# build.gradle.kts's externalNativeBuild) from QUICKJS_SRC, android/flake.nix's CARACOLE_QUICKJS_SRC: pins.json's tag's
# tree, of which this is upstream's CMakeLists' `qjs_exe` (the engine, its libc and the command), with no host step:
# gen/repl.c and gen/standalone.c, the REPL's and standalone's bytecode qjsc makes, are committed upstream.
cmake_minimum_required(VERSION 3.22)
project(caracole_qjs C)

if(NOT QUICKJS_SRC OR NOT EXISTS "${QUICKJS_SRC}/quickjs.h")
  message(FATAL_ERROR "QUICKJS_SRC (${QUICKJS_SRC}) is no QuickJS-NG source: build in `nix develop ./android`")
endif()
set(Q ${QUICKJS_SRC})

add_executable(qjs
    ${Q}/dtoa.c ${Q}/libregexp.c ${Q}/libunicode.c ${Q}/quickjs.c ${Q}/quickjs-libc.c
    ${Q}/gen/repl.c ${Q}/gen/standalone.c ${Q}/qjs.c)
# The name Android extracts and runs: lib…so, beside the app's other libraries.
set_target_properties(qjs PROPERTIES OUTPUT_NAME qjs PREFIX lib SUFFIX .so C_STANDARD 11 C_EXTENSIONS ON)
target_include_directories(qjs PRIVATE ${Q})
# Upstream's (qjs_defines; its Release's NDEBUG whatever the variant: a debug APK's command is the release's code).
target_compile_definitions(qjs PRIVATE _GNU_SOURCE NDEBUG)
target_compile_options(qjs PRIVATE
    # Upstream's Release, and its -funsigned-char, which its code assumes.
    -O3 -funsigned-char -fvisibility=hidden
    # Upstream's own quiet set, so the build says nothing of upstream's code.
    -Wno-implicit-fallthrough -Wno-sign-compare -Wno-unused-parameter -Wno-unused-but-set-variable
    -Wno-unused-result -Wno-array-bounds
    # No debug information (the Android Gradle plugin's Debug asks -g): it would carry the build's folders and the
    # NDK's store path into the APK.
    -g0
    # Reproducible (as autochords/native/CMakeLists.txt's): no checkout's, build's or source's folder in the binary
    # (__FILE__ among them), no compiler's name.
    -ffile-prefix-map=${Q}=. -ffile-prefix-map=${CMAKE_SOURCE_DIR}=. -ffile-prefix-map=${CMAKE_BINARY_DIR}=.
    -fno-ident)
# A position-independent executable (the NDK's default for Android, said here), 16 KB pages.
set_target_properties(qjs PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_link_options(qjs PRIVATE -pie
    LINKER:--build-id=none LINKER:--hash-style=gnu LINKER:-z,max-page-size=16384)
target_link_libraries(qjs PRIVATE m dl)
# The linker's own .comment (lld's name), which -fno-ident can't reach.
if(CMAKE_OBJCOPY)
  add_custom_command(TARGET qjs POST_BUILD
      COMMAND ${CMAKE_OBJCOPY} --remove-section=.comment $<TARGET_FILE:qjs>)
endif()
