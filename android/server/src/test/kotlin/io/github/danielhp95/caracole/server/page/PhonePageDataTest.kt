package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.files.LibraryFiles
import io.github.danielhp95.caracole.server.files.PhoneGate
import io.github.danielhp95.caracole.server.testing.replays.CardsReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
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
        val unit = "song/${song.key}"
        // The phone's folder holds the kept sheet alone; the mirror the computer's viewer and PDF of it.
        for (name in listOf("sheet.html", "sheet.pdf", "sheet.cho")) File(library, "$folder/$name").delete()
        val now = database.read { db -> Units.digestOf(db, unit) }!!
        val page = "<!doctype html><title>x</title>".toByteArray()
        fun card(digest: String?): Pair<JsonObject, LibraryFiles> {
            val mirror = mirrorWith(tmp.newFolder(), listOf(MirroredFile("$folder/sheet.html", page, unit, digest),
                                                            MirroredFile("$folder/sheet.pdf", PDF, unit, digest, PDF_TYPE)))
            val files = LibraryFiles(library, mirror, PhoneGate(database), database)
            return database.read { db -> data(MirrorPageData(mirror)).cards(db, listOf(song)).getValue(song.id) } to files
        }
        fun primary(card: JsonObject) = names(card).first { (_, primary) -> primary }.first

        val (listed, files) = card(now)
        assertEquals("sheet.html", primary(listed), "the mirror's page, at the digest the phone holds")
        assertEquals(setOf("sheet.html", "sheet.pdf", "sheet.txt"), names(listed).map { it.first }.toSet())
        for (name in listOf("sheet.html", "sheet.pdf")) {
            assertEquals(200, files.serve("/$folder/$name")?.status, "$name, which the card links, is served")
        }
        val (changed, gated) = card("2".repeat(64))
        assertEquals("sheet.txt", primary(changed), "changed on the phone since: its own sheet")
        assertEquals(listOf("sheet.txt"), names(changed).map { it.first }, "no page of the computer's it won't serve")
        assertEquals(409, gated.serve("/$folder/sheet.html")?.status)
        assertEquals("sheet.txt", primary(card(null).first), "a page of no digest is no page of the unit now")
    }

    @Test
    fun `a page a file's layer keeps of the song is linked as the mirror serves it`() {
        loadFull()
        val song = database.read { db -> Songs.list(db).first { it.title == "Over the Rainbow" } }
        val folder = "Israel Kamakawiwo'ole/Over the Rainbow"
        val unit = "song/${song.key}"
        for (name in listOf("sheet.html", "sheet.pdf", "sheet.cho")) File(library, "$folder/$name").delete()
        val now = database.read { db -> Units.digestOf(db, unit) }!!
        val mirror = mirrorWith(tmp.newFolder(), emptyList())
        val page = "<!doctype html><title>the file's</title>".toByteArray()
        val start = "<!doctype html><title>its library</title>".toByteArray()
        val pages = listOf(MirroredFile("index.html", start, null, null), MirroredFile("$folder/sheet.html", page, unit, now))
        val blobs = pages.associate { sha256(it.bytes) to it.bytes }
        mirror.takeLayer("0123456789abcdef", manifest(pages).toByteArray(), setOf(unit)) { sha ->
            blobs[sha]?.inputStream()
        }
        val card = database.read { db -> data(MirrorPageData(mirror)).cards(db, listOf(song)).getValue(song.id) }
        assertEquals("sheet.html", names(card).first { it.second }.first)
        assertEquals(200, LibraryFiles(library, mirror, PhoneGate(database), database).serve("/$folder/sheet.html")?.status)
    }

    @Test(timeout = 120_000)
    fun `a page built inside a read reads nothing more through the database, one reader enough`() {
        val one = Database(File(dir, "one.sqlite"), readers = 1)
        try {
            val fixture = Corpus.lines(CardsReplay.VECTOR).first { it["library"] == JsonPrimitive("full") && "fixture" in it }
            one.writeBlocking { db -> Fixtures.loadRecords(db, fixture.getValue("fixture").jsonArray.map { it.jsonObject }, library) }
            val song = one.read { db -> Songs.list(db).first { it.title == "Over the Rainbow" } }
            val unit = "song/${song.key}"
            val digest = one.read { db -> Units.digestOf(db, unit) }
            val folder = "Israel Kamakawiwo'ole/Over the Rainbow"
            val mirror = mirrorWith(tmp.newFolder(), listOf(MirroredFile("$folder/sheet.html", PDF, unit, digest)))
            val cards = PhonePageData(MirrorPageData(mirror), LibraryStore(library))  // its settings PhoneConfig.read's
            val made = one.read { db -> cards.data(db, now) }
            assertTrue(made.getValue("songs").jsonArray.isNotEmpty())
            one.read { db -> cards.cards(db, listOf(song)) }
            one.read { db -> cards.results(db, listOf(song)) }
        } finally {
            one.close()
        }
    }

    @Test
    fun `a song the computer listed as the phone holds it says what no sync carries as the computer's card does`() {
        loadFull()
        val computer = Corpus.lines(CardsReplay.VECTOR).first {
            it["fn"] == JsonPrimitive(CardsReplay.SONG_CARDS) && it["library"] == JsonPrimitive("full") &&
                it["now"] == JsonPrimitive(now) && it["songs"] == JsonNull &&
                it.getValue("config").jsonObject.getValue("off").jsonArray.isEmpty()
        }.getValue("out").jsonArray.map { it.jsonObject }
        // A sync carries none of these: the phone that took the songs has none of them.
        database.writeBlocking { db ->
            db.execute("DELETE FROM kv WHERE key GLOB 'render:export:*' OR key GLOB 'render:[0-9]*' AND key NOT GLOB " +
                           "'render:*:*' OR key GLOB '*tabs:checked:*' OR key GLOB 'ug:artist_page_checked:*' OR " +
                           "key GLOB 'ug:blocked:*'")
            db.execute("UPDATE songs SET audio_path = NULL")
        }
        val songs = database.read { db -> Songs.list(db) }
        fun made(digests: (String) -> String?): Map<Long, JsonObject> {
            val listed = computer.flatMap { card ->
                val song = songs.first { it.key == card.getValue("identity").jsonPrimitive.content }
                val unit = "song/${song.key}"
                val (artist, title) = SafeName.songFolder(song.artist, song.title)
                card.getValue("files").jsonArray.map { file ->
                    val name = file.jsonObject.getValue("name").jsonPrimitive.content
                    val bytes = File(library, "$artist/$title/$name").takeIf { it.isFile }?.readBytes() ?: PDF
                    MirroredFile("$artist/$title/$name", bytes, unit, digests(unit), if (name.endsWith(".pdf")) PDF_TYPE else HTML)
                }
            }
            val mirror = mirrorWith(tmp.newFolder(), listed, libraryPage(mirroredData(computer)))
            return database.read { db -> data(MirrorPageData(mirror)).cards(db, songs) }
        }
        val held = made { unit -> database.read { db -> Units.digestOf(db, unit) } }
        val withFiles = computer.filter { it.getValue("files").jsonArray.isNotEmpty() }
        assertTrue(withFiles.size >= 6)
        for (card in withFiles) {
            assertEquals(card, held.getValue(card.getValue("id").jsonPrimitive.long), "${card["title"]}: the computer's")
        }
        // What came of the computer's card: Queen's PDF moved 5 up, Hotel California's PDF exports.
        val queen = computer.first { it.getValue("artist").jsonPrimitive.content == "Queen" }
        assertEquals(JsonPrimitive(5), queen.getValue("transpose"))
        assertTrue(withFiles.any { c -> c.getValue("files").jsonArray.any { "version" in it.jsonObject } })
        // Changed on the phone since the computer listed it: the phone's own card, its PDF moved by nothing it knows.
        val moved = made { "f".repeat(64) }
        assertEquals(JsonPrimitive(0), moved.getValue(queen.getValue("id").jsonPrimitive.long).getValue("transpose"))
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

    /** Each file a card lists, by name, with whether its line opens it. */
    private fun names(card: JsonObject): List<Pair<String, Boolean>> = card.getValue("files").jsonArray.map {
        val f = it.jsonObject
        f.getValue("name").jsonPrimitive.content to (f.getValue("primary") == JsonPrimitive(true))
    }

    /** A file the mirror lists, of a unit at a digest (none: a file of no unit's digest), of a type. */
    private class MirroredFile(val path: String, val bytes: ByteArray, val unit: String?, val digest: String?,
                               val type: String = HTML)

    /** A list of pages as `GET /api/offline` gives it, [files] in it, the first its start page. */
    private fun manifest(files: List<MirroredFile>): String = files.withIndex().joinToString(", ",
        """{"format": 1, "start": "${files.first().path}", "files": [""", "]}") { (i, f) ->
        val unit = if (f.unit == null) "" else """, "unit": ${JsonPrimitive(f.unit)}""" +
            (f.digest?.let { """, "digest": "$it"""" } ?: "")
        """{"path": ${JsonPrimitive(f.path)}, "url": "/offline/file-$i", "size": ${f.bytes.size}, """ +
            """"sha256": "${sha256(f.bytes)}", "type": "${f.type}", "headers": {}$unit}"""
    }

    /** A mirror in [dir] holding [files] as a sync leaves them, with [start] its library page. */
    private fun mirrorWith(dir: File, files: List<MirroredFile>,
                           start: ByteArray = "<!doctype html><title>caracole</title>".toByteArray()):
        io.github.danielhp95.caracole.mirror.Mirror {
        val mirror = io.github.danielhp95.caracole.mirror.Mirror(dir)
        mirror.blobs.mkdirs()
        val all = listOf(MirroredFile("index.html", start, null, null)) + files
        for (f in all) File(mirror.blobs, sha256(f.bytes)).writeBytes(f.bytes)
        mirror.manifestFile.writeText(manifest(all))
        mirror.reload()
        return mirror
    }

    private companion object {
        const val HTML = "text/html; charset=utf-8"
        const val PDF_TYPE = "application/pdf"
        val PDF = "%PDF-1.4 x".toByteArray()

        /** library_page._song's members, in its order (initials, for a title of more than one word, last). */
        val SONG = listOf(
            "id", "artist", "artists", "title", "display", "status", "review", "added", "key", "key_source", "transpose",
            "lyrics", "lyricsFrom", "auto", "files", "instruments", "versions", "autoSheet", "source", "museScore",
            "links", "buy", "youtube", "youtubeSheet", "lacuerda", "lacuerdaVersions", "lacuerdaSheet", "identity",
            "sortArtist", "sortTitle", "artistLetter", "titleLetter", "search",
        )
    }
}
