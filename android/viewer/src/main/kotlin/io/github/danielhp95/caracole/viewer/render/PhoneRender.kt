package io.github.danielhp95.caracole.viewer.render

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.lookup.RenderStats
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.mirror.Mirror
import java.io.File

/**
 * The phone renders its own pages (lane phone-render): render.py's page path with no PDF, for the songs no mirror page
 * serves at their unit's digest; every song's progressions recorded. It is the lookup's pdf stage ([render]), what
 * follows a sync's take ([afterSync]), and the render job the phone queues at start once its build changed ([stale],
 * [renderStale]: PhoneKinds' render kind, keyed by [build]).
 *
 * Neutral until its lane lands: it makes no page, as [SongPages.NONE] does, and nothing is stale.
 */
class PhoneRender(val database: Database, val libraryDir: File, val mirror: Mirror?) : SongPages {
    /** The songs' pages made (each song in its own write; [between] runs between two songs, holding no write). */
    override fun render(db: Db, songIds: Collection<Long>, between: (() -> Unit)?): RenderStats = RenderStats()

    /** Whether the phone's pages were made by another build than this one (kv `phone:render-build`), so the render
     * job is queued at start. */
    fun stale(): Boolean = false

    /** The phone's build stamp: the viewer's assets and data hashed, and the app's version. */
    fun build(): String = TODO("lane phone-render")

    /** Every song's pages made again by this build, [between] two songs (the job's yieldToQueued: the lookups queued
     * meanwhile run first), [progress] told how far (done, total). */
    fun renderStale(between: () -> Unit, progress: (done: Int, total: Int) -> Unit = { _, _ -> }): RenderStats =
        TODO("lane phone-render")

    /** After a sync's take: the phone's pages of the units it moved forgotten, and those the mirror doesn't serve
     * made (lane written-pages). Neutral: nothing. */
    fun afterSync() {}
}
