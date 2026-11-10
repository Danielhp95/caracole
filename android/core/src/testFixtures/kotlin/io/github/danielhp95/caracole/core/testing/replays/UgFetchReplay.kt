package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.Asking
import io.github.danielhp95.caracole.core.lookup.CommandContext
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.sites.UgStages
import io.github.danielhp95.caracole.core.lookup.sites.VersionsCommands
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.FakeAsking
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.ScenarioWorld
import io.github.danielhp95.caracole.core.testing.Scenarios
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.ug.ArtistRoute
import io.github.danielhp95.caracole.core.ug.FetchContext
import io.github.danielhp95.caracole.core.ug.SongFetchOutcome
import io.github.danielhp95.caracole.core.ug.UgFetch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.json.longOrNull
import java.nio.file.Files
import java.time.Instant

/**
 * UG's lookup path (vectors/lookup/ug_sheet.jsonl, ug_keep.jsonl, ug_artist.jsonl, commands_versions.jsonl;
 * tests/test_conformance_ug_fetch.py) replayed as Python recorded it: each record's passes of `UgFetch.processSong`
 * (or `keepVersion`s, or `VersionsCommands`' turns) in its world, the requests in order, the rows, kv and files
 * written, the events and the result compared (core.testing.Scenarios); and get.py's words for the two UG stages
 * (ug_sheet_stages.jsonl): what each says a pass did, and `_ug_ready`'s answer for a song. UgFetchSheetTest,
 * KeepVersionTest, ArtistRouteTest and VersionsCommandsTest call each part on the JVM; CorpusOnDeviceTest runs them
 * all under ART.
 *
 * The phone notes each artist page a store keeps tabs of for its next push to the computer (kv
 * `phone:read:ug:<page>`), which Python doesn't: an artist record's `noted` says which, checked and then left out of
 * the kv compared.
 */
object UgFetchReplay : AreaReplay {
    override val area = "ug-fetch"

    const val SHEET = "lookup/ug_sheet.jsonl"
    const val KEEP = "lookup/ug_keep.jsonl"
    const val ARTIST = "lookup/ug_artist.jsonl"
    const val VERSIONS = "lookup/commands_versions.jsonl"
    const val STAGES = "lookup/ug_sheet_stages.jsonl"

    override fun replay(misses: Misses) {
        sheet(misses)
        keep(misses)
        stages(misses)
        artist(misses)
        versions(misses)
    }

    /** The records of a vector, its header left out. */
    fun records(name: String): List<JsonObject> = Corpus.lines(name).filter { it["header"] != JsonPrimitive(true) }

    /** vectors/lookup/ug_sheet.jsonl: each pass of a record, `process_song` in turn through one client. */
    fun sheet(misses: Misses) {
        for (record in records(SHEET)) {
            val kw = record.getValue("kw").jsonObject
            val song = kw.getValue("song").jsonPrimitive.long
            Scenarios.replay(record, misses) { world ->
                kw.getValue("passes").jsonArray.map { spec ->
                    val pass = spec.jsonObject
                    outcome(UgFetch.processSong(context(world, pass), Songs.byId(world.db, song)!!,
                                                guitar = pass.getValue("guitar").jsonPrimitive.boolean))
                }
            }
        }
    }

    /** vectors/lookup/ug_keep.jsonl: `keep_version` of each tab in turn, each with a context of its own. */
    fun keep(misses: Misses) {
        for (record in records(KEEP)) {
            val kw = record.getValue("kw").jsonObject
            val song = kw.getValue("song").jsonPrimitive.long
            val pass = kw.getValue("pass").jsonObject
            Scenarios.replay(record, misses) { world ->
                kw.getValue("tabs").jsonArray.map { tab ->
                    UgFetch.keepVersion(context(world, pass), Songs.byId(world.db, song)!!, tab.jsonPrimitive.long)
                }
            }
        }
    }

    /**
     * vectors/lookup/ug_sheet_stages.jsonl: the sheet stage's words (`_sheet_from_ug`, `[state, detail]`) and the ug
     * stage's (`ug`) for a pass that came to the record's outcome, and `_ug_ready`'s answer for its song over its
     * index, kv and overrides.
     */
    fun stages(misses: Misses) {
        for (record in records(STAGES)) {
            val case = record.getValue("case").jsonPrimitive.content
            val kw = record.getValue("kw").jsonObject
            val want = record.getValue("out")
            when (val fn = record.getValue("fn").jsonPrimitive.content) {
                "caracole.get._Lookup._sheet_from_ug" -> {
                    val got = JsonArray(listOf(JsonPrimitive("done"), JsonPrimitive(UgStages.sheetSaid(cameTo(kw)))))
                    misses.check(got == want) { "$case: $got, Python's $want" }
                }
                "caracole.get._Lookup.ug" -> {
                    val got = JsonPrimitive(UgStages.restSaid(cameTo(kw)))
                    misses.check(got == want) { "$case: $got, Python's $want" }
                }
                "caracole.get._Lookup._ug_ready" -> {
                    val got = ready(kw)
                    val python = (want as? JsonPrimitive)?.takeIf { it.isString }?.content
                    misses.check(got == python) { "$case: ${got?.let(PyStr::repr) ?: "None"}, Python's $want" }
                }
                else -> misses.check(false) { "$case: no replay for $fn" }
            }
        }
    }

    /** A record's `outcome`, `{sheet, tab, kept_versions}`, as the pass's SongFetchOutcome. */
    private fun cameTo(kw: JsonObject): SongFetchOutcome {
        val o = kw.getValue("outcome").jsonObject
        return SongFetchOutcome(1, o["sheet"]?.jsonPrimitive?.longOrNull, o["tab"]?.jsonPrimitive?.longOrNull, 3,
                                settled = true,
                                keptVersions = o.getValue("kept_versions").jsonArray.map { it.jsonPrimitive.content })
    }

    /** `_ug_ready` of a record's song in a database of its index's artists and its kv, with its overrides. */
    private fun ready(kw: JsonObject): String? {
        val s = kw.getValue("song").jsonObject
        val song = SongRow(
            id = 1, key = "soda-stereo/persiana-americana", artist = s.getValue("artist").jsonPrimitive.content,
            title = "Persiana Americana", artists = s.getValue("artists").jsonArray.map { it.jsonPrimitive.content },
            album = null, durationMs = null, isrc = null, sourceIds = "{}", addedAt = "2026-10-01T00:00:00Z",
            variant = null, status = "wanted", review = false,
            matchDecision = s.getValue("match_decision").jsonPrimitive.content, matchStep = null, matchScore = null,
            matchArtistKey = null, matchSongKey = null, matchCandidates = s.getValue("match_candidates").toString(),
            matchedAt = null, ugDirty = true, ugCheckedAt = null, lyricsStatus = "pending", lyricsJson = null,
            lyricsAt = null, lacuerdaCheckedAt = null, createdAt = "2026-10-01T00:00:00Z",
        )
        val written = kw.getValue("overrides").jsonObject
        val overrides = Overrides(
            alias = (written["alias"] as? JsonObject).orEmpty().mapValues { (_, v) -> v.jsonArray.map { it.jsonPrimitive.content } },
            artistUrl = (written["artist_url"] as? JsonObject).orEmpty().mapValues { it.value.jsonPrimitive.content },
        )
        val dir = Files.createTempDirectory("caracole-ug-ready").toFile()
        try {
            return TestDb.fresh(dir).use { database ->
                database.writeBlocking { db ->
                    kw.getValue("index").jsonArray.forEachIndexed { n, key ->
                        db.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                                       "VALUES (?, ?, 'a-song', 'chords', 'last', '2026-10-01T00:00:00Z', '')",
                                   7L + n, key.jsonPrimitive.content)
                    }
                    for ((k, v) in kw.getValue("kv").jsonObject) db.kvSet(k, v.jsonPrimitive.content)
                    val ctx = StageContext(db, song, overrides, PhoneConfig.DEFAULTS, LibraryStore(dir),
                                           FakeAsking(emptyMap()), Instant.EPOCH)
                    UgStages.notReady(ctx)
                }
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    /**
     * vectors/lookup/ug_artist.jsonl: each pass of a record, `process_song` of a song its artist's page settles, in
     * turn through one client; `artist_known` asked of the world before, the pages the phone noted, and
     * `paste_problem` after.
     */
    fun artist(misses: Misses) {
        for (record in records(ARTIST)) {
            val case = record.getValue("case").jsonPrimitive.content
            val kw = record.getValue("kw").jsonObject
            val song = kw.getValue("song").jsonPrimitive.long
            Scenarios.replay(record, misses) { world ->
                val db = world.db
                val known = ArtistRoute.artistIsKnown(db, Songs.byId(db, song)!!, Overrides.read(db))
                misses.check(JsonPrimitive(known) == record["artist_known"]) {
                    "$case: the artist's page known $known, Python's ${record["artist_known"]}"
                }
                try {
                    kw.getValue("passes").jsonArray.map { spec ->
                        val pass = spec.jsonObject
                        outcome(UgFetch.processSong(context(world, pass), Songs.byId(db, song)!!,
                                                    guitar = pass.getValue("guitar").jsonPrimitive.boolean))
                    }
                } finally {
                    val noted = JsonObject(notes(db).mapValues { JsonPrimitive(it.value) })
                    misses.check(noted == record["noted"]) { "$case: the pages noted $noted, Python's ${record["noted"]}" }
                    db.execute("DELETE FROM kv WHERE key >= ? AND key < ?", Reads.READ, Reads.READ.dropLast(1) + ";")
                    val problem = ArtistRoute.pastedPageProblem(db, Songs.byId(db, song)!!, Overrides.read(db))
                    val said: JsonElement = problem?.let { JsonArray(listOf(JsonPrimitive(it.first), JsonPrimitive(it.second))) }
                        ?: JsonNull
                    misses.check(said == record["paste_problem"]) {
                        "$case: the pasted page's problem $said, Python's ${record["paste_problem"]}"
                    }
                }
            }
        }
    }

    /** The UG artist pages the phone noted for the computer, each at its stamp. */
    private fun notes(db: Db): Map<String, String> = db.query(
        "SELECT key, value FROM kv WHERE key >= ? AND key < ? ORDER BY key", "${Reads.READ}ug:", "${Reads.READ}ug;",
    ) { it.text(0)!!.removePrefix("${Reads.READ}ug:") to it.text(1)!! }.toMap()

    /**
     * vectors/lookup/commands_versions.jsonl: each turn of a record, `VersionsCommands.keep` or `keepMore` of the
     * record's song, through a command's own asking of the record's client ([TurnAsking]): its lines and its last, the
     * library's folder written `{library}`, or its refusal's words.
     *
     * The record holds what the phone's VersionsCommands says (the generator's `phone_lines`); the rest of Python's
     * output is lane lookup's VersionsRunner's, which owns three differences: it begins the song stage before the
     * command speaks, it says the command's last line once it returns (after the pdf and pages stages it makes the
     * pages at), and the queue ends the job where Python prints its `done` event. LookupRunnersTest runs a keep
     * through that runner, LookupJobs.context and InteractiveAsk against a real client.
     */
    fun versions(misses: Misses) {
        for (record in records(VERSIONS)) {
            val kw = record.getValue("kw").jsonObject
            val song = kw.getValue("song").jsonPrimitive.long
            Scenarios.replay(record, misses) { world ->
                val library = LibraryStore(world.library)
                kw.getValue("turns").jsonArray.map { t ->
                    val turn = t.jsonObject
                    val lines = ArrayList<String>()
                    val c = object : CommandContext {
                        override val db: Db = world.db
                        override val asking: Asking = TurnAsking(world.db, world.clients.getValue("ug"), world.now)
                        override val now: Instant = world.now
                        override fun say(line: String) {
                            lines += line
                        }
                    }
                    val row = Songs.byId(world.db, song)!!
                    try {
                        lines += when (turn.getValue("command").jsonPrimitive.content) {
                            "keep" -> VersionsCommands.keep(c, library, row, turn.getValue("tab").jsonPrimitive.longOrNull!!)
                            else -> VersionsCommands.keepMore(c, library, row)
                        }
                        mapOf("lines" to lines.map { it.replace(world.library.path, "{library}") })
                    } catch (e: VersionsCommands.KeepRefused) {
                        mapOf("error" to e.message)
                    }
                }
            }
        }
    }

    /**
     * One command's asking of the record's client, as lane lookup's InteractiveAsk asks for a lookup command: none
     * while the provider cools down; a block cools it down (Health.recordBlock) and an error is counted
     * (Health.recordError); the requests counted from the command's start, the client's cache, pace and events the
     * record's.
     */
    class TurnAsking(private val db: Db, private val client: Client, private val now: Instant) : Asking {
        private val start = client.requestsMade

        override fun <T> ask(provider: String, policy: ProviderPolicy?, work: (Client) -> T): Asked<T> {
            if (Health.isCooling(db, provider, now)) return Asked.Cooling(Health.state(db, provider).cooldownUntil)
            return try {
                Asked.Done(work(client))
            } catch (e: ProviderBlocked) {
                Asked.Blocked(e, Health.recordBlock(db, e.provider, now, e.message.orEmpty()))
            } catch (e: BudgetExhausted) {
                Asked.Spent(hour = false, keptForSheets = false)
            } catch (e: ProviderError) {
                Health.recordError(db, e.provider, now, e.message.orEmpty())
                Asked.Failed(e)
            }
        }

        override val requests: Map<String, Int> get() = mapOf(VersionsCommands.PROVIDER to client.requestsMade - start)
    }

    /** A pass's FetchContext in the record's world: its client, the phone's overrides, the pass's rank. */
    fun context(world: ScenarioWorld, pass: JsonObject): FetchContext = FetchContext(
        world.db, world.clients.getValue("ug"), Overrides.read(world.db), rank(pass.getValue("rank").jsonObject),
        LibraryStore(world.library), world.now, maxPagesPerGroup = pass.getValue("max_pages_per_group").jsonPrimitive.int,
        guitarPagesPerGroup = pass.getValue("guitar_pages_per_group").jsonPrimitive.int,
        versions = pass.getValue("versions").jsonPrimitive.boolean,
    )

    /** config.RankPolicy's fields, by Python's names. */
    fun rank(o: JsonObject): RankPolicy = RankPolicy(
        coverageThreshold = o.getValue("coverage_threshold").jsonPrimitive.double,
        lineMatch = o.getValue("line_match").jsonPrimitive.double, priorVotes = o.getValue("prior_votes").jsonPrimitive.double,
        scoredSheets = o.getValue("scored_sheets").jsonPrimitive.int,
        labelPenalty = o.getValue("label_penalty").jsonPrimitive.double,
        variantBonus = o.getValue("variant_bonus").jsonPrimitive.double,
    )

    /** SongFetchOutcome as helpers.corpus.plain writes it. */
    fun outcome(o: SongFetchOutcome): Map<String, Any?> = linkedMapOf(
        "song_id" to o.songId, "sheet" to o.sheet, "tab" to o.tab, "requests" to o.requests, "settled" to o.settled,
        "kept_versions" to o.keptVersions,
    )
}
