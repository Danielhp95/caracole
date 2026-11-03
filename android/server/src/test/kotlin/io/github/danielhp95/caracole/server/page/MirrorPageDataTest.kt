package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** The computer's cards, from the mirror's library page, made the phone's (MirrorPageData). */
class MirrorPageDataTest {
    @get:Rule val tmp = TemporaryFolder()

    private val database: Database by lazy { TestDb.fresh(tmp.newFolder("db")) }

    @After fun close() = database.close()

    private val now = "2026-11-03T12:00:00Z"

    // The computer's library: three songs, its ids its own.
    private val estopa = mirroredCard(10, "estopa/tu-calorro", "Estopa", "Tu Calorro")
    private val oasis = mirroredCard(11, "oasis/wonderwall", "Oasis", "Wonderwall", "review" to true)
    private val creep = mirroredCard(12, "radiohead/creep", "Radiohead", "Creep", "status" to "wanted")

    private fun mirrored(vararg sets: JsonObject) =
        MirrorPageData(mirrorOf(tmp.newFolder(), libraryPage(mirroredData(listOf(estopa, oasis, creep), sets.toList()))))

    private fun songsOf(data: JsonObject) = data.getValue("songs").jsonArray.map { it.jsonObject }

    private fun read(data: MirrorPageData) = database.read { db -> data.data(db, now) }

    @Test
    fun `each card is re-identified to the phone's song of its identity, the others given negative ids`() {
        val wonderwall = addSong(database, "oasis/wonderwall", "Oasis", "Wonderwall", review = true)
        val calorro = addSong(database, "estopa/tu-calorro", "Estopa", "Tu Calorro")
        val songs = songsOf(read(mirrored()))
        assertEquals(listOf("estopa/tu-calorro", "oasis/wonderwall", "radiohead/creep"),
                     songs.map { it.getValue("identity").jsonPrimitive.content }, "the computer's cards, in its order")
        assertEquals(listOf(calorro, wonderwall, -1L), songs.map { it.getValue("id").jsonPrimitive.long })
        for ((made, card) in songs.zip(listOf(estopa, oasis, creep))) {
            assertEquals(card.keys.toList(), made.keys.toList(), "every field in its place")
            assertEquals(JsonObject(card - "id" - "status" - "review"), JsonObject(made - "id" - "status" - "review"))
        }
    }

    @Test
    fun `a card of a song the phone removed is left out until a sync settles it`() {
        addSong(database, "radiohead/creep", "Radiohead", "Creep")
        removeSong(database, "estopa/tu-calorro", "Estopa", "Tu Calorro")
        val songs = songsOf(read(mirrored()))
        assertEquals(listOf("oasis/wonderwall", "radiohead/creep"), songs.map { it.getValue("identity").jsonPrimitive.content })
        assertEquals(-1L, songs[0].getValue("id").jsonPrimitive.long, "the negative ids count the cards kept")
        database.read { db -> assertTrue(Songs.isRemoved(db, "estopa/tu-calorro")) }
    }

    @Test
    fun `a song's status and review are the phone's, ignored where the phone's overrides ignore it`() {
        addSong(database, "estopa/tu-calorro", "Estopa", "Tu Calorro", status = "wanted", review = true)
        addSong(database, "oasis/wonderwall", "Oasis", "Wonderwall", status = "found", review = true)
        database.writeBlocking { db ->
            db.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES ('ignore', ?, ?, 'true')",
                       "oasis/wonderwall", "Oasis - Wonderwall")
        }
        val songs = songsOf(read(mirrored())).associateBy { it.getValue("identity").jsonPrimitive.content }
        val calorro = songs.getValue("estopa/tu-calorro")
        assertEquals("wanted" to true, calorro.getValue("status").jsonPrimitive.content to calorro.getValue("review").jsonPrimitive.boolean)
        val wonderwall = songs.getValue("oasis/wonderwall")
        assertEquals("ignored" to false,
                     wonderwall.getValue("status").jsonPrimitive.content to wonderwall.getValue("review").jsonPrimitive.boolean)
        assertEquals(JsonObject(creep - "id"), JsonObject(songs.getValue("radiohead/creep") - "id"),
                     "a card of no phone song keeps the computer's status")
    }

    @Test
    fun `what isn't a song's is taken as the computer's page has it, in its order`() {
        addSong(database, "estopa/tu-calorro", "Estopa", "Tu Calorro")
        val page = mirroredData(listOf(estopa, oasis, creep))
        val data = read(mirrored())
        assertEquals(page.keys.toList(), data.keys.toList())
        for (name in listOf("generated", "fold", "icons", "catalogue", "sites")) assertEquals(page.getValue(name), data.getValue(name), name)
    }

    @Test
    fun `a songbook's set names its songs by the page's ids, none for one left out or never there`() {
        val calorro = addSong(database, "estopa/tu-calorro", "Estopa", "Tu Calorro")
        removeSong(database, "oasis/wonderwall", "Oasis", "Wonderwall")
        val sets = arrayOf(
            obj("n" to 1, "entry" to "Estopa - Tu Calorro", "key" to "estopa/tu-calorro", "id" to 10, "missing" to false),
            obj("n" to 2, "entry" to "Radiohead - Creep", "key" to "radiohead/creep", "id" to 12, "missing" to false),
            obj("n" to 3, "entry" to "Oasis - Wonderwall", "key" to "oasis/wonderwall", "id" to 11, "missing" to false),
            obj("n" to 4, "entry" to "Nobody - Nothing", "key" to "nobody/nothing", "id" to null, "missing" to true),
        )
        val books = read(mirrored(*sets)).getValue("songbooks").jsonObject
        assertEquals(JsonNull, books.getValue("error"))
        val set = books.getValue("books").jsonArray.single().jsonObject.getValue("set").jsonArray.map { it.jsonObject }
        assertEquals(listOf(calorro.toString(), "-1", "null", "null"), set.map { it.getValue("id").toString() })
        for ((made, entry) in set.zip(sets)) assertEquals(JsonObject(entry - "id"), JsonObject(made - "id"))
    }

    @Test
    fun `cards are each phone song's card under its id`() {
        val calorro = addSong(database, "estopa/tu-calorro", "Estopa", "Tu Calorro", status = "wanted")
        val data = mirrored()
        val cards = database.read { db -> data.cards(db, listOfNotNull(Songs.byId(db, calorro))) }
        assertEquals(setOf(calorro), cards.keys)
        val card = cards.getValue(calorro)
        assertEquals(calorro, card.getValue("id").jsonPrimitive.long)
        assertEquals("wanted", card.getValue("status").jsonPrimitive.content)
        assertEquals(JsonObject(estopa - "id" - "status"), JsonObject(card - "id" - "status"))
    }

    @Test
    fun `the mirror's page is read once while it is the same`() {
        addSong(database, "estopa/tu-calorro", "Estopa", "Tu Calorro")
        val data = mirrored()
        val first = read(data)
        assertEquals(first, read(data))
        val blob = data.mirror!!.blobs.listFiles()!!.single()
        blob.writeBytes(libraryPage(mirroredData(emptyList())))  // changed under it, its entry the same: still the one read
        assertEquals(first, read(data))
    }

    @Test
    fun `a page whose data block can't be read is no data`() {
        for (page in listOf("<html>no block</html>", "<script type=\"application/json\" id=\"songs\">{not json</script>",
                            "<script type=\"application/json\" id=\"songs\">[1, 2]</script>",
                            "<script type=\"application/json\" id=\"songs\">{\"songs\": []}")) {
            assertNull(MirrorPageData.dataBlock(page.toByteArray()), page)
        }
        assertNull(MirrorPageData.dataBlock(byteArrayOf(0xff.toByte(), 0xfe.toByte())))
        val read = MirrorPageData.dataBlock(libraryPage(obj("songs" to listOf(obj("title" to "</script><!--")))))
        assertEquals("</script><!--", read!!.getValue("songs").jsonArray.single().jsonObject.getValue("title").jsonPrimitive.content)
    }

    // --- what needs normalize.py's folds (lane keys) ----------------------------------------------------------

    @Test
    fun `a song only the phone has gets a minimal card, after the computer's`() {
        waitingOnKeys()
        val mine = addSong(database, "sigur-ros/hoppipolla", "Sigur Rós", "Hoppípolla (Live)", status = "wanted",
                           added = "2026-11-02T00:00:00Z")
        database.writeBlocking { db ->
            db.execute("INSERT INTO versions (provider, tab_id, song_id, slot, kind, url, fetched_at) VALUES ('ug', '1', ?, 'sheet', 'chords', 'u', ?)",
                       mine, now)
            val version = db.lastRowid()
            for ((name, rank) in listOf("tab.txt" to 2, "sheet.txt" to 1, "guitar-10.gp5" to 4, "guitar-2.gp5" to 3, "notes.md" to 5)) {
                db.execute("INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           version, mine, name, "Sigur Rós/Hoppípolla/$name", "0".repeat(64), rank, now)
            }
        }
        val songs = songsOf(read(mirrored()))
        assertEquals(4, songs.size)
        val card = songs.last()
        assertEquals(mine, card.getValue("id").jsonPrimitive.long)
        assertEquals(listOf("id", "artist", "artists", "title", "display", "status", "review", "added", "key", "files", "identity",
                            "sortArtist", "sortTitle", "artistLetter", "titleLetter", "search", "sites"), card.keys.toList())
        assertEquals("Hoppípolla", card.getValue("title").jsonPrimitive.content)
        assertEquals("sigur-ros/hoppipolla", card.getValue("identity").jsonPrimitive.content)
        assertEquals(JsonNull, card.getValue("key"))
        assertEquals("S" to "H", card.getValue("artistLetter").jsonPrimitive.content to card.getValue("titleLetter").jsonPrimitive.content)
        assertEquals(listOf("sheet.txt", "guitar-2.gp5", "guitar-10.gp5", "tab.txt"),
                     card.getValue("files").jsonArray.map { it.jsonObject.getValue("name").jsonPrimitive.content }, "the line's order")
        assertEquals(obj("name" to "sheet.txt", "label" to "Sheet text", "href" to "Sigur%20R%C3%B3s/Hopp%C3%ADpolla/sheet.txt"),
                     card.getValue("files").jsonArray.first())
        assertEquals("Guitar Pro 2", card.getValue("files").jsonArray[1].jsonObject.getValue("label").jsonPrimitive.content)
    }

    @Test
    fun `with no mirror the page is an empty library, and the phone's songs`() {
        waitingOnKeys()
        val data = database.read { db -> MirrorPageData(null).data(db, now) }
        assertEquals(listOf("generated", "fold", "songs", "icons", "catalogue", "songbooks", "sites"), data.keys.toList())
        assertEquals(now, data.getValue("generated").jsonPrimitive.content)
        assertEquals(MirrorPageData.TRANSLITERATED.length, data.getValue("fold").jsonObject.size)
        assertEquals("o", data.getValue("fold").jsonObject.getValue("ø").jsonPrimitive.content)
        assertEquals(0, data.getValue("songs").jsonArray.size)
        addSong(database, "estopa/tu-calorro", "Estopa", "Tu Calorro")
        val mirrorless = File(tmp.root, "never-synced")
        val songs = database.read { db -> MirrorPageData(io.github.danielhp95.caracole.mirror.Mirror(mirrorless)).data(db, now) }
        assertEquals(listOf("estopa/tu-calorro"), songsOf(songs).map { it.getValue("identity").jsonPrimitive.content })
    }

    @Test
    fun `a phone song's card holds what library_page writes of it`() {
        waitingOnKeys()
        val mine = addSong(database, "song-dongye/banma-banma", "宋冬野", "斑马斑马")
        val card = database.read { db -> MirrorPageData(null).cards(db, listOfNotNull(Songs.byId(db, mine))) }.getValue(mine)
        assertEquals(CardText.sortKey("宋冬野"), card.getValue("sortArtist").jsonPrimitive.content)
        assertEquals("bmbm", card.getValue("initials").jsonPrimitive.content)
        assertEquals(CardText.haystack(listOf("宋冬野", "宋冬野", "斑马斑马", "宋冬野 - 斑马斑马")), card.getValue("search").jsonPrimitive.content)
        assertEquals(0, card.getValue("sites").jsonArray.size)
    }
}
