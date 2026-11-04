package io.github.danielhp95.caracole.server.testing

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.server.testing.replays.JobViewsReplay
import io.github.danielhp95.caracole.server.testing.replays.LibraryNameReplay
import io.github.danielhp95.caracole.server.testing.replays.LookupRoutesReplay
import io.github.danielhp95.caracole.server.testing.replays.QueueReplay
import io.github.danielhp95.caracole.server.testing.replays.RequestsReplay
import io.github.danielhp95.caracole.server.testing.replays.WebReplay

/** :server's areas of the corpus (core.testing.Replays has :core's), each its own file of replays/, its lane's to
 * fill; this list is the skeletons' (skeleton-m5m6 adds milestone 5's and 6's). */
object ServerReplays {
    val all: List<AreaReplay> = listOf(WebReplay, LibraryNameReplay, QueueReplay, JobViewsReplay, RequestsReplay,
                                       LookupRoutesReplay)
}
