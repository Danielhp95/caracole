package io.github.danielhp95.caracole.viewer.autochords

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.PyFloat
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigDecimal

/**
 * sheet.Heard: what the models heard in a song's audio, the chords-on-the-phone design's §4.4 `heard`, the one
 * record an auto sheet is laid out from ([SheetHalf.make]) and laid out again from ([Relay]): the [chords] btc.py's
 * `recognize` gives (COMMON names, "Am7", "Bb", "N" for none: never the Harte labels), beat_this's [beats] and
 * [downbeats], and the audio's [duration] as music.py `read_audio` states it (null when it names none), in seconds.
 * Its one home: `:autochords` and `:ml` name it by a typealias. [contract] is [CONTRACT] for any [read] one.
 *
 * [record] is sheet.heard_record, which an auto sheet's raw keeps as `raw["heard"]`, and [json] its json.dumps text:
 * each time a float written as Python's repr writes it (PyJson.float: `1e-07`, `3.0`, `-0.0`, `NaN`), never a
 * Double's toString. [read] and [of] are sheet.read_heard, as strict: an object; `contract` a number equal to 1, never
 * a bool; `duration` a number or null, and there; `chords` a list of `[number, number, text]`; `beats` and
 * `downbeats` lists of numbers; a number an int or a float (NaN and the infinities too, as json.loads reads them),
 * never a bool or a text, nor an int no float holds; each read as the float Python makes of it. Anything else is an
 * IllegalArgumentException, Python's ValueError.
 */
data class Heard(
    val contract: Int, val duration: Double?, val chords: List<ChordSegment>, val beats: List<Double>,
    val downbeats: List<Double>,
) {
    /** sheet.heard_record: `{"contract", "duration", "chords": [[start, end, label], …], "beats", "downbeats"}`. */
    fun record(): JsonObject = JsonObject(linkedMapOf(
        "contract" to JsonPrimitive(CONTRACT),
        "duration" to (duration?.let(PyJson::float) ?: JsonNull),
        "chords" to JsonArray(chords.map {
            JsonArray(listOf(PyJson.float(it.start), PyJson.float(it.end), JsonPrimitive(it.label)))
        }),
        "beats" to JsonArray(beats.map(PyJson::float)),
        "downbeats" to JsonArray(downbeats.map(PyJson::float)),
    ))

    /** json.dumps(heard_record(heard)): the text a checkpoint keeps, and `raw["heard"]` written alone. */
    fun json(): String = PyJson.dumps(record())

    companion object {
        /** sheet.CONTRACT: the shape of `raw["heard"]` (models.json's `contract` too). */
        const val CONTRACT = 1

        /** read_heard of json.loads([text]) (PyJson.loads: Python's reading of NaN, Infinity and its numbers). */
        fun read(text: String): Heard = of(PyJson.loads(text))

        /** sheet.read_heard: the Heard of a heard record, read strictly (the class's comment). */
        fun of(record: JsonElement): Heard {
            if (record !is JsonObject) throw IllegalArgumentException("what was heard isn't a record")
            val contract = record["contract"]
            if (contract !is JsonPrimitive || contract is JsonNull || contract.isString || bool(contract) ||
                !one(contract.content)) {
                throw IllegalArgumentException("what was heard is of contract $contract, not $CONTRACT")
            }
            if ("duration" !in record) throw IllegalArgumentException("what was heard has no duration")
            val duration = record.getValue("duration")
            val chords = record["chords"] as? JsonArray
                ?: throw IllegalArgumentException("what was heard has no list of chords")
            val segments = chords.map { chord ->
                val label = (chord as? JsonArray)?.takeIf { it.size == 3 }?.get(2) as? JsonPrimitive
                if (label == null || !label.isString) {
                    throw IllegalArgumentException("what was heard holds $chord where a chord [start, end, name] goes")
                }
                ChordSegment(number(chord[0]), number(chord[1]), label.content)
            }
            return Heard(CONTRACT, if (duration is JsonNull) null else number(duration), segments,
                         numbers(record, "beats"), numbers(record, "downbeats"))
        }

        private fun numbers(record: JsonObject, member: String): List<Double> {
            val value = record[member] as? JsonArray
                ?: throw IllegalArgumentException("what was heard has no list of numbers for its $member")
            return value.map(::number)
        }

        /** sheet._number: an int or a float, as the float Python makes of it; never a bool, a text, a list. */
        private fun number(value: JsonElement): Double {
            if (value !is JsonPrimitive || value is JsonNull || value.isString || bool(value)) {
                throw IllegalArgumentException("what was heard holds $value where a number goes")
            }
            val text = value.content
            val x = PyFloat.parse(text) ?: throw IllegalArgumentException("what was heard holds $text")
            if (integral(text) && x.isInfinite()) {
                throw IllegalArgumentException("what was heard holds an int too large for a float")
            }
            return x
        }

        private fun bool(p: JsonPrimitive) = p.content == "true" || p.content == "false"

        /** An int's literal, as json.loads tells one from a float's: no point, no exponent, no NaN or Infinity. */
        private fun integral(text: String) = text.none { it == '.' || it == 'e' || it == 'E' || it == 'N' || it == 'I' }

        /** `record["contract"] != CONTRACT` false: an int 1 or a float equal to 1.0. */
        private fun one(text: String): Boolean =
            if (integral(text)) BigDecimal(text).compareTo(BigDecimal.ONE) == 0 else PyFloat.parse(text) == 1.0
    }
}
