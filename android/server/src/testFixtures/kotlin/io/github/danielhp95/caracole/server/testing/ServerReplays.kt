package io.github.danielhp95.caracole.server.testing

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.server.testing.replays.CardsReplay
import io.github.danielhp95.caracole.server.testing.replays.ChoicesReplay
import io.github.danielhp95.caracole.server.testing.replays.ExportReplay
import io.github.danielhp95.caracole.server.testing.replays.GuitarReplay
import io.github.danielhp95.caracole.server.testing.replays.JobViewsReplay
import io.github.danielhp95.caracole.server.testing.replays.LibraryNameReplay
import io.github.danielhp95.caracole.server.testing.replays.LookupRoutesReplay
import io.github.danielhp95.caracole.server.testing.replays.QueueReplay
import io.github.danielhp95.caracole.server.testing.replays.RequestsReplay
import io.github.danielhp95.caracole.server.testing.replays.ReviewReplay
import io.github.danielhp95.caracole.server.testing.replays.SongbookTabReplay
import io.github.danielhp95.caracole.server.testing.replays.WebReplay

/** :server's areas of the corpus (core.testing.Replays has :core's, viewer.testing.ViewerReplays :viewer's), each its
 * own file of replays/, its lane's to fill; this list is the skeletons'. */
object ServerReplays {
    val all: List<AreaReplay> = listOf(WebReplay, LibraryNameReplay, QueueReplay, JobViewsReplay, RequestsReplay,
                                       LookupRoutesReplay, CardsReplay, SongbookTabReplay, ChoicesReplay, GuitarReplay,
                                       ExportReplay, ReviewReplay)
}
