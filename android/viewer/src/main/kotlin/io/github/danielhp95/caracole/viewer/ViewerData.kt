package io.github.danielhp95.caracole.viewer

import kotlinx.serialization.json.JsonObject

/** A viewer module's constants and HTML templates, exported by Python from the module itself, never retyped:
 * data/caracole/viewer/<module>.json (lane theory; each M5 lane writes its own module's file). */
object ViewerData {
    fun table(module: String): JsonObject = TODO("lane theory")
}
