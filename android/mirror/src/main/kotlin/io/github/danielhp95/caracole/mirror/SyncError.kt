package io.github.danielhp95.caracole.mirror

/** Why a sync or a test of the server failed, as one plain sentence ([message]) the app shows as it is. */
sealed class SyncError(message: String, cause: Throwable? = null) : Exception(message, cause) {
    /**
     * Whether it says there is no caracole at the address: none typed, nothing answering there, or something
     * else answering (another network's device, a Wi-Fi login page). The sync on Wi-Fi keeps quiet about these.
     */
    val noCaracole: Boolean get() = this is NoAddress || this is BadAddress || this is NoAnswer || this is NotCaracole

    /** No address typed yet. */
    class NoAddress : SyncError("No computer's address yet. Type it in Settings.")

    /** The address typed isn't one the app can ask. */
    class BadAddress(text: String) :
        SyncError("“$text” isn't an address. Type one like http://192.168.1.20:8737.")

    /** Nothing answered there (refused, unreachable, timed out, or the connection broke). */
    class NoAnswer(address: ServerAddress, why: String, cause: Throwable? = null) :
        SyncError("No answer from $address ($why).", cause)

    /** Something answered, but not with caracole's offline list. */
    class NotCaracole(address: ServerAddress, why: String) :
        SyncError("$address answered, but isn't a caracole that shares its book ($why).")

    /**
     * caracole answered that it can't share its library now (HTTP 503: its written library page isn't the one
     * it recorded, say, until a command writes the pages again); [why] is its own sentence.
     */
    class Unavailable(address: ServerAddress, why: String) :
        SyncError("$address can't share its book now: $why")

    /** A caracole whose list has a format this app doesn't know. */
    class NewerFormat(format: Any?) :
        SyncError("The computer's caracole is newer than the app (list format $format). Update the app.")

    /** caracole's list, read, says something the app can't use. */
    class BadManifest(why: String) : SyncError("The computer's list of pages is unusable: $why.")

    /** A listed file didn't come as listed: the library changed while the sync ran. */
    class Changed(path: String, why: String) :
        SyncError("“$path” changed on the computer while we copied ($why). Sync again.")

    /** The phone's own storage failed. */
    class Storage(why: String, cause: Throwable? = null) : SyncError("The phone's storage failed: $why.", cause)

    /** The sync was stopped before it ended; the mirror is as it was. */
    class Cancelled : SyncError("Stopped before the end. The phone's copy is as it was.")

    /** Anything else that went wrong, which the app didn't expect: said as it is, rather than a crash. */
    class Unexpected(cause: Throwable) : SyncError(
        "Unexpected error (${cause.javaClass.simpleName}${cause.message?.let { ": $it" } ?: ""}).",
        cause,
    )

    companion object {
        /** [e] as a SyncError: itself, or [Unexpected]. */
        fun of(e: Throwable): SyncError = e as? SyncError ?: Unexpected(e)
    }
}
