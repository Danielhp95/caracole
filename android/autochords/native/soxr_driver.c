/* caracole_soxr_driver IN_RATE OUT_RATE: the float32 samples on stdin (this machine's byte order) resampled by
 * caracole_soxr_resample, the JNI's very routine, onto stdout. Built static for arm64 by the NDK, so that
 * :autochords' SoxrArm64Test runs the phone's code under qemu-aarch64 (SOXR_USE_SIMD=0 for libsoxr's scalar
 * engine). Exit 2 on its arguments, 1 on an error, said on stderr. */

#include <stdio.h>
#include <stdlib.h>

#include "caracole_soxr.h"

int main(int argc, char **argv)
{
    size_t len = 0, cap = 1 << 16, got, ylen;
    float *x, *y, *grown;
    char const *err;

    if (argc != 3) {
        fprintf(stderr, "usage: %s IN_RATE OUT_RATE < in.f32 > out.f32\n", argv[0]);
        return 2;
    }
    x = malloc(cap * sizeof *x);
    while (x && (got = fread(x + len, sizeof *x, cap - len, stdin)) > 0) {
        len += got;
        if (len == cap) {
            cap *= 2;
            grown = realloc(x, cap * sizeof *x);
            if (!grown) free(x);
            x = grown;
        }
    }
    if (!x || ferror(stdin)) {
        fprintf(stderr, "can't read the input\n");
        return 1;
    }
    err = caracole_soxr_resample(x, len, atof(argv[1]), atof(argv[2]), &y, &ylen);
    free(x);
    if (err) {
        fprintf(stderr, "%s\n", err);
        return 1;
    }
    if (fwrite(y, sizeof *y, ylen, stdout) != ylen || fflush(stdout)) {
        fprintf(stderr, "can't write the output\n");
        return 1;
    }
    free(y);
    return 0;
}
