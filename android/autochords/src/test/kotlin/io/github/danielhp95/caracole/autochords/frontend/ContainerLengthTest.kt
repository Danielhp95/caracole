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
import kotlin.test.assertFailsWith
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

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

    private fun fragmented(r: JsonObject) = r["fragmented"]?.jsonPrimitive?.content == "true"

    @Test fun anMp4sLengthIsItsSoundTracksMdhdAsMutagenReadsIt() {
        val m4a = records.filter { it.str("format") == "M4A" && !fragmented(it) }
        assertEquals(2, m4a.size)
        for (r in m4a) {
            val track = assertNotNull(Mp4.audioTrack(file(r)), name(r))
            assertEquals(r["duration"]!!.jsonPrimitive.double, track.seconds, 0.0, name(r))
            assertEquals(track.seconds, track.statedSeconds, 0.0, name(r))
        }
    }

    /** yt-dlp's m4a on the phone, fragmented: no edit list, mutagen's length 0 (its empty `mdhd`), and the length the
     * computer states, its remux's, the fragments' to the sample: where its decode ends (`frames`). */
    @Test fun aFragmentedMp4sLengthIsItsFragmentsAsTheComputersRemuxStatesIt() {
        val m4a = records.filter { it.str("format") == "M4A" && fragmented(it) }
        assertEquals(2, m4a.size)
        for (r in m4a) {
            val track = assertNotNull(Mp4.audioTrack(file(r)), name(r))
            assertTrue(track.fragmented, name(r))
            assertNull(track.edit(), name(r))
            assertEquals(0.0, track.seconds, name(r))
            assertEquals(r["frames"]!!.jsonPrimitive.long, track.fragments, name(r))
            assertEquals(r["duration"]!!.jsonPrimitive.double, track.statedSeconds, 0.0, name(r))
        }
    }

    private fun box(name: String, vararg parts: ByteArray): ByteArray {
        val body = parts.fold(ByteArray(0)) { a, b -> a + b }
        return ByteBuffer.allocate(8 + body.size).putInt(8 + body.size).put(name.toByteArray()).put(body).array()
    }

    private fun ints(vararg xs: Int): ByteArray =
        ByteBuffer.allocate(4 * xs.size).apply { xs.forEach { putInt(it) } }.array()

    private fun fragmentedFile(vararg moofs: ByteArray): File {
        val tkhd = box("tkhd", ints(0, 0, 0, 1, 0))  // version 0: track_ID 1
        val mdhd = box("mdhd", ints(0, 0, 0, 1000, 0, 0))  // timescale 1000, duration 0
        val hdlr = box("hdlr", ints(0, 0), "soun".toByteArray(), ints(0, 0, 0))
        val moov = box("moov", box("mvhd", ints(0, 0, 0, 1000, 0)), box("trak", tkhd, box("mdia", mdhd, hdlr)),
            box("mvex", box("trex", ints(0, 1, 1, 7, 0, 0))))  // track 1's default duration 7
        val bytes = moofs.fold(box("ftyp", "M4A ".toByteArray(), ints(0)) + moov) { a, b -> a + b }
        return tmp.newFile().apply { writeBytes(bytes) }
    }

    private fun traf(track: Int, flags: Int, vararg rest: ByteArray) =
        box("traf", box("tfhd", ints(flags, track), *rest.take(1).toTypedArray()), *rest.drop(1).toTypedArray())

    /** A fragment's samples timed as FFmpeg times them: from its `tfdt` (64-bit or 32-bit), else on from the one
     * before; each sample's own duration, else its `tfhd`'s default, else the `trex`'s; another track's passed over;
     * one cut short, or none at all, no length. */
    @Test fun aFragmentsLengthRunsFromTheFirstDecodeTimeToTheLastSamplesEnd() {
        val file = fragmentedFile(
            box("moof", traf(1, 0x08, ints(10), box("tfdt", ints(0x01000000, 0, 100)), box("trun", ints(0, 3)))),
            box("moof", traf(2, 0x08, ints(1000), box("trun", ints(0, 50)))),
            box("moof", traf(1, 0, ByteArray(0), box("trun", ints(0x100, 3, 1, 2, 3)))),
            box("moof", traf(1, 0, ByteArray(0), box("tfdt", ints(0, 200)), box("trun", ints(0, 2)))),
        )
        val track = assertNotNull(Mp4.audioTrack(file))
        assertEquals(214L - 100L, track.fragments)
        assertEquals(0.114, track.statedSeconds, 1e-12)
        val cut = fragmentedFile(box("moof", traf(1, 0, ByteArray(0), box("trun", ints(0x100, 3, 1, 2)))))
        assertNull(assertNotNull(Mp4.audioTrack(cut)).fragments)
        val none = assertNotNull(Mp4.audioTrack(fragmentedFile()))
        assertTrue(none.fragmented)
        assertNull(none.fragments)
        assertEquals(0.0, none.statedSeconds)
    }

    @Test fun anMp4sEditListIsTheSamplesFfmpegKeeps() {
        for (r in records.filter { it.str("format") == "M4A" && !fragmented(it) }) {
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

    /** An edit whose segment runs past its media: decode.m4a's edit made longer (7,700 samples past its media's
     * 132,300 after the priming), which FFmpeg 9.0.2 decodes to its media's 132,300 (checked by hand, 2026-11-26), as
     * did an M4A of the owner's spike folder whose edit was 5 samples longer than its media (ParityRunTest). */
    @Test fun anEditPastItsMediaKeepsTheMediasSamplesAsFfmpegDoes() {
        val r = records.first { name(it).endsWith("decode.m4a") }
        val bytes = Corpus.fixture(name(r))
        val at = String(bytes, Charsets.ISO_8859_1).indexOf("elst")
        ByteBuffer.wrap(bytes).putInt(at + 12, 140_000)  // its one entry's segment, after the version and count
        val longer = tmp.newFile("longer.m4a").apply { writeBytes(bytes) }
        val track = Mp4.audioTrack(longer)!!
        val edit = track.edit()!!
        assertEquals(140_000L, edit.segment)
        assertEquals(132_300L, track.keptFrames(edit))
        assertEquals(440_995L, Mp4.Track(44100, 440_995, 1000, listOf(Mp4.Edit(10_000, 0))).let {
            it.keptFrames(it.edit()!!)
        })
    }

    /** decode.m4a's bytes, [patch]ed, as a file. */
    private fun patched(name: String, patch: (ByteArray, (String) -> Int) -> ByteArray): File {
        val r = records.first { name(it).endsWith("decode.m4a") }
        val bytes = Corpus.fixture(name(r))
        val at = { box: String -> String(bytes, Charsets.ISO_8859_1).indexOf(box) }
        return tmp.newFile(name).apply { writeBytes(patch(bytes, at)) }
    }

    /** The edit is bounded only by a media length that is known: the sample table's total (what FFmpeg indexes) before
     * `mdhd`'s duration; none at all in a fragmented file (its samples in `moof`s), whose `mdhd` and `stts` commonly
     * say 0. None of these decodes to nothing. */
    @Test fun anEditIsBoundedByTheSampleTablesTotalAndNeverByALengthThatIsntKnown() {
        // mdhd's duration 0, the sample table whole: the table bounds it (132,300 after the priming).
        val noDuration = Mp4.audioTrack(patched("mdhd0.m4a") { b, at ->
            ByteBuffer.wrap(b).putInt(at("mdhd") + 20, 0); b
        })!!
        assertEquals(0L, noDuration.duration)
        assertEquals(132_300L, noDuration.keptFrames(noDuration.edit()!!))
        // The table's last sample 4 long, not 204: it sums below the edit, and bounds it, as FFmpeg 9.0.2's 132,100.
        val shortTable = Mp4.audioTrack(patched("stts.m4a") { b, at ->
            ByteBuffer.wrap(b).putInt(at("stts") + 12 + 8 + 4, 4); b
        })!!
        assertEquals(133_124L, shortTable.samples)
        assertEquals(132_100L, shortTable.keptFrames(shortTable.edit()!!))
        // Fragmented: an mvex in the moov, mdhd and stts empty: no bound, the edit's own length.
        val fragmented = Mp4.audioTrack(patched("fragmented.m4a") { b, at ->
            val bb = ByteBuffer.wrap(b)
            bb.putInt(at("mdhd") + 20, 0)
            bb.putInt(at("stts") + 8, 0)
            val moov = at("moov") - 4
            val end = moov + bb.getInt(moov)
            val out = b.copyOfRange(0, end) + byteArrayOf(0, 0, 0, 8) + "mvex".toByteArray() +
                b.copyOfRange(end, b.size)
            ByteBuffer.wrap(out).putInt(moov, bb.getInt(moov) + 8)
            out
        })!!
        assertTrue(fragmented.fragmented)
        assertEquals(132_300L, fragmented.keptFrames(fragmented.edit()!!))
        // An edit of no length is no edit to trim to (a fragmented file's commonly is): the stated delay instead.
        assertNull(Mp4.Track(44100, 0, 1000, listOf(Mp4.Edit(0, 1024))).edit())
    }

    @Test fun anEditsLengthPastALongIsRefusedNeverWrapped() {
        // A hostile segment: Long.MAX_VALUE seconds of a movie of 1 a second, in a media of 44,100 a second.
        val track = Mp4.Track(44100, 300_000, 1, listOf(Mp4.Edit(Long.MAX_VALUE, 0)))
        assertFailsWith<ArithmeticException> { track.keptFrames(track.edit()!!) }
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
