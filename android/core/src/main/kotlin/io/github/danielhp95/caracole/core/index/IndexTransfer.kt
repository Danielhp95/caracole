package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.db.Db
import java.io.File

/** index_transfer.py's merge on the phone: a `caracole index export` file into the database (lane index-transfer). */
object IndexTransfer {
    const val FORMAT = "1"

    /** The export's sites into [db]: called inside Database.write. */
    fun merge(db: Db, export: File, now: String, sites: List<String>? = null, backup: (() -> Unit)? = null): Merged =
        TODO("lane index-transfer")

    /** The kv records a fresh Python database holds (caracole/schema/fresh_kv.json). */
    fun seedFresh(db: Db): Unit = TODO("lane index-transfer")

    /** Per site, the newest read time: the state document's "indexes". */
    fun newest(db: Db): Map<String, String> = TODO("lane index-transfer")
}

data class Merged(val sites: Map<String, Map<String, Int>>, val changed: Boolean)

class TransferError(message: String) : Exception(message)
