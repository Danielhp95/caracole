package io.github.danielhp95.caracole.core.ug.internal.rank

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.ug.Candidate

/** How Python's sort orders rank.py's keys: floats as `==` and `<` compare them (−0.0 is 0.0, which Double's own
 * compareTo tells apart), a text's length in code points and texts by code point. */
internal object PyOrder {
    fun floats(a: Double, b: Double): Int = when {
        a == b -> 0
        a < b -> -1
        else -> 1
    }

    /** rank._tiebreak: `(c.version, len(c.tab_id), c.tab_id)`. */
    fun tiebreak(a: Candidate, b: Candidate): Int {
        a.version.compareTo(b.version).takeIf { it != 0 }?.let { return it }
        Py.len(a.tabId).compareTo(Py.len(b.tabId)).takeIf { it != 0 }?.let { return it }
        return Py.CODE_POINT_ORDER.compare(a.tabId, b.tabId)
    }
}
