package io.github.danielhp95.caracole

import android.util.Log
import kotlinx.coroutines.CancellationException

/**
 * [block]'s value, or what it threw, logged with [what] failed ([Guards.log]): anything, an Error among them (the
 * phone's caracole that can't start: the bundled SQLite's native library that won't load, a database too new after a
 * downgrade, a disk full during an update's migration), so that a screen says it rather than crash, as the library
 * screen says "Couldn't start · …". The VM's own errors (out of memory, a stack overflow) and a cancellation go on:
 * nothing a screen says helps the one, and the other is its work stopping.
 */
internal inline fun <T> guarded(what: String, block: () -> T): Result<T> = try {
    Result.success(block())
} catch (e: CancellationException) {
    throw e
} catch (e: VirtualMachineError) {
    throw e
} catch (e: Throwable) {
    Guards.log(what, e)
    Result.failure(e)
}

/** Where [guarded] logs a failure: Android's log, a test's list. */
internal object Guards {
    private const val TAG = "caracole"

    @Volatile var log: (String, Throwable) -> Unit = { what, e -> Log.w(TAG, what, e) }
}

/** [e] in its own words, else by its name ("UnsatisfiedLinkError"). */
internal fun why(e: Throwable): String = e.message?.takeIf { it.isNotBlank() } ?: e.javaClass.simpleName
