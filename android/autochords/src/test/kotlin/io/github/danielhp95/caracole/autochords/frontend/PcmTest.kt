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
import kotlin.test.assertFailsWith
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
        assertEquals(listOf("AIFF", "FLAC", "FLAC", "WAV"), lossless.map { it.str("format") }.sorted())
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

    @Test fun wavsOf24And32BitIntegersAndOf64BitFloatsAreReadAsLibsndfileReadsThem() {
        val i24 = byteArrayOf(0, 0, 0x80.toByte(), 0xFF.toByte(), 0xFF.toByte(), 0x7F)  // -2^23, then 2^23 - 1
        val w24 = file("i24.wav", wav(tag = 1, channels = 1, bits = 24, data = i24))
        assertContentEquals(floatArrayOf(-1f, 8388607f / 8388608f), Pcm.samples(w24, Pcm.format(w24)!!))
        val i32 = le(2) { putInt(Int.MIN_VALUE); putInt(1 shl 30) }
        val w32 = file("i32.wav", wav(tag = 1, channels = 1, bits = 32, data = i32))
        assertContentEquals(floatArrayOf(-1f, 0.5f), Pcm.samples(w32, Pcm.format(w32)!!))
        val f64 = ByteBuffer.allocate(16).order(ByteOrder.LITTLE_ENDIAN).putDouble(0.1).putDouble(-2.0).array()
        val w64 = file("f64.wav", wav(tag = 3, channels = 1, bits = 64, data = f64))
        assertContentEquals(floatArrayOf(0.1f, -2f), Pcm.samples(w64, Pcm.format(w64)!!))
    }

    @Test fun anAifcOfFl32AndAn8BitAiffAreReadAsLibsndfileReadsThem() {
        val fl = ByteBuffer.allocate(8).order(ByteOrder.BIG_ENDIAN).putFloat(0.75f).putFloat(-0.125f).array()
        val aifc = file("f.aifc", aifc("fl32", channels = 1, bits = 32, frames = 2, data = fl))
        assertContentEquals(floatArrayOf(0.75f, -0.125f), Pcm.samples(aifc, Pcm.format(aifc)!!))
        val aiff = file("s8.aiff", aiff(channels = 1, bits = 8, frames = 3, data = byteArrayOf(-128, 64, 127)))
        assertContentEquals(floatArrayOf(-1f, 0.5f, 127f / 128f), Pcm.samples(aiff, Pcm.format(aiff)!!))
    }

    @Test fun aChunkOfOddSizeBeforeTheDataIsPassedOverWithItsPadByte() {
        val f = file("odd.wav", wav(tag = 1, channels = 1, bits = 16, data = le(1) { putShort(16384) },
            before = byteArrayOf(1, 2, 3)))
        assertContentEquals(floatArrayOf(0.5f), Pcm.samples(f, Pcm.format(f)!!))
    }

    @Test fun aDataChunkOfNoBytesIsNoFramesAsLibsndfileReadsIt() {
        val bytes = wav(tag = 1, channels = 1, bits = 16, data = le(2) { putShort(1); putShort(2) })
        ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).putInt(40, 0)
        assertEquals(0L, Pcm.format(file("empty.wav", bytes))!!.frames)
    }

    @Test fun aTruncatedOrAbsurdHeaderIsUnreadableNeverAnOutOfMemory() {
        val whole = wav(tag = 1, channels = 1, bits = 16, data = ByteArray(4))
        assertFailsWith<Pcm.Unreadable> { Pcm.format(file("cut.wav", whole.copyOf(30))) }
        val wide = wav(tag = 1, channels = 1, bits = 16, data = ByteArray(4))
        ByteBuffer.wrap(wide).order(ByteOrder.LITTLE_ENDIAN).putShort(22, 0xFFFF.toShort())  // 65,535 channels
        assertFailsWith<Pcm.Unreadable> { Pcm.format(file("wide.wav", wide)) }
        val cutAiff = aiff(channels = 1, bits = 16, frames = 1, data = ByteArray(2)).copyOf(24)
        assertFailsWith<Pcm.Unreadable> { Pcm.format(file("cut.aiff", cutAiff)) }
        val deep = aiff(channels = 1, bits = 16, frames = 1, data = ByteArray(2))
        ByteBuffer.wrap(deep).putShort(26, 64)  // 64-bit integers
        assertFailsWith<Pcm.Unreadable> { Pcm.format(file("deep.aiff", deep)) }
    }

    @Test fun anRf64IsNoneOfPcmsToReadAsItIsNoRiff() {
        val rf64 = wav(tag = 1, channels = 1, bits = 16, data = ByteArray(4))
        "RF64".toByteArray().copyInto(rf64)
        assertNull(Pcm.format(file("big.wav", rf64)))
    }

    @Test fun aWavOfAnotherCodecIsNoneOfPcms() {
        assertNull(Pcm.format(file("adpcm.wav", wav(tag = 2, channels = 1, bits = 4, data = ByteArray(8)))))
    }

    private fun le(shorts: Int, fill: ByteBuffer.() -> Unit): ByteArray =
        ByteBuffer.allocate(shorts * 4).order(ByteOrder.LITTLE_ENDIAN).apply(fill)
            .let { it.array().copyOf(it.position()) }

    private fun wav(tag: Int, channels: Int, bits: Int, data: ByteArray, subformat: Int = 0,
                    before: ByteArray? = null): ByteArray {
        val fmt = if (tag == 0xFFFE) 40 else 16
        val extra = before?.let { 8 + it.size + (it.size and 1) } ?: 0
        val b = ByteBuffer.allocate(12 + 8 + fmt + extra + 8 + data.size).order(ByteOrder.LITTLE_ENDIAN)
        b.put("RIFF".toByteArray()).putInt(b.capacity() - 8).put("WAVE".toByteArray())
        b.put("fmt ".toByteArray()).putInt(fmt).putShort(tag.toShort()).putShort(channels.toShort()).putInt(8000)
            .putInt(8000 * channels * bits / 8).putShort((channels * bits / 8).toShort()).putShort(bits.toShort())
        if (tag == 0xFFFE) {
            b.putShort(22).putShort(bits.toShort()).putInt(0).putShort(subformat.toShort()).put(ByteArray(14))
        }
        if (before != null) {
            b.put("LIST".toByteArray()).putInt(before.size).put(before)
            if (before.size and 1 == 1) b.put(0)
        }
        b.put("data".toByteArray()).putInt(data.size).put(data)
        return b.array()
    }

    private fun aiff(channels: Int, bits: Int, frames: Int, data: ByteArray): ByteArray {
        val b = ByteBuffer.allocate(12 + 8 + 18 + 8 + 8 + data.size).order(ByteOrder.BIG_ENDIAN)
        b.put("FORM".toByteArray()).putInt(b.capacity() - 8).put("AIFF".toByteArray())
        b.put("COMM".toByteArray()).putInt(18).putShort(channels.toShort()).putInt(frames).putShort(bits.toShort())
        b.putShort((16383 + 12).toShort()).putLong(8000L shl (63 - 12))
        b.put("SSND".toByteArray()).putInt(8 + data.size).putInt(0).putInt(0).put(data)
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
