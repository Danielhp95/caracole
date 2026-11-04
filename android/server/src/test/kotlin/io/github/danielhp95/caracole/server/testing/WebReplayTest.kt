package io.github.danielhp95.caracole.server.testing

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.server.testing.replays.WebReplay
import org.junit.Test

/** The web vectors' replays whose records another test also reads on the JVM, run as the device runs them:
 * api_search.jsonl (ApiSearchTest's own loop, lane lookup-routes') and downloads.jsonl (FileTypesTest's and :core's
 * DownloadNamesTest's). */
class WebReplayTest {
    @Test fun everyApiSearchRecordIsReplayedAsTheDeviceReplaysIt() =
        Misses("web/api_search.jsonl").also { WebReplay.apiSearch(it) }.assertNone()

    @Test fun everyDownloadRecordIsReplayedAsTheDeviceReplaysIt() =
        Misses("web/downloads.jsonl").also { WebReplay.downloads(it) }.assertNone()
}
