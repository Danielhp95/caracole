package io.github.danielhp95.caracole.autochords.frontend

import io.github.danielhp95.caracole.autochords.testing.SoxrRecords
import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

/** [Pcm] against the computer's decode of the decode gate's lossless files (vectors/autochords/decode.jsonl: their
 * channels as soundfile reads them as float32, by SHA-256, sample for sample), the committed clips, and the forms the
 * fixtures don't hold, each by libsndfile's rule. */
class PcmTest {
    @get:Rule val tmp = TemporaryFolder()

    private val records by lazy { Corpus.lines("autochords/decode.jsonl").drop(1).filter { it.str("kind") == "file" } }

    private fun JsonObject.str(key: String) = this[key]!!.jsonPrimitive.content
    private fun fixture(record: JsonObject) = record["file"]!!.jsonObject.str("fixture")

    private fun file(name: String, bytes: ByteArray): File = tmp.newFile(name.substringAfterLast('/')).apply {
        writeBytes(bytes)
    }

    @Test fun theLosslessFilesAreReadSampleForSampleAsSoundfileReadsThem() {
        val lossless = records.filter { it["exact"]!!.jsonPrimitive.boolean }
        assertEquals(listOf("AIFF", "FLAC", "WAV"), lossless.map { it.str("format") }.sorted())
        for (record in lossless.filter { it.str("format") != "FLAC" }) {
            val name = fixture(record)
            val f = file(name, Corpus.fixture(name))
            val format = assertNotNull(Pcm.format(f), name)
            assertEquals(record["rate"]!!.jsonPrimitive.int, format.rate, name)
            assertEquals(record["channels"]!!.jsonPrimitive.int, format.channels, name)
            assertEquals(record["frames"]!!.jsonPrimitive.int.toLong(), format.frames, name)
            assertEquals(record.str("interleaved_sha256"), sha256(Pcm.samples(f, format)), name)
        }
    }

    @Test fun aFileACodecReadsIsNoneOfPcms() {
        for (record in records.filter { !it["exact"]!!.jsonPrimitive.boolean || it.str("format") == "FLAC" }) {
            val name = fixture(record)
            assertNull(Pcm.format(file(name, Corpus.fixture(name))), name)
        }
    }

    @Test fun theCommittedClipsAreReadAsTheFrontEndsTestsReadThem() {
        for (clip in listOf("steady", "tempo-change", "silence", "long")) {
            val bytes = Corpus.fixture("autochords/$clip.wav")
            val f = file("$clip.wav", bytes)
            assertContentEquals(SoxrRecords.wav(bytes), Pcm.samples(f, Pcm.format(f)!!), clip)
        }
    }

    @Test fun eightBitWavIsUnsignedAndAnAifcOfSowtLittleEndian() {
        val wav = file("u8.wav", wav(tag = 1, channels = 1, bits = 8, data = byteArrayOf(0, 64, -128, -1)))
        assertContentEquals(floatArrayOf(-1f, -0.5f, 0f, 127f / 128f), Pcm.samples(wav, Pcm.format(wav)!!))
        val data = le(2) { putShort(-32768); putShort(16384) }
        val aifc = file("s.aifc", aifc("sowt", channels = 1, bits = 16, frames = 2, data = data))
        assertContentEquals(floatArrayOf(-1f, 0.5f), Pcm.samples(aifc, Pcm.format(aifc)!!))
    }

    @Test fun aFloatWavOfTheExtensibleFormatIsReadAsItIs() {
        val data = le(3) { putFloat(0.25f); putFloat(-1.5f); putFloat(1e-7f) }
        val f = file("f.wav", wav(tag = 0xFFFE, channels = 1, bits = 32, data = data, subformat = 3))
        val format = Pcm.format(f)!!
        assertEquals(true, format.float)
        assertContentEquals(floatArrayOf(0.25f, -1.5f, 1e-7f), Pcm.samples(f, format))
    }

    @Test fun aDataChunkThatSaysMoreThanTheFileHoldsIsReadToItsLastWholeFrame() {
        val bytes = wav(tag = 1, channels = 2, bits = 16, data = le(5) { repeat(5) { putShort(1024) } })
        ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).putInt(40, 0x7FFFFFFF)
        val f = file("cut.wav", bytes)
        val format = Pcm.format(f)!!
        assertEquals(2L, format.frames)
        assertContentEquals(FloatArray(4) { 1f / 32f }, Pcm.samples(f, format))
    }

    @Test fun aWavOfAnotherCodecIsNoneOfPcms() {
        assertNull(Pcm.format(file("adpcm.wav", wav(tag = 2, channels = 1, bits = 4, data = ByteArray(8)))))
    }

    private fun le(shorts: Int, fill: ByteBuffer.() -> Unit): ByteArray =
        ByteBuffer.allocate(shorts * 4).order(ByteOrder.LITTLE_ENDIAN).apply(fill)
            .let { it.array().copyOf(it.position()) }

    private fun wav(tag: Int, channels: Int, bits: Int, data: ByteArray, subformat: Int = 0): ByteArray {
        val fmt = if (tag == 0xFFFE) 40 else 16
        val b = ByteBuffer.allocate(12 + 8 + fmt + 8 + data.size).order(ByteOrder.LITTLE_ENDIAN)
        b.put("RIFF".toByteArray()).putInt(b.capacity() - 8).put("WAVE".toByteArray())
        b.put("fmt ".toByteArray()).putInt(fmt).putShort(tag.toShort()).putShort(channels.toShort()).putInt(8000)
            .putInt(8000 * channels * bits / 8).putShort((channels * bits / 8).toShort()).putShort(bits.toShort())
        if (tag == 0xFFFE) {
            b.putShort(22).putShort(bits.toShort()).putInt(0).putShort(subformat.toShort()).put(ByteArray(14))
        }
        b.put("data".toByteArray()).putInt(data.size).put(data)
        return b.array()
    }

    private fun aifc(kind: String, channels: Int, bits: Int, frames: Int, data: ByteArray): ByteArray {
        val b = ByteBuffer.allocate(12 + 8 + 24 + 8 + 8 + data.size).order(ByteOrder.BIG_ENDIAN)
        b.put("FORM".toByteArray()).putInt(b.capacity() - 8).put("AIFC".toByteArray())
        b.put("COMM".toByteArray()).putInt(24).putShort(channels.toShort()).putInt(frames).putShort(bits.toShort())
        b.putShort((16383 + 12).toShort()).putLong(8000L shl (63 - 12))  // 8,000 Hz, as an 80-bit extended
        b.put(kind.toByteArray()).putShort(0)  // the compression's name, a pascal string, empty
        b.put("SSND".toByteArray()).putInt(8 + data.size).putInt(0).putInt(0).put(data)
        return b.array()
    }

    private fun sha256(samples: FloatArray): String {
        val bytes = ByteBuffer.allocate(samples.size * 4).order(ByteOrder.LITTLE_ENDIAN)
        samples.forEach { bytes.putFloat(it) }
        return MessageDigest.getInstance("SHA-256").digest(bytes.array()).joinToString("") { "%02x".format(it) }
    }
}
