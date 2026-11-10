package io.github.danielhp95.caracole.viewer.version

import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.viewer.ViewerData
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.util.Collections

/**
 * viewer/version.py's constants and patterns, and progressions.py's, as tests/test_conformance_viewer_version.py wrote
 * them from the modules themselves into caracole/viewer/version.json (that file's docstring is the format's): one
 * member a module, `version` and `progressions`, read once ([ViewerData]). Every pattern is compiled as Python reads it
 * (PyRegex), once; every collection handed out is one nothing can change.
 */
internal object VersionData {
    private val json: JsonObject by lazy { ViewerData.table("version") }

    /** One module's member of the data. */
    class Module(private val of: JsonObject) {
        fun pattern(name: String): Regex {
            val p = of.getValue("patterns").jsonObject.getValue(name).jsonObject
            val text = p.getValue("pattern").jsonPrimitive.content
            return PyRegex.compile(if (p.getValue("ignorecase").jsonPrimitive.boolean) "(?i)$text" else text)
        }

        fun text(name: String): String = of.getValue(name).jsonPrimitive.content
        fun int(name: String): Int = of.getValue(name).jsonPrimitive.int
        fun strings(name: String): Map<String, String> = Collections.unmodifiableMap(
            LinkedHashMap(of.getValue(name).jsonObject.mapValues { it.value.jsonPrimitive.content }))
        fun set(name: String): Set<String> =
            Collections.unmodifiableSet(of.getValue(name).jsonArray.mapTo(LinkedHashSet()) { it.jsonPrimitive.content })
    }

    val version: Module by lazy { Module(json.getValue("version").jsonObject) }
    val progressions: Module by lazy { Module(json.getValue("progressions").jsonObject) }
}
