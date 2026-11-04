package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.SyncReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * overrides.toml and songbooks.toml on the phone (phone.sql's phone_overrides and phone_songbooks): what each store
 * writes, each value its canonical text, and reads back; songbook.name_key against vectors/sync/name_key.jsonl.
 */
class StoresTest {
    @get:Rule val tmp = TemporaryFolder()

    private val database: Database by lazy { TestDb.fresh(tmp.root) }

    @After fun close() = database.close()

    private fun <T> write(block: (Db) -> T): T = database.writeBlocking(block)
    private fun <T> read(block: (Db) -> T): T = database.read(block)

    private fun rows(): List<List<String?>> = read { db ->
        db.query("SELECT tbl, key, written, value FROM phone_overrides ORDER BY tbl, key") {
            listOf(it.text(0), it.text(1), it.text(2), it.text(3))
        }
    }

    /** SyncReplay.nameKey's, which the device runs too. */
    @Test fun aSongbooksNameKeyIsPythons() = Misses("sync/name_key.jsonl").also { SyncReplay.nameKey(it) }.assertNone()

    @Test fun aSongsEntriesAreWrittenAsCanonicalTextAndReadBackInTheTablesOrder() {
        val entries = buildJsonObject {
            put("ignore", true)
            put("version", "key=Gm&capo=0")
            put("harmonica", buildJsonObject { put("harmonica-1.txt", "signs"); put("a", 1.50) })
            put("match", "radiohead/creep")
            put("transpose", -2)
        }
        write { db -> OverridesStore.putSongEntries(db, "radiohead/creep", "Radiohead - Creep", entries) }
        assertEquals(listOf(
            listOf("harmonica", "radiohead/creep", "Radiohead - Creep", """{"a":1.5,"harmonica-1.txt":"signs"}"""),
            listOf("ignore", "radiohead/creep", "Radiohead - Creep", "true"),
            listOf("match", "radiohead/creep", "Radiohead - Creep", "\"radiohead/creep\""),
            listOf("transpose", "radiohead/creep", "Radiohead - Creep", "-2"),
            listOf("version", "radiohead/creep", "Radiohead - Creep", "\"key=Gm&capo=0\""),
        ), rows())
        val read = read { db -> OverridesStore.songEntries(db, "radiohead/creep") }
        assertEquals(listOf("match", "transpose", "version", "harmonica", "ignore"), read.keys.toList())
        assertEquals(Canonical.write(entries), Canonical.write(read))
        assertEquals(JsonObject(emptyMap()), read { db -> OverridesStore.songEntries(db, "radiohead/karma-police") })
    }

    @Test fun anotherSongsEntriesTakeTheirPlaceAndATableAsGivenKeepsHowItWasWritten() {
        write { db ->
            OverridesStore.putSongEntries(db, "a/b", "A - B", buildJsonObject { put("pin", buildJsonArray { add(JsonPrimitive("u")) }); put("transpose", 1) })
            OverridesStore.putSongEntries(db, "c/d", "C - D", buildJsonObject { put("transpose", 3) })
            OverridesStore.putAlias(db, "a", "A", buildJsonArray { add(JsonPrimitive("a-ug")) })
        }
        write { db -> OverridesStore.putSongEntries(db, "a/b", "a - b", buildJsonObject { put("pin", buildJsonArray { add(JsonPrimitive("u")) }); put("ignore", true) }) }
        assertEquals(listOf(
            listOf("alias", "a", "A", "[\"a-ug\"]"),
            listOf("ignore", "a/b", "a - b", "true"),
            listOf("pin", "a/b", "A - B", "[\"u\"]"),
            listOf("transpose", "c/d", "C - D", "3"),
        ), rows())
        // An ignore that is false is none, as put_song_entries reads it.
        write { db -> OverridesStore.putSongEntries(db, "a/b", "A - B", buildJsonObject { put("ignore", false) }) }
        assertEquals(JsonObject(emptyMap()), read { db -> OverridesStore.songEntries(db, "a/b") })
        write { db -> OverridesStore.putSongEntries(db, "c/d", "C - D", null) }
        assertEquals(listOf(listOf("alias", "a", "A", "[\"a-ug\"]")), rows())
    }

    @Test fun aTableNoSongHasIsRefusedAndNothingIsWritten() {
        write { db -> OverridesStore.putSongEntries(db, "a/b", "A - B", buildJsonObject { put("transpose", 1) }) }
        for (table in listOf("alias", "artist_url", "block", "nonsense")) {
            val e = assertFailsWith<IllegalArgumentException> {
                write { db -> OverridesStore.putSongEntries(db, "a/b", "A - B", buildJsonObject { put("pin", JsonArray(emptyList())); put(table, 1) }) }
            }
            assertEquals("'A - B': unknown table(s) $table", e.message)
        }
        assertEquals(listOf(listOf("transpose", "a/b", "A - B", "1")), rows())
    }

    @Test fun anAliasAnArtistsPageAndABlockedTab() {
        write { db ->
            OverridesStore.putAlias(db, "soda", "Soda", buildJsonArray { add(JsonPrimitive("soda-stereo")); add(JsonPrimitive("soda")) })
            OverridesStore.putArtistUrl(db, "宋冬野", buildJsonObject { put("name", "宋冬野"); put("page", "https://www.ultimate-guitar.com/artist/song_dongye_12345") })
            OverridesStore.putBlock(db, 4242, true)
            OverridesStore.putBlock(db, 77, true)
            OverridesStore.putBlock(db, 4242, true)
        }
        assertEquals(listOf(
            listOf("alias", "soda", "Soda", """["soda-stereo","soda"]"""),
            listOf("artist_url", "宋冬野", "宋冬野", "\"https://www.ultimate-guitar.com/artist/song_dongye_12345\""),
            listOf("block", "4242", "4242", "true"),
            listOf("block", "77", "77", "true"),
        ), rows())
        read { db ->
            assertEquals(buildJsonArray { add(JsonPrimitive("soda-stereo")); add(JsonPrimitive("soda")) }, OverridesStore.alias(db, "soda"))
            assertNull(OverridesStore.alias(db, "nobody"))
            assertEquals(buildJsonObject { put("name", "宋冬野"); put("page", "https://www.ultimate-guitar.com/artist/song_dongye_12345") },
                         OverridesStore.artistUrl(db, "宋冬野"))
            assertNull(OverridesStore.artistUrl(db, "soda"))
            assertEquals(listOf(77L, 4242L), OverridesStore.blocks(db))
        }
        write { db ->
            OverridesStore.putAlias(db, "soda", "SODA", buildJsonArray { add(JsonPrimitive("soda-ug")) })
            OverridesStore.putArtistUrl(db, "宋冬野", buildJsonObject { put("name", "Song Dongye"); put("page", "https://u/2") })
            OverridesStore.putBlock(db, 77, false)
            OverridesStore.putBlock(db, 1, false)
        }
        assertEquals(listOf(
            listOf("alias", "soda", "SODA", """["soda-ug"]"""),
            listOf("artist_url", "宋冬野", "Song Dongye", "\"https://u/2\""),
            listOf("block", "4242", "4242", "true"),
        ), rows())
        write { db ->
            OverridesStore.putAlias(db, "soda", "Soda", null)
            OverridesStore.putArtistUrl(db, "宋冬野", null)
            OverridesStore.putBlock(db, 4242, false)
        }
        assertEquals(emptyList(), rows())
        assertEquals(emptyList(), read { db -> OverridesStore.blocks(db) })
        assertFailsWith<IllegalArgumentException> {
            write { db -> OverridesStore.putArtistUrl(db, "x", buildJsonObject { put("name", "x") }) }
        }
    }

    @Test fun aSongbookKeepsItsPlaceAndItsSongsAsCanonicalText() {
        val campfire = buildJsonArray {
            add(buildJsonArray { add(JsonPrimitive("Radiohead - Creep")); add(buildJsonObject { put("key", "G"); put("capo", 2) }) })
            add(buildJsonArray { add(JsonPrimitive("Radiohead - Karma Police")); add(JsonObject(emptyMap())) })
        }
        val one = buildJsonArray { add(buildJsonArray { add(JsonPrimitive("A - B")); add(JsonObject(emptyMap())) }) }
        write { db ->
            SongbookStore.put(db, "Campfire", campfire)
            SongbookStore.put(db, "Old", one)
            SongbookStore.put(db, "Zed", one)
        }
        val stored = read { db -> db.query("SELECT key, name, songs, position FROM phone_songbooks ORDER BY position") { listOf(it.text(0), it.text(1), it.text(2), it.text(3)) } }
        assertEquals(listOf(
            listOf("campfire", "Campfire", """[["Radiohead - Creep",{"capo":2,"key":"G"}],["Radiohead - Karma Police",{}]]""", "0"),
            listOf("old", "Old", """[["A - B",{}]]""", "1"),
            listOf("zed", "Zed", """[["A - B",{}]]""", "2"),
        ), stored)
        // Found by its name in any case, written under the name given, in its place; one taken out leaves the others'.
        write { db ->
            SongbookStore.put(db, "CAMPFIRE", one)
            SongbookStore.put(db, "Old", null)
            SongbookStore.put(db, "New", campfire)
            SongbookStore.put(db, "nobody", null)
        }
        val all = read { db -> SongbookStore.all(db) }
        assertEquals(listOf("campfire" to "CAMPFIRE", "zed" to "Zed", "new" to "New"), all.map { it.key to it.name })
        assertEquals(one, all[0].songs)
        assertEquals(Canonical.write(campfire), Canonical.write(all[2].songs))
        assertTrue(all.all { it.key == SongbookStore.nameKey(it.name) })
    }

    @Test fun aSongbooksSongsKeepTheirSettingsPartsThatSaySomethingAndNothingElse() {
        val given = buildJsonArray {
            add(buildJsonArray {
                add(JsonPrimitive("A - B"))
                add(buildJsonObject { put("mode", "dorian"); put("key", JsonNull); put("capo", 0); put("instrument", JsonNull) })
            })
            add(buildJsonArray { add(JsonPrimitive("C - D")); add(buildJsonObject { put("key", JsonNull) }) })
        }
        write { db -> SongbookStore.put(db, "Campfire", given) }
        val stored = read { db -> db.one("SELECT songs FROM phone_songbooks") { it.text(0) } }
        assertEquals("""[["A - B",{"capo":0,"mode":"dorian"}],["C - D",{}]]""", stored)
        val refused = listOf(
            buildJsonArray { add(JsonPrimitive("A - B")); add(buildJsonObject { put("tempo", 90) }) },
            buildJsonArray { add(JsonPrimitive("A - B")) },
            buildJsonArray { add(JsonPrimitive("A - B")); add(JsonNull) },
            buildJsonArray { add(JsonPrimitive(1)); add(JsonObject(emptyMap())) },
            JsonPrimitive("A - B"),
        )
        for (song in refused) {
            assertFailsWith<IllegalArgumentException>("$song") {
                write { db -> SongbookStore.put(db, "Campfire", JsonArray(listOf(song))) }
            }
        }
        assertEquals(stored, read { db -> db.one("SELECT songs FROM phone_songbooks") { it.text(0) } })
    }

    @Test fun aStoredValueReadsBackAsItsOwnLiterals() {
        write { db -> OverridesStore.putSongEntries(db, "a/b", "A - B", buildJsonObject { put("transpose", JsonPrimitive(-0)); put("harmonica", buildJsonObject { put("x", 1e-7) }) }) }
        val read: Map<String, JsonElement> = read { db -> OverridesStore.songEntries(db, "a/b") }
        assertEquals("""{"harmonica":{"x":0.0000001},"transpose":0}""", Canonical.write(JsonObject(read)))
    }
}
