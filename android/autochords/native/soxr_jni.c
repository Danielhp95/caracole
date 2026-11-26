/* caracole's JNI to libsoxr 0.1.3, for Soxr.kt: caracole_soxr_resample (caracole_soxr.c, python-soxr's
 * `soxr.resample` at HQ), its errors a RuntimeException. */

#include <jni.h>
#include <stdlib.h>

#include "caracole_soxr.h"

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
    float *x, *y;
    size_t ylen;
    char const *err;
    jfloatArray output;
    (void)cls;

    x = malloc((ilen ? ilen : 1) * sizeof *x);
    if (!x) {
        throw_runtime(env, "out of memory for the resampler's input");
        return NULL;
    }
    (*env)->GetFloatArrayRegion(env, input, 0, (jsize)ilen, x);
    err = caracole_soxr_resample(x, ilen, in_rate, out_rate, &y, &ylen);
    free(x);
    if (err) {
        throw_runtime(env, err);
        return NULL;
    }
    output = (*env)->NewFloatArray(env, (jsize)ylen);
    if (output) (*env)->SetFloatArrayRegion(env, output, 0, (jsize)ylen, y);
    free(y);
    return output;
}
