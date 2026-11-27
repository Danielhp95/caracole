package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.core.index.Sizes
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import io.github.danielhp95.caracole.server.lookups.ModelsRunner

/**
 * What Settings' "Chords from audio" row says and offers (the chords-on-the-phone design's §8.3), apart from Android,
 * so that a JVM test holds it: its line ([Line], each strings.xml's `chords_*`: "Not downloaded · 54 MB",
 * "Downloading · 21 of 54 MB", "Ready · 54 MB on the phone", "Not downloaded: {why}", "Waiting for your go-ahead (a
 * metered network)"), and whether Download and Remove are offered. Its facts: the models' size in this build
 * ([of]'s `bytes`, none for a build that carries none), ModelsRunner.ready's answer, what keeps this phone from
 * making chords whatever the models ([cant]: its Android, its processor, its memory), and the newest models job
 * ([Last]: the Journal's, whoever queued it). The metered stop is the job's own line (the kind's `otherwise`), so it
 * is read from the job, never from a record of its own (there is no `models:asking`).
 */
object ChordModelsRow {
    enum class Line { NOT_DOWNLOADED, DOWNLOADING, READY, CANT, WAITING }

    /** The row: its [line] with its [text] filled in (a size, a count, a why), and what it offers. */
    data class Row(val line: Line, val text: String, val download: Boolean, val remove: Boolean)

    /** The newest models job: its state, its stage's detail, and its progress (done and total bytes, none before). */
    data class Last(val state: String, val detail: String, val done: Long? = null, val total: Long? = null)

    /** The newest models job of [jobs], as [Last]; none for none. */
    fun lastOf(jobs: List<Job>): Last? {
        val job = jobs.filter { it.spec.kind == PhoneKinds.MODELS.kind }.maxByOrNull { it.id } ?: return null
        val stage = job.stages.firstOrNull()
        return Last(job.state, stage?.detail.orEmpty(), stage?.done, stage?.total)
    }

    fun of(bytes: Long?, ready: String?, cant: String?, last: Last?): Row {
        if (bytes == null) return Row(Line.CANT, ModelsRunner.NOT_CARRIED, download = false, remove = false)
        val size = Sizes.size(bytes)
        if (last != null && (last.state == Job.QUEUED || last.state == Job.RUNNING)) {
            return Row(Line.DOWNLOADING, Sizes.of(last.done ?: 0, last.total ?: bytes), download = false, remove = false)
        }
        if (ready == null) return Row(Line.READY, size, download = false, remove = true)
        if (cant != null) return Row(Line.CANT, cant, download = false, remove = false)
        if (last != null && last.state == Job.DONE && last.detail.endsWith(WAITING)) {
            return Row(Line.WAITING, size, download = true, remove = false)
        }
        if (last != null && last.state == Job.FAILED && last.detail.startsWith(FAILED)) {
            return Row(Line.CANT, last.detail.removePrefix(FAILED), download = true, remove = false)
        }
        if (last != null && last.state == Job.DONE && last.detail.isNotEmpty() && !last.detail.startsWith(READY)) {
            return Row(Line.CANT, last.detail, download = true, remove = false)  // GitHub's wait, in its words
        }
        return Row(Line.NOT_DOWNLOADED, size, download = true, remove = false)
    }

    /** The kind's metered stop after its size: "… to download: waiting for your go-ahead in Settings (a metered
     * network)". */
    private val WAITING = PhoneKinds.MODELS.otherwise!!.substringAfter("{size}")
    private val FAILED = PhoneKinds.MODELS.failed.substringBefore("{why}")
    private val READY = PhoneKinds.MODELS.done.substringBefore("{size}")
}
