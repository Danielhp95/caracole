package io.github.danielhp95.caracole.viewer.shapes

import io.github.danielhp95.caracole.viewer.theory.Chord
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject

/** voicings.Position: a chord's shape as chords-db and the page's data hold it, `[frets, fingers, base fret,
 * barres]`. */
typealias Position = JsonArray

/** viewer/voicings.py: the guitar's chord shapes, chords-db's (voicings.json) and a sheet's own (lane
 * shapes-harp-winds; [TUNING] is the skeleton's, whole, so harmony needs theory alone). */
object Voicings {
    /** Standard tuning, E2 A2 D3 G3 B3 E4, as MIDI notes, low E first (voicings.TUNING). */
    val TUNING: List<Int> = listOf(40, 45, 50, 55, 59, 64)

    fun notesOf(position: Position, tuning: List<Int> = TUNING): List<Int> = TODO("lane shapes-harp-winds")
    fun parseFingering(text: String): Position? = TODO("lane shapes-harp-winds")
    fun chordLegend(line: String): List<Pair<Chord, Position>> = TODO("lane shapes-harp-winds")
    fun parseDefine(value: String): Pair<Chord, Position>? = TODO("lane shapes-harp-winds")
    fun sheetShapes(given: List<Pair<Chord, Position>>): JsonObject = TODO("lane shapes-harp-winds")
    fun shapeKey(chord: Chord): String = TODO("lane shapes-harp-winds")
    fun fretsFromNut(position: Position): List<Int?> = TODO("lane shapes-harp-winds")
    fun voicingKeys(chord: Chord): Triple<String, Boolean, String?> = TODO("lane shapes-harp-winds")
    fun pageVoicings(keys: Set<String>): JsonObject = TODO("lane shapes-harp-winds")
}
