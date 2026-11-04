package io.github.danielhp95.caracole.viewer.progressions

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.viewer.harmony.Harmony
import io.github.danielhp95.caracole.viewer.shapes.Voicings
import io.github.danielhp95.caracole.viewer.sheet.ChordRow
import io.github.danielhp95.caracole.viewer.sheet.Item
import io.github.danielhp95.caracole.viewer.sheet.Lyrics
import io.github.danielhp95.caracole.viewer.sheet.SheetView
import io.github.danielhp95.caracole.viewer.sheet.Sheets
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import io.github.danielhp95.caracole.viewer.version.VersionData
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull

/** progressions.Wanted: a progression asked for, its own key, every key a song may play it as, its catalogue name and
 * how it is said. */
data class Wanted(val key: String, val keys: Set<String>, val name: String?, val label: String)

/** progressions.Playing: a song that plays a progression, the sections that do, and the key its sheet was read in. */
data class Playing(val song: SongRow, val sections: List<String>, val key: String)

/**
 * progressions.py: each song's progressions, read as its sheet is rendered and kept in kv `render:progressions:<song
 * id>` ([record], the text json.dumps writes), so the library page's data ([library]), `#prog=`, /api/search's
 * `progression` and a search by progression ([read], [songsWith]) read one row a song, never a sheet. Function for
 * function as progressions.py, its constants and patterns its own (caracole/viewer/version.json's `progressions`);
 * every answer held by vectors/viewer/progressions.jsonl (VersionReplay).
 *
 * Where Kotlin holds less than Python: a record's song id past a Long is none (Python's whole number names no song).
 */
object Progressions {
    private val D get() = VersionData.progressions

    /** KV: kv, then the song's id: its sheet's progressions. */
    val KV: String by lazy { D.text("KV") }

    /** UNNAMED: what a section with no heading is called where its name is said. */
    val UNNAMED: String by lazy { D.text("UNNAMED") }

    private val TYPED by lazy { D.pattern("_TYPED") }
    private val SEPARATORS by lazy { D.pattern("_SEPARATORS") }
    private val WORD by lazy { D.pattern("_WORD") }
    private val APOSTROPHES by lazy { D.pattern("_APOSTROPHES") }
    private val GENERIC by lazy { D.set("_GENERIC") }
    private val SAYS_PROGRESSION by lazy { D.set("_SAYS_PROGRESSION") }
    private val NAME_LETTERS by lazy { D.int("_NAME_LETTERS") }
    private val NOT_ALONE by lazy { D.set("_NOT_ALONE") }
    private val TITLES by lazy { D.set("_TITLES") }

    /** label: a progression's key as it is written: "I V vi IV" is "I–V–vi–IV". */
    fun label(key: String): String = Py.split(key).joinToString("–")

    /** catalogue: each progression of harmony's CATALOGUE by its key, in its own key and read in the relative one,
     * each name's first key its first row's. */
    fun catalogue(): Map<String, String> = Harmony.catalogue()

    /** key_words: "C major", "A minor", "D Dorian". */
    fun keyWords(key: Key): String {
        val mode = when (key.mode) {
            "ionian" -> "major"
            "aeolian" -> "minor"
            else -> PyUnicode.capitalize(key.mode)
        }
        return "${Theory.spelling(key)[key.tonic]} $mode"
    }

    /**
     * sheet_progressions: what a ChordPro sheet plays, as [record] keeps it: `{"key": "C major", "sections":
     * [{"section", "numerals", "repeats", "name", "ending", "key", "contains": [{"name", "key", "numerals"}]}]}`,
     * each section's heading (null for none), in the key its viewer reads it in ([key], the song's, from
     * [keySource], else the sheet's own, else estimated). A chord legend's line is no chord played; one caracole
     * can't read (N.C.) is left out. Null for a sheet with no chord it can read.
     */
    fun sheetProgressions(cho: String, key: String?, keySource: String? = null): JsonObject? {
        val shapes = SheetView.viewerKey(cho, key, keySource) ?: return null
        val sheet = Sheets.parse(cho)
        val sections = sheet.sections.map { section ->
            val played = ArrayList<Chord?>()
            for (line in section.lines) {
                if (line !is Lyrics && line !is ChordRow) continue
                if (Voicings.chordLegend(Sheets.written(line, sheet.chords)).isNotEmpty()) continue
                val items = if (line is Lyrics) line.parts.map { it.first } else (line as ChordRow).items
                for (item in items) if (item is Item.Chord) played += Theory.parseChord(sheet.chords[item.index], strict = false)
            }
            (section.label ?: "") to played.toList()
        }
        val found = Harmony.progressions(sections, shapes)
        if (found.isEmpty()) return null
        return JsonObject(linkedMapOf(
            "key" to JsonPrimitive(keyWords(shapes)),
            "sections" to JsonArray(found.map { (name, p) ->
                JsonObject(linkedMapOf(
                    "section" to (name.ifEmpty { null }?.let(::JsonPrimitive) ?: JsonNull),
                    "numerals" to strings(p.numerals),
                    "repeats" to JsonPrimitive(p.repeats),
                    "name" to (p.name?.let(::JsonPrimitive) ?: JsonNull),
                    "ending" to (p.ending?.let(::JsonPrimitive) ?: JsonNull),
                    "key" to JsonPrimitive(Harmony.progressionKey(p.numerals)),
                    "contains" to JsonArray(p.contains.map { c ->
                        JsonObject(linkedMapOf("name" to JsonPrimitive(c.name), "key" to JsonPrimitive(c.key),
                                               "numerals" to strings(c.numerals)))
                    }),
                ))
            }),
        ))
    }

    private fun strings(xs: List<String>): JsonArray = JsonArray(xs.map(::JsonPrimitive))

    /** record: keep what the song's sheet [cho] plays ([sheetProgressions]) in kv `render:progressions:<song id>`,
     * written only when it changed (as json.loads reads what is there); a sheet that plays nothing leaves no record.
     * A record there that is no JSON is PyJson.DecodeError, as kv_get_json's is. */
    fun record(db: Db, songId: Long, cho: String, key: String?, keySource: String? = null) {
        val found = sheetProgressions(cho, key, keySource)
        if (found == null) {
            forget(db, songId)
            return
        }
        val text = PyJson.dumps(found)
        val current = db.kvGet("$KV$songId")
        if (current == text || (current != null && PyJson.loads(current) == found)) return
        db.kvSet("$KV$songId", text)
    }

    /** forget: the song keeps no sheet: no progressions. */
    fun forget(db: Db, songId: Long) {
        db.kvDelete("$KV$songId")
    }

    /** any_recorded: whether any song's progressions were read. */
    fun anyRecorded(db: Db): Boolean =
        db.one("SELECT 1 FROM kv WHERE substr(key, 1, ?) = ? LIMIT 1", KV.length, KV) { true } ?: false

    // --- the records, read as data ---------------------------------------------------------------------------------

    private fun text(e: JsonElement?): String? = (e as? JsonPrimitive)?.takeIf { it.isString }?.content

    private fun strings(e: JsonElement?): List<String>? {
        val list = e as? JsonArray ?: return null
        return list.map { text(it) ?: return null }
    }

    /** _searchable: a record's sections that are progressions to search: a cycle of two chords or more, its key and
     * numerals well formed. */
    private fun searchable(record: JsonElement?): List<JsonObject> {
        val sections = (record as? JsonObject)?.get("sections") as? JsonArray ?: return emptyList()
        return sections.mapNotNull { s ->
            val section = s as? JsonObject ?: return@mapNotNull null
            val key = text(section["key"]) ?: return@mapNotNull null
            if (' ' !in key || strings(section["numerals"]) == null) null else section
        }
    }

    /** _records: every song's record, by song id, in the order SQLite reads kv, those with sections to search. */
    private fun records(db: Db): LinkedHashMap<Long, JsonObject> {
        val found = LinkedHashMap<Long, JsonObject>()
        val rows = db.query("SELECT key, value FROM kv WHERE substr(key, 1, ?) = ?", KV.length, KV) {
            it.text(0)!! to it.text(1)!!
        }
        for ((key, value) in rows) {
            val number = key.substring(KV.length)
            if (number.isEmpty() || !number.all { it in '0'..'9' }) continue
            val id = number.toLongOrNull() ?: continue
            val record = try {
                PyJson.loads(value)
            } catch (e: PyJson.DecodeError) {
                continue
            }
            if (searchable(record).isNotEmpty()) found[id] = record as JsonObject
        }
        return found
    }

    /** _contained: the named progressions a record's section plays within it, those well formed. */
    private fun contained(section: JsonObject): List<JsonObject> {
        val contains = section["contains"] as? JsonArray ?: return emptyList()
        return contains.mapNotNull { c ->
            val o = c as? JsonObject ?: return@mapNotNull null
            val key = text(o["key"])
            if (text(o["name"]) == null || key == null || ' ' !in key || strings(o["numerals"]) == null) null else o
        }
    }

    /**
     * library_progressions: what the library page's data gives each song: its progressions, each once, in the order
     * its sheet plays them, `{"key": "I V vi IV", "plays": "vi–IV–I–V"}` (as its first section that plays it does):
     * each section's cycle, then those of the catalogue it plays within it, by their name's key, and a section that is
     * a named progression whole by its name's key too, where its own is none of that name's.
     */
    fun library(db: Db): Map<Long, JsonArray> {
        val names = catalogue()
        val keys = HashMap<String, String>()  // each name's first key
        for ((key, name) in names.entries.reversed()) keys[name] = key
        val found = LinkedHashMap<Long, JsonArray>()
        for ((id, record) in records(db)) {
            val seen = LinkedHashMap<String, String>()
            for (s in searchable(record)) {
                val plays = strings(s["numerals"])!!.joinToString("–")
                val own = text(s["key"])!!
                seen.putIfAbsent(own, plays)
                val name = text(s["name"])
                if (name != null && name in keys && names[own] != name) seen.putIfAbsent(keys.getValue(name), plays)
                for (c in contained(s)) seen.putIfAbsent(text(c["key"])!!, strings(c["numerals"])!!.joinToString("–"))
            }
            found[id] = JsonArray(seen.map { (key, plays) ->
                JsonObject(linkedMapOf("key" to JsonPrimitive(key), "plays" to JsonPrimitive(plays)))
            })
        }
        return found
    }

    /** read_progression: the progression [text] asks for: numerals, two chords or more ("vi IV I V"), or a catalogue
     * name or words of one ("andalusian"); null for anything else. */
    fun read(text: String): Wanted? {
        val names = catalogue()
        val tokens = PyRe.split(SEPARATORS, Py.strip(text)).filterNotNull().filter { it.isNotEmpty() }
        if (tokens.isNotEmpty() && tokens.all { PyRe.fullmatch(TYPED, it) != null }) {
            val read = Harmony.readTyped(tokens)
            val key = Harmony.progressionKey(read)
            if (' ' !in key) return null
            val name = Harmony.nameOf(read)
            // A name that is numerals ("ii–V–I", whose key is "I ii V") says them as they are played.
            val said = if (name != null && Harmony.progressionKey(name) == key) name else label(key)
            val keys = LinkedHashSet<String>()
            keys += key
            if (name != null) names.forEach { (k, n) -> if (n == name) keys += k }
            return Wanted(key, keys, name, said)
        }
        val words = words(text)
        val rest = words.filter { it !in GENERIC }
        val says = words.any { it in SAYS_PROGRESSION }
        val short = rest.sumOf { Py.len(it) } < NAME_LETTERS && !says
        if (rest.isEmpty() || short || (rest.size == 1 && rest[0] in NOT_ALONE) || (TITLES.containsAll(rest) && !says)) {
            return null
        }
        val wanted = words.toSet()
        val found = LinkedHashSet(names.values).filter { name -> words(name).toSet().containsAll(wanted) }
        if (found.isEmpty()) return null
        val keys = names.filter { it.value in found }.keys.toList()
        return Wanted(keys[0], LinkedHashSet(keys), found[0], found.joinToString(" or "))
    }

    /** _words: the words of [text], folded, its apostrophes dropped. */
    private fun words(text: String): List<String> =
        PyRe.findall(WORD, PyRe.sub(APOSTROPHES, Normalize.fold(text)) { "" })

    /** _plays: a record's section plays [wanted]: its cycle is one of its keys, or, for a named progression, the
     * section is it whole or plays it within it. */
    private fun plays(section: JsonObject, wanted: Wanted): Boolean {
        if (text(section["key"]) in wanted.keys) return true
        if (wanted.name == null) return false
        return text(section["name"]) == wanted.name || contained(section).any { text(it["name"]) == wanted.name }
    }

    /** songs_with: your songs that play [w] (any of its keys, or its name within a section), by name (casefolded,
     * then by id). A section is named by its heading, [UNNAMED] for none, as Python's `str` writes what a record
     * holds. */
    fun songsWith(db: Db, w: Wanted): List<Playing> {
        val records = records(db)
        val order = compareBy<SongRow, String>(Py.CODE_POINT_ORDER) { PyUnicode.casefold(it.display) }.thenBy { it.id }
        val found = ArrayList<Playing>()
        for (song in Songs.list(db).sortedWith(order)) {
            val record = records[song.id] ?: continue
            val sections = searchable(record).filter { plays(it, w) }.map { s ->
                val named = s["section"]
                if (named == null || falsy(named)) UNNAMED else pyStr(named)
            }
            if (sections.isNotEmpty()) {
                found += Playing(song, sections.distinct(), text(record["key"]) ?: "")
            }
        }
        return found
    }

    /** Whether Python reads the JSON value as false: None, "", 0, 0.0, False, [], {}. */
    private fun falsy(e: JsonElement): Boolean = when (e) {
        is JsonNull -> true
        is JsonArray -> e.isEmpty()
        is JsonObject -> e.isEmpty()
        is JsonPrimitive -> when {
            e.isString -> e.content.isEmpty()
            e.content == "true" -> false
            e.content == "false" -> true
            else -> e.doubleOrNull == 0.0
        }
    }

    /** Python's `str` of what json.loads made of [e]: a text itself, anything else its repr. */
    private fun pyStr(e: JsonElement): String = text(e) ?: repr(e)

    private fun repr(e: JsonElement): String = when (e) {
        is JsonNull -> "None"
        is JsonArray -> e.joinToString(", ", "[", "]") { repr(it) }
        is JsonObject -> e.entries.joinToString(", ", "{", "}") { (k, v) -> "${PyStr.repr(k)}: ${repr(v)}" }
        is JsonPrimitive -> when {
            e.isString -> PyStr.repr(e.content)
            e.content == "true" -> "True"
            e.content == "false" -> "False"
            e.content.removePrefix("-").let { d -> d.isNotEmpty() && d.all { it in '0'..'9' } } -> e.content.toBigInteger().toString()
            else -> e.doubleOrNull?.let { d ->
                when {
                    d.isNaN() -> "nan"
                    d.isInfinite() -> if (d > 0) "inf" else "-inf"
                    else -> PyJson.floatText(d)
                }
            } ?: e.content
        }
    }
}
