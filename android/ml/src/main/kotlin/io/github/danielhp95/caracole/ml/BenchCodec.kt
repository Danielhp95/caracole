package io.github.danielhp95.caracole.ml

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.float
import kotlinx.serialization.json.floatOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put

/** What one session's process measured, whole: its [Session], its runs and its parity entries; [ended] once the
 * session is over (false in the writes it makes after each run as it goes), [nextSeconds] the audio's length of the
 * run it is about to make, which bounds how long the bench waits for its next write; [seq] numbers its writes from 1,
 * which is how the bench tells a new one ([SessionWrites]), never by a file's time. */
data class SessionResult(val session: Session, val runs: List<Run>, val btc: List<BtcParity>,
                         val beats: List<BeatParity>, val ended: Boolean = true, val nextSeconds: Double? = null,
                         val seq: Int = 0)

/**
 * A [SessionResult] as the text that crosses from the session's process to the bench's (a file the session writes as
 * it ends), every value as measured: no rounding, a float's and a double's bits kept (JSON's shortest text of each).
 */
object BenchCodec {
    fun encode(r: SessionResult): String = buildJsonObject {
        put("seq", r.seq)
        put("ended", r.ended)
        put("next_seconds", r.nextSeconds)
        put("session", buildJsonObject {
            val s = r.session
            put("model", s.model); put("threads", s.threads); put("arena", s.arena); put("round", s.round)
            put("load_seconds", s.loadSeconds); put("rss_peak_kb", s.rssPeakKb)
            put("battery_start_uah", s.batteryStartUah); put("battery_end_uah", s.batteryEndUah)
            put("failure", s.failure); put("stopped", s.stopped); put("pid", s.pid); put("fresh", s.fresh)
            put("complete", s.complete); put("out_of_memory", s.outOfMemory)
        })
        put("runs", JsonArray(r.runs.map { run ->
            buildJsonObject {
                put("file", run.file); put("kind", run.kind); put("model", run.model); put("pass", run.pass)
                put("threads", run.threads); put("arena", run.arena); put("screen", run.screen)
                put("cold", run.cold); put("nanos", run.nanos); put("duration", run.duration)
                put("samples", JsonArray(run.samples.map { s ->
                    buildJsonObject { put("pss_kb", s.pssKb); put("thermal", s.thermal); put("headroom", s.headroom) }
                }))
                put("reset", run.reset); put("rss_peak_kb", run.rssPeakKb)
                put("battery_start_uah", run.batteryStartUah); put("battery_end_uah", run.batteryEndUah)
                put("length_note", run.lengthNote)
            }
        }))
        put("btc", JsonArray(r.btc.map { b ->
            buildJsonObject {
                put("file", b.file); put("threads", b.threads); put("arena", b.arena); put("frames", b.frames)
                put("agreement", b.agreement)
                put("differ_margins", JsonArray(b.differMargins.map(::JsonPrimitive)))
                put("logits_max_abs", b.logitsMaxAbs)
            }
        }))
        put("beats", JsonArray(r.beats.map { b ->
            buildJsonObject {
                put("file", b.file); put("model", b.model); put("threads", b.threads); put("arena", b.arena)
                put("logits_max_abs", b.logitsMaxAbs); put("beats_f", b.beatsF); put("downbeats_f", b.downbeatsF)
            }
        }))
    }.toString()

    fun decode(text: String): SessionResult {
        val o = Json.parseToJsonElement(text).jsonObject
        val s = o.getValue("session").jsonObject
        return SessionResult(
            session = Session(s.str("model"), s.int("threads"), s.bool("arena"), s.str("round"),
                s.double("load_seconds"), s.long("rss_peak_kb"), s.long("battery_start_uah"),
                s.long("battery_end_uah"), s.strOrNull("failure"), s.strOrNull("stopped"),
                (s.value("pid") as? JsonPrimitive)?.content?.toIntOrNull(), s.bool("fresh"), s.bool("complete"),
                s.bool("out_of_memory")),
            runs = o.getValue("runs").jsonArray.map { it.jsonObject }.map { r ->
                Run(file = r.str("file"), kind = r.str("kind"), model = r.str("model"), pass = r.int("pass"),
                    threads = r.int("threads"), arena = r.bool("arena"), screen = r.str("screen"),
                    cold = r.bool("cold"), nanos = r.long("nanos")!!, duration = r.double("duration")!!,
                    samples = r.getValue("samples").jsonArray.map { it.jsonObject }.map { x ->
                        Sample(x.long("pss_kb"), x.str("thermal"), x.getValue("headroom").jsonPrimitive.floatOrNull)
                    },
                    reset = r.bool("reset"), rssPeakKb = r.long("rss_peak_kb"),
                    batteryStartUah = r.long("battery_start_uah"), batteryEndUah = r.long("battery_end_uah"),
                    lengthNote = r.strOrNull("length_note"))
            },
            btc = o.getValue("btc").jsonArray.map { it.jsonObject }.map { b ->
                BtcParity(b.str("file"), b.int("threads"), b.bool("arena"), b.int("frames"), b.double("agreement")!!,
                    b.getValue("differ_margins").jsonArray.map { it.jsonPrimitive.float },
                    b.getValue("logits_max_abs").jsonPrimitive.float)
            },
            beats = o.getValue("beats").jsonArray.map { it.jsonObject }.map { b ->
                BeatParity(b.str("file"), b.str("model"), b.int("threads"), b.bool("arena"),
                    b.getValue("logits_max_abs").jsonPrimitive.float, b.double("beats_f"), b.double("downbeats_f"))
            },
            ended = o.bool("ended"),
            seq = o.int("seq"),
            nextSeconds = o.double("next_seconds"),
        )
    }

    private fun JsonObject.value(key: String): JsonElement = get(key) ?: JsonNull
    private fun JsonObject.str(key: String) = getValue(key).jsonPrimitive.content
    private fun JsonObject.strOrNull(key: String) = (value(key) as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content
    private fun JsonObject.int(key: String) = getValue(key).jsonPrimitive.int
    private fun JsonObject.bool(key: String) = getValue(key).jsonPrimitive.boolean
    private fun JsonObject.long(key: String): Long? = value(key).jsonPrimitive.longOrNull
    private fun JsonObject.double(key: String): Double? = value(key).jsonPrimitive.doubleOrNull
}

/** A session's writes as the bench reads them: the text of its result file at each look, a write taken only when its
 * number is higher than the last one taken (two writes of one millisecond are two), one half written or older passed
 * over. */
class SessionWrites {
    var last: SessionResult? = null
        private set

    /** Whether [text] is a newer write than [last], which it then is. */
    fun take(text: String?): Boolean {
        if (text == null) return false
        val write = try {
            BenchCodec.decode(text)
        } catch (e: Exception) {
            return false
        }
        if (write.seq <= (last?.seq ?: 0)) return false
        last = write
        return true
    }
}
