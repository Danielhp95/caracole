package io.github.danielhp95.caracole

import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.core.http.RoutedTransport
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.viewer.autochords.Heard
import io.github.danielhp95.caracole.viewer.autochords.SheetHalf
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.net.URLEncoder
import java.time.Instant

/**
 * A song's lyrics looked up under a name typed, on the emulator against the fake sites server:
 *
 *     android/scripts/device-test.sh --sites lookups io.github.danielhp95.caracole.LyricsSearchTest
 *
 * A song the phone holds with an auto sheet of chords alone, keeping what was heard (as a sheet from an audio file
 * leaves one), and no lyrics; the card's panel's requests, as library.js sends them: POST /lyrics/search under the
 * scenario's song LRCLIB has (Thomas Moore - The Minstrel Boy), GET /api/lyrics/search lists its record, POST
 * /lyrics/pick takes it: the song's lyrics found, the auto sheet laid out again over them with no model, and every
 * request one the scenario answers. Without `-e sites` the test is skipped.
 */
@RunWith(AndroidJUnit4::class)
class LyricsSearchTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val sites: String? = InstrumentationRegistry.getArguments().getString("sites")

    @Before fun theFakeSites() {
        Assume.assumeTrue("no fake sites server: -e sites http://10.0.2.2:PORT (device-test.sh --sites lookups)",
                          sites != null)
        Caracole.sitesForTests = RoutedTransport(sites!!)
    }

    @After fun refuseAgain() {
        Caracole.sitesForTests = CaracoleTestRunner.REFUSING
    }

    @Test fun theCardsPanelSearchesListsAndTakesARecordAndTheAutoSheetIsLaidOutAgainOverIt() {
        ActivityScenario.launch(MainActivity::class.java).use {
            val phone = Caracole.phone(context)
            val now = Stamps.of(Instant.now())
            val song = phone.parts.database.writeBlocking { db ->
                val s = Songs.byKey(db, "a-singer/a-song-of-no-words") ?: phone.parts.store.add(db, "A Singer",
                    "A Song of No Words", null, 180_000, now = now)
                val heard = Heard.of(Json.parseToJsonElement(HEARD))
                val made = SheetHalf.make(s, null, heard)
                val raw = SheetHalf.raw(s, null, made)
                val version = Versions.upsert(db, "auto", s.id.toString(), s.id, "sheet", "auto", 0.0, 0, 1, null,
                                              "file://", raw, now)
                Kept.keepFile(db, phone.parts.store, s, version, Versions.SHEET_FILE_NAMES[1],
                              made.text.toByteArray(Charsets.UTF_8), 1, now)
                Versions.refreshStatus(db, s.id, ignored = false, now = now)
                Songs.byId(db, s.id)!!
            }
            val form = arrayOf("song" to song.id.toString(), "identity" to song.key)

            val (searched, answer) = PhoneForms.post("/lyrics/search", *form, "artist" to "Thomas Moore",
                                                     "title" to "The Minstrel Boy")
            assertEquals(answer, 202, searched)
            val search = await(JSONObject(answer).getInt("job"))
            assertEquals(search.asJson().toString(), Job.DONE, search.state)

            val (status, panel) = PhoneForms.script("/api/lyrics/search?song=${song.id}&identity=" +
                                                    URLEncoder.encode(song.key, "UTF-8"))
            assertEquals(panel, 200, status)
            val kept = JSONObject(panel).getJSONObject("search")
            assertTrue(panel, kept.getBoolean("pickable") && kept.getString("line").startsWith("Searched: "))
            val record = kept.getJSONArray("rows").getJSONObject(0).getString("record")
            assertTrue(panel, record.startsWith("lrclib:"))

            val (picked, queued) = PhoneForms.post("/lyrics/pick", *form, "record" to record)
            assertEquals(queued, 200, picked)  // the page's script: the job's view
            val pick = await(JSONObject(queued).getJSONObject("job").getInt("id"))
            assertEquals(pick.asJson().toString(), Job.DONE, pick.state)
            val stages = pick.stages.associate { it.name to it }
            assertEquals(pick.asJson().toString(), "done", stages.getValue("lyrics").state)
            assertEquals(pick.asJson().toString(), "done", stages.getValue("chords").state)
            val (lyrics, sheet) = phone.parts.database.read { db ->
                val s = Songs.byId(db, song.id)!!
                val auto = Kept.keptFiles(db, s.id).first { it.name == Versions.SHEET_FILE_NAMES[1] }
                s.lyricsStatus to File(phone.parts.store.libraryDir, auto.path).readText()
            }
            assertEquals("found", lyrics)
            assertTrue(sheet.take(600), sheet.lines().any { it.isNotBlank() && !it.contains('[') && it.any(Char::isLetter) })
        }
    }

    private fun await(id: Int): Job = runBlocking { withTimeout(300_000) { Caracole.phone(context).queue.await(id) } }

    private companion object {
        /** What was heard of a 30 s song: four chords, a beat every half second, a downbeat every two. */
        val HEARD: String = """{"contract": 1, "duration": 30.0, "chords": [[0.0, 10.0, "Am"], [10.0, 20.0, "F"], """ +
            """[20.0, 30.0, "C"]], "beats": [${(0 until 60).joinToString(", ") { "${it * 0.5}" }}], "downbeats": """ +
            """[${(0 until 15).joinToString(", ") { "${it * 2.0}" }}]}"""
    }
}
