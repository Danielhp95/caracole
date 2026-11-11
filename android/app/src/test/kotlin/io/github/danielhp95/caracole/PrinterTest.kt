package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import org.junit.Test
import java.net.URI
import kotlin.test.assertEquals

/** Export PDF asks the phone's own server, in the app's process, for the version's name, as the WebView would. */
class PrinterTest {
    private val asked = mutableListOf<Request>()

    private fun ask(url: String, answer: (Request) -> Response): Printer.Named =
        Printer.ask({ request -> asked.add(request); answer(request) }, URI("http://127.0.0.1:8738"), "s3cr3t", url)

    private fun json(status: Int, text: String) =
        Response(status, Body.Bytes(text.toByteArray()), mutableListOf("Content-Type" to "application/json; charset=utf-8"))

    @Test fun `the link's path and query, with the launch's cookie and the server's host, JSON back`() {
        val named = ask("http://127.0.0.1:8738/export.pdf?sheet=Soda%20Stereo%2FDe%20M%C3%BAsica%20Ligera%2Fsheet.html" +
                        "&t=2&capo=0&mine=1#ignored") {
            json(200, """{"name":"Soda Stereo - De Música Ligera (A Major, capo 0).pdf","label":"A Major, capo 0"}""")
        }
        assertEquals(Printer.Named.Version("Soda Stereo - De Música Ligera (A Major, capo 0).pdf", "A Major, capo 0"), named)
        val request = asked.single()
        assertEquals("GET", request.method)
        assertEquals("/export.pdf?sheet=Soda%20Stereo%2FDe%20M%C3%BAsica%20Ligera%2Fsheet.html&t=2&capo=0&mine=1",
                     request.target)
        assertEquals("caracole-launch=s3cr3t", request.headers["cookie"])
        assertEquals("127.0.0.1:8738", request.headers["host"])
        assertEquals("same-origin", request.headers["sec-fetch-site"])
        assertEquals("application/json", request.headers["accept"])
    }

    @Test fun `a refusal comes back in the server's words`() {
        val named = ask("http://127.0.0.1:8738/export.pdf?sheet=x/y/sheet%20(auto).html") {
            json(409, """{"error":"This is the auto-chords sheet kept beside the song's own sheet."}""")
        }
        assertEquals(Printer.Named.Refused(409, "This is the auto-chords sheet kept beside the song's own sheet."), named)
        assertEquals(Printer.Named.Refused(500, null), ask("http://127.0.0.1:8738/export.pdf") {
            Response(500, Body.Bytes("<!doctype html>".toByteArray()), mutableListOf("Content-Type" to "text/html"))
        })
        assertEquals(Printer.Named.Refused(200, null), ask("http://127.0.0.1:8738/export.pdf") { json(200, "{}") })
    }

    @Test fun `the target is the link's path on its server`() {
        assertEquals("/export.pdf?t=2", Printer.target("http://127.0.0.1:8738/export.pdf?t=2"))
        assertEquals("/export.pdf", Printer.target("http://127.0.0.1:8738/export.pdf#t=2"))
        assertEquals("/", Printer.target("http://127.0.0.1:8738"))
    }
}
