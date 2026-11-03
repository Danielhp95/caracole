package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.db.Db
import kotlinx.serialization.json.JsonObject

/** harptabs.com's and gametabs.net's keys and index states (lane search-sites). */
object SiteKeys {
    fun harptabsEnsureCurrentKeys(db: Db): Int = TODO("lane search-sites")
    fun gametabsEnsureCurrentKeys(db: Db): Int = TODO("lane search-sites")
    fun harptabsIndexState(db: Db): JsonObject = TODO("lane search-sites")
    fun gametabsIndexState(db: Db): JsonObject = TODO("lane search-sites")
}
