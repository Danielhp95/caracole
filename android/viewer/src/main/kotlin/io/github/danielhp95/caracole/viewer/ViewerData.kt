package io.github.danielhp95.caracole.viewer

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import java.util.concurrent.ConcurrentHashMap

/**
 * What each viewer/ module states as data, as its generator wrote it from the module itself:
 * tests/conformance/data/caracole/viewer/<module>.json, caracole/viewer/<module>.json on the classpath (a resource
 * of :core, in the APK). Each is one object, its members the module's constants under their Python names, a dict's
 * members in Python's order (tests/helpers/viewer_corpus.py `data_json`; each generator's docstring gives its
 * format). Never retyped in Kotlin: a change to the module regenerates the file.
 */
object ViewerData {
    private val tables = ConcurrentHashMap<String, JsonObject>()

    /**
     * The data of viewer/[module].py ("theory"), read once. A module with no data, or data that isn't one JSON
     * object in UTF-8, is an [IllegalStateException]; a name that is no module's, or whose `<module>.json` is a file
     * of viewer/ that copyViewerAssets puts in the same classpath folder ([ViewerAssets.isAsset]: voicings.py's data
     * is the asset voicings.json, never a generator's), an [IllegalArgumentException].
     */
    fun table(module: String): JsonObject {
        require(module.isNotEmpty() && module.all { it in 'a'..'z' || it in '0'..'9' || it == '_' }) {
            "$module names no viewer module"
        }
        require(!ViewerAssets.isAsset("$module.json")) { "$module.json is an asset of viewer/, no module's data" }
        return tables.getOrPut(module) {
            val path = "caracole/viewer/$module.json"
            val stream = ViewerData::class.java.classLoader?.getResourceAsStream(path)
                ?: ViewerData::class.java.getResourceAsStream("/$path")
                ?: throw IllegalStateException("$path is not on the classpath: its generator writes it (tests/conformance/data)")
            val text = ViewerAssets.strictUtf8(stream.use { it.readBytes() }, path)
            Json.parseToJsonElement(text) as? JsonObject ?: throw IllegalStateException("$path holds no JSON object")
        }
    }
}
