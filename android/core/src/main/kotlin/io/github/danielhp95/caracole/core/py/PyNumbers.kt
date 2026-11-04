package io.github.danielhp95.caracole.core.py

import java.math.BigInteger

/** float(str), Python 3.14's: Unicode decimal digits, underscores between digits, inf and nan words, spaces
 * stripped; null where Python raises ValueError. */
object PyFloat {
    fun parse(s: String): Double? = TODO("lane py-sites")
}

/** int(str), Python 3.14's (base 10): Unicode decimal digits, underscores, a sign, spaces stripped; null where Python
 * raises ValueError. */
object PyInt {
    fun parse(s: String): BigInteger? = TODO("lane py-sites")
}
