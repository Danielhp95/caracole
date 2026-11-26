/* caracole's resample over libsoxr 0.1.3 (soxr/): python-soxr 1.1.0's `soxr.resample` of a mono float32 signal at
 * HQ, which soxr_jni.c (the JVM's and the phone's) and soxr_driver.c (the arm64 check's) both call. */

#if !defined caracole_soxr_included
#define caracole_soxr_included

#include <stddef.h>

/* [ilen] samples of [x], at [in_rate] Hz, resampled to [out_rate] Hz into *[y] (malloc'd, the caller's to free;
 * NULL on an error), *[ylen] samples long. NULL, or libsoxr's error, or "out of memory". */
char const *caracole_soxr_resample(float const *x, size_t ilen, double in_rate, double out_rate,
                                   float **y, size_t *ylen);

#endif
