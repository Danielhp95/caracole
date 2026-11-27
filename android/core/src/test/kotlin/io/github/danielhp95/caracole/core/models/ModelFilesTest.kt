package io.github.danielhp95.caracole.core.models

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

class ModelFilesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val pins = ModelFiles.read()

    @Test fun thePinsAreModelsJsons() {
        assertEquals(1, pins.contract)
        assertEquals("models", pins.release)
        assertEquals(listOf("btc-graph.onnx", "btc_model_large_voca.pt", "beat_this-final0-fp16.onnx"),
                     pins.files.map { it.name })
        assertEquals(listOf(1_405_441L, 12_229_576L, 42_677_145L), pins.files.map { it.bytes })
        assertEquals(From.App, pins.files[0].from)
        assertEquals(From.Blob("jayg996/BTC-ISMIR19", "2682317be668032e6e4b269ded36adaa2ad57df0",
                               "test/btc_model_large_voca.pt", "11c6edbaaaee33737aa7a41dcb9044191630326f"),
                     pins.files[1].from)
        assertEquals(From.Release("beat_this-final0-fp16.onnx"), pins.files[2].from)
        assertEquals("1673d23f8f9a55ae7f9e8b80a51da616debb22675b8d8b67ea6ce0ef37b0ab51", pins.files[1].sha256)
        assertEquals(File("/state/models/c1"), pins.folder(File("/state")))
    }

    @Test fun carriedIsTheOneProbeOfWhetherThisBuildHasTheModels() {
        assertEquals(pins, ModelFiles.carried())
        // A build whose classpath holds no models.json (the release's: :core ships none): null, never a throw.
        val none = java.net.URLClassLoader(arrayOf(), null)
        assertNull(ModelFiles.carried(none))
        val e = kotlin.test.assertFailsWith<ModelsNotCarried> { ModelFiles.read(none) }
        assertEquals("This build carries no chord models.", e.message)
    }

    @Test fun theAppsGraphIsThePinnedOne() {
        val graph = pins.files[0]
        val bytes = ModelFiles.resource("caracole/autochords/${graph.name}")!!.use { it.readBytes() }
        assertEquals(graph.bytes, bytes.size.toLong())
        assertEquals(graph.sha256, ModelFiles.sha256(bytes.inputStream()))
    }

    /** The authors' own file (nix/autochords.nix's pin, `CARACOLE_BTC_WEIGHTS` in `nix develop ./android`): the size
     * and SHA-256 models.json pins, and every range BTC's graph reads in it a whole tensor of finite float32s. */
    @Test fun theAuthorsFileIsThePinnedOneAndHoldsEveryTensorTheGraphReadsInIt() {
        val path = System.getenv("CARACOLE_BTC_WEIGHTS")
        assumeTrue("CARACOLE_BTC_WEIGHTS names no file (outside nix develop ./android)",
                   path != null && File(path).isFile)
        val weights = File(path!!)
        val pin = pins.files[1]
        assertEquals(pin.bytes, weights.length())
        assertEquals(pin.sha256, ModelFiles.sha256(weights))
        val graph = ModelFiles.resource("caracole/autochords/${pins.files[0].name}")!!.use { it.readBytes() }
        val tensors = Onnx.externalTensors(graph)
        assertTrue("the graph reads ${tensors.size} tensors from the authors' file", tensors.size > 50)
        var end = 0L
        RandomAccessFile(weights, "r").use { file ->
            for (t in tensors.sortedBy { it.offset }) {
                assertEquals(t.name, pin.name, t.location)
                assertEquals(t.name, 1, t.dataType)  // FLOAT
                assertEquals(t.name, 4 * t.dims.fold(1L, Long::times), t.length)
                assertTrue("${t.name} overlaps the tensor before it", t.offset >= end)
                assertTrue("${t.name} past the file's end", t.offset + t.length <= weights.length())
                end = t.offset + t.length
                val bytes = ByteArray(t.length.toInt())
                file.seek(t.offset)
                file.readFully(bytes)
                val floats = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
                for (i in 0 until floats.limit()) assertTrue("${t.name}[$i] isn't finite", floats[i].isFinite())
            }
        }
    }

    // --- installed and verify --------------------------------------------------------------------------------------

    private fun fake(): Pins {
        val files = listOf("a.onnx" to "aaa", "b.pt" to "bbbb", "c.onnx" to "cc")
        return Pins(1, "models", files.map { (name, text) ->
            Pin(name, text.length.toLong(), ModelFiles.sha256(text.byteInputStream()), From.App)
        })
    }

    private fun installedFolder(pins: Pins, name: String = "c1"): File {
        val dir = tmp.newFolder(name)
        File(dir, "a.onnx").writeText("aaa")
        File(dir, "b.pt").writeText("bbbb")
        File(dir, "c.onnx").writeText("cc")
        ModelFiles.writeManifest(dir, pins)
        return dir
    }

    @Test fun aFolderWithItsManifestIsInstalledWithNoHash() {
        val pins = fake()
        val dir = installedFolder(pins)
        assertNull(ModelFiles.installed(dir, pins))
        assertNull(ModelFiles.verify(dir, pins))
    }

    @Test fun whatIsntWholeIsSaid() {
        val pins = fake()
        assertEquals(ModelFiles.NOT_HERE, ModelFiles.installed(File(tmp.root, "none"), pins))
        val dir = installedFolder(pins)
        File(dir, ModelFiles.MANIFEST).delete()
        assertEquals(ModelFiles.NOT_WHOLE, ModelFiles.installed(dir, pins))  // never placed whole
        File(dir, ModelFiles.MANIFEST).writeText("{not json")
        assertEquals(ModelFiles.NOT_WHOLE, ModelFiles.installed(dir, pins))
        ModelFiles.writeManifest(dir, pins)
        File(dir, "b.pt").delete()
        assertEquals("The chord models on the phone aren't whole: no b.pt.", ModelFiles.installed(dir, pins))
        // Another contract's, or other pins': not these.
        val other = pins.copy(contract = 2)
        assertEquals(ModelFiles.OTHER, ModelFiles.installed(installedFolder(other, "other"), pins))
    }

    @Test fun aFileChangedSinceItsCheckIsSaidByItsTimeAndVerifyHashesWhatAStatCantSee() {
        val pins = fake()
        val dir = installedFolder(pins)
        val b = File(dir, "b.pt")
        val at = b.lastModified()
        b.writeText("BBBB")  // the same size
        b.setLastModified(at + 2000)
        assertEquals("b.pt on the phone has changed since it was downloaded.", ModelFiles.installed(dir, pins))
        b.setLastModified(at)  // its time put back: a stat can't tell
        assertNull(ModelFiles.installed(dir, pins))
        assertEquals("b.pt on the phone isn't the file caracole's chords are made with (its SHA-256 differs).",
                     ModelFiles.verify(dir, pins))
    }

    @Test fun sweepTakesWhatACutOffFetchLeftBesideItsFolderAlone() {
        val into = File(tmp.root, "c1")
        val part = File(tmp.root, ".c1-0123456789abcdef.part").apply { mkdirs() }
        File(part, "b.pt").writeText("half")
        File(tmp.root, ".c1-fedcba9876543210.old").mkdirs()
        val others = listOf(".c1-xyz.part", ".c2-0123456789abcdef.part", "c1-0123456789abcdef.part")
        for (name in others) File(tmp.root, name).mkdirs()
        assertEquals(listOf(".c1-0123456789abcdef.part", ".c1-fedcba9876543210.old"), ModelFiles.sweep(into))
        assertEquals(others.sorted(), tmp.root.list()!!.sorted())
    }
}

/** Just enough of ONNX's protobuf to list the initializers a graph keeps outside it (ModelProto.graph = 7,
 * GraphProto.initializer = 5; TensorProto's dims 1, data_type 2, name 8, external_data 13, data_location 14). */
private object Onnx {
    class Tensor(val name: String, val dims: List<Long>, val dataType: Int, val location: String, val offset: Long,
                 val length: Long)

    fun externalTensors(model: ByteArray): List<Tensor> {
        val graph = fields(model).single { it.first == 7 }.second as ByteArray
        return fields(graph).filter { it.first == 5 }.mapNotNull { tensor(it.second as ByteArray) }
    }

    private fun tensor(bytes: ByteArray): Tensor? {
        val fields = fields(bytes)
        if (fields.none { it.first == 14 && it.second == 1L }) return null  // EXTERNAL
        val dims = fields.filter { it.first == 1 }.flatMap { (_, v) ->
            if (v is Long) listOf(v) else packed(v as ByteArray)
        }
        val where = fields.filter { it.first == 13 }.associate { (_, v) ->
            val entry = fields(v as ByteArray)
            fun text(n: Int) = String(entry.single { it.first == n }.second as ByteArray, Charsets.UTF_8)
            text(1) to text(2)
        }
        return Tensor(String(fields.single { it.first == 8 }.second as ByteArray, Charsets.UTF_8), dims,
                      (fields.single { it.first == 2 }.second as Long).toInt(), where.getValue("location"),
                      where.getValue("offset").toLong(), where.getValue("length").toLong())
    }

    /** Each field of a message: its number and its value (a Long for a varint or a fixed width, bytes else). */
    private fun fields(bytes: ByteArray): List<Pair<Int, Any>> {
        val out = mutableListOf<Pair<Int, Any>>()
        var at = 0
        fun varint(): Long {
            var value = 0L
            var shift = 0
            while (true) {
                val b = bytes[at++].toInt() and 0xff
                value = value or ((b and 0x7f).toLong() shl shift)
                if (b < 0x80) return value
                shift += 7
            }
        }
        while (at < bytes.size) {
            val key = varint()
            val number = (key ushr 3).toInt()
            when ((key and 7).toInt()) {
                0 -> out += number to varint()
                1 -> {
                    out += number to ByteBuffer.wrap(bytes, at, 8).order(ByteOrder.LITTLE_ENDIAN).long
                    at += 8
                }
                2 -> {
                    val n = varint().toInt()
                    out += number to bytes.copyOfRange(at, at + n)
                    at += n
                }
                5 -> {
                    out += number to ByteBuffer.wrap(bytes, at, 4).order(ByteOrder.LITTLE_ENDIAN).int.toLong()
                    at += 4
                }
                else -> throw IllegalArgumentException("wire type ${key and 7}")
            }
        }
        return out
    }

    private fun packed(bytes: ByteArray): List<Long> {
        val out = mutableListOf<Long>()
        var at = 0
        while (at < bytes.size) {
            var value = 0L
            var shift = 0
            while (true) {
                val b = bytes[at++].toInt() and 0xff
                value = value or ((b and 0x7f).toLong() shl shift)
                if (b < 0x80) break
                shift += 7
            }
            out += value
        }
        return out
    }
}
