package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.junit.runners.Parameterized
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/**
 * Every merge of tests/conformance/vectors/index/merge.jsonl: the export written as a real SQLite file
 * (Fixtures.loadRaw), the phone built (Fixtures.load into a new database), the merge run inside Database.writeBlocking,
 * and the phone's dump after equal to Python's, line by line, its kv text byte for byte; what it took as Python's
 * Merged says, and its backup callback called once exactly when Python backed the database up. A refusal is a
 * TransferError that leaves the phone as it was, its backup never called.
 */
@RunWith(Parameterized::class)
class IndexMergeTest(@Suppress("unused") private val label: String, private val record: Record) {
    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "{0}")
        fun merges(): List<Array<Any>> = Corpus.records("index/merge.jsonl").map { record ->
            val fixture = record.extra.getValue("fixture").jsonObject
            val after = fixture.getValue("after").jsonPrimitive.content
            val name = if (record.err != null) "${fixture.getValue("export").jsonPrimitive.content} refused" else after
            arrayOf("$name ${record.kw["sites"]}", record)
        }
    }

    @get:Rule val tmp = TemporaryFolder()

    private val fixture = record.extra.getValue("fixture").jsonObject
    private fun fixture(role: String) = fixture.getValue(role).jsonPrimitive.content

    @Test fun thePhoneAfterIsPythons() {
        val dir = tmp.newFolder()
        val export = File(dir, "export.sqlite")
        Fixtures.loadRaw(export, "index/fixtures/${fixture("export")}.jsonl")
        val now = record.kw.getValue("now").jsonPrimitive.content
        val sites = (record.kw["sites"] as? JsonArray)?.map { it.jsonPrimitive.content }
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { Fixtures.load(it, "index/fixtures/${fixture("before")}.jsonl") }
            var backups = 0
            if (record.err != null) {
                assertEquals("TransferError", record.err)
                assertEquals(fixture("before"), fixture("after"))
                val before = database.read { Dumps.lines(it) }
                assertFailsWith<TransferError> {
                    database.writeBlocking { IndexTransfer.merge(it, export, now, sites) { backups++ } }
                }
                assertEquals(0, backups)
                assertEquals(before, database.read { Dumps.lines(it) })
            } else {
                val merged = database.writeBlocking { IndexTransfer.merge(it, export, now, sites) { backups++ } }
                val out = record.out!!.jsonObject
                assertEquals(out.getValue("changed").jsonPrimitive.boolean, merged.changed)
                assertEquals(if (out.getValue("backup").jsonPrimitive.boolean) 1 else 0, backups)
                val taken = out.getValue("sites").jsonArray.associate { site ->
                    val s = site.jsonObject
                    s.getValue("site").jsonPrimitive.content to s.getValue("taken").jsonArray.associate { pair ->
                        pair.jsonArray[0].jsonPrimitive.content to pair.jsonArray[1].jsonPrimitive.int
                    }
                }
                assertEquals(taken, merged.sites)
                assertEquals(taken.keys.toList(), merged.sites.keys.toList())
                assertEquals(Dumps.fixture(fixture("after")), database.read { Dumps.lines(it) })
            }
            // The export stays detached: the phone's connections see one database.
            assertEquals(listOf("main"), database.writeBlocking { db ->
                db.query("PRAGMA database_list") { it.text(1)!! }.filter { it != "temp" }
            })
        }
    }
}
