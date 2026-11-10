package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.SongbookStore
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.sync.Base
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.Difference
import io.github.danielhp95.caracole.core.sync.KeptEntry
import io.github.danielhp95.caracole.core.sync.KeptPair
import io.github.danielhp95.caracole.core.sync.PeerState
import io.github.danielhp95.caracole.core.sync.Scope
import io.github.danielhp95.caracole.core.sync.SyncUnit
import io.github.danielhp95.caracole.core.sync.Take
import io.github.danielhp95.caracole.core.sync.PeerError
import io.github.danielhp95.caracole.core.sync.UnitError
import io.github.danielhp95.caracole.core.sync.file.FileError
import io.github.danielhp95.caracole.core.sync.file.FileSource
import io.github.danielhp95.caracole.core.sync.file.PageSource
import io.github.danielhp95.caracole.core.sync.file.SyncFiles
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
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.ByteArrayInputStream
import java.io.File
import java.nio.file.Files
import java.time.OffsetDateTime
import java.time.ZoneOffset
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
 * - [nameKey], songbook.name_key;
 * - the sync redesign's rules (tests/test_conformance_sync_kept.py): the remembered answer ([kept]: merged_kept,
 *   compare with kept answers, record_kept and record_agreement to the kv's byte, kept_of, a state's kept) and a
 *   sync's parts ([scope]: in_scope, listed_songs, change_of, names_of);
 * - the `.caracole` file (tests/test_conformance_sync_file.py, [file]): each fixture exported by the phone as Python
 *   exported it, as data; Python's files read back alike, their units, their refusals and their checks; and each
 *   import's differences, takes and bases.
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
        kept(misses)
        scope(misses)
        file(misses)
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

    // --- the remembered answer and the parts (vectors/sync/kept.jsonl, scope.jsonl) -----------------------------

    const val KEPT = "sync/kept.jsonl"
    const val SCOPE = "sync/scope.jsonl"

    /** Every record of kept.jsonl: merged_kept, compare with kept answers, record_kept and record_agreement (the
     * base's kv text after, byte for byte, and what each returned), kept_of and a state document's kept. */
    fun kept(misses: Misses) {
        val records = Corpus.records(KEPT)
        misses.check(records.map { it.fn }.toSet() == setOf("merged_kept", "compare", "record_kept", "record_agreement",
                                                          "kept_of", "read_state_document")) { "$KEPT's functions" }
        withDatabase { database ->
            each(records, misses) { r ->
                val given = r.extra.getValue("in").jsonObject
                when (r.fn) {
                    "merged_kept" -> differs(r, pairs(r.out), Compare.mergedKept(
                        base(given["mine"]), keptOf(given["mine_kept"]), base(given["theirs"]), keptOf(given["theirs_kept"])))
                        ?: differs(r, pairs(r.out)?.keys?.toList(), Compare.mergedKept(
                            base(given["mine"]), keptOf(given["mine_kept"]), base(given["theirs"]),
                            keptOf(given["theirs_kept"])).keys.toList())
                    "compare" -> {
                        val found = Compare.compare(units(given.getValue("mine")), units(given.getValue("theirs")),
                                                    merged(given["base"]), pairs(given["kept"]))
                        differs(r, r.out!!.jsonArray.map { row -> row.jsonArray.map(::text) },
                                found.map { listOf(it.id, it.proposal, it.why) })
                    }
                    "record_kept", "record_agreement", "kept_of" -> database.writeBlocking { db ->
                        val peer = text(given.getValue("peer"))
                        val key = "sync:base:$peer"
                        db.kvDelete(key)
                        textOrNull(given["kv"])?.let { db.kvSet(key, it) }
                        if (r.fn == "kept_of") {
                            differs(r, keptOf(r.out), Compare.keptOf(db, peer))
                        } else {
                            val args = given.getValue("args").jsonArray
                            val returned = if (r.fn == "record_kept") {
                                Compare.recordKept(db, peer, args[0].jsonObject.mapValues { (_, pair) ->
                                    textOrNull(pair.jsonArray[0]) to textOrNull(pair.jsonArray[1])
                                }, text(args[1]))
                            } else {
                                Compare.recordAgreement(db, peer, units(args[0]), units(args[1]), text(args[2]))
                            }
                            differs(r, textOrNull(r.out), db.kvGet(key))
                                ?: differs(r, r.extra.getValue("returned").jsonPrimitive.int, returned)
                        }
                    }
                    "read_state_document" ->
                        differs(r, keptOf(r.out), PeerState.read(given.getValue("doc")).kept)
                    else -> "an unknown function ${r.fn}"
                }
            }
        }
    }

    /** Every record of scope.jsonl: in_scope, change_of, names_of and [listedSongs]. */
    fun scope(misses: Misses) {
        val records = Corpus.records(SCOPE)
        misses.check(records.map { it.fn }.toSet() == setOf("in_scope", "listed_songs", "change_of", "names_of")) {
            "$SCOPE's functions"
        }
        listedSongs(misses)
        each(records.filter { it.fn != "listed_songs" }, misses) { r ->
            val given = r.extra.getValue("in").jsonObject
            when (r.fn) {
                "in_scope" -> {
                    val found = given.getValue("found").jsonArray.map(::difference)
                    val listed = nullable(given["listed"])?.jsonObject?.mapValues { (_, books) -> books.jsonArray.map(::text) }
                    val holds = nullable(given["holds"])?.jsonArray?.map(::text)
                    differs(r, r.out!!.jsonArray.map(::text),
                            Scope.inScope(found, given.getValue("parts").jsonArray.map(::text), listed ?: emptyMap(), holds)
                                .map { it.id })
                }
                "change_of" -> {
                    val (here, there) = Scope.changeOf(difference(given.getValue("d")), merged(given["base"]),
                                                       pairs(given["kept"]))
                    differs(r, r.out!!.jsonArray.map(::textOrNull), listOf(here, there))
                }
                "names_of" -> differs(r, nullable(r.out)?.jsonArray?.map(::text),
                                      Scope.namesOf(text(given.getValue("unit_id")), text(given.getValue("label")))
                                          ?.toList())
                else -> "an unknown function ${r.fn}"
            }
        }
    }

    /** scope.jsonl's listed_songs records: the songs songbooks list, by unit, in order. */
    fun listedSongs(misses: Misses) {
        val records = Corpus.records(SCOPE).filter { it.fn == "listed_songs" }
        misses.check(records.isNotEmpty()) { "$SCOPE has no listed_songs record" }
        each(records, misses) { r ->
            val given = r.extra.getValue("in").jsonObject
            val got = Scope.listedSongs(given.getValue("books").jsonObject, given.getValue("units").jsonArray.map(::text))
            val want = r.out!!.jsonObject.mapValues { (_, b) -> b.jsonArray.map(::text) }
            differs(r, want, got) ?: differs(r, want.keys.toList(), got.keys.toList())
        }
    }

    // --- the .caracole file (vectors/sync/file.jsonl and its files) -------------------------------------------

    const val FILE = "sync/file.jsonl"
    const val TAKEN = "2026-11-04T09:00:00Z"  // test_conformance_sync_file.py's: when an import's take is made

    /** Every record of file.jsonl: export, file_name, read, unit, check_whole, check_importable and import; those of
     * [only] alone when given. */
    fun file(misses: Misses, only: String? = null) {
        val records = Corpus.records(FILE)
        val fns = setOf("export", "file_name", "read", "unit", "check_whole", "check_importable", "import")
        misses.check(records.map { it.fn }.toSet() == fns) { "$FILE's functions: ${records.map { it.fn }.toSet()}" }
        each(records.filter { only == null || it.fn == only }, misses) { r ->
            when (r.fn) {
                "export" -> fileExport(r)
                "file_name" -> {
                    val given = r.extra.getValue("in").jsonObject
                    val at = OffsetDateTime.parse(text(given.getValue("when")))
                    differs(r, text(r.out!!), SyncFiles.fileName(textOrNull(given["name"]), at.toInstant(), at.offset))
                }
                "read" -> inFolder { dir ->
                    val (path, name) = materialized(r, dir)
                    differs(r, canonical(r.out), canonical(readOut(path, name)))
                }
                "unit" -> inFolder { dir ->
                    val (path, name) = materialized(r, dir)
                    val id = text(r.extra.getValue("id"))
                    val got = FileSource(SyncFiles.read(path, name), null, dir).use { source ->
                        try {
                            val doc = source.unit(id)
                            JsonObject(mapOf("unit" to JsonPrimitive(doc?.let { Canonical.digest(Units.valueOfDocument(id, it)!!) })))
                        } catch (e: PeerError) {
                            JsonObject(mapOf("error" to JsonPrimitive(e.message)))
                        }
                    }
                    differs(r, canonical(r.out), canonical(got))
                }
                "check_whole" -> inFolder { dir ->
                    val (path, name) = materialized(r, dir)
                    val error = try {
                        SyncFiles.checkWhole(SyncFiles.read(path, name))
                        null
                    } catch (e: FileError) {
                        e.message
                    }
                    differs(r, canonical(r.out), canonical(JsonObject(mapOf("error" to JsonPrimitive(error)))))
                }
                "check_importable" -> inFolder { dir ->
                    val (path, name) = materialized(r, dir)
                    val error = withDatabase { database ->
                        database.writeBlocking { db ->
                            for ((key, value) in r.extra.getValue("kv").jsonObject) db.kvSet(key, text(value))
                        }
                        try {
                            database.read { db ->
                                SyncFiles.checkImportable(SyncFiles.read(path, name), db, textOrNull(r.extra["own"]), ZoneOffset.UTC)
                            }
                            null
                        } catch (e: FileError) {
                            e.message
                        }
                    }
                    differs(r, canonical(r.out), canonical(JsonObject(mapOf("error" to JsonPrimitive(error)))))
                }
                "import" -> fileImport(r)
                else -> "an unknown function ${r.fn}"
            }
        }
    }

    /** An export record: the fixture loaded as Python's was (its id, kv and files changed), exported by the phone, and
     * the file's members compared with Python's as data. */
    private fun fileExport(r: Record): String? = phone("sync/fixtures/${text(r.extra.getValue("fixture"))}.jsonl") { p ->
        val id = text(r.extra.getValue("id"))
        p.write { db ->
            db.kvSet("sync:id", id)
            for ((key, value) in r.extra.getValue("kv").jsonObject) db.kvSet(key, text(value))
        }
        for ((unit, files) in r.extra.getValue("changed").jsonObject) {
            for ((name, data) in files.jsonObject) {
                val path = p.database.read { db ->
                    db.one("SELECT files.path FROM files JOIN songs ON songs.id = files.song_id WHERE songs.key = ? " +
                               "AND files.name = ?", unit.substringAfter('/'), name) { it.text(0) }
                }!!
                File(p.library, path).writeBytes(Base64.getDecoder().decode(text(data)))
            }
        }
        val pages = nullable(r.extra["pages"])?.jsonObject?.let(::pagesOf)
        val out = File(p.library.parentFile, "export.caracole")
        val made = p.database.writeBlocking { db ->
            SyncFiles.export(db, p.library, pages, out, r.extra.getValue("parts").jsonArray.map(::text),
                             text(r.extra.getValue("now")), id, text(r.extra.getValue("name")), text(r.extra.getValue("version")))
        }
        val members = java.util.zip.ZipFile(out).use { z -> z.entries().toList().map { it.name to z.getInputStream(it).readBytes() } }
        val got = members.toMap()
        fun json(name: String): JsonElement? = got[name]?.let { Canonical.parse(it.toString(Charsets.UTF_8)) }
        val want = r.out!!.jsonObject
        val mine = JsonObject(linkedMapOf(
            "members" to JsonArray(members.map { JsonPrimitive(it.first) }),
            "manifest" to json(SyncFiles.MANIFEST)!!, "state" to json(SyncFiles.STATE)!!, "bases" to json(SyncFiles.BASES)!!,
            "units" to JsonArray(got.getValue(SyncFiles.UNITS).toString(Charsets.UTF_8).split('\n').filter { it.isNotEmpty() }
                                     .map { Canonical.parse(it) }),
            "files" to JsonArray(members.map { it.first }.filter { it.startsWith(SyncFiles.FILES) }.map { JsonPrimitive(it.substringAfter('/')) }),
            "pages" to (json(SyncFiles.PAGES) ?: JsonNull),
            "page_blobs" to JsonArray(members.map { it.first }.filter { it.startsWith(SyncFiles.PAGE_BLOBS) }.map { JsonPrimitive(it.substringAfter('/')) }),
            "left" to JsonArray(made.left.map { (u, why) -> JsonArray(listOf(JsonPrimitive(u), JsonPrimitive(why))) }),
        ))
        want.keys.firstNotNullOfOrNull { key -> differs(r, key, canonical(want[key]), canonical(mine[key])) }
            ?: got[SyncFiles.INDEXES]?.let { indexes ->
                // Its indexes as data: a Python caracole merges the phone's indexes.sqlite as it merges its own.
                val theirs = Corpus.open("sync/" + text(r.extra.getValue("file")))!!.use { member(it.readBytes(), SyncFiles.INDEXES) }
                differs(r, SyncFiles.INDEXES, canonical(sqliteData(theirs, out.parentFile)),
                        canonical(sqliteData(indexes, out.parentFile)))
            }
    }

    /** The zip member [name] of [zip]'s bytes. */
    private fun member(zip: ByteArray, name: String): ByteArray =
        java.util.zip.ZipInputStream(ByteArrayInputStream(zip)).use { z ->
            generateSequence { z.nextEntry }.first { it.name == name }.let { z.readBytes() }
        }

    /** An SQLite file's tables as data, by name: each one's columns and its rows (in their canonical JSON's order),
     * the export's META without its `source` (the path of the database it was made from). */
    private fun sqliteData(bytes: ByteArray, dir: File): JsonObject {
        val file = File(dir, "data-${System.nanoTime()}.sqlite").apply { writeBytes(bytes) }
        val c = androidx.sqlite.driver.bundled.BundledSQLiteDriver()
            .open(file.path, androidx.sqlite.driver.bundled.SQLITE_OPEN_READONLY)
        try {
            val tables = c.prepare("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").use { st ->
                buildList { while (st.step()) add(st.getText(0)) }
            }
            return JsonObject(tables.associateWith { table ->
                c.prepare("SELECT * FROM \"$table\"").use { st ->
                    val columns = (0 until st.getColumnCount()).map { st.getColumnName(it) }
                    val rows = buildList {
                        while (st.step()) add(JsonArray(columns.indices.map { i ->
                            when (st.getColumnType(i)) {
                                androidx.sqlite.SQLITE_DATA_NULL -> JsonNull
                                androidx.sqlite.SQLITE_DATA_INTEGER -> JsonPrimitive(st.getLong(i))
                                androidx.sqlite.SQLITE_DATA_FLOAT -> PyJson.float(st.getDouble(i))
                                androidx.sqlite.SQLITE_DATA_TEXT -> JsonPrimitive(st.getText(i))
                                else -> JsonPrimitive("blob:" + Base64.getEncoder().encodeToString(st.getBlob(i)))
                            }
                        }))
                    }.filter { row -> table != io.github.danielhp95.caracole.core.index.IndexTransfer.META ||
                        (row[0] as? JsonPrimitive)?.content != "source" }
                    JsonObject(mapOf("columns" to JsonArray(columns.map(::JsonPrimitive)),
                                     "rows" to JsonArray(rows.sortedWith(compareBy(Py.CODE_POINT_ORDER) { canonical(it) ?: "" }))))
                }
            })
        } finally {
            c.close()
            file.delete()
        }
    }

    /** A record's pages (`{"manifest", "bytes": {path: base64}}`) as the export's PageSource: each page by its bytes'
     * SHA-256. */
    private fun pagesOf(given: JsonObject): PageSource {
        val bytes = given.getValue("bytes").jsonObject.values.map { Base64.getDecoder().decode(text(it)) }
            .associateBy { Canonical.sha256Hex(it) }
        val manifest = given.getValue("manifest").jsonObject
        return object : PageSource {
            override fun manifest(units: Map<String, String>): JsonObject = manifest
            override fun open(sha256: String) = bytes[sha256]?.let(::ByteArrayInputStream)
        }
    }

    /** An import record: this side as Python's was (its fixture, id and kv), the file compared, decided as chosen,
     * taken from (at [TAKEN]) and its agreement recorded, compared with Python's after. */
    private fun fileImport(r: Record): String? = phone("sync/fixtures/${text(r.extra.getValue("here"))}.jsonl") { p ->
        val id = text(r.extra.getValue("id"))
        p.write { db ->
            db.kvSet("sync:id", id)
            for ((key, value) in r.extra.getValue("kv").jsonObject) db.kvSet(key, text(value))
        }
        val (path, name) = materialized(r, p.library.parentFile)
        val sf = SyncFiles.read(path, name)
        val choices = r.extra.getValue("choices").jsonObject.mapValues { text(it.value) }
        val prefer = textOrNull(r.extra["prefer"])?.let { mapOf("here" to Compare.MINE, "there" to Compare.THEIRS)[it] }
        val parts = r.extra.getValue("parts").jsonArray.map(::text)
        FileSource(sf, p.database, p.library).use { source ->
            val compared = p.database.read { db -> SyncFiles.compareFile(db, sf, source, id) }
            val scoped = SyncFiles.inParts(compared, parts)
            val sides = mapOf("here" to Compare.MINE, "there" to Compare.THEIRS)
            val asChosen = scoped.filter { choices[it.id] != "skip" }
                .map { d -> choices[d.id]?.let { d.copy(proposal = sides.getValue(it)) } ?: d }
            val (take, keep) = Compare.decide(asChosen, prefer)
            val done = p.write { db ->
                Take.applyUnits(db, p.store, source, take.map { it.id to it.theirs?.digest },
                                take.associate { it.id to it.mine?.digest }, TAKEN)
            }
            p.write { db -> SyncFiles.recordImport(db, sf, Units.libraryState(db), SyncFiles.keptAnswers(scoped, keep)) }
            val after = p.database.read { db -> Units.libraryState(db) }
            val (baseAfter, keptAfter) = p.database.read { db ->
                db.kvGet("sync:base:${sf.id ?: "a1b2c3d4e5f60718"}") to Compare.keptOf(db, sf.id ?: "a1b2c3d4e5f60718")
            }
            val mine = JsonObject(linkedMapOf(
                "differences" to JsonArray(compared.found.map { d -> JsonArray(listOf(d.id, d.proposal, d.why).map(::JsonPrimitive)) }),
                "scoped" to JsonArray(scoped.map { JsonPrimitive(it.id) }),
                "taken" to JsonArray(done.taken.map(::JsonPrimitive)),
                "left" to JsonArray(done.left.map { (u, why) -> JsonArray(listOf(JsonPrimitive(u), JsonPrimitive(why))) }),
                "after" to JsonObject(after.mapValues { JsonPrimitive(it.value.digest) }),
                "base_after" to JsonPrimitive(baseAfter),
                "kept_after" to JsonObject(keptAfter.mapValues { (_, e) ->
                    JsonArray(listOf(JsonPrimitive(e.here), JsonPrimitive(e.there), JsonPrimitive(e.at)))
                }),
            ))
            val want = r.out!!.jsonObject
            want.keys.firstNotNullOfOrNull { key -> differs(r, key, canonical(want[key]), canonical(mine[key])) }
        }
    }

    /** read_file's answer as the vectors write it: the file's id, name, made, holds, whether an index export, its
     * units' digests and its documents' ids, or `{"error"}`. */
    private fun readOut(path: File, name: String?): JsonObject {
        val f = try {
            SyncFiles.read(path, name)
        } catch (e: FileError) {
            return JsonObject(mapOf("error" to JsonPrimitive(e.message)))
        }
        val documents = FileSource(f, null, path.parentFile).use { it.documents().keys.sortedWith(Canonical.KEY_ORDER) }
        return JsonObject(linkedMapOf(
            "id" to JsonPrimitive(f.id), "name" to JsonPrimitive(f.name), "made" to JsonPrimitive(f.made),
            "holds" to JsonArray(f.holds.map(::JsonPrimitive)), "index_only" to JsonPrimitive(f.indexOnly),
            "units" to JsonObject((f.state?.units ?: emptyMap()).mapValues { JsonPrimitive(it.value.digest) }),
            "documents" to JsonArray(documents.map(::JsonPrimitive)),
        ))
    }

    /** The file a record names, written into [dir]: one of the corpus's (`file`, less its last `cut` bytes, or its
     * `member`), or its `bytes`; and the name it is read by (`name`, for an index export). */
    private fun materialized(r: Record, dir: File): Pair<File, String?> {
        var data = textOrNull(r.extra["bytes"])?.let { Base64.getDecoder().decode(it) }
            ?: Corpus.open("sync/" + text(r.extra.getValue("file")))!!.use { it.readBytes() }
        textOrNull(r.extra["member"])?.let { member ->
            data = java.util.zip.ZipInputStream(ByteArrayInputStream(data)).use { zip ->
                generateSequence { zip.nextEntry }.first { it.name == member }.let { zip.readBytes() }
            }
        }
        textOrNull(r.extra["cut"])?.let { data = data.copyOf(data.size - it.toInt()) }
        val path = File(dir, "file-${System.nanoTime()}.caracole").apply { writeBytes(data) }
        return path to (textOrNull(r.extra["name"]) ?: textOrNull(r.extra["member"]))
    }

    private fun <T> inFolder(block: (File) -> T): T {
        val dir = Files.createTempDirectory("caracole-file").toFile()
        try {
            return block(dir)
        } finally {
            dir.deleteRecursively()
        }
    }

    /** `{id: [here, there, when]}` (kept answers as stored), else none. */
    private fun keptOf(e: JsonElement?): Map<String, KeptEntry> =
        nullable(e)?.jsonObject?.mapValues { (_, entry) ->
            val (here, there, at) = entry.jsonArray
            KeptEntry(textOrNull(here), textOrNull(there), text(at))
        } ?: emptyMap()

    /** `{id: [here, there, chooser]}` (merged_kept's), else null. */
    private fun pairs(e: JsonElement?): Map<String, KeptPair>? =
        nullable(e)?.jsonObject?.mapValues { (_, entry) ->
            val (here, there, chooser) = entry.jsonArray
            KeptPair(textOrNull(here), textOrNull(there), text(chooser))
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
        if (expected == actual) null else "${record.extra["case"] ?: record.args} ($what): Python $expected, Kotlin $actual"

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
