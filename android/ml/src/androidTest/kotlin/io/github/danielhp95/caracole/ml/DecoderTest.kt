package io.github.danielhp95.caracole.ml

import android.app.Instrumentation
import android.os.Bundle
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import java.util.Base64
import java.util.Locale
import java.util.zip.Inflater
import kotlin.math.abs
import kotlin.math.log10
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The design's B1 decode gate (§4.2) on this device's [Decoder], over the computer's decode of each of the decode
 * gate's files (tests/conformance/vectors/autochords/decode.jsonl, its files tests/fixtures/autochords/decode*.*, this
 * test APK's assets), every threshold read from the records' meta (`gates`), none typed here:
 *
 * - a lossless file (FLAC, WAV, AIFF): its channels and rate the computer's, its mono ([Mixdown]) the computer's
 *   sample for sample (by SHA-256), a FLAC's channels too; a FLAC deeper than 16 bits that the platform gives as
 *   16-bit is held as a lossy one, and one it gives in an encoding caracole refuses must be refused in words;
 * - a lossy one: its rate the computer's, no sample offset (the cross-correlation's peak at lag 0, within
 *   `offset_search`, over `offset_window` samples), an SNR of `snr_db_min` or more against the computer's 16-bit
 *   decode over the samples both decoded, and of `snr_second_db_min` over each whole second;
 * - every one: its frames within `decoded_within_samples` of the computer's, and the length it states
 *   ([Decoded.durationS]) within `length_within_samples` samples of music.py read_audio's;
 * - a fragmented MP4 (`fragmented`, yt-dlp's m4a on the phone), which the computer never holds as it is: held to the
 *   computer's remux of it (yt-dlp's FixupM4a), its decode and its read_audio length, which the generator checks
 *   against the remux beside it (`decode-frag-remux.m4a`, `decode-dash-remux.m4a`).
 *
 * It says, a file a line on the instrumentation's stream, which decoder ran, what it trimmed, and what it measured:
 * the offset, the SNR (and each second's), the lengths, the time, and the process's peak RSS while it decoded.
 */
@RunWith(AndroidJUnit4::class)
class DecoderTest {
    @Test fun eachFileIsDecodedAsTheComputerDecodesIt() {
        val failures = mutableListOf<String>()
        for (record in files) {
            val name = record.getJSONObject("file").getString("fixture").substringAfterLast('/')
            try {
                one(name, record)
            } catch (e: AssertionError) {
                failures += "$name: ${e.message}"
                report("$name: FAILED ${e.message}")
            }
        }
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
    }

    @Test fun aFileThatIsNoAudioIsUndecodableInWords() {
        val file = File(work, "not-audio.mp3").apply { writeText("not audio at all") }
        val e = runCatching { Decoder.decode(file, File(work, "out.f32")) }.exceptionOrNull()
        assertTrue("$e", e is UndecodableAudio)
    }

    @Test fun theStreamedMixdownIsTheArraysAndFormsAreCovered() {
        val forms = files.map { it.getString("format") }.toSet()
        assertEquals(setOf("MP3", "M4A", "Ogg", "FLAC", "WAV", "AIFF"), forms)
        assertEquals(13, files.size)
        val wav = files.first { it.getString("format") == "WAV" }
        val source = asset(wav.getJSONObject("file").getString("fixture").substringAfterLast('/'))
        val pcm = File(work, "wav.f32")
        val decoded = Decoder.decode(source, pcm)
        val mono = File(work, "wav-mono.f32")
        assertEquals(decoded.frames, Mixdown.mono(pcm, decoded.channels, mono))
        assertEquals(Mixdown.mono(floats(pcm), decoded.channels).toList(), floats(mono).toList())
    }

    private fun one(name: String, record: JSONObject) {
        val gates = meta.getJSONObject("gates")
        val pcm = File(work, "$name.f32")
        val source = asset(name)
        val before = status("VmRSS")
        val reset = runCatching { File("/proc/self/clear_refs").writeText("5") }.isSuccess
        val began = System.nanoTime()
        val decoded = try {
            Decoder.decode(source, pcm)
        } catch (e: UndecodableAudio) {
            // A lossless file deeper than 16 bits whose decoder's encoding caracole refuses: refused in words, and
            // its partial output gone.
            if (deep(record) && e.message.orEmpty().contains("encoding caracole doesn't read")) {
                assertTrue("its partial output deleted", !pcm.exists())
                report("$name ${record.getString("format")}: refused, ${e.message}")
                return
            }
            throw e
        }
        val took = (System.nanoTime() - began) / 1e6
        val peak = if (reset) status("VmHWM") else null
        val samples = floats(pcm)
        assertEquals("whole frames", 0, samples.size % decoded.channels)
        assertEquals(decoded.frames * decoded.channels, samples.size.toLong())
        val mono = Mixdown.mono(samples, decoded.channels)
        val rate = record.getInt("rate")
        assertEquals("rate", rate, decoded.rate)
        val duration = record.getDouble("duration")
        val stated = decoded.durationS
        assertNotNull("a stated length", stated)
        val lengthOff = abs(stated!! - duration) * rate
        val framesOff = abs(decoded.frames - record.getLong("frames"))
        val line = StringBuilder("$name ${record.getString("format")}: ${decoded.codec ?: "no codec (Pcm)"}, " +
            "${decoded.encoding}, trimmed ${decoded.delay} first, ${decoded.padding} last, " +
            "${decoded.channels} ch, ${decoded.frames} frames (the computer's ${record.getLong("frames")}), " +
            "stated ${fixed(stated, 6)} s against read_audio's ${fixed(duration, 6)}, " +
            "decoded in ${fixed(took, 0)} ms, peak RSS " +
            (if (peak != null && before != null) "${peak / 1024} MB (${(peak - before) / 1024} MB over the process's " +
                "${before / 1024} MB before)" else "unread"))
        val exact = record.getBoolean("exact") && sha256(mono) == record.getString("mono_sha256")
        if (record.getBoolean("exact") && (exact || !deep(record) || decoded.encoding != PcmEncoding.PCM_16.words)) {
            line.append(if (exact) ", sample for sample" else ", NOT exact")
            report(line.toString())
            assertEquals("channels", record.getInt("channels"), decoded.channels)
            if (record.getString("format") == "FLAC") {
                assertEquals("its channels", record.getString("interleaved_sha256"), sha256(samples))
            }
            assertEquals("its mono", record.getString("mono_sha256"), sha256(mono))
        } else {
            // A lossy file, or a deep lossless one the platform gives as 16-bit: the 16-bit gate.
            val want = pcm16(record.getJSONObject("pcm16"))
            val offset = offset(want, mono, gates.getInt("offset_search"), gates.getInt("offset_window"))
            val snr = snr(want, mono)
            line.append(", offset $offset, SNR ${fixed(snr, 1)} dB")
            val seconds = (0 until minOf(want.size, mono.size) / rate).map {
                snr(want.copyOfRange(it * rate, (it + 1) * rate), mono.copyOfRange(it * rate, (it + 1) * rate))
            }
            line.append(" (each second's: " + seconds.joinToString(" ") { fixed(it, 1) } + ")")
            report(line.toString())
            assertEquals("the offset", gates.getInt("offset"), offset)
            assertTrue("SNR $snr dB", snr >= gates.getDouble("snr_db_min"))
            assertTrue("each second's SNR $seconds", seconds.all { it >= gates.getDouble("snr_second_db_min") })
        }
        assertTrue("decoded $framesOff frames off the computer's", framesOff <= gates.getLong("decoded_within_samples"))
        assertTrue("its stated length $lengthOff samples off", lengthOff <= gates.getDouble("length_within_samples"))
    }

    /** A lossless file deeper than 16 bits: the computer's 16-bit decode kept beside its digest. */
    private fun deep(record: JSONObject) = record.getBoolean("exact") && record.has("pcm16")

    /** The lag in [-search, search] at which [got] correlates best with [want], over [window] samples they share. */
    private fun offset(want: FloatArray, got: FloatArray, search: Int, window: Int): Int {
        val n = minOf(minOf(want.size, got.size) - 2 * search, window)
        var best = 0
        var bestScore = Double.NEGATIVE_INFINITY
        for (lag in -search..search) {
            var s = 0.0
            for (i in search until search + n) s += want[i] * got[i + lag]
            if (s > bestScore) { bestScore = s; best = lag }
        }
        return best
    }

    private fun snr(want: FloatArray, got: FloatArray): Double {
        var signal = 0.0
        var noise = 0.0
        for (i in 0 until minOf(want.size, got.size)) {
            signal += want[i].toDouble() * want[i]
            val d = want[i].toDouble() - got[i]
            noise += d * d
        }
        return 10 * log10(signal / noise)
    }

    /** A line of /proc/self/status in kB, or null. */
    private fun status(key: String): Long? = runCatching {
        File("/proc/self/status").readLines().first { it.startsWith("$key:") }.substringAfter(':').trim()
            .removeSuffix("kB").trim().toLong()
    }.getOrNull()

    private fun report(line: String) {
        Log.i("caracole-ml", line)
        InstrumentationRegistry.getInstrumentation().sendStatus(STATUS, Bundle().apply {
            putString(Instrumentation.REPORT_KEY_STREAMRESULT, "$line\n")
        })
    }

    companion object {
        /** A status code no runner uses (AndroidJUnitRunner's are 0 to 2 and negative ones): a line, no test's end. */
        const val STATUS = 2026

        private val records by lazy {
            InstrumentationRegistry.getInstrumentation().context.assets.open("autochords/decode.jsonl")
                .bufferedReader().useLines { lines -> lines.drop(1).map { JSONObject(it) }.toList() }
        }
        private val meta by lazy { records.first { it.getString("kind") == "meta" } }
        private val files by lazy { records.filter { it.getString("kind") == "file" } }
        private val work by lazy {
            File(InstrumentationRegistry.getInstrumentation().targetContext.cacheDir, "decoder-test").apply { mkdirs() }
        }

        /** The asset of the decode gate's file [name] as a file of its own, as the phone's decoder takes one. */
        fun asset(name: String): File = File(work, name).also { out ->
            InstrumentationRegistry.getInstrumentation().context.assets.open("autochords/$name").use { input ->
                out.outputStream().use { input.copyTo(it) }
            }
        }

        fun floats(file: File): FloatArray {
            val b = ByteBuffer.wrap(file.readBytes()).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
            return FloatArray(b.remaining()).also { b.get(it) }
        }

        /** decode.jsonl's 16-bit samples, each less the one before and deflated, as float32 (over 32,768). */
        fun pcm16(array: JSONObject): FloatArray {
            assertEquals("deltas, zlib", array.getString("coding"))
            val n = array.getJSONArray("shape").getInt(0)
            val inflater = Inflater()
            inflater.setInput(Base64.getDecoder().decode(array.getString("base64")))
            val bytes = ByteArray(2 * n)
            var at = 0
            while (at < bytes.size && !inflater.finished()) at += inflater.inflate(bytes, at, bytes.size - at)
            inflater.end()
            assertEquals(bytes.size, at)
            val deltas = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
            var s: Short = 0
            return FloatArray(n) {
                s = (s + deltas.get(it)).toShort()
                s * (1f / 32768f)
            }
        }

        fun sha256(samples: FloatArray): String {
            val bytes = ByteBuffer.allocate(samples.size * 4).order(ByteOrder.LITTLE_ENDIAN)
            samples.forEach { bytes.putFloat(it) }
            return MessageDigest.getInstance("SHA-256").digest(bytes.array()).joinToString("") { "%02x".format(it) }
        }

        fun fixed(x: Double, digits: Int): String = String.format(Locale.ROOT, "%.${digits}f", x)
    }
}
