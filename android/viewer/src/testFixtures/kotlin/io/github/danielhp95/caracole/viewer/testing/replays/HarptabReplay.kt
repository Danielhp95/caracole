package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.viewer.ViewerData
import io.github.danielhp95.caracole.viewer.harptab.Gap
import io.github.danielhp95.caracole.viewer.harptab.Group
import io.github.danielhp95.caracole.viewer.harptab.HarpTabText
import io.github.danielhp95.caracole.viewer.harptab.HarpTabs
import io.github.danielhp95.caracole.viewer.harptab.Hole
import io.github.danielhp95.caracole.viewer.harptab.Legend
import io.github.danielhp95.caracole.viewer.harptab.Notation
import io.github.danielhp95.caracole.viewer.harptab.Prose
import io.github.danielhp95.caracole.viewer.harptab.Reading
import io.github.danielhp95.caracole.viewer.harptab.Row
import io.github.danielhp95.caracole.viewer.harptab.Scan
import io.github.danielhp95.caracole.viewer.harptab.Symbol
import io.github.danielhp95.caracole.viewer.harptab.Tab
import io.github.danielhp95.caracole.viewer.harptab.TabItem
import io.github.danielhp95.caracole.viewer.harptab.Tokens
import io.github.danielhp95.caracole.viewer.harptab.Used
import io.github.danielhp95.caracole.viewer.harptab.Words
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
 * viewer/harptab.py's reading half (vectors/viewer/harptab_read.jsonl) and its layout (vectors/viewer/
 * harptab_layout.jsonl), every record answered by :viewer's viewer.harptab as Python answered it: ReadingTest's and
 * LayoutTest's record loops on the JVM, CorpusOnDeviceTest's on the device.
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
        layout()
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
            val (spec, notation, wantRead) = pin.jsonArray
            var pinned: Notation? = null
            val got = try {
                pinned = HarpTabs.pinned(spec, body)
                pinned?.let { notationRef(it, candidates) } ?: JsonNull
            } catch (e: IllegalArgumentException) {
                JsonObject(mapOf("message" to JsonPrimitive(e.message ?: "")))
            }
            same(misses, "$what: pinned($spec)", notation, got)
            // the tab read as the pin says, as parse(notation=) reads it: "pinned", confident whatever its Q; whole
            // or by its digest
            val gotRead = pinned?.let { n ->
                val (r, rScans) = HarpTabs.read(lines, prepared.chip, n, prepared.legends)
                JsonArray(listOf(readingRow(r, candidates, whole = false), JsonPrimitive(short(JsonArray(rScans.map(::scanRow))))))
            } ?: JsonNull
            kept(misses, "$what: read as pinned($spec)", wantRead, gotRead)
        }
    }

    /** The first line whose scan under [notation] Kotlin and Python may differ on, for a failure's message: its scan
     * as Kotlin reads it. */
    private fun firstScanOff(lines: List<String>, notation: Notation): String =
        lines.firstOrNull { it.isNotBlank() }?.let { "; its first line ${PyJsonText(it)} scans ${scanRow(HarpTabs.scan(it, notation))}" } ?: ""

    // --- the layout (vectors/viewer/harptab_layout.jsonl) ---------------------------------------------------------

    fun layout() = replay("viewer/harptab_layout.jsonl", 6) { record, misses ->
        when (record.fn) {
            H + "parse_of" -> parseOf(record, misses)
            H + "line_of" -> each(misses, record) { line -> answer { lineRow(line.jsonPrimitive.content) } }
            H + "named_key_of" -> each(misses, record) { block ->
                answer { HarpTabs.namedKey(block.jsonArray.map { it.jsonPrimitive.content })?.let(::JsonPrimitive) ?: JsonNull }
            }
            H + "syllable_starts_of" -> each(misses, record) { lyric ->
                answer { JsonArray(HarpTabs.syllableStarts(lyric.jsonPrimitive.content).map(::JsonPrimitive)) }
            }
            H + "align_of" -> each(misses, record) { item -> answer { aligned(item.jsonArray) } }
            H + "cuts_of" -> each(misses, record) { item ->
                val (lyric, word, anchors, fixed) = item.jsonArray
                answer {
                    val (a, b) = word.jsonArray.map { it.jsonPrimitive.int }
                    JsonArray(HarpTabs.cuts(lyric.jsonPrimitive.content, a, b, anchors.jsonArray.map { it.jsonPrimitive.int },
                                            fixed.jsonArray.map { it.jsonPrimitive.int }).map { it?.let(::JsonPrimitive) ?: JsonNull })
                }
            }
            else -> misses.check(false) { "an unknown record: ${record.fn}" }
        }
    }

    /** The bodies of harptab_read.jsonl's `tab_of` records, in their order: a layout record's `{"read": n}`. */
    private val readBodies: List<String> by lazy {
        Corpus.records("viewer/harptab_read.jsonl").filter { it.fn == H + "tab_of" }.map { body(it.args[0].jsonObject) }
    }

    private fun body(ref: JsonObject): String = ref["fixture"]?.let { PyText.utf8(Corpus.fixture(it.jsonPrimitive.content))!! }
        ?: ref["read"]?.let { readBodies[it.jsonPrimitive.int] } ?: ref.getValue("text").jsonPrimitive.content

    private fun parseOf(record: Record, misses: Misses) {
        val ref = record.args[0].jsonObject
        val body = body(ref)
        val chip = record.args[1].let { if (it is JsonNull) null else it.jsonPrimitive.content }
        val spec = record.args[2]
        val what = (ref["fixture"] ?: ref["read"]?.let { JsonPrimitive("read tab $it") } ?: JsonPrimitive(body.take(50))).toString() +
            (if (spec is JsonNull) "" else " pinned $spec")
        val want = record.out!!.jsonObject
        val got = try {
            val notation = if (spec is JsonNull) null else HarpTabs.pinned(spec, body)
            tabLayout(HarpTabs.parse(body, chip, notation), body, chip, notation)
        } catch (e: Exception) {
            misses.check(false) { "$what: parse threw $e" }
            return
        }
        same(misses, "$what: its lines' kinds", want.getValue("kinds"), got.getValue("kinds"))
        same(misses, "$what: words above its rows", want.getValue("above"), got.getValue("above"))
        if ("short" in want) {
            misses.check(want.getValue("short").jsonPrimitive.content == short(got)) {
                "$what: its layout ${text(got).take(1200)}, whose digest isn't Python's"
            }
            return
        }
        for (key in want.keys - setOf("sections", "kinds", "above")) same(misses, "$what: $key", want.getValue(key), got.getValue(key))
        val wantSections = want.getValue("sections").jsonArray
        val gotSections = got.getValue("sections").jsonArray
        misses.check(wantSections.size == gotSections.size) { "$what: ${gotSections.size} sections, Python's ${wantSections.size}" }
        for ((n, section) in wantSections.withIndex()) {
            val mine = gotSections.getOrNull(n)?.jsonArray ?: break
            same(misses, "$what: section $n's name", JsonArray(section.jsonArray.take(2)), JsonArray(mine.take(2)))
            val items = section.jsonArray[2].jsonArray
            val gotItems = mine[2].jsonArray
            misses.check(items.size == gotItems.size) { "$what: section $n, ${gotItems.size} items, Python's ${items.size}" }
            for ((k, item) in items.withIndex()) {
                same(misses, "$what: section $n, item $k", item, gotItems.getOrNull(k) ?: JsonNull)
            }
        }
    }

    /** layout_of's whole answer: Python's `tab_layout`, with the lines' kinds and whether the words are above. */
    private fun tabLayout(t: Tab, body: String, chip: String?, notation: Notation?): JsonObject {
        val prepared = HarpTabs.prepared(body, chip)
        val (_, scans) = HarpTabs.read(prepared.read, prepared.chip, notation, prepared.legends)
        val kinds = HarpTabs.lineKinds(prepared.lines, scans, prepared.inLegend)
        val above = HarpTabs.above(prepared.lines, kinds, scans)
        for (r in t.rows()) check(r.text == prepared.lines[r.line] && r.groups == scans[r.line].groups) { "row ${r.line}" }
        return JsonObject(linkedMapOf(
            "notes" to JsonArray(t.notes.map(::JsonPrimitive)),
            "sections" to JsonArray(t.sections.map { s ->
                JsonArray(listOf(s.label?.let(::JsonPrimitive) ?: JsonNull, JsonPrimitive(s.chorus), JsonArray(s.items.map(::itemRow))))
            }),
            "reading" to JsonPrimitive(readingDigest(t.reading)),
            "key" to (t.key?.let(::JsonPrimitive) ?: JsonNull),
            "missed" to JsonArray(t.missed.map(::JsonPrimitive)),
            "chromatic" to JsonPrimitive(t.chromatic),
            "legend" to (t.legend?.let(::legendRow) ?: JsonNull),
            "harp" to (t.harp?.let(::JsonPrimitive) ?: JsonNull),
            "convention" to JsonPrimitive(t.convention),
            "readable" to JsonPrimitive(t.readable),
            "kinds" to JsonPrimitive(kinds.joinToString("") { KINDS.getValue(it) }),
            "above" to JsonPrimitive(above),
        ))
    }

    private val KINDS = mapOf("legend" to "l", "blank" to "b", "holes" to "h", "missed" to "m", "text" to "t")

    private fun itemRow(item: TabItem): JsonElement = when (item) {
        is Row -> JsonArray(listOf(JsonPrimitive("row"), JsonPrimitive(item.line), item.lyric?.let(::JsonPrimitive) ?: JsonNull,
            item.label?.let(::JsonPrimitive) ?: JsonNull, partsRow(item), placementRow(item.placement),
            PyJson.float(item.confidence), JsonPrimitive(item.trusted), JsonPrimitive(item.above),
            JsonPrimitive(short(JsonArray(listOf(JsonPrimitive(item.text), JsonArray(item.groups.map(::groupRow)),
                                                 JsonArray(item.unknown.map(::JsonPrimitive)))))))).also { checkParts(item) }
        is Words -> JsonArray(listOf(JsonPrimitive("words"), JsonArray(item.lines.map(::JsonPrimitive))))
        is Prose -> JsonArray(listOf(JsonPrimitive("prose"), JsonPrimitive(item.text)))
        is Gap -> JsonArray(listOf(JsonPrimitive("gap")))
        is Legend -> JsonArray(listOf(JsonPrimitive("legend"), legendRow(item)))
    }

    /** Python's invariant, which the records' part lengths stand on: the parts' words together end the row's words. */
    private fun checkParts(row: Row) {
        val joined = row.parts.joinToString("") { it.second }
        check(row.lyric == null || HarpTabText.rstrip(row.lyric!!).endsWith(joined)) { "row ${row.line}'s parts: ${row.parts}" }
    }

    /** parts_row: each place's groups by their places in the row's groups, and the length of its words. */
    private fun partsRow(row: Row): JsonElement = JsonArray(row.parts.map { (groups, words) ->
        JsonArray(listOf(JsonArray(groups.map { g -> JsonPrimitive(row.groups.indexOfFirst { it === g }) }),
                         JsonPrimitive(Py.len(words))))
    })

    private fun placementRow(placement: Map<String, Int>): JsonElement =
        JsonObject(placement.mapValues { JsonPrimitive(it.value) })

    private fun readingDigest(r: Reading): String = short(JsonArray(listOf(notationRow(r.notation), JsonPrimitive(r.source),
        PyJson.float(r.explained), PyJson.float(r.playable), PyJson.float(r.score), PyJson.float(r.margin),
        r.runner?.let(::JsonPrimitive) ?: JsonNull, JsonPrimitive(r.confident), usedRows(r.used), JsonPrimitive(r.standard),
        JsonPrimitive(r.said()))))

    private fun lineRow(line: String): JsonElement {
        val label = HarpTabs.isLabel(line)
        val beside = HarpTabs.isLabel(line, besideRow = true)
        return JsonArray(listOf(JsonPrimitive(label), JsonPrimitive(beside),
                                if (label || beside) JsonPrimitive(HarpTabs.labelText(line)) else JsonNull,
                                JsonPrimitive(HarpTabs.isProse(listOf(line, "la la"))), JsonPrimitive(HarpTabs.syllables(line)),
                                HarpTabs.namedKey(listOf(line))?.let(::JsonPrimitive) ?: JsonNull))
    }

    /** align_of: the row [item]'s line scans to, with its words, trusted or not, aligned at its reach. */
    private fun aligned(item: JsonArray): JsonElement {
        val (line, lyric, notation, reach, trusted) = item
        val groups = HarpTabs.scan(line.jsonPrimitive.content, notation(notation)).groups
        val row = HarpTabs.align(Row(groups, if (lyric is JsonNull) null else lyric.jsonPrimitive.content,
                                     trusted = trusted.jsonPrimitive.boolean), reach.jsonPrimitive.int)
        return JsonArray(listOf(partsRow(row), placementRow(row.placement)))
    }

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
