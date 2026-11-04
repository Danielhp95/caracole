package io.github.danielhp95.caracole.viewer.version

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.viewer.shapes.Instrument
import io.github.danielhp95.caracole.viewer.shapes.Instruments
import io.github.danielhp95.caracole.viewer.shapes.Voicings
import io.github.danielhp95.caracole.viewer.sheet.Sheets
import io.github.danielhp95.caracole.viewer.sheet.SheetView
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import java.math.BigInteger

/**
 * viewer/version.py's page side, and render.py's `own_version`: a version of a sheet as its viewer keeps it in its
 * address ([fromQuery], [query]), where it plays ([playedKey], [forInstrument]) and its name ([label],
 * [playedLabel]); a songbook's setting ([settingProblem], [inSetting]); and the song's own version kept by its key
 * (`[version]`, Make this my version: [keyVersion], [inKey], [entry], [ownVersion]). Function for function as
 * version.py, its constants and patterns its own (caracole/viewer/version.json, [VersionData]); every answer held by
 * vectors/viewer/version.jsonl (VersionReplay).
 *
 * `apply_version`, which rewrites a sheet's ChordPro for chordpro's PDF of a version, is the computer's alone: the
 * phone prints the viewer itself.
 *
 * Where Kotlin holds less than Python: a chord's index, a shape's number, a swap's root or bass past an Int, in an
 * address, is dropped, as one the viewer can't read is; Python keeps its whole number, which names no chord.
 */
object Versions {
    private val D get() = VersionData.version

    private val DIGITS by lazy { D.pattern("_DIGITS") }
    private val INDEX by lazy { D.pattern("_INDEX") }
    private val NUMBER by lazy { D.pattern("_NUMBER") }
    private val BAD_ESCAPE by lazy { D.pattern("_BAD_ESCAPE") }
    private val TONIC by lazy { D.pattern("_TONIC") }
    private val ESCAPED by lazy { D.pattern("_ESCAPED") }
    private val KEY_NAME by lazy { D.pattern("_KEY_NAME") }
    private val FORM_SAFE: Set<Char> by lazy { D.text("_FORM_SAFE").toSet() }

    /** MODE_NAMES: the modes as the viewer's settings name them (viewer.js MODES). */
    val MODE_NAMES: Map<String, String> by lazy { D.strings("MODE_NAMES") }

    /** _SAID: how a version's name says an instrument but by its name ("low-G ukulele"). */
    private val SAID: Map<String, String> by lazy { D.strings("_SAID") }

    /** CAPO_MAX: the highest fret a setting's capo names (viewer.js CAPO_MAX). */
    val CAPO_MAX: Int by lazy { D.int("CAPO_MAX") }

    /** The fret _played keeps a version's capo to, or the sheet's above it (viewer.js CAPO_MAX, a literal there). */
    private const val CAPO_TOP = 11

    internal val guitar: Instrument get() = Instruments.GUITAR

    internal fun modeName(mode: String): String = MODE_NAMES[mode] ?: throw NoSuchElementException(mode)

    // --- the instruments ---------------------------------------------------------------------------------------------

    /** instrument_of: the instrument an address or a setting names by its id, or null for a name of none. */
    fun instrumentOf(name: String?): Instrument? = if (name == null) null else Instruments.INSTRUMENTS[name]

    /** instrument_ids: every instrument's id, in the viewer's menu's order, the guitar's first. */
    fun instrumentIds(): List<String> = Instruments.INSTRUMENTS.keys.toList()

    /** played_on: the instrument the version is played on, the guitar for none. */
    fun playedOn(v: Version): Instrument = instrumentOf(v.inst) ?: guitar

    /** instrument_words: the instrument as a version's name says it ("piano", "baritone ukulele", "low-G ukulele"). */
    fun instrumentWords(inst: Instrument): String =
        SAID[inst.id] ?: (PyUnicode.lower(Py.slice(inst.name, 0, 1)) + Py.slice(inst.name, 1, null))

    /** _inst_of: an instrument named in an address, as a version keeps it: null for the guitar or a name of none. */
    internal fun instOf(name: String?): String? = name.takeIf { it != guitar.id && instrumentOf(it) != null }

    // --- the address -------------------------------------------------------------------------------------------------

    /** version_from_query: the version an address holds (`t=2&mode=dorian&capo=0&alt=…&at=…`, or the fragment with
     * its "#"), read as the viewer reads its own: the rest left out, `t` rounded to within 11 semitones, a capo below
     * the nut, a mode or a part of `alt` or `at` it can't read dropped; `inst` an instrument's id, the guitar none. */
    fun fromQuery(q: String): Version {
        val params = firsts(stripped(q))
        var t = 0
        params["t"]?.let { t = round(maxOf(-11.0, minOf(11.0, nonZero(number(it))))) }
        var capo: Int? = null
        val capoText = params["capo"]
        if (capoText != null && capoText != "") {
            val fret = number(capoText)
            if (fret != null && fret >= 0) capo = round(minOf(fret, 99.0))
        }
        val mode = params["mode"]
        return Version(t = t, mode = mode.takeIf { it in Theory.MODES }, capo = capo,
                       at = positions(params["at"] ?: ""), alt = swaps(params["alt"] ?: ""),
                       inst = instOf(params["inst"]))
    }

    /** An address's query without the "#" or "?" before it. */
    private fun stripped(q: String): String = if (q.startsWith("#") || q.startsWith("?")) q.substring(1) else q

    /** Each name's first value, as URLSearchParams.get gives it, read as parse_qsl reads them (blank ones kept). */
    private fun firsts(q: String): Map<String, String> = PyUrl.parseQs(q, keepBlank = true).mapValues { it.value.first() }

    /** _number: `text` as JavaScript's Number() reads it (blank is 0), or null where that is NaN. */
    private fun number(text: String): Double? {
        val s = Py.strip(text)
        if (s.isEmpty()) return 0.0
        return if (PyRe.fullmatch(NUMBER, s) != null) s.toDouble() else null
    }

    /** `x or 0.0`: a number that is none, or zero (-0.0 too), is 0.0. */
    private fun nonZero(x: Double?): Double = if (x == null || x == 0.0) 0.0 else x

    /** _round: Math.round, half up. */
    private fun round(x: Double): Int = Math.floor(x + 0.5).toInt()

    private fun swaps(text: String): Map<String, Map<Int, Swap>> {
        val out = LinkedHashMap<String, LinkedHashMap<Int, Swap>>()
        for (part in text.split(",")) {
            val pieces = part.split(".") + List(5) { "" }
            val (mode, i, root, suffix, bass) = pieces
            if (mode !in Theory.MODES || PyRe.fullmatch(INDEX, i) == null || root.isEmpty() ||
                PyRe.fullmatch(DIGITS, root) == null || PyRe.fullmatch(DIGITS, bass) == null) continue
            if (PyRe.search(BAD_ESCAPE, suffix) != null) continue  // decodeURIComponent throws
            val written = try {
                PyUrl.unquote(suffix, strict = true)
            } catch (e: PyUrl.Invalid) {
                continue
            }
            val index = i.toIntOrNull() ?: continue
            val r = root.toIntOrNull() ?: continue
            val b = if (bass.isEmpty()) null else bass.toIntOrNull() ?: continue
            out.getOrPut(mode) { LinkedHashMap() }[index] = Swap(r, written, b)
        }
        return out
    }

    private fun positions(text: String): Map<Int, Int> {
        val out = LinkedHashMap<Int, Int>()
        for (part in text.split(",")) {
            val pieces = part.split(".") + listOf("", "")
            val (i, n) = pieces
            if (PyRe.fullmatch(INDEX, i) != null && n.isNotEmpty() && PyRe.fullmatch(DIGITS, n) != null &&
                BigInteger(n) > BigInteger.ZERO) {
                val index = i.toIntOrNull() ?: continue
                out[index] = n.toIntOrNull() ?: continue
            }
        }
        return out
    }

    /** version_query: the version as the viewer's save() writes it in its address, in its order (`t`, `mode`,
     * `capo`, `alt`, `at`, `inst`), each left out where it says nothing; "" for the sheet as written on the guitar. */
    fun query(v: Version): String {
        val params = ArrayList<Pair<String, String>>()
        if (v.t != 0) params += "t" to v.t.toString()
        if (v.mode != null) params += "mode" to v.mode
        if (v.capo != null) params += "capo" to v.capo.toString()
        val swaps = v.alt.flatMap { (mode, chosen) ->
            chosen.entries.sortedBy { it.key }.map { (i, s) -> "$mode.$i.${s.root}.${component(s.suffix)}.${s.bass ?: ""}" }
        }.joinToString(",")
        if (swaps.isNotEmpty()) params += "alt" to swaps
        if (v.at.isNotEmpty()) params += "at" to v.at.entries.sortedBy { it.key }.joinToString(",") { "${it.key}.${it.value}" }
        if (v.inst != null) params += "inst" to v.inst
        return params.joinToString("&") { (name, value) -> "${form(name)}=${form(value)}" }
    }

    /** _component: encodeURIComponent, then "." as "%2E", as the viewer writes a swap's suffix. */
    private fun component(text: String): String = PyUrl.quote(text, safe = "!~*'()").replace(".", "%2E")

    /** _form: [text] as URLSearchParams writes it. */
    private fun form(text: String): String = buildString {
        for (byte in text.toByteArray(Charsets.UTF_8)) {
            val b = byte.toInt() and 0xFF
            when {
                b == 0x20 -> append('+')
                b < 0x80 && b.toChar() in FORM_SAFE -> append(b.toChar())
                else -> append("%%%02X".format(b))
            }
        }
    }

    // --- where the song is played ------------------------------------------------------------------------------------

    /** _Played: the mode the chords are in (null without a key), whether that is the sheet's, how many semitones
     * their names move (the transposition less the capo's move), and the fret the capo is on. */
    internal class Played(val mode: String?, val asWritten: Boolean, val shift: Int, val capo: Int)

    internal fun played(v: Version, key: Key?, capoSheet: Int?): Played {
        val sheetCapo = capoSheet ?: 0
        val capo = if (v.capo == null) sheetCapo else maxOf(0, minOf(maxOf(CAPO_TOP, sheetCapo), v.capo))
        val mode = if (key == null) null else if (v.mode in Theory.MODES) v.mode else key.mode
        return Played(mode, key == null || mode == key.mode, v.t - (capo - sheetCapo), capo)
    }

    /** played_key: the key of the shapes the version plays (null for a sheet with no key) and its capo; on an
     * instrument with no capo, the key it sounds in and no capo. */
    fun playedKey(v: Version, key: Key?, capoSheet: Int?): Pair<Key?, Int> {
        val played = played(forInstrument(v, playedOn(v)), key, capoSheet)
        if (key == null || played.mode == null) return null to played.capo
        return Key(Math.floorMod(key.tonic + played.shift, 12), played.mode) to played.capo
    }

    /** for_instrument: the version as [inst] plays it: as it is on one that takes a capo; with no capo on one that
     * takes none, its transposition kept, so its chords are named as they sound. */
    fun forInstrument(v: Version, inst: Instrument): Version = if (inst.capo) v else v.copy(capo = 0)

    /** version_label: the version in words, the key of the shapes it plays in the viewer's names of the modes and
     * its capo ("G Dorian, capo 0"); a sheet with no key says how far it moved ("Transposed +2, capo 0", "As written,
     * capo 3"); another instrument after it, and on one with no capo the key it sounds in ("A Major, piano"). */
    fun label(v: Version, key: Key?, capoSheet: Int?): String = label(v, key, capoSheet, noCapo = true)

    /** played_label: [label]'s words, with nothing of a capo it plays without ("G Dorian", "Transposed +2"), as a
     * songbook's set list says it. */
    fun playedLabel(v: Version, key: Key?, capoSheet: Int?): String = label(v, key, capoSheet, noCapo = false)

    private fun label(v: Version, key: Key?, capoSheet: Int?, noCapo: Boolean): String {
        val inst = playedOn(v)
        val played = played(forInstrument(v, inst), key, capoSheet)
        var words = if (key == null || played.mode == null) {
            val moved = if (!inst.capo) played.shift else v.t  // as it sounds: the capo folded in
            if (moved != 0) "Transposed ${if (moved > 0) "+" else ""}$moved" else "As written"
        } else {
            val shapes = Key(Math.floorMod(key.tonic + played.shift, 12), played.mode)
            "${Theory.spelling(shapes)[shapes.tonic]} ${modeName(shapes.mode)}"
        }
        if (inst.capo && (played.capo != 0 || noCapo)) words = "$words, capo ${played.capo}"
        return if (inst.id == guitar.id) words else "$words, ${instrumentWords(inst)}"
    }

    // --- where a setting plays it: by the key of its shapes ----------------------------------------------------------

    /** Setting.__bool__: whether the setting says anything. */
    fun given(setting: Setting?): Boolean =
        setting != null && (setting.key != null || setting.mode != null || setting.capo != null || setting.instrument != null)

    /** places: whether the setting names a key or a mode, which only a sheet with a key can take. */
    fun places(setting: Setting?): Boolean = setting != null && (setting.key != null || setting.mode != null)

    /** setting_problem: why these parts make no Setting, in Python's words, or null when they make one. Each part is
     * as a form or a file gives it: a String, an Int, a Long or a BigInteger, a Boolean, a Double, a JsonElement
     * (JsonNull is none), a List or a Map of those, or null; a message quotes it as Python's `{value!r}` does. */
    fun settingProblem(key: Any? = null, mode: Any? = null, capo: Any? = null, instrument: Any? = null): String? {
        val k = plain(key)
        val m = plain(mode)
        val c = plain(capo)
        val i = plain(instrument)
        if (k != null && !(k is String && PyRe.fullmatch(TONIC, k) != null)) {
            return "key must be a tonic such as \"G\", \"F#\" or \"Bb\", got ${repr(k)}"
        }
        if (m != null && !(m is String && m in Theory.MODES)) {
            return "mode must be one of ${Theory.MODES.joinToString(", ")}, got ${repr(m)}"
        }
        if (c != null && !(c is BigInteger && c >= BigInteger.ZERO && c <= BigInteger.valueOf(CAPO_MAX.toLong()))) {
            return "capo must be a fret from 0 to $CAPO_MAX, got ${repr(c)}"
        }
        if (i != null && !(i is String && instrumentOf(i) != null)) {
            return "instrument must be one of ${instrumentIds().joinToString(", ")}, got ${repr(i)}"
        }
        return null
    }

    /** A part as Python holds it: null for none, a String, a BigInteger for any int, a Boolean, a Double, a List, a
     * Map; anything else as it is. */
    private fun plain(value: Any?): Any? = when (value) {
        null, JsonNull -> null
        is JsonPrimitive -> when {
            value.isString -> value.content
            value.content == "true" -> true
            value.content == "false" -> false
            isInteger(value.content) -> BigInteger(value.content)
            else -> value.doubleOrNull ?: value.content
        }
        is JsonArray -> value.map(::plain)
        is JsonObject -> value.mapValues { plain(it.value) }
        is Int -> BigInteger.valueOf(value.toLong())
        is Long -> BigInteger.valueOf(value)
        is Short -> BigInteger.valueOf(value.toLong())
        is Byte -> BigInteger.valueOf(value.toLong())
        is Float -> value.toDouble()
        is List<*> -> value.map(::plain)
        is Map<*, *> -> value.entries.associate { (k, v) -> plain(k) to plain(v) }
        else -> value
    }

    private fun isInteger(literal: String): Boolean =
        literal.removePrefix("-").let { d -> d.isNotEmpty() && d.all { it in '0'..'9' } }

    /** Python's repr of a part [plain] made. */
    private fun repr(value: Any?): String = when (value) {
        null -> "None"
        is String -> PyStr.repr(value)
        is Boolean -> if (value) "True" else "False"
        is BigInteger -> value.toString()
        is Double -> when {
            value.isNaN() -> "nan"
            value.isInfinite() -> if (value > 0) "inf" else "-inf"
            else -> PyJson.floatText(value)
        }
        is List<*> -> value.joinToString(", ", "[", "]") { repr(it) }
        is Map<*, *> -> value.entries.joinToString(", ", "{", "}") { (k, v) -> "${repr(k)}: ${repr(v)}" }
        is JsonElement -> value.toString()
        else -> value.toString()
    }

    /**
     * in_setting: the version a setting plays a song in: the key of the shapes played, the mode and the capo, and for
     * what it leaves out the song's own version's ([own]). [shapes] and [capoSheet] are the sheet's, as its viewer
     * reads them. A setting with a key or a mode is the sheet as written for a sheet with no key; shapes chosen
     * (`at`) go when the setting plays other chords, or on another instrument. The setting's instrument is the
     * version's ("guitar" the guitar's), else the own version's; on one with no capo, the key it names is the key the
     * song sounds in, placed with no capo.
     */
    fun inSetting(own: Version, setting: Setting?, shapes: Key?, capoSheet: Int?): Version {
        if (!given(setting)) return own
        setting!!
        val inst = if (setting.instrument == null) own.inst else instOf(setting.instrument)
        if (places(setting) && shapes == null) return Version(inst = inst)
        val tonic = setting.key?.let { Theory.notePc(Py.slice(it, 0, 1), Py.slice(it, 1, null)) }
        val capo = if (tonic != null && !(instrumentOf(inst) ?: guitar).capo) 0 else setting.capo
        val placed = placed(own, tonic, setting.mode, capo, shapes, capoSheet)
        return if (inst == placed.inst) placed else placed.copy(inst = inst, at = emptyMap())
    }

    /** _placed: the setting's rule, for the tonic of the shapes played (a pitch class), a mode and a capo, each null
     * for the own version's. */
    private fun placed(own: Version, tonic: Int?, mode: String?, capo: Int?, shapes: Key?, capoSheet: Int?): Version {
        val m = mode ?: own.mode
        val c = capo ?: own.capo
        var t = own.t
        if (tonic != null) {
            val unmoved = playedKey(Version(mode = m, capo = c), shapes, capoSheet).first
                ?: throw IllegalStateException("no key to place the setting by")  // Python's AttributeError on None
            t = Math.floorMod(tonic - unmoved.tonic + 5, 12) - 5
        }
        if (t == own.t && m == own.mode && c == own.capo) return own
        return own.copy(t = t, mode = m, capo = c, at = emptyMap())
    }

    // --- the sheet's chords in a version -----------------------------------------------------------------------------

    /** _chords: each chord of the sheet as the version plays it (the chord in the mode, or one the viewer offers
     * instead there), and whether it is the chord as the sheet writes it; null for one caracole can't read. */
    private fun chords(names: List<String>, v: Version, key: Key?, played: Played): List<Pair<Chord?, Boolean>> {
        val swaps = if (key != null && played.mode != null) v.alt[played.mode] ?: emptyMap() else emptyMap()
        return names.mapIndexed { i, name ->
            val chord = Theory.parseChord(name, strict = false)
            if (chord == null || key == null || played.mode == null) return@mapIndexed chord to true
            val mapped = Theory.mapChord(chord, key, played.mode)
            val swap = swaps[i]
            val instead = if (swap == null) null else Theory.alternatives(mapped, Key(key.tonic, played.mode))
                .firstOrNull { Swap(it.root, it.suffix, it.bass) == swap }
            when {
                instead != null -> instead to false
                played.asWritten -> chord to true
                else -> mapped to false
            }
        }
    }

    /** _names: each chord of the sheet as the version names it: as written when it is the chord as written, unmoved,
     * or one caracole can't read; else its notes as the mode and the key moved there spell them, its suffix as
     * written. */
    private fun names(names: List<String>, chords: List<Pair<Chord?, Boolean>>, key: Key?, played: Played): List<String> {
        val spelled = Theory.spelling(if (key == null) null else Key(Math.floorMod(key.tonic + played.shift, 12), played.mode!!))
        return names.indices.map { i ->
            val (chord, asWritten) = chords[i]
            if (chord == null || (asWritten && played.shift == 0)) names[i]
            else {
                val bass = if (chord.bass == null) "" else "/" + spelled[Math.floorMod(chord.bass + played.shift, 12)]
                spelled[Math.floorMod(chord.root + played.shift, 12)] + chord.suffix + bass
            }
        }
    }

    /** _shapes: the shapes the viewer shows [chord] moved [shift] semitones on [inst] (instruments.chord_shapes). */
    private fun shapes(chord: Chord, shift: Int, given: JsonObject, inst: Instrument): JsonArray =
        Instruments.chordShapes(inst, chord, shift, given)

    // --- a version kept by its key ([version], "Make this my version") -----------------------------------------------

    /** _escape: what would split a chord's name in an entry, and whitespace, as its UTF-8 bytes' %XX. */
    internal fun escape(name: String): String = PyRe.sub(ESCAPED, name) { m ->
        m.value.toByteArray(Charsets.UTF_8).joinToString("") { "%%%02X".format(it.toInt() and 0xFF) }
    }

    /** _frets_text: "x-x-5-7-8-6". */
    internal fun fretsText(frets: Frets): String = frets.joinToString("-") { it?.toString() ?: "x" }

    /** _frets: a shape's frets as an entry writes them, a fret a string of [strings] from the nut (two digits at
     * most) and at least one string played; null for text that is none. */
    private fun frets(text: String, strings: Int): Frets? {
        val parts = text.split("-")
        if (parts.size != strings || !parts.all { p -> p == "x" || (p.isNotEmpty() && p.length <= 2 && p.all { it in '0'..'9' }) }) {
            return null
        }
        val frets = parts.map { if (it == "x") null else it.toInt() }
        return if (frets.all { it == null }) null else frets
    }

    /** _text: a part of an entry, its escapes undone; as written where one doesn't decode. */
    private fun text(value: String): String = try {
        PyUrl.unquote(value, strict = true)
    } catch (e: PyUrl.Invalid) {
        value
    }

    /** _chord_name: a chord's name in a kept version's `alt` or `at`, its escapes undone; null for one whose escapes
     * don't decode or that names no chord caracole can read. */
    private fun chordName(text: String): String? {
        if (PyRe.search(BAD_ESCAPE, text) != null) return null
        val name = try {
            Py.strip(PyUrl.unquote(text, strict = true))
        } catch (e: PyUrl.Invalid) {
            return null
        }
        return name.takeIf { Theory.parseChord(it, strict = false) != null }
    }

    /**
     * key_version: the version a `[version]` entry keeps by its key, or null for one that names no `key` (a move
     * from the sheet, `t=2&mode=dorian`). A "#" or a "?" before it is dropped, and of a name given twice the first
     * counts. An IllegalArgumentException, saying why in Python's words (its ValueError), for a key that is none as a
     * sheet names one, a mode, a capo or an instrument that can't be one, or a key beside a `t`. A swap or a shape it
     * can't read is dropped, and so is a shape on an instrument with no strings.
     */
    fun keyVersion(text: String): KeyVersion? {
        val params = LinkedHashMap<String, String>()
        for (part in stripped(text).split("&")) {
            if (part.isEmpty()) continue
            params.putIfAbsent(part.substringBefore('='), if ('=' in part) part.substringAfter('=') else "")
        }
        val keyText = params["key"] ?: return null
        if ("t" in params) {
            throw IllegalArgumentException(
                "a key or a t, not both: key=G is the key the song plays in, t=2 a move from its sheet")
        }
        val named = text(keyText)
        val key = (if (PyRe.fullmatch(KEY_NAME, named) != null) Theory.parseKey(named) else null)
            ?: throw IllegalArgumentException(
                "key must be a key as a sheet names it, such as \"G\", \"F#m\" or \"Bb dorian\", got ${PyStr.repr(named)}")
        val mode = text(params["mode"] ?: "").ifEmpty { null }
        val capoText = text(params["capo"] ?: "")
        val capo: Any? = if (capoText.isNotEmpty() && capoText.all { it in '0'..'9' }) BigInteger(capoText)
                         else capoText.ifEmpty { null }
        val instName = text(params["inst"] ?: "").ifEmpty { null }
        settingProblem(null, mode, capo, instName)?.let { throw IllegalArgumentException(it) }
        val inst = instrumentOf(instName) ?: guitar
        val swaps = LinkedHashMap<String, String>()
        for (part in (params["alt"] ?: "").split(",")) {
            val names = part.split(".").map(::chordName)
            if (names.size == 2 && names[0] != null && names[1] != null) swaps.putIfAbsent(names[0]!!, names[1]!!)
        }
        val shapes = LinkedHashMap<String, Frets>()
        for (part in (params["at"] ?: "").split(",")) {
            val pieces = part.split(".")
            if (inst.kind != "strings" || pieces.size != 2) continue
            val name = chordName(pieces[0]) ?: continue
            val frets = frets(pieces[1], inst.tuning.size) ?: continue
            shapes.putIfAbsent(name, frets)
        }
        return KeyVersion(key, mode, (capo as BigInteger?)?.toInt(), swaps.toList(), shapes.toList(), instOf(instName))
    }

    /** _sound: a chord as it sounds, moved [shift] semitones: its root, its intervals and its bass. */
    private fun sound(chord: Chord, shift: Int = 0): Triple<Int, Set<Int>, Int?> =
        Triple(Math.floorMod(chord.root + shift, 12), chord.intervals, chord.bass?.let { Math.floorMod(it + shift, 12) })

    private fun sounds(names: List<String>): List<Triple<Int, Set<Int>, Int?>> =
        names.map { sound(Theory.parseChord(it, strict = false) ?: throw NoSuchElementException("no chord $it")) }

    /** _relative: the degree [key]'s tonic is in the key of its notes in [mode]. */
    private fun relative(key: Key, mode: String): Int {
        val notes = Theory.scale(key)
        return Theory.SCALES.getValue(mode).withIndex()
            .first { (_, interval) -> Theory.scale(Key(Math.floorMod(key.tonic - interval, 12), mode)) == notes }.index
    }

    /** _fitting: how many of the chords named have every note, their bass too, in [key]. */
    private fun fitting(key: Key, names: List<String>): Int {
        val notes = Theory.scale(key)
        return names.count { name ->
            val chord = Theory.parseChord(name, strict = false)
            chord != null && chord.intervals.all { Math.floorMod(chord.root + it, 12) in notes } &&
                (chord.bass == null || chord.bass in notes)
        }
    }

    /** _from_degree: the mode [mode]'s notes make from its [degree]. */
    private fun fromDegree(mode: String, degree: Int): String {
        val steps = Theory.SCALES.getValue(mode)
        val intervals = (0 until 7).map { n -> Math.floorMod(steps[(n + degree) % 7] - steps[degree], 12) }
        return Theory.MODES.first { Theory.SCALES.getValue(it) == intervals }
    }

    /**
     * in_key: where the version kept by its key plays the ChordPro sheet [cho] ([key] and [capoSheet] the sheet's, as
     * its viewer reads them), by the setting's rule, its chords read in the notes of the sheet's key in the kept
     * key's mode (or from the sheet's own tonic, where its chords fit its tonic's key in that mode better), with each
     * chord its `alt` names played instead where the viewer offers it there, and each chord its `at` names given the
     * shape of those frets where its viewer lists one; on the version's instrument. A sheet with no key plays it as
     * written.
     */
    fun inKey(kept: KeyVersion, cho: String, key: Key?, capoSheet: Int?): Version {
        val inst = instrumentOf(kept.inst) ?: guitar
        if (key == null) return Version(inst = kept.inst)
        val sheet = Sheets.parse(cho)
        val parallel = Key(key.tonic, kept.key.mode)
        val placed = if (parallel != key && fitting(parallel, sheet.chords) > fitting(key, sheet.chords)) {
            val chosen = if (kept.mode == key.mode) null else kept.mode
            placed(Version(), kept.key.tonic, chosen, kept.capo, key, capoSheet)
        } else {
            val degree = relative(key, kept.key.mode)  // where the sheet's tonic is in the kept key's reading
            val mode = kept.mode?.takeIf { it.isNotEmpty() } ?: kept.key.mode
            val playedMode = fromDegree(mode, degree)
            val tonic = Math.floorMod(kept.key.tonic + Theory.SCALES.getValue(mode)[degree], 12)
            placed(Version(), tonic, if (playedMode == key.mode) null else playedMode, kept.capo, key, capoSheet)
        }
        val played = played(placed, key, capoSheet)
        val instead = LinkedHashMap<Triple<Int, Set<Int>, Int?>, Triple<Int, Set<Int>, Int?>>()
        sounds(kept.alt.map { it.first }).zip(sounds(kept.alt.map { it.second })).forEach { (a, b) -> instead[a] = b }
        val swaps = LinkedHashMap<Int, Swap>()
        for ((i, pair) in chords(sheet.chords, placed, key, played).withIndex()) {
            val chord = pair.first ?: continue
            val wanted = instead[sound(chord, played.shift)] ?: continue
            val written = Theory.parseChord(sheet.chords[i], strict = false)!!
            val offered = Theory.alternatives(Theory.mapChord(written, key, played.mode!!), Key(key.tonic, played.mode))
            val found = offered.firstOrNull { sound(it, played.shift) == wanted } ?: continue
            swaps[i] = Swap(found.root, found.suffix, found.bass)
        }
        val version = if (swaps.isNotEmpty()) placed.copy(alt = mapOf(played.mode!! to swaps), inst = kept.inst)
                      else placed.copy(inst = kept.inst)
        val chosen = LinkedHashMap<Triple<Int, Set<Int>, Int?>, Frets>()
        sounds(kept.at.map { it.first }).zip(kept.at.map { it.second }).forEach { (s, f) -> chosen[s] = f }
        val given = SheetView.shapesOf(sheet)
        val positions = LinkedHashMap<Int, Int>()
        for ((i, pair) in chords(sheet.chords, version, key, played).withIndex()) {
            val chord = pair.first ?: continue
            val frets = chosen[sound(chord, played.shift)] ?: continue
            val listed = if (inst.kind == "strings") shapes(chord, played.shift, given, inst) else JsonArray(emptyList())
            val n = listed.indexOfFirst { Voicings.fretsFromNut(it as JsonArray) == frets }
            if (n > 0) positions[i] = n  // the first is the one played anyway
        }
        return if (positions.isNotEmpty()) version.copy(at = positions) else version
    }

    /**
     * version_entry: the `[version]` entry Make this my version writes for the version [v] of the ChordPro sheet
     * [cho] ([key] and [capoSheet] as for [inKey]): [v] kept by its key (KeyVersion.query), the key of the shapes it
     * plays in the mode the sheet's chords are read in, the mode it plays them in where that is another, and its capo
     * (none past CAPO_MAX), then the chords it plays instead and the shapes it chose, each chord by its name there, in
     * its mode alone; then its instrument. Null for a sheet with no key.
     */
    fun entry(v: Version, cho: String, key: Key?, capoSheet: Int?): String? {
        val played = played(v, key, capoSheet)
        if (key == null || played.mode == null) return null
        val inst = playedOn(v)
        val shapes = Key(Math.floorMod(key.tonic + played.shift, 12), key.mode)
        val capo = if (played.capo <= CAPO_MAX) played.capo else null
        val sheet = Sheets.parse(cho)
        val plain = chords(sheet.chords, v.copy(alt = emptyMap()), key, played)
        val chords = chords(sheet.chords, v, key, played)
        val before = names(sheet.chords, plain, key, played)
        val names = names(sheet.chords, chords, key, played)
        val swaps = LinkedHashMap<String, String>()
        for (i in chords.indices) {
            val now = chords[i].first
            if (now != null && now != plain[i].first) swaps.putIfAbsent(before[i], names[i])
        }
        val given = SheetView.shapesOf(sheet)
        val shown = LinkedHashMap<String, Frets>()
        val seen = HashSet<String>()
        for ((i, pair) in chords.withIndex()) {  // a shape a name, its first place's
            val chord = pair.first
            if (chord == null || names[i] in seen) continue
            seen += names[i]
            val n = v.at[i] ?: 0
            val listed = if (inst.kind == "strings") shapes(chord, played.shift, given, inst) else JsonArray(emptyList())
            if (n > 0 && n < listed.size) shown[names[i]] = Voicings.fretsFromNut(listed[n] as JsonArray)
        }
        return KeyVersion(shapes, if (played.asWritten) null else played.mode, capo, swaps.toList(), shown.toList(),
                          v.inst).query()
    }

    // --- render.own_version ------------------------------------------------------------------------------------------

    /**
     * render.own_version: the song's own version on its sheet [cho] ([key], the sheet's, and [keySource] where it
     * came from), where its PDF, its viewer and its songbooks start: its `[version]`, else its `[transpose]` alone,
     * else the sheet as written. One kept by its key plays in that key on whatever sheet the song has (as written on
     * a sheet with no key, or one the viewer's code can't read); one without a key is a move from the sheet, at the
     * song's `[transpose]` when it names no `t`. An entry whose key can't be read raises, as key_version does.
     */
    fun ownVersion(overrides: Overrides, song: SongRow, cho: String, key: String?, keySource: String? = null): Version {
        val transpose = overrides.transpose[song.key] ?: 0
        val query = overrides.version[song.key] ?: return Version(t = transpose)
        val kept = keyVersion(query)
        if (kept == null) {
            val version = fromQuery(query)
            return if ("t" in PyUrl.parseQs(stripped(query), keepBlank = true)) version else version.copy(t = transpose)
        }
        return try {
            inKey(kept, cho, SheetView.viewerKey(cho, key, keySource), Sheets.parse(cho).capo)
        } catch (e: Exception) {  // a sheet the viewer's code can't read (a bug) never stops the song's other files
            Version()
        }
    }
}
