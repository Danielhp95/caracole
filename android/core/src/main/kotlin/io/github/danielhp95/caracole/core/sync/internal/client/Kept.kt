package io.github.danielhp95.caracole.core.sync.internal.client

import java.security.SecureRandom
import java.time.Instant

/** Values kept by id for [seconds], each forgotten once older (a comparison, kept for the Sync tab's choices). */
internal class Kept<T>(private val seconds: Long) {
    private val lock = Any()
    private val values = LinkedHashMap<String, Pair<T, Instant>>()

    fun put(id: String, value: T, now: Instant) = synchronized(lock) {
        forget(now)
        values[id] = value to now
    }

    /** The value of [id] kept within [seconds] of [now]; null for one older, or never kept. */
    fun get(id: String, now: Instant): T? = synchronized(lock) {
        forget(now)
        values[id]?.first
    }

    /** [id]'s value forgotten. */
    fun remove(id: String) = synchronized(lock) {
        values.remove(id)
        Unit
    }

    private fun forget(now: Instant) {
        values.entries.removeIf { (_, kept) -> !now.isBefore(kept.second.plusSeconds(seconds)) }
    }

    companion object {
        private val random = SecureRandom()

        /** 16 hex, random: a comparison's id, a temporary file's name. */
        fun newId(): String = ByteArray(8).also(random::nextBytes).joinToString("") { "%02x".format(it) }
    }
}
