package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.mirror.Mirror
import kotlinx.serialization.json.JsonObject

/** M2–M3's page data: the mirror's index.html data block, its cards re-identified to the phone's ids, tombstoned
 * songs dropped, phone-only songs given minimal cards (lane library-page). */
class MirrorPageData(val mirror: Mirror?) : PageData, SongCards {
    override fun data(db: Db, now: String): JsonObject = TODO("lane library-page")
    override fun cards(db: Db, songs: List<SongRow>): Map<Long, JsonObject> = TODO("lane library-page")
}
