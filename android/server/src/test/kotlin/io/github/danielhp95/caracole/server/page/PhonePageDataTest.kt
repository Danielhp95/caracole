package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.testing.replays.CardsReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** The library page's cards from the phone's own library (PhonePageData): library_page.song_cards' over the same
 * library, and the computer's pages of a song the phone holds as it did, from the mirror. */
class PhonePageDataTest {
    @get:Rule val tmp = TemporaryFolder()

    private val dir: File by lazy { tmp.newFolder("phone") }
    private val database: Database by lazy { TestDb.fresh(dir) }
    private val library: File by lazy { File(dir, "library").apply { mkdirs() } }

    @After fun close() = database.close()

    private val now = "2026-11-03T12:00:00Z"

    /** The corpus's full library, in the phone's database and folder. */
    private fun loadFull() {
        val fixture = Corpus.lines(CardsReplay.VECTOR).first { it["library"] == JsonPrimitive("full") && "fixture" in it }
        database.writeBlocking { db -> Fixtures.loadRecords(db, fixture.getValue("fixture").jsonArray.map { it.jsonObject }, library) }
    }

    private fun data(mirror: MirrorPageData = MirrorPageData(null)) =
        PhonePageData(mirror, LibraryStore(library), { PhoneConfig.DEFAULTS }, { Instant.parse(now) })

    @Test
    fun `every card is library_page's of the same library`() {
        val misses = Misses(CardsReplay.VECTOR)
        CardsReplay.replay(misses)
        assertTrue(misses.checked >= 10, "${misses.checked} records checked")
        misses.assertNone()
    }

    @Test
    fun `a card's members are in _song's order, then what is added to it`() {
        loadFull()
        val cards = database.read { db -> data().data(db, now) }.getValue("songs").jsonArray.map { it.jsonObject }
        val hotel = cards.first { it.getValue("title").jsonPrimitive.content == "Hotel California" }
        assertEquals(SONG + listOf("initials", "sites", "progressions"), hotel.keys.toList())
        val review = cards.first { it.getValue("artist").jsonPrimitive.content == "Soda Stereo" }
        assertEquals(SONG + listOf("initials", "candidates", "sites", "progressions"), review.keys.toList())
        val zebra = cards.first { it.getValue("artist").jsonPrimitive.content == "宋冬野" }
        assertEquals(SONG + listOf("initials", "sites", "progressions", "hanzi"), zebra.keys.toList())
        val file = hotel.getValue("files").jsonArray.map { it.jsonObject }.first { it.getValue("name").jsonPrimitive.content == "guitar-1.gp5" }
        assertEquals(listOf("name", "label", "href", "primary", "source", "guitarPage", "download"), file.keys.toList())
    }

    @Test
    fun `the page's data is the mirror's but its songs, every song's card the phone's`() {
        loadFull()
        val made = database.read { db -> data().data(db, now) }
        assertEquals(listOf("generated", "fold", "songs", "icons", "catalogue", "songbooks", "sites"), made.keys.toList())
        val ids = made.getValue("songs").jsonArray.map { it.jsonObject.getValue("id").jsonPrimitive.long }
        assertEquals(database.read { db -> Songs.list(db).map { it.id } }, ids, "Songs.list's order")
    }

    @Test
    fun `a song's card links the computer's pages of it while the phone holds it as the computer did`() {
        loadFull()
        val song = database.read { db -> Songs.list(db).first { it.title == "Over the Rainbow" } }
        val folder = "Israel Kamakawiwo'ole/Over the Rainbow"
        // The phone's folder holds the kept sheet alone; the mirror the computer's viewer of it, at the unit's digest.
        for (name in listOf("sheet.html", "sheet.pdf", "sheet.cho")) File(library, "$folder/$name").delete()
        fun cardWith(digest: String?, recorded: String?): JsonObject {
            database.writeBlocking { db ->
                if (recorded == null) db.kvDelete("render:${song.id}:phone")
                else db.kvSet("render:${song.id}:phone", """{"unit": "$recorded", "build": "b"}""")
            }
            val page = "<!doctype html><title>x</title>".toByteArray()
            val mirror = mirrorWith(tmp.newFolder(), listOf(MirroredFile("$folder/sheet.html", page, "song/${song.key}", digest)))
            return database.read { db -> data(MirrorPageData(mirror)).cards(db, listOf(song)).getValue(song.id) }
        }
        fun primary(card: JsonObject) = card.getValue("files").jsonArray.map { it.jsonObject }
            .first { it.getValue("primary") == JsonPrimitive(true) }.getValue("name").jsonPrimitive.content
        val (d1, d2) = "1".repeat(64) to "2".repeat(64)
        assertEquals("sheet.html", primary(cardWith(d1, d1)), "the mirror's page, at the digest the phone holds")
        assertEquals("sheet.txt", primary(cardWith(d1, d2)), "changed on the phone since: its own sheet")
        assertEquals("sheet.txt", primary(cardWith(null, d1)), "a page of no digest is no page of the unit now")
    }

    @Test
    fun `the mirror's cards of songs the phone hasn't got come after the phone's`() {
        loadFull()
        val theirs = mirroredCard(99, "beck/loser", "Beck", "Loser")
        val mirror = MirrorPageData(mirrorOf(tmp.newFolder(), libraryPage(mirroredData(listOf(theirs)))))
        val songs = database.read { db -> data(mirror).data(db, now) }.getValue("songs").jsonArray.map { it.jsonObject }
        assertEquals(-1L, songs.last().getValue("id").jsonPrimitive.long)
        assertEquals("beck/loser", songs.last().getValue("identity").jsonPrimitive.content)
        assertTrue(songs.dropLast(1).all { it.getValue("id").jsonPrimitive.long > 0 })
        assertEquals(JsonArray(listOf(JsonPrimitive("Beck"))), songs.last().getValue("artists"))
    }

    /** A file the mirror lists, of a unit at a digest (none: a file of no unit's digest). */
    private class MirroredFile(val path: String, val bytes: ByteArray, val unit: String?, val digest: String?)

    /** A mirror in [dir] holding [files] as a sync leaves them, with a start page of no data. */
    private fun mirrorWith(dir: File, files: List<MirroredFile>): io.github.danielhp95.caracole.mirror.Mirror {
        val mirror = io.github.danielhp95.caracole.mirror.Mirror(dir)
        mirror.blobs.mkdirs()
        val start = "<!doctype html><title>caracole</title>".toByteArray()
        val listed = (listOf(MirroredFile("index.html", start, null, null)) + files).withIndex().joinToString(", ") { (i, f) ->
            val sha = sha256(f.bytes)
            File(mirror.blobs, sha).writeBytes(f.bytes)
            val unit = if (f.unit == null) "" else """, "unit": "${f.unit}"""" + (f.digest?.let { """, "digest": "$it"""" } ?: "")
            """{"path": "${f.path}", "url": "/offline/file-$i", "size": ${f.bytes.size}, "sha256": "$sha", """ +
                """"type": "text/html; charset=utf-8", "headers": {}$unit}"""
        }
        mirror.manifestFile.writeText("""{"format": 1, "start": "index.html", "files": [$listed]}""")
        mirror.reload()
        return mirror
    }

    private companion object {
        /** library_page._song's members, in its order (initials, for a title of more than one word, last). */
        val SONG = listOf(
            "id", "artist", "artists", "title", "display", "status", "review", "added", "key", "key_source", "transpose",
            "lyrics", "lyricsFrom", "auto", "files", "instruments", "versions", "autoSheet", "source", "museScore",
            "links", "buy", "youtube", "youtubeSheet", "lacuerda", "lacuerdaVersions", "lacuerdaSheet", "identity",
            "sortArtist", "sortTitle", "artistLetter", "titleLetter", "search",
        )
    }
}
