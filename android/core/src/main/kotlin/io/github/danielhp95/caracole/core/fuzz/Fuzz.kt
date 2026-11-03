package io.github.danielhp95.caracole.core.fuzz

/** rapidfuzz 3.14.5 on rapidfuzz-cpp 3.3.4, on code points, processor=None (lane fuzz). */
object Fuzz {
    data class Alignment(val score: Double, val srcStart: Int, val srcEnd: Int, val destStart: Int, val destEnd: Int)
    data class Extracted(val choice: String, val score: Double, val index: Int)

    fun ratio(a: String, b: String): Double = TODO("lane fuzz")
    fun tokenSortRatio(a: String, b: String): Double = TODO("lane fuzz")
    fun partialRatioAlignment(a: String, b: String): Alignment = TODO("lane fuzz")

    /** process.extract with scorer=fuzz.ratio. */
    fun extract(query: String, choices: List<String>, scoreCutoff: Double, limit: Int?): List<Extracted> =
        TODO("lane fuzz")
}
