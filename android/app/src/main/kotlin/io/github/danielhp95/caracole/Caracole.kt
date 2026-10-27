package io.github.danielhp95.caracole

import android.content.Context
import io.github.danielhp95.caracole.mirror.Http
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.mirror.Progress
import kotlinx.coroutines.flow.MutableStateFlow

/** What the app's parts share in its process: the one [Mirror], and where the sync stands ([status]). */
object Caracole {
    @Volatile private var mirror: Mirror? = null

    /** The copy of the library, in the app's files folder: `blobs/` and `manifest.json`. */
    fun mirror(context: Context): Mirror = mirror ?: synchronized(this) {
        mirror ?: Mirror(context.applicationContext.filesDir).also { mirror = it }
    }

    fun http() = Http(userAgent = "caracole-android/${BuildConfig.VERSION_NAME}")

    /** Where the sync stands, for the screens that show it. */
    val status = MutableStateFlow<SyncState>(SyncState.Idle)
}

/** Where a sync stands. */
sealed interface SyncState {
    data object Idle : SyncState

    /** Running: [progress] is null while it asks caracole for the list. */
    data class Running(val progress: Progress?) : SyncState

    /** Over, with its [outcome]. */
    data class Ended(val outcome: Outcome) : SyncState
}

/** How a sync ended, [at] a time: [ok], and what it did ([text]: "12 files new, 2 removed") or why it failed. */
data class Outcome(val at: Long, val ok: Boolean, val text: String)
