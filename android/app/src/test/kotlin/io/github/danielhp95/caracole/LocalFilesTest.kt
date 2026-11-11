package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.net.URI
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull

/** A file handed to another app is read from the phone's own server, in the app's process, as the WebView asks. */
class LocalFilesTest {
    @get:Rule val folder = TemporaryFolder()

    private val asked = mutableListOf<Request>()
    private fun files(answer: (Request) -> Response) =
        LocalFiles({ request -> asked.add(request); answer(request) }, URI("http://127.0.0.1:8738"), "s3cr3t")

    @Test
    fun `the request carries the launch's cookie and the server's host, for the file's path percent-encoded`() {
        files { Response(200, Body.Bytes("%PDF".toByteArray()), mutableListOf("Content-Type" to "application/pdf")) }
            .get("Ñandú/Canción #1?/sheet (auto).pdf")
        val request = asked.single()
        assertEquals("GET", request.method)
        assertEquals("/%C3%91and%C3%BA/Canci%C3%B3n%20%231%3F/sheet%20%28auto%29.pdf", request.target)
        assertEquals("caracole-launch=s3cr3t", request.headers["cookie"])
        assertEquals("127.0.0.1:8738", request.headers["host"])
        assertEquals("same-origin", request.headers["sec-fetch-site"])
        // A refusal comes back as its words, not as a page to show.
        assertEquals("application/json", request.headers["accept"])
        assertEquals(0, request.body.size)
    }

    @Test
    fun `a file comes back with its type, without its parameters, its length and its bytes`() {
        val file = folder.newFile("sheet.cho").apply { writeText("{title: Tu calorro}") }
        val got = assertIs<Fetched.File>(files {
            Response(200, Body.FromFile(file, file.length()), mutableListOf("Content-Type" to "text/plain; charset=utf-8"))
        }.get("Estopa/Tu calorro/sheet.cho"))
        assertEquals("text/plain", got.type)
        assertEquals(file.length(), got.length)
        assertContentEquals(file.readBytes(), got.open().use { it.readBytes() })

        val bytes = assertIs<Fetched.File>(files {
            Response(200, Body.Bytes(byteArrayOf(1, 2, 3)), mutableListOf("Content-Type" to "Application/Octet-Stream"))
        }.get("Estopa/Tu calorro/guitar-1.gp5"))
        assertEquals("application/octet-stream", bytes.type)
        assertEquals(3L, bytes.length)
        assertContentEquals(byteArrayOf(1, 2, 3), bytes.open().use { it.readBytes() })

        val untyped = assertIs<Fetched.File>(files { Response(200, Body.Empty) }.get("x/y/z.bin"))
        assertEquals("application/octet-stream", untyped.type)
        assertEquals(0L, untyped.length)
    }

    @Test
    fun `anything but a file is a refusal, with the server's words when it gave some`() {
        val missing = assertIs<Fetched.Refused>(files {
            Response(404, Body.Bytes("""{"error":"No such page or file in the book."}""".toByteArray()),
                mutableListOf("Content-Type" to "application/json; charset=utf-8"))
        }.get("Estopa/Tu calorro/sheet.pdf"))
        assertEquals(404, missing.status)
        assertEquals("No such page or file in the book.", missing.message)

        val removed = assertIs<Fetched.Refused>(files {
            Response(410, Body.Bytes("<html>…</html>".toByteArray()), mutableListOf("Content-Type" to "text/html"),
                JsonObject(mapOf("error" to JsonPrimitive("Removed from the phone's book."))))
        }.get("Estopa/Tu calorro/sheet.pdf"))
        assertEquals(410, removed.status)
        assertEquals("Removed from the phone's book.", removed.message, "the data a page's script would get")

        val bare = assertIs<Fetched.Refused>(files {
            Response(403, Body.Bytes("Not this app's scribe.\n".toByteArray()), mutableListOf("Content-Type" to "text/plain"))
        }.get("a/b.pdf"))
        assertEquals(403, bare.status)
        assertNull(bare.message)

        // A page where a file was expected is no file for another app.
        val page = assertIs<Fetched.Refused>(files {
            Response(200, Body.Bytes("<html></html>".toByteArray()), mutableListOf("Content-Type" to "text/html; charset=utf-8"))
        }.get("a/sheet.pdf"))
        assertEquals(200, page.status)
    }
}
