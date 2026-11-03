package io.github.danielhp95.caracole.core.keys

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.boolean

/**
 * What normalize.py and library.py state as data, as tests/test_conformance_keys.py wrote it from the modules
 * themselves into caracole/keys/ on the classpath (that file's docstring is the format's): `tables.json`, every
 * constant under its own name, and `t2s.txt`, Traditional characters to Simplified ones. Read once, on first use.
 */
internal object KeyTables {
    private val json: JsonObject by lazy { Json.parseToJsonElement(text("tables.json")).jsonObject }

    val keyVersion: Int by lazy { json.getValue("KEY_VERSION").jsonPrimitive.int }
    val maxNameBytes: Int by lazy { json.getValue("MAX_NAME_BYTES").jsonPrimitive.int }

    /** _TRANSLIT: a code point and what it becomes. */
    val translit: Map<Int, String> by lazy {
        json.getValue("_TRANSLIT").jsonObject.entries.associate { (k, v) -> k.codePointAt(0) to v.jsonPrimitive.content }
    }
    val apostrophes: Set<Int> by lazy { codePoints(json.getValue("_APOSTROPHES").jsonPrimitive.content).toSet() }
    val cjk: Ranges by lazy { Ranges(json.getValue("_CJK").jsonArray) }
    val han: Ranges by lazy { Ranges(json.getValue("_HAN").jsonArray) }

    val variantTokens: List<String> by lazy { strings("VARIANT_TOKENS") }
    val genericWords: Set<String> by lazy { strings("GENERIC_WORDS").toSet() }
    val placeholderArtists: Set<String> by lazy { strings("_PLACEHOLDER_ARTISTS").toSet() }
    val artistDropped: Set<String> by lazy { strings("_ARTIST_DROPPED").toSet() }
    val titleDropped: Set<String> by lazy { strings("_TITLE_DROPPED").toSet() }
    val spanishArticles: Set<String> by lazy { strings("_SPANISH_ARTICLES").toSet() }
    val numberWords: Map<String, String> by lazy { map("_NUMBER_WORDS") }

    /** A Hangul syllable's jamo, each the ways it is romanized: an initial's, a medial's, a final's. */
    val hangulInitials: List<List<String>> by lazy { strings("_HANGUL_INITIALS").map { it.split(" ") } }
    val hangulMedials: List<List<String>> by lazy { strings("_HANGUL_MEDIALS").map { it.split(" ") } }
    val hangulFinals: List<List<String>> by lazy { strings("_HANGUL_FINALS").map { it.split(" ") } }

    /** _KANA, by a hiragana's code point: its spellings. */
    val kana: Map<Int, List<String>> by lazy { map("_KANA").entries.associate { (k, v) -> k.codePointAt(0) to v.split(" ") } }
    val smallY: Map<Int, String> by lazy { map("_SMALL_Y").entries.associate { (k, v) -> k.codePointAt(0) to v } }
    val smallVowels: Map<Int, String> by lazy { map("_SMALL_VOWELS").entries.associate { (k, v) -> k.codePointAt(0) to v } }
    val geminate: Set<String> by lazy { strings("_GEMINATE").toSet() }
    val long: Set<String> by lazy { strings("_LONG").toSet() }

    /** A pattern of normalize.py (or library.py's _RESERVED) by its name, compiled as Python reads it. */
    fun pattern(name: String): KeyPattern {
        val spec = json.getValue("patterns").jsonObject.getValue(name).jsonObject
        return KeyPattern(spec.getValue("pattern").jsonPrimitive.content, spec.getValue("ignorecase").jsonPrimitive.boolean)
    }

    /** _t2s_table(): a Traditional character's code point and its Simplified one's. */
    val t2s: Map<Int, Int> by lazy {
        val out = HashMap<Int, Int>(4096)
        for (line in text("t2s.txt").split('\n')) {
            if (line.isEmpty()) continue
            val space = line.indexOf(' ')
            out[line.substring(0, space).toInt(16)] = line.substring(space + 1).toInt(16)
        }
        out
    }

    private fun strings(name: String): List<String> = json.getValue(name).jsonArray.map { it.jsonPrimitive.content }

    private fun map(name: String): Map<String, String> =
        json.getValue(name).jsonObject.entries.associate { (k, v) -> k to v.jsonPrimitive.content }

    private fun codePoints(s: String): List<Int> {
        val out = ArrayList<Int>()
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            out += cp
            i += Character.charCount(cp)
        }
        return out
    }

    internal fun text(name: String): String {
        val path = "caracole/keys/$name"
        val stream = KeyTables::class.java.classLoader?.getResourceAsStream(path)
            ?: KeyTables::class.java.getResourceAsStream("/$path")
            ?: throw IllegalStateException("the resource $path is missing")
        return stream.use { it.readBytes().toString(Charsets.UTF_8) }
    }

    /** Code point ranges, inclusive, in order: whether one holds a code point, by a binary search. */
    class Ranges(json: JsonArray) {
        private val first = IntArray(json.size) { json[it].jsonArray[0].jsonPrimitive.int }
        private val last = IntArray(json.size) { json[it].jsonArray[1].jsonPrimitive.int }

        operator fun contains(cp: Int): Boolean {
            var lo = 0
            var hi = first.size - 1
            while (lo <= hi) {
                val mid = (lo + hi) ushr 1
                when {
                    cp < first[mid] -> hi = mid - 1
                    cp > last[mid] -> lo = mid + 1
                    else -> return true
                }
            }
            return false
        }
    }
}
