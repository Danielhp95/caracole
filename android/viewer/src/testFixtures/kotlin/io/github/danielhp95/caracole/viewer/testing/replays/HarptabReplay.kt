package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.viewer.ViewerData
import io.github.danielhp95.caracole.viewer.harptab.Group
import io.github.danielhp95.caracole.viewer.harptab.HarpTabText
import io.github.danielhp95.caracole.viewer.harptab.HarpTabs
import io.github.danielhp95.caracole.viewer.harptab.Hole
import io.github.danielhp95.caracole.viewer.harptab.Legend
import io.github.danielhp95.caracole.viewer.harptab.Notation
import io.github.danielhp95.caracole.viewer.harptab.Reading
import io.github.danielhp95.caracole.viewer.harptab.Scan
import io.github.danielhp95.caracole.viewer.harptab.Symbol
import io.github.danielhp95.caracole.viewer.harptab.Tokens
import io.github.danielhp95.caracole.viewer.harptab.Used
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
import org.junit.Assert.assertEquals

/**
 * viewer/harptab.py's reading half (vectors/viewer/harptab_read.jsonl), every record answered by :viewer's
 * viewer.harptab as Python answered it: ReadingTest's record loop on the JVM, CorpusOnDeviceTest's on the device. Lane
 * harptab-layout adds the layout's records (vectors/viewer/harptab_layout.jsonl) here.
 *
 * tests/test_conformance_viewer_harptab.py's docstring says each record's shape. A value is compared as the text
 * `json.dumps` writes of it, its members sorted (so a float is Python's repr, to the bit, and an int is no float); a
 * value Python kept by its digest (16 hex digits of the SHA-256 of `json.dumps(value, ensure_ascii=False,
 * separators=(",", ":"))`) by the digest of the same text, which core.json.PyJson.dumps writes alike.
 */
object HarptabReplay : AreaReplay {
    override val area = "harptab"

    private const val H = "test_conformance_viewer_harptab."

    override fun replay(misses: Misses) {
        dataIsTheModules(misses)
        read()
    }

    /** What the data says that Kotlin also states: STAR_BENDS is signs changed by `*` a bend after the hole. */
    fun dataIsTheModules(misses: Misses) {
        val data = ViewerData.table("harptab")
        misses.check(data.getValue("PRESETS").jsonArray.size == HarpTabs.PRESETS.size) { "the presets: ${HarpTabs.PRESETS}" }
        misses.check(HarpTabs.SIGNS.changed(listOf(Symbol("*", "bend", "after"))) == HarpTabs.STAR_BENDS) {
            "SIGNS.changed((*, bend, after)): ${HarpTabs.SIGNS.changed(listOf(Symbol("*", "bend", "after")))}"
        }
        misses.check(HarpTabs.PRESETS.map { it.name } == listOf("signs", "brackets", "letters", "signs after", "barrett")) {
            "the presets' names: ${HarpTabs.PRESETS.map { it.name }}"
        }
    }

    fun read() = replay("viewer/harptab_read.jsonl", 8) { record, misses ->
        when (record.fn) {
            H + "tokens_of" -> tokensOf(record, misses)
            H + "scan_of" -> {
                val lines = record.args[1].jsonArray.map { it.jsonPrimitive.content }
                for ((k, row) in record.args[0].jsonArray.withIndex()) {
                    val notation = notation(row)
                    val want = record.out!!.jsonArray[k].jsonArray
                    misses.check(want.size == lines.size) { "scan_of: ${lines.size} lines, ${want.size} answers" }
                    for ((i, line) in lines.withIndex()) {
                        val got = answer { scanRow(HarpTabs.scan(line, notation)) }
                        kept(misses, "scan(${PyJsonText(line)}, ${row.toString().take(60)})", want[i], got)
                    }
                }
            }
            H + "legend_of" -> {
                val lines = record.args[0].jsonArray.map { it.jsonPrimitive.content }
                same(misses, "legend($lines)", record.out!!, answer { JsonArray(HarpTabs.legend(lines).map(::legendRow)) })
            }
            H + "entry_of" -> each(misses, record) { item ->
                val (sym, meaning) = item.jsonArray.map { it.jsonPrimitive.content }
                answer { HarpTabs.entry(sym, meaning)?.let(::symbolRow) ?: JsonNull }
            }
            H + "meaning_of" -> each(misses, record) { text ->
                answer { HarpTabs.meaning(text.jsonPrimitive.content)?.let(::JsonPrimitive) ?: JsonNull }
            }
            H + "check_spec_of" -> each(misses, record) { spec ->
                try {
                    HarpTabs.checkSpec(spec)
                    JsonNull
                } catch (e: IllegalArgumentException) {
                    JsonObject(mapOf("message" to JsonPrimitive(e.message ?: "")))
                }
            }
            H + "text_of" -> each(misses, record) { text ->
                val t = text.jsonPrimitive.content
                JsonArray(listOf(JsonPrimitive(HarpTabText.expand(t)), JsonPrimitive(HarpTabText.swapcase(t)),
                                 JsonPrimitive(HarpTabText.foldAccents(t)), JsonPrimitive(HarpTabText.isWord(t, alone = true)),
                                 JsonPrimitive(HarpTabText.isWord(t, alone = false))))
            }
            H + "tab_of" -> tabOf(record, misses)
            else -> misses.check(false) { "an unknown record: ${record.fn}" }
        }
    }

    private fun tokensOf(record: Record, misses: Misses) {
        val n = notation(record.args[0])
        val tokens = Tokens.of(n)
        val names = listOf("start", "before", "after", "apart", "join", "together")
        val got = LinkedHashMap<String, JsonElement>()
        for ((i, name) in names.withIndex()) got[name] = tokens.sources[i]?.let(::JsonPrimitive) ?: JsonNull
        got["flags"] = JsonPrimitive(if (tokens.fold) "i" else "")
        same(misses, "_tokens(${record.args[0].toString().take(80)})", record.out!!, JsonObject(got))
    }

    private fun tabOf(record: Record, misses: Misses) {
        val ref = record.args[0].jsonObject
        val body = ref["fixture"]?.let { PyText.utf8(Corpus.fixture(it.jsonPrimitive.content))!! }
            ?: ref.getValue("text").jsonPrimitive.content
        val chip = record.args[1].let { if (it is JsonNull) null else it.jsonPrimitive.content }
        val what = ref["fixture"]?.jsonPrimitive?.content ?: PyJsonText(body.take(50))
        val want = record.out!!.jsonObject
        val prepared = HarpTabs.prepared(body, chip)
        same(misses, "$what: the chip", want.getValue("chip"), prepared.chip?.let(::JsonPrimitive) ?: JsonNull)
        same(misses, "$what: its legends", want.getValue("legends"), JsonArray(prepared.legends.map(::legendRow)))
        same(misses, "$what: their lines", want.getValue("in_legend"), JsonArray(prepared.inLegend.sorted().map(::JsonPrimitive)))
        val lines = prepared.read
        val (candidates, found) = HarpTabs.candidates(lines, prepared.chip, prepared.legends)
        same(misses, "$what: the candidates", want.getValue("candidates"),
             JsonArray(candidates.map { (n, source) -> JsonArray(listOf(notationRow(n), JsonPrimitive(source))) }))
        same(misses, "$what: the legend's symbols placed", want.getValue("found"), JsonArray(found.map(::symbolRow)))
        val weighed = HarpTabs.weighed(lines, candidates, prepared.chip, found)
        same(misses, "$what: the lines scored", want.getValue("scored"), JsonArray(weighed.scored.map(::JsonPrimitive)))
        same(misses, "$what: the results", want.getValue("results"), JsonArray(weighed.results.map {
            JsonArray(listOf(PyJson.float(it.score), JsonPrimitive(it.k), PyJson.float(it.explained), PyJson.float(it.playable)))
        }))
        val scans = want.getValue("scans").jsonArray
        for ((k, scanned) in weighed.scanned.withIndex()) {
            val digest = short(JsonArray(scanned.map(::scanRow)))
            misses.check(scans.getOrNull(k)?.jsonPrimitive?.content == digest) {
                "$what: candidate $k's scans (${notationRow(candidates[k].first).toString().take(60)}) differ from Python's" +
                    firstScanOff(lines, candidates[k].first)
            }
        }
        val k = weighed.best
        same(misses, "$what: the reading kept", want.getValue("read"), JsonPrimitive(k))
        val winner = want.getValue("winner").jsonArray
        misses.check(winner.size == weighed.scored.size) { "$what: ${weighed.scored.size} lines scored, Python's ${winner.size}" }
        for ((n, i) in weighed.scored.withIndex()) {
            kept(misses, "$what: line $i, ${PyJsonText(lines[i])}", winner.getOrNull(n) ?: JsonNull,
                 scanRow(weighed.scanned[k][i]))
        }
        val (read, readScans) = HarpTabs.read(lines, prepared.chip, null, prepared.legends)
        misses.check(readScans == weighed.scanned[k]) { "$what: read's scans aren't its reading's" }
        val readings = HarpTabs.readings(body, chip)
        misses.check(readings.firstOrNull() == read) { "$what: readings' first ${readings.firstOrNull()}, read's $read" }
        val wantReadings = want.getValue("readings").jsonArray
        misses.check(readings.size == wantReadings.size) { "$what: ${readings.size} readings, Python's ${wantReadings.size}" }
        for ((n, r) in readings.withIndex()) {
            val row = readingRow(r, candidates, whole = n == 0)
            same(misses, "$what: reading $n", wantReadings.getOrNull(n) ?: JsonNull, row)
            misses.check(r.symbols().joinToString(" · ") { (t, w) -> "$t $w" } == r.said()) { "$what: said" }
        }
        for (pin in want.getValue("pins").jsonArray) {
            val (spec, notation) = pin.jsonArray
            val got = try {
                HarpTabs.pinned(spec, body)?.let { notationRef(it, candidates) } ?: JsonNull
            } catch (e: IllegalArgumentException) {
                JsonObject(mapOf("message" to JsonPrimitive(e.message ?: "")))
            }
            same(misses, "$what: pinned($spec)", notation, got)
        }
    }

    /** The first line whose scan under [notation] Kotlin and Python may differ on, for a failure's message: its scan
     * as Kotlin reads it. */
    private fun firstScanOff(lines: List<String>, notation: Notation): String =
        lines.firstOrNull { it.isNotBlank() }?.let { "; its first line ${PyJsonText(it)} scans ${scanRow(HarpTabs.scan(it, notation))}" } ?: ""

    // --- the shapes of the records ---------------------------------------------------------------------------------

    fun symbolRow(s: Symbol): JsonElement =
        JsonArray(listOf(JsonPrimitive(s.text), JsonPrimitive(s.means), JsonPrimitive(s.at), JsonPrimitive(s.count)))

    private fun notationData(n: Notation): JsonElement = JsonObject(linkedMapOf(
        "name" to JsonPrimitive(n.name), "symbols" to JsonArray(n.symbols.map(::symbolRow)),
        "bare" to (n.bare?.let(::JsonPrimitive) ?: JsonNull), "fold" to JsonPrimitive(n.fold)))

    private fun known(n: Notation): String? =
        HarpTabs.PRESETS.firstOrNull { it == n }?.let { "preset:${it.name}" } ?: if (n == HarpTabs.STAR_BENDS) "star bends" else null

    fun notationRow(n: Notation): JsonElement {
        known(n)?.let { return JsonPrimitive(it) }
        val plain = Notation(n.name, n.symbols.filter { it != HarpTabs.DOTS }, n.bare, n.fold)
        if (plain != n && plain.changed(listOf(HarpTabs.DOTS)) == n) known(plain)?.let { return JsonPrimitive("$it+dots") }
        return notationData(n)
    }

    fun notation(e: JsonElement): Notation {
        if (e is JsonPrimitive) {
            val text = e.content
            val plain = text.removeSuffix("+dots")
            val n = if (plain == "star bends") HarpTabs.STAR_BENDS else HarpTabs.PRESET.getValue(plain.removePrefix("preset:"))
            return if (text.endsWith("+dots")) n.changed(listOf(HarpTabs.DOTS)) else n
        }
        val o = e.jsonObject
        return Notation(o.getValue("name").jsonPrimitive.content,
                        o.getValue("symbols").jsonArray.map {
                            val s = it.jsonArray
                            Symbol(s[0].jsonPrimitive.content, s[1].jsonPrimitive.content, s[2].jsonPrimitive.content,
                                   s[3].jsonPrimitive.int)
                        },
                        o.getValue("bare").let { if (it is JsonNull) null else it.jsonPrimitive.content },
                        o.getValue("fold").jsonPrimitive.boolean)
    }

    private fun notationRef(n: Notation, candidates: List<Pair<Notation, String>>): JsonElement {
        val k = candidates.indexOfFirst { it.first == n }
        return if (k >= 0) JsonPrimitive(k) else notationRow(n)
    }

    private fun holeRow(h: Hole): JsonElement = JsonArray(listOf(JsonPrimitive(h.hole), JsonPrimitive(h.breath),
        JsonPrimitive(h.bend), JsonPrimitive(h.over), JsonPrimitive(h.button)))

    private fun groupRow(g: Group): JsonElement = JsonArray(listOf(JsonArray(g.holes.map(::holeRow)), JsonPrimitive(g.kind),
        JsonPrimitive(g.col), JsonPrimitive(g.digit), JsonPrimitive(g.text), JsonPrimitive(g.hold),
        JsonArray(g.effects.map(::JsonPrimitive)), JsonPrimitive(g.join)))

    private fun usedRows(used: List<Pair<Used, Int>>): JsonElement = JsonArray(used.map { (u, times) ->
        JsonArray(listOf(JsonPrimitive(u.text), JsonPrimitive(u.means), JsonPrimitive(u.at), JsonPrimitive(u.count),
                         JsonPrimitive(times)))
    })

    fun scanRow(s: Scan): JsonElement = JsonArray(listOf(
        JsonArray(s.groups.map(::groupRow)), PyJson.float(s.coverage), JsonArray(s.unknown.map(::JsonPrimitive)),
        s.label?.let(::JsonPrimitive) ?: JsonNull, usedRows(s.used.entries.map { it.key to it.value }),
        JsonPrimitive(s.free), PyJson.float(s.prose), JsonPrimitive(s.run), JsonPrimitive(s.tokens),
        JsonArray(listOf(JsonPrimitive(s.isRow), JsonPrimitive(s.missed), JsonPrimitive(s.holey), PyJson.float(s.explained))),
    ))

    private fun readingRow(r: Reading, candidates: List<Pair<Notation, String>>, whole: Boolean): JsonElement {
        val used = usedRows(r.used)
        return JsonArray(listOf(notationRef(r.notation, candidates), JsonPrimitive(r.source), PyJson.float(r.explained),
                                PyJson.float(r.playable), PyJson.float(r.score), PyJson.float(r.margin),
                                r.runner?.let(::JsonPrimitive) ?: JsonNull, JsonPrimitive(r.confident),
                                if (whole) used else JsonPrimitive(short(used)), JsonPrimitive(r.standard),
                                JsonPrimitive(r.said()), HarpTabs.specOf(r)))
    }

    fun legendRow(l: Legend): JsonElement = JsonArray(listOf(JsonArray(l.lines.map(::JsonPrimitive)),
        JsonArray(l.symbols.map(::symbolRow)), JsonArray(l.at.map(::JsonPrimitive))))

    // --- comparing -------------------------------------------------------------------------------------------------

    /** Every record of [name] through [check], with [kinds] kinds of record each found. */
    private fun replay(name: String, kinds: Int, check: (Record, Misses) -> Unit) {
        val misses = Misses(name)
        val counts = HashMap<String, Int>()
        for (record in Corpus.records(name)) {
            counts.merge(record.fn, 1, Int::plus)
            check(record, misses)
        }
        assertEquals("$name: the kinds of record, $counts", kinds, counts.size)
        misses.assertNone()
    }

    /** Each item of the record's batch (its first argument): its answer, and Python's. */
    private fun each(misses: Misses, record: Record, got: (JsonElement) -> JsonElement) {
        val items = record.args[0].jsonArray
        val out = record.out!!.jsonArray
        misses.check(items.size == out.size) { "${record.fn}: ${items.size} items, ${out.size} answers" }
        for ((i, item) in items.withIndex()) {
            same(misses, "${record.fn.removePrefix(H)}(${item.toString().take(80)})", out[i], got(item))
        }
    }

    /** What [block] answers, or `{"message": …}` for the IllegalArgumentException it threw; another exception is
     * `{"err": its name}`. */
    private fun answer(block: () -> JsonElement): JsonElement = try {
        block()
    } catch (e: IllegalArgumentException) {
        JsonObject(mapOf("message" to JsonPrimitive(e.message ?: "")))
    } catch (e: Exception) {
        JsonObject(mapOf("err" to JsonPrimitive(e.javaClass.simpleName)))
    }

    /** An answer and Python's alike: as `json.dumps` writes them, members sorted; Python's error (`{"err", "message"}`)
     * matched by its words where Kotlin threw an IllegalArgumentException, by being an error at all else. */
    private fun same(misses: Misses, what: String, want: JsonElement, got: JsonElement) {
        if (want is JsonObject && "err" in want) {
            val ok = got is JsonObject && ("err" in got || got["message"] == want["message"])
            misses.check(ok) { "$what: $got, Python raised $want" }
            return
        }
        misses.check(text(want) == text(got)) { "$what: ${text(got).take(600)}, Python's ${text(want).take(600)}" }
    }

    /** A value Python kept whole, or by its digest. */
    private fun kept(misses: Misses, what: String, want: JsonElement, got: JsonElement) {
        if (want is JsonPrimitive && want.isString) {
            misses.check(short(got) == want.content) { "$what: ${text(got).take(600)}, whose digest isn't Python's" }
        } else same(misses, what, want, got)
    }

    private fun text(value: JsonElement): String = PyJson.dumps(value, sortKeys = true, compact = true)

    /** The first 16 hex digits of the SHA-256 of `json.dumps(value, ensure_ascii=False, separators=(",", ":"))`. */
    fun short(value: JsonElement): String =
        Canonical.sha256Hex(PyJson.dumps(value, compact = true).toByteArray(Charsets.UTF_8)).take(16)

    @Suppress("FunctionName")
    private fun PyJsonText(s: String): String = PyJson.dumps(JsonPrimitive(s))
}
