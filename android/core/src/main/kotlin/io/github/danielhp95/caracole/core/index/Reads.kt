package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.db.Db

/**
 * The index pages the phone's lookups stored, for the next push to the computer (`POST /peer/index`): each noted as
 * it is stored, kv `phone:read:<site>:<page>` = its stamp, and kv `phone:pushed:<peer id>` = the last push's stamp.
 * A site lane calls [note] for each index row a lookup stores; lane index-push reads [since] and [forget]s.
 */
object Reads {
    const val READ = "phone:read:"
    const val PUSHED = "phone:pushed:"

    /** [page] of [site] stored at [at]. */
    fun note(db: Db, site: String, page: String, at: String) {
        require(':' !in site) { "a site's name holds no colon: $site" }
        db.kvSet("$READ$site:$page", at)
    }

    /** The pages noted since the last push to [peer] (all of them before the first), by site, in each site's
     * order of its pages' names. */
    fun since(db: Db, peer: String): Map<String, List<String>> {
        val pushed = db.kvGet(PUSHED + peer)
        val out = sortedMapOf<String, MutableList<String>>()
        db.query("SELECT key, value FROM kv WHERE key >= ? AND key < ? ORDER BY key", READ, READ.dropLast(1) + ";") {
            it.text(0)!! to it.text(1)!!
        }.forEach { (key, at) ->
            if (pushed != null && at <= pushed) return@forEach
            val rest = key.removePrefix(READ)
            out.getOrPut(rest.substringBefore(':')) { mutableListOf() }.add(rest.substringAfter(':'))
        }
        return out
    }

    /** A push to [peer] answered: the pages noted up to [upTo] forgotten, and [upTo] the last push's stamp. */
    fun forget(db: Db, peer: String, upTo: String) {
        db.savepoint("reads_forget") {
            db.execute("DELETE FROM kv WHERE key >= ? AND key < ? AND value <= ?", READ, READ.dropLast(1) + ";", upTo)
            db.kvSet(PUSHED + peer, upTo)
        }
    }
}
