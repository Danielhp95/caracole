package io.github.danielhp95.caracole

import android.Manifest
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.http.TransportError
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.server.http.App
import io.github.danielhp95.caracole.server.http.Security
import io.github.danielhp95.caracole.server.jobs.Job
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * A lookup on the phone with no network, in the app (CaracoleTestRunner: every site refused):
 *
 *     android/scripts/device-test.sh io.github.danielhp95.caracole.LookupOfflineTest
 *
 * Get it, posted as the library page's script posts it to the app's own server, queues `caracole get`, which adds its
 * song and asks each site, every one refusing ("refused", as a phone with no network answers): it ends done, its song
 * in the library, LRCLIB's stage failed, every site's failed or skipped (a lane's port still neutral), none a miss,
 * its line the one the library page shows (/jobs.json's, its song's facts read: status.py's "Not fetched yet", never
 * "Not found"). While it runs the app is kept in the foreground, its `jobs` notification naming the song; once it is
 * over the notification goes. The sites answer slowly here, so that the lookup is seen running.
 */
@RunWith(AndroidJUnit4::class)
class LookupOfflineTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext

    @After fun refuseAgain() {
        Caracole.sitesForTests = CaracoleTestRunner.REFUSING
    }

    @Test fun aLookupWithNoNetworkAddsItsSongItsStagesFailedTheJobsNotificationWhileItRan() {
        val release = CountDownLatch(1)
        val asked = AtomicInteger()
        Caracole.sitesForTests = Transport { request ->
            asked.incrementAndGet()
            release.await(60, TimeUnit.SECONDS)
            throw TransportError("refused", "no network: ${request.url}")
        }
        if (Build.VERSION.SDK_INT >= 33) {
            instrumentation.uiAutomation.grantRuntimePermission(context.packageName, Manifest.permission.POST_NOTIFICATIONS)
        }
        ActivityScenario.launch(MainActivity::class.java).use {
            val phone = Caracole.phone(context)
            val (status, body) = PhoneForms.post("/lookup", "artist" to ARTIST, "title" to TITLE)
            assertEquals(body, 202, status)
            val id = JSONObject(body).getInt("job")

            waitUntil("the jobs notification naming the lookup", 30_000) { PhoneForms.jobsNotice(context)?.contains(ARTIST) == true }
            assertTrue("the lookup runs: ${phone.queue.job(id)?.state}", phone.queue.job(id)?.state == Job.RUNNING)
            release.countDown()

            val job = runBlocking { withTimeout(120_000) { phone.queue.await(id) } }
            assertEquals(job.asJson().toString(), Job.DONE, job.state)
            val stages = job.stages.associate { it.name to it }
            assertEquals("done", stages.getValue("song").state)
            assertEquals("failed", stages.getValue("lyrics").state)
            assertTrue(stages.getValue("lyrics").detail, "refused" in stages.getValue("lyrics").detail)
            for (site in listOf("ug", "lacuerda", "gtptabs", "harptabs", "gametabs")) {
                assertTrue("$site: ${job.asJson()}", stages.getValue(site).state in setOf("failed", "skipped"))
            }
            val line = PhoneForms.line(id)
            assertEquals(line.toString(), "Not fetched yet", line.getString("text"))
            assertEquals(line.toString(), "waiting", line.getString("tone"))
            assertTrue("the sites were asked", asked.get() > 0)
            val song = phone.parts.database.read { Songs.byKey(it, Normalize.identityKey(ARTIST, TITLE)) }
            assertNotNull("the song added", song)
            assertFalse("a refused site is never a miss: ${song!!.lyricsStatus}", song.lyricsStatus == "missing")
            assertFalse("a refused site is never a miss: ${song.matchDecision}", song.matchDecision == "not_found")

            waitUntil("the notification gone once the queue is idle", 30_000) { PhoneForms.jobsNotice(context) == null }
        }
    }

    private companion object {
        const val ARTIST = "Los Fabulosos Cadillacs"
        const val TITLE = "Matador"
    }
}

/** The library page's forms, posted as its script posts them to the app's own server: the launch's cookie, the page's
 * own origin, the form token the page carries (its request form's). */
internal object PhoneForms {
    private val TOKEN = Regex("""name="csrf" value="([0-9a-f]+)"""")

    /** The form token the library page carries (its request form's). */
    private fun token(origin: String): String =
        TOKEN.find(get("$origin/").second)?.groupValues?.get(1) ?: throw AssertionError("no form token")

    /** [path]'s status and text for [fields], with the token; as JSON, unless [json] is false. */
    fun post(path: String, vararg fields: Pair<String, String>, json: Boolean = true): Pair<Int, String> {
        val origin = Pages.origin()
        val token = token(origin)
        val body = (listOf("csrf" to token) + fields).joinToString("&") { (name, value) ->
            URLEncoder.encode(name, "UTF-8") + "=" + URLEncoder.encode(value, "UTF-8")
        }.toByteArray()
        val connection = URL("$origin$path").openConnection() as HttpURLConnection
        try {
            connection.instanceFollowRedirects = false
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.setRequestProperty("Cookie", "${Security.SECRET_COOKIE}=${Caracole.secret}")
            connection.setRequestProperty("Origin", origin)
            connection.setRequestProperty("Sec-Fetch-Site", "same-origin")
            connection.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
            if (json) connection.setRequestProperty("Accept", "application/json")
            connection.outputStream.use { it.write(body) }
            return answer(connection)
        } finally {
            connection.disconnect()
        }
    }

    /** [path] read as the library page's script reads it: JSON, the form token in its header, the launch's cookie. */
    fun script(path: String): Pair<Int, String> {
        val origin = Pages.origin()
        val token = token(origin)
        val connection = URL("$origin$path").openConnection() as HttpURLConnection
        try {
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Cookie", "${Security.SECRET_COOKIE}=${Caracole.secret}")
            connection.setRequestProperty("Sec-Fetch-Site", "same-origin")
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty(App.TOKEN_HEADER, token)
            return answer(connection)
        } finally {
            connection.disconnect()
        }
    }

    /** The line the library page shows for request [id]: /jobs.json's view of it, its song's facts read
     * (jobs_routes.view), `{tone, text, link, details}`. */
    fun line(id: Int): JSONObject {
        val (status, body) = script("/jobs.json?jobs=$id")
        if (status != 200) throw AssertionError("/jobs.json?jobs=$id: HTTP $status $body")
        return JSONObject(body).getJSONArray("jobs").getJSONObject(0).getJSONObject("line")
    }

    /** [url]'s status and text, with the launch's cookie. */
    fun get(url: String): Pair<Int, String> {
        val connection = URL(url).openConnection() as HttpURLConnection
        try {
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Cookie", "${Security.SECRET_COOKIE}=${Caracole.secret}")
            connection.setRequestProperty("Sec-Fetch-Site", "same-origin")
            return answer(connection)
        } finally {
            connection.disconnect()
        }
    }

    private fun answer(connection: HttpURLConnection): Pair<Int, String> {
        val status = connection.responseCode
        val text = (if (status >= 400) connection.errorStream else connection.inputStream)?.use { it.readBytes() }
        return status to (text ?: ByteArray(0)).toString(Charsets.UTF_8)
    }

    /** What the app's notification on the `jobs` channel (the foreground service's, SyncService) says now; null for
     * none. */
    fun jobsNotice(context: Context): String? =
        context.getSystemService(NotificationManager::class.java).activeNotifications
            .firstOrNull { it.notification.channelId == Notifications.JOBS }
            ?.notification?.extras?.getCharSequence("android.text")?.toString()
}
