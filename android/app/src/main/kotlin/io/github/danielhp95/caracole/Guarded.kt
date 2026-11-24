package io.github.danielhp95.caracole

import kotlinx.coroutines.CancellationException

/**
 * [block]'s value, or what it threw: anything, an Error among them (the phone's caracole that can't start: the bundled
 * SQLite's native library that won't load, a database too new after a downgrade, a disk full during an update's
 * migration), so that a screen says it rather than crash, as the library screen says "Couldn't start · …"; a
 * cancellation goes on, as the screen's work stops with it.
 */
internal inline fun <T> guarded(block: () -> T): Result<T> = try {
    Result.success(block())
} catch (e: CancellationException) {
    throw e
} catch (e: Throwable) {
    Result.failure(e)
}

/** [e] in its own words, else by its name ("UnsatisfiedLinkError"). */
internal fun why(e: Throwable): String = e.message?.takeIf { it.isNotBlank() } ?: e.javaClass.simpleName
