package io.github.danielhp95.caracole

import android.Manifest
import android.view.KeyEvent
import android.webkit.WebView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.evaluate
import io.github.danielhp95.caracole.Pages.tapElement
import io.github.danielhp95.caracole.Pages.url
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.viewer.testing.replays.RenderReplay
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Android's Back closes a sheet's layer in the app, on a device or an emulator:
 *
 *     android/scripts/device-test.sh io.github.danielhp95.caracole.SheetLayersBackTest
 *
 * The render corpus's `ug_sheet` song's sheet.html is opened in the WebView; the settings panel opened from `#more` is
 * one layer (one history entry), so Back closes it and the sheet stays, and a second Back leaves for the library page.
 */
@RunWith(AndroidJUnit4::class)
class SheetLayersBackTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext

    @Test fun aBackClosesTheSettingsAndTheSheetStays() {
        Corpus.open = { name -> runCatching { instrumentation.context.assets.open("conformance/$name") }.getOrNull() }
        Corpus.openFixture = { name -> runCatching { instrumentation.context.assets.open("fixtures/$name") }.getOrNull() }
        val phone = Caracole.phone(context)
        val record = Corpus.records(RenderReplay.VECTOR).first { it.extra["case"] == JsonPrimitive("ug_sheet") }
        phone.parts.database.writeBlocking { db ->
            if (Songs.byId(db, SONG) == null) {
                Fixtures.loadRecords(db, record.args[0].jsonArray.map { it.jsonObject }, phone.parts.store.libraryDir)
            }
            phone.render.render(db, listOf(SONG), null)
        }

        // The notification permission asked at launch would take the window focus (and every touch) from the page.
        instrumentation.uiAutomation.grantRuntimePermission(context.packageName, Manifest.permission.POST_NOTIFICATIONS)

        // A computer's address (nothing answers at port 9), so that the first launch opens the library screen, never
        // Settings in front of it.
        if (Settings(context).server.isBlank()) Settings(context).server = "http://10.0.2.2:9"

        ActivityScenario.launch(MainActivity::class.java).use { main ->
            waitUntil("the library page") {
                url(main).startsWith("${Pages.origin()}/") && evaluate(main, "document.readyState") == "complete"
            }
            evaluate(main, "window.before = 1")
            main.onActivity { it.findViewById<WebView>(R.id.web).loadUrl(Pages.address("$FOLDER/sheet.html")) }
            waitUntil("the phone's sheet") {
                url(main).substringBefore('#').endsWith("/sheet.html") &&
                    evaluate(main, "window.before === undefined && document.readyState === 'complete'") == true
            }
            waitUntil("its script to draw the chords") {
                (evaluate(main, "document.querySelectorAll('.c').length") as Number).toInt() > 0
            }
            waitUntil("the window's focus (no Settings in front)") {
                var focus = false
                main.onActivity { focus = it.hasWindowFocus() }
                focus
            }
            evaluate(main, "window.marker = 1")

            tapElement(main, "#more")
            waitUntil("the settings open") { evaluate(main, "!document.getElementById('panel').hidden") == true }

            back()
            waitUntil("the settings closed, on the sheet still") {
                url(main).substringBefore('#').endsWith("/sheet.html") &&
                    evaluate(main, "document.getElementById('panel').hidden") == true
            }
            assertTrue(url(main), url(main).substringBefore('#').endsWith("/sheet.html"))
            assertEquals("the sheet stayed: the same document", 1, (evaluate(main, "window.marker") as Number).toInt())

            back()
            waitUntil("the library page") {
                val at = url(main).substringBefore('#')
                !at.endsWith("/sheet.html") && at.startsWith("${Pages.origin()}/")
            }
        }
    }

    private fun back() {
        instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)
        instrumentation.waitForIdleSync()
    }

    private companion object {
        const val SONG = 1L
        const val FOLDER = "Soda Stereo/De Música Ligera"
    }
}
