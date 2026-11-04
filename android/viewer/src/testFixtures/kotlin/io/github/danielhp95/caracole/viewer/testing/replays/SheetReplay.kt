package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.viewer.shapes.Position
import io.github.danielhp95.caracole.viewer.sheet.Blank
import io.github.danielhp95.caracole.viewer.sheet.ChordPro
import io.github.danielhp95.caracole.viewer.sheet.ChordRow
import io.github.danielhp95.caracole.viewer.sheet.Item
import io.github.danielhp95.caracole.viewer.sheet.Line
import io.github.danielhp95.caracole.viewer.sheet.Lyrics
import io.github.danielhp95.caracole.viewer.sheet.MusicKeys
import io.github.danielhp95.caracole.viewer.sheet.Preamble
import io.github.danielhp95.caracole.viewer.sheet.Section
import io.github.danielhp95.caracole.viewer.sheet.Sheet
import io.github.danielhp95.caracole.viewer.sheet.SheetView
import io.github.danielhp95.caracole.viewer.sheet.Sheets
import io.github.danielhp95.caracole.viewer.sheet.SongKey
import io.github.danielhp95.caracole.viewer.sheet.Tab
import io.github.danielhp95.caracole.viewer.sheet.Text
import io.github.danielhp95.caracole.viewer.theory.Chord
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.double
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import java.io.File
import java.nio.file.Files
import java.security.MessageDigest

/**
 * viewer/sheet.py, page.py's reading functions, chordpro.py (with render._chordpro_text, _as_latin and
 * ug.page.decode_twice) and keys.py (vectors/viewer/sheet.jsonl, chordpro.jsonl and musickeys.jsonl), every record
 * answered by :viewer's viewer.sheet as Python answered it: SheetsTest's, ChordProTest's and MusicKeysTest's record
 * loops, run on the device by CorpusOnDeviceTest. tests/test_conformance_viewer_sheet.py's docstring says each
 * record's shape: a line `["L", [[item, text], …]]`, `["C", [item, …]]`, `["T", text]`, `["Tab", [line, …]]` or
 * `["B"]`, a section `[label, chorus, [line, …]]`, a chord and a key as TheoryReplay writes them.
 */
object SheetReplay : AreaReplay {
    override val area = "sheet"

    private const val HELPER = "test_conformance_viewer_sheet."

    override fun replay(misses: Misses) {
        sheets()
        chordPro()
        musicKeys()
    }

    // --- vectors/viewer/sheet.jsonl -------------------------------------------------------------------------------

    fun sheets() {
        val misses = Misses("viewer/sheet.jsonl")
        val counts = HashMap<String, Int>()
        for (record in Corpus.records("viewer/sheet.jsonl")) {
            counts.merge(record.fn, 1, Int::plus)
            val out = record.out!!.jsonObject
            when (record.fn) {
                HELPER + "read_of" -> readOf(record.args, out, misses)
                HELPER + "lines_of" -> {
                    val text = record.args[0].jsonPrimitive.content
                    val said = JsonPrimitive(text).toString().take(80)
                    fun check(field: String, got: JsonElement) =
                        misses.check(got == out.getValue(field)) { "lines_of($said).$field: $got, Python's ${out[field]}" }
                    check("sheet", sheetRow(Sheets.parse(text)))
                    check("directive", Sheets.directive(text)?.let { strings(listOf(it.first, it.second)) } ?: JsonNull)
                    check("legend_line", JsonPrimitive(Sheets.isLegendLine(text)))
                    check("split", preambleRow(Sheets.splitPreamble(PyStr.splitlines(text))))
                    check("note", preambleRow(Sheets.splitPreamble(listOf(text) + NOTE_SONG)))
                }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        assertTrue("records of every kind: $counts", counts.size == 2 && counts.getValue(HELPER + "read_of") > 150)
        misses.assertNone()
    }

    /** test_conformance_viewer_sheet.NOTE_SONG: the rest of a sheet after a note. */
    private val NOTE_SONG = listOf("", "{comment: Verse}", "[Em]words", "{comment: Chorus}", "[G]more")

    private fun readOf(args: JsonArray, out: JsonObject, misses: Misses) {
        val cho = args[0].jsonPrimitive.content
        val key = (args[1] as? JsonPrimitive)?.takeIf { it.isString }?.content
        val keySource = (args[2] as? JsonPrimitive)?.takeIf { it.isString }?.content
        val name = cho.lineSequence().firstOrNull().orEmpty().take(60)
        fun check(field: String, got: () -> JsonElement) {
            val answer = try {
                got()
            } catch (e: Exception) {
                misses.check(false) { "read_of($name).$field threw $e" }
                return
            }
            misses.check(answer == out.getValue(field)) { "read_of($name).$field: $answer, Python's ${out[field]}" }
        }
        val s = Sheets.parse(cho)
        check("sheet") { sheetRow(s) }
        check("preamble") { sectionRow(Sheets.preambleSection(s)) }
        check("shown") { shownRow(s) }
        check("drawn") { digest(strings(SheetView.drawnLines(s))) }
        check("texts") { digest(strings(SheetView.writtenTexts(s))) }
        check("peek") { SheetView.shown(s).first?.let { strings(SheetView.peek(it, s.chords)) } ?: JsonNull }
        check("places") { digest(JsonArray(SheetView.places(s).map { ints(listOf(it.first, it.second)) })) }
        check("played") { digest(ints(SheetView.played(s))) }
        check("keys") {
            JsonArray(out.getValue("keys").jsonArray.map { row ->
                val (k, source) = row.jsonArray
                val given = (k as? JsonPrimitive)?.takeIf { it.isString }?.content
                val from = (source as? JsonPrimitive)?.takeIf { it.isString }?.content
                val (found, origin) = SheetView.songKey(s, SheetView.chords(s), given, from)
                JsonArray(listOf(k, source, TheoryReplay.key(found), origin?.let(::JsonPrimitive) ?: JsonNull))
            })
        }
        check("viewer_key") { TheoryReplay.key(SheetView.viewerKey(cho, key, keySource)) }
        check("given") { givenRow(SheetView.givenShapes(s)) }
        check("shapes") { SheetView.shapesOf(s) }
        check("written") { digest(JsonArray(s.sections.map { x -> strings(x.lines.map { Sheets.written(it, s.chords) }) })) }
        check("legend") {
            JsonArray(s.sections.flatMapIndexed { i, x ->
                x.lines.mapIndexedNotNull { j, line -> if (Sheets.isLegend(line, s.chords)) ints(listOf(i, j)) else null }
            })
        }
        val lines = PyStr.splitlines(cho)
        check("directives") {
            digest(JsonArray(lines.mapIndexedNotNull { n, line ->
                Sheets.directive(line)?.let { (dn, value) -> JsonArray(listOf(JsonPrimitive(n), JsonPrimitive(dn), JsonPrimitive(value))) }
            }))
        }
        check("legend_lines") { ints(lines.indices.filter { Sheets.isLegendLine(lines[it]) }) }
        check("split") { preambleRow(Sheets.splitPreamble(lines)) }
    }

    /** _shown: the preamble's row, and each section shown as its index in the sheet's sections where it is one of
     * them, else its row. */
    private fun shownRow(s: Sheet): JsonElement {
        val (pre, sections) = SheetView.shown(s)
        return JsonArray(listOf(sectionRow(pre), JsonArray(sections.map { x ->
            val at = s.sections.indexOfFirst { it === x }
            if (at >= 0) JsonPrimitive(at) else sectionRow(x)
        })))
    }

    // --- vectors/viewer/chordpro.jsonl ----------------------------------------------------------------------------

    fun chordPro() {
        val misses = Misses("viewer/chordpro.jsonl")
        val counts = HashMap<String, Int>()
        for (record in Corpus.records("viewer/chordpro.jsonl")) {
            counts.merge(record.fn, 1, Int::plus)
            when (record.fn) {
                "caracole.render._chordpro_text" -> {
                    val kw = record.kw
                    val capo = (kw["capo"] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content
                    val key = (kw["key"] as? JsonPrimitive)?.takeIf { it.isString }?.content
                    misses.expect(record) {
                        ChordPro.chordProText(record.args[0].jsonPrimitive.content, kw.getValue("title").jsonPrimitive.content,
                            kw.getValue("artist").jsonPrimitive.content, key, capo,
                            kw.getValue("auto").jsonPrimitive.content == "true")
                    }
                }
                "caracole.chordpro.display_columns" ->
                    misses.expect(record) { ChordPro.displayColumns(record.args[0].jsonPrimitive.content) }
                HELPER + "lines_of" -> {
                    val text = record.args[0].jsonPrimitive.content
                    val out = record.out!!.jsonObject
                    val said = JsonPrimitive(text).toString().take(80)
                    fun check(field: String, got: () -> JsonElement) {
                        val answer = try {
                            got()
                        } catch (e: Exception) {
                            misses.check(false) { "lines_of($said).$field threw $e" }
                            return
                        }
                        misses.check(answer == out.getValue(field)) { "lines_of($said).$field: $answer, Python's ${out[field]}" }
                    }
                    check("normalize") { JsonPrimitive(ChordPro.normalizeChord(text)) }
                    check("tagged") { JsonPrimitive(ChordPro.tagForgotten(text)) }
                    check("chord_line") { JsonPrimitive(ChordPro.isChordLine(text)) }
                    check("columns") { ints(ChordPro.displayColumns(text)) }
                    check("directive") { JsonPrimitive(ChordPro.directiveText(text)) }
                    check("latin") { JsonPrimitive(ChordPro.asLatin(text)) }
                    check("decoded") { JsonPrimitive(ChordPro.decodeTwice(text)) }
                    check("converted") { JsonPrimitive(ChordPro.toChordPro(text, "T", "A")) }
                    val merged = out["merged"]?.jsonArray
                    val after = (record.args[1] as? JsonPrimitive)?.takeIf { it.isString }?.content
                    if (merged != null) check("merged") { strings(listOf(after!!, ChordPro.mergeChordLine(text, after))) }
                    else misses.check(after == null || !ChordPro.isChordLine(text)) { "lines_of($said): a chord line with no merged line" }
                }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        assertTrue("records of every kind: $counts", counts.size == 3 && counts.getValue("caracole.render._chordpro_text") > 150)
        misses.assertNone()
    }

    // --- vectors/viewer/musickeys.jsonl ---------------------------------------------------------------------------

    fun musicKeys() {
        val misses = Misses("viewer/musickeys.jsonl")
        val counts = HashMap<String, Int>()
        for (record in Corpus.records("viewer/musickeys.jsonl")) {
            counts.merge(record.fn, 1, Int::plus)
            val out = record.out
            when (record.fn) {
                HELPER + "named_of" -> for ((i, t) in record.args[0].jsonArray.withIndex()) {
                    val text = t.jsonPrimitive.content
                    val got = MusicKeys.named(text)?.let { (key, bare) ->
                        JsonArray(listOf(JsonPrimitive(MusicKeys.parseKey(text)), JsonPrimitive(bare),
                            JsonPrimitive(MusicKeys.keyName(key)), JsonPrimitive(MusicKeys.sameKey(key, "F# minor"))))
                    } ?: JsonNull
                    val want = out!!.jsonArray[i]
                    misses.check(got == want) { "named_of(${JsonPrimitive(text)}): $got, Python's $want" }
                }
                HELPER + "chord_of" -> for ((i, n) in record.args[0].jsonArray.withIndex()) {
                    val name = n.jsonPrimitive.content
                    val got = MusicKeys.chord(name)?.let { c ->
                        JsonArray(listOf(JsonPrimitive(c.root), JsonPrimitive(c.spelling), c.triad?.let(::JsonPrimitive) ?: JsonNull,
                            JsonArray(c.tones.map { (interval, share) -> JsonArray(listOf(JsonPrimitive(interval), JsonPrimitive(share))) })))
                    } ?: JsonNull
                    val want = out!!.jsonArray[i]
                    misses.check(got == want) { "_chord(${JsonPrimitive(name)}): $got, Python's $want" }
                }
                HELPER + "markup_of" -> markupOf(record.args[0].jsonPrimitive.content, out!!.jsonObject, misses)
                "caracole.keys.estimate_key" -> misses.expect(record) {
                    val items = record.args[0].jsonArray
                    if (items.all { it is JsonPrimitive }) MusicKeys.estimateKey(items.map { it.jsonPrimitive.content })
                    else MusicKeys.estimateWeighted(items.map { it.jsonArray[0].jsonPrimitive.content to it.jsonArray[1].jsonPrimitive.double })
                }
                "caracole.keys._correlation" -> {
                    val (a, b) = record.args.map { row -> row.jsonArray.map { it.jsonPrimitive.double } }
                    val got = MusicKeys.correlation(a, b)
                    val want = out!!.jsonPrimitive.double
                    misses.check(got.toRawBits() == want.toRawBits()) { "_correlation($a, $b): $got, Python's $want" }
                }
                "caracole.keys.sheet_capo" -> misses.expect(record) {
                    MusicKeys.sheetCapo(record.args[0])
                }
                HELPER + "song_keys" -> songKeys(record.args[0].jsonArray.map { it.jsonObject }, out!!.jsonArray, misses)
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        assertTrue("records of every kind: $counts", counts.size == 7 && counts.getValue(HELPER + "markup_of") > 50)
        misses.assertNone()
    }

    private fun markupOf(markup: String, out: JsonObject, misses: Misses) {
        val said = JsonPrimitive(markup).toString().take(80)
        val stated = MusicKeys.stated(markup)?.let { JsonArray(listOf(JsonPrimitive(it.first), JsonPrimitive(it.second))) } ?: JsonNull
        misses.check(stated == out.getValue("stated")) { "_stated($said): $stated, Python's ${out["stated"]}" }
        val chords = MusicKeys.chordsInSheet(markup)
        misses.check(strings(chords) == out.getValue("chords")) { "chords_in_sheet($said): $chords, Python's ${out["chords"]}" }
        val estimate = MusicKeys.estimateKey(chords)?.let(::JsonPrimitive) ?: JsonNull
        misses.check(estimate == out.getValue("estimate")) { "estimate_key($said): $estimate, Python's ${out["estimate"]}" }
        for (row in out.getValue("sheet_key").jsonArray) {
            val (raw, capo, want) = row.jsonArray
            val got = songKeyRow(MusicKeys.sheetKey(raw.jsonObject, markup, capo.jsonPrimitive.intOrNull))
            misses.check(got == want) { "sheet_key($raw, $said, $capo): $got, Python's $want" }
        }
    }

    private fun songKeys(fixture: List<JsonObject>, out: JsonArray, misses: Misses) {
        val dir = Files.createTempDirectory("caracole-keys").toFile()
        try {
            val library = File(dir, "library")
            TestDb.fresh(dir).use { database ->
                database.writeBlocking { db -> Fixtures.loadRecords(db, fixture, library) }
                database.read { db ->
                    for (row in out) {
                        val (id, song, human, auto, letter) = row.jsonArray
                        val songId = id.jsonPrimitive.long
                        val (h, a) = MusicKeys.sheetKeys(db, library, songId)
                        val got = JsonArray(listOf(id, songKeyRow(MusicKeys.songKey(db, library, songId)), songKeyRow(h),
                            songKeyRow(a), MusicKeys.letterAlone(db, library, songId)?.let(::JsonPrimitive) ?: JsonNull))
                        misses.check(got == row) { "song $songId's keys: $got, Python's [$id, $song, $human, $auto, $letter]" }
                    }
                }
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    // --- rows -----------------------------------------------------------------------------------------------------

    fun sheetRow(s: Sheet): JsonObject = JsonObject(linkedMapOf(
        "title" to JsonPrimitive(s.title), "artist" to JsonPrimitive(s.artist),
        "key" to (s.key?.let(::JsonPrimitive) ?: JsonNull), "capo" to (s.capo?.let(::JsonPrimitive) ?: JsonNull),
        "auto" to JsonPrimitive(s.auto), "chords" to strings(s.chords),
        "sections" to JsonArray(s.sections.map(::sectionRow)), "defines" to strings(s.defines),
    ))

    fun sectionRow(section: Section?): JsonElement {
        if (section == null) return JsonNull
        return JsonArray(listOf(section.label?.let(::JsonPrimitive) ?: JsonNull, JsonPrimitive(section.chorus),
            JsonArray(section.lines.map(::lineRow))))
    }

    fun lineRow(line: Line): JsonElement = when (line) {
        is Lyrics -> JsonArray(listOf(JsonPrimitive("L"),
            JsonArray(line.parts.map { (item, text) -> JsonArray(listOf(itemRow(item), JsonPrimitive(text))) })))
        is ChordRow -> JsonArray(listOf(JsonPrimitive("C"), JsonArray(line.items.map(::itemRow))))
        is Text -> JsonArray(listOf(JsonPrimitive("T"), JsonPrimitive(line.text)))
        is Tab -> JsonArray(listOf(JsonPrimitive("Tab"), strings(line.lines)))
        Blank -> JsonArray(listOf(JsonPrimitive("B")))
    }

    private fun itemRow(item: Item?): JsonElement = when (item) {
        null -> JsonNull
        is Item.Chord -> JsonPrimitive(item.index)
        is Item.Mark -> JsonPrimitive(item.text)
    }

    fun givenRow(given: List<Pair<Chord, Position>>): JsonArray =
        JsonArray(given.map { (c, position) -> JsonArray(listOf(TheoryReplay.chord(c), position)) })

    fun preambleRow(pre: Preamble): JsonObject = JsonObject(linkedMapOf(
        "notes" to strings(pre.notes), "legend" to givenRow(pre.legend),
        "tabs" to JsonArray(pre.tabs.map { ints(listOf(it.first, it.second)) }),
        "tuning" to (pre.tuning?.let(::JsonPrimitive) ?: JsonNull),
        "capo_note" to (pre.capoNote?.let(::JsonPrimitive) ?: JsonNull), "end" to JsonPrimitive(pre.end),
    ))

    fun songKeyRow(found: SongKey?): JsonElement =
        if (found == null) JsonNull else JsonArray(listOf(JsonPrimitive(found.key), JsonPrimitive(found.source)))

    /** The SHA-256 of `json.dumps(value)`, its defaults (ASCII, ", " and ": "), as the generator's `digest`. */
    fun digest(value: JsonElement): JsonPrimitive {
        val text = PyJson.dumps(value, indent = null, ensureAscii = true)
        val bytes = MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.US_ASCII))
        return JsonPrimitive(bytes.joinToString("") { "%02x".format(it) })
    }

    private fun strings(xs: List<String>): JsonArray = JsonArray(xs.map(::JsonPrimitive))
    private fun ints(xs: List<Int>): JsonArray = JsonArray(xs.map(::JsonPrimitive))
}
