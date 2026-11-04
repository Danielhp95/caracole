package io.github.danielhp95.caracole.viewer.shapes

import io.github.danielhp95.caracole.viewer.theory.Chord
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject

/** instruments.Instrument: an instrument the viewer draws chords for, field for field. */
data class Instrument(val id: String, val name: String, val kind: String, val tuning: List<Int> = emptyList(),
                      val capo: Boolean = true, val shapes: String = "", val easy: String? = null,
                      val voice: String = "guitar", val sounds: Int = 0, val offset: Int = 0, val about: String = "",
                      val tab: String = "")

/** viewer/instruments.py: the instruments and each one's shapes of a chord (lane shapes-harp-winds). */
object Instruments {
    /** INSTRUMENTS by id, in Python's order (exported as data, never retyped). */
    val INSTRUMENTS: Map<String, Instrument> get() = TODO("lane shapes-harp-winds")

    fun instrument(name: String?): Instrument = TODO("lane shapes-harp-winds")
    fun easyKeys(table: String): JsonObject = TODO("lane shapes-harp-winds")
    fun pianoPositions(chord: Chord): List<List<Int>> = TODO("lane shapes-harp-winds")
    fun chordShapes(inst: Instrument, chord: Chord, shift: Int = 0, given: JsonObject? = null): JsonArray =
        TODO("lane shapes-harp-winds")
    fun pageVoicings(fingerings: Set<String>, chords: List<Chord>): JsonObject = TODO("lane shapes-harp-winds")
}
