package io.github.danielhp95.caracole.autochords.frontend

import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.Base64
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** [AudioLengths] (and [MpegFrames], mpeg_frames.py's count) against what the computer's audio store reads of each
 * file (vectors/web/audio_routes.jsonl's `caracole.audio_store.examine` records: the committed fixtures, and tiny
 * files of every format tagged by mutagen), each length to the bit, handed a file named with no audio extension, as a
 * stage hands the examiner its spool. */
class AudioLengthsTest {
    @get:Rule val tmp = TemporaryFolder()

    private val records by lazy {
        Corpus.records("web/audio_routes.jsonl").filter { it.fn == "caracole.audio_store.examine" }
    }

    private fun spool(r: io.github.danielhp95.caracole.core.testing.Record): Pair<String, File> {
        val name = r.extra["file"]?.jsonPrimitive?.content
        val bytes = if (name != null) Corpus.fixture(name)
                    else Base64.getDecoder().decode(r.extra.getValue("bytes").jsonPrimitive.content)
        return (name ?: "tagged ${(r.out as JsonObject).getValue("format").jsonPrimitive.content}") to
            tmp.newFile().apply { writeBytes(bytes) }  // no extension, as `.upload-<id>.part`
    }

    @Test fun everyFilesLengthIsTheStoresToTheBit() {
        assertTrue(records.size >= 20, "${records.size} records")
        for (r in records) {
            val (name, file) = spool(r)
            val out = r.out!!.jsonObject
            val format = out.getValue("format").jsonPrimitive.content
            assertEquals(out.getValue("duration").jsonPrimitive.double, assertNotNull(AudioLengths.of(file, format), name),
                         0.0, name)
        }
        assertEquals(setOf("MP3", "M4A", "FLAC", "WAV", "Ogg", "AIFF"),
                     records.map { it.out!!.jsonObject.getValue("format").jsonPrimitive.content }.toSet())
    }

    @Test fun anMp3WhoseFirstFrameNamesNoLengthIsCountedAndOneThatNamesItIsNot() {
        val counted = MpegFrames.count(File(tmp.root, "x").apply { writeBytes(Corpus.fixture("audio/long-guess.mp3")) })
        assertNotNull(counted)
        assertTrue(counted.guessed > counted.seconds, "a guess past its frames: $counted")
        assertNull(MpegFrames.count(File(tmp.root, "y").apply { writeBytes(Corpus.fixture("audio/xing.mp3")) }))
        assertNull(MpegFrames.count(ByteArray(0)))
        assertNull(MpegFrames.count("not an mp3 at all".toByteArray()))
    }

    @Test fun anM4aWithNoSoundTrackHasNoLength() {
        // the vector's clip.m4a, a video track alone (helpers/audio_files.mp4(video=True)), which the store refuses
        val clip = Corpus.records("web/audio_routes.jsonl").filter { it.fn == "scene" }
            .flatMap { it.extra.getValue("steps").jsonArray }.map { it.jsonObject.getValue("ask").jsonObject }
            .single { "clip.m4a" in it.getValue("target").jsonPrimitive.content }
        val video = tmp.newFile().apply { writeBytes(Base64.getDecoder().decode(clip.getValue("body").jsonPrimitive.content)) }
        assertNotNull(Mp4.audioTrack(video), "an MP4 mutagen reads")
        assertNull(AudioLengths.of(video, "M4A"))
        assertNull(AudioLengths.of(tmp.newFile().apply { writeText("text") }, "M4A"))
        assertNull(AudioLengths.of(tmp.newFile().apply { writeText("fLaC") }, "FLAC"))
    }
}
