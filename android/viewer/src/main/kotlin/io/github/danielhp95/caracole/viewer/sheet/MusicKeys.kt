package io.github.danielhp95.caracole.viewer.sheet

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFloat
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.attribute.BasicFileAttributes

/** keys.SongKey: a song's key ("A minor", "C") and where it came from: one of [MusicKeys.SOURCES]. */
data class SongKey(val key: String, val source: String) {
    /** For people: "A minor (from the tab)", "C major (estimated from the chords)". */
    fun describe(): String = "${MusicKeys.keyName(key)} (${MusicKeys.SOURCES.getValue(source)})"
}

/**
 * keys.py: a song's musical key, read from its tab or estimated from its chords, over the phone's files and versions.
 *
 * A key is written as its tonic, a letter with `#` or `b`, followed by " minor" for a minor key: "A minor", "C", "F#",
 * "Bb minor"; the spelling is the source's. An estimate is the key of the chords as the sheet writes them, the shapes
 * played. A tab's own key is as its transcriber gives it, but for a letter alone ("A", "La"): that is the parallel
 * minor where the sheet's chords say so (Theory.bareKey), with the capo in sheet.json's `meta`. [songKey] gives the
 * human sheet's key (`tab`: UG's `tonality_name`, else a key its markup states; `chords`: estimated from its chords),
 * else the auto sheet's (`audio`: the key the model heard, else estimated from the sheet it wrote).
 *
 * [estimateKey] finds the key of a progression: every chord's notes make a histogram of the 12 pitch classes, whose
 * correlation with the Krumhansl–Kessler profile of each of the 24 keys says which scale the song lives in; the tonic
 * chord decides between a key and its relative minor. Its sums are Python's (the builtin sum of floats, Py.fsum), so
 * a near tie goes as it does on the computer.
 */
object MusicKeys {
    private val K get() = SheetData.keys
    private val KEY_HEAD by lazy { K.pattern("_KEY_HEAD") }
    private val KEY_HEAD_ENGLISH by lazy { K.pattern("_KEY_HEAD_ENGLISH") }
    private val KEY_LABEL by lazy { K.pattern("_KEY_LABEL") }
    private val DIRECTIVE by lazy { K.pattern("_DIRECTIVE") }
    private val CHORD_TAG by lazy { K.pattern("_CHORD_TAG") }
    private val CHORD by lazy { K.pattern("_CHORD") }
    private val QUALITY by lazy { K.pattern("_QUALITY") }
    private val ADDED by lazy { K.pattern("_ADDED") }
    private val EXTENDED by lazy { K.pattern("_EXTENDED") }
    private val MAJOR_SEVENTH by lazy { K.pattern("_MAJOR_SEVENTH") }
    private val LETTERS by lazy { K.ints("_LETTERS") }
    private val SOLFEGE by lazy { K.strings("_SOLFEGE") }
    private val ACCIDENTALS by lazy { K.strings("_ACCIDENTALS") }
    private val SHIFT by lazy { K.ints("_SHIFT") }
    private val DIMINISHED by lazy { K.list("_DIMINISHED") }
    private val MAJOR_PROFILE by lazy { K.obj("_PROFILES").let { SheetData.Module(it).doubles("major") } }
    private val MINOR_PROFILE by lazy { K.obj("_PROFILES").let { SheetData.Module(it).doubles("minor") } }
    private val MIN_FIT by lazy { K.double("MIN_FIT") }
    private val TONIC_SHARE by lazy { K.double("TONIC_SHARE") }
    private val EDGE by lazy { K.double("EDGE") }
    private val MAJOR_NAMES by lazy { K.list("_MAJOR_NAMES") }
    private val MINOR_NAMES by lazy { K.list("_MINOR_NAMES") }

    /** keys.SOURCES: where a key came from, in words. */
    val SOURCES: Map<String, String> by lazy { K.strings("SOURCES") }

    /** keys.SHEET_DOC: the human sheet's markup, beside it; songs.HUMAN_SHEET and AUTO_SHEET, the sheets. */
    val SHEET_DOC: String by lazy { K.text("SHEET_DOC") }
    val HUMAN_SHEET: String by lazy { K.text("HUMAN_SHEET") }
    val AUTO_SHEET: String by lazy { K.text("AUTO_SHEET") }

    // --- a key named -------------------------------------------------------------------------------------------------

    /** parse_key: a key as caracole writes it, from the ways tabs write one ("Am", "A min" and "La menor" are
     * "A minor"; "C", "C major" and "Do" are "C"; "E♭" is "Eb"); null if [text] is no key. A letter alone is its major
     * key here: [sheetKey] reads a tab's again with its chords. */
    fun parseKey(text: String): String? = named(text)?.first

    /** _named: [parseKey]'s key, and whether [text] named it by its letter alone, with no mode ("A", "La"). */
    internal fun named(text: String): Pair<String, Boolean>? =
        PyRe.fullmatch(KEY_HEAD, Py.strip(text))?.let(::canonical)

    /** key_name: the key with its mode spelled out, for people: "C major", "A minor". */
    fun keyName(key: String): String = if (key.endsWith(" minor")) key else "$key major"

    /** same_key: whether two keys sound the same: "F# minor" is "Gb minor". */
    fun sameKey(a: String, b: String): Boolean {
        val pa = pitch(a)
        return pa != null && pa == pitch(b)
    }

    /** key_in_text: the key a sheet states itself, in UG markup or plain text: a ChordPro `{key: …}` anywhere, or a
     * note before the first chords ("Key: G", "Key of Bb", "Tono: La menor"); null if it states none. */
    fun keyInText(sheet: String): String? = stated(sheet)?.first

    /** _stated: [keyInText]'s key, and whether the sheet named it by its letter alone. */
    internal fun stated(sheet: String): Pair<String, Boolean>? {
        val lines = PyStr.splitlines(sheet)
        for (raw in lines) {
            val directive = PyRe.fullmatch(DIRECTIVE, raw) ?: continue
            named(directive.groupValues[1])?.let { return it }
        }
        for (raw in lines) {
            if (ChordPro.isChordLine(raw)) return null
            val line = PyRe.sub(CHORD_TAG, raw) { it.groupValues[1] }
            for (label in PyRe.finditer(KEY_LABEL, line)) {
                val english = label.groups[1]?.value.orEmpty().isNotEmpty()
                val m = (if (english) KEY_HEAD_ENGLISH else KEY_HEAD).matchAt(line, label.range.last + 1)
                if (m != null) return canonical(m)
            }
            if (PyRe.search(CHORD_TAG, raw) != null) return null // the chords have started
        }
        return null
    }

    /** chords_in_sheet: the chords of a sheet in UG markup (`[ch]X[/ch]`), in order, with letter names. */
    fun chordsInSheet(markup: String): List<String> =
        PyStr.splitlines(markup).flatMap { line ->
            PyRe.finditer(CHORD_TAG, ChordPro.tagForgotten(line)).map { Py.strip(it.groupValues[1]) }.toList()
        }.filter { it.isNotEmpty() }.map(ChordPro::normalizeChord)

    // --- an estimate -------------------------------------------------------------------------------------------------

    /** estimate_key of chord names, each counted once. */
    fun estimateKey(names: List<String>): String? = estimateWeighted(names.map { it to 1.0 })

    /**
     * estimate_key: the key a progression is most likely in, or null. Each item is a chord name and how long it
     * sounds; names that aren't chords ("N.C.", "x2") and weights of 0 or less are skipped. Chords that fit no key
     * well (a correlation under MIN_FIT) give no estimate.
     */
    fun estimateWeighted(items: List<Pair<String, Double>>): String? {
        class Played(val root: Int, val triad: String?, val weight: Double, val spelling: String)

        val played = ArrayList<Played>()
        val histogram = DoubleArray(12)
        for ((name, weight) in items) {
            val c = chord(name) ?: continue
            if (weight <= 0) continue
            played += Played(c.root, c.triad, weight, c.spelling)
            for ((interval, share) in c.tones) histogram[Math.floorMod(c.root + interval, 12)] += share * weight
        }
        if (played.isEmpty()) return null
        val total = Py.fsum(played.map { it.weight })
        val weights = LinkedHashMap<Pair<Int, String?>, Double>() // how long each (root, triad) sounds
        for (p in played) weights[p.root to p.triad] = (weights[p.root to p.triad] ?: 0.0) + p.weight
        val first = played.first()
        val last = played.last()
        var bestScore = Double.NEGATIVE_INFINITY
        var bestFit = 0.0
        var bestTonic = 0
        var bestMinor = false
        val hist = histogram.toList()
        for (minor in listOf(false, true)) {
            val profile = if (minor) MINOR_PROFILE else MAJOR_PROFILE
            for (tonic in 0 until 12) {
                val fit = correlation(hist, (0 until 12).map { profile[Math.floorMod(it - tonic, 12)] })
                val tonics = weights.map { (rt, w) -> w * tonicChord(rt.first, rt.second, tonic, minor) }
                val share = Py.fsum(tonics) / total
                val starts = tonicChord(first.root, first.triad, tonic, minor)
                val ends = tonicChord(last.root, last.triad, tonic, minor)
                val score = fit + TONIC_SHARE * share + EDGE * (starts + ends)
                if (score > bestScore) {
                    bestScore = score
                    bestFit = fit
                    bestTonic = tonic
                    bestMinor = minor
                }
            }
        }
        if (bestFit < MIN_FIT) return null
        val spelled = Py.mostCommonFirst(played.filter { it.root == bestTonic }.map { it.spelling }) // the chords' own
        val name = spelled ?: (if (bestMinor) MINOR_NAMES else MAJOR_NAMES)[bestTonic]
        return if (bestMinor) "$name minor" else name
    }

    /** _correlation: Pearson's correlation of two equal-length lists, summed as Python sums them; 0 when either is
     * flat. */
    internal fun correlation(a: List<Double>, b: List<Double>): Double {
        require(a.size == b.size) { "lists of ${a.size} and ${b.size}" }
        val ma = Py.fsum(a) / a.size
        val mb = Py.fsum(b) / b.size
        val num = Py.fsum(a.indices.map { (a[it] - ma) * (b[it] - mb) })
        val den = Math.sqrt(Py.fsum(a.map { (it - ma) * (it - ma) }) * Py.fsum(b.map { (it - mb) * (it - mb) }))
        return if (den != 0.0) num / den else 0.0
    }

    /** _tonic_chord: how much a chord is the key's tonic chord: 1 for its triad, 0.5 for a power or sus chord on it. */
    private fun tonicChord(root: Int, triad: String?, tonic: Int, minor: Boolean): Double = when {
        root != tonic -> 0.0
        triad == (if (minor) "minor" else "major") -> 1.0
        triad == "open" -> 0.5
        else -> 0.0
    }

    /** keys._chord: a chord's root (pitch class) and its spelling, its triad ("major", "minor", "open" for a power or
     * sus chord, null for diminished and augmented) and its notes with their weights (a seventh at half weight). */
    internal class KeyChord(val root: Int, val spelling: String, val triad: String?, val tones: List<Pair<Int, Double>>)

    internal fun chord(name: String): KeyChord? {
        val m = PyRe.fullmatch(CHORD, ChordPro.normalizeChord(Py.strip(name))) ?: return null
        val quality = m.groupValues[3]
        if (PyRe.fullmatch(QUALITY, quality) == null) return null
        val letter = m.groupValues[1]
        val accidental = ACCIDENTALS.getValue(m.groupValues[2])
        val root = Math.floorMod(LETTERS.getValue(letter) + SHIFT.getValue(accidental), 12)
        val q = PyUnicode.lower(quality)
        val (triad, third, fifth) = when {
            q.startsWith("m7b5") || q.startsWith("m7-5") || q.startsWith("ø") -> Triple(null, 3, 6)
            "sus2" in q -> Triple("open", 2, 7)
            "sus" in q -> Triple("open", 5, 7)
            quality.startsWith("maj") || quality.startsWith("M") || quality.startsWith("Δ") -> Triple("major", 4, 7)
            q.startsWith("min") || q.startsWith("m") || q.startsWith("-") -> Triple("minor", 3, 7)
            DIMINISHED.any { q.startsWith(it) } -> Triple(null, 3, 6)
            q.startsWith("aug") || q.startsWith("+") -> Triple(null, 4, 8)
            q.startsWith("5") -> Triple("open", null, 7)
            else -> Triple("major", 4, 7)
        }
        val tones = arrayListOf(0 to 1.0, fifth to 1.0)
        if (third != null) tones += third to 1.0
        val extended = PyRe.sub(ADDED, quality) { "" }
        when {
            PyRe.search(MAJOR_SEVENTH, extended) != null -> tones += 11 to 0.5
            DIMINISHED.any { q.startsWith(it) } && "7" in extended -> tones += 9 to 0.5
            PyRe.search(EXTENDED, extended) != null -> tones += 10 to 0.5
        }
        return KeyChord(root, letter + accidental, triad, tones)
    }

    // --- a song's key ------------------------------------------------------------------------------------------------

    /**
     * sheet_key: the key of a human sheet from its version's data ([raw]), its [markup] and its [capo]: UG's
     * `tonality_name`, else the key the markup states, else the one its chords suggest. A key named by its letter
     * alone is the parallel minor where the chords say so. A version kept beside the sheet takes its own so.
     */
    fun sheetKey(raw: JsonObject, markup: String?, capo: Int? = null): SongKey? {
        var named = namedIn(raw)
        if (named == null && markup != null) named = stated(markup)
        if (named != null) {
            val (key, bare) = named
            return SongKey(if (bare) readBare(key, markup, capo) else key, "tab")
        }
        if (markup == null) return null
        return estimateKey(chordsInSheet(markup))?.let { SongKey(it, "chords") }
    }

    /** _read_bare: a key a tab names by its letter alone ([key], read as major), as Theory.bareKey reads it with the
     * sheet's chords and capo: "A minor" for Hotel California's "A", and for a "C" over chords that centre on A minor,
     * C major's relative minor (its tonic spelled as the chords spell it); [key] as it is without chords to tell. */
    private fun readBare(key: String, markup: String?, capo: Int?): String {
        if (markup.isNullOrEmpty()) return key
        val names = chordsInSheet(markup)
        val played = names.mapNotNull { Theory.parseChord(it, strict = false) }
        val pitch = pitch(key)
        val read = if (pitch != null) Theory.bareKey(Key(pitch.first, "ionian"), capo ?: 0, played) else null
        if (read == null || read.mode != "aeolian") return key
        if (read.tonic == pitch!!.first) return "$key minor"
        val spellings = names.mapNotNull { name -> chord(name)?.takeIf { it.root == read.tonic }?.spelling }
        val spelled = Py.mostCommonFirst(spellings)
        return "${spelled ?: MINOR_NAMES[read.tonic]} minor"
    }

    /** A kept file's row (library.KeptFile's fields song_key reads). */
    private class Kept(val versionId: Long, val name: String, val path: String)

    private fun kept(db: Db, songId: Long): Map<String, Kept> {
        val out = LinkedHashMap<String, Kept>()
        db.query("SELECT version_id, name, path FROM files WHERE song_id = ? ORDER BY name", songId) {
            Kept(it.long(0)!!, it.text(1)!!, it.text(2)!!)
        }.forEach { out[it.name] = it }
        return out
    }

    /** versions.get_version(...).raw: a version's data, `{}` for none; NoSuchElementException for no version. */
    private fun raw(db: Db, versionId: Long): JsonObject {
        val text = db.one("SELECT raw FROM versions WHERE id = ?", versionId) { it.text(0) ?: "" }
            ?: throw NoSuchElementException("no version with id $versionId")
        return PyJson.loads(text.ifEmpty { "{}" }) as? JsonObject ?: JsonObject(emptyMap())
    }

    /** song_key: the song's key from the sheets it keeps, and its source; null without a sheet, or when no source
     * gives one: the human sheet's key, else the auto sheet's. Sheets are read from the library only as regular
     * files: one that can't be read, isn't UTF-8 or isn't JSON gives nothing, and the next source is tried. */
    fun songKey(db: Db, libraryDir: File, songId: Long): SongKey? {
        val (human, auto) = sheetKeys(db, libraryDir, songId)
        return human ?: auto
    }

    /** sheet_keys: the key of each sheet the song keeps, as [songKey] finds it: (the human sheet's, the auto
     * sheet's). Each sheet's viewer takes its own: the chords the model heard may be in another key than the tab. */
    fun sheetKeys(db: Db, libraryDir: File, songId: Long): Pair<SongKey?, SongKey?> {
        val kept = kept(db, songId)
        return humanKey(db, libraryDir, kept) to autoKey(db, libraryDir, kept)
    }

    private fun humanKey(db: Db, libraryDir: File, kept: Map<String, Kept>): SongKey? {
        val human = kept[HUMAN_SHEET] ?: return null
        val raw = raw(db, human.versionId)
        val named = namedIn(raw)
        if (named != null && !named.second) return SongKey(named.first, "tab") // its mode named: nothing else needed
        val (markup, capo) = markup(libraryDir, kept[SHEET_DOC], human)
        return sheetKey(raw, markup, capo)
    }

    /** letter_alone: the letter the song's human sheet names its key by alone (UG's `tonality_name`, else the key its
     * markup states), as caracole writes a key ("A", "Bb"); null for a key named with its mode, or none. */
    fun letterAlone(db: Db, libraryDir: File, songId: Long): String? {
        val kept = kept(db, songId)
        val human = kept[HUMAN_SHEET] ?: return null
        var named = namedIn(raw(db, human.versionId))
        if (named == null) {
            val markup = markup(libraryDir, kept[SHEET_DOC], human).first
            named = if (markup != null) stated(markup) else null
        }
        return if (named != null && named.second) named.first else null
    }

    private fun autoKey(db: Db, libraryDir: File, kept: Map<String, Kept>): SongKey? {
        val auto = kept[AUTO_SHEET] ?: return null
        namedIn(raw(db, auto.versionId), "key")?.let { return SongKey(it.first, "audio") }
        val text = text(File(libraryDir, auto.path)) ?: return null
        return estimateKey(chordsInSheet(text))?.let { SongKey(it, "audio") }
    }

    /** _named_in: the key a version's data gives in [field] (UG's `tonality_name`, often empty), if it is a key, and
     * whether it is a letter alone. */
    private fun namedIn(raw: JsonObject, field: String = "tonality_name"): Pair<String, Boolean>? {
        val value = raw[field] as? JsonPrimitive ?: return null
        return if (value.isString) named(value.content) else null
    }

    /** _markup: the human sheet's markup and its capo: the `content` of the sheet.json kept with it (of its own
     * version), and the capo in its `meta` ([sheetCapo]). Whatever the file holds gives null at worst. */
    private fun markup(libraryDir: File, doc: Kept?, sheet: Kept): Pair<String?, Int?> {
        if (doc == null || doc.versionId != sheet.versionId) return null to null
        val bytes = regularBytes(File(libraryDir, doc.path)) ?: return null to null
        val text = PyText.utf8(bytes) ?: return null to null
        val data = try {
            PyJson.loads(text)
        } catch (_: IllegalArgumentException) { // json's ValueError and its RecursionError
            return null to null
        }
        if (data !is JsonObject) return null to null
        val content = (data["content"] as? JsonPrimitive)?.takeIf { it.isString }?.content
        return content to sheetCapo(data["meta"])
    }

    /**
     * sheet_capo: the capo fret in UG's `meta` (sheet.json's, a version's JSON): a whole number, written as a number
     * or a string ("2", "2.0", as float() reads one), else no capo, as for 0. A capo past what an Int holds is none
     * (Python keeps its whole number); a JSON integer too large for a float raises, as Python's OverflowError.
     */
    fun sheetCapo(meta: JsonElement?): Int? {
        val value = (meta as? JsonObject)?.get("capo") as? JsonPrimitive ?: return null
        if (!value.isString && (value.booleanOrNull != null || value.content == "null")) return null
        val n = PyFloat.parse(value.content) ?: return null
        val integer = !value.isString && value.content.all { it in '0'..'9' || it == '-' } // a JSON int, as Python's
        if (integer && n.isInfinite()) throw ArithmeticException("int too large to convert to float")
        if (!n.isFinite() || n != Math.floor(n)) return null
        return if (n > 0 && n <= Int.MAX_VALUE) n.toInt() else null
    }

    /** _text: a library file as UTF-8 text, never read through a link; null if it can't be read so. */
    private fun text(file: File): String? = regularBytes(file)?.let { PyText.utf8(it) }

    /** library.read_regular: the bytes of the regular file at [file], never read through a link in its place; null
     * for anything else, or a file that can't be read. */
    private fun regularBytes(file: File): ByteArray? {
        val path = file.toPath()
        return try {
            val attrs = Files.readAttributes(path, BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS)
            if (!attrs.isRegularFile) return null
            Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS).use { it.readBytes() }
        } catch (_: IOException) {
            null
        }
    }

    // --- helpers -----------------------------------------------------------------------------------------------------

    /** _canonical: the key a match of _KEY_HEAD names, as caracole writes it, and whether it named no mode. Groups:
     * root, acc, word, m. */
    private fun canonical(m: MatchResult): Pair<String, Boolean> {
        val root = m.groupValues[1]
        val letter = SOLFEGE[PyUnicode.lower(root)] ?: root
        val tonic = letter + ACCIDENTALS.getValue(m.groups[2]?.value ?: "")
        val word = PyUnicode.lower(m.groups[3]?.value ?: "")
        val mPart = m.groups[4]?.value.orEmpty()
        val minor = mPart.isNotEmpty() || word == "minor" || word == "menor" || word == "min"
        return (if (minor) "$tonic minor" else tonic) to (mPart.isEmpty() && word.isEmpty())
    }

    /** _pitch: the tonic's pitch class (C is 0) and whether the key is minor. */
    private fun pitch(key: String): Pair<Int, Boolean>? {
        val canonical = parseKey(key) ?: return null
        val tonic = canonical.removeSuffix(" minor")
        val letter = LETTERS[tonic.substring(0, 1)] ?: throw NoSuchElementException("no letter ${tonic.take(1)}")
        return Math.floorMod(letter + SHIFT.getValue(tonic.substring(1)), 12) to (tonic != canonical)
    }
}
