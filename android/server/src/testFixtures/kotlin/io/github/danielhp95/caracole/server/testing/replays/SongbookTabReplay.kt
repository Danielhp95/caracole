package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.inbox.GuitarFile
import io.github.danielhp95.caracole.core.inbox.GuitarFiles
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongbookStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.songbooks.Setting
import io.github.danielhp95.caracole.core.songbooks.Songbook
import io.github.danielhp95.caracole.core.songbooks.SongbookError
import io.github.danielhp95.caracole.core.songbooks.SongbookSong
import io.github.danielhp95.caracole.core.songbooks.Songbooks
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.page.SongbookSection
import io.github.danielhp95.caracole.server.songbooks.Entry
import io.github.danielhp95.caracole.server.songbooks.SongbookEntries
import io.github.danielhp95.caracole.server.songbooks.SongbookPagesImpl
import io.github.danielhp95.caracole.viewer.pages.BookSong
import io.github.danielhp95.caracole.viewer.pages.SongbookPage
import io.github.danielhp95.caracole.viewer.version.Versions
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.nio.file.Files
import java.nio.file.attribute.FileTime

/**
 * A songbook's entries, settings, page and the Songbooks tab's data (tests/test_conformance_songbook_tab.py) (lanes
 * songbook-entries, then songbook-routes), each record answered as Python answered it:
 *
 * - songbook/entries.jsonl, over fixtures/entries-library.jsonl and its first record's overrides: SongbookEntries'
 *   entries (each as the record writes songbook.Entry, its plays_in and where_played), songsToGet, withCapo and
 *   onInstrument (`caracole songbook set`'s), Songbooks.listing, and Songbooks.set over phone_songbooks holding the
 *   record's `before` (its setting checked by Versions.settingProblem, a refusal in its words);
 * - songbook/tab.jsonl: SongbookSection.data with the phone's files, the songbooks' files dated as the record says,
 *   whole; and each songbook's BookSongs as SongbookPagesImpl makes them of its entries, with the page of them;
 * - viewer/songbook_pages.jsonl: SongbookPage.build, page by page, by its pieces.
 */
object SongbookTabReplay : AreaReplay {
    override val area = "songbook-tab"

    const val ENTRIES = "songbook/entries.jsonl"
    const val TAB = "songbook/tab.jsonl"
    const val PAGES = "viewer/songbook_pages.jsonl"
    const val LIBRARY = "songbook/fixtures/entries-library.jsonl"

    private const val S = "caracole.songbook."

    override fun replay(misses: Misses) {
        entries(misses)
        tab(misses)
        pages(misses)
    }

    /** vectors/songbook/entries.jsonl. */
    fun entries(misses: Misses) {
        val records = Corpus.records(ENTRIES)
        val overrides = overrides(records)
        withLibrary { db, dir ->
            val books = Songbooks.all(db)
            fun book(r: Record) = Songbooks.find(books, text(r.extra.getValue("book")))!!
            fun played(r: Record, setting: Setting?): Entry =
                SongbookEntries.entries(db, dir, overrides, Songbook("x", listOf(SongbookSong(text(r.extra.getValue("entry")), setting)))).single()
            for (r in records) {
                when (r.fn.removePrefix(S)) {
                    "songbook_entries" -> misses.expect(r.fn, text(r.extra.getValue("book")), r.out) {
                        JsonArray(SongbookEntries.entries(db, dir, overrides, book(r)).map(::entryJson))
                    }
                    "songs_to_get" -> misses.expect(r.fn, text(r.extra.getValue("book")), r.out) {
                        JsonArray(SongbookEntries.songsToGet(SongbookEntries.entries(db, dir, overrides, book(r)), overrides)
                                      .map { JsonPrimitive(it.key) })
                    }
                    "songbooks_listing" -> misses.expect(r.fn, r.extra["song"], r.out) {
                        val song = Songs.byKey(db, text(r.extra.getValue("song")))!!
                        JsonArray(Songbooks.listing(db, books, song).map { JsonPrimitive(it.name) })
                    }
                    "with_capo" -> {
                        val entry = played(r, setting(r.extra["played"]))
                        for (case in r.extra.getValue("cases").jsonArray) {
                            val (given, want) = case.jsonArray
                            misses.expect(r.fn, "${r.extra["entry"]} $given", want) {
                                parts(SongbookEntries.withCapo(entry, setting(given)!!, overrides))
                            }
                        }
                    }
                    "on_instrument" -> {
                        val entry = played(r, setting(r.extra["played"]))
                        for (case in r.extra.getValue("cases").jsonArray) {
                            val (given, keyGiven, capoGiven, want) = case.jsonArray
                            misses.expect(r.fn, "${r.extra["entry"]} ${r.extra["played"]} $given $keyGiven $capoGiven", want) {
                                parts(SongbookEntries.onInstrument(entry, setting(given)!!, keyGiven.jsonPrimitive.boolean,
                                                                   capoGiven.jsonPrimitive.boolean))
                            }
                        }
                    }
                    "set_song_setting" -> set(db, r, misses)
                }
            }
        }
    }

    /** vectors/songbook/tab.jsonl; [guitarFiles] in place of GuitarFiles.of, for a test that checks the marks before
     * it lands. */
    fun tab(misses: Misses, guitarFiles: ((Db) -> List<GuitarFile>)? = null) {
        val overrides = overrides(Corpus.records(ENTRIES))
        withLibrary { db, dir ->
            for (r in Corpus.records(TAB)) {
                when (r.fn) {
                    "caracole.songbook_section.songbooks_data" -> {
                        for ((path, time) in r.extra.getValue("times").jsonObject) {
                            Files.setLastModifiedTime(File(dir, path).toPath(), FileTime.fromMillis(time.jsonPrimitive.long * 1000))
                        }
                        val files = r.kw.getValue("files").jsonArray.map { it.jsonArray[0].jsonPrimitive.content to it.jsonArray[1].jsonPrimitive.content }
                        // A Phase A guard, waiting on: guitar-alphatab (GuitarFiles.of, inbox.guitar_files): until
                        // it lands no song has a Guitar Pro mark, so the marks alone go unchecked.
                        val marks = guitarFiles != null || guitarFilesBuilt(db)
                        misses.expect(r.fn, files, r.out?.let { if (marks) it else withoutMarks(it) }) {
                            val data = if (guitarFiles == null) SongbookSection.data(db, dir, overrides, files)
                                       else SongbookSection.data(db, dir, overrides, files, guitarFiles)
                            if (marks) data else withoutMarks(data)
                        }
                    }
                    "test_conformance_songbook_tab.book_songs" -> {
                        val book = Songbooks.find(Songbooks.all(db), text(r.extra.getValue("book")))!!
                        val songs = SongbookPagesImpl.bookSongs(SongbookEntries.entries(db, dir, overrides, book))
                        val want = r.out!!.jsonObject
                        misses.expect(r.fn, book.name, want.getValue("songs")) { JsonArray(songs.map(::bookSongJson)) }
                        misses.expect(r.fn + " page", book.name, want.getValue("page")) { digests(SongbookPage.build(book.name, songs)) }
                    }
                }
            }
        }
    }

    /** vectors/viewer/songbook_pages.jsonl. */
    fun pages(misses: Misses) {
        for (r in Corpus.records(PAGES)) {
            val name = text(r.args[0])
            val songs = r.args[1].jsonArray.map { bookSong(it.jsonObject) }
            fun string(key: String) = (r.kw[key] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content
            val want = r.out!!.jsonObject
            val html = try {
                SongbookPage.build(name, songs, pdf = string("pdf"), cho = string("cho"), pdfTraditional = string("pdf_traditional"))
            } catch (e: Exception) {
                misses.check(false) { "build_songbook($name): threw $e" }
                continue
            }
            val got = JsonObject(digests(html).jsonObject + ("pieces" to pieces(html)))
            misses.check(got == want) { "build_songbook($name, ${songs.size} songs, ${r.kw}): ${differences(got, want)}" }
        }
    }

    /** songbook.set_song_setting over the record's songbooks `before`. */
    private fun set(db: Db, r: Record, misses: Misses) {
        db.execute("DELETE FROM phone_songbooks")
        for (book in r.extra.getValue("before").jsonArray) {
            SongbookStore.put(db, text(book.jsonObject.getValue("name")), book.jsonObject.getValue("songs").jsonArray)
        }
        val before = values(db)
        val (name, entry, given) = r.args
        val got = try {
            Songbooks.set(db, text(name), text(entry), setting(given)) { s -> Versions.settingProblem(s.key, s.mode, s.capo, s.instrument) }
            JsonObject(mapOf("out" to values(db)))
        } catch (e: SongbookError) {
            misses.check(values(db) == before) { "set_song_setting(${r.args}): a refusal changed the songbooks" }
            JsonObject(mapOf("err" to JsonPrimitive("SongbookError"), "words" to JsonPrimitive(e.message ?: "")))
        }
        val want = if (r.err != null) {
            JsonObject(mapOf("err" to JsonPrimitive(r.err), "words" to (r.extra["words"] ?: JsonNull)))
        } else {
            JsonObject(mapOf("out" to (r.out ?: JsonNull)))
        }
        misses.check(canonical(got) == canonical(want)) { "set_song_setting(${r.args}) answered $got, Python's $want" }
    }

    private fun guitarFilesBuilt(db: Db): Boolean = try {
        GuitarFiles.of(db)
        true
    } catch (e: NotImplementedError) {
        false
    }

    /** The tab's data with every song's Guitar Pro mark taken out. */
    private fun withoutMarks(data: JsonElement): JsonElement {
        val tab = data.jsonObject
        return JsonObject(tab + ("books" to JsonArray(tab.getValue("books").jsonArray.map { book ->
            JsonObject(book.jsonObject + ("set" to JsonArray(book.jsonObject.getValue("set").jsonArray.map {
                JsonObject(it.jsonObject - "guitar")
            })))
        })))
    }

    private fun values(db: Db): JsonArray = JsonArray(Songbooks.all(db).map(Songbooks::value))

    /** A record's songbook.Entry, as the generator's entry_json writes it. */
    fun entryJson(e: Entry): JsonObject {
        val (label, played) = SongbookEntries.wherePlayed(e)
        return JsonObject(linkedMapOf(
            "text" to JsonPrimitive(e.text), "title" to JsonPrimitive(e.title), "artist" to JsonPrimitive(e.artist),
            "song" to text(e.song?.key), "cho" to text(e.cho?.let { Canonical.sha256Hex(it.toByteArray()) }),
            "missing" to text(e.missing), "transpose" to JsonPrimitive(e.transpose),
            "version" to JsonPrimitive(Versions.query(e.version)), "key" to text(e.key), "key_source" to text(e.keySource),
            "setting" to parts(e.setting), "keeps_key" to JsonPrimitive(e.keepsKey), "plays" to text(label),
            "played" to (played?.let { (key, capo) ->
                JsonArray(listOf(key?.let { JsonArray(listOf(JsonPrimitive(it.tonic), JsonPrimitive(it.mode))) } ?: JsonNull,
                                 JsonPrimitive(capo)))
            } ?: JsonNull),
        ))
    }

    private fun bookSongJson(s: BookSong): JsonArray = JsonArray(listOf(
        JsonPrimitive(s.title), JsonPrimitive(s.artist), text(s.cho?.let { Canonical.sha256Hex(it.toByteArray()) }),
        text(s.key), text(s.keySource), JsonPrimitive(s.transpose), text(s.missing), JsonPrimitive(s.id), text(s.start)))

    private fun bookSong(o: JsonObject): BookSong {
        fun string(key: String) = (o[key] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content
        return BookSong(string("title")!!, string("artist")!!, cho = string("cho"), key = string("key"),
                        keySource = string("key_source"), transpose = o.getValue("transpose").jsonPrimitive.int,
                        missing = string("missing"), id = string("id") ?: "", start = string("start"))
    }

    private fun digests(html: String): JsonObject = JsonObject(linkedMapOf(
        "sha256" to JsonPrimitive(sha(html)), "size" to JsonPrimitive(html.toByteArray().size)))

    private const val BLOCK = "<script type=\"application/json\" id=\""

    /** The page cut at its JSON blocks, as the generator's `pieces` cuts it. */
    fun pieces(html: String): JsonArray {
        val out = ArrayList<JsonElement>()
        var at = 0
        while (true) {
            val start = html.indexOf(BLOCK, at)
            if (start < 0) break
            out.add(piece("text", sha(html.substring(at, start)).take(16)))
            val nameEnd = html.indexOf("\">", start)
            val name = html.substring(start + BLOCK.length, nameEnd)
            val end = html.indexOf("</script>", nameEnd)
            val payload = html.substring(nameEnd + 2, end)
            out.add(piece(name, if (name.startsWith("data-")) members(payload) else sha(payload).take(16)))
            at = end
        }
        out.add(piece("text", sha(html.substring(at)).take(16)))
        return JsonArray(out)
    }

    private fun piece(name: String, digest: String) = JsonArray(listOf(JsonPrimitive(name), JsonPrimitive(digest)))

    private fun members(payload: String): String = Json.parseToJsonElement(payload).jsonObject.entries
        .joinToString(" ") { (name, value) -> "$name=${sha(PyJson.dumps(value, compact = true)).take(8)}" }

    private fun differences(got: JsonObject, want: JsonObject): String {
        val g = got["pieces"] as? JsonArray ?: return "no pieces"
        val w = want["pieces"] as? JsonArray ?: return "no pieces"
        if (g.size != w.size) return "${g.size} pieces, Python's ${w.size}"
        val i = g.indices.firstOrNull { g[it] != w[it] } ?: return "sha256 ${got["sha256"]}, Python's ${want["sha256"]}"
        return "piece $i: ${g[i]}, Python's ${w[i]}"
    }

    private fun overrides(records: List<Record>): Overrides {
        val o = records.first { it.fn.endsWith(".overrides") }.out!!.jsonObject
        return Overrides(
            version = o.getValue("version").jsonObject.mapValues { it.value.jsonPrimitive.content },
            transpose = o.getValue("transpose").jsonObject.mapValues { it.value.jsonPrimitive.int },
            ignore = o.getValue("ignore").jsonArray.mapTo(HashSet()) { it.jsonPrimitive.content },
        )
    }

    private fun setting(e: JsonElement?): Setting? {
        val o = e as? JsonObject ?: return null
        fun string(key: String) = (o[key] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content
        return Setting(string("key"), string("mode"), (o["capo"] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.int,
                       string("instrument"))
    }

    /** A setting as the records write it: its parts that say something, in songbook_value's order; null for none. */
    private fun parts(s: Setting?): JsonElement {
        if (s == null) return JsonNull
        val out = LinkedHashMap<String, JsonElement>()
        s.key?.let { out["key"] = JsonPrimitive(it) }
        s.mode?.let { out["mode"] = JsonPrimitive(it) }
        s.capo?.let { out["capo"] = JsonPrimitive(it) }
        s.instrument?.let { out["instrument"] = JsonPrimitive(it) }
        return JsonObject(out)
    }

    private fun canonical(e: JsonElement): String = Canonical.write(e)

    private fun text(e: JsonElement): String = e.jsonPrimitive.content
    private fun text(value: String?): JsonElement = value?.let(::JsonPrimitive) ?: JsonNull

    private fun sha(text: String): String = Canonical.sha256Hex(text.toByteArray())

    /** The fixture library loaded into a fresh database and library folder, in one write. */
    private fun withLibrary(block: (Db, File) -> Unit) {
        val root = Files.createTempDirectory("caracole-songbook-tab").toFile()
        try {
            val library = File(root, "library").also { it.mkdirs() }
            TestDb.fresh(root).use { database ->
                database.writeBlocking { db ->
                    Fixtures.load(db, LIBRARY, library)
                    block(db, library)
                }
            }
        } finally {
            root.deleteRecursively()
        }
    }
}
