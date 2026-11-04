package io.github.danielhp95.caracole.viewer.harmony

import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import kotlinx.serialization.json.JsonObject

/** viewer/harmony_tables.py: harmony's answers as the tables a viewer's data carries (lane harmony-progressions). */
object HarmonyTables {
    fun tables(chords: List<Chord?>, key: Key?, places: List<Pair<Int, Int>>, mapped: Map<String, List<Chord?>>,
               alts: Map<String, List<List<Chord>>>): JsonObject = TODO("lane harmony-progressions")
}
