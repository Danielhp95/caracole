package io.github.danielhp95.caracole.viewer.harp

import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject

/** harp.HarpChoice: a harp for a song, its position, its key (a pitch class), the position's mode, and how it plays
 * the song's chords. */
data class HarpChoice(val position: Int, val harp: Int, val mode: String?, val fit: Double, val chords: Int,
                      val plays: Int, val substitutes: Int)

/** viewer/harp.py: the Richter harmonica (lane shapes-harp-winds). */
object Harp {
    fun tables(key: Key?, mapped: Map<String, List<Chord?>>, alts: Map<String, List<List<Chord>>>? = null): JsonObject =
        TODO("lane shapes-harp-winds")
    fun holeNote(harp: Int, hole: Int, breath: String, bend: Int = 0, over: Boolean = false): Int? =
        TODO("lane shapes-harp-winds")
    fun holeTables(): JsonArray = TODO("lane shapes-harp-winds")
    fun choices(key: Key, chords: List<Chord?>): List<HarpChoice> = TODO("lane shapes-harp-winds")
    fun headerLine(key: Key, chords: List<Chord?>): String = TODO("lane shapes-harp-winds")
    fun layouts(): JsonArray = TODO("lane shapes-harp-winds")
}
