package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.lyrics.lyricsFromJson
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.viewer.autochords.Align
import io.github.danielhp95.caracole.viewer.autochords.Alignment
import io.github.danielhp95.caracole.viewer.autochords.AutoSheet
import io.github.danielhp95.caracole.viewer.autochords.ChordSegment
import io.github.danielhp95.caracole.viewer.autochords.Heard
import io.github.danielhp95.caracole.viewer.autochords.Lrc
import io.github.danielhp95.caracole.viewer.autochords.LrcLine
import io.github.danielhp95.caracole.viewer.autochords.Maker
import io.github.danielhp95.caracole.viewer.autochords.Made
import io.github.danielhp95.caracole.viewer.autochords.Noted
import io.github.danielhp95.caracole.viewer.autochords.Relay
import io.github.danielhp95.caracole.viewer.autochords.SheetHalf
import io.github.danielhp95.caracole.viewer.autochords.Timed
import io.github.danielhp95.caracole.viewer.autochords.Transcript
import io.github.danielhp95.caracole.viewer.autochords.WordStart
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import java.io.File
import java.nio.file.Files

/**
 * merge.py and align.py (vectors/autochords-sheet/merge.jsonl and align.jsonl), every record answered by :viewer's
 * viewer.autochords as Python answered it: AutoSheetTest's and AlignTest's record loops, run on the device by
 * CorpusOnDeviceTest. tests/test_conformance_autochords.py's docstring says each record's shape. A float is compared
 * to the bit (0.0 and -0.0 apart), a text whole or by its digest, a raise by its having raised (Python's ValueError
 * an IllegalArgumentException, its OverflowError an ArithmeticException).
 */
object AutochordsReplay : AreaReplay {
    override val area = "autochords-sheet"

    override fun replay(misses: Misses) {
        merge()
        align()
        sheet()
        relay()
    }

    // --- vectors/autochords-sheet/merge.jsonl ------------------------------------------------------------------

    fun merge() {
        val misses = Misses("autochords-sheet/merge.jsonl")
        val counts = HashMap<String, Int>()
        for (record in Corpus.records("autochords-sheet/merge.jsonl")) {
            counts.merge(record.fn, 1, Int::plus)
            val a = record.args
            when (record.fn) {
                "parse_lrc_words" -> {
                    val text = a[0].jsonPrimitive.content
                    raises(record, misses) { lrcLines(Lrc.parseWords(text)) }
                    if (record.err == null) {
                        val want = record.out!!.jsonArray.map { JsonArray(it.jsonArray.take(2)) }
                        check(misses, record, JsonArray(want)) {
                            JsonArray(Lrc.parse(text).map { (t, s) -> JsonArray(listOf(num(t), JsonPrimitive(s))) })
                        }
                    }
                }
                "parse_lrc" -> raises(record, misses) {
                    JsonArray(Lrc.parse(str(a[0])).map { (t, s) -> JsonArray(listOf(num(t), JsonPrimitive(s))) })
                }
                "snap_to_beats" -> check(misses, record, record.out!!) {
                    segs(AutoSheet.snapToBeats(segments(a[0]), times(a[1])))
                }
                "_beat_grid" -> check(misses, record, record.out!!) {
                    JsonArray(AutoSheet.beatGrid(times(a[0]), a[1].jsonPrimitive.double).map(::num))
                }
                "_bar_starts" -> check(misses, record, record.out!!) {
                    JsonArray(AutoSheet.barStarts(times(a[0]), times(a[1]), times(a[2])).map(::num))
                }
                "youtube_credit" -> check(misses, record, record.out!!) {
                    JsonPrimitive(AutoSheet.youtubeCredit(str(a[0]), str(a[1]), str(a[2])))
                }
                "_word_start" -> check(misses, record, record.out!!) {
                    val text = str(a[0])
                    if (a[1] is JsonNull) JsonArray((0 until Py.len(text) + 2).map { JsonPrimitive(AutoSheet.wordStart(text, it)) })
                    else JsonPrimitive(AutoSheet.wordStart(text, a[1].jsonPrimitive.int))
                }
                "_on_words" -> check(misses, record, record.out!!) {
                    placed(AutoSheet.onWords(str(a[0]), placed(a[1])))
                }
                "_chord_line" -> check(misses, record, record.out!!) { JsonPrimitive(AutoSheet.chordLine(placed(a[0]))) }
                "with_plain_lyrics" -> check(misses, record, record.out!!) {
                    text(AutoSheet.withPlainLyrics(str(a[0]), str(a[1])), record.out!!)
                }
                "build_sheet" -> check(misses, record, record.out!!) { text(build(record.kw), record.out!!) }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        val kinds = setOf("parse_lrc_words", "parse_lrc", "snap_to_beats", "_beat_grid", "_bar_starts", "youtube_credit", "_word_start", "_on_words",
                          "_chord_line", "with_plain_lyrics", "build_sheet")
        assertTrue("records of every kind: $counts", counts.keys == kinds && counts.getValue("build_sheet") > 100)
        misses.assertNone()
    }

    private fun build(kw: JsonObject): String {
        val synced = kw["synced"].orNull()?.jsonPrimitive?.content
        val words = when (val w = kw["synced_words"]) {
            null, JsonNull -> null
            JsonPrimitive(true) -> Lrc.parseWords(synced!!)
            else -> w.jsonArray.map(::lrcLine)
        }
        return AutoSheet.build(
            segments(kw.getValue("segments")), str(kw.getValue("title")), str(kw.getValue("artist")), synced, words,
            kw["plain"].orNull()?.jsonPrimitive?.content, kw["beats"].orNull()?.let(::times),
            kw["downbeats"].orNull()?.let(::times), kw["source"].orNull()?.jsonPrimitive?.content,
        )
    }

    // --- vectors/autochords-sheet/align.jsonl ------------------------------------------------------------------

    fun align() {
        val misses = Misses("autochords-sheet/align.jsonl")
        val counts = HashMap<String, Int>()
        for (record in Corpus.records("autochords-sheet/align.jsonl")) {
            counts.merge(record.fn, 1, Int::plus)
            when (record.fn) {
                "shifted_lrc" -> {
                    val (text, offset) = record.args.let { str(it[0]) to it[1].jsonPrimitive.double }
                    raises(record, misses) { text(Align.shiftedLrc(text, offset), record.out!!) }
                }
                "lyrics_offset" -> {
                    val kw = record.kw
                    val lines = kw.getValue("lines").jsonArray.map { it.jsonArray[0].jsonPrimitive.double to str(it.jsonArray[1]) }
                    val segments = segments(kw.getValue("segments"))
                    val beats = times(kw.getValue("beats"))
                    val downbeats = times(kw.getValue("downbeats"))
                    val audioS = kw.getValue("audio_s").jsonPrimitive.double
                    val lyricsS = kw.getValue("lyrics_s").jsonPrimitive.double
                    check(misses, record, record.out!!) {
                        alignment(Align.lyricsOffset(lines, segments, beats, downbeats, audioS, lyricsS))
                    }
                    // Every candidate's scores to the bit, before lyrics_offset rounds any (the record's `fits`).
                    check(misses, record, record.extra.getValue("fits")) {
                        val scored = Align.scored(lines, segments, beats, downbeats, audioS, lyricsS)
                        if (scored.early != null) JsonNull else fitsDigest(scored.fits)
                    }
                }
                "math.fsum" -> raises(record, misses) {
                    num(Py.mathFsum(record.args[0].jsonArray.map { it.jsonPrimitive.double }))
                }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        assertTrue("records of every kind: $counts",
                   counts.keys == setOf("shifted_lrc", "lyrics_offset", "math.fsum") && counts.getValue("lyrics_offset") > 30)
        misses.assertNone()
    }

    // --- vectors/autochords-sheet/sheet.jsonl ------------------------------------------------------------------

    fun sheet() {
        val misses = Misses("autochords-sheet/sheet.jsonl")
        val records = Corpus.records("autochords-sheet/sheet.jsonl")
        val named = records.filter { it.fn == "heard" }.associate { str(it.args[0]) to str(it.out!!) }
        val counts = HashMap<String, Int>()
        for (record in records) {
            counts.merge(record.fn, 1, Int::plus)
            val a = record.args
            val kw = record.kw
            when (record.fn) {
                "heard" -> check(misses, record, record.out!!) { JsonPrimitive(Heard.read(str(record.out!!)).json()) }
                "read_heard" -> raises(record, misses) { text(Heard.read(str(a[0])).json(), record.out!!) }
                "make_sheet" -> raises(record, misses) {
                    val song = song(kw.getValue("song").jsonObject)
                    val lyrics = lyricsFromJson(song.lyricsJson)
                    val transcript = kw["transcript"].orNull()?.jsonObject?.let(::transcript)
                    val made = SheetHalf.make(song, lyrics, Heard.read(named.getValue(str(kw.getValue("heard")))),
                                              kw["source"].orNull()?.let(::str), transcript,
                                              kw.getValue("silent").jsonPrimitive.content == "true",
                                              kw.getValue("said").jsonPrimitive.content == "true")
                    val raw = SheetHalf.raw(song, lyrics, made, kw["video"].orNull()?.let { PyJson.loads(str(it)).jsonObject },
                                            kw["maker"].orNull()?.jsonObject?.let(::maker))
                    JsonObject(made(made, record.out!!.jsonObject) + ("raw" to text(PyJson.dumps(raw),
                                                                                     record.out!!.jsonObject.getValue("raw"))))
                }
                "relay" -> check(misses, record, record.out!!) {
                    val song = song(kw.getValue("song").jsonObject)
                    val raw = withHeard(PyJson.loads(str(kw.getValue("raw"))).jsonObject, named)
                    val noted = kw["noted"].orNull()?.jsonObject?.let(::noted)
                    val want = record.out!!.jsonObject.getValue("relay").jsonObject
                    val relaid = try {
                        val made = Relay.relay(song, raw, noted)
                        val written = SheetHalf.raw(song, lyricsFromJson(song.lyricsJson), made)
                        JsonObject(made(made, want) + ("raw" to text(PyJson.dumps(written), want.getValue("raw"))))
                    } catch (e: IllegalArgumentException) {
                        JsonObject(mapOf("err" to JsonPrimitive("ValueError")))
                    }
                    JsonObject(linkedMapOf("due" to (Relay.due(song, raw, noted)?.let(::JsonPrimitive) ?: JsonNull),
                                           "noted_in" to noted(Relay.notedIn(raw)), "relay" to relaid))
                }
                "relays_here" -> check(misses, record, record.out!!) {
                    JsonPrimitive(Relay.relaysHere(song(a[0].jsonObject), a[1].jsonPrimitive.content == "true"))
                }
                "made_by_another" -> check(misses, record, record.out!!) {
                    JsonPrimitive(Relay.madeByAnother(PyJson.loads(str(a[0])).jsonObject, a[1].orNull()?.let(::str)))
                }
                "Timed.note" -> check(misses, record, record.out!!) {
                    val shift = a[0].orNull()?.jsonPrimitive?.double
                    Timed("", shift, a[1].jsonPrimitive.double).note()?.let(::JsonPrimitive) ?: JsonNull
                }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        assertTrue("records of every kind: $counts",
                   counts.keys == setOf("heard", "read_heard", "make_sheet", "relay", "relays_here", "made_by_another",
                                        "Timed.note") && counts.getValue("make_sheet") > 80 && counts.getValue("relay") > 80)
        misses.assertNone()
    }

    /** A song as the record names it: only the members make_sheet and relay_due read matter. */
    private fun song(kw: JsonObject): SongRow = SongRow(
        id = 7, key = "nobody|river road", artist = str(kw.getValue("artist")), title = str(kw.getValue("title")),
        artists = listOf(str(kw.getValue("artist"))), album = null, durationMs = null, isrc = null, sourceIds = "{}",
        addedAt = "", variant = null, status = "found", review = false, matchDecision = null, matchStep = null,
        matchScore = null, matchArtistKey = null, matchSongKey = null, matchCandidates = "[]", matchedAt = null,
        ugDirty = true, ugCheckedAt = null, lyricsStatus = str(kw.getValue("lyrics_status")),
        lyricsJson = kw["lyrics_json"].orNull()?.let(::str), lyricsAt = null, lacuerdaCheckedAt = null, createdAt = "",
        audioPath = kw["audio_path"].orNull()?.let(::str), audioMtime = kw["audio_mtime"].orNull()?.jsonPrimitive?.double,
        autochordsMtime = kw["autochords_mtime"].orNull()?.jsonPrimitive?.double,
    )

    private fun transcript(t: JsonObject) = Transcript(str(t.getValue("lrc")), str(t.getValue("made_at")))

    private fun maker(m: JsonObject) = Maker(
        str(m.getValue("on")), m["by"].orNull()?.let(::str),
        m.getValue("models").jsonArray.associateTo(LinkedHashMap()) { str(it.jsonArray[0]) to str(it.jsonArray[1]) },
        m["runtime"].orNull()?.let(::str),
        m["audio_name"].orNull()?.let(::str), m["audio_sha16"].orNull()?.let(::str),
    )

    private fun noted(n: JsonObject) = Noted(n["transcript"].orNull()?.jsonObject?.let(::transcript),
                                             n.getValue("silent").jsonPrimitive.content == "true",
                                             n.getValue("said").jsonPrimitive.content == "true")

    private fun noted(n: Noted): JsonElement = JsonObject(linkedMapOf(
        "transcript" to (n.transcript?.let { JsonObject(mapOf("lrc" to JsonPrimitive(it.lrc), "made_at" to JsonPrimitive(it.madeAt))) }
            ?: JsonNull),
        "silent" to JsonPrimitive(n.silent), "said" to JsonPrimitive(n.said),
    ))

    /** A raw whose `heard` names one of the records' hearings (a text), that hearing's record in its place. */
    private fun withHeard(raw: JsonObject, named: Map<String, String>): JsonObject {
        val heard = raw["heard"] as? JsonPrimitive ?: return raw
        if (!heard.isString) return raw
        return JsonObject(raw.mapValues { (k, v) -> if (k == "heard") PyJson.loads(named.getValue(heard.content)) else v })
    }

    /** A Made's members as the record writes them (its text whole, or by its digest as Python's). */
    private fun made(made: Made, want: JsonObject): Map<String, JsonElement> = linkedMapOf(
        "text" to text(made.text, want.getValue("text")), "used" to JsonPrimitive(made.used),
        "key" to (made.key?.let(::JsonPrimitive) ?: JsonNull), "shift" to (made.shift?.let(::num) ?: JsonNull),
        "silent" to JsonPrimitive(made.silent), "said" to JsonPrimitive(made.said),
    )

    // --- vectors/autochords-sheet/relay.jsonl ------------------------------------------------------------------

    /** relay_onto_sheets over its fixture library, step by step: the songs re-laid, every file of the songs' folders,
     * every version's raw as stored, each song unit's digest and each info.json, as Python's after that step. */
    fun relay() {
        val misses = Misses("autochords-sheet/relay.jsonl")
        val records = Corpus.records("autochords-sheet/relay.jsonl")
        misses.check(records.isNotEmpty()) { "relay.jsonl: no records" }
        for (record in records) {
            val (fixture, steps) = record.args
            val outs = record.out!!.jsonArray
            world(fixture) { database, library ->
                for ((n, step) in steps.jsonArray.withIndex()) {
                    val want = outs[n].jsonObject
                    val named = step.jsonObject.getValue("relay")
                    database.writeBlocking { db ->
                        val only = if (named is JsonNull) null else named.jsonArray.map { it.jsonPrimitive.long }
                        val relayed = Relay.onto(db, library, Overrides.read(db), only)
                        val relaid = relayed.songs.map { it.id }
                        val wantIds = want.getValue("relaid").jsonArray.map { it.jsonPrimitive.long }
                        misses.check(relaid == wantIds) { "step $n: re-laid $relaid, Python's $wantIds" }
                        val failed = relayed.failed.keys.sorted()
                        val wantFailed = want.getValue("failed").jsonArray.map { it.jsonPrimitive.long }
                        misses.check(failed == wantFailed) { "step $n: failed ${relayed.failed}, Python's $wantFailed" }
                        val raws = db.query("SELECT id, raw FROM versions ORDER BY id") { it.long(0)!!.toString() to it.text(1)!! }.toMap()
                        for ((id, text) in want.getValue("raws").jsonObject) {
                            misses.check(raws[id] == str(text)) { "step $n: version $id's raw is\n${raws[id]}\nPython's\n${str(text)}" }
                        }
                        for ((unit, digest) in want.getValue("units").jsonObject) {
                            val mine = Units.digestOf(db, unit)
                            misses.check(mine == str(digest)) { "step $n: $unit is $mine, Python's $digest" }
                        }
                    }
                    val files = library.walkTopDown().filter { it.isFile && it.parentFile != library }
                        .map { f -> val b = f.readBytes(); listOf(f.relativeTo(library).invariantSeparatorsPath, Canonical.sha256Hex(b), b.size.toString()) }
                        .sortedWith { x, y -> Py.CODE_POINT_ORDER.compare(x[0], y[0]) }.toList()
                    val wantFiles = want.getValue("files").jsonArray.map { f -> f.jsonArray.map { it.jsonPrimitive.content } }
                    misses.check(files == wantFiles) { "step $n: files $files, Python's $wantFiles" }
                    for ((path, text) in want.getValue("info").jsonObject) {
                        val mine = File(library, path).takeIf { it.isFile }?.readText()
                        misses.check(mine == str(text)) { "step $n: $path is\n$mine\nPython's\n${str(text)}" }
                    }
                }
            }
        }
        misses.assertNone()
    }

    /** relay.jsonl's library, loaded into a fresh database and library folder for [block] (RelayTest's and
     * PhoneRenderTest's own cases over it). */
    fun relayLibrary(block: (Database, File) -> Unit) =
        world(Corpus.records("autochords-sheet/relay.jsonl").single().args[0], block)

    /** The record's fixture in a fresh database and library folder of its own, gone after [block]. */
    private fun world(fixture: JsonElement, block: (Database, File) -> Unit) {
        val dir = Files.createTempDirectory("caracole-relay").toFile()
        try {
            val library = File(dir, "library").apply { mkdirs() }
            TestDb.fresh(dir).use { database ->
                database.writeBlocking { db -> Fixtures.loadRecords(db, fixture.jsonArray.map { it.jsonObject }, library) }
                block(database, library)
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    // --- shapes -------------------------------------------------------------------------------------------------

    /** Checks [got] against [want], numbers to the bit. */
    private fun check(misses: Misses, record: Record, want: JsonElement, got: () -> JsonElement) {
        val answer = try {
            got()
        } catch (e: Exception) {
            misses.check(false) { "${record.fn}(${record.args.toString().take(160)}${record.kw.toString().take(160)}) threw $e" }
            return
        }
        misses.check(same(answer, want)) {
            "${record.fn}(${record.args.toString().take(160)}${record.kw.toString().take(200)}) = " +
                "${answer.toString().take(600)}, Python's ${want.toString().take(600)}"
        }
    }

    /** A record that may have raised: then the call must throw what Python's exception stands for. */
    private fun raises(record: Record, misses: Misses, got: () -> JsonElement) {
        val err = record.err ?: return check(misses, record, record.out!!, got)
        val thrown = try {
            got()
            null
        } catch (e: Exception) {
            e
        }
        val expected = when (err) {
            "ValueError" -> thrown is IllegalArgumentException
            "OverflowError" -> thrown is ArithmeticException
            else -> false
        }
        misses.check(expected) { "${record.fn}(${record.args.toString().take(120)}) gave ${thrown ?: "no error"}, Python raised $err" }
    }

    /** Two JSON values alike, a number by its double to the bit (a string "inf", "-inf" or "nan" a float's repr). */
    private fun same(a: JsonElement, b: JsonElement): Boolean = when {
        a is JsonArray && b is JsonArray -> a.size == b.size && a.indices.all { same(a[it], b[it]) }
        a is JsonObject && b is JsonObject -> a.keys == b.keys && a.keys.all { same(a.getValue(it), b.getValue(it)) }
        a is JsonPrimitive && b is JsonPrimitive && !a.isString && !b.isString && a !is JsonNull && b !is JsonNull &&
            a.content != "true" && a.content != "false" ->
            java.lang.Double.compare(a.double, b.double) == 0
        else -> a == b
    }

    private fun JsonElement?.orNull(): JsonElement? = if (this == null || this is JsonNull) null else this

    private fun str(e: JsonElement): String = e.jsonPrimitive.content

    private fun num(x: Double): JsonElement = when {
        x.isNaN() -> JsonPrimitive("nan")
        x == Double.POSITIVE_INFINITY -> JsonPrimitive("inf")
        x == Double.NEGATIVE_INFINITY -> JsonPrimitive("-inf")
        else -> JsonPrimitive(x)
    }

    /** A list of times, or the series `{"start", "step", "n"}` it is: `start + k * step`. */
    private fun times(e: JsonElement): List<Double> {
        if (e is JsonObject) {
            val start = e.getValue("start").jsonPrimitive.double
            val step = e.getValue("step").jsonPrimitive.double
            return (0 until e.getValue("n").jsonPrimitive.int).map { start + it * step }
        }
        return e.jsonArray.map { it.jsonPrimitive.double }
    }

    private fun segments(e: JsonElement): List<ChordSegment> = e.jsonArray.map {
        val s = it.jsonArray
        ChordSegment(s[0].jsonPrimitive.double, s[1].jsonPrimitive.double, str(s[2]))
    }

    private fun segs(segs: List<ChordSegment>): JsonElement =
        JsonArray(segs.map { JsonArray(listOf(num(it.start), num(it.end), JsonPrimitive(it.label))) })

    private fun placed(e: JsonElement): List<Pair<Int, String>> =
        e.jsonArray.map { it.jsonArray[0].jsonPrimitive.int to str(it.jsonArray[1]) }

    private fun placed(p: List<Pair<Int, String>>): JsonElement =
        JsonArray(p.map { JsonArray(listOf(JsonPrimitive(it.first), JsonPrimitive(it.second))) })

    private fun lrcLine(e: JsonElement): LrcLine {
        val l = e.jsonArray
        val words = l[2].orNull()?.jsonArray?.map { WordStart(it.jsonArray[0].jsonPrimitive.double, it.jsonArray[1].jsonPrimitive.int) }
        return LrcLine(l[0].jsonPrimitive.double, str(l[1]), words)
    }

    private fun lrcLines(lines: List<LrcLine>): JsonElement = JsonArray(lines.map { line ->
        JsonArray(listOf(num(line.time), JsonPrimitive(line.text), line.words?.let { w ->
            JsonArray(w.map { JsonArray(listOf(num(it.time), JsonPrimitive(it.column))) })
        } ?: JsonNull))
    })

    /** A text as the record holds it: whole, or its digest and length when the record has them. */
    private fun text(got: String, want: JsonElement): JsonElement {
        if (want !is JsonObject) return JsonPrimitive(got)
        val sha = Canonical.sha256Hex(got.toByteArray(Charsets.UTF_8)).substring(0, 16)
        return JsonObject(mapOf("sha256" to JsonPrimitive(sha), "size" to JsonPrimitive(Py.len(got))))
    }

    /** The SHA-256 (16 hex digits) of every fit's offset, score, onsets and coverage as big-endian doubles. */
    private fun fitsDigest(fits: List<Align.Fit>): JsonElement {
        val bytes = java.nio.ByteBuffer.allocate(fits.size * 32)
        for (f in fits) bytes.putDouble(f.offset).putDouble(f.score).putDouble(f.onsets).putDouble(f.coverage)
        val sha = Canonical.sha256Hex(bytes.array()).substring(0, 16)
        return JsonObject(mapOf("sha256" to JsonPrimitive(sha), "n" to JsonPrimitive(fits.size)))
    }

    private fun alignment(a: Alignment): JsonElement = JsonObject(mapOf(
        "offset" to (a.offset?.let(::num) ?: JsonNull), "why" to JsonPrimitive(a.why),
        "best" to (a.best?.let(::num) ?: JsonNull), "score" to (a.score?.let(::num) ?: JsonNull),
        "runner_up" to (a.runnerUp?.let(::num) ?: JsonNull),
    ))
}
