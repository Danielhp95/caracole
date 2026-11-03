package io.github.danielhp95.caracole.e2e

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File

/** A song of the scenario: its names, and its identity key as the computer made it. */
data class Song(val artist: String, val title: String, val key: String) {
    val unit: String get() = "song/$key"
    val tombstone: String get() = "removed/$key"
}

/**
 * What tests/helpers/e2e_library.py says of the scenario's songs, in DIR/scenario.json (its docstring): the
 * computer's 20 songs, the keys of each overrides.toml table the goal's changes fill, an indexed song the library
 * hasn't got (the query that finds it, and its names and identity key as search.py gives them), the tables of the
 * index export, the songs the phone asks for by name (with Fetch now or without), R and C1 (which the phone removes),
 * C1 and C2 (whose [transpose] the computer changes while the phone is away) and the computer's adds meanwhile.
 */
class Scenario private constructor(json: JsonObject) {
    val name: String = json.text("name")
    val songs: List<Song> = json["songs"]!!.jsonArray.map { song(it.jsonObject) }
    val changed: Map<String, List<String>> =
        json["changed"]!!.jsonObject.mapValues { (_, keys) -> keys.jsonArray.map { it.jsonPrimitive.content } }
    val index: JsonObject = json["index"]!!.jsonObject
    val indexSong: Song = song(index)
    val indexTables: List<String> = json["index_tables"]!!.jsonArray.map { it.jsonPrimitive.content }
    val requests: List<Pair<Song, String>> =
        json["requests"]!!.jsonArray.map { it.jsonObject.let { r -> song(r) to r.text("fetch") } }
    val removed: Map<String, Song> = json["removed"]!!.jsonObject.mapValues { song(it.value.jsonObject) }
    val transposed: Map<String, Song> = json["transposed"]!!.jsonObject.mapValues { song(it.value.jsonObject) }
    val adds: List<Song> = json["adds"]!!.jsonArray.map { song(it.jsonObject) }

    val r: Song get() = removed.getValue("R")
    val c1: Song get() = removed.getValue("C1")
    val c2: Song get() = transposed.getValue("C2")

    companion object {
        fun read(dir: File): Scenario = Scenario(Json.parseToJsonElement(File(dir, "scenario.json").readText()).jsonObject)

        private fun song(json: JsonObject) = Song(json.text("artist"), json.text("title"), json.text("key"))
    }
}

fun JsonObject.text(name: String): String =
    (this[name] ?: throw AssertionError("no \"$name\" in $this")).jsonPrimitive.content
