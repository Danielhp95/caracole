package io.github.danielhp95.caracole.e2e

import io.github.danielhp95.caracole.core.backup.Backups
import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.RenderStats
import io.github.danielhp95.caracole.core.songbooks.Songbooks
import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.sync.SyncUnit
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.ug.SheetVersions
import io.github.danielhp95.caracole.mirror.Gate
import io.github.danielhp95.caracole.mirror.ServerAddress
import io.github.danielhp95.caracole.server.files.PhoneGate
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.PhoneDeps
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.lookups.BackupRunner
import io.github.danielhp95.caracole.server.lookups.InboxShare
import io.github.danielhp95.caracole.server.lookups.Review
import io.github.danielhp95.caracole.server.testing.bytes
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.text
import io.github.danielhp95.caracole.viewer.progressions.Progressions
import io.github.danielhp95.caracole.viewer.render.WrittenPages
import io.github.danielhp95.caracole.viewer.render.PhoneRender
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
import java.security.MessageDigest
import java.time.Instant
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
 * 5. With the computer off, the phone looks songs up against the fake sites server (`-Pcaracole.e2e.sites`,
 *    tests/helpers/fake_sites.py's scenario `lookups`, every site's request sent there by RoutedTransport): Get it on
 *    a search row of a song new to both sides keeps its sheet, LRCLIB's timed lyrics and its card's sheet.txt,
 *    served; a song asked for with no fetch (no site asked), then Fetch now on its card, keeps its sheet, every lyrics
 *    site answering a miss; Fetch them keeps more of the first one's versions; a song at a bare tab its artist's page
 *    alone lists, asked for with Fetch now, keeps its sheet from that page, an index page noted for the computer; the
 *    pages phase's (milestone 5's check): Get it on a song whose charts sing Chinese words keeps its sheet and its other
 *    version beside it, and on one with a harmonica tab on harptabs.com its sheet and the tab, and the phone makes
 *    their pages itself (the lookup's pdf and pages stages: the sheets' viewers and .cho, the kept version's page, the
 *    tab's page, info.json), each recorded at its song unit's digest and served as it wrote it, the Chinese sheet's
 *    with each character's reading, which /api/search's progression finds by what it plays; Get it on a song whose
 *    page redirects to one robots.txt closes keeps no sheet, the redirect never followed; Get it on one whose page
 *    answers 403 keeps none either and is never a miss, Ultimate Guitar cooling down on the phone. Each lookup asks the sites (counted from
 *    just before it is posted), each at most its lookup_requests, every lookup together at most its lookup_per_hour,
 *    never a URL robots.txt closes, every URL one the scenario answers (`known`: no URL the computer's caracole
 *    wouldn't ask read as a miss), and no request leaves for any host but the fake server's (Requests, against the
 *    server's own count); what the phone noted of the index pages it read, and each lookup's requests (Get it's URLs
 *    in order, which the Python side compares with the computer's own lookup), are written for the Python side.
 * 6. The computer back, having looked the first song up itself against the same sites and changed its caracole.toml:
 *    the comparison lists the phone's lookups as the phone's and the song looked up on both sides a conflict (how many
 *    conflicts, and which fields of the unit differ, are reported: §11 Q2); applied with that one taken from the
 *    computer: every stage done, the rest given, nothing left; the computer's settings taken (kv `phone:settings`,
 *    `PhoneConfig.read`); Ultimate Guitar still cooling on the phone, as nothing of either side's politeness crosses;
 *    the index pages the phone read pushed (none noted left); every mirrored page served, and the pages the phone made
 *    of the songs it gave still its own, served as it wrote them (tests/test_android_e2e.py's step 11 holds them to
 *    Python's for the same inputs), and those of the song it took, which the computer rendered again as it looked it
 *    up, forgotten (their record and files), the mirror's serving at the unit's digest the take moved it to; then the
 *    phone's units written to DIR/phone/phone-state.json again.
 * 7. A new build (PhoneRender's stamp another), every site refused: the render job makes the pages owed again, a
 *    lookup queued as it starts runs between two songs, before the job ends, phase 5's pages, which the mirror holds
 *    the computer's of now, forgotten for the mirror's, and its time over the library is written for the report,
 *    with a pass's that makes every song's pages itself, as a phone with none of the computer's (no mirror).
 * 8. Milestone 6's changes, the computer back and the fake sites up, each through its own route: a songbook made, a
 *    song's key set in it, a song moved and the songbook renamed, its songbook.html the phone's and served; a song
 *    matched only uncertainly, its review answered with a candidate; a version kept beside a sheet (Keep it, one tab
 *    page from the fake sites, Ultimate Guitar's phase-5 cooldown over); a version made a song's own (Export PDF's
 *    `mine=1`); a Guitar Pro file shared to the app (InboxShare), filed for its song. The comparison lists each
 *    change's unit as the phone's and nothing else, the apply gives them all and leaves nothing, and a comparison
 *    after finds nothing; each change and the phone's units are written for the Python side to read back.
 * 9. The round (the integration's scenario), the computer off and the fake sites up: two songs new to both sides
 *    looked up by their rows' Get it, the first played from its card (its page the phone's own), a songbook made of
 *    both and the second's key set in it, the first made the song's own version (Export PDF's `mine=1`), a Guitar Pro
 *    file shared to the second, and a backup made by hand; each lookup within its limits; the pages, as every change
 *    left them, and each change written for the Python side.
 * 10. The computer back, one sync: the round's units (its two songs and the songbook) the phone's and nothing else,
 *    given, nothing taken or left, a comparison after finding nothing, the round's pages still the phone's own; the
 *    phone's units written for the Python side, which holds them to the computer's and the pages to Python's.
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
        refusedLookup(phone, done(phone.await(phone.jobOf(lookup))))
        for ((song, fetch) in scenario.requests) {
            val asked = phone.post("/request", "artist" to song.artist, "title" to song.title, "fetch" to fetch)
            val job = done(phone.await(phone.jobOf(asked)))
            if (fetch == "1") {
                refusedLookup(phone, job)
            } else {  // an add asks no site: status.py's line for one, as the page shows it
                assertEquals(ADDED, shownLine(phone, job.id).text("text"), "${song.key}, fetch=$fetch")
            }
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

    @Test fun phase5_thePhoneOnItsOwnLooksSongsUpAgainstTheFakeSites() = phase(5) { phone, scenario ->
        val fake = FakeSites(sites ?: fail("phase 5 looks songs up against the fake sites (-Pcaracole.e2e.sites)"))
        val computer = URI(phone.server)
        assertFailsWith<ConnectException>("the computer is off") {
            Socket().use { it.connect(InetSocketAddress(computer.host, computer.port), 5_000) }
        }
        val lookups = scenario.lookups
        val asked = LinkedHashMap<String, List<JsonObject>>()  // each lookup's requests to the sites, by its name
        val lines = LinkedHashMap<String, JsonObject>()
        val started = fake.count()

        /** The lookup [post] queues, done: the requests the fake sites were sent from just before it was posted (so
         * that none its worker sends at once escapes the count) kept under [name], at least one, and its line read. */
        fun lookUp(name: String, post: () -> Response): Job {
            val before = fake.count()
            val response = post()
            assertTrue(response.status in setOf(200, 202), "$name: HTTP ${response.status} ${response.text.take(1000)}")
            val job = done(phone.await(phone.jobOf(response)))
            asked[name] = fake.log(before)
            assertTrue(asked.getValue(name).isNotEmpty(), "$name asked no site: ${job.asJson()}")
            lines[name] = shownLine(phone, job.id)
            return job
        }

        // Get it on a search's row: a song new to both sides, its sheet, timed lyrics and card's sheet.txt the phone's.
        val getIt = lookups.song("get_it")
        val hit = searchRow(phone, getIt.search!!)
        val got = lookUp("get it") {
            phone.post("/lookup", "artist" to hit.text("artist"), "title" to hit.text("title"), "ug" to hit.text("ug"))
        }
        assertStage(got, "song", DONE)
        assertStage(got, "match", DONE)
        assertStage(got, "sheet", DONE)
        assertStage(got, "lyrics", DONE)
        val minstrel = songOf(phone, getIt.found)
        val sheet = keptSheet(phone, minstrel.key)
        assertTrue("Made-up words of verse 1" in sheet, "the chart the fake sites gave: ${sheet.take(500)}")
        assertEquals("found", lyricsStatus(phone, minstrel.key), "LRCLIB's lyrics kept")
        val timed = File(songFolder(phone, minstrel.key), "lyrics.lrc")
        assertTrue(timed.isFile, "LRCLIB's timed lyrics written as $timed")
        assertTrue(timed.readText().startsWith("[00:10.00]"), "LRCLIB's timed lyrics: ${timed.readText().take(300)}")
        servedFromItsCard(phone, minstrel.key, sheet)

        // A song asked for with no fetch (no site asked), then Fetch now on its card: every lyrics site a miss.
        val fetchNow = lookups.song("fetch_now").song
        val quiet = fake.count()
        done(phone.await(phone.jobOf(phone.post("/request", "artist" to fetchNow.artist, "title" to fetchNow.title,
                                                "fetch" to "0"))))
        assertEquals(emptyList(), fake.log(quiet), "a request with no fetch asks no site")
        val stilly = songOf(phone, fetchNow)
        val fetched = lookUp("fetch now") { phone.post("/fetch", "song" to "${idOf(phone, stilly.key)}") }
        assertStage(fetched, "sheet", DONE)
        assertTrue("Made-up words" in keptSheet(phone, stilly.key))
        assertEquals("missing", lyricsStatus(phone, stilly.key),
                     "every lyrics site answered a miss: ${fetched.asJson()}")

        // Fetch them: more of Get it's song's versions kept beside its sheet.
        val versionsBefore = keptVersions(phone, minstrel.key)
        val more = lookUp("fetch them") { phone.post("/versions/keep-more", "song" to "${idOf(phone, minstrel.key)}") }
        assertTrue(keptVersions(phone, minstrel.key).size > versionsBefore.size,
                   "Fetch them kept more of its versions (it had $versionsBefore): ${more.asJson()}")

        // Fetch now on the request form: a song at a bare tab its artist's page alone lists, which the phone notes.
        val rose = lookups.song("artist_page")
        val roseJob = lookUp("artist page") {
            phone.post("/request", "artist" to rose.song.artist, "title" to rose.song.title, "fetch" to "1")
        }
        assertTrue("Made-up words" in keptSheet(phone, rose.song.key), "the bare tab's sheet: ${roseJob.asJson()}")
        assertTrue(asked.getValue("artist page").any { it.text("url").startsWith(rose.artistPage) },
                   "the artist's page read: ${asked["artist page"]}")
        assertTrue(rose.tabs.single() in asked.getValue("artist page").map { it.text("url") },
                   "the bare tab read: ${asked["artist page"]}")
        val reads = noted(phone)
        assertTrue(reads.any { it.startsWith("ug:") && URI(it.removePrefix("ug:")).path == URI(rose.artistPage).path },
                   "the artist's page noted for the computer: $reads")

        // The pages phase's lookups (milestone 5's check): Get it on the row of a song whose charts sing Chinese words
        // keeps its sheet and its other version beside it, and on one with a harmonica tab on harptabs.com its sheet
        // and the tab; the phone makes their pages itself (the lookup's pdf and pages stages, PhoneRender), each
        // recorded at its song unit's digest now and served as it wrote it, the Chinese sheet's with its readings,
        // and /api/search's progression finds that song by what it plays. Step 11 holds them to Python's.
        val chinese = lookups.song("chinese")
        val chineseRow = searchRow(phone, chinese.search!!)
        val sung = lookUp("chinese") {
            phone.post("/lookup", "artist" to chineseRow.text("artist"), "title" to chineseRow.text("title"),
                       "ug" to chineseRow.text("ug"))
        }
        for (stage in listOf("sheet", "pdf", "ug", "pages")) assertStage(sung, stage, DONE)
        val beside = chinese.tabs.drop(1).map { "version-${it.substringAfterLast('-')}.txt" }
        assertEquals(beside, keptVersions(phone, chinese.found.key), "its other version kept beside its sheet")
        val harmonica = lookups.song("harmonica")
        val harpRow = searchRow(phone, harmonica.search!!)
        val harped = lookUp("harmonica") {
            phone.post("/lookup", "artist" to harpRow.text("artist"), "title" to harpRow.text("title"),
                       "ug" to harpRow.text("ug"))
        }
        for (stage in listOf("sheet", "pdf", "harptabs", "pages")) assertStage(harped, stage, DONE)
        assertTrue(harmonica.harp!! in asked.getValue("harmonica").map { it.text("url") },
                   "its tab's page read on harptabs.com: ${asked["harmonica"]}")
        assertTrue("harmonica-1.txt" in keptFiles(phone, harmonica.found.key), "${keptFiles(phone, harmonica.found.key)}")
        val pages = linkedMapOf("chinese" to chinese.found, "harmonica" to harmonica.found).mapValues { (_, song) ->
            ownPages(phone, song.key)
        }
        assertTrue(pages.getValue("chinese").keys.containsAll(
            listOf("sheet.html", "sheet.cho") + beside.map { it.removeSuffix(".txt") + ".html" }), "${pages["chinese"]}")
        assertTrue(pages.getValue("harmonica").keys.containsAll(listOf("sheet.html", "sheet.cho", "harmonica-1.html")),
                   "${pages["harmonica"]}")
        val sheetData = pageData(ownFile(phone, chinese.found.key, "sheet.html").readText(), "song")
        assertTrue(sheetData["pinyin"]!!.jsonArray.any { line ->
            line is JsonArray && line.any { it is JsonPrimitive && it.isString && it.content.isNotEmpty() }
        }, "each character's reading in the Chinese sheet's data: ${sheetData["pinyin"]}")
        val tabs = pageData(ownFile(phone, harmonica.found.key, "sheet.html").readText(), "song")["harmonicaTabs"]
        assertEquals(listOf("harmonica-1.html"), tabs!!.jsonArray.map { it.jsonObject.text("page") },
                     "the sheet's viewer links its harmonica tab's page")
        val playing = progressionFinds(phone, chinese.found.key)

        // Get it on a song whose page redirects to its print view, which robots.txt closes: never followed, the song
        // matched and its page checked as the computer's caracole checks it (tests/test_fake_sites.py: a page
        // robots.txt closes is Ultimate Guitar's answer, RobotsClosed, so the song isn't left dirty).
        val wild = lookups.song("closed")
        val wildRow = searchRow(phone, wild.search!!)
        val closed = lookUp("closed") {
            phone.post("/lookup", "artist" to wildRow.text("artist"), "title" to wildRow.text("title"),
                       "ug" to wildRow.text("ug"))
        }
        assertEquals(setOf("301"), asked.getValue("closed").filter { it.text("url") in wild.tabs }
            .map { it.text("status") }.toSet(), "its page's redirect: ${asked["closed"]}")
        assertTrue(keptFiles(phone, wild.found.key).none { it.startsWith("sheet") }, "no sheet kept for it")
        assertEquals("accept" to 0L, phone.database.read { db ->
            db.one("SELECT match_decision, ug_dirty FROM songs WHERE key = ?", wild.found.key) {
                it.text(0) to it.long(1)
            }
        }, "matched, and checked as the computer checks it: ${closed.asJson()}")

        // Get it on a song Ultimate Guitar answers 403 for: a block, Ultimate Guitar cooling on the phone.
        val blocked = lookups.song("blocked")
        val row = searchRow(phone, blocked.search!!)
        val stopped = lookUp("blocked") {
            phone.post("/lookup", "artist" to row.text("artist"), "title" to row.text("title"), "ug" to row.text("ug"))
        }
        assertTrue(asked.getValue("blocked").any { it.text("status") == "403" }, "UG's 403: ${asked["blocked"]}")
        assertTrue(phone.database.read { db -> Health.isCooling(db, "ug", Instant.now()) },
                   "a 403 cools Ultimate Guitar down on the phone")
        assertTrue(keptFiles(phone, blocked.found.key).none { it.startsWith("sheet") }, "no sheet kept for it")
        neverAMiss(phone, blocked.found.key, stopped)
        assertEquals(1L, phone.database.read { db ->
            db.one("SELECT ug_dirty FROM songs WHERE key = ?", blocked.found.key) { it.long(0) }
        }, "the blocked song waits for Ultimate Guitar again")

        // The limits: each lookup's to each site, the hour's together; no closed URL; every URL one the scenario
        // answers; no other host.
        for ((name, requests) in asked) {
            for ((provider, n) in FakeSites.byProvider(requests)) {
                assertTrue(n <= lookups.requests(provider), "$name sent $provider $n requests: $requests")
            }
        }
        val every = fake.log(started)
        for ((provider, n) in FakeSites.byProvider(every)) {
            assertTrue(n <= lookups.perHour(provider), "the lookups sent $provider $n requests in the hour")
        }
        assertEquals(emptyList(), every.filter { it.text("closed") == "true" }, "no URL robots.txt closes")
        assertEquals(emptyList(), every.filter { it.text("url") in wild.closed }, "the redirect to one, not followed")
        assertEquals(emptyList(), every.filter { it.text("known") != "true" },
                     "every URL the phone asked is one the scenario answers")
        assertEquals(emptyList(), every.filter { it.text("provider").isEmpty() }, "no host but the sites'")
        assertEquals(setOf(fake.hostPort), Requests.hosts.toSet(), "no request to any host but the fake sites'")
        assertTrue(Requests.paths.all { it == "/fetch" }, "${Requests.paths}")
        assertEquals(every.size, Requests.count, "every request the phone sent is one the fake sites counted")

        // Get it's song's pages, the phone's own (its lookups' pdf stage): phase 6 takes it from the computer, which
        // looks it up meanwhile and renders it, and the mirror's pages of it then serve in their place, the phone's
        // forgotten.
        val minstrelPages = ownPages(phone, minstrel.key)
        assertTrue("sheet.html" in minstrelPages, "the phone made its sheet's page: $minstrelPages")

        val looked = listOf(getIt.found, fetchNow, rose.song, chinese.found, harmonica.found, wild.found, blocked.found)
        buildJsonObject {
            put("sites", every.size)
            put("asked", JsonObject(asked.mapValues { (_, requests) ->
                JsonObject(FakeSites.byProvider(requests).mapValues { JsonPrimitive(it.value) })
            }))
            put("urls", JsonObject(asked.mapValues { (_, requests) ->
                JsonArray(requests.map { it["url"]!! })
            }))
            put("lines", JsonObject(lines))
            put("added", JsonArray(looked.map { song ->
                buildJsonObject { put("artist", song.artist); put("title", song.title); put("key", song.key) }
            }))
            put("reads", JsonArray(reads.map(::JsonPrimitive)))
            put("pages", JsonObject(mapOf("chinese" to chinese.found, "harmonica" to harmonica.found).mapValues { (role, song) ->
                buildJsonObject {
                    put("key", song.key)
                    put("files", JsonObject(pages.getValue(role).mapValues { JsonPrimitive(it.value) }))
                }
            }))
            put("progression", playing)
            put("superseded", buildJsonObject {
                put("key", minstrel.key)
                put("files", JsonObject(minstrelPages.mapValues { JsonPrimitive(it.value) }))
            })
        }
    }

    @Test fun phase6_theNextSyncGivesTheComputerThePhonesLookupsAndTakesItsSettings() = phase(6) { phone, scenario ->
        val five = read(File(phone.home, "phase-5.json"))
        val looked = five["added"]!!.jsonArray.map { it.jsonObject.text("key") }
        val both = scenario.lookups.song("get_it").found  // looked up on the computer too, meanwhile
        val noted = noted(phone)
        assertEquals(five["reads"]!!.jsonArray.map { it.jsonPrimitive.content }, noted, "the reads phase 5 noted")
        assertTrue(noted.isNotEmpty(), "phase 5 noted the index pages it read")

        val compared = compare(phone)
        val expected = looked.associate { key -> "song/$key" to if (key == both.key) "conflict" else "mine" }
        assertEquals(expected, compared.proposals, "the phone's lookups, one looked up on both sides")
        val conflicts = compared.proposals.filterValues { it == "conflict" }.keys.sorted()
        val differ = conflicts.associateWith { unit ->
            val mine = phone.database.read { db -> Units.document(db, phone.libraryDir, unit) }
            val theirs = phone.peer().unit(unit)
            JsonArray(differences(mine ?: JsonObject(emptyMap()), theirs ?: JsonObject(emptyMap()), "").map(::JsonPrimitive))
        }

        val job = apply(phone, compared, "there\t${both.unit}")
        assertStages(phone, job, SyncEngine.COMPARE to DONE, SyncEngine.TAKE to DONE, SyncEngine.GIVE to DONE,
                     SyncEngine.MIRROR to DONE, SyncEngine.AGREE to DONE)
        val outcome = outcome(phone, job)
        assertEquals(setOf(both.unit), units(outcome, "taken"), "$outcome")
        assertEquals(looked.filter { it != both.key }.map { "song/$it" }.toSet(), units(outcome, "given"), "$outcome")
        assertEquals(JsonArray(emptyList()), outcome["left"], "nothing left: $outcome")

        // The computer's settings, taken; nothing of its politeness, nor of the phone's, crossed.
        val config = phone.database.read { db -> PhoneConfig.read(db) }
        val said = scenario.settings
        assertEquals(said["match"]!!.jsonObject.text("accept").toDouble(), config.match.accept, "[match] accept")
        assertEquals(said["providers"]!!.jsonObject["megalobiz"]!!.jsonObject.text("lookup_requests").toInt(),
                     config.providers.getValue("megalobiz").lookupRequests, "megalobiz's lookup_requests")
        assertTrue(phone.database.read { db -> Health.isCooling(db, "ug", Instant.now()) },
                   "Ultimate Guitar still cooling on the phone: no cooldown crosses")
        // The index pages the phone read, pushed: none noted is left.
        assertEquals(emptyList(), noted(phone), "every index page the phone read, pushed")

        val gate = PhoneGate(phone.database)
        for (page in phone.mirror.manifest()!!.entries.filter { it.unit != null }) {
            assertEquals(Gate.SERVE, gate.check(page.unit!!, page.digest), page.path)
        }
        // The song taken from the computer, which rendered it as it looked it up: the mirror's pages of it serve, at
        // the unit's digest the take moved it to, and the pages the phone made of it in phase 5 are forgotten, their
        // record and their files (PhoneRender.afterSync).
        val superseded = five["superseded"]!!.jsonObject
        assertEquals(both.key, superseded.text("key"), "phase 5's Get it is the song looked up on both sides")
        mirrorsInPlaceOfOwn(phone, both.key, superseded["files"]!!.jsonObject)
        // The pages the phone made of the songs it gave, still its own, as it wrote them: the songs given as they
        // were, so the computer's pages of them (the mirror's now) supersede none.
        for ((role, made) in five["pages"]!!.jsonObject) {
            val key = made.jsonObject.text("key")
            assertEquals(made.jsonObject["files"]!!.jsonObject.mapValues { it.value.jsonPrimitive.content },
                         ownPages(phone, key), "$role: the phone's own pages after the sync")
        }
        write(File(phone.home, "phone-state.json"), buildJsonObject {
            put("units", JsonObject(phone.units().toSortedMap().mapValues { (_, unit) -> stateOf(unit) }))
        })
        buildJsonObject {
            put("conflicts", conflicts.size)
            put("differ", JsonObject(differ))
            put("taken", outcome["taken"] ?: JsonNull)
            put("given", outcome["given"] ?: JsonNull)
            put("settings", phone.database.read { db -> db.kvGet(PhoneConfig.SETTINGS_KV) }
                ?.let { Json.parseToJsonElement(it) } ?: JsonNull)
            put("reads", JsonArray(noted.map(::JsonPrimitive)))
        }
    }

    /** A new build of the app (PhoneRender's build stamp another): the render job makes the pages owed again over the
     * scenario's library, a lookup queued as it starts runs between two songs, before the job ends, and the phone's
     * own pages of phase 5's songs, which the mirror holds the computer's of now, are forgotten for the mirror's; how
     * long it took is written for the report (milestone 5's check). Every site refused: the lookup's sites fail,
     * never a miss. */
    @Test fun phase7_aNewBuildMakesThePagesAgainAndALookupQueuedMeanwhileRunsBetweenTwoSongs() {
        var phone: ScenarioPhone? = null
        var lookup: Int? = null
        val said = mutableListOf<String>()
        var song: Song? = null
        val newBuild: (PhoneDeps) -> PhoneRender = { deps ->
            object : PhoneRender(deps.database, deps.libraryDir, deps.mirror, deps.version) {
                private val stamp = "e2e-new-build-${System.nanoTime()}"
                override fun build(): String = stamp
                override fun renderStale(between: () -> Unit, progress: (done: Int, total: Int) -> Unit): RenderStats =
                    super.renderStale(between = {
                        val queue = phone!!.phone.queue
                        if (lookup == null) {
                            val looked = song!!
                            lookup = queue.submit(JobSpec("Look it up", looked.key, "song", emptyList(),
                                                          commands = JobCommands.lookupSteps(looked.artist, looked.title)))
                                .first.id
                        }
                        between()
                        said += "between: the lookup ${queue.snapshot().first { it.id == lookup }.state}"
                    }) { done, total ->
                        said += "$done of $total"
                        progress(done, total)
                    }
            }
        }
        phase(7, newBuild) { scenarioPhone, scenario ->
            phone = scenarioPhone
            val five = read(File(scenarioPhone.home, "phase-5.json"))
            song = scenario.lookups.song("get_it").found
            val render = scenarioPhone.phone.render
            assertTrue(render.stale(), "a new build owes the pages again")
            val started = System.nanoTime()
            val job = scenarioPhone.phone.renderAgain()
            val over = scenarioPhone.await(job.id)
            val seconds = (System.nanoTime() - started) / 1e9
            assertEquals(DONE, over.state, "${over.stages.single().detail}: $said")
            val looked = scenarioPhone.await(lookup ?: fail("no lookup queued: the job had one song at most: $said"))
            assertEquals(DONE, looked.state, looked.asJson().toString())
            val betweens = said.filter { it.startsWith("between: ") }
            assertTrue(betweens.isNotEmpty() && betweens.all { it == "between: the lookup $DONE" },
                       "the lookup ran at the first song's end, before the job's next: $said")
            assertTrue(said.indexOf(betweens.first()) < said.size - 1, "and before the job ended: $said")
            assertTrue(!render.stale(), "the pages made at the new build")
            // Phase 5's songs, which the phone gave and the computer took and rendered: the mirror holds the
            // computer's pages of them at their units' digests, so the pass forgets the phone's own, the mirror's
            // serving in their place (PhoneRender: a song the mirror serves gets its progressions, script and
            // info.json alone).
            for ((_, made) in five["pages"]!!.jsonObject) {
                mirrorsInPlaceOfOwn(scenarioPhone, made.jsonObject.text("key"), made.jsonObject["files"]!!.jsonObject)
            }
            val total = said.last { !it.startsWith("between: ") }.substringAfter(" of ").toInt()
            // And the whole library's pages made by the phone itself, as on a phone that holds none of the
            // computer's (no mirror): every song with a sheet a pass that writes its pages, timed too.
            val alone = PhoneRender(scenarioPhone.database, scenarioPhone.libraryDir, null, "e2e-alone")
            val whole = System.nanoTime()
            val made = alone.renderStale(between = {})
            val wholeSeconds = (System.nanoTime() - whole) / 1e9
            assertEquals(emptyMap(), made.failed, "every song's pages made")
            assertTrue(made.written > 0, "the phone wrote pages: $made")
            buildJsonObject {
                put("seconds", seconds)
                put("songs", total)
                put("detail", over.stages.single().detail)
                put("alone", buildJsonObject {
                    put("seconds", wholeSeconds)
                    put("written", made.written)
                    put("unchanged", made.unchanged)
                })
                put("progress", JsonArray(said.map(::JsonPrimitive)))
            }
        }
    }

    /**
     * Milestone 6's changes, each made on the phone through its own route as the page or the share sheet makes it,
     * then given to the computer at the next sync (the Sync tab's compare and apply): a songbook made, a song's key
     * set in it, a song moved and the songbook renamed (SongbookRoutes), its songbook.html the phone's own and served;
     * a song asked for that the index matches only uncertainly, its review answered with a candidate (ReviewRoutes);
     * a version kept beside a sheet (VersionsRoutes' Keep it, one tab page from the fake sites); a version made a
     * song's own (Export PDF's `mine=1`, ExportRoutes); and a Guitar Pro file shared to the app, filed for its song
     * (InboxShare, the inbox runner). The comparison lists each change's unit as the phone's and nothing else; the
     * apply gives them all and leaves nothing; what each change is, for tests/test_android_e2e.py's step 13 to read
     * back on the computer, and the phone's units, are written.
     */
    @Test fun phase8_theSongbooksVersionsReviewAndFilesMadeOnThePhoneReachTheComputer() = phase(8) { phone, scenario ->
        assertNotNull(sites, "phase 8 keeps a version from the fake sites (-Pcaracole.e2e.sites)")
        val changed = scenario.changed.values.flatten().toSet()
        val taken = setOf(scenario.r.key, scenario.c1.key, scenario.c2.key)
        val guitars = phone.database.read { db ->
            db.query("SELECT DISTINCT songs.key FROM files JOIN songs ON songs.id = files.song_id " +
                         "WHERE files.name LIKE 'guitar-%'") { it.text(0)!! }
        }.toSet()
        // The computer's songs no change of the goal's touched, each with the computer's sheet viewer mirrored.
        val sheets = phone.mirror.manifest()!!.entries.filter { it.path.endsWith("/sheet.html") && it.unit != null }
            .associateBy { it.unit!! }
        val plain = scenario.songs.filter { it.key !in changed && it.key !in taken && it.key !in guitars &&
                                                it.unit in sheets }
        assertTrue(plain.size >= 4, "four songs of the computer's to change: $plain")
        val (first, second, mine, shared) = plain.take(4).map { songOf(phone, it) }
        fun display(song: Song) = phone.database.read { db -> Songs.byKey(db, song.key)!!.display }

        // A song asked for by a name the index matches only uncertainly (its title a part of the index's), looked up:
        // a review, its candidates the index's; answered with the first of them, and matched again by it.
        val loose = Song(scenario.lookups.song("fetch_now").song.artist, "Stilly Night", "")
        val asked = done(phone.await(phone.jobOf(phone.post("/request", "artist" to loose.artist,
                                                            "title" to loose.title, "fetch" to "1"))))
        val reviewed = phone.database.read { db ->
            db.query("SELECT key FROM songs WHERE artist = ? AND title = ?", loose.artist, loose.title) { it.text(0)!! }
        }.singleOrNull() ?: fail("no song ${loose.artist} - ${loose.title}: ${asked.asJson()}")
        val inReview = phone.database.read { db -> Songs.byKey(db, reviewed)!! }
        assertTrue(inReview.review, "an uncertain match is a review: ${inReview.matchDecision} ${asked.asJson()}")
        val refs = phone.database.read { db -> Review.choices(db, inReview) }.map { it.text("ref") }
        assertTrue(refs.isNotEmpty(), "the review's candidates")
        val pick = refs.first()
        done(phone.await(phone.jobOf(phone.post("/review", "song" to "${inReview.id}", "pick" to pick,
                                                "shown" to refs.joinToString(" ")))))
        val answered = phone.database.read { db -> Songs.byKey(db, reviewed)!! }
        assertFalse(answered.review, "the review answered: ${answered.matchDecision}")
        assertEquals(pick, "${answered.matchArtistKey}/${answered.matchSongKey}", "matched by the pick")

        // A songbook made of two songs, one's key set in it, the other moved first, and renamed.
        val made = "From the phone"
        val named = "Phone set"
        val ids = listOf(first, second).map { idOf(phone, it.key) }
        done(phone.await(phone.jobOf(phone.post("/songbook/make", "name" to made, "songs" to ids.joinToString(",")))))
        done(phone.await(phone.jobOf(phone.post("/songbook/set", "name" to made, "song" to display(first),
                                                "key" to "D"))))
        done(phone.await(phone.jobOf(phone.post("/songbook/move", "name" to made, "song" to display(second),
                                                "position" to "1"))))
        done(phone.await(phone.jobOf(phone.post("/songbook/rename", "name" to made, "new" to named))))
        val books = phone.database.read { db ->
            db.query("SELECT name FROM phone_songbooks ORDER BY position") { it.text(0)!! }
        }
        assertTrue(named in books && made !in books, "the songbook renamed: $books")
        val page = File(phone.libraryDir, "_songbooks/$named/songbook.html")
        assertTrue(page.isFile, "the phone made the songbook's page: $page")
        val served = phone.get("/" + quotePath("_songbooks/$named/songbook.html"))
        assertEquals(200, served.status, served.text.take(1000))
        assertTrue(served.header("content-type").orEmpty().startsWith("text/html"), "${served.header("content-type")}")
        assertTrue(served.bytes.contentEquals(page.readBytes()), "the songbook's page served as the phone wrote it")

        // Keep it: a version of a sheet not kept beside it yet, one tab page from the fake sites (a page of theirs).
        // Ultimate Guitar cools on the phone since phase 5's 403: that cooldown over, as a day on would leave it.
        phone.database.writeBlocking { db -> db.kvDelete("provider:ug") }
        val theirs = listOf("get_it", "fetch_now", "chinese", "harmonica")
            .flatMap { scenario.lookups.song(it).tabs }.toSet()
        val (kept, tab) = phone.database.read { db ->
            val rank = PhoneConfig.read(db).rank
            db.query("SELECT DISTINCT song_id FROM versions WHERE provider = 'ug' ORDER BY song_id") { it.long(0)!! }
                .firstNotNullOfOrNull { id ->
                    SheetVersions.mayKeep(db, id, SheetVersions.inLibrary(db, id, rank), emptyList())
                        .firstOrNull { it.url in theirs }
                        ?.let { Songs.byId(db, id)!!.key to it.tabId }
                }
        } ?: fail("no song with a version left to keep")
        val keep = done(phone.await(phone.jobOf(phone.post("/versions/keep", "song" to "${idOf(phone, kept)}",
                                                           "tab" to tab))))
        assertTrue("version-$tab.txt" in keptFiles(phone, kept), "version $tab kept: ${keep.asJson()}")

        // Make this my version: Export PDF's link with mine=1, on the computer's viewer the mirror serves.
        val viewer = sheets.getValue(mine.unit).path
        val export = phone.get("/export.pdf?sheet=" + quote(viewer) + "&t=2&mine=1")
        assertEquals(200, export.status, export.text.take(1000))
        val making = phone.phone.queue.snapshot().single { it.key.startsWith("export:${mine.key}:") }
        done(phone.await(making.id))
        val version = phone.database.read { db ->
            db.one("SELECT value FROM phone_overrides WHERE tbl = 'version' AND key = ?", mine.key) { it.text(0)!! }
        } ?: fail("no [version] of ${mine.key} written")

        // A Guitar Pro file shared to the app, named for its song: filed as the song's guitar-N.
        val gp = phone.database.read { db ->
            db.one("SELECT path FROM files WHERE name LIKE 'guitar-%.gp' ORDER BY path LIMIT 1") { it.text(0)!! }
        } ?: fail("no Guitar Pro file on the phone to share")
        val bytes = File(phone.libraryDir, gp).readBytes()
        val share = InboxShare.share(phone.phone.parts, "${display(shared)}.gp", "application/octet-stream", bytes)
        val filing = done(phone.await((share.job ?: fail("not queued: ${share.said}")).id))
        val filed = keptFiles(phone, shared.key).filter { it.startsWith("guitar-") }
        assertEquals(listOf("guitar-1.gp"), filed, "filed for ${shared.key}: ${filing.asJson()}")

        // The next sync: every change the phone's, given; nothing else differs.
        val units = setOf("songbook/" + Songbooks.nameKey(named), "song/$reviewed", "song/$kept", mine.unit, shared.unit)
        val compared = compare(phone)
        assertEquals(units.associateWith { "mine" }, compared.proposals)
        val job = apply(phone, compared, "")
        assertStages(phone, job, SyncEngine.COMPARE to DONE, SyncEngine.TAKE to SKIPPED, SyncEngine.GIVE to DONE,
                     SyncEngine.MIRROR to DONE, SyncEngine.AGREE to DONE)
        val outcome = outcome(phone, job)
        assertEquals(units, units(outcome, "given"), "$outcome")
        assertEquals(JsonArray(emptyList()), outcome["left"], "nothing left: $outcome")
        assertEquals(emptyMap(), compare(phone).proposals, "a comparison after finds nothing")

        write(File(phone.home, "phone-state.json"), buildJsonObject {
            put("units", JsonObject(phone.units().toSortedMap().mapValues { (_, unit) -> stateOf(unit) }))
        })
        buildJsonObject {
            put("songbook", buildJsonObject {
                put("name", named)
                put("songs", JsonArray(listOf(second, first).map { JsonPrimitive(display(it)) }))
                put("set", display(first))
                put("key", "D")
            })
            put("review", buildJsonObject { put("key", reviewed); put("pick", pick) })
            put("kept", buildJsonObject { put("key", kept); put("tab", tab) })
            put("mine", buildJsonObject { put("key", mine.key); put("version", Json.parseToJsonElement(version)) })
            put("guitar", buildJsonObject {
                put("key", shared.key)
                put("name", filed.single())
                put("sha256", sha256(bytes))
            })
            put("given", outcome["given"] ?: JsonNull)
        }
    }

    /**
     * The round (the integration's scenario), the computer off and the fake sites up: Get it on the rows of two songs
     * new to both sides (the fake sites' `round_play` and `round_book`), each its sheet and its pages the phone's own,
     * the first's other version kept beside its sheet; the first played from its card (its sheet.html the phone's, no
     * page of the mirror's of it); a songbook made of both, the second's key set in it; the first made the song's own
     * version (Export PDF's `mine=1` on the phone's own viewer); a Guitar Pro file shared to the second, filed for it;
     * and a backup made by hand, holding both songs, the songbook, the version and the file. Each lookup within its
     * limits, no URL robots.txt closes, every URL one the scenario answers. Its pages, as they are once every change
     * made them again, and what each change is, are written for tests/test_android_e2e.py's step 14, which holds the
     * pages to Python's byte for byte once phase 10 gave the computer the round.
     */
    @Test fun phase9_theRoundThePhoneAloneLooksUpPlaysMakesASongbookAVersionAFileAndABackup() = phase(9) { phone, scenario ->
        val fake = FakeSites(sites ?: fail("phase 9 looks songs up against the fake sites (-Pcaracole.e2e.sites)"))
        val computer = URI(phone.server)
        assertFailsWith<ConnectException>("the computer is off") {
            Socket().use { it.connect(InetSocketAddress(computer.host, computer.port), 5_000) }
        }
        assertFalse(phone.database.read { db -> Health.isCooling(db, "ug", Instant.now()) },
                    "Ultimate Guitar isn't cooling on the phone (phase 8 ended phase 5's cooldown)")
        val lookups = scenario.lookups
        val started = fake.count()
        val asked = LinkedHashMap<String, List<JsonObject>>()
        val round = ROUND.map { lookups.song(it) }
        val (played, booked) = round.map { site ->
            val row = searchRow(phone, site.search!!)
            val before = fake.count()
            val job = done(phone.await(phone.jobOf(phone.post("/lookup", "artist" to row.text("artist"),
                                                              "title" to row.text("title"), "ug" to row.text("ug")))))
            asked[site.found.key] = fake.log(before)
            for (stage in listOf("song", "match", "sheet", "pdf", "pages")) assertStage(job, stage, DONE)
            val song = songOf(phone, site.found)
            assertTrue("Made-up words" in keptSheet(phone, song.key), "${song.key}: the chart the fake sites gave")
            song
        }
        val beside = round[0].tabs.drop(1).map { "version-${it.substringAfterLast('-')}.txt" }
        assertEquals(beside, keptVersions(phone, played.key), "its other version kept beside its sheet")
        assertEquals("found", lyricsStatus(phone, booked.key), "LRCLIB's lyrics kept")
        fun display(song: Song) = phone.database.read { db -> Songs.byKey(db, song.key)!!.display }

        // Played: its card's sheet viewer, the phone's own page (the mirror holds none of a song new to both sides).
        assertTrue(phone.mirror.manifest()?.entries.orEmpty().none { it.unit == played.unit },
                   "the mirror holds no page of ${played.key}")
        val card = pageData(phone)["songs"]!!.jsonArray.map { it.jsonObject }
            .firstOrNull { it.text("identity") == played.key } ?: fail("no card of ${played.key} on the library page")
        val viewer = card["files"]!!.jsonArray.map { it.jsonObject }.firstOrNull { it.text("name") == "sheet.html" }
            ?: fail("its card opens no sheet.html: $card")
        val shown = phone.get("/" + viewer.text("href"))
        assertEquals(200, shown.status, "${viewer.text("href")}: ${shown.text.take(500)}")
        assertTrue(shown.header("content-type").orEmpty().startsWith("text/html"), "${shown.header("content-type")}")
        assertTrue(shown.bytes.contentEquals(ownFile(phone, played.key, "sheet.html").readBytes()),
                   "its sheet.html served as the phone wrote it")
        ownPages(phone, played.key)

        // A songbook of both, the second's key set in it.
        val book = "Round"
        val ids = listOf(played, booked).map { idOf(phone, it.key) }
        done(phone.await(phone.jobOf(phone.post("/songbook/make", "name" to book, "songs" to ids.joinToString(",")))))
        done(phone.await(phone.jobOf(phone.post("/songbook/set", "name" to book, "song" to display(booked),
                                                "key" to "E"))))
        val page = File(phone.libraryDir, "_songbooks/$book/songbook.html")
        assertTrue(page.isFile, "the phone made the songbook's page: $page")

        // The first made the song's own version: Export PDF's link with mine=1, on the phone's own viewer.
        val sheetPath = ownFile(phone, played.key, "sheet.html").relativeTo(phone.libraryDir).invariantSeparatorsPath
        val export = phone.get("/export.pdf?sheet=" + quote(sheetPath) + "&t=3&mine=1")
        assertEquals(200, export.status, export.text.take(1000))
        val making = phone.phone.queue.snapshot().single { it.key.startsWith("export:${played.key}:") }
        done(phone.await(making.id))
        val version = phone.database.read { db ->
            db.one("SELECT value FROM phone_overrides WHERE tbl = 'version' AND key = ?", played.key) { it.text(0)!! }
        } ?: fail("no [version] of ${played.key} written")

        // A Guitar Pro file shared to the app, named for the second: filed as its guitar-1.
        val gp = phone.database.read { db ->
            db.one("SELECT path FROM files WHERE name LIKE 'guitar-%.gp' ORDER BY path LIMIT 1") { it.text(0)!! }
        } ?: fail("no Guitar Pro file on the phone to share")
        val bytes = File(phone.libraryDir, gp).readBytes()
        val share = InboxShare.share(phone.phone.parts, "${display(booked)}.gp", "application/octet-stream", bytes)
        val filing = done(phone.await((share.job ?: fail("not queued: ${share.said}")).id))
        val filed = keptFiles(phone, booked.key).filter { it.startsWith("guitar-") }
        assertEquals(listOf("guitar-1.gp"), filed, "filed for ${booked.key}: ${filing.asJson()}")

        // Backed up by hand, as Settings' Backups' Back up now queues it.
        val backing = phone.phone.queue.submit(BackupRunner(phone.phone.parts).backup(Backups.BY_HAND)).first
        done(phone.await(backing.id))
        val backup = Backups.list(phone.stateDir).firstOrNull { it.label == Backups.BY_HAND }
            ?: fail("no backup made by hand: ${Backups.list(phone.stateDir)}")
        assertEquals(0, backup.missing, "the backup holds every kept file: $backup")

        // The round's lookups, each within its limits; no URL robots.txt closes, every one the scenario answers.
        for ((name, requests) in asked) {
            assertTrue(requests.isNotEmpty(), "$name asked no site")
            for ((provider, n) in FakeSites.byProvider(requests)) {
                assertTrue(n <= lookups.requests(provider), "$name sent $provider $n requests: $requests")
            }
        }
        val every = fake.log(started)
        assertEquals(emptyList(), every.filter { it.text("closed") == "true" }, "no URL robots.txt closes")
        assertEquals(emptyList(), every.filter { it.text("known") != "true" }, "every URL one the scenario answers")
        assertEquals(setOf(fake.hostPort), Requests.hosts.toSet(), "no request to any host but the fake sites'")
        assertEquals(every.size, Requests.count, "every request the phone sent is one the fake sites counted")

        // The pages, once every change made them again: each the phone's own, at its song unit's digest now.
        val pages = listOf(played, booked).associate { it.key to ownPages(phone, it.key) }
        assertTrue(pages.getValue(played.key).keys.containsAll(listOf("sheet.html", "sheet.cho") +
                                                                   beside.map { it.removeSuffix(".txt") + ".html" }),
                   "${pages[played.key]}")
        val guitar = pageData(ownFile(phone, booked.key, "sheet.html").readText(), "song")["guitar"]
        assertEquals(listOf("guitar-1.gp"), guitar?.jsonArray?.map { it.jsonPrimitive.content },
                     "the second's viewer names the file shared to it")
        buildJsonObject {
            put("play", buildJsonObject {
                put("key", played.key); put("display", display(played)); put("version", Json.parseToJsonElement(version))
            })
            put("book", buildJsonObject { put("key", booked.key); put("display", display(booked)) })
            put("songbook", buildJsonObject {
                put("name", book)
                put("songs", JsonArray(listOf(played, booked).map { JsonPrimitive(display(it)) }))
                put("set", display(booked))
                put("key", "E")
            })
            put("guitar", buildJsonObject {
                put("key", booked.key); put("name", filed.single()); put("sha256", sha256(bytes))
            })
            put("backup", buildJsonObject { put("name", backup.file.name); put("label", backup.label) })
            put("pages", JsonObject(pages.mapValues { (_, files) -> JsonObject(files.mapValues { JsonPrimitive(it.value) }) }))
            put("sites", every.size)
            put("asked", JsonObject(asked.mapValues { (_, requests) ->
                JsonObject(FakeSites.byProvider(requests).mapValues { JsonPrimitive(it.value) })
            }))
        }
    }

    /**
     * The round's end, the computer back: one sync. The comparison lists the round's units (its two songs and the
     * songbook) as the phone's and nothing else; the apply gives them, takes nothing and leaves nothing, and a
     * comparison after finds nothing; the pages the phone made of the round still its own, as phase 9 wrote them; the
     * phone's units written for the Python side, which holds them to the computer's, unit for unit.
     */
    @Test fun phase10_theComputerBackOneSyncGivesTheRoundAndBothSidesAgree() = phase(10) { phone, _ ->
        val nine = read(File(phone.home, "phase-9.json"))
        val keys = listOf("play", "book").map { nine[it]!!.jsonObject.text("key") }
        val units = keys.map { "song/$it" }.toSet() + ("songbook/" + Songbooks.nameKey(nine["songbook"]!!.jsonObject.text("name")))
        val compared = compare(phone)
        assertEquals(units.associateWith { "mine" }, compared.proposals, "the round's units, the phone's, and no other")
        val job = apply(phone, compared, "")
        assertStages(phone, job, SyncEngine.COMPARE to DONE, SyncEngine.TAKE to SKIPPED, SyncEngine.GIVE to DONE,
                     SyncEngine.MIRROR to DONE, SyncEngine.AGREE to DONE)
        val outcome = outcome(phone, job)
        assertEquals(units, units(outcome, "given"), "$outcome")
        assertEquals(emptySet(), units(outcome, "taken"), "$outcome")
        assertEquals(JsonArray(emptyList()), outcome["left"], "nothing left: $outcome")
        assertEquals(emptyMap(), compare(phone).proposals, "a comparison after finds nothing")
        for ((key, files) in nine["pages"]!!.jsonObject) {
            assertEquals(files.jsonObject.mapValues { it.value.jsonPrimitive.content }, ownPages(phone, key),
                         "$key: the phone's own pages after the sync")
        }
        write(File(phone.home, "phone-state.json"), buildJsonObject {
            put("units", JsonObject(phone.units().toSortedMap().mapValues { (_, unit) -> stateOf(unit) }))
        })
        buildJsonObject { put("given", outcome["given"] ?: JsonNull) }
    }

    // --- the phases' plumbing ---------------------------------------------------------------------------------------

    private val phase: Int? = System.getProperty("caracole.e2e.phase")?.toIntOrNull()
    private val server: String? = System.getProperty("caracole.e2e.server")
    private val dir: File? = System.getProperty("caracole.e2e.dir")?.let(::File)
    private val sites: String? = System.getProperty("caracole.e2e.sites")

    /** Phase [n]'s [body], given the phone over DIR/phone/ and the scenario, if it is the phase asked for; what it
     * returns, and the requests the phone sent, written to DIR/phone/phase-N.json. */
    private fun phase(n: Int, render: ((PhoneDeps) -> PhoneRender)? = null, body: (ScenarioPhone, Scenario) -> JsonObject) {
        Assume.assumeTrue("phase $n alone, against a computer (-Pcaracole.e2e.phase, .server, .dir)",
                          phase == n && server != null && dir != null)
        val home = File(dir, "phone")
        if (n == 1) assertFalse(home.exists(), "phase 1 makes a new phone, and $home is there already")
        Requests.install()
        Requests.reset()
        val scenario = Scenario.read(dir!!)
        val result = ScenarioPhone(home, server!!, sites, render).use { phone -> body(phone, scenario) }
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

    /** The line the library page shows for request [id]: /jobs.json's view, its song's facts read (jobs_routes.view
     * on the phone), `{tone, text, link, details}`. */
    private fun shownLine(phone: ScenarioPhone, id: Int): JsonObject =
        phone.answer(phone.script("/jobs.json?jobs=$id"))["jobs"]!!.jsonArray.single().jsonObject["line"]!!.jsonObject

    /** A lookup whose every site refused (phase 2: the computer off, the phone's transport refusing them): its song
     * added, LRCLIB's stage failed, every site's failed or skipped (a lane's port still neutral), none a miss, and its
     * line the library page's, status.py's for a lookup no site answered ([NOT_FETCHED], never "Not found"). */
    private fun refusedLookup(phone: ScenarioPhone, job: Job) {
        assertEquals(listOf("get"), job.steps.map { it.args.first() }, job.spec.title)
        val stages = job.stages.associate { it.name to it }
        assertEquals(DONE, stages.getValue("song").state, "${job.spec.title}: ${job.asJson()}")
        assertEquals("failed", stages.getValue("lyrics").state, "${job.spec.title}: LRCLIB refused")
        for (site in listOf("ug", "lacuerda", "gtptabs", "harptabs", "gametabs")) {
            assertTrue(stages.getValue(site).state in setOf("failed", SKIPPED), "${job.spec.title}: $site ${job.asJson()}")
        }
        assertFalse(job.stages.any { "not found" in it.detail.lowercase() || "missing" in it.detail.lowercase() },
                    "a refused site is never a miss: ${job.asJson()}")
        val line = shownLine(phone, job.id)
        assertEquals(NOT_FETCHED, line.text("text"), "${job.spec.title}: $line")
        assertEquals("waiting", line.text("tone"), "${job.spec.title}: $line")
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

    /** The row /api/search's `index` gives for a song of the fake sites' scenario ([search]: its query and `ug`). */
    private fun searchRow(phone: ScenarioPhone, search: JsonObject): JsonObject {
        val found = phone.answer(phone.script("/api/search?q=" + quote(search.text("query"))))
        return found["index"]!!.jsonArray.map { it.jsonObject }.firstOrNull { it.text("ug") == search.text("ug") }
            ?: fail("/api/search finds no ${search.text("ug")}: $found")
    }

    private fun assertStage(job: Job, name: String, state: String) {
        val stage = job.stages.singleOrNull { it.name == name } ?: fail("no $name stage: ${job.asJson()}")
        assertEquals(state, stage.state, "${job.spec.title}'s $name stage (${stage.detail}): ${job.asJson()}")
    }

    /** The song of [song]'s key on the phone, as the library holds it. */
    private fun songOf(phone: ScenarioPhone, song: Song): Song = phone.database.read { db ->
        db.one("SELECT artist, title, key FROM songs WHERE key = ?", song.key) {
            Song(it.text(0)!!, it.text(1)!!, it.text(2)!!)
        }
    } ?: fail("no song ${song.key} on the phone")

    private fun idOf(phone: ScenarioPhone, key: String): Long =
        phone.database.read { db -> db.one("SELECT id FROM songs WHERE key = ?", key) { it.long(0)!! } }
            ?: fail("no song $key")

    /** The names of the files the phone keeps of the song of [key] (its `files`). */
    private fun keptFiles(phone: ScenarioPhone, key: String): List<String> = phone.database.read { db ->
        db.query("SELECT files.name FROM files JOIN songs ON songs.id = files.song_id WHERE songs.key = ? " +
                     "ORDER BY files.name", key) { it.text(0)!! }
    }

    /** A lookup whose site answered with an error (a block, a redirect robots.txt closes): never a miss, its song
     * neither not found by its match nor shown "Not found" (status.py's words for a miss), as
     * test_pipeline.py's test_ug_block_cools_down_and_never_marks_not_found holds the computer to. */
    private fun neverAMiss(phone: ScenarioPhone, key: String, job: Job) {
        val decision = phone.database.read { db ->
            db.one("SELECT match_decision FROM songs WHERE key = ?", key) { it.text(0) }
        }
        assertTrue(decision != "not_found", "$key, its match: $decision")
        val line = shownLine(phone, job.id)
        assertTrue(line.text("text") != NOT_FOUND && line.text("tone") != "missing", "$key's line: $line")
    }

    private fun lyricsStatus(phone: ScenarioPhone, key: String): String? = phone.database.read { db ->
        db.one("SELECT lyrics_status FROM songs WHERE key = ?", key) { it.text(0) }
    }

    /** The text of the file [name] the phone keeps of the song of [key], read from its library folder. */
    private fun keptFile(phone: ScenarioPhone, key: String, name: String): String {
        val path = phone.database.read { db ->
            db.one("SELECT files.path FROM files JOIN songs ON songs.id = files.song_id " +
                       "WHERE songs.key = ? AND files.name = ?", key, name) { it.text(0) }
        } ?: fail("no $name kept for $key: ${keptFiles(phone, key)}")
        return File(phone.libraryDir, path).readText()
    }

    private fun keptVersions(phone: ScenarioPhone, key: String): List<String> =
        keptFiles(phone, key).filter { it.startsWith("version-") && it.endsWith(".txt") }

    /** The song's folder in the phone's library, where its sheet.txt is kept (and its lyrics written beside it). */
    private fun songFolder(phone: ScenarioPhone, key: String): File {
        val path = phone.database.read { db ->
            db.one("SELECT files.path FROM files JOIN songs ON songs.id = files.song_id " +
                       "WHERE songs.key = ? AND files.name = 'sheet.txt'", key) { it.text(0) }
        } ?: fail("no sheet.txt kept for $key: ${keptFiles(phone, key)}")
        return File(phone.libraryDir, path).parentFile
    }

    /** The sheet.txt the phone keeps of the song of [key], read from its library folder. */
    private fun keptSheet(phone: ScenarioPhone, key: String): String = keptFile(phone, key, "sheet.txt")

    /** The song's card on the library page links its sheet.txt, and the link answers it, [sheet] whole. */
    private fun servedFromItsCard(phone: ScenarioPhone, key: String, sheet: String) {
        val card = pageData(phone)["songs"]!!.jsonArray.map { it.jsonObject }.firstOrNull { it.text("identity") == key }
            ?: fail("no card of $key on the library page")
        val file = card["files"]!!.jsonArray.map { it.jsonObject }.firstOrNull { it.text("name") == "sheet.txt" }
            ?: fail("its card links no sheet.txt: $card")
        val served = phone.get("/" + file.text("href"))
        assertEquals(200, served.status, "${file.text("href")}: ${served.text.take(500)}")
        assertTrue(served.header("content-type").orEmpty().startsWith("text/plain"), "${served.header("content-type")}")
        assertEquals(sheet, served.text, "the card's sheet.txt is the one kept")
    }

    /** The index pages the phone noted it read for the next push (core.index.Reads: `site:page`, in order). */
    private fun noted(phone: ScenarioPhone): List<String> = phone.database.read { db ->
        db.query("SELECT key FROM kv WHERE key >= ? AND key < ? ORDER BY key", Reads.READ, Reads.READ.dropLast(1) + ";") {
            it.text(0)!!.removePrefix(Reads.READ)
        }
    }

    /** Where two JSON documents differ, each place as a path (`versions[0].raw.votes`), in order. */
    private fun differences(a: JsonElement, b: JsonElement, at: String): List<String> = when {
        a is JsonObject && b is JsonObject -> (a.keys + b.keys).sorted().distinct().flatMap { k ->
            differences(a[k] ?: JsonNull, b[k] ?: JsonNull, if (at.isEmpty()) k else "$at.$k")
        }
        a is JsonArray && b is JsonArray && a.size == b.size -> a.indices.flatMap { i -> differences(a[i], b[i], "$at[$i]") }
        a == b -> emptyList()
        else -> listOf(at)
    }

    /** The library page's data, GET /'s `songs` block. */
    private fun pageData(phone: ScenarioPhone): JsonObject {
        val page = phone.get("/")
        assertEquals(200, page.status, page.text.take(1000))
        return pageData(page.text, "songs")
    }

    /** A page's JSON data block [name] (`<script type="application/json" id="NAME">`). */
    private fun pageData(page: String, name: String): JsonObject {
        val block = Regex("""<script type="application/json" id="$name">(.*?)</script>""", RegexOption.DOT_MATCHES_ALL)
            .find(page) ?: fail("no $name data in the page: ${page.take(500)}")
        return Json.parseToJsonElement(block.groupValues[1]).jsonObject
    }

    /**
     * The pages the phone made itself of the song of [key] (kv `render:files:<id>`, WrittenPages), by name, each
     * one's SHA-256: each written beside the song's kept files with the bytes its record says, made at the song
     * unit's digest now, and served as it wrote it (LibraryFiles: a link's GET of its path); its info.json written.
     */
    private fun ownPages(phone: ScenarioPhone, key: String): Map<String, String> {
        val id = idOf(phone, key)
        val folder = songFolder(phone, key)
        val (record, digest) = phone.database.read { db ->
            WrittenPages.record(db, id).keys.associateWith { WrittenPages.written(db, id, it)!! } to
                Units.digestOf(db, "song/$key")
        }
        assertTrue(record.isNotEmpty(), "the phone made no page of $key")
        assertTrue(File(folder, "info.json").isFile, "its info.json")
        for ((name, written) in record) {
            val file = File(folder, name)
            assertTrue(file.isFile, "$key's $name, recorded, is written")
            val bytes = file.readBytes()
            assertEquals(sha256(bytes) to bytes.size.toLong(), written.sha256 to written.size, "$key's $name record")
            assertEquals(digest, written.unitDigest, "$key's $name made at its unit's digest now")
            val path = file.relativeTo(phone.libraryDir).invariantSeparatorsPath
            val served = phone.get("/" + quotePath(path))
            assertEquals(200, served.status, "$path: ${served.text.take(500)}")
            assertTrue(served.bytes.contentEquals(bytes), "$path served as the phone wrote it")
        }
        return record.mapValues { it.value.sha256 }
    }

    /** The song of [key]'s pages are the mirror's now, at its unit's digest, each served as the mirror holds it, and
     * the phone's own of it (phase 5's [own], by name, each one's SHA-256) forgotten: no record left, each file
     * deleted. */
    private fun mirrorsInPlaceOfOwn(phone: ScenarioPhone, key: String, own: JsonObject) {
        val unit = "song/$key"
        val id = idOf(phone, key)
        val (record, digest) = phone.database.read { db -> WrittenPages.record(db, id) to Units.digestOf(db, unit) }
        assertEquals(emptySet(), record.keys, "$key: the phone's own pages, forgotten")
        val mirrored = phone.mirror.manifest()!!.entries.filter { it.unit == unit && it.isPage }
        assertTrue(mirrored.any { it.name == "sheet.html" }, "$key: the mirror holds the computer's sheet: $mirrored")
        for (entry in mirrored) {
            assertEquals(digest, entry.digest, "${entry.path}: the computer's page at the unit's digest now")
            val served = phone.get("/" + quotePath(entry.path))
            assertEquals(200, served.status, "${entry.path}: ${served.text.take(500)}")
            assertEquals(entry.sha256, sha256(served.bytes), "${entry.path}: the mirror's page served")
        }
        val folder = songFolder(phone, key)
        for ((name, sha) in own) {
            val file = File(folder, name)
            assertFalse(file.isFile && sha256(file.readBytes()) == sha.jsonPrimitive.content,
                        "$key: the phone's own $name is deleted")
        }
    }

    /** The file [name] in the folder of the song of [key] on the phone. */
    private fun ownFile(phone: ScenarioPhone, key: String, name: String): File = File(songFolder(phone, key), name)

    /**
     * What the song of [key] plays, as the phone recorded it rendering its sheet (kv `render:progressions:<id>`), and
     * /api/search's answer to its first section's progression typed: the progression read (`progression`), the song
     * one of those that play it, among the answer's songs of yours. The record, for the Python side.
     */
    private fun progressionFinds(phone: ScenarioPhone, key: String): JsonObject {
        val id = idOf(phone, key)
        val record = phone.database.read { db -> db.kvGet("${Progressions.KV}$id") }
            ?.let { Json.parseToJsonElement(it).jsonObject } ?: fail("no progressions recorded of $key")
        val typed = record["sections"]!!.jsonArray.first().jsonObject.text("key")
        val found = phone.answer(phone.script("/api/search?q=" + quote(typed)))
        val said = found["progression"] as? JsonObject ?: fail("/api/search reads no progression in \"$typed\": $found")
        assertTrue(said.text("songs").toInt() >= 1, "$said")
        assertTrue(found["library"]!!.jsonArray.any { it.jsonObject.text("id") == "$id" },
                   "/api/search's progression \"$typed\" finds $key: $found")
        return buildJsonObject { put("typed", typed); put("record", record); put("said", said) }
    }

    private fun sha256(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    private fun stateOf(unit: SyncUnit): JsonObject =
        buildJsonObject { put("label", unit.label); put("digest", unit.digest) }

    private fun read(file: File): JsonObject = Json.parseToJsonElement(file.readText()).jsonObject

    private fun write(file: File, json: JsonElement) =
        file.writeText(Json { prettyPrint = true }.encodeToString(JsonElement.serializer(), json) + "\n")

    private companion object {
        /** The fake sites' songs of the integration's round (tests/helpers/fake_sites.py's `ROUND`). */
        val ROUND = listOf("round_play", "round_book")

        const val DONE = "done"
        const val SKIPPED = "skipped"

        /** status.py's line for a song added, no site asked (phase 2's add). */
        const val ADDED = "Added: the nightly run looks for it"

        /** status.py's line for a lookup over that found no sheet and checked nothing (phase 2's, every site refused). */
        const val NOT_FETCHED = "Not fetched yet"

        /** status.py's line for a lookup that found its song nowhere: a miss, which an error never is. */
        const val NOT_FOUND = "Not found"
    }
}
