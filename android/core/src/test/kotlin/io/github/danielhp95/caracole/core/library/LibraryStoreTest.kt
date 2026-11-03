package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.internal.LyricsFiles
import io.github.danielhp95.caracole.core.library.internal.Removal
import io.github.danielhp95.caracole.core.library.internal.Stamps
import io.github.danielhp95.caracole.core.library.internal.Upsert
import io.github.danielhp95.caracole.core.sync.UnitError
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import org.junit.Ignore
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.io.IOException
import java.nio.file.Files
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * LibraryStore and what it rests on, against Python: songs.upsert_song (vectors/library/add.jsonl),
 * removal.remove_song (remove.jsonl), songs.ensure_current_keys (ensure_current_keys.jsonl), peer_sync.lyrics_files
 * (lyrics_files.jsonl) and stamps.parse (stamps.jsonl); and AGENTS.md's invariant that a removed song stays removed
 * until it is asked for again.
 */
class LibraryStoreTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun <T> phone(fixture: String? = null, block: (Db, LibraryStore) -> T): T {
        val dir = tmp.newFolder()
        val library = File(dir, "library")
        return TestDb.fresh(dir).use { database ->
            database.writeBlocking { db ->
                if (fixture != null) Fixtures.load(db, fixture, library)
                block(db, LibraryStore(library))
            }
        }
    }

    private fun Record.case(): String = extra["case"]?.jsonPrimitive?.content ?: args.toString()

    private fun text(e: JsonElement?): String? = if (e == null || e is JsonNull) null else e.jsonPrimitive.content

    private fun long(e: JsonElement?): Long? = if (e == null || e is JsonNull) null else e.jsonPrimitive.longOrNull

    // --- stamps.parse ---------------------------------------------------------------------------------------------

    @Test fun storedTimesReadAsStampsParseReadsThem() {
        val records = Corpus.records("library/stamps.jsonl")
        assertTrue(records.size >= 30)
        for (r in records) {
            val got = Stamps.parse(text(r.args[0]))
            val want = r.out as? JsonObject
            assertEquals(want?.let { text(it["iso"]) to text(it["stamp"]) }, got?.let { it.iso to it.stamp },
                         "stamps.parse(${r.args[0]})")
        }
    }

    @Test fun aTimeThatIsNoneSaysSoInPythonsWords() {
        assertEquals("2026-10-31T00:00:00Z", Stamps.stampOf("2026-10-31T02:00:00+02:00"))
        assertEquals("not a time: 'soon'", assertFailsWith<IllegalArgumentException> { Stamps.stampOf("soon") }.message)
    }

    // --- peer_sync.lyrics_files -----------------------------------------------------------------------------------

    @Test fun lyricsFilesAreWhatATakeWritesFromItsLyricsJson() {
        val records = Corpus.records("library/lyrics_files.jsonl")
        assertTrue(records.size >= 10)
        for (r in records) {
            val got = LyricsFiles.of(text(r.args[0])).mapValues { it.value?.toString(Charsets.UTF_8) }
            val want = r.out!!.jsonObject.mapValues { text(it.value) }
            assertEquals(want, got, "lyrics_files(${r.args[0]})")
            assertEquals(listOf("lyrics.txt", "lyrics.lrc"), got.keys.toList())
        }
    }

    @Test fun lyricsThatCantBeWrittenAsUtf8LeaveTheTake() {
        assertFailsWith<IllegalArgumentException> {
            LyricsFiles.of("{\"plain\": \"a \\ud800 b\", \"raw\": {}}")
        }
    }

    // --- songs.upsert_song ----------------------------------------------------------------------------------------

    @Ignore("Phase B: needs lane keys (Normalize, SafeName) on main")
    @Test fun aSongIsAddedAsUpsertSongAddsIt() {
        val records = Corpus.records("library/add.jsonl")
        assertTrue(records.size >= 15)
        for (r in records) phone { db, _ ->
            val before = r.extra.getValue("before").jsonObject
            for (pair in before.getValue("songs").jsonArray) {
                val (artist, title) = pair.jsonArray.map { it.jsonPrimitive.content }
                Upsert.upsertSong(db, listOf(artist), title, null, null, null, "wanted",
                                  Normalize.identityKey(artist, title), "2026-10-01T00:00:00Z", NOW)
            }
            for (stone in before.getValue("removed").jsonArray.map { it.jsonObject }) {
                db.execute("INSERT INTO removed (key, artist, title, source_ids, removed_at) VALUES (?, ?, ?, ?, ?)",
                           text(stone["key"]), text(stone["artist"]), text(stone["title"]),
                           io.github.danielhp95.caracole.core.json.PyJson.dumps(stone.getValue("source_ids")),
                           text(stone["removed_at"]))
            }
            val kw = r.kw
            val call = {
                Upsert.upsertSong(db, kw.getValue("artists").jsonArray.map { it.jsonPrimitive.content },
                                  text(kw["title"])!!, text(kw["album"]), long(kw["duration_ms"]), text(kw["isrc"]),
                                  text(kw["source"])!!, text(kw["source_id"])!!, text(kw["added_at"])!!, NOW)
            }
            if (r.err != null) {
                assertEquals("ValueError", r.err, r.case())
                assertFailsWith<IllegalArgumentException>(r.case()) { call() }
                return@phone
            }
            val added = call()
            val out = r.out!!.jsonObject
            assertEquals(out["created"]?.jsonPrimitive?.content?.toBoolean(), added.created, r.case())
            val song = Songs.byId(db, added.id)!!
            assertEquals(canonical(out.getValue("song")), canonical(songJson(song)), r.case())
            assertEquals(out.getValue("songs").jsonArray.map { row -> row.jsonArray.map { it.jsonPrimitive.content } },
                         db.query("SELECT key, artist, title FROM songs ORDER BY id") {
                             listOf(it.text(0)!!, it.text(1)!!, it.text(2)!!)
                         }, r.case())
            assertEquals(out.getValue("removed").jsonArray.map { it.jsonPrimitive.content },
                         Songs.removed(db).map { it.key }, r.case())
        }
    }

    @Ignore("Phase B: needs lane keys (Normalize, SafeName) on main")
    @Test fun addIsUpsertSongForOneSongOfThePhone() {
        val record = Corpus.records("library/add.jsonl").first { it.case() == "a new song" }
        phone { db, store ->
            val song = store.add(db, "Radiohead", "Creep", now = NOW)
            assertEquals(canonical(record.out!!.jsonObject.getValue("song")), canonical(songJson(song)))
            assertEquals(song.id, store.add(db, " radiohead", "creep ", now = NOW).id) // found, not doubled
            assertEquals(1, Songs.list(db).size)
        }
    }

    private fun songJson(song: SongRow): JsonObject = JsonObject(linkedMapOf(
        "key" to JsonPrimitive(song.key), "artist" to JsonPrimitive(song.artist), "title" to JsonPrimitive(song.title),
        "artists" to JsonArray(song.artists.map { JsonPrimitive(it) }),
        "album" to (song.album?.let { JsonPrimitive(it) } ?: JsonNull),
        "duration_ms" to (song.durationMs?.let { JsonPrimitive(it) } ?: JsonNull),
        "isrc" to (song.isrc?.let { JsonPrimitive(it) } ?: JsonNull),
        "variant" to (song.variant?.let { JsonPrimitive(it) } ?: JsonNull),
        "source_ids" to Canonical.parse(song.sourceIds), "added_at" to JsonPrimitive(song.addedAt),
        "status" to JsonPrimitive(song.status), "match_candidates" to Canonical.parse(song.matchCandidates),
        "review" to JsonPrimitive(song.review), "ug_dirty" to JsonPrimitive(song.ugDirty),
        "lyrics_status" to JsonPrimitive(song.lyricsStatus),
    ))

    private fun canonical(e: JsonElement): String = Canonical.write(e)

    // --- removal.remove_song --------------------------------------------------------------------------------------

    @Ignore("Phase B: needs lane keys (Normalize, SafeName) on main")
    @Test fun aSongIsRemovedAsRemoveSongRemovesIt() {
        val records = Corpus.records("library/remove.jsonl")
        assertTrue(records.size >= 3)
        for (r in records) phone("library/fixtures/${text(r.extra["fixture"])}.jsonl") { db, store ->
            val key = text(r.args[0])!!
            val song = Songs.byKey(db, key)!!
            val done = Removal.remove(db, store.libraryDir, Removal.plan(db, store.libraryDir, song),
                                      Stamps.stampOf(text(r.kw["now"])!!))
            val out = r.out!!.jsonObject
            val stone = out.getValue("removed").jsonObject
            assertEquals(RemovedRow(text(stone["key"])!!, text(stone["artist"])!!, text(stone["title"])!!,
                                    text(stone["source_ids"])!!, text(stone["removed_at"])!!), done.tombstone, r.case())
            assertEquals(done.tombstone, Songs.removed(db).first { it.key == key })
            fun strings(name: String) = out.getValue(name).jsonArray.map { it.jsonPrimitive.content }
            assertEquals(strings("tombstones"), db.query("SELECT key FROM removed ORDER BY key") { it.text(0)!! })
            assertEquals(strings("songs"), db.query("SELECT key FROM songs ORDER BY id") { it.text(0)!! })
            assertEquals(out.getValue("versions").jsonArray.map { v -> v.jsonArray.map { it.jsonPrimitive.content } },
                         db.query("SELECT song_id, provider, tab_id FROM versions ORDER BY id") {
                             listOf(it.long(0).toString(), it.text(1)!!, it.text(2)!!)
                         }, r.case())
            assertEquals(strings("files"), db.query("SELECT path FROM files ORDER BY id") { it.text(0)!! }, r.case())
            assertEquals(strings("kv"), db.query("SELECT key FROM kv WHERE key != 'sync:id' ORDER BY key") { it.text(0)!! },
                         r.case())
            assertEquals(strings("deleted"), done.deleted.sorted(), r.case())
            assertEquals(out["folder_gone"]?.jsonPrimitive?.content?.toBoolean(), done.folderGone, r.case())
        }
    }

    @Ignore("Phase B: needs lane keys (Normalize, SafeName) on main")
    @Test fun aRemovedSongStaysRemovedUntilItIsAskedForAgainThenComesBackNew() {
        phone("library/fixtures/remove.jsonl") { db, store ->
            val before = Songs.byKey(db, "radiohead/karma-police")!!
            val folder = store.folderOf(before)
            assertTrue(File(folder, "sheet.txt").isFile)
            val stone = store.remove(db, "radiohead/karma-police", NOW)!!
            assertEquals("radiohead/karma-police", stone.key)
            assertNull(Songs.byKey(db, "radiohead/karma-police"))
            assertTrue(Songs.isRemoved(db, "radiohead/karma-police"))
            assertTrue(!folder.exists(), "the folder caracole wrote goes")
            assertNull(store.remove(db, "radiohead/karma-police", NOW), "nothing more to remove")
            // Asked for again: the tombstone goes, and the song comes back as a new one, with nothing of before.
            val back = store.add(db, "Radiohead", "Karma Police", now = "2026-11-01T00:00:00Z")
            assertTrue(!Songs.isRemoved(db, back.key))
            assertTrue(Songs.removed(db).none { it.key == back.key })
            assertEquals("wanted", back.status)
            assertEquals("2026-11-01T00:00:00Z", back.addedAt)
            assertEquals(0, db.one("SELECT COUNT(*) FROM versions WHERE song_id = ?", back.id) { it.long(0) })
        }
    }

    @Ignore("Phase B: needs lane keys (Normalize, SafeName) on main")
    @Test fun aFileTheRemovalDidntWriteStays() {
        phone("library/fixtures/remove.jsonl") { db, store ->
            val song = Songs.byKey(db, "radiohead/karma-police")!!
            val mine = File(store.folderOf(song), "notes.txt").also { it.writeText("mine") }
            store.remove(db, song.key, NOW)
            assertTrue(mine.isFile, "a file caracole didn't write is never deleted")
            assertTrue(!File(store.folderOf(song), "sheet.txt").exists())
        }
    }

    // --- songs.ensure_current_keys --------------------------------------------------------------------------------

    @Ignore("Phase B: needs lane keys (Normalize, SafeName) on main")
    @Test fun songsAndTombstonesAreRekeyedAsEnsureCurrentKeysRekeysThem() {
        val r = Corpus.records("library/ensure_current_keys.jsonl").single()
        phone("library/fixtures/${text(r.extra["fixture"])}.jsonl") { db, store ->
            val out = r.out!!.jsonObject
            assertEquals(long(out["count"])!!.toInt(), store.ensureCurrentKeys(db))
            fun rows(name: String) = out.getValue(name).jsonArray.map { row -> row.jsonArray.map { text(it) } }
            fun cells(sql: String, n: Int) = db.query(sql) { row -> (0 until n).map { row.text(it) } }
            assertEquals(rows("songs"), cells("SELECT id, key, artist, title, artists, album, duration_ms, variant, " +
                                              "source_ids, added_at, status, ug_dirty FROM songs ORDER BY id", 12))
            assertEquals(rows("versions"), cells("SELECT id, song_id, provider, tab_id, pick_rank FROM versions ORDER BY id", 5))
            assertEquals(rows("files"), cells("SELECT id, song_id, version_id, name, path FROM files ORDER BY id", 5))
            assertEquals(rows("removed"), cells("SELECT key, artist, title, source_ids, removed_at FROM removed ORDER BY key", 5))
            assertEquals(rows("kv"), cells("SELECT key, value FROM kv WHERE key LIKE 'wanted:first_seen:%' OR " +
                                           "key = 'songs:key_version' ORDER BY key", 2))
            assertEquals(0, store.ensureCurrentKeys(db), "once")
        }
    }

    // --- the song's folder ----------------------------------------------------------------------------------------

    @Ignore("Phase B: needs lane keys (Normalize, SafeName) on main")
    @Test fun aSongsFileIsAFileOfItsFolderNeverThroughALink() {
        phone { db, store ->
            val song = store.add(db, "Radiohead", "Creep", now = NOW)
            assertEquals(File(store.libraryDir, "Radiohead/Creep"), store.folderOf(song))
            assertEquals(File(store.libraryDir, "Radiohead/Creep/sheet.txt"), store.fileOf(song, "sheet.txt"))
            assertFailsWith<UnitError> { store.fileOf(song, "../sheet.txt") }
            assertFailsWith<UnitError> { store.fileOf(song, ".sheet.txt") }
            val elsewhere = tmp.newFolder()
            store.libraryDir.mkdirs()
            Files.createSymbolicLink(File(store.libraryDir, "Radiohead").toPath(), elsewhere.toPath())
            assertFailsWith<IOException> { store.fileOf(song, "sheet.txt") }
        }
    }

    @Test fun aStoreAddsNoSongWithoutAnArtistOrATimeAndRemovesNoneItHasnt() {
        phone { db, store ->
            assertFailsWith<IllegalArgumentException> { store.add(db, "  ", "Creep", now = NOW) }
            assertFailsWith<IllegalArgumentException> { store.add(db, "Radiohead", "Creep", now = "later") }
            assertEquals(0L, db.one("SELECT COUNT(*) FROM songs") { it.long(0) })
            assertNull(store.remove(db, "nobody/here", NOW))
            assertNull(store.remove(db, "nobody/here", "later"), "a time is read only for a song to remove")
            assertEquals(emptyList(), Songs.removed(db))
            assertNotNull(db.kvGet("sync:id"))
            assertNotEquals("", db.kvGet("phone:schema"))
        }
    }

    companion object {
        const val NOW = "2026-10-31T00:00:00Z"
    }
}
