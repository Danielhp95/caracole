package io.github.danielhp95.caracole.autochords.frontend

import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.ByteBuffer
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

/** [Mp4] and [MpegHeader] against the computer's lengths of the decode gate's files (decode.jsonl's `duration`,
 * music.py read_audio's: mutagen's, an MP3 that names no length its frames counted), each to the bit, and the edit
 * list FFmpeg trims an MP4 to (its `frames`). */
class ContainerLengthTest {
    @get:Rule val tmp = TemporaryFolder()

    private val records by lazy {
        Corpus.lines("autochords/decode.jsonl").drop(1).filter { it.str("kind") == "file" }
    }

    private fun JsonObject.str(key: String) = this[key]!!.jsonPrimitive.content
    private fun name(r: JsonObject) = r["file"]!!.jsonObject.str("fixture")
    private fun file(r: JsonObject): File =
        tmp.newFile(name(r).substringAfterLast('/')).apply { writeBytes(Corpus.fixture(name(r))) }

    @Test fun anMp4sLengthIsItsSoundTracksMdhdAsMutagenReadsIt() {
        val m4a = records.filter { it.str("format") == "M4A" }
        assertEquals(2, m4a.size)
        for (r in m4a) {
            val track = assertNotNull(Mp4.audioTrack(file(r)), name(r))
            assertEquals(r["duration"]!!.jsonPrimitive.double, track.seconds, 0.0, name(r))
        }
    }

    @Test fun anMp4sEditListIsTheSamplesFfmpegKeeps() {
        for (r in records.filter { it.str("format") == "M4A" }) {
            val track = Mp4.audioTrack(file(r))!!
            val edit = assertNotNull(track.edit(), name(r))
            assertEquals(1024L, edit.mediaTime, name(r))
            assertEquals(r["frames"]!!.jsonPrimitive.long, track.keptFrames(edit), name(r))
        }
    }

    @Test fun anEditsLengthIsRescaledToTheMediasTimescaleRoundingHalvesAway() {
        // 1,000 a second in the movie, 44,100 in the media: 6.000 s is 264,600 samples; 0.0005 s is 22.05, so 22.
        val track = Mp4.Track(44100, 300_000, 1000, listOf(Mp4.Edit(6000, 2112)))
        assertEquals(264_600L, track.keptFrames(track.edit()!!))
        assertEquals(22L, Mp4.rescale(1, 44100, 2000))
        assertEquals(23L, Mp4.rescale(1, 45, 2))  // 22.5 rounds away from zero, as FFmpeg's av_rescale does
    }

    @Test fun moreThanOneMediaEditIsNoEditTrimmedExactly() {
        assertNull(Mp4.Track(22050, 10, 22050, listOf(Mp4.Edit(5, 0), Mp4.Edit(5, 100))).edit())
        assertEquals(Mp4.Edit(5, 1024), Mp4.Track(22050, 10, 22050, listOf(Mp4.Edit(3, -1), Mp4.Edit(5, 1024))).edit())
    }

    @Test fun anMp3sLengthIsItsXingFramesLessALameTagsDelayAndPaddingAsMutagenReadsThem() {
        for (r in records.filter { it.str("format") == "MP3" }) {
            val stated = MpegHeader.statedLength(file(r))
            if (name(r).endsWith("headerless.mp3")) {
                assertNull(stated, "no Xing or VBRI header: the frames are counted")
            } else {
                assertEquals(r["duration"]!!.jsonPrimitive.double, stated!!, 0.0, name(r))
            }
        }
    }

    @Test fun aLameVersionIsReadAsMutagenReadsIt() {
        fun v(s: String) = MpegHeader.lameHeaderFollows(s.toByteArray(Charsets.ISO_8859_1).copyOf(20))
        assertEquals(true, v("LAME3.100\u0000UUUUUUUUUU"))
        assertEquals(true, v("LAME4.0 \u0000UUUUUUUUUUUU"))
        assertEquals(false, v("LAME3.88\u0000UUUUUUUUUUU"))
        assertEquals(null, v("Lavf lame\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000\u0000"))
        assertEquals(null, v("LAMEx.99"))
    }

    @Test fun anOggsSamplesAreItsLastPagesGranuleLessOpussPreSkipAsTheComputersDecodeEnds() {
        val ogg = records.filter { it.str("format") == "Ogg" }
        assertEquals(2, ogg.size)
        for (r in ogg) {
            val stream = assertNotNull(Ogg.stream(file(r)), name(r))
            assertEquals(r["frames"]!!.jsonPrimitive.long, stream.frames, name(r))
            assertEquals(r["duration"]!!.jsonPrimitive.double, stream.frames.toDouble() / stream.rate, 0.0, name(r))
        }
    }

    @Test fun aBoxSizeThatWouldOverflowPastTheFileIsNoBoxNeverASeekPastIt() {
        val b = ByteBuffer.allocate(40)
        b.putInt(16).put("ftyp".toByteArray()).put("M4A ".toByteArray()).putInt(0)
        b.putInt(1).put("moov".toByteArray()).putLong(Long.MAX_VALUE - 3).putLong(0)
        assertNull(Mp4.audioTrack(tmp.newFile("huge.m4a").apply { writeBytes(b.array()) }))
    }

    @Test fun anEditOfNoMovieTimescaleOrANegativeSegmentIsNoEditToTrimBy() {
        assertNull(Mp4.Track(22050, 10, 0, listOf(Mp4.Edit(5, 1024))).edit())
        assertNull(Mp4.Track(22050, 10, 22050, listOf(Mp4.Edit(-5, 1024))).edit())
        assertNull(Mp4.Track(0, 10, 22050, listOf(Mp4.Edit(5, 1024))).edit())
    }

    @Test fun anMp3sXingFrameIsFoundPastAnId3v2TagOfAnySize() {
        val r = records.first { name(it).endsWith("/decode.mp3") }
        val tag = ByteArray(10 + 2_000_000)
        "ID3".toByteArray().copyInto(tag)
        tag[3] = 4
        val size = tag.size - 10
        for (i in 0..3) tag[6 + i] = ((size shr (21 - 7 * i)) and 0x7F).toByte()  // syncsafe
        val tagged = tmp.newFile("tagged.mp3").apply { writeBytes(tag + Corpus.fixture(name(r))) }
        assertEquals(r["duration"]!!.jsonPrimitive.double, MpegHeader.statedLength(tagged)!!, 0.0)
    }

    @Test fun aFileNoContainerOfTheseHoldsGivesNone() {
        val wav = file(records.first { it.str("format") == "WAV" })
        assertNull(Mp4.audioTrack(wav))
        assertNull(MpegHeader.statedLength(wav))
        assertNull(Ogg.stream(wav))
        assertNull(Mp4.audioTrack(tmp.newFile("tiny").apply { writeBytes(ByteBuffer.allocate(3).array()) }))
    }
}
