package io.github.danielhp95.caracole.core.py

/** Python's format specs and rounding, the ones caracole writes text with. */
object PyFormat {
    /** f'{x:0W.Nf}': [digits] after the point, at least [width] wide, padded with zeros when [zero]. */
    fun fixed(x: Double, digits: Int, width: Int = 0, zero: Boolean = false): String = TODO("lane py-format")

    /** f'{x:.N%}'. */
    fun percent(x: Double, digits: Int): String = TODO("lane py-format")

    /** round(x): to the nearest whole number, a half to the even one. */
    fun roundHalfEven(x: Double): Long = TODO("lane py-format")
}
