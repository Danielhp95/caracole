package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.http.ProviderUnavailable
import kotlin.reflect.KClass

/**
 * provider_pass.PassStats: what a pass did, whatever its provider: the songs [tried] (errors included), the [errors],
 * whether the budget ran out, and [failures]: the songs a provider's error left for the next run, each with its error,
 * the errors counted, then the songs not asked about once the client gave up on the provider for the run.
 */
open class PassStats(var tried: Int = 0, var errors: Int = 0, var budgetExhausted: Boolean = false,
                     val failures: MutableList<Pair<SongRow, ProviderError>> = mutableListOf())

/**
 * provider_pass.py: one song at a time through a provider, the ladder every per-song pass climbs (lyrics, LaCuerda,
 * gtptabs.com, harptabs.com, gametabs.net). Errors are never misses:
 *
 * - a block ([ProviderBlocked]) propagates;
 * - a spent budget ([BudgetExhausted]) ends the pass (`budgetExhausted`), the song not counted;
 * - once the client gives up on the provider for the run ([ProviderUnavailable]), the pass ends and every song left,
 *   that one first, is a failure with that error, never asked about and no error of its own;
 * - any other [ProviderError] counts the song in `tried` and `errors`, names it in `failures` with its error, is told
 *   to `onError`, and leaves the song for the next run; the pass goes on, unless the error is one of `stopOn`.
 *
 * A song that answers counts in `tried`. Python's `site` names the provider in its log; the phone keeps no such log.
 */
object Passes {
    /**
     * each_song itself: each song's [turn], in order, and what it came to, for the songs it came to something for, as
     * the caller takes them. [songs] is read lazily, a song just before its turn, so a filter in it sees what the
     * turns before did; and the caller's work on an answer runs outside the ladder, as Python's loop body does, so
     * an error of its own is never one of the pass's.
     */
    fun <T> eachSong(songs: Sequence<SongRow>, stats: PassStats, @Suppress("UNUSED_PARAMETER") site: String,
                     stopOn: Set<KClass<out ProviderError>> = emptySet(),
                     onError: ((SongRow, ProviderError) -> Unit)? = null,
                     turn: (SongRow) -> T): Sequence<Pair<SongRow, T>> = sequence {
        val left = songs.iterator()
        while (left.hasNext()) {
            val song = left.next()
            val outcome = try {
                turn(song)
            } catch (e: ProviderBlocked) {
                throw e
            } catch (_: BudgetExhausted) {
                stats.budgetExhausted = true
                return@sequence
            } catch (e: ProviderUnavailable) {
                stats.failures += song to e
                while (left.hasNext()) stats.failures += left.next() to e
                return@sequence
            } catch (e: ProviderError) {
                stats.tried++
                stats.errors++
                stats.failures += song to e
                onError?.invoke(song, e)
                if (stopOn.any { it.isInstance(e) }) return@sequence
                continue
            }
            stats.tried++
            yield(song to outcome)
        }
    }

    /** [eachSong] over a list, read whole first, every turn's work done inside [turn] (so a provider's error of that
     * work is the turn's, on the ladder): the [stats] once the pass is over. A pass whose filter must see what the
     * turns before did, or whose work on an answer must stay off the ladder, takes the sequence's. */
    fun <S : PassStats> eachSong(songs: List<SongRow>, stats: S, site: String,
                                 stopOn: Set<KClass<out ProviderError>> = emptySet(),
                                 onError: ((SongRow, ProviderError) -> Unit)? = null, turn: (SongRow) -> Unit): S {
        eachSong(songs.asSequence(), stats, site, stopOn, onError, turn).forEach { _ -> }
        return stats
    }
}
