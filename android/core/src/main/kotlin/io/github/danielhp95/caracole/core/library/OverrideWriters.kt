package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import kotlinx.serialization.json.JsonElement

/** overrides.py's add_* writers on the phone: each writes `phone_overrides` exactly as song_entries yields after the
 * same add on the computer. */
object OverrideWriters {
    fun addMatch(db: Db, display: String, ugRef: String): Unit = TODO("lane overrides-model")
    fun addPin(db: Db, display: String, urls: List<String>): Unit = TODO("lane overrides-model")
    fun removePin(db: Db, display: String, tabs: Set<Long>?): Boolean = TODO("lane overrides-model")
    fun addLacuerda(db: Db, display: String, url: String): Unit = TODO("lane overrides-model")
    fun addHarptabs(db: Db, display: String, url: String): Unit = TODO("lane overrides-model")
    fun addGametabs(db: Db, display: String, url: String): Unit = TODO("lane overrides-model")
    fun addReject(db: Db, display: String, refs: List<String>): Unit = TODO("lane overrides-model")
    fun addAlias(db: Db, sourceArtist: String, ugArtist: String): Unit = TODO("lane overrides-model")
    fun addIgnore(db: Db, display: String): Unit = TODO("lane overrides-model")
    fun addVersion(db: Db, display: String, query: String?, keyVersion: (String) -> Boolean): Unit =
        TODO("lane overrides-model")
    fun addHarmonica(db: Db, display: String, tab: String, reading: JsonElement?, checkSpec: (JsonElement) -> Unit): Unit =
        TODO("lane overrides-model")
}
