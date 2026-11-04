package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongbookStore
import io.github.danielhp95.caracole.core.songbooks.SongbookError
import io.github.danielhp95.caracole.core.songbooks.Songbooks
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import java.io.File
import java.nio.file.Files

/**
 * Songbooks named, made and edited (vectors/songbook/, tests/test_conformance_songbook.py) (lanes songbook-writers,
 * songbook-entries), every record answered as songbook.py answered it, a refusal by its class and its words exactly:
 *
 * - writers_names.jsonl: Songbooks.checkName, nameKey and folderKey;
 * - writers_entries.jsonl: entryKeys (in Python's order), sameEntry, and findEntrySong over writers_library.jsonl's
 *   library (the song's key, or null);
 * - writers.jsonl: each writer over phone_songbooks holding the record's `before` (each put in order, as a sync puts
 *   one), its result, the songbooks after (Songbooks.all, and the rows SongbookStore holds, each as
 *   peer_sync.songbook_value), and their units (Units.libraryState's label and digest, Units.document the value),
 *   which the computer takes; a refusal leaves the songbooks as they were. put_songbook is SongbookStore.put, the
 *   take's.
 */
object SongbookReplay : AreaReplay {
    override val area = "songbook"

    const val NAMES = "songbook/writers_names.jsonl"
    const val ENTRIES = "songbook/writers_entries.jsonl"
    const val LIBRARY = "songbook/writers_library.jsonl"
    const val WRITERS = "songbook/writers.jsonl"

    override fun replay(misses: Misses) {
        names(misses)
        withDb { db, _ ->
            Fixtures.load(db, LIBRARY)
            entries(db, misses)
        }
        withDb { db, dir -> writers(db, dir, misses) }
    }

    private fun names(misses: Misses) {
        for (r in Corpus.records(NAMES)) {
            val name = text(r.args[0])
            val got = when (r.fn) {
                "caracole.songbook.check_name" -> answer { JsonPrimitive(Songbooks.checkName(name)) }
                "caracole.songbook.name_key" -> answer { JsonPrimitive(Songbooks.nameKey(name)) }
                "caracole.songbook._folder_key" -> answer { JsonPrimitive(Songbooks.folderKey(name)) }
                else -> null
            }
            compare(misses, r, got)
        }
    }

    private fun entries(db: Db, misses: Misses) {
        for (r in Corpus.records(ENTRIES)) {
            val text = text(r.args[0])
            val got = when (r.fn) {
                "caracole.songbook.entry_keys" ->
                    answer { JsonArray(Songbooks.entryKeys(text).map(::JsonPrimitive)) }
                "caracole.songbook.same_entry" -> answer { JsonPrimitive(Songbooks.sameEntry(text, text(r.args[1]))) }
                "caracole.songbook.find_entry_song" ->
                    answer { Songbooks.findEntrySong(db, text)?.key?.let(::JsonPrimitive) ?: JsonNull }
                else -> null
            }
            compare(misses, r, got)
        }
    }

    private fun writers(db: Db, dir: File, misses: Misses) {
        for (r in Corpus.records(WRITERS)) {
            val case = r.extra["case"]?.let(::text) ?: r.fn
            val before = r.extra["before"] as? JsonArray
            if (before == null) {
                misses.check(false) { "$case: no songbooks before" }
                continue
            }
            db.execute("DELETE FROM phone_songbooks")
            for (book in before) {
                book as JsonObject
                SongbookStore.put(db, text(book.getValue("name")), book.getValue("songs") as JsonArray)
            }
            val start = stored(db)
            misses.check(same(start, before)) { "$case: the songbooks before are $start, Python's $before" }
            val got = answer { write(db, r) }
            if (r.err != null) {
                compare(misses, r, got, case)
                misses.check(same(stored(db), before)) { "$case: a refusal left ${stored(db)}, not $before" }
                continue
            }
            val out = r.out as? JsonObject
            val result = got["out"]
            if (out == null || result == null) {
                misses.check(false) { "$case: ${r.fn}(${r.args}) answered $got, Python's ${r.out}" }
                continue
            }
            misses.check(same(result, out["result"] ?: JsonNull)) {
                "$case: ${r.fn}(${r.args}) = $result, Python's ${out["result"]}"
            }
            val books = out["books"] ?: JsonNull
            val all = JsonArray(Songbooks.all(db).map(Songbooks::value))
            misses.check(same(all, books)) { "$case: Songbooks.all = $all, Python's $books" }
            misses.check(same(stored(db), books)) { "$case: the rows hold ${stored(db)}, Python's $books" }
            val units = JsonObject(Units.libraryState(db).filterKeys { it.startsWith("songbook/") }.mapValues { (_, u) ->
                JsonObject(linkedMapOf("label" to JsonPrimitive(u.label), "digest" to JsonPrimitive(u.digest)))
            })
            misses.check(same(units, out["units"] ?: JsonNull)) { "$case: the units are $units, Python's ${out["units"]}" }
            for (book in books as? JsonArray ?: JsonArray(emptyList())) {
                val id = "songbook/" + Songbooks.nameKey(text((book as JsonObject).getValue("name")))
                val doc = Units.document(db, dir, id)
                misses.check(doc != null && same(doc, book)) { "$case: the unit $id's document is $doc, Python's $book" }
            }
        }
    }

    /** The record's writer, called as Python called it; what it returned, as the record holds it. */
    private fun write(db: Db, r: Record): JsonElement {
        val name = text(r.args[0])
        return when (r.fn.removePrefix("caracole.songbook.")) {
            "make_songbook" -> Songbooks.value(Songbooks.make(db, name, texts(r.args[1])))
            "add_to_songbook" -> JsonArray(Songbooks.add(db, name, texts(r.args[1])).map(::JsonPrimitive))
            "remove_from_songbook" -> JsonArray(Songbooks.remove(db, name, texts(r.args[1])).map(::JsonPrimitive))
            "move_in_songbook" -> JsonPrimitive(Songbooks.move(db, name, text(r.args[1]),
                                                               (r.args[2] as JsonPrimitive).intOrNull!!))
            "rename_songbook" -> Songbooks.value(Songbooks.rename(db, name, text(r.args[1])))
            "delete_songbook" -> Songbooks.value(Songbooks.delete(db, name))
            "put_songbook" -> JsonNull.also { SongbookStore.put(db, name, r.args[1] as? JsonArray) }
            else -> throw AssertionError("no writer ${r.fn}")
        }
    }

    /** The songbooks phone_songbooks holds, in their order, each as songbook_value: what a sync gives. */
    private fun stored(db: Db): JsonArray = JsonArray(SongbookStore.all(db).map {
        JsonObject(linkedMapOf("name" to JsonPrimitive(it.name), "songs" to it.songs))
    })

    /** A call's answer as a record holds it: `{"out": …}`, or `{"err": "SongbookError", "words": …}`. */
    private fun answer(call: () -> JsonElement): JsonObject = try {
        JsonObject(mapOf("out" to call()))
    } catch (e: SongbookError) {
        JsonObject(mapOf("err" to JsonPrimitive("SongbookError"), "words" to JsonPrimitive(e.message ?: "")))
    }

    private fun compare(misses: Misses, r: Record, got: JsonObject?, case: String? = null) {
        val want = if (r.err != null) {
            JsonObject(mapOf("err" to JsonPrimitive(r.err), "words" to (r.extra["words"] ?: JsonNull)))
        } else {
            JsonObject(mapOf("out" to (r.out ?: JsonNull)))
        }
        misses.check(got != null && same(got, want)) {
            "${case ?: r.fn}(${r.args.toString().take(120)}) answered $got, Python's $want"
        }
    }

    private fun texts(e: JsonElement): List<String> = (e as JsonArray).map(::text)

    private fun text(e: JsonElement): String = (e as JsonPrimitive).also { check(it.isString) { "not a text: $e" } }.content

    /** Two JSON values alike as Python compares them once read: objects by their members (in any order), arrays item
     * for item, the rest as written (a capo 2 is 2: no number here is a float). */
    private fun same(a: JsonElement, b: JsonElement): Boolean = when {
        a is JsonObject && b is JsonObject -> a.keys == b.keys && a.all { (k, v) -> same(v, b.getValue(k)) }
        a is JsonArray && b is JsonArray -> a.size == b.size && a.indices.all { same(a[it], b[it]) }
        else -> a == b
    }

    private fun withDb(block: (Db, File) -> Unit) {
        val dir = Files.createTempDirectory("caracole-songbook").toFile()
        try {
            TestDb.fresh(dir).use { database -> database.writeBlocking { db -> block(db, dir) } }
        } finally {
            dir.deleteRecursively()
        }
    }
}
