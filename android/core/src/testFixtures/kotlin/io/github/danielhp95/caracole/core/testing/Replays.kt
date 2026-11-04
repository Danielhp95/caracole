package io.github.danielhp95.caracole.core.testing

import io.github.danielhp95.caracole.core.testing.replays.CanonicalReplay
import io.github.danielhp95.caracole.core.testing.replays.FuzzReplay
import io.github.danielhp95.caracole.core.testing.replays.GameTabsReplay
import io.github.danielhp95.caracole.core.testing.replays.HarpTabsReplay
import io.github.danielhp95.caracole.core.testing.replays.HealthReplay
import io.github.danielhp95.caracole.core.testing.replays.HtmlReplay
import io.github.danielhp95.caracole.core.testing.replays.HttpReplay
import io.github.danielhp95.caracole.core.testing.replays.IndexExportReplay
import io.github.danielhp95.caracole.core.testing.replays.InboxReplay
import io.github.danielhp95.caracole.core.testing.replays.IndexReplay
import io.github.danielhp95.caracole.core.testing.replays.KeysReplay
import io.github.danielhp95.caracole.core.testing.replays.LaCuerdaReplay
import io.github.danielhp95.caracole.core.testing.replays.LibraryWritesReplay
import io.github.danielhp95.caracole.core.testing.replays.LookupReplay
import io.github.danielhp95.caracole.core.testing.replays.LookupScenariosReplay
import io.github.danielhp95.caracole.core.testing.replays.LyricsReplay
import io.github.danielhp95.caracole.core.testing.replays.MatchReplay
import io.github.danielhp95.caracole.core.testing.replays.OverridesReplay
import io.github.danielhp95.caracole.core.testing.replays.PaceReplay
import io.github.danielhp95.caracole.core.testing.replays.PinyinReplay
import io.github.danielhp95.caracole.core.testing.replays.PyReplay
import io.github.danielhp95.caracole.core.testing.replays.RankReplay
import io.github.danielhp95.caracole.core.testing.replays.SearchReplay
import io.github.danielhp95.caracole.core.testing.replays.SettingsReplay
import io.github.danielhp95.caracole.core.testing.replays.SongbookReplay
import io.github.danielhp95.caracole.core.testing.replays.SyncReplay
import io.github.danielhp95.caracole.core.testing.replays.TabFilesReplay
import io.github.danielhp95.caracole.core.testing.replays.UgFetchReplay
import io.github.danielhp95.caracole.core.testing.replays.UgPagesReplay
import io.github.danielhp95.caracole.core.testing.replays.UnicodeReplay

/**
 * One area of the corpus replayed: every record of its vectors answered as Python answered it, each miss told to
 * [Misses]. A lane's JVM test of its area calls its replay (beside its hand-written cases), and CorpusOnDeviceTest
 * runs every one under ART and ICU, one test an area (docs/superpowers/specs/2026-11-03-conformance-corpus.md, "On the
 * device"). An area not built yet replays nothing.
 */
interface AreaReplay {
    val area: String
    fun replay(misses: Misses)
}

/** :core's areas, in the order the device runs them (server.testing.ServerReplays has :server's). Each is its own
 * file of replays/, its lane's to fill; this list is the skeletons'. */
object Replays {
    val all: List<AreaReplay> = listOf(
        UnicodeReplay, KeysReplay, PinyinReplay, FuzzReplay, CanonicalReplay, SearchReplay, IndexReplay, SyncReplay,
        PyReplay, HtmlReplay, HttpReplay, HealthReplay, PaceReplay, LibraryWritesReplay, OverridesReplay,
        UgPagesReplay, RankReplay, MatchReplay, UgFetchReplay, LyricsReplay, LaCuerdaReplay, HarpTabsReplay,
        GameTabsReplay, TabFilesReplay, LookupReplay, LookupScenariosReplay, SettingsReplay, IndexExportReplay,
        SongbookReplay, InboxReplay,
    )

    /** The areas named (every one when [names] is empty), [IllegalArgumentException] for a name no area has. An area
     * is named with hyphens ("job-views"); a name with underscores, as the plan writes some ("job_views"), names it
     * too. */
    fun named(names: Collection<String>, among: List<AreaReplay> = all): List<AreaReplay> {
        if (names.isEmpty()) return among
        val byName = among.associateBy { it.area }
        return names.map {
            byName[it.replace('_', '-')] ?: throw IllegalArgumentException("no corpus area $it (${byName.keys})")
        }
    }
}
