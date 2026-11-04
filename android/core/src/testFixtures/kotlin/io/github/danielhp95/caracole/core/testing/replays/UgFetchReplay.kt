package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.sites.NotYet
import io.github.danielhp95.caracole.core.lookup.sites.UgStages
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.FakeAsking
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.ScenarioWorld
import io.github.danielhp95.caracole.core.testing.Scenarios
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.ug.FetchContext
import io.github.danielhp95.caracole.core.ug.SongFetchOutcome
import io.github.danielhp95.caracole.core.ug.UgFetch
import kotlinx.serialization.json.JsonArray
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
 * UG's lookup path for a matched song (vectors/lookup/ug_sheet.jsonl, ug_keep.jsonl; tests/test_conformance_ug_fetch.py)
 * replayed as Python recorded it: each record's passes of `UgFetch.processSong` (or `keepVersion`s) in its world, the
 * requests in order, the rows, kv and files written, the events and the result compared (core.testing.Scenarios);
 * and get.py's words for the two UG stages (ug_sheet_stages.jsonl): what each says a pass did, and `_ug_ready`'s
 * answer for a song. UgFetchSheetTest and KeepVersionTest call each part on the JVM; CorpusOnDeviceTest runs them all
 * under ART.
 */
object UgFetchReplay : AreaReplay {
    override val area = "ug-fetch"

    const val SHEET = "lookup/ug_sheet.jsonl"
    const val KEEP = "lookup/ug_keep.jsonl"
    const val STAGES = "lookup/ug_sheet_stages.jsonl"

    override fun replay(misses: Misses) {
        sheet(misses)
        keep(misses)
        stages(misses)
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
     * index, kv and overrides. Where Python's answer is none for a song the index can't settle (it reads the artist's
     * page then), the phone's is NotYet's until lane ug-fetch-artist builds that route.
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
                    val (got, needs) = ready(kw)
                    val python = (want as? JsonPrimitive)?.takeIf { it.isString }?.content
                    val expected = if (python == null && needs) NotYet.WORDS else python
                    misses.check(got == expected) { "$case: ${got?.let(PyStr::repr) ?: "None"}, Python's $want" }
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

    /** `_ug_ready` of a record's song in a database of its index's artists and its kv, with its overrides; and
     * whether the song needs its artist's page. */
    private fun ready(kw: JsonObject): Pair<String?, Boolean> {
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
                    UgStages.notReady(ctx) to UgFetch.needsArtistPage(song)
                }
            }
        } finally {
            dir.deleteRecursively()
        }
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
