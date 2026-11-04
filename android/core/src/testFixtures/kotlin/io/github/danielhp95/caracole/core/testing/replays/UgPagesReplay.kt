package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.html.Html
import io.github.danielhp95.caracole.core.http.CachedAnswers
import io.github.danielhp95.caracole.core.http.PageParseError
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.Scenarios
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.ug.ArtistTabs
import io.github.danielhp95.caracole.core.ug.IndexTab
import io.github.danielhp95.caracole.core.ug.UgArtist
import io.github.danielhp95.caracole.core.ug.UgArtistPage
import io.github.danielhp95.caracole.core.ug.UgLookup
import io.github.danielhp95.caracole.core.ug.UgPage
import io.github.danielhp95.caracole.core.ug.UgTabPage
import io.github.danielhp95.caracole.core.ug.UgVersion
import io.github.danielhp95.caracole.core.ug.internal.pages.PyValues
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
import org.junit.Assert.assertTrue
import java.nio.file.Files
import java.security.MessageDigest

/**
 * UG's tab and artist pages, the index's reads and the artist pages' tabs kept (vectors/sites/ug_pages.jsonl,
 * ug_artist.jsonl, ug_artist_tabs.jsonl, ug_pages_lookup.jsonl; tests/test_conformance_ug_pages.py) answered by
 * core.ug as Python answered them. UgPageTest, UgArtistTest and ArtistTabsStoreTest call each part on the JVM;
 * CorpusOnDeviceTest runs them all under ART.
 *
 * The phone notes each page a store keeps tabs of for the next push to the computer (kv `phone:read:ug:<page>`, the
 * newest read stored), which Python doesn't: checked here, and left out of the kv compared with Python's.
 */
object UgPagesReplay : AreaReplay {
    override val area = "ug-pages"

    /** Phase A guard: core.html is lane html-tree's, and until it merges a page can't be parsed; the records of a
     * page parsed wait on it (waiting on html-tree). */
    val htmlReady: Boolean by lazy { runCatching { Html.parse("<p>") }.isSuccess }

    /** Phase A guard: the backfill's known pages read overrides.artist_page_address, lane overrides-model's
     * (waiting on overrides-model). */
    val overrideUrlsReady: Boolean by lazy { runCatching { OverrideUrls.artistPageAddress("x") }.isSuccess }

    override fun replay(misses: Misses) {
        pages()
        artists()
        artistTabs()
        lookup()
    }

    // --- what a record holds ---------------------------------------------------------------------------------

    private fun sha256(text: String): String = MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8))
        .joinToString("") { b -> "%02x".format(b.toInt() and 0xff) }

    private fun indented(value: JsonElement): String = PyJson.dumps(value, indent = 2)

    private fun str(s: String?): JsonElement = s?.let { JsonPrimitive(it) } ?: JsonNull

    fun version(v: UgVersion): JsonObject = JsonObject(linkedMapOf(
        "tab_id" to JsonPrimitive(v.tabId), "song_id" to (v.songId?.let { JsonPrimitive(it) } ?: JsonNull),
        "song_name" to str(v.songName), "artist_name" to str(v.artistName), "type" to str(v.type),
        "part" to str(v.part), "version" to JsonPrimitive(v.version), "rating" to str(PyValues.floatRepr(v.rating)),
        "votes" to JsonPrimitive(v.votes), "access" to str(v.access), "url" to str(v.url),
        "description" to str(v.description), "is_acoustic" to JsonPrimitive(v.isAcoustic), "kind" to str(v.kind),
        "label" to str(v.label), "raw_sha256" to str(sha256(indented(v.raw))),
    ))

    private const val RAW_WHOLE = 2000

    private fun textOrDigest(text: String): JsonElement {
        val size = text.toByteArray(Charsets.UTF_8).size
        return if (size <= RAW_WHOLE) JsonPrimitive(text)
        else JsonObject(linkedMapOf("sha256" to JsonPrimitive(sha256(text)), "size" to JsonPrimitive(size)))
    }

    fun tabPage(p: UgTabPage): JsonObject = JsonObject(linkedMapOf(
        "tab" to version(p.tab), "versions" to JsonArray(p.versions.map { version(it) }), "content" to str(p.content),
        "meta" to str(indented(p.meta)), "raw" to textOrDigest(indented(p.raw)), "artist_url" to str(p.artistUrl),
    ))

    fun artistPage(p: UgArtistPage): JsonObject = JsonObject(linkedMapOf(
        "artist_id" to JsonPrimitive(p.artistId), "name" to str(p.name), "tabs" to JsonArray(p.tabs.map { version(it) }),
        "page" to JsonPrimitive(p.page), "pages" to JsonPrimitive(p.pages),
        "filters" to JsonArray(p.filters.sorted().map { JsonPrimitive(it) }),
    ))

    /** A record's body: Scenarios.body's, or `{"before", "repeat", "times", "after"}`. */
    fun body(spec: JsonElement): ByteArray {
        val o = spec.jsonObject
        if ("repeat" !in o) return Scenarios.body(spec)
        val text = o.getValue("before").jsonPrimitive.content +
            o.getValue("repeat").jsonPrimitive.content.repeat(o.getValue("times").jsonPrimitive.int) +
            o.getValue("after").jsonPrimitive.content
        return text.toByteArray(Charsets.UTF_8)
    }

    /** The first place [got] differs from [want], or null. */
    fun difference(path: String, want: JsonElement?, got: JsonElement?): String? {
        if (want is JsonObject && got is JsonObject) {
            for (k in (want.keys + got.keys)) difference("$path.$k", want[k], got[k])?.let { return it }
            return null
        }
        if (want is JsonArray && got is JsonArray) {
            if (want.size != got.size) return "$path: ${got.size} items, Python's ${want.size}"
            want.indices.forEach { i -> difference("$path[$i]", want[i], got[i])?.let { return it } }
            return null
        }
        return if (want == got) null else "$path = ${got.toString().take(300)}, Python's ${want.toString().take(300)}"
    }

    /** A parser's record: what [parse] made of the record's body, or what it raised. */
    private fun parsed(misses: Misses, r: Record, parse: (ByteArray, String?) -> JsonElement) {
        val case = r.extra["case"]?.jsonPrimitive?.content ?: r.fn
        val url = (r.kw["url"] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content
        val got = try {
            parse(body(r.args[0]), url)
        } catch (e: PageParseError) {
            val words = "PageParseError: ${e.message}"
            val ok = if (r.extra["recursion"] == JsonPrimitive(true)) {
                e.cause is PyJson.RecursionError && words.startsWith(r.err ?: "\u0000")
            } else {
                words == r.err
            }
            misses.check(ok) { "$case: raised $words (${e.cause}), Python ${r.err ?: "answered"}" }
            return
        } catch (e: IllegalArgumentException) {
            misses.check("ValueError: ${e.message}" == r.err) { "$case: raised ${e.message}, Python ${r.err ?: "answered"}" }
            return
        }
        if (r.err != null) {
            misses.check(false) { "$case: answered ${got.toString().take(200)}, Python raised ${r.err}" }
            return
        }
        val differs = difference(case, r.out, got)
        misses.check(differs == null) { differs!! }
    }

    // --- ug_pages.jsonl ----------------------------------------------------------------------------------------

    fun pages() {
        val misses = Misses("sites/ug_pages.jsonl")
        var pages = 0
        for (r in Corpus.records("sites/ug_pages.jsonl")) {
            when (r.fn) {
                "caracole.ug.page.parse_tab_page" -> {
                    if (!htmlReady) continue  // waiting on html-tree
                    pages++
                    parsed(misses, r) { html, url -> tabPage(UgPage.parseTabPage(html, url)) }
                }
                "caracole.ug.page.parse_version" -> batch(misses, r) { text ->
                    UgPage.parseVersion(PyJson.loads(text.jsonPrimitive.content))?.let { version(it) } ?: JsonNull
                }
                "caracole.ug.page._number" -> batch(misses, r) { text ->
                    PyValues.number(PyJson.loads(text.jsonPrimitive.content))?.let { JsonPrimitive(PyValues.floatRepr(it)) }
                        ?: JsonNull
                }
                "caracole.ug.page.json_int" -> batch(misses, r) { text ->
                    UgPage.jsonInt(PyJson.loads(text.jsonPrimitive.content))?.let { JsonPrimitive(it) } ?: JsonNull
                }
                "caracole.ug.page.kind_of" -> batch(misses, r) { s ->
                    str(UgPage.kindOf((s as? JsonPrimitive)?.takeIf { it.isString }?.content))
                }
                "caracole.ug.page.page_url" -> batch(misses, r) { pair ->
                    val (id, path) = pair.jsonArray
                    str(UgPage.pageUrl(id.jsonPrimitive.long, (path as? JsonPrimitive)?.takeIf { it.isString }?.content))
                }
                "caracole.ug.page.strip_markup" -> batch(misses, r) { s -> str(UgPage.stripMarkup(s.jsonPrimitive.content)) }
                "caracole.ug.page.decode_twice" -> batch(misses, r) { s -> str(UgPage.decodeTwice(s.jsonPrimitive.content)) }
                else -> throw AssertionError("sites/ug_pages.jsonl: no replay for ${r.fn}")
            }
        }
        if (htmlReady) assertTrue("tab pages replayed: $pages", pages >= 60)
        misses.assertNone()
    }

    /** A batch record: each input of `args[0]` answered as `out` says, in order. */
    private fun batch(misses: Misses, r: Record, answer: (JsonElement) -> JsonElement) {
        val inputs = r.args[0].jsonArray
        val outs = r.out!!.jsonArray
        misses.check(inputs.size == outs.size) { "${r.fn}: ${inputs.size} inputs, ${outs.size} answers" }
        inputs.forEachIndexed { i, input ->
            val got = try {
                answer(input)
            } catch (e: IllegalArgumentException) {
                JsonObject(mapOf("err" to JsonPrimitive("ValueError: ${e.message}")))
            }
            val differs = difference("${r.fn}(${input.toString().take(80)})", outs[i], got)
            misses.check(differs == null) { differs!! }
        }
    }

    // --- ug_artist.jsonl ---------------------------------------------------------------------------------------

    fun artists() {
        val misses = Misses("sites/ug_artist.jsonl")
        var pages = 0
        for (r in Corpus.records("sites/ug_artist.jsonl")) {
            when (r.fn) {
                "caracole.ug.artist.parse_artist_page" -> {
                    if (!htmlReady) continue  // waiting on html-tree
                    pages++
                    parsed(misses, r) { html, url -> artistPage(UgArtist.parse(html, url)) }
                }
                "caracole.ug.artist.artist_page_url" -> batch(misses, r) { call ->
                    val (base, kind, page) = call.jsonArray
                    str(UgArtist.pageUrl(base.jsonPrimitive.content,
                                         (kind as? JsonPrimitive)?.takeIf { it.isString }?.content, page.jsonPrimitive.int))
                }
                else -> throw AssertionError("sites/ug_artist.jsonl: no replay for ${r.fn}")
            }
        }
        if (htmlReady) assertTrue("artist pages replayed: $pages", pages >= 30)
        misses.assertNone()
    }

    // --- ug_artist_tabs.jsonl ---------------------------------------------------------------------------------

    private fun rows(db: Db): JsonArray {
        val columns = db.query("PRAGMA main.table_info(ug_artist_tabs)") { it.text(1)!! }
        val select = columns.joinToString(", ") { "typeof(\"$it\"), \"$it\"" }
        return JsonArray(db.query("SELECT $select FROM ug_artist_tabs ORDER BY rowid") { row ->
            JsonObject(columns.withIndex().associate { (i, column) ->
                column to when (row.text(2 * i)) {
                    "null" -> JsonNull
                    "integer" -> JsonPrimitive(row.long(2 * i + 1)!!)
                    "real" -> PyJson.float(row.double(2 * i + 1)!!)
                    else -> JsonPrimitive(row.text(2 * i + 1)!!)
                }
            })
        })
    }

    private fun kv(db: Db): Map<String, String> =
        db.query("SELECT key, value FROM kv") { it.text(0)!! to it.text(1)!! }.toMap()

    private fun notes(db: Db): Map<String, String> =
        kv(db).filterKeys { it.startsWith("${Reads.READ}ug:") }.mapKeys { it.key.removePrefix("${Reads.READ}ug:") }

    fun artistTabs() {
        val misses = Misses("sites/ug_artist_tabs.jsonl")
        var ops = 0
        for (line in Corpus.lines("sites/ug_artist_tabs.jsonl")) {
            if (line["header"] == JsonPrimitive(true)) continue
            when (line.getValue("fn").jsonPrimitive.content) {
                "caracole.ug.artist_tabs.ops" -> ops += replayOps(misses, line)
                "caracole.ug.artist_tabs.backfill" -> {
                    if (!htmlReady || !overrideUrlsReady) continue  // waiting on html-tree and overrides-model
                    backfill(misses, line)
                }
                else -> throw AssertionError("sites/ug_artist_tabs.jsonl: no replay for ${line["fn"]}")
            }
        }
        assertTrue("ops replayed: $ops", ops >= 15)
        misses.assertNone()
    }

    /** One `ops` record: its database, each op in turn, what each came to; how many ops it replayed. */
    private fun replayOps(misses: Misses, record: JsonObject): Int {
        val case = record.getValue("case").jsonPrimitive.content
        val ops = record.getValue("ops").jsonArray.map { it.jsonObject }
        if (!htmlReady && ops.any { it.getValue("op").jsonPrimitive.content == "store_page" }) return 0  // waiting on html-tree
        val outs = record.getValue("out").jsonArray.map { it.jsonObject }
        val dir = Files.createTempDirectory("caracole-ug-pages").toFile()
        try {
            TestDb.fresh(dir).use { database ->
                database.writeBlocking { db ->
                    db.execute("DELETE FROM kv WHERE key != 'sync:id'")
                    Fixtures.loadRecords(db, record.getValue("fixture").jsonArray.map { it.jsonObject }, null, case)
                    val noted = LinkedHashMap<String, String>()
                    var rows = rows(db)
                    ops.forEachIndexed { n, op ->
                        val what = "$case, op $n (${op.getValue("op").jsonPrimitive.content})"
                        val want = outs[n]
                        val before = kv(db)
                        val result = runOp(db, op)
                        misses.check(Scenarios.json(result) == want["result"]) { "$what: ${Scenarios.json(result)}, Python's ${want["result"]}" }
                        val after = kv(db)
                        val changed = (before.keys + after.keys).filter { !it.startsWith(Reads.READ) && before[it] != after[it] }
                            .associateWith { k -> after[k]?.let { JsonPrimitive(it) } ?: JsonNull }
                        misses.check(JsonObject(changed) == want["kv"]) { "$what: kv $changed, Python's ${want["kv"]}" }
                        if (want["rows"] != JsonNull) rows = want.getValue("rows").jsonArray
                        val differs = difference("$what: ug_artist_tabs", rows, rows(db))
                        misses.check(differs == null) { differs!! }
                        val kind = op.getValue("op").jsonPrimitive.content
                        if (kind.startsWith("store") && want["result"]!!.jsonArray.isNotEmpty()) {
                            val page = op.getValue("page").jsonPrimitive.content
                            val at = op.getValue("read_at").jsonPrimitive.content
                            if (noted[page].let { it == null || at > it }) noted[page] = at
                        }
                        misses.check(notes(db) == noted) { "$what: the pages noted ${notes(db)}, the stores' $noted" }
                    }
                }
            }
        } finally {
            dir.deleteRecursively()
        }
        return ops.size
    }

    private fun runOp(db: Db, op: JsonObject): Any? {
        fun text(k: String) = op.getValue(k).jsonPrimitive.content
        return when (text("op")) {
            "store" -> ArtistTabs.store(db, text("page"), text("name"),
                                        op.getValue("tabs").jsonArray.mapNotNull { UgPage.parseVersion(it) }, text("read_at"))
            "store_page" -> {
                val listed = UgArtist.parse(body(op.getValue("body")), text("page"))
                val kind = (op["kind"] as? JsonPrimitive)?.takeIf { it.isString }?.content
                ArtistTabs.store(db, text("page"), listed.name, listed.tabs.filter { kind == null || it.kind == kind },
                                 text("read_at"))
            }
            "keep_only" -> ArtistTabs.keepOnly(db, text("page"), text("kind"),
                                               op.getValue("ids").jsonArray.map { it.jsonPrimitive.long }, text("read_at"))
            "forget" -> ArtistTabs.forget(db, text("page")).let { null }
            else -> throw AssertionError("no op ${op["op"]}")
        }
    }

    /** A backfill's scenario: the cache's pages stored, nothing sent; the pages it stored tabs of noted. */
    private fun backfill(misses: Misses, record: JsonObject) {
        val pasted = record.getValue("kw").jsonObject.getValue("artist_url").jsonObject
            .mapValues { it.value.jsonPrimitive.content }
        Scenarios.replay(record, misses) { world ->
            val stored = ArtistTabs.backfill(world.db, CachedAnswers("ug", world.cacheDir), Overrides(artistUrl = pasted))
            val pages = world.db.query("SELECT page, MAX(read_at) FROM ug_artist_tabs GROUP BY page") {
                it.text(0)!! to it.text(1)!!
            }.toMap()
            misses.check(notes(world.db) == pages) { "${record["case"]}: the pages noted ${notes(world.db)}, stored $pages" }
            world.db.execute("DELETE FROM kv WHERE key >= ? AND key < ?", Reads.READ, Reads.READ.dropLast(1) + ";")
            stored
        }
    }

    // --- ug_pages_lookup.jsonl -----------------------------------------------------------------------------------

    private fun indexTab(t: IndexTab?): JsonElement = t?.let {
        JsonObject(linkedMapOf("tab_id" to JsonPrimitive(it.tabId), "type" to str(it.type), "song_key" to str(it.songKey),
                               "label" to str(it.label), "path" to str(it.path), "url" to str(it.url)))
    } ?: JsonNull

    fun lookup() {
        val misses = Misses("sites/ug_pages_lookup.jsonl")
        for (line in Corpus.lines("sites/ug_pages_lookup.jsonl")) {
            if (line["header"] == JsonPrimitive(true)) continue
            val dir = Files.createTempDirectory("caracole-ug-lookup").toFile()
            try {
                TestDb.fresh(dir).use { database ->
                    database.writeBlocking { db ->
                        Fixtures.loadRecords(db, line.getValue("fixture").jsonArray.map { it.jsonObject })
                        for (call in line.getValue("calls").jsonArray.map { it.jsonObject }) {
                            val fn = call.getValue("fn").jsonPrimitive.content
                            val args = call.getValue("args").jsonArray
                            fun s(i: Int) = args[i].jsonPrimitive.content
                            val got: JsonElement = when (fn) {
                                "song_tabs" -> JsonArray(UgLookup.songTabs(db, s(0), s(1)).map { indexTab(it) })
                                "artist_known" -> JsonPrimitive(UgLookup.artistKnown(db, s(0)))
                                "index_tab" -> indexTab(UgLookup.indexTab(db, args[0].jsonPrimitive.long))
                                "tab_url_for" -> str(UgLookup.tabUrlFor(db, args[0].jsonPrimitive.long))
                                "artist_tabs" -> JsonArray(
                                    (if (args.size > 1) UgLookup.artistTabs(db, s(0), args[1].jsonPrimitive.int)
                                     else UgLookup.artistTabs(db, s(0))).map { indexTab(it) })
                                "learned_artist_url" -> str(UgLookup.learnedArtistUrl(db, s(0)))
                                "remember_artist_url" -> UgLookup.rememberArtistUrl(db, s(0), s(1)).let { JsonNull }
                                "forget_artist_url" -> UgLookup.forgetArtistUrl(db, s(0)).let { JsonNull }
                                else -> throw AssertionError("sites/ug_pages_lookup.jsonl: no replay for $fn")
                            }
                            val differs = difference("$fn$args", call["out"], got)
                            misses.check(differs == null) { differs!! }
                        }
                    }
                }
            } finally {
                dir.deleteRecursively()
            }
        }
        assertTrue("calls replayed: ${misses.checked}", misses.checked >= 30)
        misses.assertNone()
    }
}
