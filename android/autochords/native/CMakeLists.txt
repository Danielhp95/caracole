# libcaracole_soxr.so: libsoxr 0.1.3 (soxr/, LGPL-2.1+, see soxr/README.md) and caracole's JNI to it
# (soxr_jni.c over caracole_soxr.c), one shared library. Built by the host's gcc for the JVM's tests
# (autochords/build.gradle.kts's hostSoxr) and by the NDK for arm64-v8a and x86_64 (ml/build.gradle.kts's
# externalNativeBuild), from the same sources with the same choices: those of nixpkgs' libsoxr, which python-soxr
# links (its HQ engine on x86_64, cr32s, over PFFFT), but no OpenMP (python-soxr's resample runs one thread) and only
# the engines HQ float32 can take. With CARACOLE_SOXR_DRIVER, a static program instead, caracole_soxr_driver
# (soxr_driver.c), which :autochords' arm64 check runs under qemu-aarch64.
cmake_minimum_required(VERSION 3.22)
project(caracole_soxr C)

option(CARACOLE_SOXR_DRIVER "Build the static test driver, not the JNI library." OFF)

set(SOXR ${CMAKE_CURRENT_SOURCE_DIR}/soxr)

# soxr-config.h, upstream's template: every C library here has these.
set(AVCODEC_FOUND 0)
set(AVUTIL_FOUND 0)
set(WITH_PFFFT 1)
set(HAVE_FENV_H 1)
set(HAVE_STDBOOL_H 1)
set(HAVE_STDINT_H 1)
set(HAVE_LRINT 1)
set(HAVE_BIGENDIAN 0)
# The 32-bit engines alone (HQ's precision of 20 bits and float32 never reach the 64-bit ones, VHQ's, nor the
# variable-rate one): cr32s, the SIMD one python-soxr runs on x86_64 (SSE there; NEON on arm64 by
# soxr/aarch64.patch), and cr32, the scalar one soxr.c falls back to (SOXR_USE_SIMD=0, or a CPU without SIMD).
set(WITH_CR32 1)
set(WITH_CR32S 1)
set(WITH_CR64 0)
set(WITH_CR64S 0)
set(WITH_VR32 0)
# Upstream's defaults.
set(WITH_HI_PREC_CLOCK 1)
set(WITH_FLOAT_STD_PREC_CLOCK 0)
set(WITH_DEV_TRACE 1)
configure_file(${SOXR}/soxr-config.h.in ${CMAKE_CURRENT_BINARY_DIR}/soxr-config.h)

# src/CMakeLists.txt's SOURCES for these choices, and caracole's resample over them.
set(SOURCES
    caracole_soxr.c
    ${SOXR}/src/soxr.c ${SOXR}/src/data-io.c
    ${SOXR}/src/dbesi0.c ${SOXR}/src/filter.c ${SOXR}/src/fft4g64.c ${SOXR}/src/cr.c
    ${SOXR}/src/cr32.c ${SOXR}/src/fft4g32.c
    ${SOXR}/src/cr32s.c ${SOXR}/src/pffft32s.c ${SOXR}/src/util32s.c)

if(CARACOLE_SOXR_DRIVER)
  add_executable(caracole_soxr soxr_driver.c ${SOURCES})
  set_target_properties(caracole_soxr PROPERTIES OUTPUT_NAME caracole_soxr_driver)
  target_link_options(caracole_soxr PRIVATE -static)
else()
  add_library(caracole_soxr SHARED soxr_jni.c ${SOURCES})
  if(NOT ANDROID)
    # The JDK's jni.h, the NDK's sysroot having its own.
    set(JDK_INCLUDE "$ENV{JAVA_HOME}/include")
    if(NOT EXISTS "${JDK_INCLUDE}/jni.h")
      message(FATAL_ERROR "no jni.h under JAVA_HOME (${JDK_INCLUDE}): build in `nix develop ./android`")
    endif()
    target_include_directories(caracole_soxr PRIVATE ${JDK_INCLUDE} ${JDK_INCLUDE}/linux)
  endif()
  target_link_options(caracole_soxr PRIVATE
      LINKER:--build-id=none LINKER:--hash-style=gnu LINKER:-z,max-page-size=16384)
endif()
target_include_directories(caracole_soxr PRIVATE ${CMAKE_CURRENT_BINARY_DIR} ${SOXR}/src)
# Upstream's gnu89. Every symbol hidden but the JNI's (JNIEXPORT): no SOXR_VISIBILITY, so soxr.h exports no soxr_*,
# which nothing else links.
set_target_properties(caracole_soxr PROPERTIES C_STANDARD 90 C_EXTENSIONS ON)
target_compile_definitions(caracole_soxr PRIVATE SOXR_LIB NDEBUG)
target_compile_options(caracole_soxr PRIVATE
    # Upstream's Release (-O3, NDEBUG above) whatever the variant: a debug APK's library is the release's code.
    -O3 -fvisibility=hidden
    # No debug information (the Android Gradle plugin's Debug asks -g): nothing reads it, and it would carry the
    # build's folders and the NDK's store path into the APK.
    -g0
    # No fused multiply-add where the source writes a multiply and an add (clang's default on arm64 fuses them;
    # x86_64's baseline has none), so every ABI rounds as python-soxr's library does.
    -ffp-contract=off
    # Reproducible (the design's §7): no checkout's or build's folder in the binary (__FILE__ among them), no
    # compiler's name.
    -ffile-prefix-map=${CMAKE_SOURCE_DIR}=. -ffile-prefix-map=${CMAKE_BINARY_DIR}=. -fno-ident)
target_link_libraries(caracole_soxr PRIVATE m)
# The linker's own .comment (lld's name), which -fno-ident can't reach.
if(CMAKE_OBJCOPY)
  add_custom_command(TARGET caracole_soxr POST_BUILD
      COMMAND ${CMAKE_OBJCOPY} --remove-section=.comment $<TARGET_FILE:caracole_soxr>)
endif()
