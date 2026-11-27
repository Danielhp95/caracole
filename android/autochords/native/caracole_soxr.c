/* python-soxr 1.1.0's `soxr.resample(x, in_rate, out_rate)` of a contiguous 1-D float32 x at HQ, as its
 * src/soxr_ext.cpp does it: resample() sends such an x (its stride its item size) to csoxr_split_ch, one channel of
 * split I/O (SOXR_FLOAT32_S): soxr_create with HQ, linear phase (flags 0) and the default runtime spec (one
 * thread); the input fed in pieces of max(1000, 48000 * in / out) samples, then a flush; room for
 * in * out / in + 1 samples, of which it keeps those soxr wrote. */

#include <stdlib.h>

#include "caracole_soxr.h"
#include "soxr.h"

char const *caracole_soxr_resample(float const *x, size_t ilen, double in_rate, double out_rate,
                                   float **y, size_t *ylen)
{
    size_t const olen = (size_t)((double)ilen * out_rate / in_rate + 1);
    size_t const div_len = caracole_soxr_piece(in_rate, out_rate);
    soxr_io_spec_t const io_spec = soxr_io_spec(SOXR_FLOAT32_S, SOXR_FLOAT32_S);
    soxr_quality_spec_t const quality_spec = soxr_quality_spec(SOXR_HQ, 0);
    soxr_error_t err = NULL;
    soxr_t soxr;
    float *out;
    size_t idx, out_pos = 0, odone = 0;
    float const *in_ptr;
    float *out_ptr;

    *y = NULL;
    *ylen = 0;
    soxr = soxr_create(in_rate, out_rate, 1, &err, &io_spec, &quality_spec, NULL);
    if (err) return err;
    out = calloc(olen, sizeof *out);
    if (!out) {
        soxr_delete(soxr);
        return "out of memory for the resampler's output";
    }
    for (idx = 0; idx < ilen; idx += div_len) {
        size_t const n = div_len < ilen - idx ? div_len : ilen - idx;
        in_ptr = &x[idx];
        out_ptr = &out[out_pos];
        err = soxr_process(soxr, &in_ptr, n, NULL, &out_ptr, olen - out_pos, &odone);
        out_pos += odone;
    }
    out_ptr = &out[out_pos];
    err = soxr_process(soxr, NULL, 0, NULL, &out_ptr, olen - out_pos, &odone);
    out_pos += odone;
    soxr_delete(soxr);
    if (err) {
        free(out);
        return err;
    }
    *y = out;
    *ylen = out_pos;
    return NULL;
}

size_t caracole_soxr_piece(double in_rate, double out_rate)
{
    double const div = 48000 * in_rate / out_rate;
    return (size_t)(div < 1000. ? 1000. : div);
}

struct caracole_soxr_stream {
    soxr_t soxr;
};

char const *caracole_soxr_stream_open(double in_rate, double out_rate, caracole_soxr_stream **stream)
{
    soxr_io_spec_t const io_spec = soxr_io_spec(SOXR_FLOAT32_S, SOXR_FLOAT32_S);
    soxr_quality_spec_t const quality_spec = soxr_quality_spec(SOXR_HQ, 0);
    soxr_error_t err = NULL;
    caracole_soxr_stream *s;

    *stream = NULL;
    s = malloc(sizeof *s);
    if (!s) return "out of memory for the resampler";
    s->soxr = soxr_create(in_rate, out_rate, 1, &err, &io_spec, &quality_spec, NULL);
    if (err) {
        free(s);
        return err;
    }
    *stream = s;
    return NULL;
}

char const *caracole_soxr_stream_process(caracole_soxr_stream *stream, float const *x, size_t ilen, float *y,
                                         size_t ocap, size_t *odone)
{
    float const *in_ptr = x;
    float *out_ptr = y;
    *odone = 0;
    return soxr_process(stream->soxr, x ? &in_ptr : NULL, x ? ilen : 0, NULL, &out_ptr, ocap, odone);
}

void caracole_soxr_stream_close(caracole_soxr_stream *stream)
{
    if (!stream) return;
    soxr_delete(stream->soxr);
    free(stream);
}
