package io.github.danielhp95.caracole.core.search.internal.ug

import io.github.danielhp95.caracole.core.py.Py

/**
 * Python's sort keys, for the ports of search.py: a key is a tuple compared item by item, a float by IEEE (so -0.0
 * and 0.0 are equal, as `-0 * share` and `0 * share` are in Python, where Double.compareTo would part them), an int
 * as an int, a str by code point ([Py.CODE_POINT_ORDER], never String.compareTo), a bool False first, a tuple (a
 * List) item by item, the shorter first on a tie. Python's sort is stable, and so is Kotlin's sortedWith.
 */
internal object PyKeys {
    /** Python's `<` between two values of one key's place. */
    fun compare(a: Any?, b: Any?): Int = when {
        a is Double || b is Double || a is Float || b is Float -> {
            val x = (a as Number).toDouble()
            val y = (b as Number).toDouble()
            if (x < y) -1 else if (x > y) 1 else 0
        }
        a is Number && b is Number -> a.toLong().compareTo(b.toLong())
        a is String && b is String -> Py.CODE_POINT_ORDER.compare(a, b)
        a is Boolean && b is Boolean -> a.compareTo(b)
        a is List<*> && b is List<*> -> {
            var c = 0
            for (i in 0 until minOf(a.size, b.size)) {
                c = compare(a[i], b[i])
                if (c != 0) break
            }
            if (c != 0) c else a.size.compareTo(b.size)
        }
        a is Pair<*, *> && b is Pair<*, *> -> compare(listOf(a.first, a.second), listOf(b.first, b.second))
        else -> throw IllegalArgumentException("no Python order between $a and $b")
    }

    /** A comparator by the tuple of [keys], as `key=lambda x: (k1(x), k2(x), …)` sorts. */
    fun <T> by(vararg keys: (T) -> Any?): Comparator<T> = Comparator { x, y ->
        for (key in keys) {
            val c = compare(key(x), key(y))
            if (c != 0) return@Comparator c
        }
        0
    }

    /** `items[:n]`: the first n, or for a negative n all but the last -n. */
    fun <T> head(items: List<T>, n: Int): List<T> = if (n >= 0) items.take(n) else items.take(maxOf(items.size + n, 0))

    /** The first item [key] makes least, as Python's `min(items, key=…)`; null for none. */
    fun <T> min(items: Iterable<T>, key: (T) -> Any?): T? {
        var best: T? = null
        var bestKey: Any? = null
        var any = false
        for (item in items) {
            val k = key(item)
            if (!any || compare(k, bestKey) < 0) {
                best = item
                bestKey = k
                any = true
            }
        }
        return best
    }
}
