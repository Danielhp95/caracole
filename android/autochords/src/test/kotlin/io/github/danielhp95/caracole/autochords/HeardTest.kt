package io.github.danielhp95.caracole.autochords

import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlin.test.assertNull

/** [Heard], the design's §4.4 `heard`, its checkpoints ([Checkpoints]) and recognize's common names
 * ([Labels.recognized]). */
class HeardTest {
    @get:Rule val tmp = TemporaryFolder()

    private val heard = Heard(Heard.CONTRACT, 225.31, listOf(ChordSegment(0.0, 1.204, "N"),
        ChordSegment(1.204, 3.5, "Am7")), listOf(0.48, 0.96, 1.44), listOf(0.48))

    @Test
    fun `heard is the design's contract, member for member`() {
        val doc = Json.parseToJsonElement(heard.json()).jsonObject
        assertEquals(listOf("contract", "duration", "chords", "beats", "downbeats"), doc.keys.toList())
        assertEquals(1, doc["contract"]!!.jsonPrimitive.int)
        assertEquals("[1.204,3.5,\"Am7\"]", doc["chords"]!!.jsonArray[1].toString())
        assertEquals(heard, Heard.read(heard.json()))
    }

    @Test
    fun `a heard of another contract is never read`() {
        val other = heard.json().replace("\"contract\":1", "\"contract\":2")
        assertFailsWith<IllegalArgumentException> { Heard.read(other) }
    }

    @Test
    fun `a checkpoint's folder names its audio's sha16 and the contract`() {
        val audio = tmp.newFile("a.wav").apply { writeText("abc") }
        // SHA-256 of "abc": ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad.
        val points = Checkpoints.of(tmp.root, audio)
        assertEquals(File(tmp.root, "ba7816bf8f01cfea-c1"), points.folder)
        assertEquals("ba7816bf8f01cfea", Checkpoints.sha16(audio))
    }

    @Test
    fun `a checkpoint is written whole under its name or not at all, and a part is never read`() {
        val points = Checkpoints.of(tmp.root, tmp.newFile("a.wav").apply { writeText("x") })
        assertNull(points.read(Checkpoints.CHORDS))
        // A write cut off: its part alone is there, which nothing reads.
        File(points.folder.apply { mkdirs() }, Checkpoints.CHORDS + Checkpoints.PART).writeText("{\"harte\":[[0.0,")
        assertNull(points.read(Checkpoints.CHORDS))
        points.write(Checkpoints.CHORDS, "{}")
        assertEquals("{}", points.read(Checkpoints.CHORDS))
        assertEquals(listOf(Checkpoints.CHORDS), points.folder.list()!!.toList())
    }

    @Test
    fun `a checkpoint that won't parse is absent, deleted to be made again`() {
        val points = Checkpoints.of(tmp.root, tmp.newFile("a.wav").apply { writeText("y") })
        points.folder.mkdirs()
        // A power cut after the rename, before the disk had the bytes: a cut file, or an empty one.
        points.file(Checkpoints.CHORDS).writeText("{\"harte\":[[0.0,1.2")
        points.file(Checkpoints.HEARD).writeText("")
        assertNull(points.parsed(Checkpoints.CHORDS, Checkpoints::readChords))
        assertNull(points.parsed(Checkpoints.HEARD, Heard::read))
        assertFalse(points.has(Checkpoints.CHORDS))
        assertFalse(points.has(Checkpoints.HEARD))
        points.write(Checkpoints.CHORDS, Checkpoints.chordsJson(emptyList()))
        assertEquals(emptyList(), points.parsed(Checkpoints.CHORDS, Checkpoints::readChords))
    }

    @Test
    fun `a pcm shorter than its meta says is no pcm`() {
        val points = Checkpoints.of(tmp.root, tmp.newFile("a.wav").apply { writeText("z") })
        val meta = Checkpoints.Pcm(1.0, 22050, 22050)
        points.write(Checkpoints.PCM_META, Checkpoints.pcmJson(meta))
        points.into(Checkpoints.PCM) { it.writeBytes(ByteArray(4 * 22050)) }
        assertTrue(points.pcmWhole(meta))
        points.file(Checkpoints.PCM).writeBytes(ByteArray(4 * 22049))
        assertFalse(points.pcmWhole(meta))
    }

    @Test
    fun `a sweep takes what cut-off stages left in any song's folder, never a checkpoint`() {
        val a = File(tmp.root, "aaaa-c1").apply { mkdirs() }
        val b = File(tmp.root, "bbbb-c1").apply { mkdirs() }
        for (name in listOf("decoded.f32", "mono.f32", "pcm.f32.part", Checkpoints.PCM, Checkpoints.CHORDS)) {
            File(a, name).writeText("x")
        }
        File(b, "beats.json.part").writeText("x")
        Checkpoints.sweep(tmp.root)
        assertEquals(setOf(Checkpoints.PCM, Checkpoints.CHORDS), a.list()!!.toSet())
        assertEquals(emptySet(), b.list()!!.toSet())
    }

    @Test
    fun `chords and beats round-trip through their checkpoints`() {
        val harte = listOf(ChordSegment(0.0, 1.204, "N"), ChordSegment(1.204, 3.5, "A:min7"))
        assertEquals(harte, Checkpoints.readChords(Checkpoints.chordsJson(harte)))
        val beats = listOf(0.5, 1.0) to listOf(0.5)
        assertEquals(beats, Checkpoints.readBeats(Checkpoints.beatsJson(beats.first, beats.second)))
        val pcm = Checkpoints.Pcm(12.0, 264_599, 264_600)
        assertEquals(pcm, Checkpoints.readPcm(Checkpoints.pcmJson(pcm)))
    }

    @Test
    fun `recognized is btc_py's recognize over the computer's own argmax`() {
        val names = Labels.vocabulary(170)
        val clips = Corpus.lines("autochords/models.jsonl").drop(1)
            .filter { it["kind"]?.jsonPrimitive?.content == "clip" }
        assertEquals(4, clips.size)
        for (clip in clips) {
            val btc = clip["btc"]!!.jsonObject
            val argmax = btc["argmax"]!!.jsonArray.map { it.jsonPrimitive.int }.toIntArray()
            val harte = Labels.spellForKey(Labels.framesToSegments(argmax, Labels.FRAME_SECONDS, names))
            val want = btc["segments"]!!.jsonArray.map { s ->
                val (start, end, label) = s.jsonArray
                ChordSegment(start.jsonPrimitive.content.toDouble(), end.jsonPrimitive.content.toDouble(),
                    label.jsonPrimitive.content)
            }
            assertEquals(want, Labels.recognized(harte), clip["clip"].toString())
        }
        assertEquals(listOf(ChordSegment(0.0, 2.0, "C"), ChordSegment(2.0, 3.0, "N")),
            Labels.recognized(listOf(ChordSegment(0.0, 1.0, "C"), ChordSegment(1.0, 2.0, "C:maj"),
                ChordSegment(2.0, 2.5, "X"), ChordSegment(2.5, 3.0, "N"))))
    }
}
