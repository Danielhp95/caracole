package io.github.danielhp95.caracole.core.names

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow

/** song_names.py: the artist and the title a free text names (lane song-names). */
object SongNames {
    fun clean(text: String): String = TODO("lane song-names")
    fun cleanChannel(channel: String): String = TODO("lane song-names")
    fun readNames(db: Db?, text: String, songs: List<SongRow>, channel: String? = null): Pair<String, String>? =
        TODO("lane song-names")
}
