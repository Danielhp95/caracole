package io.github.danielhp95.caracole

import android.app.Activity
import android.app.AlertDialog
import android.app.Instrumentation
import android.content.Intent
import android.net.Uri
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.intent.Intents
import androidx.test.espresso.intent.Intents.intended
import androidx.test.espresso.intent.Intents.intending
import androidx.test.espresso.intent.matcher.IntentMatchers.hasAction
import androidx.test.espresso.intent.matcher.IntentMatchers.hasExtra
import androidx.test.espresso.intent.matcher.IntentMatchers.hasType
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.Pages.waitUntil
import io.github.danielhp95.caracole.core.backup.Backups
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.lookups.BackupRunner
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonObject
import org.hamcrest.Matchers.allOf
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.time.Instant
import java.util.zip.ZipInputStream

/**
 * The phone's backups in the app (Settings' Backups row, BackupsActivity), on the device:
 *
 *     android/scripts/device-test.sh io.github.danielhp95.caracole.BackupsTest
 *
 * Back up now makes a backup by hand, a queued job, listed once it is over; its Export asks the document picker
 * (ACTION_CREATE_DOCUMENT, answered here as the picker would) and writes one zip of the copy and the kept files there;
 * its Restore, asked first, puts the library back and keeps the cooldown the phone met since.
 */
@RunWith(AndroidJUnit4::class)
class BackupsTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext

    /** A song of the phone's with a kept file, its bytes. */
    private fun seed(title: String, bytes: ByteArray) {
        val phone = Caracole.phone(context)
        phone.parts.database.writeBlocking { db ->
            val now = "2026-11-10T08:00:00Z"
            val song = phone.parts.store.add(db, "Los Fabulosos Cadillacs", title, now = now)
            val version = Versions.upsert(db, "inbox", title, song.id, "sheet", "tabs", 0.0, 0, 1, null, "",
                                          JsonObject(emptyMap()), now)
            Kept.keepFile(db, phone.parts.store, song, version, "tab.txt", bytes, 0, now)
        }
    }

    private fun <T> onActivity(scenario: ActivityScenario<BackupsActivity>, block: (BackupsActivity) -> T): T {
        var out: T? = null
        scenario.onActivity { out = block(it) }
        @Suppress("UNCHECKED_CAST")
        return out as T
    }

    private fun status(scenario: ActivityScenario<BackupsActivity>): String =
        onActivity(scenario) { it.findViewById<TextView>(R.id.backups_status).text.toString() }

    private fun listed(scenario: ActivityScenario<BackupsActivity>): List<String> = onActivity(scenario) { activity ->
        val list = activity.findViewById<LinearLayout>(R.id.backups_list)
        (0 until list.childCount).map { list.getChildAt(it).tag as String }
    }

    @Test fun aBackupByHandIsListedAndExportedThroughTheDocumentPicker() {
        val bytes = "e|-0-3-5-|".toByteArray()
        seed("Matador", bytes)
        val out = File(context.cacheDir, "exported.zip").apply { delete() }
        Intents.init()
        try {
            intending(hasAction(Intent.ACTION_CREATE_DOCUMENT))
                .respondWith(Instrumentation.ActivityResult(Activity.RESULT_OK, Intent().setData(Uri.fromFile(out))))
            val before = Backups.list(Caracole.phone(context).parts.stateDir).map { it.file.name }
            ActivityScenario.launch(BackupsActivity::class.java).use { scenario ->
                waitUntil("the backups listed", 30_000) { listed(scenario) == before }
                onActivity(scenario) { it.findViewById<Button>(R.id.backup_now).performClick() }
                waitUntil("the backup made and listed", 60_000) { listed(scenario).size == before.size + 1 }
                assertEquals("Backed up (by-hand)", status(scenario))
                val name = listed(scenario).first()
                assertTrue(name, name.startsWith("by-hand-") && name.endsWith(".sqlite") && name !in before)
                val backup = Backups.list(Caracole.phone(context).parts.stateDir).first()
                assertEquals(name, backup.file.name)

                onActivity(scenario) { it.window.decorView.findViewWithTag<Button>(BackupsActivity.EXPORT_TAG + name).performClick() }
                intended(allOf(hasAction(Intent.ACTION_CREATE_DOCUMENT), hasType(BackupsActivity.ZIP),
                               hasExtra(Intent.EXTRA_TITLE, Backups.exportName(backup))))
                waitUntil("the export written", 60_000) { status(scenario) == context.getString(R.string.backup_exported) }
                val entries = LinkedHashMap<String, ByteArray>()
                ZipInputStream(out.inputStream()).use { zip ->
                    while (true) {
                        val entry = zip.nextEntry ?: break
                        entries[entry.name] = zip.readBytes()
                    }
                }
                assertEquals(listOf(name, "blobs/${Canonical.sha256Hex(bytes)}"), entries.keys.toList())
                assertTrue(entries.getValue(name).contentEquals(backup.file.readBytes()))
                assertTrue(entries.getValue("blobs/${Canonical.sha256Hex(bytes)}").contentEquals(bytes))
            }
        } finally {
            Intents.release()
            out.delete()
        }
    }

    @Test fun aRestoreFromTheListPutsTheLibraryBackAndKeepsTheCooldownMetSince() {
        val bytes = "e|-7-5-3-|".toByteArray()
        seed("Matador", bytes)
        val phone = Caracole.phone(context)
        val made = runBlocking {
            withTimeout(60_000) { phone.queue.await(phone.queue.submit(BackupRunner(phone.parts).backup(Backups.BY_HAND)).first.id) }
        }
        assertEquals(made.asJson().toString(), Job.DONE, made.state)
        val backup = Backups.list(phone.parts.stateDir).first()
        // Since: a song added, its file kept, the tab's bytes kept again otherwise, and a site that blocked a lookup.
        seed("Vasos vacíos", "e|-0-|".toByteArray())
        val matador = phone.parts.database.read { db ->
            Songs.byKey(db, Normalize.identityKey("Los Fabulosos Cadillacs", "Matador"))!!
        }
        val tab = phone.parts.database.read { db -> Kept.keptFiles(db, matador.id).single() }
        val now = Instant.now()
        phone.parts.database.writeBlocking { db ->
            Kept.keepFile(db, phone.parts.store, matador, tab.versionId, "tab.txt", "e|-changed-|".toByteArray(), 0,
                          "2026-11-10T09:00:00Z")
            Health.recordBlock(db, "ug", now, "403")
        }

        ActivityScenario.launch(BackupsActivity::class.java).use { scenario ->
            waitUntil("the backup listed", 30_000) { backup.file.name in listed(scenario) }
            onActivity(scenario) {
                it.window.decorView.findViewWithTag<Button>(BackupsActivity.RESTORE_TAG + backup.file.name).performClick()
            }
            waitUntil("the restore asked first", 10_000) { onActivity(scenario) { it.asked?.isShowing == true } }
            onActivity(scenario) { it.asked!!.getButton(AlertDialog.BUTTON_POSITIVE).performClick() }
            val restored = "Restored the library of ${BackupRunner.date(backup.at)}"
            waitUntil("the library restored", 60_000) { status(scenario) == restored }
        }
        phone.parts.database.read { db ->
            assertNull("the song added since is gone", Songs.list(db).firstOrNull { it.title == "Vasos vacíos" })
            assertNotNull(Songs.byId(db, matador.id))
            assertTrue("the cooldown met since is kept", Health.isCooling(db, "ug", now))
        }
        assertTrue("the tab as backed up", Kept.holds(File(phone.parts.store.libraryDir, tab.path).toPath(), tab.sha256))
        assertEquals(Canonical.sha256Hex(bytes), tab.sha256)
    }
}
