package io.github.danielhp95.caracole.viewer.theory

/**
 * theory.py's chord: [root] and [bass] pitch classes, [quality] a key of QUALITIES (or a chord's normalized suffix
 * outside it, whose intervals are then [tones]), [shown] its suffix as the sheet wrote it ("M7" for a maj7), null for
 * a chord the viewer made up. A value: every field compared (lane theory).
 */
data class Chord(val root: Int, val quality: String, val bass: Int? = null, val shown: String? = null,
                 val tones: Set<Int>? = null)

/** theory.Key: a tonic (pitch class) and a mode, one of MODES: C major is Key(0, "ionian"). */
data class Key(val tonic: Int, val mode: String)

/** viewer/theory.py: chords, keys and modes read, spelt and moved (lane theory). */
object Theory {
    fun parseChord(text: String, strict: Boolean = true): Chord? = TODO("lane theory")
    fun parseKey(text: Any?): Key? = TODO("lane theory")
    fun namedKey(text: Any?, capo: Int, played: List<Chord>): Key? = TODO("lane theory")
    fun bareKey(named: Key, capo: Int, played: List<Chord>): Key = TODO("lane theory")
    fun keyName(k: Key): String = TODO("lane theory")
    fun spelling(k: Key?): List<String> = TODO("lane theory")
    fun mapChord(c: Chord, k: Key, mode: String): Chord = TODO("lane theory")
    fun alternatives(c: Chord, k: Key, limit: Int = 8): List<Chord> = TODO("lane theory")
    fun capoHints(k: Key, limit: Int = 2, capo: Int = 0): List<Pair<Int, Key>> = TODO("lane theory")
    fun estimateKey(chords: List<Chord>): Key? = TODO("lane theory")
    fun sounding(shapes: Key, capo: Int): Key = TODO("lane theory")
    fun shapesKey(named: Key, capo: Int, played: List<Chord>): Key = TODO("lane theory")
}
