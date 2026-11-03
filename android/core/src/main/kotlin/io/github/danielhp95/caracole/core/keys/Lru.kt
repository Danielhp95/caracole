package io.github.danielhp95.caracole.core.keys

/** functools.lru_cache for a pure function of one key: at most [max] answers kept, the least recently used dropped
 * first; a null answer is kept as any other. Safe across threads; two threads asking at once may both compute. */
internal class Lru<K, V>(private val max: Int) {
    private class Held<V>(val value: V)

    private val map = object : LinkedHashMap<K, Held<V>>(64, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<K, Held<V>>): Boolean = size > max
    }

    fun get(key: K, make: (K) -> V): V {
        synchronized(map) { map[key] }?.let { return it.value }
        val value = make(key)
        synchronized(map) { map[key] = Held(value) }
        return value
    }
}
