package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.GameTabsParseError
import io.github.danielhp95.caracole.core.http.LaCuerdaParseError
import io.github.danielhp95.caracole.core.http.LrclibParseError
import io.github.danielhp95.caracole.core.http.PageParseError
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.http.ProviderUnavailable
import io.github.danielhp95.caracole.core.http.Response
import io.github.danielhp95.caracole.core.http.RobotsClosed
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LaCuerdaPick
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SharedFolder
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.InteractiveAsk
import io.github.danielhp95.caracole.core.lookup.Lookup
import io.github.danielhp95.caracole.core.lookup.LookupLines
import io.github.danielhp95.caracole.core.lookup.LookupRequest
import io.github.danielhp95.caracole.core.lookup.LookupResult
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.Progress
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.SiteStages
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.lookup.SongbookStats
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.nio.file.Files
import java.time.Duration
import java.time.Instant

/**
 * A lookup's words, its envelope and its pace (vectors/lookup/words*, asking*, after_the_sheet*, written by
 * tests/test_conformance_lookup.py): get.py's constants and words in [LookupWords] and [LookupLines], each site's
 * answer said through [InteractiveAsk] as `_Lookup.asking` says it (its records of cooldowns and errors, the songs it
 * owes a fetch), what follows the sheet held to [LookupWords.SHEETS_SHARE] ([InteractiveAsk.afterTheSheet]), and the
 * sheet stage's order over its sites' answers through [Lookup] itself, each over a database of its own.
 */
object LookupReplay : AreaReplay {
    override val area = "lookup"

    override fun replay(misses: Misses) {
        val dir = Files.createTempDirectory("caracole-lookup").toFile()
        try {
            TestDb.fresh(File(dir, "db").apply { mkdirs() }).use { database ->
                val store = LibraryStore(File(dir, "library").apply { mkdirs() })
                val cache = File(dir, "cache")
                database.writeBlocking { db ->
                    words(database, db, store, cache, misses)
                    asking(db, store, cache, misses)
                    afterTheSheet(db, store, cache, misses)
                }
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    // --- words.jsonl --------------------------------------------------------------------------------------------

    private fun words(database: Database, db: Db, store: LibraryStore, cache: File, misses: Misses) {
        for (r in Corpus.records("lookup/words.jsonl")) {
            val case = r.extra["case"]?.jsonPrimitive?.content
            when (r.fn) {
                "caracole.get" -> constants(r.out!!.jsonObject, misses)
                "caracole.get._Lookup._then" -> {
                    val then = r.kw.getValue("then").takeUnless { it is JsonNull }?.let(::end)
                    val got = LookupWords.then(end(r.kw.getValue("out")), then, r.kw.getValue("has_lyrics").jsonPrimitive.boolean)
                    misses.check(got == end(r.out!!)) { "_then(${r.kw}) = $got, Python's ${r.out}" }
                }
                "caracole.get._Lookup.sheet" -> sheet(database, db, store, cache, r, misses)
                "caracole.get._Lookup.pdf" ->
                    misses.check(StageEnd("skipped", LookupWords.NO_SHEET_YET) == end(r.out!!)) { "$case: ${r.out}" }
                "caracole.get._Lookup.lacuerda" -> {
                    val got = LookupWords.lacuerdaAgain(end(r.kw.getValue("said")))
                    misses.check(got == end(r.out!!)) { "lacuerda again (${r.kw}) = $got, Python's ${r.out}" }
                }
                "caracole.get._Lookup.songbooks" -> songbooks(r, misses)
                "caracole.commands.get._Lines" -> lines(r, misses)
                "caracole.commands.get._totals" -> {
                    val requests = r.kw.getValue("requests").jsonArray.associateTo(LinkedHashMap()) { pair ->
                        text(pair.jsonArray[0]) to pair.jsonArray[1].jsonPrimitive.int
                    }
                    val result = LookupResult(null, "", emptyMap(), emptyMap(), emptyMap(), null,
                                              double(r.kw.getValue("seconds")), requests, null,
                                              r.kw.getValue("refused").takeUnless { it is JsonNull }?.let(::text))
                    val got = LookupWords.totals(result)
                    misses.check(got == text(r.out!!)) { "$case: totals $got, Python's ${r.out}" }
                }
                else -> misses.check(false) { "no replay of ${r.fn}" }
            }
        }
    }

    private fun constants(want: JsonObject, misses: Misses) {
        val got: Map<String, Any> = mapOf(
            "STAGES" to LookupWords.STAGES.map { listOf(it.first, it.second) },
            "NAMES" to LookupWords.NAMES, "SHEETS_SHARE" to LookupWords.SHEETS_SHARE,
            "SHEET_FROM" to LookupWords.SHEET_FROM, "MATCH_NOT_FOUND" to LookupWords.MATCH_NOT_FOUND,
            "GTPTABS_KEPT" to LookupWords.GTPTABS_KEPT, "HARPTABS_KEPT" to LookupWords.HARPTABS_KEPT,
            "GAMETABS_KEPT" to LookupWords.GAMETABS_KEPT, "NOT_IN_INDEX" to LookupWords.NOT_IN_INDEX,
            "ADDED" to LookupWords.ADDED, "NO_PDFS" to LookupWords.NO_PDFS, "PAGES_MADE" to LookupWords.PAGES_MADE,
            "LIBRARY_PAGE" to LookupWords.LIBRARY_PAGE,
        )
        for ((name, value) in got) {
            val expected = want.getValue(name)
            val same = when (value) {
                is List<*> -> value == expected.jsonArray.map { row -> row.jsonArray.map(::text) }
                is Map<*, *> -> value == expected.jsonObject.mapValues { text(it.value) }
                is Double -> value == double(expected)
                else -> value == text(expected)
            }
            misses.check(same) { "get.$name = $value, Python's $expected" }  // the corpus writes a dict's keys sorted
        }
        misses.check(want.keys == got.keys) { "get's constants ${want.keys}, the replay's ${got.keys}" }
    }

    /** The sheet stage, then the lacuerda stage, through the frame over scripted sites (the record's KDoc in
     * tests/test_conformance_lookup.py). */
    private fun sheet(database: Database, db: Db, store: LibraryStore, cache: File, r: Record, misses: Misses) {
        val case = r.extra["case"]?.jsonPrimitive?.content
        PoliteDb.fresh(db, JsonArray(emptyList()))
        noSongs(db)
        val now = Instant.parse("2026-11-03T12:00:00Z")
        val song = store.add(db, "Soda Stereo", "De Música Ligera", now = Stamps.of(now))
        val picked = r.kw.getValue("picked").jsonPrimitive.boolean
        val pick = LaCuerdaPick("soda_stereo", "de_musica_ligera")
        r.kw.getValue("kept").takeUnless { it is JsonNull }?.let { keep(db, store, song, text(it)) }
        val asked = ArrayList<String>()
        fun scripted(provider: String): SiteStage = SiteStage { ctx ->
            val s = r.kw.getValue(provider).jsonObject
            asked += "$provider:" + if (ctx.asking is InteractiveAsk.AfterTheSheet) "after" else "asking"
            if (s.getValue("asked").jsonPrimitive.boolean) ctx.asking.ask(provider) { }
            s.getValue("keeps").takeUnless { it is JsonNull }?.let { keep(db, store, ctx.song, text(it)) }
            end(s.getValue("end"))
        }
        val quiet = SiteStage { StageEnd("skipped", "") }
        val stages = SiteStages(match = quiet, ugSheet = scripted("ug"), ug = quiet, lacuerdaPick = scripted("lacuerda"),
                                lacuerda = scripted("lacuerda"), lrclib = quiet, megalobiz = quiet, azlyrics = quiet,
                                gtptabs = quiet, harptabs = quiet, gametabs = quiet)
        val heard = ArrayList<Triple<String, String, String>>()
        val progress = object : Progress {
            override fun stage(name: String, state: String, detail: String) {
                heard += Triple(name, state, detail)
            }
        }
        val cfg = PhoneConfig.DEFAULTS
        val pacing = fixed(now)
        val lookup = Lookup(cfg, database, store, Clients(cfg, cache, { RefusingTransport }, pacing), SongPages.NONE,
                            SongbookPages.NONE, Alerts.NONE, LookupRequest(song.artist, song.title), progress, pacing,
                            stages, readOverrides = { if (picked) Overrides(lacuerda = mapOf(song.key to pick)) else Overrides() })
        val result = lookup.run(db)
        val want = r.out!!.jsonObject
        val got = mapOf(
            "sheet" to StageEnd(result.states.getValue("sheet"), result.details.getValue("sheet")),
            "lacuerda_stage" to StageEnd(result.states.getValue("lacuerda"), result.details.getValue("lacuerda")),
        )
        for ((name, value) in got) {
            misses.check(value == end(want.getValue(name))) { "$case: $name $value, Python's ${want.getValue(name)}" }
        }
        misses.check(asked == want.getValue("asked").jsonArray.map(::text)) { "$case: asked $asked, Python's ${want["asked"]}" }
        val running = heard.filter { it.first == "sheet" && it.second == "running" }.map { it.third }
        misses.check(running == want.getValue("running").jsonArray.map(::text)) {
            "$case: running $running, Python's ${want["running"]}"
        }
    }

    /** The song's sheet.txt kept from [provider]'s version: Ultimate Guitar's tab, or the LaCuerda pick's version. */
    private fun keep(db: Db, store: LibraryStore, song: SongRow, provider: String) {
        val tab = if (provider == "lacuerda") "soda_stereo/de_musica_ligera-1" else "4169"
        val id = Versions.upsert(db, provider, tab, song.id, "sheet", "chords", 4.5, 10, 1, null,
                                 "https://example.invalid/$provider/$tab", JsonObject(emptyMap()), "2026-11-03T12:00:00Z")
        Kept.dropFile(db, store, song, "sheet.txt")
        Kept.keepFile(db, store, song, id, "sheet.txt", "[C]$provider\n".toByteArray(), 0, "2026-11-03T12:00:00Z")
    }

    private fun songbooks(r: Record, misses: Misses) {
        val case = r.extra["case"]?.jsonPrimitive?.content
        val kw = r.kw
        val listing = kw["listing"]?.jsonArray?.map(::text).orEmpty()
        val names = listing.joinToString(", ")
        val stats = kw["stats"]?.jsonObject.orEmpty()
        val got = when {
            "error" in kw -> StageEnd("skipped", LookupWords.songbooksUnread(text(kw.getValue("error"))))
            kw["songbooks"]?.jsonPrimitive?.boolean == false -> StageEnd("skipped", LookupWords.SONGBOOKS_LEFT)
            listing.isEmpty() -> StageEnd("skipped", LookupWords.NO_SONGBOOK)
            else -> LookupWords.songbooksEnd(names, SongbookStats(
                rendered = stats["rendered"]?.jsonPrimitive?.int ?: 0,
                failed = stats["failed"]?.jsonArray?.map(::text).orEmpty(),
                fontError = stats["font_error"]?.let(::text)))
        }
        val want = r.out!!.jsonObject
        misses.check(got == end(want.getValue("end"))) { "$case: songbooks $got, Python's ${want["end"]}" }
    }

    private fun lines(r: Record, misses: Misses) {
        val case = r.extra["case"]?.jsonPrimitive?.content
        val said = ArrayList<String>()
        val lines = LookupLines(File(text(r.kw.getValue("library")))) { said += it }
        for (e in r.kw.getValue("events").jsonArray) {
            val event = e.jsonArray
            when (text(event[0])) {
                "stage" -> lines.stage(text(event[1]), text(event[2]), text(event[3]))
                "readable" -> lines.readable(event[1].jsonObject.mapValues { text(it.value) }, double(event[2]))
                else -> lines.flush()
            }
        }
        val want = r.out!!.jsonArray.map(::text)
        misses.check(said == want) { "$case: lines $said, Python's $want" }
    }

    // --- asking.jsonl -------------------------------------------------------------------------------------------

    private fun asking(db: Db, store: LibraryStore, cache: File, misses: Misses) {
        for (r in Corpus.records("lookup/asking.jsonl")) {
            val case = r.extra["case"]?.jsonPrimitive?.content
            val provider = text(r.kw.getValue("provider"))
            val now = Instant.parse(text(r.kw.getValue("now")))
            noSongs(db)
            PoliteDb.fresh(db, r.kw.getValue("events").jsonArray,
                           r.kw.getValue("kv").jsonObject.mapValues { text(it.value) })
            val cfg = configured(r.kw.getValue("providers").jsonObject)
            val song = r.kw.getValue("song").takeUnless { it is JsonNull }?.jsonObject?.let { s ->
                val added = store.add(db, text(s.getValue("artist")), text(s.getValue("title")), now = Stamps.of(now))
                Versions.updateSong(db, added.id, mapOf("match_decision" to text(s.getValue("match_decision")),
                                                        "ug_dirty" to s.getValue("ug_dirty").jsonPrimitive.boolean))
                added
            }
            val ask = InteractiveAsk(Clients(cfg, cache, { RefusingTransport }, fixed(now)), db, Pace.lookupRunId(now),
                                     now, Alerts.NONE, cfg)
            ask.blocked += r.kw.getValue("blocked").jsonArray.map(::text)
            ask.failed += r.kw.getValue("failed").jsonArray.map(::text)
            ask.keptForSheets += r.kw.getValue("kept_for_sheets").jsonArray.map(::text)
            ask.owedSong = song?.id
            val outcome = r.kw.getValue("outcome").jsonObject
            val got = try {
                LookupWords.end(cfg, provider, ask.ask(provider) {
                    outcome["raises"]?.let { throw raised(db, store, now, it.jsonObject) }
                    end(outcome.getValue("returns"))
                })
            } catch (e: SharedFolder) {  // the frame's: a stage that would write over another song's file fails
                StageEnd("failed", LookupWords.sharedFolder(e))
            }
            val want = r.out!!.jsonObject
            misses.check(got == end(want.getValue("end"))) { "$case: $got, Python's ${want["end"]}" }
            val kv = db.kvGet("provider:$provider")
            misses.check(kv == want.getValue("kv").takeUnless { it is JsonNull }?.let(::text)) {
                "$case: kv $kv, Python's ${want["kv"]}"
            }
            val dirty = song?.let { Songs.byId(db, it.id)!!.ugDirty }
            misses.check(dirty == want.getValue("ug_dirty").takeUnless { it is JsonNull }?.jsonPrimitive?.boolean) {
                "$case: ug_dirty $dirty, Python's ${want["ug_dirty"]}"
            }
            for ((name, set) in listOf("blocked" to ask.blocked, "failed" to ask.failed)) {
                misses.check(set.sorted() == want.getValue(name).jsonArray.map(::text)) {
                    "$case: $name ${set.sorted()}, Python's ${want[name]}"
                }
            }
        }
    }

    /** The exception a record's work raised, as the phone declares each. */
    private fun raised(db: Db, store: LibraryStore, now: Instant, spec: JsonObject): Exception {
        fun opt(name: String): String? = spec[name]?.takeUnless { it is JsonNull }?.let(::text)
        val provider = opt("provider").orEmpty()
        val status = spec["status"]?.takeUnless { it is JsonNull }?.jsonPrimitive?.int
        return when (val cls = text(spec.getValue("class"))) {
            "ProviderBlocked" -> ProviderBlocked(provider, opt("url"), status, opt("message"))
            "ProviderError" -> ProviderError(provider, opt("url"), status, opt("message"))
            "ProviderUnavailable" -> ProviderUnavailable(provider, opt("url"), status, opt("message"))
            "RobotsClosed" -> RobotsClosed(provider, opt("url"), status, opt("message"))
            "PageParseError" -> PageParseError(provider, opt("url"), status, opt("message"))
            "LrclibParseError" -> LrclibParseError(provider, opt("url"), status, opt("message"))
            "LaCuerdaParseError" -> LaCuerdaParseError(opt("message").orEmpty(), opt("url"))
            "GameTabsParseError" -> GameTabsParseError(opt("message").orEmpty(), opt("url"))
            "BudgetExhausted" -> BudgetExhausted(provider)
            "SharedFolder" -> {
                fun named(e: JsonElement): SongRow {
                    val (artist, title) = e.jsonArray.map(::text)
                    return Songs.byKey(db, Normalize.identityKey(artist, title))
                        ?: store.add(db, artist, title, now = Stamps.of(now))
                }
                SharedFolder(named(spec.getValue("song")), named(spec.getValue("other")), opt("name").orEmpty())
            }
            else -> throw AssertionError("no exception $cls")
        }
    }

    // --- after_the_sheet.jsonl ----------------------------------------------------------------------------------

    private fun afterTheSheet(db: Db, store: LibraryStore, cache: File, misses: Misses) {
        for (r in Corpus.records("lookup/after_the_sheet.jsonl")) {
            val case = r.extra["case"]?.jsonPrimitive?.content
            val provider = text(r.kw.getValue("provider"))
            val now = Instant.parse(text(r.kw.getValue("now")))
            PoliteDb.fresh(db, r.kw.getValue("events").jsonArray,
                           r.kw.getValue("kv").jsonObject.mapValues { text(it.value) })
            val cfg = configured(r.kw.getValue("providers").jsonObject)
            val made = r.kw.getValue("requests_made").jsonPrimitive.int
            val ask = InteractiveAsk(Clients(cfg, cache, { RefusingTransport }, fixed(now)), db, Pace.lookupRunId(now),
                                     now, Alerts.NONE, cfg) { p, policy ->
                SentAlready(p, Pace.withinTheDay(db, p, policy ?: Pace.lookupPolicy(cfg, db, p, now), now), made)
            }
            val seen = ArrayList<Long>()
            val spends = text(r.kw.getValue("work")) == "spends"
            val got = LookupWords.end(cfg, provider, ask.afterTheSheet.ask(provider) { client ->
                seen += client.policy.budget
                if (spends) throw BudgetExhausted(provider)
                StageEnd("done", "asked")
            })
            val want = r.out!!.jsonObject
            misses.check(got == end(want.getValue("end"))) { "$case: $got, Python's ${want["end"]}" }
            misses.check(ask.left(provider) == want.getValue("left").jsonPrimitive.int) {
                "$case: left ${ask.left(provider)}, Python's ${want["left"]}"
            }
            val budget = want.getValue("budget").takeUnless { it is JsonNull }?.jsonPrimitive?.long
            misses.check(seen.firstOrNull() == budget) { "$case: budget ${seen.firstOrNull()}, Python's $budget" }
            misses.check((provider in ask.keptForSheets) == want.getValue("kept_for_sheets").jsonPrimitive.boolean) {
                "$case: kept for sheets ${provider in ask.keptForSheets}, Python's ${want["kept_for_sheets"]}"
            }
        }
    }

    /** A lookup's client that had sent [requestsMade] before, and sends nothing more. */
    private class SentAlready(override val provider: String, override var policy: ProviderPolicy,
                              override val requestsMade: Int) : Client {
        override fun get(url: String, params: List<Pair<String, String>>?, cache: Boolean, conditional: Boolean,
                         accept: Set<Int>, maxAge: Duration?): Response = throw AssertionError("no request: $url")

        override fun cached(url: String, accept: Set<Int>): Response? = null
        override fun hasCached(url: String, accept: Set<Int>): Boolean = false
    }

    // --- shared -------------------------------------------------------------------------------------------------

    /** No song, version or kept file left of the record before (songs.id has no AUTOINCREMENT: a new song may take a
     * gone one's id). */
    private fun noSongs(db: Db) {
        db.execute("DELETE FROM files")
        db.execute("DELETE FROM versions")
        db.execute("DELETE FROM songs")
    }

    /** A stage's end as the corpus writes get.py's: a text (`done` with those words) or `[state, detail]`. */
    private fun end(e: JsonElement): StageEnd = when (e) {
        is JsonArray -> StageEnd(text(e[0]), text(e[1]))
        else -> StageEnd("done", text(e))
    }

    /** The clocks at [now], no pause slept and each draw its lowest. */
    private fun fixed(now: Instant): Pacing =
        Pacing(sleep = {}, draws = { low, _ -> low }, wallSeconds = { now.epochSecond.toDouble() },
               monotonic = { 0.0 }, clock = { now })

    /** config.DEFAULT_PROVIDERS with a record's fields over theirs (config.py's names). */
    private fun configured(overrides: JsonObject): PhoneConfig =
        PhoneConfig.DEFAULTS.copy(providers = PhoneConfig.DEFAULTS.providers.mapValues { (name, p) ->
            overrides[name]?.jsonObject?.let { f ->
                p.copy(enabled = f["enabled"]?.jsonPrimitive?.boolean ?: p.enabled,
                       lookupRequests = f["lookup_requests"]?.jsonPrimitive?.int ?: p.lookupRequests,
                       lookupPerHour = f["lookup_per_hour"]?.jsonPrimitive?.int ?: p.lookupPerHour)
            } ?: p
        })
}
