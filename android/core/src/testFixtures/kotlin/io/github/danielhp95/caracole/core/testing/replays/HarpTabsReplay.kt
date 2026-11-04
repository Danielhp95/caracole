package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.EventLog
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.html.Html
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.Asking
import io.github.danielhp95.caracole.core.lookup.CommandContext
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.sites.HarpTabsCommands
import io.github.danielhp95.caracole.core.lookup.sites.HarpTabsStage
import io.github.danielhp95.caracole.core.sites.HarpArtistPage
import io.github.danielhp95.caracole.core.sites.HarpTabsFetch
import io.github.danielhp95.caracole.core.sites.HarpTabsStats
import io.github.danielhp95.caracole.core.sites.internal.harptabs.HarpTabsPages
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.ScenarioWorld
import io.github.danielhp95.caracole.core.testing.Scenarios
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.nio.file.Files
import java.time.Instant

/**
 * harptabs.com on the phone (tests/test_conformance_harptabs.py): its pages read (vectors/sites/harptabs.jsonl),
 * a lookup's pass and get.py's harptabs stage (vectors/lookup/harptabs.jsonl), an artist's page read now and the pages
 * a name names (harptabs_artist.jsonl), and `caracole harptabs --artist` (commands_harptabs.jsonl), each answered by
 * core.sites' HarpTabsPages and HarpTabsFetch, the stage and HarpTabsCommands as Python answered it. HarpTabsTest and
 * HarpTabsCommandsTest call each part on the JVM; CorpusOnDeviceTest runs them all under ART.
 *
 * A scenario's asking is [Envelope]: what lane lookup's InteractiveAsk does with a provider cooling down, a block
 * (Health.recordBlock), a spent budget and an error (Health.recordError), so that each record's kv is Python's, with
 * get.py's words for a site that is off. Every request a scenario sends carries the record's `agent`, caracole's own
 * user agent. The phone notes each artist page it stores for the next push to the computer (kv
 * `phone:read:harptabs:<path>`, the store's stamp), which Python doesn't: checked against the record's `reads`, then
 * left out of the kv compared.
 */
object HarpTabsReplay : AreaReplay {
    override val area = "harptabs"

    const val SITES = "sites/harptabs.jsonl"
    const val LOOKUP = "lookup/harptabs.jsonl"
    const val ARTIST = "lookup/harptabs_artist.jsonl"
    const val COMMANDS = "lookup/commands_harptabs.jsonl"

    /** Phase A guard: core.html is lane html-tree's, and until it merges no page can be parsed; a record that parses
     * one waits on it (waiting on html-tree), counted in [waiting]. */
    val htmlReady: Boolean by lazy { runCatching { Html.parse("<p>") }.isSuccess }

    /** The records the last replay left, waiting on html-tree (none once it has merged). */
    var waiting = 0
        private set

    override fun replay(misses: Misses) {
        waiting = 0
        pages(misses)
        lookups(misses)
        artists(misses)
        commands(misses)
    }

    /** [block], unless it parses a page before core.html is there: then counted in [waiting]. */
    private fun guarded(block: () -> Unit) {
        try {
            block()
        } catch (e: NotImplementedError) {
            if (htmlReady) throw e
            waiting++
        }
    }

    // --- the pages ----------------------------------------------------------------------------------------------------

    fun pages(misses: Misses) {
        for (r in records(SITES)) {
            val fn = text(r.getValue("fn")).removePrefix("caracole.harptabs.")
            if (fn == "parse_tab_page" || fn == "parse_artist_page") {
                guarded { parsed(misses, fn, r) }
                continue
            }
            val arg = r.getValue("args").jsonArray[0]
            val s = (arg as? JsonPrimitive)?.takeIf { it.isString }?.content
            val got: JsonElement = when (fn) {
                "page_url" -> JsonPrimitive(HarpTabsPages.pageUrl(s!!))
                "parse_page_url" -> HarpTabsPages.parsePageUrl(s!!)?.let {
                    obj("path" to JsonPrimitive(it.path), "kind" to JsonPrimitive(it.kind),
                        "page_id" to JsonPrimitive(it.pageId), "key" to JsonPrimitive(it.key))
                } ?: JsonNull
                "joined" -> JsonPrimitive(HarpTabsPages.joined(s!!))
                "title_key" -> JsonPrimitive(HarpTabsPages.titleKey(s!!))
                "title_keys" -> JsonArray(HarpTabsPages.titleKeys(s!!).map { JsonPrimitive(it) })
                "song_title" -> JsonPrimitive(HarpTabsPages.songTitle(s!!))
                "song_key" -> JsonPrimitive(HarpTabsPages.songKey(s!!))
                "_views" -> JsonPrimitive(HarpTabsPages.views(s))
                "_rating" -> HarpTabsPages.rating(s)?.let(PyJson::float) ?: JsonNull
                else -> throw AssertionError("no harptabs record of $fn")
            }
            val want = r["out"] ?: JsonNull
            misses.check(got == want) { "$fn(${arg.toString().take(80)}) = $got, Python's $want" }
        }
    }

    private fun parsed(misses: Misses, fn: String, r: JsonObject) {
        val html = r.getValue("html").jsonObject
        val url = (r["url"] as? JsonPrimitive)?.takeIf { it.isString }?.content
        val asText = html["text"]?.jsonPrimitive?.content
        val got: JsonElement = try {
            if (fn == "parse_tab_page") {
                tab(if (asText != null) HarpTabsPages.parseTabPage(asText, url) else HarpTabsPages.parseTabPage(Scenarios.body(html), url))
            } else {
                page(if (asText != null) HarpTabsPages.parseArtistPage(asText, url) else HarpTabsPages.parseArtistPage(Scenarios.body(html), url))
            }
        } catch (e: NotImplementedError) {
            throw e
        } catch (e: Exception) {
            raised(e)
        }
        val want = r["out"] ?: r["raises"]?.jsonObject?.let(::shownAsKotlin) ?: JsonNull
        misses.check(got == want) { "$fn(${html.toString().take(100)}) = $got, Python's $want" }
    }

    /** What stands on the phone for each exception Python's records name. */
    private val RAISES = mapOf("ValueError" to "IllegalArgumentException")

    private fun shownAsKotlin(raises: JsonObject): JsonObject {
        val type = text(raises.getValue("type"))
        return obj("type" to JsonPrimitive(RAISES[type] ?: type), "message" to raises.getValue("message"))
    }

    private fun raised(e: Exception): JsonObject =
        obj("type" to JsonPrimitive(e::class.simpleName ?: "?"), "message" to JsonPrimitive(e.message ?: ""))

    // --- what a record holds ------------------------------------------------------------------------------------------

    private fun str(s: String?): JsonElement = s?.let { JsonPrimitive(it) } ?: JsonNull
    private fun obj(vararg members: Pair<String, JsonElement>) = JsonObject(linkedMapOf(*members))
    private fun text(e: JsonElement): String = e.jsonPrimitive.content

    fun tab(t: HarpTabsPages.HarpTab): JsonObject = obj(
        "title" to JsonPrimitive(t.title), "artist" to str(t.artist), "body" to JsonPrimitive(t.body),
        "key" to str(t.key), "harp" to str(t.harp), "difficulty" to str(t.difficulty), "views" to JsonPrimitive(t.views),
        "rating" to (t.rating?.let(PyJson::float) ?: JsonNull), "raw" to t.raw(),
    )

    fun page(p: HarpArtistPage?): JsonElement = if (p == null) JsonNull else obj(
        "name" to JsonPrimitive(p.name), "tabs" to JsonPrimitive(p.tabs),
        "listed" to JsonArray(p.listed.map { t ->
            obj("tab_id" to JsonPrimitive(t.tabId), "path" to JsonPrimitive(t.path), "title" to JsonPrimitive(t.title),
                "key" to str(t.key), "difficulty" to str(t.difficulty), "views" to JsonPrimitive(t.views),
                "rating" to (t.rating?.let(PyJson::float) ?: JsonNull))
        }),
    )

    fun stats(s: HarpTabsStats): JsonObject = obj(
        "tried" to JsonPrimitive(s.tried), "errors" to JsonPrimitive(s.errors),
        "budget_exhausted" to JsonPrimitive(s.budgetExhausted),
        "failures" to JsonArray(s.failures.map { (song, e) ->
            JsonArray(listOf(JsonPrimitive(song.id), JsonPrimitive(e::class.simpleName), JsonPrimitive(e.message)))
        }),
        "sitemaps" to JsonPrimitive(s.sitemaps), "kept" to JsonPrimitive(s.kept), "missing" to JsonPrimitive(s.missing),
    )

    private fun records(name: String): List<JsonObject> = Corpus.lines(name).filter { it["header"] != JsonPrimitive(true) }

    // --- the scenarios ------------------------------------------------------------------------------------------------

    /** A scenario record replayed, [pass] its call in the record's world; every request's user agent the record's
     * `agent`, and the pages noted for the next push its `reads`, checked then forgotten. */
    private fun scenario(misses: Misses, r: JsonObject, pass: (ScenarioWorld) -> Any?) = guarded {
        val now = Instant.parse(text(r.getValue("now")))
        Scenarios.replay(r, misses, eventLog = { db, run -> EventLog(db, run) { now } }) { world ->
            var parsedNothing = false
            try {
                pass(world)
            } catch (e: NotImplementedError) {  // core.html not there yet: the record waits, nothing compared
                parsedNothing = true
                throw e
            } finally {
                if (!parsedNothing) checked(misses, r, world)
            }
        }
    }

    private fun checked(misses: Misses, r: JsonObject, world: ScenarioWorld) {
        val agent = r["agent"]?.let(::text)
        for (request in world.transport.requests) {
            val sent = request.headers.filter { it.first.equals("User-Agent", ignoreCase = true) }.map { it.second }
            misses.check(agent != null && sent == listOf(agent)) {
                "${r["case"]}: ${request.url} sent as $sent, Python's agent $agent"
            }
        }
        noted(misses, world.db, r, text(r.getValue("now")))
    }

    private fun noted(misses: Misses, db: Db, r: JsonObject, stamp: String) {
        val notes = db.query("SELECT key, value FROM kv WHERE key >= ? AND key < ? ORDER BY key", Reads.READ,
                             Reads.READ.dropLast(1) + ";") { it.text(0)!! to it.text(1)!! }
        val want = (r["reads"] as? JsonArray ?: JsonArray(emptyList())).map { "${Reads.READ}harptabs:${text(it)}" to stamp }
        misses.check(notes == want) { "${r["case"]}: the phone noted $notes, the pages stored $want" }
        for ((key, _) in notes) db.kvDelete(key)
    }

    private fun only(r: JsonObject): Set<Long> = r.getValue("kw").jsonObject.getValue("only").jsonArray.map { it.jsonPrimitive.long }.toSet()

    fun lookups(misses: Misses) {
        for (r in records(LOOKUP)) {
            when (text(r.getValue("fn"))) {
                "caracole.harptabs_fetch.harptabs_tabs" -> scenario(misses, r) { w ->
                    stats(HarpTabsFetch.harptabsTabs(w.db, w.clients.getValue("harptabs"), LibraryStore(w.library), w.now,
                                                     Overrides.read(w.db), only(r)))
                }
                "caracole.get._Lookup.harptabs" -> scenario(misses, r) { w ->
                    val song = Songs.byId(w.db, only(r).single())!!
                    val ctx = StageContext(w.db, song, Overrides.read(w.db), PhoneConfig.read(w.db), LibraryStore(w.library),
                                           Envelope(w.db, w.clients, w.now), w.now)
                    HarpTabsStage.run(ctx).let { JsonArray(listOf(JsonPrimitive(it.state), JsonPrimitive(it.detail))) }
                }
                else -> throw AssertionError("no harptabs lookup record of ${r["fn"]}")
            }
        }
    }

    fun artists(misses: Misses) {
        for (r in records(ARTIST)) {
            when (text(r.getValue("fn"))) {
                "caracole.harptabs_index.read_artist" -> scenario(misses, r) { w ->
                    page(HarpTabsFetch.readArtist(w.db, w.clients.getValue("harptabs"),
                                                  text(r.getValue("kw").jsonObject.getValue("path")), w.now))
                }
                "caracole.harptabs_index.artist_paths" -> paths(misses, r)
                else -> throw AssertionError("no harptabs artist record of ${r["fn"]}")
            }
        }
    }

    private fun paths(misses: Misses, r: JsonObject) {
        val dir = Files.createTempDirectory("caracole-harptabs").toFile()
        try {
            TestDb.fresh(dir).use { database ->
                database.writeBlocking { db ->
                    Fixtures.loadRecords(db, r.getValue("fixture").jsonArray.map { it.jsonObject })
                    for (case in r.getValue("cases").jsonArray) {
                        val (name, want) = case.jsonArray
                        val got = JsonArray(HarpTabsFetch.artistPaths(db, text(name)).map { JsonPrimitive(it) })
                        misses.check(got == want) { "artist_paths(${PyJson.dumps(name)}) = $got, Python's $want" }
                    }
                }
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    fun commands(misses: Misses) {
        for (r in records(COMMANDS)) {
            scenario(misses, r) { w ->
                val lines = ArrayList<String>()
                val c = object : CommandContext {
                    override val db = w.db
                    override val asking = Envelope(w.db, w.clients, w.now)
                    override val now = w.now
                    override fun say(line: String) {
                        lines += line
                    }
                }
                lines += HarpTabsCommands.artist(c, text(r.getValue("kw").jsonObject.getValue("artist")))
                JsonArray(lines.map { JsonPrimitive(it) })
            }
        }
    }

    /**
     * A lookup's asking in a scenario, as lane lookup's InteractiveAsk asks: a provider turned off ([Asked.Off], in
     * get.py's words) or cooling down after a block ([Asked.Cooling]) is sent nothing; a block cools it down
     * (Health.recordBlock, [Asked.Blocked]); a spent budget is [Asked.Spent], the hour's when the client's budget was
     * below `lookup_requests`; any other provider error is recorded (Health.recordError) and [Asked.Failed].
     */
    class Envelope(private val db: Db, private val clients: Map<String, Client>, private val now: Instant) : Asking {
        override fun <T> ask(provider: String, policy: ProviderPolicy?, work: (Client) -> T): Asked<T> {
            val config = PhoneConfig.read(db).provider(provider)
            if (!config.enabled) return Asked.Off("${NAMES[provider] ?: provider} is off in caracole.toml")
            if (Health.isCooling(db, provider, now)) return Asked.Cooling(Health.state(db, provider).cooldownUntil)
            val client = clients[provider] ?: throw AssertionError("the record has no client of $provider")
            if (policy != null) client.policy = policy
            return try {
                Asked.Done(work(client))
            } catch (e: ProviderBlocked) {
                Asked.Blocked(e, Health.recordBlock(db, e.provider, now, e.message ?: ""))
            } catch (_: BudgetExhausted) {
                Asked.Spent(hour = client.policy.budget < config.lookupRequests, keptForSheets = false)
            } catch (e: ProviderError) {
                Health.recordError(db, e.provider, now, e.message ?: "")
                Asked.Failed(e)
            }
        }

        override val requests: Map<String, Int> get() = clients.mapValues { it.value.requestsMade }

        private companion object {
            val NAMES = mapOf("harptabs" to "harptabs.com")
        }
    }
}
