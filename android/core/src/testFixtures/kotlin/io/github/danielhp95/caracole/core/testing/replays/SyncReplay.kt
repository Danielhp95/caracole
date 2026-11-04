package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.SongbookStore
import io.github.danielhp95.caracole.core.sync.Base
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.Difference
import io.github.danielhp95.caracole.core.sync.SyncUnit
import io.github.danielhp95.caracole.core.sync.Take
import io.github.danielhp95.caracole.core.sync.UnitError
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.sync.internal.units.Documents
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.sync.InlineSource
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.nio.file.Files
import java.util.Base64

/**
 * The sync vectors (vectors/sync/, tests/test_conformance_sync.py; its settings records are SettingsReplay's), every
 * record answered by :core as Python answered it, on the JVM (CompareTest, TakeTest and UnitsTest call these) and on
 * the device (CorpusOnDeviceTest):
 *
 * - the comparison: [compare] over the design's three-way table, [mergedBase], [recordAgreement] (the base's kv text
 *   byte for byte), [decide] and [comparedHash];
 * - the units: over each fixture (vectors/sync/fixtures/) loaded into a fresh database, [libraryState]'s units, each
 *   one's value, label and digest ([values]), its document ([documents]), [valueOfDocument], and each document read
 *   back as its value ([documentsAsValues]); [takeDigests], the digests take.jsonl's records compared;
 * - the take: [checkedName], every case of take.jsonl ([takes]), every fixture's units taken into an empty phone
 *   ([fixturesTaken]) and every take's fixture copied unit by unit into one ([takesCopied]);
 * - [nameKey], songbook.name_key.
 *
 * A value compares by its canonical text, the digest's own; a document as json.dumps(sort_keys=True) writes it. Each
 * phone is a database of its own in a temporary folder.
 */
object SyncReplay : AreaReplay {
    override val area = "sync"

    const val VALUES = "sync/values.jsonl"
    const val DOCUMENTS = "sync/documents.jsonl"
    const val TAKE = "sync/take.jsonl"
    const val NOW = "2026-10-31T00:00:00Z"
    const val STALE = "stale" // test_conformance_sync.py's digest that no longer is the unit's
    const val UNIT_VALUE = "caracole.peer_sync.unit_value"
    const val UNIT_DOCUMENT = "caracole.peer_sync.unit_document"
    const val VALUE_OF_DOCUMENT = "caracole.peer_sync.value_of_document"

    /** The lyrics' files a take writes from lyrics_json, which were never in a fixture's folder. */
    val LYRICS = setOf("lyrics.txt", "lyrics.lrc")

    override fun replay(misses: Misses) {
        compare(misses)
        mergedBase(misses)
        recordAgreement(misses)
        decide(misses)
        comparedHash(misses)
        libraryState(misses)
        values(misses)
        documents(misses)
        valueOfDocument(misses)
        takeDigests(misses)
        documentsAsValues(misses)
        checkedName(misses)
        takes(misses)
        fixturesTaken(misses)
        takesCopied(misses)
        nameKey(misses)
    }

    // --- the comparison -------------------------------------------------------------------------------------------

    fun compare(misses: Misses) = each(records("sync/compare.jsonl", "caracole.peer_sync.compare", misses), misses) { r ->
        val found = Compare.compare(units(r.args[0]), units(r.args[1]), merged(r.args[2]))
        differs(r, r.out!!.jsonArray.map(::difference), found)
    }

    fun mergedBase(misses: Misses) =
        each(records("sync/merged_base.jsonl", "caracole.peer_sync.merged_base", misses), misses) { r ->
            val got = Compare.mergedBase(base(r.args[0]), base(r.args[1]))
            differs(r, merged(r.out), got) ?: differs(r, merged(r.out)?.keys?.toList(), got?.keys?.toList())
        }

    fun recordAgreement(misses: Misses) {
        val records = records("sync/record_agreement.jsonl", "caracole.peer_sync.record_agreement", misses)
        withDatabase { database ->
            each(records, misses) { r ->
                val peer = text(r.args[0])
                val key = "sync:base:$peer"
                val out = r.out!!.jsonObject
                database.writeBlocking { db ->
                    db.kvDelete(key)
                    textOrNull(r.extra["before"])?.let { db.kvSet(key, it) }
                    val agreed = Compare.recordAgreement(db, peer, units(r.args[1]), units(r.args[2]), text(r.args[3]))
                    differs(r, text(out.getValue("after")), db.kvGet(key))
                        ?: differs(r, out.getValue("agreed").jsonPrimitive.content.toInt(), agreed)
                }
            }
        }
    }

    fun decide(misses: Misses) = each(records("sync/decide.jsonl", "caracole.peer_sync.decide", misses), misses) { r ->
        val found = r.args[0].jsonArray.map(::difference)
        val chosen = r.kw.getValue("choose").jsonObject.mapValues { (_, side) -> text(side) }
        val (here, there) = Compare.decide(found, textOrNull(r.args.getOrNull(1))) { chosen[it.id] }
        val out = r.out!!.jsonObject
        differs(r, out.getValue("here").jsonArray.map(::text), here.map { it.id })
            ?: differs(r, out.getValue("there").jsonArray.map(::text), there.map { it.id })
    }

    fun comparedHash(misses: Misses) =
        each(records("sync/compared_hash.jsonl", "caracole.peer_sync.compared_hash", misses), misses) { r ->
            differs(r, text(r.out!!), Compare.comparedHash(r.args[0].jsonArray.map(::difference)))
        }

    // --- the units ------------------------------------------------------------------------------------------------

    /** The fixtures values.jsonl and documents.jsonl name. */
    fun fixtures(): List<String> = (Corpus.records(VALUES) + Corpus.records(DOCUMENTS))
        .mapNotNull { r -> r.extra["fixture"]?.takeUnless { it is JsonNull }?.let(::text) }.distinct()

    /** Each fixture's units, as library_state lists them, with their labels and digests. */
    fun libraryState(misses: Misses) = withFixtures { reads ->
        for (name in fixtures()) {
            val expected = Corpus.records(VALUES).filter { text(it.extra.getValue("fixture")) == name }
                .map { it.out!!.jsonObject }
                .associate { text(it.getValue("id")) to (text(it.getValue("label")) to text(it.getValue("digest"))) }
            val state = reads.read(name) { db, _ -> Units.libraryState(db) }
            misses.check(expected.keys.sorted() == state.keys.sorted()) { "the units of $name: ${state.keys.sorted()}" }
            for ((id, unit) in state) {
                misses.check(id == unit.id && expected[id] == (unit.label to unit.digest)) {
                    "$name's $id: ${unit.label to unit.digest}, Python ${expected[id]}"
                }
            }
        }
    }

    /** values.jsonl: each unit's value, label and digest. */
    fun values(misses: Misses) = withFixtures { reads ->
        each(Corpus.records(VALUES), misses) { r ->
            val id = text(r.args[0])
            val out = r.out!!.jsonObject
            reads.read(text(r.extra.getValue("fixture"))) { db, _ ->
                val value = Units.value(db, id)
                differs(r, "value", canonical(out.getValue("value")), canonical(value))
                    ?: differs(r, "digest", text(out.getValue("digest")), Units.digestOf(db, id))
                    ?: differs(r, "digest of the value", text(out.getValue("digest")), value?.let(Canonical::digest))
                    ?: differs(r, "label", text(out.getValue("label")), Units.libraryState(db)[id]?.label)
            }
        }
    }

    /** documents.jsonl's unit_document records: each unit's document, its format, id and digest. */
    fun documents(misses: Misses) = withFixtures { reads ->
        each(Corpus.records(DOCUMENTS).filter { it.fn == UNIT_DOCUMENT }, misses) { r ->
            val id = text(r.args[0])
            val out = nullable(r.out)?.jsonObject
            reads.read(text(r.extra.getValue("fixture"))) { db, library ->
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
    }

    /** documents.jsonl's value_of_document records: a document read back as Python reads it, or a UnitError. */
    fun valueOfDocument(misses: Misses) = each(Corpus.records(DOCUMENTS).filter { it.fn == VALUE_OF_DOCUMENT }, misses) { r ->
        val id = text(r.args[0])
        val doc = r.args[1]
        if (r.err != null) {
            val e = runCatching { Documents.valueOf(id, nullable(doc)) }.exceptionOrNull()
            if (r.err == "UnitError" && e is UnitError) null else "${r.args}: Python raised ${r.err}, Kotlin ${e ?: "answered"}"
        } else {
            val value = if (doc is JsonObject || doc is JsonNull) Units.valueOfDocument(id, doc as? JsonObject)
            else Documents.valueOf(id, doc)
            differs(r, "value", canonical(nullable(r.out)), canonical(value))
        }
    }

    /** take.jsonl's records name, for each unit a take asks for, its digest here before (`expected_here`, over the
     * take's fixture) and the digest of the document there (`wanted`): the phone's are those. */
    fun takeDigests(misses: Misses) = withFixtures { reads ->
        each(Corpus.records(TAKE), misses) { r ->
            val name = text(r.extra.getValue("fixture"))
            val units = r.extra.getValue("source").jsonObject.getValue("units").jsonObject
            val wrong = ArrayList<String>()
            reads.read(name) { db, _ ->
                for ((id, digest) in r.kw.getValue("expected_here").jsonObject) {
                    val expected = nullable(digest)?.let(::text)
                    if (expected != STALE && expected != Units.digestOf(db, id)) {
                        wrong += "$name's $id here: Python $expected, Kotlin ${Units.digestOf(db, id)}"
                    }
                }
            }
            for (pair in r.args[0] as JsonArray) {
                val (id, digest) = (pair as JsonArray).let { text(it[0]) to nullable(it[1])?.let(::text) }
                if (digest == STALE) continue
                val got = Units.valueOfDocument(id, nullable(units[id])?.jsonObject)?.let(Canonical::digest)
                if (got != digest) wrong += "$name's $id there: Python $digest, Kotlin $got"
            }
            wrong.takeIf { it.isNotEmpty() }?.joinToString("; ")
        }
    }

    /** Every unit's document of each fixture reads back as its value. */
    fun documentsAsValues(misses: Misses) = withFixtures { reads ->
        for (name in fixtures()) {
            reads.read(name) { db, library ->
                for ((id, unit) in Units.libraryState(db)) {
                    val value = Units.valueOfDocument(id, Units.document(db, library, id))
                    misses.check(unit.digest == value?.let(Canonical::digest)) { "$name: $id's document reads otherwise" }
                }
            }
        }
    }

    // --- the take -------------------------------------------------------------------------------------------------

    /** checked_name.jsonl: a kept file's name a song's folder can hold, else a UnitError (as is a name that isn't
     * text, the take's nameOf). */
    fun checkedName(misses: Misses) {
        val records = Corpus.records("sync/checked_name.jsonl")
        misses.check(records.size >= 15) { "checked_name.jsonl holds ${records.size} records" }
        for (r in records) {
            val name = r.args[0]
            if (name !is JsonPrimitive || !name.isString) {
                misses.check(r.err == "UnitError") { "a name that isn't text is no name: $name" }
                continue
            }
            if (r.err != null) {
                misses.check(r.err == "UnitError" && runCatching { Take.checkedName(name.content) }.exceptionOrNull() is UnitError) {
                    "checked_name(${name.content}): Python raised ${r.err}"
                }
            } else {
                val got = runCatching { Take.checkedName(name.content) }.getOrElse { it.toString() }
                misses.check(textOrNull(r.out) == got) { "checked_name(${name.content}) = $got, Python ${r.out}" }
            }
        }
    }

    /** take.jsonl: each case taken as Python's apply_units took it, the phone after as Python's. */
    fun takes(misses: Misses) {
        val records = Corpus.records(TAKE)
        misses.check(records.size >= 15) { "$TAKE holds ${records.size} records" }
        for (r in records) {
            val case = textOrNull(r.extra["case"])!!
            phone("sync/fixtures/${textOrNull(r.extra["fixture"])}.jsonl") { phone ->
                take(r, case, phone, misses)
            }
        }
    }

    private fun take(r: Record, case: String, phone: Phone, misses: Misses) {
        val source = InlineSource.of(r.extra.getValue("source").jsonObject)
        val wanted = r.args[0].jsonArray.map { w -> w.jsonArray.let { textOrNull(it[0])!! to textOrNull(it[1]) } }
        val expected = r.kw.getValue("expected_here").jsonObject.mapValues { textOrNull(it.value) }
        val told = mutableListOf<Pair<String, String>>()
        val done = phone.write { db ->
            Take.applyUnits(db, phone.store, source, wanted, expected, textOrNull(r.kw["now"])!!) { id, what -> told += id to what }
        }
        val out = r.out!!.jsonObject
        fun strings(name: String) = out.getValue(name).jsonArray.map { it.jsonPrimitive.content }
        fun same(what: String, want: Any?, got: Any?) = misses.check(want == got) { "$case: $what $got, Python $want" }
        same("taken", strings("taken"), done.taken)
        val left = out.getValue("left").jsonArray.map { it.jsonArray.let { p -> textOrNull(p[0])!! to textOrNull(p[1])!! } }
        same("left", left.map { it.first }, done.left.map { it.first })
        for ((want, got) in left.zip(done.left)) {
            if (want.second.startsWith("changed ") || want.second.startsWith("a kept file named") ||
                want.second.endsWith("no such file is kept") || want.second.contains(" came other than it is there")) {
                same("${got.first} left saying", want.second, got.second) // the compare-and-swap's and the take's words
            } else {
                misses.check(got.second.isNotEmpty()) { "$case: ${got.first} left saying nothing" }
            }
        }
        same("units told", wanted.size, told.size) // each unit told once, as it is done
        same("told", (done.taken.map { it to "taken" } + done.left.map { it.first to "left" }).toMap(), told.toMap())
        same("respelled", strings("respelled"), done.respelled)
        same("songbooks", out["songbooks"]?.jsonPrimitive?.content?.toBoolean(), done.songbooksChanged)
        same("songs", out.getValue("songs").jsonArray.map { it.jsonPrimitive.content.toLong() }, done.songs)
        phone.write { db ->
            same("after", Canonical.write(out.getValue("after")), Canonical.write(after(db)))
            // What a song's value leaves out: its record's other columns, its versions' (rating, votes, coverage,
            // fetched_at), its files' kept_rank, the carried kv under the phone's own id.
            val documents = out.getValue("documents").jsonObject
            same("songs' documents", documents.keys, after(db).keys.filter { it.startsWith("song/") }.toSet())
            for ((id, want) in documents) {
                same("$id's document", Canonical.write(want), Canonical.write(Units.document(db, phone.library, id) ?: JsonNull))
            }
            same("ids", out.getValue("ids").jsonObject.mapValues { it.value.jsonPrimitive.content.toLong() },
                 db.query("SELECT id, key FROM songs ORDER BY id") { it.text(1)!! to it.long(0) }.toMap())
            // The render records of a folder moved go; the carried kv is the phone's id's.
            same("kv", out.getValue("kv").jsonArray.map { kv -> kv.jsonArray.map { it.jsonPrimitive.content } },
                 db.query("SELECT key, value FROM kv WHERE substr(key, 1, 7) = 'render:' " +
                              "OR substr(key, 1, 15) = 'sheet_versions:' ORDER BY key") {
                     listOf(it.text(0)!!, it.text(1)!!)
                 })
            same("paths", strings("paths"), db.query("SELECT path FROM files ORDER BY path") { it.text(0)!! })
        }
        same("files", out.getValue("files").jsonArray.map { f -> f.jsonArray.map { it.jsonPrimitive.content } },
             filesOf(phone.library))
    }

    /** Every fixture of values.jsonl taken into an empty phone is its values and digests, its documents the
     * computer's. */
    fun fixturesTaken(misses: Misses) {
        val values = Corpus.records(VALUES)
        val documents = Corpus.records(DOCUMENTS).filter { it.fn.endsWith(".unit_document") }
        for (fixture in listOf("rich", "dense", "plain", "empty")) {
            val units = documents.filter { textOrNull(it.extra["fixture"]) == fixture && it.out is JsonObject }
                .associate { textOrNull(it.args[0])!! to it.out!!.jsonObject.getValue("unit").jsonObject }
            val want = values.filter { textOrNull(it.extra["fixture"]) == fixture }.map { it.out!!.jsonObject }
            val source = InlineSource(units, keptFiles("sync/fixtures/$fixture.jsonl"))
            phone(null) { phone ->
                val done = phone.write { db ->
                    Take.applyUnits(db, phone.store, source, want.map { textOrNull(it["id"])!! to textOrNull(it["digest"]) },
                                    want.associate { textOrNull(it["id"])!! to null }, NOW)
                }
                misses.check(done.left.isEmpty()) { "$fixture: left ${done.left}" }
                misses.check(want.map { textOrNull(it["id"]) }.toSet() == done.taken.toSet()) { "$fixture: took ${done.taken}" }
                phone.write { db ->
                    val state = Units.libraryState(db)
                    misses.check(want.map { textOrNull(it["id"]) }.toSet() == state.keys) { "$fixture: holds ${state.keys}" }
                    for (unit in want) {
                        val id = textOrNull(unit["id"])!!
                        misses.check(textOrNull(unit["label"]) == state[id]?.label) { "$fixture $id's label" }
                        misses.check(textOrNull(unit["digest"]) == state[id]?.digest) { "$fixture $id's digest" }
                        misses.check(Canonical.write(unit.getValue("value")) == Units.value(db, id)?.let(Canonical::write)) {
                            "$fixture $id's value"
                        }
                        // And all a document holds beyond the value: the phone's document is the computer's.
                        misses.check(Canonical.write(units.getValue(id)) ==
                                         Units.document(db, phone.library, id)?.let(Canonical::write)) {
                            "$fixture $id's document"
                        }
                    }
                }
            }
        }
    }

    /** Every take's fixture read by the phone, its every unit taken into an empty phone, which then holds them alike
     * (the take.jsonl fixtures have no values.jsonl records), its kept files too. */
    fun takesCopied(misses: Misses) {
        val fixtures = Corpus.records(TAKE).map { textOrNull(it.extra["fixture"])!! }.distinct()
        misses.check(fixtures.size >= 15) { "$TAKE names ${fixtures.size} fixtures" }
        for (fixture in fixtures) {
            phone("sync/fixtures/$fixture.jsonl") { from ->
                val (state, documents) = from.write { db ->
                    Units.libraryState(db).let { s -> s to s.keys.associateWith { Units.document(db, from.library, it) } }
                }
                val source = InlineSource(documents, keptFiles("sync/fixtures/$fixture.jsonl"))
                phone(null) { into ->
                    val done = into.write { db ->
                        Take.applyUnits(db, into.store, source, state.values.map { it.id to it.digest }, state.mapValues { null }, NOW)
                    }
                    misses.check(done.left.isEmpty()) { "$fixture: left ${done.left}" }
                    into.write { db ->
                        misses.check(state == Units.libraryState(db)) { "$fixture: the units differ after the copy" }
                        for ((id, doc) in documents) {
                            misses.check(Canonical.write(doc!!) == Units.document(db, into.library, id)?.let(Canonical::write)) {
                                "$fixture $id's document"
                            }
                        }
                    }
                    fun kept(library: File) = filesOf(library).filter { it[0].substringAfterLast('/') !in LYRICS }
                    misses.check(kept(from.library) == kept(into.library)) { "$fixture: the kept files differ" }
                }
            }
        }
    }

    /** name_key.jsonl: songbook.name_key. */
    fun nameKey(misses: Misses) {
        val records = Corpus.records("sync/name_key.jsonl")
        misses.check(records.map { it.fn }.toSet() == setOf("caracole.songbook.name_key")) { "name_key.jsonl's functions" }
        for (r in records) {
            val name = r.args[0].jsonPrimitive.content
            val got = runCatching { SongbookStore.nameKey(name) }.getOrElse { "${it::class.simpleName}: ${it.message}" }
            misses.check(got == r.out!!.jsonPrimitive.content) { "name_key($name) = $got, Python ${r.out}" }
        }
    }

    // --- what they share ------------------------------------------------------------------------------------------

    /** A phone of a fixture's: its database and library folder. */
    class Phone(val database: Database, val library: File) {
        val store = LibraryStore(library)
        fun <T> write(block: (Db) -> T): T = database.writeBlocking(block)
    }

    /** A fresh phone with [fixture] (a corpus path, or none) loaded, in a temporary folder of its own, for [block]. */
    fun <T> phone(fixture: String?, block: (Phone) -> T): T {
        val dir = Files.createTempDirectory("caracole-sync").toFile()
        try {
            return TestDb.fresh(dir).use { database ->
                val phone = Phone(database, File(dir, "library"))
                if (fixture != null) phone.write { Fixtures.load(it, fixture, phone.library) }
                block(phone)
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    /** Reads of the fixtures by name (sync/fixtures/<name>.jsonl), each loaded once into a phone of its own. */
    class FixtureReads : AutoCloseable {
        private val opened = HashMap<String, Triple<Database, File, File>>()

        fun <T> read(name: String, block: (Db, File) -> T): T {
            val (database, library) = opened.getOrPut(name) {
                val dir = Files.createTempDirectory("caracole-units").toFile()
                val library = File(dir, "library").apply { mkdirs() }
                val database = TestDb.fresh(dir)
                database.writeBlocking { Fixtures.load(it, "sync/fixtures/$name.jsonl", library) }
                Triple(database, library, dir)
            }
            return database.read { block(it, library) }
        }

        override fun close() {
            for ((database, _, dir) in opened.values) {
                database.close()
                dir.deleteRecursively()
            }
        }
    }

    private fun <T> withFixtures(block: (FixtureReads) -> T): T = FixtureReads().use(block)

    private fun <T> withDatabase(block: (Database) -> T): T {
        val dir = Files.createTempDirectory("caracole-sync").toFile()
        try {
            return TestDb.fresh(dir).use(block)
        } finally {
            dir.deleteRecursively()
        }
    }

    private fun records(name: String, fn: String, misses: Misses): List<Record> = Corpus.records(name).also { all ->
        misses.check(all.map { it.fn }.toSet() == setOf(fn)) { "$name's functions: ${all.map { it.fn }.toSet()}" }
        misses.check(all.isNotEmpty()) { "$name has no records" }
    }

    /** Each record's mismatch ([compare]'s words, or what it threw), as a miss. */
    private fun each(records: List<Record>, misses: Misses, compare: (Record) -> String?) {
        for (record in records) {
            val wrong = try {
                compare(record)
            } catch (e: Throwable) {
                "${record.extra["case"] ?: record.args}: ${e::class.simpleName}: ${e.message}"
            }
            misses.check(wrong == null) { wrong!! }
        }
    }

    private fun differs(record: Record, expected: Any?, actual: Any?): String? =
        if (expected == actual) null else "${record.extra["case"] ?: record.args}:\n  Python $expected\n  Kotlin $actual"

    private fun differs(record: Record, what: String, expected: Any?, actual: Any?): String? =
        if (expected == actual) null else "${record.args} ($what): Python $expected, Kotlin $actual"

    /** This side's units, as take.jsonl's `after` writes them: `{id: {label, digest, value}}`. */
    private fun after(db: Db): JsonObject = JsonObject(Units.libraryState(db).values.associate { unit ->
        unit.id to JsonObject(mapOf("label" to JsonPrimitive(unit.label), "digest" to JsonPrimitive(unit.digest),
                                    "value" to (Units.value(db, unit.id) ?: JsonNull)))
    })

    /** Every file of the library's song folders (not the library's own top files), [path, sha256], by path as
     * Python sorts its paths (part by part). */
    fun filesOf(library: File): List<List<String>> {
        if (!library.isDirectory) return emptyList()
        return library.walkTopDown().filter { it.isFile && it.parentFile != library }
            .map { it.relativeTo(library).invariantSeparatorsPath }
            .sortedWith { a, b -> compareParts(a.split('/'), b.split('/')) }
            .map { listOf(it, Canonical.sha256Hex(File(library, it).readBytes())) }
            .toList()
    }

    private fun compareParts(a: List<String>, b: List<String>): Int {
        for (i in 0 until minOf(a.size, b.size)) {
            val c = Canonical.KEY_ORDER.compare(a[i], b[i])
            if (c != 0) return c
        }
        return a.size - b.size
    }

    /** A fixture's kept files, by song key, name and SHA-256, with their bytes. */
    fun keptFiles(fixture: String): List<InlineSource.Kept> {
        val lines = Corpus.lines(fixture).filter { it["header"] != JsonPrimitive(true) }
        val keys = lines.filter { textOrNull(it["table"]) == "songs" }.map { it.getValue("row").jsonObject }
            .associate { textOrNull(it["id"]) to textOrNull(it["key"])!! }
        val bytes = lines.filter { "file" in it }
            .associate { textOrNull(it["file"]) to Base64.getDecoder().decode(textOrNull(it["base64"])) }
        return lines.filter { textOrNull(it["table"]) == "files" }.map { it.getValue("row").jsonObject }.mapNotNull { f ->
            bytes[textOrNull(f["path"])]?.let {
                InlineSource.Kept(keys.getValue(textOrNull(f["song_id"])), textOrNull(f["name"])!!, textOrNull(f["sha256"])!!, it)
            }
        }
    }

    private fun text(e: JsonElement): String = e.jsonPrimitive.content
    private fun textOrNull(e: JsonElement?): String? = if (e == null || e is JsonNull) null else e.jsonPrimitive.content
    private fun nullable(e: JsonElement?): JsonElement? = e?.takeUnless { it is JsonNull }
    private fun canonical(e: JsonElement?): String? = e?.let { Canonical.write(it) }
    private fun python(e: JsonElement?): String? = e?.let { PyJson.dumps(it, sortKeys = true) }

    private fun unit(e: JsonElement?): SyncUnit? = e?.takeUnless { it is JsonNull }?.jsonObject?.let {
        SyncUnit(text(it.getValue("id")), text(it.getValue("label")), text(it.getValue("digest")))
    }

    private fun units(e: JsonElement): Map<String, SyncUnit> = e.jsonObject.mapValues { (_, u) -> unit(u)!! }

    private fun base(e: JsonElement?): Base? = e?.takeUnless { it is JsonNull }?.jsonObject?.mapValues { (_, entry) ->
        val pair = entry.jsonArray
        textOrNull(pair[0]) to text(pair[1])
    }

    private fun merged(e: JsonElement?): Map<String, String?>? =
        e?.takeUnless { it is JsonNull }?.jsonObject?.mapValues { (_, d) -> textOrNull(d) }

    private fun difference(e: JsonElement): Difference = e.jsonObject.let {
        Difference(text(it.getValue("id")), text(it.getValue("label")), unit(it["mine"]), unit(it["theirs"]),
                   text(it.getValue("proposal")), text(it.getValue("why")))
    }
}
