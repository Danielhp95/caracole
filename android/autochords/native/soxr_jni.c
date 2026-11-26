/* caracole's JNI to libsoxr 0.1.3 (soxr/), for Soxr.kt: python-soxr 1.1.0's `soxr.resample` of a mono float32
 * signal at HQ, call for call, so the phone resamples as the computer does (the chords-on-the-phone design's §3.6):
 * its csoxr_divide_proc (src/soxr_ext.cpp): soxr_create with HQ, linear phase (flags 0) and the default runtime
 * spec (one thread); the input fed in pieces of max(1000, 48000 * in / out) samples, then a flush; room for
 * in * out / in + 1 samples, of which it keeps those soxr wrote. */

#include <jni.h>
#include <stdlib.h>

#include "soxr.h"

static void throw_runtime(JNIEnv *env, char const *words)
{
    jclass cls = (*env)->FindClass(env, "java/lang/RuntimeException");
    if (cls) (*env)->ThrowNew(env, cls, words);
}

JNIEXPORT jfloatArray JNICALL
Java_io_github_danielhp95_caracole_autochords_frontend_Soxr_resampleHq(
        JNIEnv *env, jclass cls, jfloatArray input, jdouble in_rate, jdouble out_rate)
{
    size_t const ilen = (size_t)(*env)->GetArrayLength(env, input);
    size_t const olen = (size_t)((double)ilen * out_rate / in_rate + 1);
    double const div = 48000 * in_rate / out_rate;
    size_t const div_len = (size_t)(div < 1000. ? 1000. : div);
    soxr_io_spec_t const io_spec = soxr_io_spec(SOXR_FLOAT32_I, SOXR_FLOAT32_I);
    soxr_quality_spec_t const quality_spec = soxr_quality_spec(SOXR_HQ, 0);
    soxr_error_t err = NULL;
    soxr_t soxr;
    float *x, *y;
    size_t idx, out_pos = 0, odone = 0;
    jfloatArray output;
    (void)cls;

    x = malloc((ilen ? ilen : 1) * sizeof *x);
    y = calloc(olen, sizeof *y);
    if (!x || !y) {
        free(x);
        free(y);
        throw_runtime(env, "out of memory for the resampler's buffers");
        return NULL;
    }
    (*env)->GetFloatArrayRegion(env, input, 0, (jsize)ilen, x);

    soxr = soxr_create(in_rate, out_rate, 1, &err, &io_spec, &quality_spec, NULL);
    if (!err) {
        for (idx = 0; idx < ilen; idx += div_len) {
            size_t const n = div_len < ilen - idx ? div_len : ilen - idx;
            err = soxr_process(soxr, &x[idx], n, NULL, &y[out_pos], olen - out_pos, &odone);
            out_pos += odone;
        }
        err = soxr_process(soxr, NULL, 0, NULL, &y[out_pos], olen - out_pos, &odone);
        out_pos += odone;
        soxr_delete(soxr);
    }
    free(x);
    if (err) {
        free(y);
        throw_runtime(env, err);
        return NULL;
    }
    output = (*env)->NewFloatArray(env, (jsize)out_pos);
    if (output) (*env)->SetFloatArrayRegion(env, output, 0, (jsize)out_pos, y);
    free(y);
    return output;
}
