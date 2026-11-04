package io.github.danielhp95.caracole.viewer.testing

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.viewer.testing.replays.ChineseReplay
import io.github.danielhp95.caracole.viewer.testing.replays.HarmonicaPageReplay
import io.github.danielhp95.caracole.viewer.testing.replays.HarmonyReplay
import io.github.danielhp95.caracole.viewer.testing.replays.HarptabReplay
import io.github.danielhp95.caracole.viewer.testing.replays.PagesReplay
import io.github.danielhp95.caracole.viewer.testing.replays.RenderReplay
import io.github.danielhp95.caracole.viewer.testing.replays.ShapesReplay
import io.github.danielhp95.caracole.viewer.testing.replays.SheetReplay
import io.github.danielhp95.caracole.viewer.testing.replays.TheoryReplay
import io.github.danielhp95.caracole.viewer.testing.replays.VersionReplay

/** :viewer's areas of the corpus, milestone 5's (core.testing.Replays has :core's, server.testing.ServerReplays
 * :server's), in the order the device runs them, each its own file of replays/, its lane's to fill; this list is the
 * skeletons'. */
object ViewerReplays {
    val all: List<AreaReplay> = listOf(TheoryReplay, SheetReplay, ShapesReplay, ChineseReplay, HarmonyReplay,
                                       VersionReplay, HarptabReplay, PagesReplay, HarmonicaPageReplay, RenderReplay)
}
