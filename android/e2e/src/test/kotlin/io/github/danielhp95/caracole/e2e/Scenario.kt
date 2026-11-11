package io.github.danielhp95.caracole.e2e

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
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
    val lookups: Lookups = Lookups(json["lookups"]!!.jsonObject)

    /** What the computer's caracole.toml says once the phone has looked songs up (e2e_library.SETTINGS_SAID). */
    val settings: JsonObject = json["settings"]!!.jsonObject

    val r: Song get() = removed.getValue("R")
    val c1: Song get() = removed.getValue("C1")
    val c2: Song get() = transposed.getValue("C2")

    companion object {
        fun read(dir: File): Scenario = Scenario(Json.parseToJsonElement(File(dir, "scenario.json").readText()).jsonObject)

        private fun song(json: JsonObject) = Song(json.text("artist"), json.text("title"), json.text("key"))
    }
}

/**
 * The fake sites' scenario (tests/helpers/fake_sites.py's `document`, as GET /scenario.json gives it, and as
 * scenario.json's `lookups` holds it over the computer's index): each song by its part in the lookups ([song]), and the
 * lookup limits of each provider ([requests], [perHour]); [provider] names the site a host is.
 */
class Lookups(json: JsonObject) {
    private val songs: Map<String, LookupSong> = json["songs"]!!.jsonObject.mapValues { (_, v) -> LookupSong(v.jsonObject) }
    private val limits: Map<String, JsonObject> = json["limits"]!!.jsonObject.mapValues { it.value.jsonObject }
    private val hosts: Map<String, String> = json["hosts"]!!.jsonObject.mapValues { it.value.jsonPrimitive.content }

    fun song(role: String): LookupSong = songs[role] ?: throw AssertionError("no song of part \"$role\" in $songs")

    /** A provider's lookup_requests: what one lookup may send it. */
    fun requests(provider: String): Int = limits.getValue(provider).text("lookup_requests").toInt()

    /** A provider's lookup_per_hour: what every lookup of an hour may send it together. */
    fun perHour(provider: String): Int = limits.getValue(provider).text("lookup_per_hour").toInt()

    fun provider(host: String): String? = hosts[host]
}

/** A song of the fake sites' scenario: its names and identity key, its tab pages (and where a page redirects that
 * robots.txt closes, [closed]), its artist's page, its harmonica tab's page on harptabs.com ([harp], or null), and,
 * for a song of UG's index, what a search types for it and the row it finds ([search]: `ug`, the names and their
 * key). */
class LookupSong(json: JsonObject) {
    val song: Song = Song(json.text("artist"), json.text("title"), json.text("key"))
    val tabs: List<String> = json["tabs"]!!.jsonArray.map { it.jsonPrimitive.content }
    val closed: List<String> = json["closed"]?.jsonArray?.map { it.jsonPrimitive.content }.orEmpty()
    val artistPage: String = json.text("artist_page")
    val harp: String? = (json["harp"] as? JsonPrimitive)?.takeIf { it.isString }?.content
    val search: JsonObject? = json["search"]?.jsonObject

    /** The song as the search's row names it, and its key: what Get it adds. */
    val found: Song get() = search!!.let { Song(it.text("artist"), it.text("title"), it.text("key")) }
}

fun JsonObject.text(name: String): String =
    (this[name] ?: throw AssertionError("no \"$name\" in $this")).jsonPrimitive.content
