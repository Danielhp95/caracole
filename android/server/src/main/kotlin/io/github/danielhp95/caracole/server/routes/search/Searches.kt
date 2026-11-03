package io.github.danielhp95.caracole.server.routes.search

import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/** A search a newer one of its box has typed over: thrown between two of its queries, answered `superseded`. */
internal class Superseded : RuntimeException("typed over", null, false, false)

/**
 * caracole serve's searching on the phone (search_routes.api_search, WebApp's `_searching`, `_tickets` and
 * `_newest`): one search at a time, in the order they were asked (a fair lock), and of each search box ([BOXES] of
 * them, those that asked last) its newest search alone, so that a query typed on in a box stops that box's older
 * ones, waiting or running, and never another box's: another page's, or another person's phone's.
 *
 * Python's SQLite interrupts a running query from its progress handler; the bundled SQLite has none, so a search
 * looks between two of its queries ([Ticket.check]) and once more as it ends: an older search of its box answers
 * `{query, superseded: true}` then, and the page asks again if it still wants it.
 */
internal class Searches(private val boxes: Int = BOXES) {
    private val lock = ReentrantLock(true)
    private var asked = 0L
    private val newest = LinkedHashMap<String, Long>()

    /** One search, of [box]: newer than every one asked before it. */
    inner class Ticket internal constructor(private val box: String, private val number: Long) {
        /** Whether a newer search of its box was asked since. A box forgotten ([BOXES] asked since) has this one as
         * its newest. */
        val over: Boolean get() = synchronized(newest) { (newest[box] ?: number) != number }

        /** [Superseded] once [over]: between two queries. */
        fun check() {
            if (over) throw Superseded()
        }
    }

    /** The search of [box] asked now, the newest of its box. */
    fun ask(box: String): Ticket = synchronized(newest) {
        val number = ++asked
        newest.remove(box)
        newest[box] = number
        val forget = newest.keys.iterator()
        while (newest.size > boxes) {
            forget.next()
            forget.remove()
        }
        Ticket(box, number)
    }

    /**
     * [block] for the search of [box] asked now, once every search asked before it is over; null when a newer search
     * of [box] was asked before it began, while it ran (its block's [Ticket.check]) or as it ended.
     */
    fun <T : Any> search(box: String, block: (Ticket) -> T): T? {
        val ticket = ask(box)
        return lock.withLock {
            try {
                ticket.check()
                block(ticket).also { ticket.check() }
            } catch (e: Superseded) {
                null
            }
        }
    }

    /** [block] alone, with no search beside it (/api/artist, which reads as a search does). */
    fun <T> alone(block: () -> T): T = lock.withLock(block)

    /** How many wait for their turn (an estimate, for a test that waits for one to wait). */
    val waiting: Int get() = lock.queueLength

    companion object {
        /** The search boxes whose newest search is kept: those that asked last. */
        const val BOXES = 256
    }
}
