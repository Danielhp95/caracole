/* caracole's resample over libsoxr 0.1.3 (soxr/): python-soxr 1.1.0's `soxr.resample` of a mono float32 signal at
 * HQ, which soxr_jni.c (the JVM's and the phone's) and soxr_driver.c (the arm64 check's) both call. */

#if !defined caracole_soxr_included
#define caracole_soxr_included

#include <stddef.h>

/* [ilen] samples of [x], at [in_rate] Hz, resampled to [out_rate] Hz into *[y] (malloc'd, the caller's to free;
 * NULL on an error), *[ylen] samples long. NULL, or libsoxr's error, or "out of memory". */
char const *caracole_soxr_resample(float const *x, size_t ilen, double in_rate, double out_rate,
                                   float **y, size_t *ylen);

/* The same resample a block at a time, so no song is held whole: a stream opened at [in_rate] to [out_rate] HQ, linear
 * phase, one channel, split float32 I/O, exactly as caracole_soxr_resample creates its soxr_t; then fed [ilen]
 * samples of [x] at a time (x NULL: the flush), writing at most [ocap] samples into [y], *[odone] of them. Fed the
 * input in caracole_soxr_resample's pieces and flushed until it gives nothing, its output is that routine's, sample for
 * sample (soxr_jni.c's stream, SoxrTest; soxr_driver.c's "stream", SoxrArm64Test); the caller cuts it to the
 * one-shot's room, in * out / in + 1 samples. NULL, or libsoxr's error, or "out of memory". */
typedef struct caracole_soxr_stream caracole_soxr_stream;
char const *caracole_soxr_stream_open(double in_rate, double out_rate, caracole_soxr_stream **stream);
char const *caracole_soxr_stream_process(caracole_soxr_stream *stream, float const *x, size_t ilen, float *y,
                                         size_t ocap, size_t *odone);
void caracole_soxr_stream_close(caracole_soxr_stream *stream);

/* caracole_soxr_resample's input piece: max(1000, 48000 * in / out) samples. */
size_t caracole_soxr_piece(double in_rate, double out_rate);

#endif
