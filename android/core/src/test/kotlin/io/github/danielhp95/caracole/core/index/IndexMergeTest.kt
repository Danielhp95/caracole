package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.replays.IndexReplay
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized

/**
 * Every merge of tests/conformance/vectors/index/merge.jsonl: the export written as a real SQLite file
 * (Fixtures.loadRaw), the phone built (Fixtures.load into a new database), the merge run inside Database.writeBlocking,
 * and the phone's dump after equal to Python's, line by line, its kv text byte for byte; what it took as Python's
 * Merged says, and its backup callback called once exactly when Python backed the database up. A refusal is a
 * TransferError that leaves the phone as it was, its backup never called (IndexReplay.merge, which the device runs
 * too).
 */
@RunWith(Parameterized::class)
class IndexMergeTest(@Suppress("unused") private val label: String, private val record: Record) {
    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "{0}")
        fun merges(): List<Array<Any>> = Corpus.records(IndexReplay.MERGE).map { arrayOf(IndexReplay.label(it), it) }
    }

    @Test fun thePhoneAfterIsPythons() = Misses(label).also { IndexReplay.merge(record, it) }.assertNone()
}
