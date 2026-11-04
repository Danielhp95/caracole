package io.github.danielhp95.caracole.e2e

import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.sync.SyncUnit
import io.github.danielhp95.caracole.mirror.Gate
import io.github.danielhp95.caracole.mirror.ServerAddress
import io.github.danielhp95.caracole.server.files.PhoneGate
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.testing.bytes
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
import kotlinx.serialization.json.jsonPrimitive
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
 *    (the Sync tab's compare, then apply with no choice: compare, take, mirror and agree done, nothing to give, every
 *    unit taken) come to a new phone: the 20 songs with the computer's digests, the goal's changes in
 *    `phone_overrides`, each mirrored sheet served (its gate SERVE), and an indexed song the library hasn't got found
 *    under search.py's names of it. Both clients' requests were counted, PeerClient's and the mirror's; the phone's
 *    songs and each index table's rows are written for the Python side to check.
 * 2. With the computer off: an indexed song found and added by its row's Get it, two asked for by name (Request with
 *    Fetch now, and without), each line in caracole's words, R and C1 removed (C1's card gone from the page, its sheet
 *    "removed on the phone"); not one request sent, and the computer's port refusing. Get it and Fetch now are
 *    lookups, `caracole get`, every site refused (the phone's transport): each adds its song, its sites' stages
 *    failed or skipped (a lane's port still neutral), never a miss.
 * 3. The comparison lists the phone's three adds and R's units as the phone's, the computer's three adds and C2 as
 *    the computer's, and C1 a conflict (its tombstone the phone's); applied with C1 kept as the phone has it: every
 *    stage done (the index's, done or skipped), the computer's adds and C2 taken, the phone's adds, C1's and R's units
 *    given, nothing left, and C2's sheet served again as the computer renders it now; then the phone's units written
 *    to DIR/phone/phone-state.json.
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
        val synced = apply(phone, compared, "")
        assertStages(phone, synced, SyncEngine.COMPARE to DONE, SyncEngine.TAKE to DONE, SyncEngine.GIVE to SKIPPED,
                     SyncEngine.MIRROR to DONE, SyncEngine.AGREE to DONE)
        val outcome = outcome(phone, synced)
        assertEquals(compared.proposals.keys, units(outcome, "taken"), "every unit of the computer's taken: $outcome")
        assertEquals(emptySet(), units(outcome, "given"), "nothing given: $outcome")
        assertEquals(JsonArray(emptyList()), outcome["left"], "nothing left: $outcome")

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
        assertEquals(scenario.indexSong.artist to scenario.indexSong.title, hit.text("artist") to hit.text("title"),
                     "the indexed song named as search.py names it")

        // Both of the phone's clients were seen, so that phase 2's count of none means neither sent anything.
        val asked = Requests.paths.toSet()
        for (path in listOf(PeerClient.STATE_PATH, PeerClient.UNIT_PATH, PeerClient.FILE_PATH, PeerClient.INDEX_PATH,
                            ServerAddress.MANIFEST_PATH)) {
            assertTrue(path in asked, "no request to $path counted: $asked")
        }

        buildJsonObject {
            put("songs", phone.database.read { db -> db.one("SELECT COUNT(*) FROM songs") { it.long(0) } })
            put("indexes", JsonObject(scenario.indexTables.associateWith { table ->
                JsonPrimitive(phone.database.read { db -> db.one("SELECT COUNT(*) FROM \"$table\"") { it.long(0) } })
            }))
        }
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
        refusedLookup(done(phone.await(phone.jobOf(lookup))))
        for ((song, fetch) in scenario.requests) {
            val asked = phone.post("/request", "artist" to song.artist, "title" to song.title, "fetch" to fetch)
            val job = done(phone.await(phone.jobOf(asked)))
            // status.py's words for a song added that nothing was found for yet: Fetch now's sites all refused, an
            // add's none asked
            assertEquals(ADDED, JobViews.line(job).text, "${song.key}, fetch=$fetch")
            if (fetch == "1") refusedLookup(job)
        }
        val added = phone.database.read { db ->
            db.query("SELECT key, artist, title FROM songs ORDER BY id") { Song(it.text(1)!!, it.text(2)!!, it.text(0)!!) }
        }.filter { it.key !in known }
        assertEquals(3, added.size, "$added")
        assertTrue(added.map { it.key }.containsAll(scenario.requests.map { it.first.key }), "$added")
        assertTrue(added.any { it == scenario.indexSong }, "Get it adds the indexed song as search.py names it: $added")

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
        assertStages(phone, job, SyncEngine.COMPARE to DONE, SyncEngine.TAKE to DONE, SyncEngine.GIVE to DONE,
                     SyncEngine.MIRROR to DONE, SyncEngine.AGREE to DONE)
        val outcome = outcome(phone, job)
        assertEquals(scenario.adds.map { it.unit }.toSet() + scenario.c2.unit, units(outcome, "taken"), "$outcome")
        assertEquals(adds.map { "song/$it" }.toSet() + listOf(scenario.c1.unit, scenario.c1.tombstone, scenario.r.unit,
                                                             scenario.r.tombstone),
                     units(outcome, "given"), "$outcome")
        assertEquals(JsonArray(emptyList()), outcome["left"], "nothing left: $outcome")

        // The mirror brought up to date after the take: C2's sheet as the computer renders it now, its gate SERVE
        // for the digest the phone took, and so every page of a unit.
        val gate = PhoneGate(phone.database)
        val pages = phone.mirror.manifest()!!.entries.filter { it.unit != null }
        for (page in pages) assertEquals(Gate.SERVE, gate.check(page.unit!!, page.digest), page.path)
        val c2 = pages.single { it.unit == scenario.c2.unit && it.path.endsWith("/sheet.html") }
        val sheet = phone.get("/" + quotePath(c2.path))
        assertEquals(200, sheet.status, sheet.text.take(1000))
        val now = File(phone.home.parentFile, "computer/library/${c2.path}")  // the computer's, rendered again
        assertTrue(sheet.bytes.contentEquals(now.readBytes()),
                   "C2's sheet as the computer has it now: ${sheet.text.take(500)}")

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

    /** A lookup whose every site refused (phase 2: the computer off, the phone's transport refusing them): its song
     * added, LRCLIB's stage failed, every site's failed or skipped (a lane's port still neutral), none a miss, and its
     * line status.py's [ADDED]. */
    private fun refusedLookup(job: Job) {
        assertEquals(listOf("get"), job.steps.map { it.args.first() }, job.spec.title)
        val stages = job.stages.associate { it.name to it }
        assertEquals(DONE, stages.getValue("song").state, "${job.spec.title}: ${job.asJson()}")
        assertEquals("failed", stages.getValue("lyrics").state, "${job.spec.title}: LRCLIB refused")
        for (site in listOf("ug", "lacuerda", "gtptabs", "harptabs", "gametabs")) {
            assertTrue(stages.getValue(site).state in setOf("failed", SKIPPED), "${job.spec.title}: $site ${job.asJson()}")
        }
        assertFalse(job.stages.any { "not found" in it.detail.lowercase() || "missing" in it.detail.lowercase() },
                    "a refused site is never a miss: ${job.asJson()}")
        assertEquals(ADDED, JobViews.line(job).text, job.spec.title)
    }

    private fun done(job: Job): Job {
        assertEquals(DONE, job.state, "${job.spec.title}: ${job.asJson()}")
        return job
    }

    /** A sync job's stages as its view shows them: each of [expected] in its state, and the index's, the last,
     * done or skipped (skipped when no index of the computer's is newer than the one the phone merged). */
    private fun assertStages(phone: ScenarioPhone, job: Job, vararg expected: Pair<String, String>) {
        val steps = JobViews.view(job, phone.phone.queue)["steps"]!!.jsonArray.map { it.jsonObject }
        val states = steps.associate { it.text("name") to it.text("state") }
        assertEquals(SyncEngine.STAGES.map { it.first }, steps.map { it.text("name") }, "the sync's stages: $steps")
        assertEquals(expected.toMap(), states - SyncEngine.INDEX, "the sync's stages: $steps")
        assertTrue(states[SyncEngine.INDEX] in setOf(DONE, SKIPPED), "the sync's stages: $steps")
    }

    /** A sync job's outcome, as its view gives it: what was taken, given and left. */
    private fun outcome(phone: ScenarioPhone, job: Job): JsonObject =
        JobViews.view(job, phone.phone.queue)["outcome"] as? JsonObject ?: fail("no outcome: ${job.asJson()}")

    /** The units an outcome's list (taken, given) names. */
    private fun units(outcome: JsonObject, list: String): Set<String> =
        outcome[list]!!.jsonArray.map { it.jsonPrimitive.content }.toSet()

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

    private companion object {
        const val DONE = "done"
        const val SKIPPED = "skipped"

        /** status.py's line for a song added that nothing was found for yet (phase 2's). */
        const val ADDED = "Added: the nightly run looks for it"
    }
}
