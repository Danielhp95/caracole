package io.github.danielhp95.caracole

import android.webkit.WebView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.evaluate
import io.github.danielhp95.caracole.Pages.url
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.server.http.Security
import io.github.danielhp95.caracole.viewer.pages.SheetPage
import io.github.danielhp95.caracole.viewer.render.WrittenPages
import io.github.danielhp95.caracole.viewer.testing.replays.RenderReplay
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * A page the phone wrote, opened in the WebView, on a device or an emulator, with no computer:
 *
 *     android/scripts/device-test.sh io.github.danielhp95.caracole.PagesServedTest
 *
 * The render corpus's `ug_sheet` song (vectors/viewer/render.jsonl's fixture: Soda Stereo - De Música Ligera, a sheet
 * kept from Ultimate Guitar) is put in the app's library, and the phone makes its pages as a lookup's pdf stage does
 * (PhoneRender). Its sheet.html is then served from the phone's own folder, the bytes the phone recorded, with their own
 * policy and the viewer's sandbox (SheetPage.viewerCsp, framed by none): in the WebView it runs in an opaque origin,
 * its script drawing the sheet's chords. Changed on disk it is refused (404, Not sent); once the song's unit moves (a
 * take's, or a change on the phone) it is never served (409, a link to the phone's sheet.txt), until the phone makes
 * the song's pages again.
 */
@RunWith(AndroidJUnit4::class)
class PagesServedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext

    @Test fun aWrittenPageIsServedInTheViewersSandboxWhileItIsTheRecordsAtItsUnitsDigest() {
        Corpus.open = { name -> runCatching { instrumentation.context.assets.open("conformance/$name") }.getOrNull() }
        Corpus.openFixture = { name -> runCatching { instrumentation.context.assets.open("fixtures/$name") }.getOrNull() }
        val phone = Caracole.phone(context)
        val database = phone.parts.database
        val library = phone.parts.store.libraryDir
        val record = Corpus.records(RenderReplay.VECTOR).first { it.extra["case"] == JsonPrimitive("ug_sheet") }
        val id = database.writeBlocking { db ->
            if (Songs.byId(db, SONG) == null) {
                Fixtures.loadRecords(db, record.args[0].jsonArray.map { it.jsonObject }, library)
            }
            phone.render.render(db, listOf(SONG), null)
            Songs.byId(db, SONG)!!.id
        }
        val file = File(library, "$FOLDER/sheet.html")
        val bytes = file.readBytes()
        assertTrue("the phone's page, current", database.read { WrittenPages.current(it, id, "sheet.html") })

        val (status, headers, body) = get(PATH)
        assertEquals(200, status)
        assertArrayEquals("the bytes the phone recorded", bytes, body)
        val policy = headers["Content-Security-Policy"].orEmpty()
        assertEquals("${SheetPage.viewerCsp(bytes)}; frame-ancestors 'none'", policy)
        assertTrue(policy, policy.startsWith("sandbox allow-scripts allow-downloads;"))

        ActivityScenario.launch(MainActivity::class.java).use { main ->
            waitUntil("the library page") {
                url(main).startsWith("${Pages.origin()}/") && evaluate(main, "document.readyState") == "complete"
            }
            val address = Pages.address("$FOLDER/sheet.html")
            // The address loaded again, and the new document waited for, never the one before it.
            fun open(what: String) {
                evaluate(main, "window.before = 1")
                main.onActivity { it.findViewById<WebView>(R.id.web).loadUrl(address) }
                waitUntil(what) {
                    url(main).substringBefore('#').endsWith("/sheet.html") &&
                        evaluate(main, "window.before === undefined && document.readyState === 'complete'") == true
                }
            }

            open("the phone's sheet")
            waitUntil("its script to draw the chords") {
                (evaluate(main, "document.querySelectorAll('.c').length") as Number).toInt() > 0
            }
            val shown = JSONObject(evaluate(main, """JSON.stringify({origin: String(window.origin),
                title: document.title, chords: Array.from(document.querySelectorAll('.c')).slice(0, 3)
                    .map(c => c.textContent).join(' ')})""") as String)
            assertEquals("the viewer's sandbox: an opaque origin", "null", shown.getString("origin"))
            assertTrue(shown.toString(), "De Música Ligera" in shown.getString("title"))
            assertTrue(shown.toString(), shown.getString("chords").isNotBlank())

            // Changed on disk (its length kept): never sent.
            file.writeBytes(bytes.copyOf().also { it[it.size - 2] = (it[it.size - 2] + 1).toByte() })
            assertEquals(404, get(PATH).first)
            open("the refusal")
            assertEquals("Not sent", evaluate(main, "document.querySelector('h1').textContent"))
            file.writeBytes(bytes)
            assertEquals(200, get(PATH).first)

            // The song's unit moves: the phone's page is of the song as it was, and the computer sent none of it.
            database.writeBlocking { db -> db.execute("UPDATE songs SET review = 1 WHERE id = ?", id) }
            val (moved, _, text) = get(PATH)
            assertEquals(409, moved)
            assertTrue(String(text), "This song changed since the phone made its page" in String(text))
            open("the page saying it changed")
            assertEquals("Changed since", evaluate(main, "document.querySelector('h1').textContent"))

            // Made again at the unit as it is now: served again.
            database.writeBlocking { db -> phone.render.render(db, listOf(id), null) }
            assertEquals(200, get(PATH).first)
            open("the phone's sheet again")
            assertEquals("null", evaluate(main, "String(window.origin)"))
        }
    }

    /** [path]'s status, headers and bytes, asked with the launch's cookie as the WebView asks. */
    private fun get(path: String): Triple<Int, Map<String, String>, ByteArray> {
        val connection = URL(Pages.origin() + path).openConnection() as HttpURLConnection
        try {
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Cookie", "${Security.SECRET_COOKIE}=${Caracole.secret}")
            connection.setRequestProperty("Sec-Fetch-Site", "same-origin")
            val status = connection.responseCode
            val body = (if (status >= 400) connection.errorStream else connection.inputStream)?.use { it.readBytes() }
                ?: ByteArray(0)
            val headers = connection.headerFields.filterKeys { it != null }.mapValues { it.value.joinToString(", ") }
            return Triple(status, headers, body)
        } finally {
            connection.disconnect()
        }
    }

    private companion object {
        /** The fixture's song, and where its pages are. */
        const val SONG = 1L
        const val FOLDER = "Soda Stereo/De Música Ligera"
        const val PATH = "/Soda%20Stereo/De%20M%C3%BAsica%20Ligera/sheet.html"
    }
}
