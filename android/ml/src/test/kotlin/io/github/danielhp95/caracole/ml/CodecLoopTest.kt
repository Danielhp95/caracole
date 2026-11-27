package io.github.danielhp95.caracole.ml

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** [CodecLoop]'s decisions over a scripted codec, and [Trim]'s arithmetic over the decode gate's own numbers. */
class CodecLoopTest {
    @get:Rule val tmp = TemporaryFolder()

    /** What the fake codec answers to each dequeueOutput, in turn; then try-again for ever. */
    private sealed class Answer {
        data class Format(val f: OutFormat) : Answer()
        class Buffer(val bytes: ByteArray, val end: Boolean = false) : Answer()
        object Later : Answer()
    }

    private class FakeCodec(answers: List<Answer>, private var format: OutFormat = OutFormat(22050, 1, null)) :
        CodecPort {
        private val script = ArrayDeque(answers)
        private val held = mutableMapOf<Int, ByteArray>()
        var queued = 0
        var inputEnded = false
        override fun dequeueInput(timeoutUs: Long) = if (inputEnded) -1 else 0
        override fun inputBuffer(index: Int): ByteBuffer = ByteBuffer.allocate(4096)
        override fun queueInput(index: Int, size: Int, timeUs: Long, endOfStream: Boolean) {
            queued++
            if (endOfStream) inputEnded = true
        }
        override fun dequeueOutput(timeoutUs: Long, into: OutBuffer): Int =
            when (val a = script.removeFirstOrNull() ?: Answer.Later) {
                is Answer.Format -> { format = a.f; CodecPort.FORMAT_CHANGED }
                is Answer.Buffer -> {
                    held[7] = a.bytes
                    into.offset = 0; into.size = a.bytes.size; into.endOfStream = a.end
                    7
                }
                Answer.Later -> CodecPort.TRY_AGAIN
            }
        override fun outputFormat() = format
        override fun outputFormat(index: Int) = format
        override fun outputBuffer(index: Int): ByteBuffer = ByteBuffer.wrap(held.getValue(index))
        override fun releaseOutput(index: Int) {}
    }

    private class Samples(private var left: Int) : SamplePort {
        override fun read(into: ByteBuffer): Int = if (left <= 0) -1 else { into.put(ByteArray(8)); 8 }
        override fun timeUs() = 0L
        override fun advance() { left-- }
    }

    private fun shorts(vararg s: Int): ByteArray = ByteBuffer.allocate(2 * s.size).order(ByteOrder.nativeOrder())
        .apply { s.forEach { putShort(it.toShort()) } }.array()

    private fun run(codec: CodecPort, skip: Long = 0, nanos: () -> Long = { 0L }): Pair<CodecLoop.Result, FloatArray> {
        val file = tmp.newFile()
        val result = FloatWriter(file).use { CodecLoop(nanos).run(codec, Samples(3), it, skip, null) }
        val b = ByteBuffer.wrap(file.readBytes()).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
        return result to FloatArray(b.remaining()).also { b.get(it) }
    }

    @Test fun samplesAreReadInTheirEncodingTheFirstSkippedAcrossBuffers() {
        val codec = FakeCodec(listOf(Answer.Buffer(shorts(1, 2)), Answer.Buffer(shorts(16384, -32768), end = true)))
        val (result, samples) = run(codec, skip = 3)
        assertEquals(PcmEncoding.PCM_16, result.encoding)
        assertArrayEquals(floatArrayOf(-1f), samples, 0f)
    }

    @Test fun twentyFourBitPackedSamplesAreReadAsLibsndfileReadsThem() {
        val packed = byteArrayOf(0, 0, 0x80.toByte(), 0xFF.toByte(), 0xFF.toByte(), 0x7F, 0, 0, 0x40)
        val codec = FakeCodec(listOf(Answer.Format(OutFormat(44100, 1, 21)), Answer.Buffer(packed, end = true)))
        val (result, samples) = run(codec)
        assertEquals(PcmEncoding.PCM_24_PACKED, result.encoding)
        assertArrayEquals(floatArrayOf(-1f, 8388607f / 8388608f, 0.5f), samples, 0f)
    }

    @Test fun anEncodingCaracoleDoesntReadIsRefusedNeverReadAs16Bit() {
        val codec = FakeCodec(listOf(Answer.Format(OutFormat(44100, 1, 13)), Answer.Buffer(ByteArray(4), end = true)))
        val e = assertThrows(UndecodableAudio::class.java) { run(codec) }
        assertTrue(e.message!!, e.message!!.contains("encoding caracole doesn't read (13)"))
    }

    @Test fun aFormatChangeOfRateOrChannelsOnceSamplesWereWrittenIsRefused() {
        val codec = FakeCodec(listOf(Answer.Buffer(shorts(1, 2)), Answer.Format(OutFormat(22050, 2, null)),
            Answer.Buffer(shorts(3, 4), end = true)))
        val e = assertThrows(UndecodableAudio::class.java) { run(codec) }
        assertTrue(e.message!!, e.message!!.contains("partway"))
        // Before any sample, the format the codec settles on is the one read.
        val early = FakeCodec(listOf(Answer.Format(OutFormat(44100, 2, null)), Answer.Buffer(shorts(1, 2), end = true)))
        assertEquals(2, run(early).first.channels)
    }

    @Test fun aCodecThatNeverEndsItsStreamIsGivenUpAfterTheInputEnds() {
        val codec = FakeCodec(listOf(Answer.Buffer(shorts(1))))
        val e = assertThrows(UndecodableAudio::class.java) { run(codec) }
        assertTrue(e.message!!, e.message!!.contains("stopped giving audio"))
        assertTrue(codec.inputEnded)
    }

    @Test fun aCodecThatTakesNothingAndGivesNothingIsGivenUpByTheClock() {
        val stuck = object : CodecPort by FakeCodec(emptyList()) {
            override fun dequeueInput(timeoutUs: Long) = -1
        }
        var now = 0L
        val e = assertThrows(UndecodableAudio::class.java) { run(stuck) { now += 1_000_000_000L; now } }
        assertTrue(e.message!!, e.message!!.contains("nothing for a while"))
    }

    @Test fun anMp4IsTrimmedToItsEditListExactlyWhateverItsPadding() {
        // decode.m4a: 131 AAC frames of 1,024 (134,144 samples), the edit 132,300 from 1,024: 820 cut off the end.
        val m4a = Trim.edit(mediaTime = 1024, kept = 132_300)
        assertEquals(132_300L, m4a.frames(134_144L - 1024))
        // decode-11k.m4a: 34 frames (34,816), the edit 33,075 from 1,024: 717 cut, 0.065 s at 11,025 Hz.
        assertEquals(33_075L, Trim.edit(1024, 33_075).frames(34_816L - 1024))
    }

    @Test fun nothingIsCutToALengthMerelyStatedSoNoRealAudioGoes() {
        // An Ogg's or a FLAC's decode, its container's stated length a few ms short: every frame kept.
        assertEquals(132_300L, Trim.stated(0, 0).frames(132_300L))
        // A LAME tag's delay and padding: those alone.
        assertEquals(132_300L, Trim.stated(576, 756).frames(133_632L - 576))
        assertEquals(0L, Trim.stated(0, 900).frames(100))
    }
}
