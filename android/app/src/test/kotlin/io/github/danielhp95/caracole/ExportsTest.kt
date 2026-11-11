package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.net.URI
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertTrue

/**
 * The page's export (the sync sheet's Export: a link to `GET /api/sync/export?export=<id>` with `download`) reaches
 * Android's share sheet: told from any other download, read from the phone's server in this process, and copied under
 * the name the server's attachment gives it.
 */
class ExportsTest {
    @get:Rule val folder = TemporaryFolder()

    private val origin = "http://127.0.0.1:8738"
    private val export = "$origin/api/sync/export?export=0123456789abcdef"
    private val asked = mutableListOf<Request>()
    private fun files(answer: (Request) -> Response) =
        LocalFiles({ request -> asked.add(request); answer(request) }, URI(origin), "s3cr3t")

    @Test
    fun `an export's link is told from any other download`() {
        assertTrue(Exports.isExport(export, origin))
        assertTrue(Exports.isExport("$export#done", origin), "a fragment changes nothing")
        assertTrue(Exports.isExport("$origin/api/sync/export?x=1&export=0123456789abcdef", origin))
        assertFalse(Exports.isExport("$origin/api/sync/export", origin), "no export named")
        assertFalse(Exports.isExport("$origin/api/sync/export?export=", origin), "an empty one")
        assertFalse(Exports.isExport("$origin/api/sync/exports?export=0123456789abcdef", origin))
        assertFalse(Exports.isExport("$origin/Estopa/Tu%20calorro/guitar-1.gp5", origin), "a kept file's download")
        assertFalse(Exports.isExport("$origin/export.pdf?sheet=x", origin), "the viewer's Export PDF")
        assertFalse(Exports.isExport("http://127.0.0.1:8737/api/sync/export?export=0123456789abcdef", origin),
                    "another port: caracole serve's, in the browser")
        assertFalse(Exports.isExport("http://localhost:8738/api/sync/export?export=0123456789abcdef", origin))
        assertFalse(Exports.isExport("https://127.0.0.1:8738/api/sync/export?export=0123456789abcdef", origin))
        assertFalse(Exports.isExport("not a url at all", origin))
        assertFalse(Exports.isExport(export, null), "no server yet")
    }

    @Test
    fun `the shared file is named as the server's attachment names it`() {
        assertEquals("horde_logbook-03-11-26.caracole",
                     Exports.nameOf("attachment; filename=\"horde_logbook-03-11-26.caracole\""))
        // download_names.content_disposition: the ASCII name, then the UTF-8 one, which is read first.
        assertEquals("Cañón-03-11-26.caracole", Exports.nameOf(
            "attachment; filename=\"Ca_o_n-03-11-26.caracole\"; filename*=UTF-8''Ca%C3%B1%C3%B3n-03-11-26.caracole"))
        assertEquals("a b.caracole", Exports.nameOf("attachment; filename*=utf-8''a%20b.caracole"))
        assertEquals("plain.caracole", Exports.nameOf("attachment; filename=plain.caracole"))
        assertEquals(Exports.DEFAULT_NAME, Exports.nameOf(null))
        assertEquals(Exports.DEFAULT_NAME, Exports.nameOf(""))
        assertEquals(Exports.DEFAULT_NAME, Exports.nameOf("attachment"))
        assertEquals(Exports.DEFAULT_NAME, Exports.nameOf("attachment; filename=\"\""))
    }

    @Test
    fun `a name with a path in it is cut to its last part`() {
        assertEquals("x.caracole", Exports.nameOf("attachment; filename=\"../../etc/x.caracole\""))
        assertEquals("x.caracole", Exports.nameOf("attachment; filename*=UTF-8''..%2F..%2Fx.caracole"))
        assertEquals("x.caracole", Exports.nameOf("attachment; filename=\"C:\\\\Users\\\\x.caracole\""))
        assertEquals(Exports.DEFAULT_NAME, Exports.nameOf("attachment; filename=\"..\""))
        assertEquals(Exports.DEFAULT_NAME, Exports.nameOf("attachment; filename=\"a/\""))
        assertEquals("a_b.caracole", Exports.nameOf("attachment; filename*=UTF-8''a%00b.caracole"), "no NUL in a name")
    }

    @Test
    fun `an export is read from the phone's server in this process, copied once under its name`() {
        val bytes = "PK\u0003\u0004caracole.json".toByteArray()
        val got = assertIs<Exports.Copied.File>(Exports.copy(files {
            Response(200, Body.Bytes(bytes), mutableListOf(
                "Content-Type" to "application/vnd.caracole+zip",
                "Content-Disposition" to "attachment; filename=\"Phone-10-11-26.caracole\"; " +
                    "filename*=UTF-8''Phone-10-11-26.caracole"))
        }, export, folder.root))
        val request = asked.single()
        assertEquals("GET", request.method)
        assertEquals("/api/sync/export?export=0123456789abcdef", request.target)
        assertEquals("caracole-launch=s3cr3t", request.headers["cookie"])
        assertEquals("127.0.0.1:8738", request.headers["host"])
        assertEquals("Phone-10-11-26.caracole", got.file.name)
        assertContentEquals(bytes, got.file.readBytes())
        assertTrue(got.file.canonicalPath.startsWith(folder.root.canonicalPath + "/"), "in the exports' folder")

        // The WebView's request and its download listener may each ask: the server sends an export once, and the
        // second ask is the copy made.
        val again = assertIs<Exports.Copied.File>(Exports.copy(files { error("asked twice") }, export, folder.root))
        assertEquals(got.file, again.file)
        // However each spells its address: the export is its id.
        val spelled = assertIs<Exports.Copied.File>(Exports.copy(files { error("asked twice") },
            "$origin/api/sync/export?x=1&export=0123456789abcdef#done", folder.root))
        assertEquals(got.file, spelled.file)
        assertEquals(1, asked.size)
    }

    @Test
    fun `an export the server no longer has is said, never shared`() {
        val gone = assertIs<Exports.Copied.Refused>(Exports.copy(files {
            Response(404, Body.Bytes("""{"error":"No such export."}""".toByteArray()),
                     mutableListOf("Content-Type" to "application/json"))
        }, "$origin/api/sync/export?export=fedcba9876543210", folder.root))
        assertEquals(404, gone.status)
        assertEquals("No such export.", gone.message)
        assertEquals(emptyList(), folder.root.listFiles()!!.filter { it.isFile }, "nothing left behind")
    }

    @Test
    fun `a name the server gives none of is the listener's, else caracole's`() {
        val bytes = byteArrayOf(1, 2, 3)
        val named = assertIs<Exports.Copied.File>(Exports.copy(files {
            Response(200, Body.Bytes(bytes), mutableListOf("Content-Type" to "application/vnd.caracole+zip"))
        }, "$origin/api/sync/export?export=1111111111111111", folder.root,
            disposition = "attachment; filename=\"From-the-listener.caracole\""))
        assertEquals("From-the-listener.caracole", named.file.name)
        val bare = assertIs<Exports.Copied.File>(Exports.copy(files {
            Response(200, Body.Bytes(bytes), mutableListOf("Content-Type" to "application/vnd.caracole+zip"))
        }, "$origin/api/sync/export?export=2222222222222222", folder.root))
        assertEquals(Exports.DEFAULT_NAME, bare.file.name)
        assertTrue(named.file.parentFile != bare.file.parentFile, "each copy in a folder of its own")
    }
}
