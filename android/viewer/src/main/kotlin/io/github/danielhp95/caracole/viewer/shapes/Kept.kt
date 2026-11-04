package io.github.danielhp95.caracole.viewer.shapes

/**
 * A least-recently-used store of at most [size] answers, as functools.lru_cache(maxsize=size) keeps them: what
 * viewer.shapes, viewer.harp and viewer.winds keep where their Python keeps a bounded cache, so a phone that renders
 * page after page holds no more than Python's process would. Safe across threads; an answer made twice at once is
 * kept once.
 */
internal class Kept<K, V : Any>(private val size: Int) {
    private val map = object : LinkedHashMap<K, V>(64, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<K, V>?): Boolean = this.size > this@Kept.size
    }

    fun getOrPut(key: K, make: () -> V): V {
        synchronized(map) { map[key]?.let { return it } }
        val value = make()
        synchronized(map) { return map.putIfAbsent(key, value) ?: value }
    }
}
