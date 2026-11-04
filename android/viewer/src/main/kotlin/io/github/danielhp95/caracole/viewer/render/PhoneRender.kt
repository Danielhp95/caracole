package io.github.danielhp95.caracole.viewer.render

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.lookup.RenderStats
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.mirror.Mirror
import java.io.File

/**
 * The phone renders its own pages (lane phone-render): render.py's page path with no PDF, for the songs no mirror page
 * serves at their unit's digest; every song's progressions recorded. It is the lookup's pdf stage ([seam]), what
 * follows a sync's take ([afterSync]), and the render job (PhoneKinds' render kind, keyed by [build]), which the phone
 * queues itself, never this class: at its start when [stale] (Phone.start, once the app has wired the queue), and
 * after a take that owes pages; the job runs [renderStale]. [version] is the app's, part of [build].
 *
 * Neutral until its lane lands: it makes no page, as [SongPages.NONE] does, and nothing is stale. Open, so a test of
 * the phone's wiring can stand a stale one in its place.
 */
open class PhoneRender(val database: Database, val libraryDir: File, val mirror: Mirror?, val version: String) :
    SongPages {
    /** The songs' pages made (each song in its own write; [between] runs between two songs, holding no write). */
    override fun render(db: Db, songIds: Collection<Long>, between: (() -> Unit)?): RenderStats = RenderStats()

    /** What the lookup's pdf stage calls (Assembly gives it as PhoneParts.pages): [SongPages.NONE] while this is
     * neutral, so the stage says get.py's no-PDF words; this lane makes it `this`. */
    open val seam: SongPages get() = SongPages.NONE

    /** Whether the phone owes pages: made by another build than this one (kv `phone:render-build`), or forgotten by a
     * take and not made since, so the render job is queued at start. */
    open fun stale(): Boolean = false

    /** The phone's build stamp: the viewer's assets and data hashed, and the app's [version]. */
    open fun build(): String = TODO("lane phone-render")

    /** The pages owed made ([stale]'s songs), [between] two songs (the job's yieldToQueued: the lookups queued
     * meanwhile run first), [progress] told how far (done, total). */
    open fun renderStale(between: () -> Unit, progress: (done: Int, total: Int) -> Unit = { _, _ -> }): RenderStats =
        TODO("lane phone-render")

    /** After a sync's take, inside the sync's job (lane written-pages): the phone's pages of the units it moved
     * forgotten, and whether pages are owed now (those the mirror doesn't serve). It makes none itself: the phone
     * queues the render job for them after the sync, so the sync ends when its stages do and a lookup goes first.
     * Neutral: nothing, and none owed. */
    open fun afterSync(): Boolean = false
}
