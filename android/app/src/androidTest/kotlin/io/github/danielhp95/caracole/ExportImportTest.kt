package io.github.danielhp95.caracole

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.net.Uri
import android.util.Log
import androidx.core.content.FileProvider
import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.action.ViewActions.scrollTo
import androidx.test.espresso.intent.Intents
import androidx.test.espresso.intent.Intents.intending
import androidx.test.espresso.intent.matcher.IntentMatchers.hasAction
import androidx.test.espresso.matcher.RootMatchers.isPlatformPopup
import androidx.test.espresso.matcher.ViewMatchers.withId
import androidx.test.espresso.matcher.ViewMatchers.withText
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.waitUntil
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.FixMethodOrder
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.MethodSorters
import java.io.File
import java.util.zip.ZipInputStream

/**
 * Settings' Export and Import a file on the phone, through Android's share sheet and its file picker (Espresso-Intents
 * answers both: nothing outside the app opens), against a real caracole serve for the library exported, as
 * android/scripts/device-test.sh runs it:
 *
 *     android/scripts/device-test.sh --computer "$(mktemp -d)" io.github.danielhp95.caracole.ExportImportTest
 *
 * Export: the phone agreed with the computer first (Sync on Wi-Fi's sync), Settings' Export opens the library page's
 * sheet at its export, whose Export makes the file and downloads it, which the app reads in its own process and hands
 * to the share sheet (ACTION_CHOOSER of an ACTION_SEND of application/zip): the URI shared is the file, a zip whose
 * first member is caracole.json. Import a file: Settings' Import a file opens the sheet at its import, its Choose a
 * file (tapped, as a file input opens its chooser only on a user's gesture) opens the picker (ACTION_OPEN_DOCUMENT,
 * answered with the corpus's `full.caracole` copied to the app's cache), and the sheet sends the file, compares, and
 * syncs with it, "Synced with: Desk". The export runs first, so the computer is given nothing of the file's. Without
 * `server` it is skipped.
 */
@RunWith(AndroidJUnit4::class)
@FixMethodOrder(MethodSorters.NAME_ASCENDING)
class ExportImportTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val server: String? = InstrumentationRegistry.getArguments().getString("server")
    private val found = JSONObject()

    @Before
    fun setUp() {
        assumeTrue("needs -e server http://10.0.2.2:<port>", server != null)
        Settings(context).server = server!!
        SyncDevice.mayNotify()
        Intents.init()
    }

    @After
    fun tearDown() {
        if (server != null) Intents.release()
    }

    @Test
    fun exportFromSettingsOpensTheSheetAndItsFileGoesToTheShareSheet() {
        val agreed = runBlocking { Syncs.run(context, probe = false) }!!
        record("agreed", agreed.text)
        assertTrue(agreed.text, agreed.ok)
        intending(hasAction(Intent.ACTION_CHOOSER)).respondWith(Instrumentation.ActivityResult(Activity.RESULT_OK, null))

        ActivityScenario.launch<MainActivity>(library()).use { main ->
            val sheet = SyncSheet { script -> Pages.evaluate(main, script) }
            sheet.libraryLoaded()
            settingsRow(R.id.export)

            // The sheet at its export: the parts with their sizes, Site indexes unticked.
            waitUntil("the export's sizes") {
                val s = sheet.state()
                s.getBoolean("open") && s.getString("flow") == "export" && s.getString("go") == "Export" &&
                    !s.getBoolean("goDisabled")
            }
            val asked = sheet.state()
            record("export", asked)
            assertEquals("Export this library", asked.getString("title"))
            val parts = asked.getJSONArray("parts").toString()
            assertTrue(parts, "indexes-" in parts && "library+" in parts && "songbooks+" in parts)

            // Export: the file made, downloaded, and handed to the share sheet.
            sheet.click("sync-go")
            var chooser: Intent? = null
            waitUntil("the share sheet", 2 * 60_000) {
                chooser = Intents.getIntents().lastOrNull { it.action == Intent.ACTION_CHOOSER }
                chooser != null
            }
            val send = (@Suppress("DEPRECATION") chooser!!.getParcelableExtra<Intent>(Intent.EXTRA_INTENT))!!
            @Suppress("DEPRECATION") val uri = send.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)!!
            val name = send.getStringExtra(Intent.EXTRA_TITLE).orEmpty()
            record("shared", JSONObject().put("action", send.action).put("type", send.type).put("uri", uri.toString())
                .put("name", name).put("flags", send.flags))
            assertEquals(Intent.ACTION_SEND, send.action)
            assertEquals("application/zip", send.type)
            assertTrue(name, name.endsWith(".caracole"))
            assertTrue("the URI readable by the app it goes to", send.flags and Intent.FLAG_GRANT_READ_URI_PERMISSION != 0)
            assertEquals("content", uri.scheme)

            // The bytes shared are the export: a zip whose first member is its manifest, of the songs the phone took.
            val (first, manifest) = context.contentResolver.openInputStream(uri)!!.use { input ->
                ZipInputStream(input).use { zip ->
                    val entry = zip.nextEntry!!
                    entry.name to JSONObject(zip.readBytes().toString(Charsets.UTF_8))
                }
            }
            record("manifest", manifest)
            assertEquals("caracole.json", first)
            assertTrue(manifest.toString(), manifest.getInt("songs") > 0)
            assertEquals(manifest.toString(), listOf("library", "songbooks"),
                         manifest.getJSONArray("parts").let { p -> (0 until p.length()).map { p.getString(it) } })

            // The sheet says the file was made, and the page stays where it is.
            waitUntil("the sheet's word of the file") { sheet.state().getString("status").startsWith("Made ") }
            val made = sheet.state()
            record("made", made)
            assertTrue(made.toString(), name in made.getString("status"))
            assertEquals("Done", made.getString("go"))
            sheet.click("sync-go")
        }
        Log.i(TAG, "RESULT $found")
    }

    @Test
    fun importAFilePicksThroughAndroidsPickerAndSyncsWithTheFile() {
        // The file another caracole exported: the corpus's full.caracole (a library named Desk), copied to the cache.
        val copy = File(context.cacheDir, "${Exports.FOLDER}/picked/full.caracole")
        copy.parentFile!!.mkdirs()
        instrumentation.context.assets.open("conformance/sync/files/full.caracole").use { input ->
            copy.outputStream().use { input.copyTo(it) }
        }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", copy)
        intending(hasAction(Intent.ACTION_OPEN_DOCUMENT)).respondWith(Instrumentation.ActivityResult(
            Activity.RESULT_OK, Intent().setData(uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)))

        ActivityScenario.launch<MainActivity>(library()).use { main ->
            val js = { script: String -> Pages.evaluate(main, script) }
            val sheet = SyncSheet(js)
            sheet.libraryLoaded()
            settingsRow(R.id.import_file)

            waitUntil("the sheet at its import") {
                val s = sheet.state()
                s.getBoolean("open") && s.getString("flow") == "import" && s.getString("go") == "Choose a file" &&
                    !s.getBoolean("goDisabled")
            }
            record("import", sheet.state())

            // Choose a file, tapped: Android's picker, answered with the copy.
            var activity: MainActivity? = null
            main.onActivity { activity = it }
            SyncDevice.tap(activity!!, js, "sync-go")
            waitUntil("the picker asked for") { Intents.getIntents().any { it.action == Intent.ACTION_OPEN_DOCUMENT } }
            val picker = Intents.getIntents().last { it.action == Intent.ACTION_OPEN_DOCUMENT }
            record("picker", JSONObject().put("type", picker.type).put("categories", picker.categories?.toString()))
            assertEquals("*/*", picker.type)
            assertTrue(picker.categories.orEmpty().contains(Intent.CATEGORY_OPENABLE))

            // The file sent and compared: a sync with it, the indexes not in it.
            val compared = sheet.compared()
            record("compared", compared)
            assertEquals("Sync with a file from Desk", compared.getString("title"))
            assertTrue(compared.toString(), "full.caracole" in compared.getString("sub"))
            val parts = compared.getJSONArray("parts").toString()
            assertTrue(parts, "indexes- off: Not in this file" in parts)
            assertTrue(compared.toString(), compared.getInt("take") > 0)

            // Sync: each conflict, if any (a songbook of the same name as the computer's, say), the file's.
            sheet.click("sync-go")
            waitUntil("the sync under way, or a card") { sheet.state().getString("view") in setOf("conflict", "going", "done") }
            if (sheet.state().getString("view") == "conflict") {
                val card = sheet.card()
                record("card", card)
                assertEquals("File", card.getString("there"))
                if (card.getBoolean("same")) js("document.getElementById('sync-same').checked = true")
                sheet.click("sync-keep-there")
            }
            val done = sheet.done()
            record("done", done)
            assertEquals("Synced with: Desk", done.getString("title"))
            assertTrue("a file takes nothing back: $done", done.getBoolean("fileNote"))
            val taken = done.getJSONArray("sections").objects().first { it.getString("kind") == "taken" }
            assertTrue(taken.toString(), taken.getJSONArray("rows").toString().contains("Radiohead"))
            sheet.click("sync-go")
        }
        Log.i(TAG, "RESULT $found")
    }

    /** The library screen as Settings starts it (MainActivity is single-task: its intent, Settings' then, is the one
     * the screen holds): an ActivityScenario follows the activity whose intent is the one it started with, so it is
     * started with this one, never the launcher's. */
    private fun library(): Intent = Intent(context, MainActivity::class.java)

    /** Settings, from the bar's ⋮, and its row [id] pressed (Export, Import a file): the library screen comes back with
     * the sheet. */
    private fun settingsRow(id: Int) {
        onView(withId(R.id.more)).perform(click())
        onView(withText(R.string.settings)).inRoot(isPlatformPopup()).perform(click())
        onView(withId(id)).perform(scrollTo(), click())
    }

    private fun record(what: String, value: Any) {
        found.put(what, value)
        Log.i(TAG, "$what: $value")
    }

    private companion object {
        const val TAG = "CaracoleExportImport"
    }
}
