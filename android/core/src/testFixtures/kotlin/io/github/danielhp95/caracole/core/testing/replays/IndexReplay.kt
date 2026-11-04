package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.index.Sites
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.index.TransferError
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Dumps
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.nio.file.Files

/**
 * The index vectors (vectors/index/, tests/test_conformance_index.py), every record answered by :core as Python
 * answered it, on the JVM (IndexMergeTest, IndexTransferTest, StampsTest call these) and on the device
 * (CorpusOnDeviceTest):
 *
 * - [merge]: each merge of merge.jsonl, the export written as a real SQLite file (Fixtures.loadRaw), the phone built
 *   (Fixtures.load into a new database), the merge run inside Database.writeBlocking, and the phone's dump after equal
 *   to Python's line by line, its kv text byte for byte; what it took as Python's Merged says, its backup called once
 *   exactly when Python backed the database up; a refusal a TransferError that leaves the phone as it was;
 * - [seedFresh] and [freshMerge]: a new phone seeded as a new Python database is (fresh-before), then merging the
 *   full export as Python did (fresh-after);
 * - [newest], newest.jsonl's each site's newest read; [sites], sites.jsonl's sites, their tables and kv;
 * - [stamps], stamps.jsonl's stamps.parse: datetime.fromisoformat's C reading, then the time in UTC.
 *
 * Each database is a fresh one in a temporary folder of its own.
 */
object IndexReplay : AreaReplay {
    override val area = "index"

    const val MERGE = "index/merge.jsonl"
    const val NEWEST = "index/newest.jsonl"
    const val SITES = "index/sites.jsonl"
    const val STAMPS = "index/stamps.jsonl"
    const val NOW = "2026-11-03T12:00:00Z"

    override fun replay(misses: Misses) {
        for (record in Corpus.records(MERGE)) merge(record, misses)
        seedFresh(misses)
        freshMerge(misses)
        newest(misses)
        sites(misses)
        stamps(misses)
    }

    /** A name for a merge's record: its fixture after, or its export refused, and the sites it asks for. */
    fun label(record: Record): String {
        val fixture = record.extra.getValue("fixture").jsonObject
        val name = if (record.err != null) "${fixture.getValue("export").jsonPrimitive.content} refused"
        else fixture.getValue("after").jsonPrimitive.content
        return "$name ${record.kw["sites"]}"
    }

    /** One merge of merge.jsonl, as Python merged it. */
    fun merge(record: Record, misses: Misses) {
        val label = label(record)
        val fixture = record.extra.getValue("fixture").jsonObject
        fun fixture(role: String) = fixture.getValue(role).jsonPrimitive.content
        inFolder("caracole-merge") { dir ->
            val export = File(dir, "export.sqlite")
            Fixtures.loadRaw(export, "index/fixtures/${fixture("export")}.jsonl")
            val now = record.kw.getValue("now").jsonPrimitive.content
            val sites = (record.kw["sites"] as? JsonArray)?.map { it.jsonPrimitive.content }
            TestDb.fresh(dir).use { database ->
                database.writeBlocking { Fixtures.load(it, "index/fixtures/${fixture("before")}.jsonl") }
                var backups = 0
                if (record.err != null) {
                    misses.check(record.err == "TransferError") { "$label: Python raised ${record.err}" }
                    misses.check(fixture("before") == fixture("after")) { "$label: a refusal changes the phone" }
                    val before = database.read { Dumps.lines(it) }
                    val refused = try {
                        database.writeBlocking { IndexTransfer.merge(it, export, now, sites) { backups++ } }
                        false
                    } catch (e: TransferError) {
                        true
                    }
                    misses.check(refused) { "$label: Python refused it, Kotlin merged it" }
                    misses.check(backups == 0) { "$label: backed up $backups times before a refusal" }
                    misses.check(before == database.read { Dumps.lines(it) }) { "$label: the refusal changed the phone" }
                } else {
                    val merged = database.writeBlocking { IndexTransfer.merge(it, export, now, sites) { backups++ } }
                    val out = record.out!!.jsonObject
                    misses.check(out.getValue("changed").jsonPrimitive.boolean == merged.changed) {
                        "$label: changed ${merged.changed}, Python's ${out["changed"]}"
                    }
                    val backedUp = if (out.getValue("backup").jsonPrimitive.boolean) 1 else 0
                    misses.check(backedUp == backups) { "$label: backed up $backups times, Python $backedUp" }
                    val taken = out.getValue("sites").jsonArray.associate { site ->
                        val s = site.jsonObject
                        s.getValue("site").jsonPrimitive.content to s.getValue("taken").jsonArray.associate { pair ->
                            pair.jsonArray[0].jsonPrimitive.content to pair.jsonArray[1].jsonPrimitive.int
                        }
                    }
                    misses.check(taken == merged.sites && taken.keys.toList() == merged.sites.keys.toList()) {
                        "$label: took ${merged.sites}, Python $taken"
                    }
                    val after = database.read { Dumps.lines(it) }
                    val want = Dumps.fixture(fixture("after"))
                    misses.check(want == after) {
                        "$label: the phone after differs from Python's at ${firstDifference(want, after)}"
                    }
                }
                // The export stays detached: the phone's connections see one database.
                val attached = database.writeBlocking { db ->
                    db.query("PRAGMA database_list") { it.text(1)!! }.filter { it != "temp" }
                }
                misses.check(attached == listOf("main")) { "$label: attached $attached after the merge" }
            }
        }
    }

    /** A new phone seeded holds what a new Python database holds (fresh-before), less kv phone:schema, which Python's
     * fixture was dumped before. */
    fun seedFresh(misses: Misses) = inFolder("caracole-seed") { dir ->
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            val seeded = database.read { Dumps.lines(it) }.filter { !it.startsWith("{\"kv\":\"phone:schema\"") }
            val want = Dumps.fixture("fresh-before")
            misses.check(want == seeded) { "seedFresh: differs from fresh-before at ${firstDifference(want, seeded)}" }
        }
    }

    /** A fresh phone seeded, then the full export merged into it: Python's fresh-after. */
    fun freshMerge(misses: Misses) = inFolder("caracole-fresh") { dir ->
        val export = File(dir, "export.sqlite").also { Fixtures.loadRaw(it, "index/fixtures/full-export.jsonl") }
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            val merged = database.writeBlocking { IndexTransfer.merge(it, export, NOW) }
            misses.check(merged.changed) { "the full export into a fresh phone changed nothing" }
            val after = database.read { Dumps.lines(it) }
            val want = Dumps.fixture("fresh-after")
            misses.check(want == after) { "the fresh phone differs from fresh-after at ${firstDifference(want, after)}" }
        }
    }

    /** newest.jsonl: each fixture's newest read of each site, in caracole's order; an OverflowError Python raised an
     * ArithmeticException. */
    fun newest(misses: Misses) {
        val records = Corpus.records(NEWEST)
        misses.check(records.size >= 10) { "$NEWEST holds ${records.size} records" }
        for (record in records) {
            val fixture = record.extra.getValue("fixture").jsonPrimitive.content
            inFolder("caracole-newest") { dir ->
                TestDb.fresh(dir).use { database ->
                    database.writeBlocking { Fixtures.load(it, "index/fixtures/$fixture.jsonl") }
                    if (record.err != null) {
                        misses.check(record.err == "OverflowError") { "$fixture: Python raised ${record.err}" }
                        val raised = try {
                            database.read { IndexTransfer.newest(it) }
                            false
                        } catch (e: ArithmeticException) {
                            true
                        }
                        misses.check(raised) { "$fixture: Python raised OverflowError, Kotlin answered" }
                    } else {
                        val expected = record.out!!.jsonObject.mapValues { it.value.jsonPrimitive.content }
                        val newest = database.read { IndexTransfer.newest(it) }
                        misses.check(expected == newest) { "$fixture: newest $newest, Python $expected" }
                        val order = Sites.ALL.map { it.name }.filter { it in newest }
                        misses.check(order == newest.keys.toList()) { "$fixture: in the order ${newest.keys}" }
                    }
                }
            }
        }
    }

    /** sites.jsonl: index_transfer's sites, in its order, each with its title, tables and kv records. */
    fun sites(misses: Misses) {
        val records = Corpus.records(SITES)
        misses.check(records.map { it.args[0].jsonPrimitive.content } == Sites.ALL.map { it.name }) {
            "the sites ${Sites.ALL.map { it.name }}, Python's ${records.map { it.args[0] }}"
        }
        for ((record, site) in records.zip(Sites.ALL)) {
            val out = record.out!!.jsonObject
            fun strings(key: String) = out.getValue(key).jsonArray.map { it.jsonPrimitive.content }
            misses.check(out.getValue("title").jsonPrimitive.content == site.title) { "${site.name}'s title ${site.title}" }
            misses.check(strings("tables") == site.tables) { "${site.name}'s tables ${site.tables}" }
            misses.check(strings("kv") == site.kv) { "${site.name}'s kv ${site.kv}" }
        }
    }

    /** stamps.jsonl: stamps.parse of every value, a string's twice (as a JSON value and as text), Python's TypeError
     * an IllegalArgumentException and its OverflowError an ArithmeticException. */
    fun stamps(misses: Misses) {
        val records = Corpus.records(STAMPS)
        misses.check(records.size > 1000) { "$STAMPS holds ${records.size} records" }
        var strings = 0
        for (r in records) {
            val value = r.args[0]
            val shown = value.toString()
            when (r.err) {
                null -> {
                    val expected = (r.out as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content
                    misses.expect("stamps.parse", shown, expected?.let(::JsonPrimitive)) {
                        Stamps.parse(value)?.let(Stamps::isoformat)
                    }
                    if (value is JsonPrimitive && value.isString) {
                        strings++
                        misses.expect("stamps.parse", shown, expected?.let(::JsonPrimitive)) {
                            Stamps.parse(value.content)?.let(Stamps::isoformat)
                        }
                    }
                }
                "OverflowError" -> misses.check(raises<ArithmeticException> { Stamps.parse(value) }) {
                    "stamps.parse($shown): Python raised OverflowError"
                }
                "TypeError" -> misses.check(raises<IllegalArgumentException> { Stamps.parse(value) }) {
                    "stamps.parse($shown): Python raised TypeError"
                }
                else -> misses.check(false) { "no such error: ${r.err}" }
            }
        }
        misses.check(strings > 1000) { "$STAMPS holds $strings strings" }
    }

    private inline fun <reified E : Throwable> raises(block: () -> Unit): Boolean = try {
        block()
        false
    } catch (e: Throwable) {
        e is E
    }

    private fun firstDifference(a: List<String>, b: List<String>): String {
        val i = a.indices.firstOrNull { it >= b.size || a[it] != b[it] } ?: a.size
        return "line $i: Python ${a.getOrNull(i)?.take(300)}, Kotlin ${b.getOrNull(i)?.take(300)}"
    }

    private fun <T> inFolder(prefix: String, block: (File) -> T): T {
        val dir = Files.createTempDirectory(prefix).toFile()
        try {
            return block(dir)
        } finally {
            dir.deleteRecursively()
        }
    }
}
