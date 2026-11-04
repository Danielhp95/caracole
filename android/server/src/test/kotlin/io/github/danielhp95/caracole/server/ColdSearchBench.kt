package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.server.testing.ColdSearch
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/**
 * The first search after an import and a start, on the JVM, over 300,000 ug_index rows (ColdSearch; its numbers
 * are android/README.md's Performance notes, beside the emulator's, ColdSearchTest's). In the gated `bench` task.
 */
class ColdSearchBench {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun theFirstSearchAfterAStart() {
        val result = ColdSearch(tmp.root, 300_000).run()
        println("ColdSearchBench: $result")
    }
}
