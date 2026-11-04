package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.viewer.ViewerAssets
import io.github.danielhp95.caracole.viewer.ViewerData
import io.github.danielhp95.caracole.viewer.harp.Harp
import io.github.danielhp95.caracole.viewer.harpfit.Choice
import io.github.danielhp95.caracole.viewer.harpfit.Fit
import io.github.danielhp95.caracole.viewer.harpfit.HarmonicaTab
import io.github.danielhp95.caracole.viewer.harpfit.HarpFit
import io.github.danielhp95.caracole.viewer.harptab.HarpTabs
import io.github.danielhp95.caracole.viewer.harptab.Tab
import io.github.danielhp95.caracole.viewer.pages.HarmonicaPage
import kotlinx.serialization.json.Json
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

/**
 * viewer/harpfit.py and viewer/harptab_page.py (vectors/viewer/harpfit*.jsonl, harmonica_pages*.jsonl), every record
 * answered by :viewer's HarpFit and HarmonicaPage as Python answered it: HarpFitTest's and HarmonicaPageTest's record
 * loops on the JVM, CorpusOnDeviceTest's on the device. tests/test_conformance_viewer_harmonica.py's docstring says
 * each record's shape. A value is compared as the text `json.dumps` writes of it, its members sorted (so a float is
 * Python's repr, to the bit); a digest is the first 8 hex digits of the SHA-256 of a value's compact `json.dumps`, or
 * the first 16 of an HTML text's UTF-8.
 *
 * Phase A: a record that reads a tab (HarpTabs.parse, lane harptab-layout's) or writes a page (SheetPage's frame,
 * lane pages') is counted in [waiting] while its producer hasn't merged (its NotImplementedError); the JVM tests
 * assume none is.
 */
object HarmonicaPageReplay : AreaReplay {
    override val area = "harmonica-page"

    private const val H = "test_conformance_viewer_harmonica."
    private const val F = "caracole.viewer.harpfit."
    private const val P = "caracole.viewer.harptab_page."

    /** Phase A: the records whose producer hasn't merged (waiting on lanes harptab-layout and pages). */
    @Volatile var waiting = 0
        private set

    override fun replay(misses: Misses) {
        data(misses)
        harpfit()
        pages()
        whole()
    }

    /** What the data says that Kotlin also states. */
    fun data(misses: Misses) {
        val data = ViewerData.table("harmonica_page")
        misses.check(HarpFit.WHY == listOf("record", "tab", "page", "song", "usual")) { "WHY: ${HarpFit.WHY}" }
        val said = data.getValue("harptab_page").jsonObject.getValue("_SAID").jsonObject.keys.toList()
        misses.check(said == HarpFit.WHY) { "_SAID's keys: $said" }
        misses.check(HarmonicaPage.BAR.contains("id=\"h-down\"") && !HarmonicaPage.BAR_RAW.contains("id=\"h-down\"")) {
            "the bar of a tab shown as written has no harp"
        }
    }

    private val texts: Map<String, String> by lazy {
        Corpus.records("viewer/harpfit_texts.jsonl").associate { it.args[0].jsonPrimitive.content to it.out!!.jsonPrimitive.content }
    }

    /** A record's text: a fixture's, or one of harpfit_texts.jsonl's. */
    fun text(ref: JsonElement): String {
        val o = ref.jsonObject
        o["fixture"]?.let { return String(Corpus.fixture(it.jsonPrimitive.content), Charsets.UTF_8) }
        return texts.getValue(o.getValue("named").jsonPrimitive.content)
    }

    private fun textOrNull(ref: JsonElement): String? = if (ref is JsonNull) null else text(ref)

    private fun string(e: JsonElement?): String? = (e as? JsonPrimitive)?.takeIf { it !is JsonNull && it.isString }?.content

    private fun tab(row: JsonElement): Tab = HarpTabs.parse(text(row.jsonArray[0]), harp = string(row.jsonArray[1]))

    // --- harpfit -------------------------------------------------------------------------------------------------

    fun harpfit() = replay("viewer/harpfit.jsonl", 5) { record, misses ->
        when (record.fn) {
            F + "pitch" -> each(misses, record) { JsonPrimitive(HarpFit.pitch(string(it))) }
            F + "words" -> each(misses, record) { JsonArray(HarpFit.words(it.jsonPrimitive.content).map(::JsonPrimitive)) }
            F + "_sheet_lines" -> {
                val lines = linesJson(HarpFit.sheetLines(text(record.args[0])))
                val want = record.out!!
                if (want is JsonObject) {
                    misses.check(short(lines) == want.getValue("digest").jsonPrimitive.content &&
                                     lines.size == want.getValue("lines").jsonPrimitive.int) {
                        "_sheet_lines(${record.args[0]}): ${dumps(lines).take(400)}, whose digest isn't Python's"
                    }
                } else same(misses, "_sheet_lines(${record.args[0]})", want, lines)
            }
            H + "fit_of" -> waitingOn(misses) {
                val tab = tab(record.args[0])
                val cho = textOrNull(record.args[1])
                val fitted = if (cho != null) HarpFit.recordFit(tab, cho) else emptyList()
                val choices = record.args[2].jsonArray.map { case ->
                    val (key, source, page) = case.jsonArray.map(::string)
                    choiceRow(HarpFit.choose(tab, cho, key, source, page), fitted, misses)
                }
                same(misses, "fit_of(${record.args.toString().take(160)})", record.out!!,
                     JsonObject(mapOf("record_fit" to fitsJson(fitted), "choices" to JsonArray(choices))))
            }
            "caracole.render._tab_harps" -> waitingOn(misses) {
                val tabs = record.args[0].jsonArray.map { e ->
                    val (name, ref, chip, pageKey, pin) = e.jsonArray
                    HarmonicaTab(name.jsonPrimitive.content, textOrNull(ref), string(chip), string(pageKey),
                                 pin.takeIf { it !is JsonNull })
                }
                val got = HarpFit.tabHarps(tabs, text(record.args[1]), string(record.args[2]), string(record.args[3]))
                same(misses, "_tab_harps(${record.args.toString().take(160)})", record.out!!,
                     JsonObject(got.mapValues { JsonPrimitive(it.value) }))
            }
            else -> misses.check(false) { "an unknown record: ${record.fn}" }
        }
    }

    private fun linesJson(lines: List<List<Pair<String, Set<Int>?>>>): JsonArray = JsonArray(lines.map { line ->
        JsonArray(line.map { (w, chord) ->
            JsonArray(listOf(JsonPrimitive(w), chord?.let { c -> JsonArray(c.sorted().map(::JsonPrimitive)) } ?: JsonNull))
        })
    })

    private fun fitsJson(fits: List<Fit>): JsonArray = JsonArray(fits.map {
        JsonArray(listOf(JsonPrimitive(it.harp), PyJson.float(it.share), JsonPrimitive(it.notes)))
    })

    private fun choiceRow(c: Choice, fitted: List<Fit>, misses: Misses): JsonArray {
        misses.check(c.fits.isEmpty() || c.fits == fitted) { "a choice's fits aren't record_fit's: ${c.fits}" }
        return JsonArray(listOf(JsonPrimitive(c.harp), JsonPrimitive(c.why), JsonPrimitive(c.fits.isNotEmpty()),
                                JsonPrimitive(c.named), JsonPrimitive(c.page), JsonPrimitive(c.tonic), JsonPrimitive(c.tabsHarp)))
    }

    // --- the pages -----------------------------------------------------------------------------------------------

    fun pages() = replay("viewer/harmonica_pages.jsonl", 6) { record, misses ->
        when (record.fn) {
            P + "_a" -> each(misses, record) { JsonPrimitive(HarmonicaPage.a(it.jsonPrimitive.content)) }
            P + "_harp_lines" -> each(misses, record) { JsonPrimitive(HarmonicaPage.harpLines(choiceOf(it.jsonArray))) }
            P + "_footer" -> each(misses, record) { e ->
                val (file, url, placed, change) = e.jsonArray
                JsonPrimitive(HarmonicaPage.footer(file.jsonPrimitive.content, string(url), placed.jsonPrimitive.boolean,
                                                   change.jsonPrimitive.boolean))
            }
            P + "_read_as" -> waitingOn(misses) {
                val (tabRow, pin, facts) = record.args
                val body = text(tabRow.jsonArray[0])
                val notation = if (pin is JsonNull) null else runCatching { HarpTabs.pinned(pin, body) }
                    .getOrElse { if (it is IllegalArgumentException) null else throw it }
                val tab = HarpTabs.parse(body, harp = string(tabRow.jsonArray[1]), notation = notation)
                val want = record.out!!.jsonArray
                for ((k, f) in facts.jsonArray.withIndex()) {
                    val html = HarmonicaPage.readAs(tab.reading, f.jsonObject)
                    val expected = want[k].jsonPrimitive.content
                    val ok = if (k < 2) html == expected else sha(html).take(16) == expected
                    misses.check(ok) { "_read_as(${tabRow.jsonArray[0]}, $pin, $f): $html, Python's $expected" }
                }
            }
            P + "_overlay_data" -> {
                val (choice, sheet, key, source) = record.args
                val found = HarmonicaPage.overlayData(choiceOf(choice.jsonArray), textOrNull(sheet), string(key), string(source))
                same(misses, "_overlay_data(${record.args.toString().take(160)})", record.out!!,
                     JsonObject(found.mapValues { JsonPrimitive(members(it.value)) }))
            }
            P + "build_harmonica_viewer" -> waitingOn(misses) {
                val html = build(record)
                same(misses, "build_harmonica_viewer(${record.args[0]}, ${record.kw.toString().take(200)})", record.out!!,
                     pageOut(html))
            }
            else -> misses.check(false) { "an unknown record: ${record.fn}" }
        }
    }

    /** A page kept whole: its pieces, the assets read as ViewerAssets reads them, are the page. */
    fun whole() = replay("viewer/harmonica_pages_whole.jsonl", 1) { record, misses ->
        waitingOn(misses) {
            val want = record.extra.getValue("pieces").jsonArray.joinToString("") { piece ->
                if (piece is JsonObject) ViewerAssets.text(piece.getValue("asset").jsonPrimitive.content) else piece.jsonPrimitive.content
            }
            val got = build(record)
            val at = got.zip(want).indexOfFirst { (a, b) -> a != b }.let { if (it < 0) minOf(got.length, want.length) else it }
            misses.check(got == want) {
                "the whole page differs from Python's at character $at: …${got.substring(maxOf(0, at - 80), minOf(got.length, at + 80))}…, " +
                    "Python's …${want.substring(maxOf(0, at - 80), minOf(want.length, at + 80))}…"
            }
        }
    }

    private fun build(record: Record): String {
        val kw = record.kw
        return HarmonicaPage.build(
            text(record.args[0]), title = string(kw["title"])!!, artist = string(kw["artist"]) ?: "",
            tabFile = string(kw["tab_file"])!!, url = string(kw["url"]), pageKey = string(kw["page_key"]),
            harp = string(kw["harp"]), pin = kw["pin"]?.takeIf { it !is JsonNull }, facts = kw["facts"] as? JsonObject,
            cho = kw["cho"]?.takeIf { it !is JsonNull }?.let(::text), key = string(kw["key"]),
            keySource = string(kw["key_source"]), back = string(kw["back"]))
    }

    private fun choiceOf(row: JsonArray): Choice {
        val (harp, why, fits, named, page, tonic) = row
        return Choice(harp.jsonPrimitive.int, why.jsonPrimitive.content,
                      fits.jsonArray.map { f -> f.jsonArray.let { Fit(it[0].jsonPrimitive.int, it[1].jsonPrimitive.double, it[2].jsonPrimitive.int) } },
                      intOrNull(named), intOrNull(page), intOrNull(tonic))
    }

    private operator fun <T> List<T>.component6(): T = this[5]

    private fun intOrNull(e: JsonElement): Int? = if (e is JsonNull) null else e.jsonPrimitive.int

    private const val DATA = "<script type=\"application/json\" id=\"harp-data\">"
    private const val NAMES = "<script type=\"application/json\" id=\"song-names\">"

    /** page_out: a page's record. */
    fun pageOut(html: String): JsonObject {
        val body = html.indexOf("<body>\n")
        val (head, a) = cut(html, "<header class=\"head\">", "</header>\n", body)
        val (article, b) = cut(html, "<article class=\"sheet", "</article>\n", a)
        val (foot, c) = cut(html, "<footer class=\"foot\">", "</footer>\n", b)
        val block = html.indexOf(DATA, c)
        val data = Json.parseToJsonElement(html.substring(block + DATA.length, html.indexOf("</script>", block))).jsonObject
        val names = html.indexOf(NAMES).takeIf { it >= 0 }?.let { n ->
            val at = n + NAMES.length
            JsonPrimitive(sha(html.substring(at, html.indexOf("</script>", at))).take(16))
        } ?: JsonNull
        return JsonObject(linkedMapOf(
            "sha256" to JsonPrimitive(sha(html)), "size" to JsonPrimitive(html.toByteArray(Charsets.UTF_8).size),
            "head" to JsonPrimitive(sha(head).take(16)), "article" to JsonPrimitive(sha(article).take(16)),
            "foot" to JsonPrimitive(sha(foot).take(16)), "bar" to JsonPrimitive(sha(html.substring(c, block)).take(16)),
            "data" to JsonPrimitive(members(data)), "overlay" to JsonPrimitive(members(data.getValue("overlay"))),
            "names" to names))
    }

    private fun cut(html: String, start: String, end: String, from: Int): Pair<String, Int> {
        val a = html.indexOf(start, from)
        check(a >= 0) { "no $start in the page" }
        val b = html.indexOf(end, a) + end.length
        return html.substring(a, b) to b
    }

    private fun members(value: JsonElement): String =
        if (value is JsonNull) "-" else value.jsonObject.entries.joinToString(" ") { (k, v) -> "$k=${short(v)}" }

    // --- the loop ------------------------------------------------------------------------------------------------

    private fun replay(name: String, kinds: Int, check: (Record, Misses) -> Unit) {
        val misses = Misses(name)
        val counts = HashMap<String, Int>()
        for (record in Corpus.records(name)) {
            counts.merge(record.fn, 1, Int::plus)
            check(record, misses)
        }
        misses.check(counts.size == kinds) { "$name: the kinds of record, $counts" }
        misses.assertNone()
    }

    /** Phase A: [block], or a record counted in [waiting] where its producer (HarpTabs.parse, lane harptab-layout;
     * SheetPage's frame, lane pages) hasn't merged. */
    private fun waitingOn(misses: Misses, block: () -> Unit) {
        try {
            block()
        } catch (e: NotImplementedError) {
            waiting++
            misses.check(true) { "" }
        }
    }

    /** Each item of the record's batch (its first argument): its answer, and Python's. */
    private fun each(misses: Misses, record: Record, got: (JsonElement) -> JsonElement) {
        val items = record.args[0].jsonArray
        val out = record.out!!.jsonArray
        misses.check(items.size == out.size) { "${record.fn}: ${items.size} items, ${out.size} answers" }
        for ((i, item) in items.withIndex()) {
            same(misses, "${record.fn.substringAfterLast('.')}(${item.toString().take(100)})", out[i], got(item))
        }
    }

    private fun same(misses: Misses, what: String, want: JsonElement, got: JsonElement) =
        misses.check(dumps(want) == dumps(got)) { "$what: ${dumps(got).take(600)}, Python's ${dumps(want).take(600)}" }

    private fun dumps(value: JsonElement): String = PyJson.dumps(value, sortKeys = true, compact = true)

    /** The first 8 hex digits of the SHA-256 of `json.dumps(value, ensure_ascii=False, separators=(",", ":"))`. */
    fun short(value: JsonElement): String = sha(PyJson.dumps(value, compact = true)).take(8)

    private fun sha(text: String): String = Canonical.sha256Hex(text.toByteArray(Charsets.UTF_8))
}
