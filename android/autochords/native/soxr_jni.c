/* caracole's JNI to libsoxr 0.1.3, for Soxr.kt: caracole_soxr_resample (caracole_soxr.c, python-soxr's
 * `soxr.resample` at HQ), its errors a RuntimeException. */

#include <jni.h>
#include <stdint.h>
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

/* Soxr.Stream's: caracole_soxr_stream_open, _process (a block, or the flush where x is NULL) and _close, the stream's
 * address its handle. */
JNIEXPORT jlong JNICALL
Java_io_github_danielhp95_caracole_autochords_frontend_Soxr_streamOpen(
        JNIEnv *env, jclass cls, jdouble in_rate, jdouble out_rate)
{
    caracole_soxr_stream *s = NULL;
    char const *err = caracole_soxr_stream_open(in_rate, out_rate, &s);
    (void)cls;
    if (err) {
        throw_runtime(env, err);
        return 0;
    }
    return (jlong)(intptr_t)s;
}

JNIEXPORT jint JNICALL
Java_io_github_danielhp95_caracole_autochords_frontend_Soxr_streamProcess(
        JNIEnv *env, jclass cls, jlong handle, jfloatArray input, jint ilen, jfloatArray output)
{
    caracole_soxr_stream *s = (caracole_soxr_stream *)(intptr_t)handle;
    size_t const ocap = (size_t)(*env)->GetArrayLength(env, output);
    float *x = NULL, *y;
    size_t odone = 0;
    char const *err;
    (void)cls;

    y = malloc((ocap ? ocap : 1) * sizeof *y);
    if (input) x = malloc((ilen ? (size_t)ilen : 1) * sizeof *x);
    if (!y || (input && !x)) {
        free(x);
        free(y);
        throw_runtime(env, "out of memory for the resampler's block");
        return 0;
    }
    if (input) (*env)->GetFloatArrayRegion(env, input, 0, ilen, x);
    err = caracole_soxr_stream_process(s, x, input ? (size_t)ilen : 0, y, ocap, &odone);
    free(x);
    if (err) {
        free(y);
        throw_runtime(env, err);
        return 0;
    }
    (*env)->SetFloatArrayRegion(env, output, 0, (jsize)odone, y);
    free(y);
    return (jint)odone;
}

JNIEXPORT void JNICALL
Java_io_github_danielhp95_caracole_autochords_frontend_Soxr_streamClose(JNIEnv *env, jclass cls, jlong handle)
{
    (void)env;
    (void)cls;
    caracole_soxr_stream_close((caracole_soxr_stream *)(intptr_t)handle);
}
