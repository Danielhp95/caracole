package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.db.Db
import java.io.File

/** index_transfer.Exported: the file made, its sites, each table's rows and its size. */
data class Exported(val path: File, val sites: List<String>, val rows: Map<String, Int>, val size: Long)

/** index_transfer.export(pages=) on the phone: the pages [Reads] noted, as an index export the computer merges. */
object IndexExport {
    fun export(db: Db, to: File, pages: Map<String, List<String>>): Exported = TODO("lane index-push")
}
