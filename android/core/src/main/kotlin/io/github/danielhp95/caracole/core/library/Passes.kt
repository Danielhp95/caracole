package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.http.ProviderError
import kotlin.reflect.KClass

/**
 * provider_pass.PassStats: what a pass did, whatever its provider: the songs [tried] (errors included), the [errors],
 * whether the budget ran out, and [failures]: the songs a provider's error left for the next run, each with its error.
 */
open class PassStats(var tried: Int = 0, var errors: Int = 0, var budgetExhausted: Boolean = false,
                     val failures: MutableList<Pair<SongRow, ProviderError>> = mutableListOf())

/** provider_pass.py: one song at a time through a provider, its ladder of errors that are never misses. */
object Passes {
    fun <S : PassStats> eachSong(songs: List<SongRow>, stats: S, site: String,
                                 stopOn: Set<KClass<out ProviderError>> = emptySet(),
                                 onError: ((SongRow, ProviderError) -> Unit)? = null, turn: (SongRow) -> Unit): S =
        TODO("lane library-writes")
}
