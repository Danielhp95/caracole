package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.ProviderState
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import java.time.Instant

/**
 * What asking a site came to, the envelope every stage and lookup command asks through (get.py's `_Lookup._ask`):
 * its work's value ([Done]), or why it sent nothing more: the provider turned off ([Off]), cooling down ([Cooling]),
 * blocked just now ([Blocked], with the cooldown it began), the lookup's or the hour's budget spent ([Spent], and
 * whether what is left is kept for sheets, `get.SHEETS_SHARE`), or a provider's error ([Failed]). Never a miss.
 */
sealed interface Asked<out T> {
    data class Done<T>(val value: T) : Asked<T>
    data class Off(val why: String) : Asked<Nothing>
    data class Cooling(val until: Instant?) : Asked<Nothing>
    data class Blocked(val error: ProviderBlocked, val state: ProviderState) : Asked<Nothing>
    data class Spent(val hour: Boolean, val keptForSheets: Boolean) : Asked<Nothing>
    data class Failed(val error: ProviderError) : Asked<Nothing>
}

/** A lookup's asking: [ask] runs [work] with the provider's client at the lookup pace, and [requests] counts what
 * each provider was sent. Lane lookup's InteractiveAsk; a test's FakeAsking. */
interface Asking {
    fun <T> ask(provider: String, policy: ProviderPolicy? = null, work: (Client) -> T): Asked<T>
    val requests: Map<String, Int>
}

/** What a site's stage of a lookup reads: the database (autocommit), the song, the overrides and settings now, the
 * library, the asking and the lookup's time. */
data class StageContext(val db: Db, val song: SongRow, val overrides: Overrides, val config: PhoneConfig,
                        val library: LibraryStore, val asking: Asking, val now: Instant)

/** How a stage ended: done, skipped or failed, and get.py's words for it. */
data class StageEnd(val state: String, val detail: String)

/** One site's stage of `caracole get` (get.py's), in its site lane's file of core/lookup/sites/. */
fun interface SiteStage {
    fun run(ctx: StageContext): StageEnd
}

/** A lookup's site stages, in get.py's order; [ALL] the phone's. */
class SiteStages(val match: SiteStage, val ugSheet: SiteStage, val ug: SiteStage, val lacuerdaPick: SiteStage,
                 val lacuerda: SiteStage, val lrclib: SiteStage, val megalobiz: SiteStage, val azlyrics: SiteStage,
                 val gtptabs: SiteStage, val harptabs: SiteStage, val gametabs: SiteStage) {
    companion object {
        val ALL: SiteStages = SiteStages(
            match = io.github.danielhp95.caracole.core.lookup.sites.MatchStage,
            ugSheet = io.github.danielhp95.caracole.core.lookup.sites.UgSheetStage,
            ug = io.github.danielhp95.caracole.core.lookup.sites.UgStage,
            lacuerdaPick = io.github.danielhp95.caracole.core.lookup.sites.LaCuerdaPickStage,
            lacuerda = io.github.danielhp95.caracole.core.lookup.sites.LaCuerdaStage,
            lrclib = io.github.danielhp95.caracole.core.lookup.sites.LrclibStage,
            megalobiz = io.github.danielhp95.caracole.core.lookup.sites.MegalobizStage,
            azlyrics = io.github.danielhp95.caracole.core.lookup.sites.AzLyricsStage,
            gtptabs = io.github.danielhp95.caracole.core.lookup.sites.GtpTabsStage,
            harptabs = io.github.danielhp95.caracole.core.lookup.sites.HarpTabsStage,
            gametabs = io.github.danielhp95.caracole.core.lookup.sites.GameTabsStage,
        )
    }
}

/** What a lookup command (`versions --keep`, `lacuerda --artist` and `--search`, `harptabs --artist`) reads, and
 * [say], a line of its output. */
interface CommandContext {
    val db: Db
    val asking: Asking
    val now: Instant
    fun say(line: String)
}
