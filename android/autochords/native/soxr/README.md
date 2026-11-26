# libsoxr 0.1.3, vendored

The SoX Resampler library, by robs@users.sourceforge.net: LGPL-2.1 or later (`LICENCE`, `COPYING.LGPL`; its PFFFT,
`src/pffft.c`, under the BSD-like licence in that file). caracole builds it into a shared library of its own,
`libcaracole_soxr.so` (../CMakeLists.txt), which anyone may replace with their own build of these sources.

Taken from nixpkgs' own source of it, the one the libsoxr python-soxr links is built from, through caracole's pinned
nixpkgs (`nix build --inputs-from . nixpkgs#soxr.src`):

- `/nix/store/5c3j5mvbmmhq5d6xry4fi560p6izxbna-soxr-0.1.3-Source.tar.xz`
- SHA-256 `b111c15fdc8c029989330ff559184198c161100a59312f5dc19ddeb9b5a15889` (nixpkgs'
  `sha256-sRHBX9yMApmJMw/1WRhBmMFhEApZMS9dwZ3eubWhWIk=`)

Only what ../CMakeLists.txt builds is kept: `LICENCE`, `COPYING.LGPL`, `AUTHORS`, `soxr-config.h.in` and the sources
and headers of the 32-bit constant-rate engines under `src/`, as the tarball has them, but for two patches, applied:

- `arm64-check.patch`, nixpkgs' own (pkgs/by-name/so/soxr/), which its build applies: NEON where `__arm64__`;
- `aarch64.patch`, caracole's, after it: NEON where `__aarch64__` too (Android's arm64-v8a defines neither `__arm__`
  nor `__arm64__`), and SIMD taken for granted there as on x86_64 (`cpu_has_simd32`), so the phone runs the HQ engine
  python-soxr runs, cr32s over PFFFT, not the scalar fallback.
