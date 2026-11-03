package io.github.danielhp95.caracole

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.webkit.WebView
import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.intent.Intents
import androidx.test.espresso.intent.Intents.intending
import androidx.test.espresso.intent.matcher.IntentMatchers.hasAction
import androidx.test.espresso.intent.matcher.IntentMatchers.hasData
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.evaluate
import io.github.danielhp95.caracole.Pages.url
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.server.http.Security
import org.hamcrest.Matchers.allOf
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.ServerSocket
import java.net.SocketException
import java.net.URL
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

/**
 * The app's own caracole, on a device or an emulator, with no computer:
 *
 *     adb shell am instrument -w -e class io.github.danielhp95.caracole.LocalServerTest \
 *         io.github.danielhp95.caracole.test/androidx.test.runner.AndroidJUnitRunner
 *
 * Its server listens on 127.0.0.1 and answers its library page at `/` to a request with the launch's cookie, and
 * refuses one without it (403, "Not this app's caracole."), so no other app on the phone can use it. The WebView
 * carries that cookie and loads the server's exact origin alone: another server on another loopback port (as a
 * Termux caracole serve on 8737 would be) never hears from it, neither when the app is told to load it, nor when the
 * page follows a link to it, which opens in the browser instead, nor when a page there asks it for a resource. And
 * the database a first start makes is named only once whole, seeded, with no WAL left behind.
 */
@RunWith(AndroidJUnit4::class)
class LocalServerTest {
    /** Another server on 127.0.0.1, on a port of its own: it counts the connections it is asked for. */
    private val other = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"))
    private val heard = AtomicInteger()

    @Before
    fun listen() {
        thread(isDaemon = true) {
            while (true) {
                val socket = try {
                    other.accept()
                } catch (e: SocketException) {
                    break
                }
                heard.incrementAndGet()
                socket.use {
                    it.getOutputStream().write("HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nno".toByteArray())
                }
            }
        }
    }

    @After
    fun stop() = other.close()

    @Test
    fun theAppsServerAnswersItsPageWithTheLaunchsCookieAndRefusesAnyRequestWithout() {
        val origin = Pages.origin()
        assertTrue(origin, origin.startsWith("http://127.0.0.1:"))

        val page = get("$origin/", cookie = "${Security.SECRET_COOKIE}=${Caracole.secret}")
        assertEquals(200, page.first)
        assertTrue("the library page: ${page.second.take(200)}", page.second.startsWith("<!doctype html>"))

        for (cookie in listOf(null, "${Security.SECRET_COOKIE}=${"0".repeat(64)}", "other=${Caracole.secret}")) {
            val refused = get("$origin/", cookie)
            assertEquals("cookie $cookie", 403, refused.first)
            assertEquals("Not this app's caracole.\n", refused.second)
        }
        assertEquals("a file of the library is the server's too", 403, get("$origin/index.html", null).first)
    }

    @Test
    fun theWebViewNeverLoadsAnotherLoopbackPort() {
        val origin = Pages.origin()
        val elsewhere = "http://127.0.0.1:${other.localPort}/"
        ActivityScenario.launch(MainActivity::class.java).use { main ->
            waitUntil("the library page") {
                url(main).startsWith("$origin/") && evaluate(main, "document.readyState") == "complete"
            }
            val shown = JSONObject(evaluate(main, "JSON.stringify({origin: window.origin, title: document.title})") as String)
            assertEquals(origin, shown.getString("origin"))

            Intents.init()
            try {
                intending(allOf(hasAction(Intent.ACTION_VIEW), hasData(elsewhere)))
                    .respondWith(Instrumentation.ActivityResult(Activity.RESULT_OK, null))

                // The page follows a link there: the browser's, never the WebView's.
                evaluate(main, "location.href = ${JSONObject.quote(elsewhere)}")
                waitUntil("the link handed to the browser") {
                    Intents.getIntents().any { it.action == Intent.ACTION_VIEW && it.dataString == elsewhere }
                }
                assertTrue(url(main).startsWith("$origin/"))

                // The app itself told to load it: answered in the app, a 404, and no socket is opened.
                main.onActivity { it.findViewById<WebView>(R.id.web).loadUrl(elsewhere + "page") }
                waitUntil("the WebView to give up on it") {
                    url(main).startsWith(elsewhere) && evaluate(main, "document.readyState") == "complete"
                }
                // From that page, the app's own 404 with no policy of its own (the library page's would refuse these
                // before the WebView ever asked the app), a fetch and an image of that origin: each answered in the
                // app (a 404, or refused), and neither opens a socket.
                evaluate(main, """(() => {
                    window.probes = {};
                    const done = (name, how) => { window.probes[name] = how; };
                    fetch(${JSONObject.quote(elsewhere + "fetched")}).then((r) => done("fetch", "status " + r.status),
                                                                          () => done("fetch", "refused"));
                    const image = new Image();
                    image.onload = () => done("image", "loaded");
                    image.onerror = () => done("image", "refused");
                    image.src = ${JSONObject.quote(elsewhere + "image.png")};
                    return 1;
                })()""")
                waitUntil("the fetch and the image to settle") {
                    evaluate(main, "Object.keys(window.probes || {}).length") == 2
                }
                val probes = JSONObject(evaluate(main, "JSON.stringify(window.probes)") as String)
                assertTrue("the app's own answer: $probes", probes.getString("fetch") in setOf("status 404", "refused"))
                assertEquals("refused", probes.getString("image"))
            } finally {
                Intents.release()
            }
        }
        assertEquals("connections the other server heard", 0, heard.get())
    }

    @Test
    fun aFirstStartMakesTheDatabaseWholeSeededWithNoWalLeft() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val dir = File(context.cacheDir, "first-start-${System.nanoTime()}").apply { mkdirs() }
        try {
            val file = File(dir, "caracole.sqlite")
            Caracole.openDatabase(file).use { database ->
                assertEquals("the kv a fresh computer's database holds", "2",
                             database.read { it.kvGet("lacuerda:index:keys") })
                assertEquals("the phone's own tables", "1", database.read { it.kvGet("phone:schema") })
            }
            assertTrue("named once made whole", file.isFile)
            assertFalse(File(dir, "caracole.sqlite.new").exists())
            val wal = File(dir, "caracole.sqlite-wal")
            assertTrue("no WAL left with what the file lacks", !wal.exists() || wal.length() == 0L)
            Caracole.openDatabase(file).use { database ->
                assertEquals("opened again as it is", "2", database.read { it.kvGet("lacuerda:index:keys") })
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    /** [url]'s status and text, asked as another app on the phone would, with [cookie] or none. */
    private fun get(url: String, cookie: String?): Pair<Int, String> {
        val connection = URL(url).openConnection() as HttpURLConnection
        try {
            connection.instanceFollowRedirects = false
            if (cookie != null) connection.setRequestProperty("Cookie", cookie)
            val status = connection.responseCode
            val body = (if (status >= 400) connection.errorStream else connection.inputStream)?.use { it.readBytes() } ?: ByteArray(0)
            return status to body.toString(Charsets.UTF_8)
        } finally {
            connection.disconnect()
        }
    }
}
