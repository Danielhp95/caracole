package io.github.danielhp95.caracole.viewer.pages

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

/** viewer/harptab_page.py: a harmonica tab's page, byte for byte (lane harmonica-page). */
object HarmonicaPage {
    /** build_harmonica_viewer: [pin] a preset's name, "legend" or a table (overrides.toml's `[harmonica]`). */
    fun build(text: String, title: String, artist: String = "", tabFile: String, url: String? = null,
              pageKey: String? = null, harp: String? = null, pin: JsonElement? = null, facts: JsonObject? = null,
              cho: String? = null, key: String? = null, keySource: String? = null, back: String? = null): String =
        TODO("lane harmonica-page")
}
