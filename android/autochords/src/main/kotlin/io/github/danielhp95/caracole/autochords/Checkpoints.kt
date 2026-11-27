package io.github.danielhp95.caracole.autochords

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.json.put
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest

/**
 * A hearing's checkpoints (the design's §3.3), in `<root>/<sha16>-c<contract>/` ([folder]): the first 16 hex digits
 * of the audio's SHA-256 and [Heard.CONTRACT], so a checkpoint of another file or another contract is never read.
 * Each step's file, in order: [PCM_META] and [PCM] (the audio mono at 22,050 Hz, float32), [CHORDS] (BTC's chords,
 * Harte labels spelled for the key, before [Labels.recognized]), [BEATS], then [HEARD]. A file is written under a name
 * of its own ([PART] after it) and renamed into place, so one cut off is never read: [read] reads the name alone.
 */
class Checkpoints private constructor(val folder: File) {
    /** [name]'s text, or null while no whole one is there. */
    fun read(name: String): String? = File(folder, name).takeIf { it.isFile }?.readText(Charsets.UTF_8)

    fun has(name: String): Boolean = File(folder, name).isFile

    fun write(name: String, text: String) = into(name) { it.writeText(text, Charsets.UTF_8) }

    /** [name] made by [write], into a part first, then renamed into place. */
    fun into(name: String, write: (File) -> Unit) {
        folder.mkdirs()
        val part = File(folder, name + PART)
        write(part)
        Files.move(part.toPath(), File(folder, name).toPath(), StandardCopyOption.ATOMIC_MOVE,
            StandardCopyOption.REPLACE_EXISTING)
    }

    fun file(name: String) = File(folder, name)

    /** What [PCM_META] says of [PCM]: the audio's stated length and the samples at 22,050 Hz. */
    data class Pcm(val duration: Double, val samples: Long)

    companion object {
        const val PCM = "pcm.f32"
        const val PCM_META = "pcm.json"
        const val CHORDS = "chords.json"
        const val BEATS = "beats.json"
        const val HEARD = "heard.json"
        const val PART = ".part"

        fun of(root: File, audio: File) = Checkpoints(File(root, "${sha16(audio)}-c${Heard.CONTRACT}"))

        /** The first 16 hex digits of [file]'s SHA-256 (design C's kept-file name's). */
        fun sha16(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val chunk = ByteArray(1 shl 20)
                while (true) {
                    val n = input.read(chunk)
                    if (n < 0) break
                    digest.update(chunk, 0, n)
                }
            }
            return digest.digest().take(8).joinToString("") { "%02x".format(it.toInt() and 0xFF) }
        }

        fun chordsJson(harte: List<ChordSegment>): String = buildJsonObject { put("harte", segments(harte)) }.toString()

        fun readChords(text: String): List<ChordSegment> =
            segments(Json.parseToJsonElement(text).jsonObject["harte"]!!)

        fun beatsJson(beats: List<Double>, downbeats: List<Double>): String = buildJsonObject {
            put("beats", JsonArray(beats.map(::JsonPrimitive)))
            put("downbeats", JsonArray(downbeats.map(::JsonPrimitive)))
        }.toString()

        fun readBeats(text: String): Pair<List<Double>, List<Double>> {
            val doc = Json.parseToJsonElement(text).jsonObject
            return doc["beats"]!!.jsonArray.map { it.jsonPrimitive.double } to
                doc["downbeats"]!!.jsonArray.map { it.jsonPrimitive.double }
        }

        fun pcmJson(pcm: Pcm): String = buildJsonObject {
            put("duration", pcm.duration)
            put("samples", pcm.samples)
        }.toString()

        fun readPcm(text: String): Pcm {
            val doc = Json.parseToJsonElement(text).jsonObject
            return Pcm(doc["duration"]!!.jsonPrimitive.double, doc["samples"]!!.jsonPrimitive.long)
        }

        internal fun segments(chords: List<ChordSegment>) = JsonArray(chords.map {
            JsonArray(listOf(JsonPrimitive(it.start), JsonPrimitive(it.end), JsonPrimitive(it.label)))
        })

        internal fun segments(json: JsonElement): List<ChordSegment> = json.jsonArray.map { s ->
            val (start, end, label) = s.jsonArray
            ChordSegment(start.jsonPrimitive.double, end.jsonPrimitive.double, label.jsonPrimitive.content)
        }
    }
}
