package io.github.danielhp95.caracole.e2e

import io.github.danielhp95.caracole.core.models.From
import io.github.danielhp95.caracole.core.models.ModelFiles
import io.github.danielhp95.caracole.core.models.ModelsSource
import io.github.danielhp95.caracole.core.models.Pin
import io.github.danielhp95.caracole.core.models.Pins
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.viewer.autochords.AudioUnreadable
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import io.github.danielhp95.caracole.viewer.autochords.Heard
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.security.MessageDigest

/**
 * The chord models of the scenario's phone on the JVM, which has no `:ml`: what the computer's models heard in a
 * committed clip ([CLIP], tests/fixtures/autochords/; its `hearing` record of vectors/autochords/models.jsonl: BTC's
 * segments in common names, beat_this's beats and downbeats, the clip's length as music.py reads it), answered for
 * that clip's audio alone (by its bytes), any other audio [AudioUnreadable]. Ready always; each hearing counted
 * ([heard]), its steps said in run.py's words as the real models say them.
 *
 * [installed] are the models' files the phone's own job installs from (ModelsRunner, `PhoneDeps.models`): three tiny
 * files under the real files' names, each pinned from the app ([From.App], nothing asked of GitHub), with the real
 * pins' contract and [Pins.models] names (models.json, read from the corpus's data: the e2e's classpath, as the
 * release's, carries none), so that ModelsRunner.ready() judges them as it judges the real ones, by their manifest.
 */
class RecordedChordModels : ChordModels {
    private val record: JsonObject = Corpus.lines("autochords/models.jsonl").first {
        it["kind"] == JsonPrimitive("hearing") && it["file"]?.jsonObject?.get("fixture") == JsonPrimitive(CLIP)
    }

    /** The clip's bytes, as the e2e stages them. */
    val clip: ByteArray = Corpus.fixture(CLIP)

    /** What the computer heard in [clip], as a sheet keeps it. */
    val heardOfClip: Heard = Heard.of(JsonObject(linkedMapOf(
        "contract" to JsonPrimitive(Heard.CONTRACT),
        "duration" to record.getValue("duration"),
        "chords" to record.getValue("btc").jsonObject.getValue("segments"),
        "beats" to record.getValue("beats").jsonObject.getValue("beats"),
        "downbeats" to record.getValue("beats").jsonObject.getValue("downbeats"),
    )))

    /** The clip's length as the computer read it (the examiner's). */
    val duration: Double = record.getValue("duration").jsonPrimitive.content.toDouble()

    @Volatile var heard: Int = 0
        private set

    override fun ready(): String? = null

    override fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard {
        if (!sha256(audio.readBytes()).contentEquals(sha256(clip))) {
            throw AudioUnreadable("not the recorded clip ($CLIP): ${audio.name}")
        }
        for (step in STEPS) {
            onStep(step)
            waiting()
        }
        heard++
        return heardOfClip
    }

    override val runtime: String get() = RUNTIME

    companion object {
        const val CLIP = "autochords/hearing.mp3"
        const val RUNTIME = "recorded (vectors/autochords/models.jsonl)"
        private val STEPS = listOf("setting up the models", "hearing the chords", "finding the beats")

        private val files: Map<String, ByteArray> = mapOf(
            "btc-graph.onnx" to "the graph".toByteArray(),
            "btc_model_large_voca.pt" to "the weights".toByteArray(),
            "beat_this-final0-fp16.onnx" to "the beats".toByteArray(),
        )

        /** The models' files as the phone's job installs them here: [files], each from the app, under the real
         * pins' contract and names. */
        fun installed(): ModelsSource {
            val data = File(System.getProperty("caracole.conformance")).resolveSibling("data")
            val real = ModelFiles.read(File(data, "caracole/autochords/models.json").readBytes())
            val pins = Pins(real.contract, real.release, files.map { (name, bytes) ->
                Pin(name, bytes.size.toLong(), hex(sha256(bytes)), From.App)
            }, real.models)
            return ModelsSource(pins = { pins }, app = { name -> files[name]?.inputStream() })
        }

        private fun sha256(bytes: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(bytes)

        private fun hex(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it.toInt() and 0xff) }
    }
}
