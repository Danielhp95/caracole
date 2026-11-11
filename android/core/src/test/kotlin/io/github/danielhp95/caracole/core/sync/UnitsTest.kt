package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.OverridesStore
import io.github.danielhp95.caracole.core.library.SongbookStore
import io.github.danielhp95.caracole.core.sync.internal.units.Documents
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.SyncReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlin.test.fail

/**
 * peer_sync's units on the phone against vectors/sync (tests/test_conformance_sync.py): over each fixture replayed
 * into a fresh database, every unit library_state lists, with its label, its value and its digest (values.jsonl);
 * every unit's document, and value_of_document of each (documents.jsonl): SyncReplay's loops, which the device runs
 * too. A value compares by its canonical text, the digest's own; a document as json.dumps(sort_keys=True) writes it,
 * so a REAL cell is Python's float to the digit.
 */
class UnitsTest {
    @get:Rule val tmp = TemporaryFolder()

    private val opened = HashMap<String, Pair<Database, File>>()

    @After fun close() = opened.values.forEach { it.first.close() }

    @Test fun whatAUgRawRecordIsHashedWithoutIsWhatItsKeptJsonLeavesOut() {
        // A unit hashes each kept file's bytes: the version's JSON kept beside a UG sheet (Slots.keepText) leaves out
        // what the raw record's hash does, or a tab read on two days would differ still.
        assertEquals(io.github.danielhp95.caracole.core.ug.UgFetch.KEPT_WITHOUT, Units.VOLATILE_RAW.getValue("ug"))
    }

    /** The fixture [name] (sync/fixtures/<name>.jsonl) in a database of its own, and its library folder. */
    private fun fixture(name: String): Pair<Database, File> = opened.getOrPut(name) {
        val dir = tmp.newFolder(name)
        val library = File(dir, "library").apply { mkdirs() }
        val database = TestDb.fresh(dir)
        database.writeBlocking { Fixtures.load(it, "sync/fixtures/$name.jsonl", library) }
        database to library
    }

    private fun <T> reading(name: String, block: (io.github.danielhp95.caracole.core.db.Db, File) -> T): T {
        val (database, library) = fixture(name)
        return database.read { block(it, library) }
    }

    private fun canonical(e: JsonElement?): String? = e?.let { Canonical.write(it) }

    private fun python(e: JsonElement?): String? = e?.let { PyJson.dumps(it, sortKeys = true) }

    private fun nullable(e: JsonElement?): JsonElement? = e?.takeUnless { it is JsonNull }

    private fun text(e: JsonElement): String = e.jsonPrimitive.content

    /** Every record's mismatch, so one run names them all. */
    private fun check(records: List<Record>, compare: (Record) -> String?) {
        assertTrue(records.isNotEmpty(), "no records to check")
        val wrong = records.mapNotNull { record ->
            try {
                compare(record)
            } catch (e: Throwable) {
                "${record.args}: ${e::class.simpleName}: ${e.message}"
            }
        }
        if (wrong.isNotEmpty()) fail("${wrong.size} of ${records.size} records differ:\n" + wrong.take(20).joinToString("\n"))
    }

    private fun differs(record: Record, what: String, expected: Any?, actual: Any?): String? =
        if (expected == actual) null else "${record.args} ($what): Python $expected, Kotlin $actual"

    private val values get() = Corpus.records(VALUES)
    private val documents get() = Corpus.records(DOCUMENTS)

    private val fixtures: List<String> get() = SyncReplay.fixtures()

    private fun replayed(name: String, replay: (Misses) -> Unit) = Misses(name).also(replay).assertNone()

    @Test fun everyRecordIsOfAFunctionThePhonePorts() {
        assertEquals(setOf(UNIT_VALUE), values.map { it.fn }.toSet())
        assertEquals(setOf(UNIT_DOCUMENT, VALUE_OF_DOCUMENT), documents.map { it.fn }.toSet())
        // dense fills every column a value reads (match, review, album, variant, gone, pick, coverage, a REAL score),
        // which the others leave at their defaults: a corpus without it couldn't tell those columns apart.
        assertTrue(listOf("empty", "plain", "rich", "dense").all { it in fixtures }, "the fixtures: $fixtures")
    }

    @Test fun aLibrarysUnitsAreTheOnesPythonLists() = replayed("the fixtures' units", SyncReplay::libraryState)

    @Test fun eachUnitsValueLabelAndDigestAreItsOwn() = replayed(VALUES, SyncReplay::values)

    @Test fun aUnitTheLibraryHasntGotHasNoValueAndNoDigest() {
        for (name in fixtures) {
            reading(name) { db, _ ->
                for (id in listOf("song/nobody/here", "removed/nobody/here", "songbook/nobody", "alias/nobody",
                                  "artist_url/nobody", "block/1", "block/x", "block/", "block/04242", "block/+1",
                                  "block/-1", "block/1 ", "nonsense/x", "song")) {
                    assertNull(Units.value(db, id), "$name: $id")
                    assertNull(Units.digestOf(db, id), "$name: $id")
                }
            }
        }
    }

    @Test fun eachUnitsDocumentIsPythons() = replayed(DOCUMENTS, SyncReplay::documents)

    @Test fun aDocumentReadsBackAsPythonReadsIt() = replayed("$DOCUMENTS value_of_document", SyncReplay::valueOfDocument)

    @Test fun theDigestsATakeComparedAreThePhones() = replayed(TAKE, SyncReplay::takeDigests)

    @Test fun everyUnitsDocumentReadsBackAsItsValue() = replayed("the fixtures' documents", SyncReplay::documentsAsValues)

    @Test fun aDocumentThatIsntOfItsKindIsAUnitError() {
        val refused = listOf(
            "nonsense/x" to buildJsonObject { },
            "removed/a/b" to buildJsonObject { put("artist", "a") },
            "removed/a/b" to buildJsonObject { put("artist", "a"); put("title", JsonNull) },
            "songbook/x" to buildJsonObject { put("name", "x"); put("songs", buildJsonArray { add(buildJsonArray { add(JsonPrimitive("a")) }) }) },
            "songbook/x" to buildJsonObject { put("songs", JsonArray(emptyList())) },
            "alias/x" to buildJsonObject { },
            "artist_url/x" to buildJsonObject { put("name", "x"); put("page", 1) },
            "block/1" to buildJsonObject { put("tab", 1.0) },
            "block/1" to buildJsonObject { put("tab", JsonNull) },
            "song/a/b" to song { remove("overrides") },
            "song/a/b" to song { put("song", JsonArray(emptyList())) },
            "song/a/b" to song { put("versions", JsonPrimitive(3)) },
            "song/a/b" to song { put("versions", JsonPrimitive("v")) },
            "song/a/b" to song { put("versions", buildJsonObject { put("v", 1) }) },
            "song/a/b" to song { put("versions", buildJsonArray { add(JsonArray(emptyList())) }) },
            "song/a/b" to song { put("versions", buildJsonArray { add(version { put("raw", JsonPrimitive(1)) }) }) },
            "song/a/b" to song { put("versions", buildJsonArray { add(version { remove("url") }) }) },
            "song/a/b" to song { put("versions", buildJsonArray { add(version { put("files", buildJsonArray { add(buildJsonObject { put("name", 1); put("sha256", "s") }) }) }) }) },
            "song/a/b" to song { put("versions", buildJsonArray { add(version { put("files", buildJsonArray { add(buildJsonObject { put("name", "n") }) }) }) }) },
            "song/a/b" to song { put("song", record { put("lyrics_json", JsonPrimitive(1)) }) },
            "song/a/b" to song { put("song", record { remove("review") }) },
        )
        for ((id, doc) in refused) assertFailsWith<UnitError>("$id $doc") { Units.valueOfDocument(id, doc) }
        assertFailsWith<UnitError> { Documents.valueOf("removed/a/b", JsonPrimitive("x")) }
        assertFailsWith<UnitError> { Documents.valueOf("song/a/b", JsonArray(emptyList())) }
    }

    @Test fun aSongsDocumentReadsAsPythonsDoesWhereItIsLoose() {
        // Python iterates an empty object or an empty text of versions as no version, and reads "gone" and
        // "review" by their truth.
        for (versions in listOf(JsonObject(emptyMap()), JsonPrimitive(""), JsonArray(emptyList()))) {
            val value = Units.valueOfDocument("song/a/b", song { put("versions", versions) })!!.jsonObject
            assertEquals(JsonArray(emptyList()), value["versions"])
        }
        val value = Units.valueOfDocument("song/a/b", song {
            put("song", record { put("review", JsonPrimitive("no")) })
            put("versions", buildJsonArray {
                add(version { put("gone", JsonPrimitive(0.0)); put("files", buildJsonArray {
                    add(buildJsonObject { put("name", "z.txt"); put("sha256", "1") })
                    add(buildJsonObject { put("name", "a.txt"); put("sha256", 2) })
                }) })
                add(version { put("tab_id", JsonPrimitive("7")); put("gone", buildJsonArray { add(JsonNull) }); put("raw", JsonNull) })
            })
        })!!.jsonObject
        assertEquals(JsonPrimitive(true), value["review"])
        val read = value.getValue("versions") as JsonArray
        assertEquals(listOf(JsonPrimitive(false), JsonPrimitive(true)), read.map { it.jsonObject["gone"] })
        assertEquals(JsonNull, read[1].jsonObject["raw"])
        assertEquals(Canonical.hashStoredJson("{}"), read[0].jsonObject.getValue("raw").jsonPrimitive.content)
        assertEquals("""{"a.txt":2,"z.txt":"1"}""", Canonical.write(value.getValue("files")))
        assertEquals(listOf("a.txt", "z.txt"), value.getValue("files").jsonObject.keys.toList())
    }

    @Test fun aBlockedTabIsFoundOnlyByItsIdAsTheStateWritesIt() {
        TestDb.fresh(tmp.newFolder("blocks")).use { database ->
            database.writeBlocking { OverridesStore.putBlock(it, 77, true); OverridesStore.putBlock(it, 0, true) }
            database.read { db ->
                assertEquals(mapOf("block/0" to "blocked tab 0", "block/77" to "blocked tab 77"),
                             Units.libraryState(db).mapValues { it.value.label })
                assertEquals(JsonPrimitive(true), Units.value(db, "block/77"))
                assertEquals(buildJsonObject { put("tab", 77) }, Units.document(db, tmp.root, "block/77"))
                assertEquals(buildJsonObject { put("tab", 0) }, Units.document(db, tmp.root, "block/0"))
                // peer_sync.tab_of: ASCII digits with no leading zero, else no unit at all.
                for (id in listOf("block/077", "block/00", "block/+77", "block/-77", "block/ 77", "block/77 ", "block/٧٧",
                                  "block/７７", "block/99999999999999999999999")) {
                    assertNull(Units.value(db, id), id)
                    assertNull(Units.document(db, tmp.root, id), id)
                }
            }
        }
        assertEquals(listOf(0L, 7L, 4242L, null, null, null, null, null, null),
                     listOf("0", "7", "4242", "", "07", "+7", "٧", "7 ", "99999999999999999999999").map(Documents::tabOf))
    }

    @Test fun aSongsVersionsComeByProviderThenTabInSqlitesOrder() {
        val dir = tmp.newFolder("providers")
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { db ->
                Fixtures.load(db, "sync/fixtures/rich.jsonl", File(dir, "library").apply { mkdirs() })
                // rich's 宋冬野 - 斑马斑马 has UG's tabs 99 and 101; another site's tabs beside them.
                for ((provider, tab) in listOf("lacuerda" to "zz", "gtptabs" to "5", "lacuerda" to "Z")) {
                    db.execute("INSERT INTO versions (provider, tab_id, song_id, slot, kind, url, fetched_at) " +
                                   "VALUES (?, ?, 3, 'sheet', 'chords', ?, '2026-10-31T00:00:00Z')", provider, tab, "https://u/$tab")
                }
            }
            database.read { db ->
                val id = "song/宋冬野/斑马斑马"
                val versions = Units.value(db, id)!!.jsonObject.getValue("versions") as JsonArray
                assertEquals(listOf("gtptabs/5", "lacuerda/Z", "lacuerda/zz", "ug/101", "ug/99"),
                             versions.map { v -> v.jsonObject.let { "${text(it.getValue("provider"))}/${text(it.getValue("tab"))}" } })
                val document = Units.document(db, tmp.root, id)!!
                assertEquals(listOf("gtptabs/5", "lacuerda/Z", "lacuerda/zz", "ug/101", "ug/99"),
                             (document.getValue("versions") as JsonArray).map { v ->
                                 v.jsonObject.let { "${text(it.getValue("provider"))}/${text(it.getValue("tab_id"))}" }
                             })
                assertEquals(Units.digestOf(db, id), Units.valueOfDocument(id, document)?.let(Canonical::digest))
            }
        }
    }

    @Test fun aUgVersionsRatingsAndVotesAreNoPartOfItsUnitAndAnotherSitesAre() {
        val dir = tmp.newFolder("volatile")
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { db -> Fixtures.load(db, "sync/fixtures/rich.jsonl", File(dir, "library").apply { mkdirs() }) }
            val id = "song/radiohead/creep"
            fun digest(provider: String, raw: String): Pair<String?, String?> {
                database.writeBlocking { db -> db.execute("UPDATE versions SET provider = ?, raw = ? WHERE song_id = 1", provider, raw) }
                return database.read { db ->
                    val raws = (Units.value(db, id)!!.jsonObject.getValue("versions") as JsonArray).map {
                        it.jsonObject.getValue("raw").jsonPrimitive.content
                    }
                    assertEquals(Units.digestOf(db, id), Units.valueOfDocument(id, Units.document(db, tmp.root, id))?.let(Canonical::digest))
                    Units.digestOf(db, id) to raws.single()
                }
            }
            val read = digest("ug", """{"id": 101, "rating": 4.5, "votes": 10, "content": "x"}""")
            assertEquals(read, digest("ug", """{"votes": 12, "content": "x", "id": 101, "rating": 4.71}"""))
            assertEquals(read, digest("ug", """{"id": 101, "content": "x"}"""))
            assertEquals(Canonical.hashStoredJson("""{"id": 101, "content": "x"}"""), read.second)
            assertTrue(read != digest("ug", """{"id": 101, "rating": 4.5, "votes": 10, "content": "y"}"""))
            // Another site's raw counts whole; and UG's rating within a member, or of a raw that holds no object.
            for ((provider, raw) in listOf("lacuerda" to """{"rating": 4.5, "votes": 10}""", "ug" to """[{"rating": 4.5}]""",
                                           "ug" to "not json")) {
                assertEquals(Canonical.hashStoredJson(raw), digest(provider, raw).second, "$provider $raw")
            }
            assertEquals(Canonical.hashStoredJson("""{"meta": {"rating": 4.5}}"""),
                         digest("ug", """{"meta": {"rating": 4.5}, "votes": 1}""").second)
        }
    }

    @Test fun aSongbooksUnitIsOfItsNamesKeyNowWhateverKeyIsStoredBesideIt() {
        TestDb.fresh(tmp.newFolder("songbooks")).use { database ->
            val songs = buildJsonArray { add(buildJsonArray { add(JsonPrimitive("A - B")); add(JsonObject(emptyMap())) }) }
            database.writeBlocking { db ->
                db.execute("INSERT INTO phone_songbooks (key, name, songs, position) VALUES ('stale', ?, ?, 0)",
                           "Camp  FIRE", Canonical.write(songs))
            }
            database.read { db ->
                assertEquals(listOf("songbook/camp fire"), Units.libraryState(db).keys.toList())
                assertEquals("""{"name":"Camp  FIRE","songs":[["A - B",{}]]}""", canonical(Units.value(db, "songbook/camp fire")))
                assertNull(Units.value(db, "songbook/stale"))
            }
            database.writeBlocking { db -> SongbookStore.put(db, "Camp Fire", songs) }
            database.read { db ->
                assertEquals(listOf(Triple("camp fire", "Camp Fire", 0L)),
                             db.query("SELECT key, name, position FROM phone_songbooks") { Triple(it.text(0), it.text(1), it.long(2)) })
            }
        }
    }

    @Test fun theStoresAreWhatTheUnitsRead() {
        TestDb.fresh(tmp.newFolder("stores")).use { database ->
            database.writeBlocking { db ->
                OverridesStore.putAlias(db, "soda", "Soda", buildJsonArray { add(JsonPrimitive("soda-stereo")) })
                OverridesStore.putArtistUrl(db, "soda", buildJsonObject { put("name", "Soda"); put("page", "https://u/a") })
            }
            database.read { db ->
                val state = Units.libraryState(db)
                assertEquals("alias of soda", state.getValue("alias/soda").label)
                assertEquals("UG page of Soda", state.getValue("artist_url/soda").label)
                assertEquals(Canonical.digest(buildJsonArray { add(JsonPrimitive("soda-stereo")) }), state.getValue("alias/soda").digest)
                assertEquals(buildJsonObject { put("slugs", buildJsonArray { add(JsonPrimitive("soda-stereo")) }) },
                             Units.document(db, tmp.root, "alias/soda"))
                assertEquals("""{"name":"Soda","page":"https://u/a"}""", canonical(Units.value(db, "artist_url/soda")))
                assertTrue(SongbookStore.all(db).isEmpty())
            }
        }
    }

    private fun song(change: MutableMap<String, JsonElement>.() -> Unit): JsonObject = JsonObject(
        linkedMapOf<String, JsonElement>(
            "key" to JsonPrimitive("a/b"),
            "names" to buildJsonObject { put("artist", "A"); put("title", "B") },
            "song" to record { },
            "versions" to buildJsonArray { add(version { }) },
            "kv" to JsonObject(emptyMap()),
            "overrides" to JsonObject(emptyMap()),
        ).apply(change),
    )

    private fun record(change: MutableMap<String, JsonElement>.() -> Unit): JsonObject = JsonObject(
        linkedMapOf<String, JsonElement>(
            "status" to JsonPrimitive("wanted"), "review" to JsonPrimitive(0), "match_decision" to JsonNull,
            "match_artist_key" to JsonNull, "match_song_key" to JsonNull, "lyrics_status" to JsonPrimitive("pending"),
            "lyrics_json" to JsonNull,
        ).apply(change),
    )

    private fun version(change: MutableMap<String, JsonElement>.() -> Unit): JsonObject = JsonObject(
        linkedMapOf<String, JsonElement>(
            "provider" to JsonPrimitive("ug"), "tab_id" to JsonPrimitive("1"), "slot" to JsonPrimitive("sheet"),
            "kind" to JsonPrimitive("chords"), "label" to JsonNull, "pick_rank" to JsonNull, "gone" to JsonPrimitive(0),
            "url" to JsonPrimitive("https://u/1"), "raw" to JsonPrimitive("{}"), "files" to JsonArray(emptyList()),
        ).apply(change),
    )

    private companion object {
        const val VALUES = "sync/values.jsonl"
        const val DOCUMENTS = "sync/documents.jsonl"
        const val TAKE = "sync/take.jsonl"
        const val STALE = "stale" // test_conformance_sync.py's digest that no longer is the unit's
        const val UNIT_VALUE = "caracole.peer_sync.unit_value"
        const val UNIT_DOCUMENT = "caracole.peer_sync.unit_document"
        const val VALUE_OF_DOCUMENT = "caracole.peer_sync.value_of_document"
    }
}
