package io.github.danielhp95.caracole

import android.Manifest
import android.app.Notification
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.http.TransportError
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobSpec
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.net.URI

/**
 * The phone's alerts as notifications on the `alerts` channel, in the app (AndroidAlerts), on the device:
 *
 *     android/scripts/device-test.sh io.github.danielhp95.caracole.AlertsTest
 *
 * A lookup that a site blocks posts one notification, titled as the computer's ntfy alert ("caracole: LRCLIB
 * blocked"), and none for a second block of the same cooldown, nor for the next lookup (the site cools down, asked
 * nothing); a job that fails while a screen of the app's is open posts none, and one that fails with the app in the
 * background posts one, by its line.
 */
@RunWith(AndroidJUnit4::class)
class AlertsTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val manager get() = context.getSystemService(NotificationManager::class.java)

    @Before fun allowAndForget() {
        if (Build.VERSION.SDK_INT >= 33) {
            instrumentation.uiAutomation.grantRuntimePermission(context.packageName, Manifest.permission.POST_NOTIFICATIONS)
        }
        manager.cancelAll()
        context.getSharedPreferences(AndroidAlerts.PREFS, Context.MODE_PRIVATE).edit().clear().commit()
    }

    @After fun refuseAgain() {
        Caracole.sitesForTests = CaracoleTestRunner.REFUSING
        manager.cancelAll()
    }

    /** The alerts posted, each's title. */
    private fun posted(): List<String> = mine().map { it.notification.extras.getCharSequence(Notification.EXTRA_TITLE).toString() }

    /** The alerts' notifications. */
    private fun mine() = manager.activeNotifications
        .filter { it.notification.channelId == AndroidAlerts.CHANNEL }

    private fun lookUp(title: String): Job {
        val phone = Caracole.phone(context)
        val spec = JobSpec("Fetch Los Fabulosos Cadillacs - $title", "los fabulosos cadillacs/$title", "song", emptyList(),
                           display = "Los Fabulosos Cadillacs - $title", fetching = true,
                           commands = JobCommands.lookupSteps("Los Fabulosos Cadillacs", title))
        return runBlocking { withTimeout(120_000) { phone.queue.await(phone.queue.submit(spec).first.id) } }
    }

    @Test fun aBlockALookupMetPostsOneNotificationOnceACooldown() {
        // LRCLIB blocks (403); every other site has no network.
        Caracole.sitesForTests = Transport { request ->
            if (URI(request.url).host == "lrclib.net") HttpAnswer(403, listOf("Content-Type" to "text/plain"), "Forbidden".toByteArray())
            else throw TransportError("refused", "no network: ${request.url}")
        }
        val alerts = Caracole.phone(context).let { Caracole.alerts }
        assertTrue("the app's alerts: $alerts", alerts is AndroidAlerts)

        val first = lookUp("Matador")
        assertEquals(first.asJson().toString(), Job.DONE, first.state)
        waitUntil("the block's notification", 30_000) { posted() == listOf("caracole: LRCLIB blocked") }
        val until = Caracole.phone(context).parts.database.read { db -> Health.state(db, "lrclib").cooldownUntil }
        assertNotNull("LRCLIB cools down", until)

        // The same cooldown's block again (a second lookup that met it at once, say): none.
        alerts.blocked("lrclib", until, "403")
        // The next lookup asks LRCLIB nothing while it cools down: none.
        val second = lookUp("Vasos vacíos")
        assertEquals(Job.DONE, second.state)
        Thread.sleep(1_000)
        assertEquals(listOf("caracole: LRCLIB blocked"), posted())
        // A cooldown of its own (another block, once this one is over) is told again, in the same notification's place.
        val at = mine().single().postTime
        Thread.sleep(50)
        alerts.blocked("lrclib", until!!.plusSeconds(86_400), "403")
        waitUntil("the next cooldown's notification", 10_000) { mine().singleOrNull()?.let { it.postTime > at } == true }
    }

    @Test fun aJobThatFailsInTheBackgroundPostsOneAndNoneWhileTheAppIsOpen() {
        val phone = Caracole.phone(context)
        fun fail(display: String): Job = runBlocking {
            val spec = JobSpec("Fail", "fail:$display", "test", emptyList(), display = display) { _ ->
                throw IllegalStateException("the disk is full")
            }
            withTimeout(60_000) { phone.queue.await(phone.queue.submit(spec).first.id) }
        }
        val alerts = Caracole.alerts as AndroidAlerts

        ActivityScenario.launch(SettingsActivity::class.java).use {
            assertTrue(alerts.inForeground())
            assertEquals(Job.FAILED, fail("While open").state)
            Thread.sleep(1_000)
            assertEquals(emptyList<String>(), posted())
        }
        waitUntil("the app in the background", 10_000) { !alerts.inForeground() }
        assertEquals(Job.FAILED, fail("In the background").state)
        waitUntil("the failure's notification", 30_000) { posted() == listOf("In the background") }
        assertFalse(alerts.inForeground())
    }
}
