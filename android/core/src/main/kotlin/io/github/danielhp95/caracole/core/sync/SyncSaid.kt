package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.py.Py
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * What a sync or an import took and gave, a line a unit, as commands/peer.py's `done_line` and `done_lines` say it
 * (its words: data/caracole/sync/said.json, written by tests/test_conformance_sync_said.py, never retyped here):
 * "Took Radiohead - Creep", "Gave songbook Campfire"; a unit the side it came from holds none of a removal, named as a
 * tombstone's label names one ("Took Oasis - Wonderwall (removed)"); a conflict with the side that came ("Took Blur -
 * Song 2: changed on both sides, theirs kept"); a tombstone that goes with its song said by the song's line alone; at
 * most `most` a way, then "Took … and 312 more". The phone's Journal says them before its "Left as it was" lines
 * (SyncRoutes.said), held by vectors/sync/said.jsonl (SyncReplay.said).
 */
object SyncSaid {
    private val data: JsonObject by lazy { Json.parseToJsonElement(Database.resource("caracole/sync/said.json")).jsonObject }
    private fun word(group: String, way: String): String = data.getValue(group).jsonObject.getValue(way).jsonPrimitive.content

    const val TAKEN = "taken"
    const val GIVEN = "given"

    /** The units said by name a way (commands/peer.py's DONE_MOST). */
    val MOST: Int by lazy { data.getValue("most").jsonPrimitive.int }

    /** A unit taken or given ([way], [TAKEN] or [GIVEN]) by [name] on one line, whitespace collapsed as Python's
     * split() and join collapse it; [d], its difference as compared, says a removal and a conflict (`done_line`). */
    fun line(way: String, name: String, d: Difference? = null): String {
        var shown = Py.split(name).joinToString(" ").ifEmpty { name }
        if (d != null && !d.id.startsWith("removed/") && (if (way == TAKEN) d.theirs else d.mine) == null) {
            shown = data.getValue("removed_label").jsonPrimitive.content.replace("{}", shown)
        }
        val conflict = if (d != null && d.proposal == Compare.CONFLICT) ": " + word("conflict_came", way) else ""
        return "${word("done", way)} $shown$conflict"
    }

    /** What a sync took ([taken], in the order taken) and gave ([given]), a [line] a unit by its label as compared
     * ([compared]; else its id), at most [MOST] a way, then how many more (`done_lines`). */
    fun lines(taken: List<String>, given: List<String>, compared: List<Difference>): List<String> {
        val byId = compared.associateBy { it.id }
        val out = ArrayList<String>()
        for ((way, units) in listOf(TAKEN to taken, GIVEN to given)) {
            val songs = units.filter { it.startsWith("song/") }.toSet()
            val said = units.filter { !(it.startsWith("removed/") && "song/" + it.removePrefix("removed/") in songs) }
            for (unit in said.take(MOST)) {
                val d = byId[unit]
                out.add(line(way, d?.label ?: unit, d))
            }
            if (said.size > MOST) {
                out.add("${word("done", way)} " + data.getValue("more").jsonPrimitive.content
                    .replace("{}", (said.size - MOST).toString()))
            }
        }
        return out
    }
}
