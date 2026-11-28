/* caracole_soxr_driver IN_RATE OUT_RATE [stream]: the float32 samples on stdin (this machine's byte order) resampled by
 * caracole_soxr_resample, the JNI's very routine, onto stdout; with "stream", by the JNI's stream instead, as Soxr.kt
 * feeds it (caracole_soxr_piece's pieces, room for STREAM_ROOM samples a call, flushed until it gives nothing, cut to
 * the one-shot's room). Built static for arm64 by the NDK, so that
 * :autochords' SoxrArm64Test runs the phone's code under qemu-aarch64 (SOXR_USE_SIMD=0 for libsoxr's scalar
 * engine). Exit 2 on its arguments, 1 on an error, said on stderr. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "caracole_soxr.h"

#define STREAM_ROOM 4096

/* Soxr.kt's resample of a file, over an array. */
static char const *streamed(float const *x, size_t len, double in_rate, double out_rate, float **y, size_t *ylen)
{
    size_t const room = (size_t)((double)len * out_rate / in_rate + 1);
    size_t const piece = caracole_soxr_piece(in_rate, out_rate);
    size_t at = 0, n = 0, done, i;
    float block[STREAM_ROOM];
    caracole_soxr_stream *s;
    char const *err = caracole_soxr_stream_open(in_rate, out_rate, &s);
    float *out;

    *y = NULL;
    if (err) return err;
    out = calloc(room ? room : 1, sizeof *out);
    if (!out) {
        caracole_soxr_stream_close(s);
        return "out of memory";
    }
    /* Each piece fed, then what it gave drained (no input, no flush) while a call fills the room; then the flush,
     * until a call gives nothing. */
    for (;;) {
        int const flushing = at >= len;
        size_t const take = flushing ? 0 : (len - at < piece ? len - at : piece);
        err = caracole_soxr_stream_process(s, flushing ? NULL : x + at, take, block, STREAM_ROOM, &done);
        while (!err) {
            for (i = 0; i < done && n < room; i++) out[n++] = block[i];
            if (flushing ? done == 0 : done < STREAM_ROOM) break;
            err = caracole_soxr_stream_process(s, flushing ? NULL : x + at + take, 0, block, STREAM_ROOM, &done);
        }
        if (err || flushing) break;
        at += take;
    }
    caracole_soxr_stream_close(s);
    if (err) {
        free(out);
        return err;
    }
    *y = out;
    *ylen = n;
    return NULL;
}

int main(int argc, char **argv)
{
    size_t len = 0, cap = 1 << 16, got, ylen;
    float *x, *y, *grown;
    char const *err;

    if (argc != 3 && !(argc == 4 && !strcmp(argv[3], "stream"))) {
        fprintf(stderr, "usage: %s IN_RATE OUT_RATE [stream] < in.f32 > out.f32\n", argv[0]);
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
    err = argc == 4 ? streamed(x, len, atof(argv[1]), atof(argv[2]), &y, &ylen)
                    : caracole_soxr_resample(x, len, atof(argv[1]), atof(argv[2]), &y, &ylen);
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
