package io.github.danielhp95.caracole.server.routes.library

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.server.testing.replays.WebReplay
import org.junit.Test
import kotlin.test.assertEquals

/**
 * Every record of vectors/web/sync_routes.jsonl, caracole serve's Sync tab routes over a fixture of the sync corpus and
 * another caracole's state, asked of the phone's SyncRoutes over the same: here, the fixture loaded into the phone's
 * database with its id and kv, its library's name; there, a computer answering its state as the record's
 * `peer_state` (then `peer_state_then`, for the Sync that follows a comparison) gives it, and its units as
 * `peer_units` do. The phone answers what Python answered, under UTC, the comparison's id masked, its status and its
 * words alike, but for its device ("phone") and the computer's kind ("computer"), where caracole serve says
 * "computer" and "server"; a Sync queued is the computer's view of the same job but for the stages the phone's sync
 * has and the computer's hasn't (mirror and index, §5.3), and its comparison the one the computer's queued command
 * names (`--compared=<hash>`). WebReplay.syncRoutes replays them, on the device too.
 */
class SyncRoutesVectorsTest {
    @Test fun theRecordsAskEveryRouteOfTheSyncTab() =
        assertEquals(setOf("GET /api/sync", "POST /sync/test", "POST /sync/compare", "GET /api/sync/unit",
                           "GET /api/sync/indexes", "POST /sync/apply"),
                     Corpus.records("web/sync_routes.jsonl").map { it.fn }.toSet())

    @Test fun everyRecordIsThePhonesAnswerOverTheSameSides() =
        Misses("web/sync_routes.jsonl").also { WebReplay.syncRoutes(it) }.assertNone()
}
