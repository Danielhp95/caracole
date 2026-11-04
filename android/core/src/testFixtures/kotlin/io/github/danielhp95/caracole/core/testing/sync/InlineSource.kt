package io.github.danielhp95.caracole.core.testing.sync

import io.github.danielhp95.caracole.core.sync.UnitError
import io.github.danielhp95.caracole.core.sync.UnitSource
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.util.Base64

/**
 * A UnitSource of documents and files held in memory: a take.jsonl record's `source`, or a fixture's documents and
 * kept files, as the phone's tests read them (the corpus's InlineSource). A file it doesn't hold is a UnitError in
 * Python's words.
 */
class InlineSource(private val units: Map<String, JsonObject?>, private val files: List<Kept>) : UnitSource {
    data class Kept(val song: String, val name: String, val sha256: String, val bytes: ByteArray)

    val asked = mutableListOf<String>()

    override fun unit(id: String): JsonObject? = units[id].also { asked += id }

    override fun file(songKey: String, name: String, sha256: String): ByteArray =
        files.firstOrNull { it.song == songKey && it.name == name && it.sha256 == sha256 }?.bytes
            ?: throw UnitError("$name: there, no such file is kept")

    companion object {
        /** A take.jsonl record's `source`: `{units: {id: document or null}, files: [{song, name, sha256, base64}]}`. */
        fun of(source: JsonObject): InlineSource = InlineSource(
            source.getValue("units").jsonObject.mapValues { it.value as? JsonObject },
            source.getValue("files").jsonArray.map { it.jsonObject }.map {
                Kept(it.getValue("song").jsonPrimitive.content, it.getValue("name").jsonPrimitive.content,
                     it.getValue("sha256").jsonPrimitive.content,
                     Base64.getDecoder().decode(it.getValue("base64").jsonPrimitive.content))
            },
        )
    }
}
