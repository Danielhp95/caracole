package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.viewer.ViewerAssets
import io.github.danielhp95.caracole.viewer.pages.SheetPage
import io.github.danielhp95.caracole.viewer.pages.ViewerInputs
import io.github.danielhp95.caracole.viewer.sheet.Blank
import io.github.danielhp95.caracole.viewer.sheet.ChordRow
import io.github.danielhp95.caracole.viewer.sheet.Item
import io.github.danielhp95.caracole.viewer.sheet.Line
import io.github.danielhp95.caracole.viewer.sheet.Lyrics
import io.github.danielhp95.caracole.viewer.sheet.Section
import io.github.danielhp95.caracole.viewer.sheet.Tab
import io.github.danielhp95.caracole.viewer.sheet.Text
import io.github.danielhp95.caracole.viewer.theory.Key
import kotlinx.serialization.json.Json
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
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.AssumptionViolatedException
import java.security.MessageDigest
import java.util.Base64

/**
 * The sheet page, byte for byte: every record of vectors/viewer/pages_parts.jsonl (the page's frame, function by
 * function), pages-1.jsonl to pages-N.jsonl (each page's digests: whole, its body's, each data member's, its names')
 * and page_whole.json (a small page whole) answered by :viewer's viewer.pages.SheetPage as page.py answered it:
 * SheetPageTest's record loops, run on the device by CorpusOnDeviceTest. tests/test_conformance_viewer_pages.py's
 * docstring says each record's shape.
 *
 * Phase A, waiting on sheet-keys and harmony-progressions: until a sheet is read (Sheets.parse) and harmony's tables
 * are made (HarmonyTables.tables), a whole page can't be built, and [everyPageIsPagePys] and [theWholePageIsPagePys]
 * stop as an assumption that names them; the frame's parts are checked now.
 */
object PagesReplay : AreaReplay {
    override val area = "pages"

    private const val P = "caracole.viewer.page."
    private const val HELPER = "test_conformance_viewer_pages."
    private const val SONG = "<script type=\"application/json\" id=\"song\">"
    private const val NAMES = "<script type=\"application/json\" id=\"song-names\">"

    override fun replay(misses: Misses) {
        everyPartIsPagePys()
        everyPageIsPagePys()
        theWholePageIsPagePys()
    }

    fun everyPartIsPagePys() {
        val misses = Misses("viewer/pages_parts.jsonl")
        val counts = HashMap<String, Int>()
        for (record in Corpus.records("viewer/pages_parts.jsonl")) {
            counts.merge(record.fn.substringAfterLast('.'), 1, Int::plus)
            val a = record.args
            when (record.fn) {
                P + "names_table" -> misses.expect(record) {
                    names(SheetPage.namesTable(a[0].jsonPrimitive.boolean, strings(a[1])))
                }
                P + "artist_line" -> misses.expect(record) { SheetPage.artistLine(text(a[0]), names(a[1])) }
                P + "zh_attr" -> misses.expect(record) { SheetPage.zhAttr(text(a[0]), names(a[1])) }
                P + "pdf_line" -> misses.expect(record) {
                    SheetPage.pdfLine(a[0].jsonArray.map { f ->
                        val (name, label, twin) = f.jsonArray
                        Triple(text(name), text(label), (twin as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content)
                    })
                }
                P + "_words" -> misses.expect(record) { strings(a[0]).map(SheetPage::words) }
                P + "_facts" -> misses.expect(record) {
                    val key = key(a[0])
                    a[1].jsonArray.map { case ->
                        val (origin, capo) = case.jsonArray
                        SheetPage.facts(key, (origin as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content, capo.jsonPrimitive.int)
                    }
                }
                P + "_footer" -> misses.expect(record) { SheetPage.footer(text(a[0])) }
                P + "_page" -> misses.expect(record) {
                    SheetPage.page(text(a[0]), text(a[1]), strings(a[2]), strings(a[3]), names(a[4]))
                }
                P + "viewer_csp" -> misses.expect(record) {
                    SheetPage.viewerCsp(Base64.getDecoder().decode(a[0].jsonObject.getValue("base64").jsonPrimitive.content))
                }
                HELPER + "shown_html" -> misses.expect(record) {
                    val chords = strings(a[0])
                    JsonObject(linkedMapOf(
                        "pre" to ((a[1] as? JsonObject)?.let { JsonPrimitive(SheetPage.preambleHtml(section(it), chords)) }
                            ?: JsonNull),
                        "sections" to JsonArray(a[2].jsonArray.map { JsonPrimitive(SheetPage.sectionHtml(section(it.jsonObject), chords)) }),
                    ))
                }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        assertTrue("records of every kind: $counts", counts.size == 10 && counts.getValue("shown_html") >= 20)
        misses.assertNone()
    }

    /** The page files, pages-1.jsonl on, as many as there are. */
    fun pageFiles(): List<String> = generateSequence(1) { it + 1 }
        .map { "viewer/pages-$it.jsonl" }
        .takeWhile { name -> Corpus.open(name)?.also { it.close() } != null }
        .toList()

    fun everyPageIsPagePys() {
        val files = pageFiles()
        assertTrue("the page files: $files", files.size >= 2)
        val records = files.flatMap(Corpus::records)
        assertTrue("every sheet's page: ${records.size}", records.size >= 180)
        buildable(records.first())
        val misses = Misses("viewer/pages-*.jsonl")
        for (record in records) {
            val sheet = record.extra["sheet"]?.jsonPrimitive?.content
            val want = record.out!!.jsonObject
            val cho = text(record.args[0])
            val got = try {
                out(SheetPage.build(inputs(cho, record.kw)), cho)
            } catch (e: Exception) {
                misses.check(false) { "$sheet ${record.kw}: threw $e" }
                continue
            }
            misses.check(got == want) { "$sheet ${record.kw.keys}: ${differences(got, want)}" }
        }
        misses.assertNone()
    }

    fun theWholePageIsPagePys() {
        val pages = Corpus.json("viewer/page_whole.json").getValue("pages").jsonArray
        assertTrue("a page", pages.isNotEmpty())
        val misses = Misses("viewer/page_whole.json")
        for (entry in pages) {
            val page = entry.jsonObject
            val cho = text(page.getValue("args").jsonArray[0])
            val kw = page.getValue("kw").jsonObject
            val want = page.getValue("pieces").jsonArray.joinToString("") { piece ->
                (piece as? JsonObject)?.let { ViewerAssets.text(it.getValue("asset").jsonPrimitive.content) }
                    ?: piece.jsonPrimitive.content
            }
            val built = try {
                SheetPage.build(inputs(cho, kw))
            } catch (e: NotImplementedError) {
                throw AssumptionViolatedException("waiting on sheet-keys and harmony-progressions: ${e.message}")
            }
            misses.check(built == want) { "the whole page differs from line ${firstLine(built, want)} on" }
        }
        misses.assertNone()
    }

    /** Phase A's guard: a page can be built once sheet-keys and harmony-progressions have merged. */
    private fun buildable(record: Record) {
        try {
            SheetPage.build(inputs(text(record.args[0]), record.kw))
        } catch (e: NotImplementedError) {
            throw AssumptionViolatedException("waiting on sheet-keys and harmony-progressions: ${e.message}")
        }
    }

    /** build_viewer's keywords as the record holds them. */
    fun inputs(cho: String, kw: JsonObject): ViewerInputs {
        fun string(name: String): String? = (kw[name] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content
        return ViewerInputs(
            cho = cho, key = string("key"), keySource = string("key_source"),
            transpose = kw["transpose"]?.jsonPrimitive?.int ?: 0, start = string("start"), pdf = string("pdf"),
            export = kw["export"]?.jsonPrimitive?.boolean ?: true, versions = kw["versions"] as? JsonObject,
            guitar = kw["guitar"]?.let(::strings) ?: emptyList(),
            harmonica = kw["harmonica"]?.jsonArray?.map { it.jsonObject } ?: emptyList(),
            pdfTraditional = string("pdf_traditional"), video = kw["video"] as? JsonObject,
        )
    }

    /** A page's record, as the generator's `page_out` makes it. */
    fun out(html: String, cho: String): JsonObject {
        val start = html.indexOf("<body>\n") + "<body>\n".length
        val song = html.indexOf(SONG, start)
        val payload = html.substring(song + SONG.length, html.indexOf("</script>", song))
        val data = Json.parseToJsonElement(payload).jsonObject
        val names = html.indexOf(NAMES).takeIf { it >= 0 }?.let { at ->
            val from = at + NAMES.length
            sha(html.substring(from, html.indexOf("</script>", from))).take(16)
        }
        val members = data.entries.joinToString(" ") { (name, value) -> "$name=${sha(PyJson.dumps(value, compact = true)).take(8)}" }
        return JsonObject(linkedMapOf(
            "sha256" to JsonPrimitive(sha(html)), "size" to JsonPrimitive(html.toByteArray().size),
            "body" to JsonPrimitive(sha(html.substring(start, song)).take(16)), "data" to JsonPrimitive(members),
            "names" to (names?.let(::JsonPrimitive) ?: JsonNull),
            "written_script" to (SheetPage.writtenScript(cho)?.let(::JsonPrimitive) ?: JsonNull),
            "is_chinese" to JsonPrimitive(SheetPage.isChinese(cho)),
        ))
    }

    /** What differs between two page records: the members of the data by name, else the record's fields. */
    private fun differences(got: JsonObject, want: JsonObject): String {
        val fields = want.keys.filter { got[it] != want[it] }
        val mine = members(got)
        val theirs = members(want)
        val data = (theirs.keys + mine.keys).filter { mine[it] != theirs[it] }
        return "fields $fields" + if (data.isNotEmpty()) ", data members $data" else ""
    }

    private fun members(record: JsonObject): Map<String, String> =
        record.getValue("data").jsonPrimitive.content.split(' ').filter { it.isNotEmpty() }
            .associate { it.substringBefore('=') to it.substringAfter('=') }

    private fun firstLine(a: String, b: String): Int {
        val x = a.split('\n')
        val y = b.split('\n')
        return (x.indices.firstOrNull { it >= y.size || x[it] != y[it] } ?: x.size) + 1
    }

    private fun sha(text: String): String =
        MessageDigest.getInstance("SHA-256").digest(text.toByteArray()).joinToString("") { "%02x".format(it) }

    private fun text(e: JsonElement): String = e.jsonPrimitive.content
    private fun strings(e: JsonElement): List<String> = e.jsonArray.map { it.jsonPrimitive.content }

    private fun key(e: JsonElement): Key? =
        (e as? JsonArray)?.let { Key(it[0].jsonPrimitive.int, it[1].jsonPrimitive.content) }

    private fun names(e: JsonElement): Map<String, Map<String, String>>? = (e as? JsonObject)?.let { table ->
        table.mapValues { (_, texts) -> texts.jsonObject.mapValues { it.value.jsonPrimitive.content } }
    }

    private fun names(table: Map<String, Map<String, String>>?): JsonElement = if (table == null) JsonNull else
        JsonObject(table.mapValues { (_, texts) -> JsonObject(texts.mapValues { JsonPrimitive(it.value) }) })

    private fun section(o: JsonObject): Section = Section(
        label = (o["label"] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content,
        chorus = o.getValue("chorus").jsonPrimitive.boolean,
        lines = o.getValue("lines").jsonArray.map { line(it.jsonObject) },
    )

    private fun line(o: JsonObject): Line = when {
        "lyrics" in o -> Lyrics(o.getValue("lyrics").jsonArray.map { part ->
            val (head, words) = part.jsonArray
            item(head) to words.jsonPrimitive.content
        })
        "chords" in o -> ChordRow(o.getValue("chords").jsonArray.map { item(it)!! })
        "text" in o -> Text(o.getValue("text").jsonPrimitive.content)
        "tab" in o -> Tab(strings(o.getValue("tab")))
        "blank" in o -> Blank
        else -> throw AssertionError("no line in $o")
    }

    private fun item(e: JsonElement): Item? = when {
        e is JsonNull -> null
        e is JsonPrimitive && e.isString -> Item.Mark(e.content)
        else -> Item.Chord(e.jsonPrimitive.int)
    }
}
