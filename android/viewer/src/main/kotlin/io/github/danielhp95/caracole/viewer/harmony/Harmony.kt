package io.github.danielhp95.caracole.viewer.harmony

import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key

/** harmony.Numeral: a chord's Roman numeral in its key, in parts. */
data class Numeral(val accidental: String, val roman: String, val quality: String, val extension: String,
                   val bass: String?, val of: String?)

/** harmony.Relation: what a chord does in its key. */
data class Relation(val kind: String, val source: String?, val target: String?)

/** harmony.Contained: a progression of CATALOGUE played within a longer section. */
data class Contained(val name: String, val times: Int, val numerals: List<String>, val key: String)

/** harmony.Progression: a section's progression, one cycle, its repeats folded. */
data class Progression(val numerals: List<String>, val repeats: Int, val name: String?, val ending: String?,
                       val variations: Int = 0, val contains: List<Contained> = emptyList())

/** viewer/harmony.py: numerals, relations, families, tones and scales (lane harmony); progressions, their keys and
 * names (lane harmony-progressions). */
object Harmony {
    fun numeral(chord: Chord, key: Key, nextChord: Chord? = null): Numeral = TODO("lane harmony")
    fun relation(chord: Chord, key: Key, nextChord: Chord? = null): Relation = TODO("lane harmony")
    fun family(chord: Chord, key: Key): String? = TODO("lane harmony")
    fun explain(chord: Chord, key: Key, nextChord: Chord? = null): String = TODO("lane harmony")
    fun glossary(chords: List<Chord>, key: Key): List<Triple<String, String, String>> = TODO("lane harmony")
    fun chordTones(chord: Chord, key: Key?): List<Pair<String, String>> = TODO("lane harmony")
    fun soloScale(chord: Chord, key: Key): Pair<String, List<String>> = TODO("lane harmony")
    fun keyScale(key: Key): List<Int> = TODO("lane harmony")
    fun pentatonic(key: Key): List<Int> = TODO("lane harmony")

    fun progressions(sections: List<Pair<String, List<Chord?>>>, key: Key): List<Pair<String, Progression>> =
        TODO("lane harmony-progressions")
    fun progressionKey(numerals: List<String>): String = TODO("lane harmony-progressions")
    fun nameOf(numerals: List<String>): String? = TODO("lane harmony-progressions")
    fun readTyped(text: String): List<String> = TODO("lane harmony-progressions")
    /** harmony.catalogue_keys: each catalogue name's key for searching. */
    fun catalogue(): Map<String, String> = TODO("lane harmony-progressions")
}
