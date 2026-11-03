package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.OverridesStore
import io.github.danielhp95.caracole.core.library.SongbookStore
import io.github.danielhp95.caracole.core.sync.internal.units.Documents
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
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
 * every unit's document, and value_of_document of each (documents.jsonl). A value compares by its canonical text, the
 * digest's own; a document as json.dumps(sort_keys=True) writes it, so a REAL cell is Python's float to the digit.
 */
class UnitsTest {
    @get:Rule val tmp = TemporaryFolder()

    private val opened = HashMap<String, Pair<Database, File>>()

    @After fun close() = opened.values.forEach { it.first.close() }

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

    private val fixtures: List<String>
        get() = (values + documents).mapNotNull { r -> r.extra["fixture"]?.takeUnless { it is JsonNull }?.let(::text) }
            .distinct()

    @Test fun everyRecordIsOfAFunctionThePhonePorts() {
        assertEquals(setOf(UNIT_VALUE), values.map { it.fn }.toSet())
        assertEquals(setOf(UNIT_DOCUMENT, VALUE_OF_DOCUMENT), documents.map { it.fn }.toSet())
        assertTrue("empty" in fixtures && "rich" in fixtures, "the fixtures: $fixtures")
    }

    @Test fun aLibrarysUnitsAreTheOnesPythonLists() {
        for (name in fixtures) {
            val expected = values.filter { text(it.extra.getValue("fixture")) == name }
                .map { it.out!!.jsonObject }
                .associate { text(it.getValue("id")) to (text(it.getValue("label")) to text(it.getValue("digest"))) }
            val state = reading(name) { db, _ -> Units.libraryState(db) }
            assertEquals(expected.keys.sorted(), state.keys.sorted(), "the units of $name")
            for ((id, unit) in state) {
                assertEquals(id, unit.id)
                assertEquals(expected.getValue(id), unit.label to unit.digest, "$name's $id")
            }
        }
    }

    @Test fun eachUnitsValueLabelAndDigestAreItsOwn() = check(values) { r ->
        val fixture = text(r.extra.getValue("fixture"))
        val id = text(r.args[0])
        val out = r.out!!.jsonObject
        reading(fixture) { db, _ ->
            val value = Units.value(db, id)
            differs(r, "value", canonical(out.getValue("value")), canonical(value))
                ?: differs(r, "digest", text(out.getValue("digest")), Units.digestOf(db, id))
                ?: differs(r, "digest of the value", text(out.getValue("digest")), value?.let(Canonical::digest))
                ?: differs(r, "label", text(out.getValue("label")), Units.libraryState(db)[id]?.label)
        }
    }

    @Test fun aUnitTheLibraryHasntGotHasNoValueAndNoDigest() {
        for (name in fixtures) {
            reading(name) { db, _ ->
                for (id in listOf("song/nobody/here", "removed/nobody/here", "songbook/nobody", "alias/nobody",
                                  "artist_url/nobody", "block/1", "block/x", "block/", "nonsense/x", "song")) {
                    assertNull(Units.value(db, id), "$name: $id")
                    assertNull(Units.digestOf(db, id), "$name: $id")
                }
            }
        }
    }

    @Test fun eachUnitsDocumentIsPythons() = check(documents.filter { it.fn == UNIT_DOCUMENT }) { r ->
        val fixture = text(r.extra.getValue("fixture"))
        val id = text(r.args[0])
        val out = nullable(r.out)?.jsonObject
        reading(fixture) { db, library ->
            val doc = Units.document(db, library, id)
            if (out == null) {
                differs(r, "document", null, python(doc))
            } else {
                differs(r, "format", out["format"], JsonPrimitive(Units.FORMAT))
                    ?: differs(r, "id", text(out.getValue("id")), id)
                    ?: differs(r, "document", python(out.getValue("unit")), python(doc))
                    ?: differs(r, "digest", text(out.getValue("digest")), Units.digestOf(db, id))
            }
        }
    }

    @Test fun aDocumentReadsBackAsPythonReadsIt() = check(documents.filter { it.fn == VALUE_OF_DOCUMENT }) { r ->
        val id = text(r.args[0])
        val doc = r.args[1]
        if (r.err != null) {
            assertEquals("UnitError", r.err)
            val e = runCatching { Documents.valueOf(id, nullable(doc)) }.exceptionOrNull()
            if (e is UnitError) null else "${r.args}: Python raised UnitError, Kotlin ${e ?: "answered"}"
        } else {
            val value = if (doc is JsonObject || doc is JsonNull) Units.valueOfDocument(id, doc as? JsonObject)
            else Documents.valueOf(id, doc)
            differs(r, "value", canonical(nullable(r.out)), canonical(value))
        }
    }

    /** take.jsonl's records name, for each unit a take asks for, its digest here before (`expected_here`, over the
     * take's fixture) and the digest of the document there (`wanted`, value_of_document's): the phone's are those. */
    @Test fun theDigestsATakeComparedAreThePhones() {
        val takes = Corpus.records(TAKE)
        assertTrue(takes.isNotEmpty(), "$TAKE has no records")
        check(takes) { r ->
            val fixture = text(r.extra.getValue("fixture"))
            val units = r.extra.getValue("source").jsonObject.getValue("units").jsonObject
            val wrong = ArrayList<String>()
            reading(fixture) { db, _ ->
                for ((id, digest) in r.kw.getValue("expected_here").jsonObject) {
                    val expected = nullable(digest)?.let(::text)
                    if (expected != STALE && expected != Units.digestOf(db, id)) {
                        wrong += "$fixture's $id here: Python $expected, Kotlin ${Units.digestOf(db, id)}"
                    }
                }
            }
            for (pair in r.args[0] as JsonArray) {
                val (id, digest) = (pair as JsonArray).let { text(it[0]) to nullable(it[1])?.let(::text) }
                if (digest == STALE) continue
                val got = Units.valueOfDocument(id, nullable(units[id])?.jsonObject)?.let(Canonical::digest)
                if (got != digest) wrong += "$fixture's $id there: Python $digest, Kotlin $got"
            }
            wrong.takeIf { it.isNotEmpty() }?.joinToString("; ")
        }
    }

    @Test fun everyUnitsDocumentReadsBackAsItsValue() {
        for (name in fixtures) {
            reading(name) { db, library ->
                for ((id, unit) in Units.libraryState(db)) {
                    val value = Units.valueOfDocument(id, Units.document(db, library, id))
                    assertEquals(unit.digest, value?.let(Canonical::digest), "$name: $id")
                }
            }
        }
    }

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

    @Test fun aBlockedTabIsFoundByItsNumberHoweverItIsWritten() {
        TestDb.fresh(tmp.newFolder("blocks")).use { database ->
            database.writeBlocking { OverridesStore.putBlock(it, 77, true) }
            database.read { db ->
                assertEquals(mapOf("block/77" to "the blocked tab 77"), Units.libraryState(db).mapValues { it.value.label })
                assertEquals(JsonPrimitive(true), Units.value(db, "block/077"))
                assertEquals(buildJsonObject { put("tab", 77) }, Units.document(db, tmp.root, "block/077"))
                assertNull(Units.value(db, "block/-77"))
                assertNull(Units.value(db, "block/ 77"))
                assertNull(Units.value(db, "block/99999999999999999999999"))
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
                assertEquals("the alias of soda", state.getValue("alias/soda").label)
                assertEquals("the UG page of Soda", state.getValue("artist_url/soda").label)
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
