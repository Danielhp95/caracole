package io.github.danielhp95.caracole.e2e

import io.github.danielhp95.caracole.core.sync.SyncUnit
import io.github.danielhp95.caracole.mirror.Gate
import io.github.danielhp95.caracole.server.files.PhoneGate
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.text
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import org.junit.Assume
import org.junit.Test
import java.io.File
import java.net.ConnectException
import java.net.InetSocketAddress
import java.net.Socket
import java.net.URI
import io.github.danielhp95.caracole.mirror.SyncEngine as MirrorSync
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue
import kotlin.test.fail

/**
 * The phone's side of the goal end to end (the Android plan's §9, docs/android_port.md), a phase at a time against the
 * real caracole serve tests/test_android_e2e.py starts and stops between them: each test runs only as its phase
 * (`-Pcaracole.e2e.phase=N`, with `-Pcaracole.e2e.server`, the computer's address, and `-Pcaracole.e2e.dir`, the
 * scenario's folder), and is skipped otherwise. The phone is server.Phone over DIR/phone/ ([ScenarioPhone]), driven
 * through its App as its WebView would drive it; each phase ends by writing DIR/phone/phase-N.json (the requests it
 * sent, counted by [Requests], and what the Python side checks next).
 *
 * 1. The computer's index (`GET /api/peer/index`, Phone.importIndex), its pages (the mirror's sync) and its library
 *    (the Sync tab's compare, then apply with no choice) come to a new phone: the 20 songs with the computer's
 *    digests, the goal's changes in `phone_overrides`, each mirrored sheet served (its gate SERVE), and an indexed
 *    song the library hasn't got found.
 * 2. With the computer off: an indexed song found and added by its row's Get it, two asked for by name (Request with
 *    Fetch now, and without), R and C1 removed (C1's card gone from the page, its sheet "removed on the phone"); not
 *    one request sent, and the computer's port refusing.
 * 3. The comparison lists the phone's three adds and R's units as the phone's, the computer's three adds and C2 as
 *    the computer's, and C1 a conflict (its tombstone the phone's); applied with C1 kept as the phone has it, every
 *    stage done and nothing left; then the phone's units written to DIR/phone/phone-state.json.
 * 4. A comparison once more finds no difference.
 */
class PhoneScenarioTest {
    @Test fun phase1_theComputersLibraryIndexAndPagesComeToANewPhone() = phase(1) { phone, scenario ->
        val index = File(phone.stateDir, "cache/index.sqlite").apply { parentFile.mkdirs() }
        phone.peer().index(index)
        done(phone.await(phone.phone.importIndex(index).id))
        MirrorSync(phone.mirror).sync(phone.address)

        val compared = compare(phone)
        assertTrue(compared.proposals.values.all { it == "theirs" }, "a new phone takes everything: $compared")
        assertTrue(compared.proposals.keys.containsAll(scenario.songs.map { it.unit }), "$compared")
        apply(phone, compared, "")

        val mine = phone.units()
        assertEquals(phone.peer().state(phone.ownId()).units, mine, "the phone's units are the computer's")
        assertEquals(scenario.songs.map { it.unit }.toSet(), mine.keys.filter { it.startsWith("song/") }.toSet())

        val held = phone.database.read { db ->
            db.query("SELECT tbl, key FROM phone_overrides ORDER BY tbl, key") { it.text(0)!! to it.text(1)!! }
        }
        for ((table, keys) in scenario.changed) {
            assertEquals(keys.sorted(), held.filter { it.first == table }.map { it.second }.sorted(), "[$table]")
        }

        val sheets = phone.mirror.manifest()!!.entries.filter { it.path.endsWith("/sheet.html") }
        assertEquals(scenario.songs.map { it.unit }.toSet(), sheets.map { it.unit }.toSet(), "the mirror's sheets")
        val gate = PhoneGate(phone.database)
        for (sheet in sheets) {
            assertEquals(Gate.SERVE, gate.check(sheet.unit!!, sheet.digest), sheet.path)
            val page = phone.get("/" + quotePath(sheet.path))
            assertEquals(200, page.status, "${sheet.path}: ${page.text.take(500)}")
            assertTrue(page.header("content-type").orEmpty().startsWith("text/html"), sheet.path)
        }

        val hit = indexHit(phone, scenario)
        val (artistKey, songKey) = hit.text("ug").split("/", limit = 2)
        assertEquals(0L, phone.database.read { db ->
            db.one("SELECT COUNT(*) FROM songs WHERE match_artist_key = ? AND match_song_key = ?", artistKey, songKey) {
                it.long(0)
            }
        }, "the indexed song is no song of the library's")

        buildJsonObject { put("songs", scenario.songs.size) }
    }

    @Test fun phase2_thePhoneOnItsOwnSearchesAddsAndRemovesAndAsksNoOne() = phase(2) { phone, scenario ->
        val computer = URI(phone.server)
        assertFailsWith<ConnectException>("the computer is off") {
            Socket().use { it.connect(InetSocketAddress(computer.host, computer.port), 5_000) }
        }
        val known = scenario.songs.map { it.key }.toSet()

        val hit = indexHit(phone, scenario)
        val lookup = phone.post("/lookup", "artist" to hit.text("artist"), "title" to hit.text("title"),
                                "ug" to hit.text("ug"))
        assertEquals(202, lookup.status, lookup.text.take(1000))
        done(phone.await(phone.jobOf(lookup)))
        for ((song, fetch) in scenario.requests) {
            val asked = phone.post("/request", "artist" to song.artist, "title" to song.title, "fetch" to fetch)
            done(phone.await(phone.jobOf(asked)))
        }
        val added = phone.database.read { db ->
            db.query("SELECT key, artist, title FROM songs ORDER BY id") { Song(it.text(1)!!, it.text(2)!!, it.text(0)!!) }
        }.filter { it.key !in known }
        assertEquals(3, added.size, "$added")
        assertTrue(added.map { it.key }.containsAll(scenario.requests.map { it.first.key }), "$added")

        for (song in listOf(scenario.r, scenario.c1)) {
            val id = phone.database.read { db -> db.one("SELECT id FROM songs WHERE key = ?", song.key) { it.long(0)!! } }
            assertNotNull(id, song.key)
            val question = phone.post("/remove", "song" to "$id", json = false)
            val removal = phone.answer(question)["removal"]?.jsonObject ?: fail("no question: ${question.text.take(1000)}")
            assertEquals(song.key, removal.text("key"))
            done(phone.await(phone.jobOf(phone.post("/remove", "song" to "$id", "confirm" to "1",
                                                    "key" to song.key, json = false))))
        }
        val cards = pageData(phone)["songs"]!!.jsonArray.map { it.jsonObject.text("identity") }
        assertFalse(scenario.c1.key in cards || scenario.r.key in cards, "a removed song's card is gone")
        val c1 = phone.mirror.manifest()!!.entries.single { it.unit == scenario.c1.unit && it.path.endsWith("/sheet.html") }
        val sheet = phone.get("/" + quotePath(c1.path))
        assertTrue("removed on the phone" in sheet.text, sheet.text.take(1000))

        assertEquals(0, Requests.count, "the phone on its own sends nothing")
        buildJsonObject {
            put("added", JsonArray(added.map { song ->
                buildJsonObject { put("artist", song.artist); put("title", song.title); put("key", song.key) }
            }))
        }
    }

    @Test fun phase3_theDifferencesAreListedAndTheOwnersChoicesApply() = phase(3) { phone, scenario ->
        val adds = read(File(phone.home, "phase-2.json"))["added"]!!.jsonArray.map { it.jsonObject.text("key") }
        val expected = buildMap {
            for (key in adds) put("song/$key", "mine")
            for (song in scenario.adds) put(song.unit, "theirs")
            put(scenario.c2.unit, "theirs")
            put(scenario.c1.unit, "conflict")
            put(scenario.c1.tombstone, "mine")
            put(scenario.r.unit, "mine")
            put(scenario.r.tombstone, "mine")
        }
        val compared = compare(phone)
        assertEquals(expected, compared.proposals)

        val job = apply(phone, compared, "here\t${scenario.c1.unit}")
        val view = JobViews.view(job, phone.phone.queue)
        for (step in view["steps"]!!.jsonArray.map { it.jsonObject }) {
            assertTrue(step.text("state") in setOf("done", "skipped"), "the sync's stages: ${view["steps"]}")
        }
        val outcome = view["outcome"]!!.jsonObject
        assertEquals(JsonArray(emptyList()), outcome["left"], "nothing left: $outcome")

        write(File(phone.home, "phone-state.json"), buildJsonObject {
            put("units", JsonObject(phone.units().toSortedMap().mapValues { (_, unit) -> stateOf(unit) }))
        })
        buildJsonObject { put("taken", outcome["taken"] ?: JsonNull); put("given", outcome["given"] ?: JsonNull) }
    }

    @Test fun phase4_aComparisonOnceMoreFindsNothing() = phase(4) { phone, _ ->
        val found = compare(phone).proposals
        assertEquals(emptyMap(), found)
        buildJsonObject { put("differences", JsonArray(found.keys.map(::JsonPrimitive))) }
    }

    // --- the phases' plumbing ---------------------------------------------------------------------------------------

    private val phase: Int? = System.getProperty("caracole.e2e.phase")?.toIntOrNull()
    private val server: String? = System.getProperty("caracole.e2e.server")
    private val dir: File? = System.getProperty("caracole.e2e.dir")?.let(::File)

    /** Phase [n]'s [body], given the phone over DIR/phone/ and the scenario, if it is the phase asked for; what it
     * returns, and the requests the phone sent, written to DIR/phone/phase-N.json. */
    private fun phase(n: Int, body: (ScenarioPhone, Scenario) -> JsonObject) {
        Assume.assumeTrue("phase $n alone, against a computer (-Pcaracole.e2e.phase, .server, .dir)",
                          phase == n && server != null && dir != null)
        val home = File(dir, "phone")
        if (n == 1) assertFalse(home.exists(), "phase 1 makes a new phone, and $home is there already")
        Requests.install()
        Requests.reset()
        val scenario = Scenario.read(dir!!)
        val result = ScenarioPhone(home, server!!).use { phone -> body(phone, scenario) }
        write(File(home, "phase-$n.json"), JsonObject(result + mapOf(
            "phase" to JsonPrimitive(n), "requests" to JsonPrimitive(Requests.count),
        )))
    }

    /** A comparison the phone keeps ([id]), and each difference's proposal by its unit. */
    private data class Compared(val id: String, val proposals: Map<String, String>)

    /** The Sync tab's compare: POST /sync/compare, the computer's address. */
    private fun compare(phone: ScenarioPhone): Compared {
        val answer = phone.post("/sync/compare", "address" to phone.server)
        assertEquals(200, answer.status, answer.text.take(2000))
        val compared = phone.answer(answer)
        return Compared(compared.text("comparison"), compared["differences"]!!.jsonArray.map { it.jsonObject }
            .associate { it.text("id") to it.text("proposal") })
    }

    /** The Sync tab's apply of [compared], with [choices] (lines `<here|there|skip>\t<unit id>`) and no preference:
     * its job, done. */
    private fun apply(phone: ScenarioPhone, compared: Compared, choices: String): Job {
        val answer = phone.post("/sync/apply", "comparison" to compared.id, "prefer" to "", "choices" to choices)
        assertEquals(200, answer.status, answer.text.take(2000))
        return done(phone.await(phone.jobOf(answer)))
    }

    private fun done(job: Job): Job {
        assertEquals("done", job.state, "${job.spec.title}: ${job.asJson()}")
        return job
    }

    /** The scenario's indexed song, as /api/search's `index` rows give it. */
    private fun indexHit(phone: ScenarioPhone, scenario: Scenario): JsonObject {
        val ug = scenario.index.text("artist_key") + "/" + scenario.index.text("song_key")
        val found = phone.answer(phone.script("/api/search?q=" + quote(scenario.index.text("query"))))
        return found["index"]!!.jsonArray.map { it.jsonObject }.firstOrNull { it.text("ug") == ug }
            ?: fail("/api/search finds no $ug: $found")
    }

    /** The library page's data, GET /'s `songs` block. */
    private fun pageData(phone: ScenarioPhone): JsonObject {
        val page = phone.get("/")
        assertEquals(200, page.status, page.text.take(1000))
        val block = Regex("""<script type="application/json" id="songs">(.*?)</script>""", RegexOption.DOT_MATCHES_ALL)
            .find(page.text) ?: fail("no data on the library page")
        return Json.parseToJsonElement(block.groupValues[1]).jsonObject
    }

    private fun stateOf(unit: SyncUnit): JsonObject =
        buildJsonObject { put("label", unit.label); put("digest", unit.digest) }

    private fun read(file: File): JsonObject = Json.parseToJsonElement(file.readText()).jsonObject

    private fun write(file: File, json: JsonElement) =
        file.writeText(Json { prettyPrint = true }.encodeToString(JsonElement.serializer(), json) + "\n")
}
