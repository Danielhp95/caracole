package io.github.danielhp95.caracole.core.testing

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.io.InputStream

/** One record of a `.jsonl` vector: a call and what Python answered ([out]), or the exception it raised ([err]);
 * [extra] holds the record's other keys (fixture, note, seed…). */
data class Record(val fn: String, val args: JsonArray, val kw: JsonObject, val out: JsonElement?, val err: String?,
                  val extra: JsonObject)

/**
 * The conformance corpus, as the Python suite wrote it (docs/superpowers/specs/2026-11-03-conformance-corpus.md).
 * A name is a path under tests/conformance/vectors/ ("unicode/categories.jsonl"). A missing file fails the test: it
 * never skips.
 */
object Corpus {
    /** Opens a vector by its path; by default from the folder in the system property `caracole.conformance`, which
     * Gradle sets for every test task. An androidTest sets it from the instrumentation's AssetManager. */
    @JvmStatic
    var open: (String) -> InputStream? = { name ->
        System.getProperty("caracole.conformance")?.let { File(it, name) }?.takeIf { it.isFile }?.inputStream()
    }

    fun text(name: String): String {
        val stream = open(name) ?: throw AssertionError(
            "the conformance vector $name is missing (caracole.conformance=${System.getProperty("caracole.conformance")}): " +
                "regenerate it with CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py",
        )
        return stream.use { it.readBytes().toString(Charsets.UTF_8) }
    }

    /** Every line of a `.jsonl` vector, the header first. */
    fun lines(name: String): List<JsonObject> =
        text(name).split('\n').filter { it.isNotEmpty() }.map { Json.parseToJsonElement(it).jsonObject }

    /** A `.jsonl` vector's header. */
    fun header(name: String): JsonObject = lines(name).first().also {
        check(it["header"] == JsonPrimitive(true)) { "$name starts with no header" }
    }

    /** A `.jsonl` vector's records, its header left out. */
    fun records(name: String): List<Record> = lines(name).filter { it["header"] != JsonPrimitive(true) }.map { line ->
        Record(
            fn = line["fn"]?.jsonPrimitive?.content ?: "",
            args = line["args"] as? JsonArray ?: JsonArray(emptyList()),
            kw = line["kw"] as? JsonObject ?: JsonObject(emptyMap()),
            out = line["out"],
            err = line["err"]?.jsonPrimitive?.content,
            extra = JsonObject(line.filterKeys { it !in RECORD_KEYS }),
        )
    }

    /** A `.json` vector: one object, its `header` among its members. */
    fun json(name: String): JsonObject = Json.parseToJsonElement(text(name)).jsonObject

    private val RECORD_KEYS = setOf("fn", "args", "kw", "out", "err")
}
