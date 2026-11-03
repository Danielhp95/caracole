package io.github.danielhp95.caracole.server.routes.search

/**
 * The offline indexes' answers kept a while, by query (WebApp's `_found`): [SECONDS] old at most, the [SIZE] made
 * last, the oldest going first. An answer made again for a query takes its place where it was, as a dict's does.
 * [clear] drops them all: after an index import or a sync, the indexes hold what an answer from before lacks; and an
 * answer begun before a clear ([since], its [era]) is not kept once made, since it may have read the indexes as they
 * were.
 */
internal class AnswerCache<T : Any>(
    private val size: Int = SIZE,
    private val seconds: Double = SECONDS,
    /** A monotonic clock, in seconds (time.monotonic). */
    var now: () -> Double = { System.nanoTime() / 1e9 },
) {
    private val kept = LinkedHashMap<String, Pair<Double, T>>()
    private var cleared = 0L

    /** How many times the answers were dropped: what an answer begun now is made since. */
    @get:Synchronized
    val era: Long get() = cleared

    /** The answer kept for [query], unless it is [seconds] old or more. */
    @Synchronized
    fun get(query: String): T? {
        val (made, answer) = kept[query] ?: return null
        return answer.takeIf { now() - made < seconds }
    }

    /** [answer] kept for [query], unless the answers were dropped since it was begun ([since], the [era] then). */
    @Synchronized
    fun put(query: String, answer: T, since: Long = cleared) {
        if (since != cleared) return
        kept[query] = now() to answer
        val oldest = kept.keys.iterator()
        while (kept.size > size) {
            oldest.next()
            oldest.remove()
        }
    }

    @Synchronized
    fun clear() {
        kept.clear()
        cleared++
    }

    @get:Synchronized
    val count: Int get() = kept.size

    companion object {
        const val SIZE = 128
        const val SECONDS = 300.0
    }
}
