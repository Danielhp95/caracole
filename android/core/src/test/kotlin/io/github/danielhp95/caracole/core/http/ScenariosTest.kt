package io.github.danielhp95.caracole.core.http

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.HttpReplay
import org.junit.Test

/** core.testing.Scenarios replays tests/test_scenario_helper.py's two records: a miss then the same page from the
 * cache, and a cached page then a 404. */
class ScenariosTest {
    @Test fun theScenarioHelpersRecordsReplay() {
        val misses = Misses("http/scenario_helper.jsonl")
        HttpReplay.scenarioHelper(misses)
        misses.assertNone()
    }
}
