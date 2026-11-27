package io.github.danielhp95.caracole.autochords

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.io.File
import java.io.IOException

/**
 * What the models heard in a song's audio, the chords-on-the-phone design's §4.4 `heard`, which a sheet is laid out
 * from (run.py `_make_sheet`'s inputs): its [contract] ([CONTRACT]), the audio's [duration] as music.py `read_audio`
 * states it (never its decoded samples over the rate), the [chords] btc.py `recognize` gives (common names, a run of
 * one name joined: [Labels.recognized]; times rounded as btc.py rounds them), and beat_this's [beats] and [downbeats],
 * in seconds. [json] writes it as §4.4 does, `{"contract", "duration", "chords": [[start, end, label], …], "beats",
 * "downbeats"}`; [read] reads back only that contract's.
 */
data class Heard(
    val contract: Int, val duration: Double, val chords: List<ChordSegment>, val beats: List<Double>,
    val downbeats: List<Double>,
) {
    fun json(): String = buildJsonObject {
        put("contract", contract)
        put("duration", duration)
        put("chords", Checkpoints.segments(chords))
        put("beats", JsonArray(beats.map(::JsonPrimitive)))
        put("downbeats", JsonArray(downbeats.map(::JsonPrimitive)))
    }.toString()

    companion object {
        /** The contract's number: what `heard` holds and how it was heard (models.json's `contract`). */
        const val CONTRACT = 1

        fun read(text: String): Heard {
            val doc = Json.parseToJsonElement(text).jsonObject
            val contract = doc["contract"]!!.jsonPrimitive.int
            require(contract == CONTRACT) { "a heard of contract $contract, not $CONTRACT" }
            return Heard(contract, doc["duration"]!!.jsonPrimitive.double, Checkpoints.segments(doc["chords"]!!),
                doc["beats"]!!.jsonArray.map { it.jsonPrimitive.double },
                doc["downbeats"]!!.jsonArray.map { it.jsonPrimitive.double })
        }
    }
}

/**
 * The chord models, wherever they run (the design's §3.1; on the phone `:ml`'s MlChordModels, the models in a process
 * of their own).
 *
 * - [ready]: null when the models can hear a song here, else why not in words (a file missing, one that isn't the one
 *   pinned).
 * - [hear]: the [audio] file heard, its steps told to [onStep] as they start, in run.py's words (`STEPS`: "setting up
 *   the models", "hearing the chords", "finding the beats"), and the phone's "waiting for the phone to cool"; [waiting]
 *   called about every second while the models work, a hand-over point (the lookups queued meanwhile go first). Audio
 *   that can't be decoded is [AudioUnreadable]; the models' setup failing (missing, stopped, too hot, the battery too
 *   low) [ChordsUnavailable], each in words.
 */
interface ChordModels {
    fun ready(): String?
    fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard
}

/** An audio file the models can't hear: decoded by nothing here, or too short to hold a chord. */
class AudioUnreadable(words: String, cause: Throwable? = null) : IOException(words, cause)

/** The chord models can't hear a song now: their files missing, their process stopped, the phone too hot, its
 * battery too low. Try again may do. */
class ChordsUnavailable(words: String, cause: Throwable? = null) : IOException(words, cause)
