package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.mirror.Http
import io.github.danielhp95.caracole.mirror.ServerAddress
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayInputStream
import java.io.File
import java.net.InetAddress
import java.net.ServerSocket
import java.net.SocketException
import kotlin.concurrent.thread
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** The computer's index brought to the phone: fetched from caracole serve, or copied from a file picked, then merged. */
class IndexImportsTest {
    @get:Rule val folder = TemporaryFolder()

    private val export = "SQLite format 3\u0000".toByteArray() + ByteArray(4096) { (it % 251).toByte() }
    /** The computer: a plain HTTP/1.1 server on 127.0.0.1 that answers every request with [answer]. */
    private val server = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"))
    private val asked = java.util.Collections.synchronizedList(mutableListOf<String>())
    @Volatile private var answer: Pair<Int, ByteArray> = 200 to export

    init {
        thread(isDaemon = true) {
            while (true) {
                val socket = try {
                    server.accept()
                } catch (e: SocketException) {
                    break
                }
                socket.use {
                    val input = it.getInputStream().bufferedReader(Charsets.ISO_8859_1)
                    val line = input.readLine() ?: return@use
                    while (!input.readLine().isNullOrEmpty()) Unit
                    asked.add(line.split(' ')[1])
                    val (status, body) = answer
                    val head = "HTTP/1.1 $status Answer\r\nContent-Type: application/vnd.sqlite3\r\n" +
                        "Content-Length: ${body.size}\r\nConnection: close\r\n\r\n"
                    it.getOutputStream().apply { write(head.toByteArray(Charsets.ISO_8859_1)); write(body); flush() }
                }
            }
        }
    }

    @After fun stop() = server.close()

    private val address get() = ServerAddress.parse("127.0.0.1:${server.localPort}")

    @Test
    fun `the computer's index comes whole from GET api peer index, into a file of its own in the cache`() {
        val cache = File(folder.root, "state/cache")
        val seen = mutableListOf<Pair<Long, Long>>()
        val file = IndexImports.download(Http(), address, cache) { done, total -> seen.add(done to total) }
        assertEquals(listOf("/api/peer/index"), asked)
        assertEquals(cache, file.parentFile)
        assertTrue(file.name.startsWith("index-") && file.name.endsWith(".sqlite"), file.name)
        assertContentEquals(export, file.readBytes())
        assertEquals(listOf(file.name), cache.list()!!.toList(), "nothing else left there")
        assertEquals(export.size.toLong() to export.size.toLong(), seen.last())
    }

    @Test
    fun `a computer with no index to give, or that sends something else, leaves nothing`() {
        val cache = File(folder.root, "cache")
        answer = 404 to "Not found".toByteArray()
        val old = assertFailsWith<IndexImportError> { IndexImports.download(Http(), address, cache) }
        assertTrue("newer caracole" in old.message!!, old.message)
        answer = 503 to ByteArray(0)
        val busy = assertFailsWith<IndexImportError> { IndexImports.download(Http(), address, cache) }
        assertTrue("503" in busy.message!!, busy.message)
        answer = 200 to "<html>Wi-Fi login</html>".toByteArray()
        val other = assertFailsWith<IndexImportError> { IndexImports.download(Http(), address, cache) }
        assertTrue("isn't an index" in other.message!!, other.message)
        assertEquals(emptyList(), cache.list().orEmpty().toList())
    }

    @Test
    fun `a file picked is copied whole into the cache, and only an SQLite file is taken`() {
        val cache = File(folder.root, "cache")
        val file = IndexImports.copy(ByteArrayInputStream(export), cache)
        assertContentEquals(export, file.readBytes())
        assertFailsWith<IndexImportError> { IndexImports.copy(ByteArrayInputStream("PK\u0003\u0004zip".toByteArray()), cache) }
        assertFailsWith<IndexImportError> { IndexImports.copy(ByteArrayInputStream(ByteArray(0)), cache) }
        assertEquals(listOf(file.name), cache.list()!!.toList())
    }

    @Test
    fun `a merge's job ends in a line of its own`() {
        fun view(text: String) = Json.parseToJsonElement(text).jsonObject
        val done = IndexImports.describe("done", view("""{"state":"done","note":"",
            "steps":[{"name":"merge","label":"Merging the index","state":"done","detail":"merged"}]}"""), at = 5L)
        assertEquals(Outcome(5L, true, "Indexes imported: merged"), done)
        val same = IndexImports.describe("done", view("""{"steps":[{"name":"merge","state":"done","detail":"nothing newer"}]}"""), at = 6L)
        assertEquals(Outcome(6L, true, "Indexes imported: nothing newer"), same)
        val failed = IndexImports.describe("failed", view("""{"state":"failed","note":"the file's schema is 14, the phone's 15",
            "steps":[{"name":"merge","state":"failed","detail":""}]}"""), at = 7L)
        assertEquals(Outcome(7L, false, "The import failed: the file's schema is 14, the phone's 15"), failed)
        val bare = IndexImports.describe("interrupted", view("{}"), at = 8L)
        assertFalse(bare.ok)
        assertEquals("The import failed: interrupted", bare.text)
        assertEquals(Outcome(9L, true, "Indexes imported"), IndexImports.describe("done", view("{}"), at = 9L))
    }
}
