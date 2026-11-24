package io.github.danielhp95.caracole.core.index

/** A size as the pages say one (sync-words.js's `size`), and a download's "31 of 52 MB": the phone's words for the
 * catalogues' download and a sync's indexes coming. ASCII digits, never a locale's. */
object Sizes {
    /** 0.4 MB, 3.4 MB, 207 MB, 1.2 GB: a megabyte a million bytes, 0.1 MB at least. */
    fun size(bytes: Long): String {
        val b = maxOf(bytes, 0)
        return when {
            b >= GB -> tenths(b, 100_000_000) + " GB"
            b >= WHOLE_MB -> ((b + 500_000) / 1_000_000).toString() + " MB"
            else -> tenths(maxOf(b, 100_000), 100_000) + " MB"
        }
    }

    /** "31 of 52 MB": [got] of [total] bytes, in the unit and the precision [size] says [total] in. */
    fun of(got: Long, total: Long): String {
        val so = when {
            total >= GB -> tenths(got, 100_000_000)
            total >= WHOLE_MB -> ((got + 500_000) / 1_000_000).toString()
            else -> tenths(got, 100_000)
        }
        return "$so of ${size(total)}"
    }

    /** [bytes] in tenths of [tenth] bytes, rounded half up, as "1.2". */
    private fun tenths(bytes: Long, tenth: Long): String {
        val n = (bytes + tenth / 2) / tenth
        return "${n / 10}.${n % 10}"
    }

    /** The sizes from which [size] says gigabytes, and whole megabytes (sync-words.js's 999.5 and 9.95 MB). */
    private const val GB = 999_500_000L
    private const val WHOLE_MB = 9_950_000L
}
