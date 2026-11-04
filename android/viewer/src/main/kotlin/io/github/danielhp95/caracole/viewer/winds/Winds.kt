package io.github.danielhp95.caracole.viewer.winds

import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import kotlinx.serialization.json.JsonObject

/** viewer/winds.py: the flute's and the recorder's fingerings (lane shapes-harp-winds). */
object Winds {
    fun tables(chords: List<Chord?>, key: Key?, mapped: Map<String, List<Chord?>>,
               alts: Map<String, List<List<Chord>>>): JsonObject = TODO("lane shapes-harp-winds")
    fun fingeringData(): JsonObject = TODO("lane shapes-harp-winds")
}
