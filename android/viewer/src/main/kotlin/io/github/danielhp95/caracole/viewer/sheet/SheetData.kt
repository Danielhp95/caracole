package io.github.danielhp95.caracole.viewer.sheet

import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.viewer.ViewerData
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.util.Collections

/**
 * The constants and patterns of viewer/sheet.py, page.py's key words, chordpro.py, render.py's look-alike letters,
 * ug/page.py's entity pattern and keys.py, as tests/test_conformance_viewer_sheet.py wrote them from the modules
 * themselves into caracole/viewer/sheet.json (that file's docstring is the format's), read once ([ViewerData]). Every
 * pattern is compiled as Python reads it (PyRegex), once; every collection handed out is one nothing can change.
 */
internal object SheetData {
    private val json: JsonObject by lazy { ViewerData.table("sheet") }

    /** One module's member of the data. */
    class Module(private val of: JsonObject) {
        fun pattern(name: String): Regex {
            val p = of.getValue("patterns").jsonObject.getValue(name).jsonObject
            val text = p.getValue("pattern").jsonPrimitive.content
            return PyRegex.compile(if (p.getValue("ignorecase").jsonPrimitive.boolean) "(?i)$text" else text)
        }

        fun text(name: String): String = of.getValue(name).jsonPrimitive.content
        fun int(name: String): Int = of.getValue(name).jsonPrimitive.int
        fun double(name: String): Double = of.getValue(name).jsonPrimitive.double
        fun list(name: String): List<String> =
            Collections.unmodifiableList(of.getValue(name).jsonArray.map { it.jsonPrimitive.content })
        fun doubles(name: String): List<Double> =
            Collections.unmodifiableList(of.getValue(name).jsonArray.map { it.jsonPrimitive.double })
        fun strings(name: String): Map<String, String> =
            Collections.unmodifiableMap(LinkedHashMap(of.getValue(name).jsonObject.mapValues { it.value.jsonPrimitive.content }))
        fun ints(name: String): Map<String, Int> =
            Collections.unmodifiableMap(LinkedHashMap(of.getValue(name).jsonObject.mapValues { it.value.jsonPrimitive.int }))
        fun obj(name: String): JsonObject = of.getValue(name).jsonObject

        /** `[[first, last], …]`, inclusive. */
        fun ranges(name: String): List<IntRange> = Collections.unmodifiableList(of.getValue(name).jsonArray.map {
            val (first, last) = it.jsonArray
            first.jsonPrimitive.int..last.jsonPrimitive.int
        })
    }

    val sheet: Module by lazy { Module(json.getValue("sheet").jsonObject) }
    val page: Module by lazy { Module(json.getValue("page").jsonObject) }
    val chordpro: Module by lazy { Module(json.getValue("chordpro").jsonObject) }
    val render: Module by lazy { Module(json.getValue("render").jsonObject) }
    val ugPage: Module by lazy { Module(json.getValue("ug_page").jsonObject) }
    val keys: Module by lazy { Module(json.getValue("keys").jsonObject) }

    /** A `{character: what it becomes}` table, as str.translate reads one, by code point. */
    fun translation(table: Map<String, String>): Map<Int, String> =
        Collections.unmodifiableMap(table.entries.associate { (k, v) ->
            require(k.codePointCount(0, k.length) == 1) { "$k is no character" }
            k.codePointAt(0) to v
        })
}
