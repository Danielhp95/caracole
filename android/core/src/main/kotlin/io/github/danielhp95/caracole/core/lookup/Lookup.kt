package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.library.LibraryStore

/** What `caracole get` is asked: the song's names (and what its wanted.txt line would say), and the pages a lookup
 * picks (`--ug`, `--tab`, `--lacuerda`, `--harptabs`, `--gametabs`); [songbooks]: its songbooks stage too. */
data class LookupRequest(val artist: String, val title: String, val album: String? = null,
                         val durationMs: Long? = null, val ug: String? = null, val tab: String? = null,
                         val lacuerda: String? = null, val harptabs: String? = null, val gametabs: String? = null,
                         val songbooks: Boolean = true)

/** What a lookup came to, as get.py's `--progress` end says it. */
data class LookupResult(val songId: Long?, val display: String, val states: Map<String, String>,
                        val details: Map<String, String>, val files: Map<String, String>,
                        val secondsToSheet: Double?, val seconds: Double, val requests: Map<String, Int>,
                        val bug: String?, val refused: String?) {
    val ok: Boolean get() = bug == null
}

/** What a lookup tells as it goes, as get.py's `--progress` lines: a stage's state and words, the song once known,
 * and the files a reader can open. */
interface Progress {
    fun stage(name: String, state: String, detail: String = "")
    fun song(id: Long, display: String) {}
    fun readable(files: Map<String, String>, seconds: Double) {}
}

/**
 * get.py on the phone: one song looked up now, its stages in get.py's order ([stages], each its site's), at the
 * lookup pace alone. [run] blocks: the runner calls it inside `database.writeBlocking`, in autocommit, never one
 * transaction, so each event, block and kv record commits as it happens.
 */
class Lookup(val cfg: PhoneConfig, val database: Database, val store: LibraryStore, val clients: Clients,
             val pages: SongPages, val songbooks: SongbookPages, val alerts: Alerts, val request: LookupRequest,
             val progress: Progress, val pacing: Pacing, val stages: SiteStages = SiteStages.ALL) {
    fun run(db: Db): LookupResult = TODO("lane lookup")
}
