package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.core.catalogues.Named
import io.github.danielhp95.caracole.core.catalogues.date
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import io.github.danielhp95.caracole.server.jobs.QueueFull
import io.github.danielhp95.caracole.server.lookups.CataloguesRunner
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull
import java.time.Duration
import java.time.Instant
import java.util.Collections

/**
 * What the app says and decides of the site catalogues (CataloguesRunner's job, Settings' row and the first start's
 * card), apart from Android, so that a JVM test holds it: the date Settings shows ([newest], [day], [age]), whether the
 * first start offers them ([offers]), and the question a metered network leaves ([asking], [asks]). Its words are the
 * app's strings.xml; the ones it makes here are the job's ([size]) and core.catalogues' ([day]).
 */
object SiteCatalogues {
    /** kv: when the first start offered the catalogues, so it offers them once. */
    const val OFFERED = "catalogues:offered"

    /** The newest of the sites' indexes' times (IndexTransfer.newest's), none for none; a time Stamps can't read is
     * none. */
    fun newest(times: Map<String, String>): Instant? = times.values.mapNotNull { stamp ->
        try {
            Stamps.parse(stamp)?.let(Stamps::instant)
        } catch (e: ArithmeticException) {
            null
        }
    }.maxOrNull()

    /** [at]'s day in UTC as "3 Nov 2026", English months from core.catalogues' table. */
    fun day(at: Instant): String = date(Named(0, at))

    /** How old a time is, as Settings says it: today, then days to 13, weeks to 8, months (of 30 days) to 11, years. */
    enum class Unit { TODAY, DAYS, WEEKS, MONTHS, YEARS }

    data class Age(val unit: Unit, val count: Int)

    /** How old [at] is at [now], in whole days (a time after [now], a laptop's clock ahead, is today's). */
    fun age(at: Instant, now: Instant): Age {
        val days = Duration.between(at, now).toDays()
        return when {
            days < 1 -> Age(Unit.TODAY, 0)
            days < 14 -> Age(Unit.DAYS, days.toInt())
            days < 60 -> Age(Unit.WEEKS, (days / 7).toInt())
            days < 365 -> Age(Unit.MONTHS, (days / 30).toInt())
            else -> Age(Unit.YEARS, (days / 365).toInt())
        }
    }

    /** Whether the first start offers the catalogues: no computer set ([server] blank), no site's index holds a tab
     * ([counts], TabCounts.of's), and never offered before ([offered], kv [OFFERED]). */
    fun offers(server: String, counts: Map<String, Long>, offered: String?): Boolean =
        server.isBlank() && counts.values.all { it == 0L } && offered == null

    /** The file a metered network left waiting for the owner's go-ahead (kv `catalogues:asking`). */
    data class Asking(val name: String, val bytes: Long)

    /** kv `catalogues:asking`'s text read: `{"name": text, "bytes": number}`, none else. */
    fun asking(text: String?): Asking? {
        val doc = try {
            text?.let(PyJson::loads)
        } catch (e: Exception) {
            null
        } as? JsonObject ?: return null
        val name = (doc["name"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return null
        val bytes = (doc["bytes"] as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull ?: return null
        return Asking(name, bytes)
    }

    /** The question to ask after a catalogues job ended [state] with its line's [tone]: the file waiting, when the job
     * stopped for a metered network (done, its line a wait: the kind's otherwise) and [asking] names it; none else. */
    fun asks(state: String, tone: String, asking: Asking?): Asking? =
        if (state == Job.DONE && tone == WAITING) asking else null

    /** Whether a job in [state] is over: done, failed, cancelled, or cut short by the app's end. */
    fun over(state: String): Boolean = state in OVER

    /** The catalogues' job queued ([meteredOk]: the owner's go-ahead on a metered network), as BackupsActivity queues
     * a backup; the job waiting or running answers a second tap (CataloguesRunner.spec); null when the queue is full.
     * Its end is then still to be said ([toSay]). */
    fun queue(phone: Phone, meteredOk: Boolean): Job? = try {
        phone.queue.submit(phone.catalogues.spec(meteredOk)).first.also { unsaid += it.id }
    } catch (_: QueueFull) {
        null
    }

    /** Whether the end of job [id], one the app queued ([queue]), is still to be said (its question asked): true
     * once, so that a screen that follows it twice, or opens after it ended, asks once. */
    fun toSay(id: Int): Boolean = unsaid.remove(id)

    /** The newest of [jobs] that is a catalogues job, none for none. */
    fun newestOf(jobs: List<Job>): Job? = jobs.filter { it.spec.kind == PhoneKinds.CATALOGUES.kind }.maxByOrNull { it.id }

    /** A size as the job says one ("52 MB"). */
    fun size(bytes: Long): String = CataloguesRunner.size(bytes)

    private const val WAITING = "waiting"
    private val OVER = setOf(Job.DONE, Job.FAILED, Job.CANCELLED, Job.INTERRUPTED)
    private val unsaid: MutableSet<Int> = Collections.synchronizedSet(HashSet())
}
