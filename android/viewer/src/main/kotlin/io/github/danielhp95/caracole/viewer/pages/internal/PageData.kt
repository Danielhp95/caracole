package io.github.danielhp95.caracole.viewer.pages.internal

import io.github.danielhp95.caracole.viewer.chinese.Hanzi
import io.github.danielhp95.caracole.viewer.chinese.ViewerPinyin
import io.github.danielhp95.caracole.viewer.harmony.HarmonyTables
import io.github.danielhp95.caracole.viewer.harp.Harp
import io.github.danielhp95.caracole.viewer.shapes.Instruments
import io.github.danielhp95.caracole.viewer.shapes.Voicings
import io.github.danielhp95.caracole.viewer.sheet.Sheet
import io.github.danielhp95.caracole.viewer.sheet.SheetView
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import io.github.danielhp95.caracole.viewer.winds.Winds
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * page._data: the song's data block, its members in Python's order (a member Python sets again, `names` for a sheet
 * with a key, keeps its place, as a dict's key does), each the module's answer the viewer packages give: each chord
 * as the script reads it (`rep`), each mode's chords, alternatives, names and capo hints, the fingerings and
 * instruments the page needs, the sheet's own shapes, harmony's, the harmonica's and the winds' tables, and a Chinese
 * sheet's pinyin and characters. viewer/page.py's docstring says what each member is.
 */
internal object PageData {
    fun data(sheet: Sheet, chords: List<Chord?>, key: Key?, origin: String?, transpose: Int): LinkedHashMap<String, JsonElement> {
        val needed = LinkedHashSet<String>()
        val kinds = LinkedHashMap<String, Chord>()  // each kind of chord the page shows, by its piano key

        fun rep(chord: Chord?): JsonElement {
            if (chord == null) return JsonNull
            kinds.putIfAbsent(Instruments.pianoKey(chord), chord)
            val (fingering, nearest, slash) = Voicings.voicingKeys(chord)
            needed += fingering
            if (!slash.isNullOrEmpty()) needed += slash
            return JsonArray(listOf(JsonPrimitive(chord.root), JsonPrimitive(chord.suffix), int(chord.bass),
                                    JsonPrimitive(fingering), JsonPrimitive(if (nearest) 1 else 0), text(slash)))
        }

        val data = LinkedHashMap<String, JsonElement>()
        data["chords"] = JsonArray(chords.map(::rep))
        data["key"] = if (key == null) JsonNull else JsonObject(linkedMapOf(
            "tonic" to JsonPrimitive(key.tonic), "mode" to JsonPrimitive(key.mode), "from" to text(origin)))
        data["transpose"] = JsonPrimitive(transpose)
        data["capoSheet"] = int(sheet.capo)
        val mapped = LinkedHashMap<String, JsonElement>()
        val alts = LinkedHashMap<String, JsonElement>()
        var names = linkedMapOf<String, JsonElement>("" to JsonPrimitive(Theory.spelling(null).joinToString(" ")))
        val keyNames = LinkedHashMap<String, JsonElement>()
        val capo = LinkedHashMap<String, JsonElement>()
        data["modes"] = JsonArray(emptyList())
        data["mapped"] = JsonNull
        data["alts"] = JsonNull
        data["names"] = JsonNull
        data["keyNames"] = JsonNull
        data["capo"] = JsonNull
        data["qualities"] = JsonObject(Theory.DISPLAY.mapValuesTo(LinkedHashMap()) { JsonPrimitive(it.value) })
        val mappedByMode = LinkedHashMap<String, List<Chord?>>()
        val altsByMode = LinkedHashMap<String, List<List<Chord>>>()
        if (key != null) {
            data["modes"] = JsonArray(Theory.MODES.map(::JsonPrimitive))
            names = LinkedHashMap()
            for (mode in Theory.MODES) {
                val inMode = Key(key.tonic, mode)
                val inKey = chords.map { c -> c?.let { Theory.mapChord(it, key, mode) } }
                mappedByMode[mode] = inKey
                altsByMode[mode] = inKey.map { c -> if (c == null) emptyList() else Theory.alternatives(c, inMode) }
                mapped[mode] = JsonArray(inKey.map(::rep))
                alts[mode] = JsonArray(altsByMode.getValue(mode).map { options -> JsonArray(options.map(::rep)) })
                names[mode] = JsonArray((0 until 12).map { JsonPrimitive(Theory.spelling(Key(it, mode)).joinToString(" ")) })
                keyNames[mode] = JsonArray((0 until 12).map { JsonPrimitive(Theory.keyName(Key(it, mode))) })
                capo[mode] = JsonArray((0 until 12).map { t ->
                    JsonArray(Theory.capoHints(Key(Math.floorMod(key.tonic + t, 12), mode), capo = sheet.capo ?: 0)
                        .map { (fret, shapes) -> JsonArray(listOf(JsonPrimitive(fret), JsonPrimitive(Theory.keyName(shapes)))) })
                })
            }
        }
        data["mapped"] = JsonObject(mapped)
        data["alts"] = JsonObject(alts)
        data["names"] = JsonObject(names)
        data["keyNames"] = JsonObject(keyNames)
        data["capo"] = JsonObject(capo)
        data["voicings"] = merged(Voicings.pageVoicings(needed), Instruments.pageVoicings(needed, kinds.values.toList()))
        data["instruments"] = Instruments.entries(needed)
        if (key != null) {
            data["easy"] = JsonObject(Instruments.EASY.keys.associateWithTo(LinkedHashMap()) { Instruments.easyKeys(it) })
        }
        data["shapes"] = SheetView.shapesOf(sheet)
        data.putAll(HarmonyTables.tables(chords, key, SheetView.places(sheet), mappedByMode, altsByMode))
        data.putAll(Harp.tables(key, mappedByMode, altsByMode))
        data.putAll(Winds.tables(chords, key, mappedByMode, altsByMode))
        data["winds"] = JsonObject(LinkedHashMap<String, JsonElement>(Winds.fingeringData()).also { it["harps"] = Harp.layouts() })
        data["library"] = JsonPrimitive(PageConstants.LIBRARY_PAGE)
        val readings = ViewerPinyin.readings(SheetView.drawnLines(sheet))
        if (readings != null) {
            data["pinyin"] = JsonArray(readings.map { line -> line?.let { JsonArray(it.map(::JsonPrimitive)) } ?: JsonNull })
            data["hanzi"] = names(Hanzi.scripts(SheetView.writtenTexts(sheet)))
        }
        return data
    }

    /** A names table (Hanzi's) as JSON, in its order. */
    fun names(table: Names): JsonObject = JsonObject(table.entries.associateTo(LinkedHashMap()) { (script, texts) ->
        script to JsonObject(texts.entries.associateTo(LinkedHashMap()) { (k, v) -> k to JsonPrimitive(v) })
    })

    /** Python's `a | b` of two dicts: a's members, each b's value where b has it, then b's others. */
    private fun merged(a: JsonObject, b: JsonObject): JsonObject =
        JsonObject(LinkedHashMap<String, JsonElement>(a).also { it.putAll(b) })

    private fun int(value: Int?): JsonElement = value?.let(::JsonPrimitive) ?: JsonNull
    private fun text(value: String?): JsonElement = value?.let(::JsonPrimitive) ?: JsonNull
}
