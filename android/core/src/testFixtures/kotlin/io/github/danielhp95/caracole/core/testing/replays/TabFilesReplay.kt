package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.InteractiveAsk
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.sites.GtpTabsStage
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.sites.GtpIndexRow
import io.github.danielhp95.caracole.core.sites.GtpTab
import io.github.danielhp95.caracole.core.sites.GtpTabsFetch
import io.github.danielhp95.caracole.core.sites.GtpTabsPages
import io.github.danielhp95.caracole.core.sites.GtpTabsStats
import io.github.danielhp95.caracole.core.sites.MuseScorePage
import io.github.danielhp95.caracole.core.sites.MuseScorePages
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.ScenarioWorld
import io.github.danielhp95.caracole.core.testing.Scenarios
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.nio.file.Files
import java.time.Instant

/**
 * gtptabs.com and MuseScore (tests/test_conformance_tab_files.py), each record answered as Python answered it:
 * - [pages]: vectors/sites/gtptabs.jsonl, gtptabs.py's URLs, keys, artist pages and `sniff` (its seeded mutations of
 *   Guitar Pro 7's zip each rebuilt from the record's base);
 * - [titlePages]: vectors/sites/gtptabs_title_page.jsonl, gtptabs_fetch.title_page over its fixture;
 * - [museScore]: vectors/sites/musescore.jsonl, musescore.py's URLs and keys and `song_pages` over its fixture;
 * - [lookups]: vectors/lookup/gtptabs.jsonl, scenario records (Scenarios.replay) of gtptabs_files for one song and of
 *   get.py's gtptabs stage, each request carrying the record's user agent, caracole's own. The stage asks through
 *   the phone's InteractiveAsk with the record's clients (a site off, cooling, a block and an error recorded in
 *   `provider:gtptabs` by Health), so a record's kv is compared whole.
 */
object TabFilesReplay : AreaReplay {
    override val area = "tab-files"

    const val SITES = "sites/gtptabs.jsonl"
    const val TITLE_PAGE = "sites/gtptabs_title_page.jsonl"
    const val MUSESCORE = "sites/musescore.jsonl"
    const val LOOKUP = "lookup/gtptabs.jsonl"

    override fun replay(misses: Misses) {
        pages(misses)
        titlePages(misses)
        museScore(misses)
        lookups(misses)
    }

    private fun lines(name: String): List<JsonObject> = Corpus.lines(name).filter { it["header"] != JsonPrimitive(true) }

    private fun text(e: JsonElement?): String? = (e as? JsonPrimitive)?.takeIf { it.isString }?.content

    // --- gtptabs.py ----------------------------------------------------------------------------------------------

    fun pages(misses: Misses) {
        for (r in lines(SITES)) {
            val fn = r.getValue("fn").jsonPrimitive.content.removePrefix("caracole.gtptabs.")
            val args = r["args"] as? JsonArray ?: JsonArray(emptyList())
            val want = r["out"]
            when (fn) {
                "page_url" -> check(misses, fn, args, want) { JsonPrimitive(GtpTabsPages.pageUrl(text(args[0])!!)) }
                "download_url" -> check(misses, fn, args, want) {
                    JsonPrimitive(GtpTabsPages.downloadUrl(args[0].jsonPrimitive.long))
                }
                "https" -> check(misses, fn, args, want) { JsonPrimitive(GtpTabsPages.https(text(args[0])!!)) }
                "sitemap_name" -> check(misses, fn, args, want) { nullable(GtpTabsPages.sitemapName(text(args[0])!!)) }
                "parse_page_url" -> check(misses, fn, args, want) {
                    GtpTabsPages.parsePageUrl(text(args[0])!!)?.let(::row) ?: JsonNull
                }
                "artist_keys" -> check(misses, fn, args, want) {
                    JsonArray(GtpTabsPages.artistKeys(text(args[0])!!).map(::JsonPrimitive))
                }
                "title_key" -> check(misses, fn, args, want) { JsonPrimitive(GtpTabsPages.titleKey(text(args[0])!!)) }
                "_title" -> check(misses, fn, args, want) {
                    val (title, version) = GtpTabsPages.title(text(args[0])!!)
                    JsonArray(listOf(JsonPrimitive(title), JsonPrimitive(version)))
                }
                "parse_artist_page" -> artistPage(misses, r)
                "sniff" -> sniff(misses, r)
                else -> misses.check(false) { "$SITES: a record of $fn, which the replay doesn't know" }
            }
        }
    }

    private fun check(misses: Misses, fn: String, args: JsonArray, want: JsonElement?, got: () -> JsonElement) {
        val answer = try {
            got()
        } catch (e: Exception) {
            misses.check(false) { "gtptabs.$fn(${args.toString().take(120)}) threw $e, Python answered $want" }
            return
        }
        misses.check(answer == (want ?: JsonNull)) { "gtptabs.$fn(${args.toString().take(120)}) = $answer, Python's $want" }
    }

    private fun nullable(s: String?): JsonElement = s?.let(::JsonPrimitive) ?: JsonNull

    private fun row(r: GtpIndexRow) = JsonObject(linkedMapOf(
        "path" to JsonPrimitive(r.path), "artist_path" to JsonPrimitive(r.artistPath),
        "artist_key" to JsonPrimitive(r.artistKey), "title_key" to JsonPrimitive(r.titleKey),
        "base_key" to JsonPrimitive(r.baseKey),
    ))

    private fun tab(t: GtpTab) = JsonObject(linkedMapOf(
        "tab_id" to JsonPrimitive(t.tabId), "title" to JsonPrimitive(t.title), "version" to JsonPrimitive(t.version),
        "path" to JsonPrimitive(t.path), "format" to JsonPrimitive(t.format), "stars" to JsonPrimitive(t.stars),
        "size_kb" to (t.sizeKb?.let(PyJson::float) ?: JsonNull),
        "instruments" to JsonArray(t.instruments.map(::JsonPrimitive)), "guitar" to JsonPrimitive(t.guitar),
    ))

    private fun artistPage(misses: Misses, r: JsonObject) {
        val html = Scenarios.body(r.getValue("html")).toString(Charsets.UTF_8)
        val url = text(r["url"])
        val case = "parse_artist_page(${r["html"].toString().take(80)})"
        val got = try {
            JsonArray(GtpTabsPages.parseArtistPage(html, url).map(::tab))
        } catch (e: ProviderError) {
            val want = r["raises"]?.jsonObject
            misses.check(want != null && e::class.simpleName == text(want["type"]) && e.message == text(want["message"])) {
                "$case raised ${e::class.simpleName}: ${e.message}, Python ${r["raises"] ?: r["out"]}"
            }
            return
        }
        misses.check(r["raises"] == null && got == r["out"]) { "$case = $got, Python's ${r["raises"] ?: r["out"]}" }
    }

    private fun sniff(misses: Misses, r: JsonObject) {
        if (text(r["case"]) == "seeded mutations") {
            val base = Scenarios.body(r.getValue("base"))
            for (m in r.getValue("mutations").jsonArray.map { it.jsonObject }) {
                val data = base.copyOf()
                for (edit in m.getValue("set").jsonArray) {
                    data[edit.jsonArray[0].jsonPrimitive.int] = edit.jsonArray[1].jsonPrimitive.int.toByte()
                }
                val cut = (m["cut"] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.int
                val mutated = if (cut == null) data else data.copyOf(cut)
                val got = nullable(GtpTabsFetch.sniff(mutated))
                misses.check(got == m["out"]) { "sniff of the mutation ${m["set"]} cut at $cut = $got, Python's ${m["out"]}" }
            }
            return
        }
        val got = nullable(GtpTabsFetch.sniff(Scenarios.body(r.getValue("data"))))
        misses.check(got == r["out"]) { "sniff(${r["data"].toString().take(100)}) = $got, Python's ${r["out"]}" }
    }

    // --- gtptabs_fetch.title_page --------------------------------------------------------------------------------

    fun titlePages(misses: Misses) {
        for (r in lines(TITLE_PAGE)) {
            withFixture(r) { db ->
                for (case in r.getValue("cases").jsonArray.map { it.jsonArray }) {
                    val song = Songs.byId(db, case[0].jsonPrimitive.long)!!
                    val got = nullable(GtpTabsFetch.titlePage(db, song, Instant.parse(case[1].jsonPrimitive.content)))
                    misses.check(got == case[2]) { "title_page(${song.display}, ${case[1]}) = $got, Python's ${case[2]}" }
                }
            }
        }
    }

    private fun withFixture(r: JsonObject, block: (Db) -> Unit) {
        val dir = Files.createTempDirectory("tab-files").toFile()
        try {
            TestDb.fresh(dir).use { database ->
                database.writeBlocking { db ->
                    Fixtures.loadRecords(db, r.getValue("fixture").jsonArray.map { it.jsonObject }, File(dir, "library"),
                                         text(r["case"]) ?: "the fixture")
                    block(db)
                }
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    // --- musescore.py --------------------------------------------------------------------------------------------

    private fun page(p: MuseScorePage) = JsonObject(linkedMapOf(
        "page_id" to JsonPrimitive(p.pageId), "path" to JsonPrimitive(p.path), "title_key" to JsonPrimitive(p.titleKey),
    ))

    fun museScore(misses: Misses) {
        for (r in lines(MUSESCORE)) {
            val fn = r.getValue("fn").jsonPrimitive.content.removePrefix("caracole.musescore.")
            val args = r["args"] as? JsonArray ?: JsonArray(emptyList())
            val want = r["out"]
            when (fn) {
                "parse_song_url" -> check(misses, fn, args, want) {
                    MuseScorePages.parseSongUrl(text(args[0])!!)?.let(::page) ?: JsonNull
                }
                "sitemap_name" -> check(misses, fn, args, want) { nullable(MuseScorePages.sitemapName(text(args[0])!!)) }
                "title_key" -> check(misses, fn, args, want) { JsonPrimitive(MuseScorePages.titleKey(text(args[0])!!)) }
                "song_pages" -> withFixture(r) { db ->
                    for (case in r.getValue("cases").jsonArray.map { it.jsonArray }) {
                        val song = Songs.byId(db, case[0].jsonPrimitive.long)!!
                        val got = JsonArray(MuseScorePages.songPages(db, song, case[1].jsonPrimitive.int).map(::page))
                        misses.check(got == case[2]) { "song_pages(${song.title}, ${case[1]}) = $got, Python's ${case[2]}" }
                    }
                }
                else -> misses.check(false) { "$MUSESCORE: a record of $fn, which the replay doesn't know" }
            }
        }
    }

    // --- the lookups ---------------------------------------------------------------------------------------------

    fun lookups(misses: Misses) {
        for (r in lines(LOOKUP)) {
            val only = r.getValue("kw").jsonObject.getValue("only").jsonArray.map { it.jsonPrimitive.long }.toSet()
            val agent = text(r["agent"])
            misses.check(agent == PhoneConfig.DEFAULTS.userAgent) { "${r["case"]}: the phone's user agent isn't $agent" }
            Scenarios.replay(r, misses) { world ->
                val db = world.db
                val lib = LibraryStore(world.library)
                val overrides = Overrides.read(db)
                val result: Any = when (val fn = r.getValue("fn").jsonPrimitive.content) {
                    "caracole.gtptabs_fetch.gtptabs_files" ->
                        stats(GtpTabsFetch.gtptabsFiles(db, world.clients.getValue(GtpTabsFetch.PROVIDER), lib,
                                                        world.now, overrides, only))
                    "caracole.get._Lookup.gtptabs" -> {
                        val config = PhoneConfig.read(db)
                        val song = Songs.byId(db, only.single())!!
                        val asking = asking(world, config)
                        val end = GtpTabsStage.run(StageContext(db, song, overrides, config, lib, asking, world.now,
                                                                world.cacheDir))
                        listOf(end.state, end.detail)
                    }
                    else -> throw AssertionError("$LOOKUP: a record of $fn, which the replay doesn't know")
                }
                val agents = world.transport.requests.map { req ->
                    req.headers.firstOrNull { Py.asciiLower(it.first) == "user-agent" }?.second
                }
                misses.check(agents.all { it == agent }) { "${r["case"]}: requests sent as $agents, Python's $agent" }
                result
            }
        }
    }

    /** The phone's envelope (InteractiveAsk) handing out the record's clients, as the records' `_Lookup` was given
     * them (`lk.clients`): get.py's `_usable` and `asking` over [config], each block and error recorded in
     * `provider:gtptabs` by Health. */
    private fun asking(world: ScenarioWorld, config: PhoneConfig): InteractiveAsk {
        val pacing = Pacing(sleep = {}, draws = { low, _ -> low }, wallSeconds = { world.now.epochSecond.toDouble() },
                            monotonic = { 0.0 }, clock = { world.now })
        return InteractiveAsk(Clients(config, world.cacheDir, { RefusingTransport }, pacing), world.db,
                              Pace.lookupRunId(world.now), world.now, config = config) { provider, policy ->
            world.clients.getValue(provider).also { client -> if (policy != null) client.policy = policy }
        }
    }

    /** A pass's stats as a record holds them. */
    private fun stats(s: GtpTabsStats): JsonObject = JsonObject(linkedMapOf(
        "tried" to JsonPrimitive(s.tried), "errors" to JsonPrimitive(s.errors),
        "budget_exhausted" to JsonPrimitive(s.budgetExhausted),
        "failures" to JsonArray(s.failures.map { (song, e) ->
            JsonArray(listOf(JsonPrimitive(song.id), JsonPrimitive(e::class.simpleName), JsonPrimitive(e.message)))
        }),
        "sitemaps" to JsonPrimitive(s.sitemaps), "kept" to JsonPrimitive(s.kept), "missing" to JsonPrimitive(s.missing),
    ))
}
