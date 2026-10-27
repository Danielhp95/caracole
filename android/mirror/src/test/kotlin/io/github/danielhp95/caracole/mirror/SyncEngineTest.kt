package io.github.danielhp95.caracole.mirror

import io.github.danielhp95.caracole.mirror.FakeCaracole.Companion.sha256
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.net.ServerSocket
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class SyncEngineTest {
    @get:Rule val folder = TemporaryFolder()

    private val server = FakeCaracole()
    private val mirror by lazy { Mirror(folder.newFolder("files")) }
    private val engine by lazy { SyncEngine(mirror) }

    @After fun stop() = server.close()

    private val library = mapOf(
        "index.html" to "<html>library</html>".toByteArray(),
        "Estopa/Tu calorro/sheet.html" to "<html>sheet</html>".toByteArray(),
        "Estopa/Tu calorro/sheet.pdf" to "%PDF-1.7 sheet".toByteArray(),
        "Ñandú/Canción #1/sheet.cho" to "{title: Canción}".toByteArray(),
    )

    /** The mirror's whole state: the list on disk and every file in its folders. */
    private fun snapshot(): Map<String, String> =
        mirror.dir.walkTopDown().filter { it.isFile }.associate { it.relativeTo(mirror.dir).path to sha256(it.readBytes()) }

    private fun assertMirrors(files: Map<String, ByteArray>) {
        val manifest = assertNotNull(mirror.reload())
        assertEquals(files.keys, manifest.byPath.keys)
        for ((path, bytes) in files) assertContentEquals(bytes, assertNotNull(mirror.lookup(path)).file.readBytes(), path)
        val blobs = mirror.blobs.list()!!.toSet()
        assertEquals(files.values.map { sha256(it) }.toSet(), blobs, "each content once, nothing else")
    }

    @Test
    fun `a first sync mirrors every file listed, and the server's list as it sent it`() {
        server.publish(library)
        val seen = mutableListOf<Progress>()
        val report = engine.sync(server.address, progress = { seen.add(it) })

        assertMirrors(library)
        assertContentEquals(server.manifest, mirror.manifestFile.readBytes())
        assertEquals(SyncReport(4, library.values.sumOf { it.size.toLong() }, 4, 0, 0, 4, emptyList()), report)
        assertEquals((0..4).map { Progress(it, 4) }, seen)
        assertEquals("4 files new", report.summary())
        assertTrue("/%C3%91and%C3%BA/Canci%C3%B3n%20%231/sheet.cho" in server.requests, server.requests.toString())
    }

    @Test
    fun `a later sync downloads only new bytes, and deletes the blobs no entry names`() {
        server.publish(library)
        engine.sync(server.address)
        server.requests.clear()

        val next = library - "Estopa/Tu calorro/sheet.pdf" +
            ("Estopa/Tu calorro/sheet.html" to "<html>sheet, rendered again</html>".toByteArray()) +
            ("Estopa/Tu calorro/version-39144.html" to "<html>a version</html>".toByteArray())
        server.publish(next)
        val report = engine.sync(server.address)

        assertMirrors(next)
        assertEquals(1, report.added)
        assertEquals(1, report.changed)
        assertEquals(1, report.removed)
        assertEquals(2, report.downloaded)
        assertEquals("1 file new, 1 changed, 1 removed", report.summary())
        assertEquals(
            setOf("/api/offline", "/Estopa/Tu%20calorro/sheet.html", "/Estopa/Tu%20calorro/version-39144.html"),
            server.requests.toSet(),
        )
    }

    @Test
    fun `nothing new is nothing downloaded`() {
        server.publish(library)
        engine.sync(server.address)
        server.requests.clear()
        val report = engine.sync(server.address)
        assertEquals(listOf("/api/offline"), server.requests.toList())
        assertEquals("nothing changed", report.summary())
    }

    @Test
    fun `two paths with the same bytes share one download`() {
        val same = "same bytes".toByteArray()
        server.publish(mapOf("index.html" to "<html/>".toByteArray(), "a/sheet.txt" to same, "b/sheet.txt" to same))
        val report = engine.sync(server.address)
        assertEquals(2, report.downloaded)
        assertEquals(1, server.requests.count { it.endsWith("sheet.txt") })
        assertContentEquals(same, mirror.lookup("b/sheet.txt")!!.file.readBytes())
    }

    /**
     * Syncs [library], lists [next] with [arrange] making its sync fail with [E], and checks the mirror shows
     * [library] still, every file of it as it was; the one thing more allowed is a blob of [next] downloaded
     * and checked before the failure, which waits for the next sync.
     */
    private inline fun <reified E : SyncError> failsAndKeepsTheMirror(
        next: Map<String, ByteArray> = library + ("new.pdf" to "%PDF new".toByteArray()),
        arrange: (List<Entry>) -> Unit,
    ): E {
        server.publish(library)
        engine.sync(server.address)
        val before = snapshot()
        arrange(server.publish(next))
        val error = assertFailsWith<E> { engine.sync(server.address) }
        val after = snapshot()
        assertEquals(before, after.filterKeys { it in before }, "every file before is as it was")
        val checked = next.values.map { "blobs/" + sha256(it) }.toSet()
        assertTrue((after.keys - before.keys).all { it in checked }, "only checked blobs more: ${after.keys - before.keys}")
        assertEquals(library.keys, assertNotNull(mirror.reload()).byPath.keys)
        for ((path, bytes) in library) assertContentEquals(bytes, assertNotNull(mirror.lookup(path)).file.readBytes(), path)
        return error
    }

    @Test
    fun `a file whose bytes don't match fails the sync and keeps the mirror before it`() {
        val error = failsAndKeepsTheMirror<SyncError.Changed> { entries ->
            val pdf = entries.first { it.path == "new.pdf" }
            server.answers[pdf.url] = { FakeCaracole.send(it, 200, "%PDF mew".toByteArray(), "application/pdf") }
        }
        assertTrue("sync again" in error.message!!, error.message)
        assertTrue("new.pdf" in error.message!!, error.message)
    }

    @Test
    fun `a file longer than listed is cut off and fails`() {
        val error = failsAndKeepsTheMirror<SyncError.Changed> { entries ->
            val pdf = entries.first { it.path == "new.pdf" }
            server.answers[pdf.url] = { exchange ->
                exchange.sendResponseHeaders(200, 0) // chunked: no length said
                val chunk = ByteArray(1024) { 'x'.code.toByte() }
                try {
                    repeat(1024) { exchange.responseBody.write(chunk) }
                } catch (e: java.io.IOException) { /* the app stopped reading */ }
            }
        }
        assertTrue("longer than 8 bytes" in error.message!!, error.message)
    }

    @Test
    fun `a length said that isn't the listed size fails before reading`() {
        val error = failsAndKeepsTheMirror<SyncError.Changed> { entries ->
            val pdf = entries.first { it.path == "new.pdf" }
            server.answers[pdf.url] = { FakeCaracole.send(it, 200, "%PDF new and more".toByteArray(), "application/pdf") }
        }
        assertTrue("it is 17 bytes, not 8" in error.message!!, error.message)
    }

    @Test
    fun `a listed file the server no longer has fails the sync, mid-way, and keeps the mirror before it`() {
        val next = library + ("a.pdf" to "%PDF a".toByteArray()) + ("b.pdf" to "%PDF b".toByteArray()) + ("c.pdf" to "%PDF c".toByteArray())
        failsAndKeepsTheMirror<SyncError.Changed>(next) { entries ->
            server.answers[entries.first { it.path == "b.pdf" }.url] = { FakeCaracole.send(it, 404, "gone".toByteArray(), "text/plain") }
        }
    }

    @Test
    fun `a redirect is never followed, to another host or any`() {
        FakeCaracole().use { other ->
            failsAndKeepsTheMirror<SyncError.Changed> { entries ->
                val pdf = entries.first { it.path == "new.pdf" }
                server.answers[pdf.url] = { exchange ->
                    exchange.responseHeaders.add("Location", "${other.address}/new.pdf")
                    exchange.sendResponseHeaders(302, -1)
                }
            }
            assertEquals(emptyList(), other.requests.toList())
        }
    }

    @Test
    fun `a sync stopped part-way leaves the mirror as it was`() {
        var downloads = 0
        server.publish(library)
        engine.sync(server.address)
        val before = snapshot()
        server.publish(library + ("x.pdf" to "%PDF x".toByteArray()) + ("y.pdf" to "%PDF y".toByteArray()))
        assertFailsWith<SyncError.Cancelled> {
            engine.sync(server.address, progress = { downloads = it.done }, cancelled = { downloads >= 1 })
        }
        assertEquals(library.keys, assertNotNull(mirror.reload()).byPath.keys, "the list is the one before")
        assertEquals(before.keys + "blobs/${sha256("%PDF x".toByteArray())}", snapshot().keys, "the blob checked waits for the next sync")
        engine.sync(server.address)
        assertMirrors(library + ("x.pdf" to "%PDF x".toByteArray()) + ("y.pdf" to "%PDF y".toByteArray()))
    }

    @Test
    fun `a sync clears what an earlier one left, temporary files and blobs no entry names`() {
        server.publish(library)
        engine.sync(server.address)
        File(mirror.blobs, "${Mirror.TMP}0123").writeText("half a file")
        File(mirror.dir, "${Mirror.TMP}4567").writeText("half a list")
        File(mirror.blobs, "f".repeat(64)).writeText("an old blob")
        engine.sync(server.address)
        assertMirrors(library)
        assertFalse(File(mirror.dir, "${Mirror.TMP}4567").exists())
    }

    @Test
    fun `nothing listening is no answer, and changes nothing`() {
        server.publish(library)
        engine.sync(server.address)
        val before = snapshot()
        val closed = ServerSocket(0).use { it.localPort }
        val error = assertFailsWith<SyncError.NoAnswer> { engine.sync(ServerAddress.parse("127.0.0.1:$closed")) }
        assertTrue(error.message!!.startsWith("No answer from http://127.0.0.1:$closed"), error.message)
        assertEquals(before, snapshot())
    }

    @Test
    fun `a server without the list is no caracole, and a newer list is refused before any download`() {
        server.answers["/api/offline"] = { FakeCaracole.send(it, 404, "<html>nope</html>".toByteArray(), "text/html") }
        assertFailsWith<SyncError.NotCaracole> { engine.sync(server.address) }
        assertNull(mirror.reload())

        server.answers.clear()
        server.publish(library)
        server.manifest = String(server.manifest).replace("\"format\": 1", "\"format\": 2").toByteArray()
        server.requests.clear()
        assertFailsWith<SyncError.NewerFormat> { engine.sync(server.address) }
        assertEquals(listOf("/api/offline"), server.requests.toList())
        assertNull(mirror.reload())
    }

    @Test
    fun `a caracole that can't share its library now says why, and the copy stays`() {
        server.publish(library)
        engine.sync(server.address)
        val before = snapshot()
        val why = "The library page isn't the one caracole last wrote: run caracole todo, then sync again."
        server.answers["/api/offline"] = {
            FakeCaracole.send(it, 503, "{\"error\": ${FakeCaracole.quote(why)}}".toByteArray(), "application/json; charset=utf-8")
        }
        val error = assertFailsWith<SyncError.Unavailable> { engine.sync(server.address) }
        assertEquals("caracole at ${server.address} can't share its library now: $why", error.message)
        assertEquals(before, snapshot())

        server.answers["/api/offline"] = { FakeCaracole.send(it, 503, "busy".toByteArray(), "text/plain") }
        val bare = assertFailsWith<SyncError.Unavailable> { engine.sync(server.address) }
        assertTrue(bare.message!!.endsWith("it answered HTTP 503"), bare.message)
    }

    @Test
    fun `entries the server listed wrong are left out and said, the rest mirrored`() {
        server.publish(library, extra = listOf("""{"path": "../escape.pdf", "url": "/x", "size": 1, "sha256": "${"a".repeat(64)}", "type": "application/pdf"}"""))
        val report = engine.sync(server.address)
        assertMirrors(library)
        assertEquals(1, report.skipped.size)
        assertEquals("4 files new; 1 left out (the server listed them wrong)", report.summary())
    }

    @Test
    fun `fetching the list alone downloads nothing and writes nothing`() {
        server.publish(library)
        val fetched = engine.fetchManifest(server.address)
        assertEquals(4, fetched.manifest.entries.size)
        assertEquals(listOf("/api/offline"), server.requests.toList())
        assertEquals(emptyMap(), snapshot())
        engine.sync(server.address, fetched)
        assertEquals(1, server.requests.count { it == "/api/offline" }, "a list fetched is used, not asked for again")
        assertMirrors(library)
    }
}
