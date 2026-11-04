package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.testing.TestParts
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals

/** The lookup commands' runners are built from the phone's parts (lane lookup runs them). */
class RunnersTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun eachRunnerIsMadeOfThePhonesParts() {
        val scope = CoroutineScope(SupervisorJob())
        TestDb.fresh(tmp.root).use { database ->
            val parts = TestParts.of(database, tmp.root, scope)
            assertEquals(listOf(parts, parts, parts, parts),
                         listOf(GetRunner(parts).parts, VersionsRunner(parts).parts, LaCuerdaRunner(parts).parts,
                                HarpTabsRunner(parts).parts))
        }
        scope.cancel()
    }
}
