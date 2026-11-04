package io.github.danielhp95.caracole.core.py

/**
 * Whether a text is an IP address as Python 3.14's `ipaddress.ip_address` reads one: IPv4 as four decimal octets
 * (ASCII, no leading zero, at most 255), else IPv6 (hextets, one `::`, an IPv4 tail, a `%scope`). No DNS, ever.
 */
object IpAddress {
    /** 4 or 6, or null for neither. */
    fun version(text: String): Int? = when {
        v4(text) -> 4
        v6(text) -> 6
        else -> null
    }

    private fun v4(text: String): Boolean = '/' !in text && v4Int(text) != null

    private fun v4Int(text: String): Long? {
        if (text.isEmpty()) return null
        val octets = text.split('.')
        if (octets.size != 4) return null
        var value = 0L
        for (octet in octets) {
            if (octet.isEmpty() || !octet.all { it in '0'..'9' } || octet.length > 3) return null
            if (octet != "0" && octet[0] == '0') return null
            val n = octet.toInt()
            if (n > 255) return null
            value = value * 256 + n
        }
        return value
    }

    private fun v6(text: String): Boolean {
        if ('/' in text) return false
        val percent = text.indexOf('%')
        val address = if (percent >= 0) {
            val scope = text.substring(percent + 1)
            if (scope.isEmpty() || '%' in scope) return false
            text.substring(0, percent)
        } else {
            text
        }
        return v6Parts(address)
    }

    private const val HEXTETS = 8

    private fun v6Parts(text: String): Boolean {
        if (text.isEmpty() || text.codePointCount(0, text.length) > 45) return false
        // str.split(':', maxsplit=9)
        val parts = ArrayList<String>()
        var rest = text
        while (parts.size < HEXTETS + 1) {
            val at = rest.indexOf(':')
            if (at < 0) break
            parts.add(rest.substring(0, at))
            rest = rest.substring(at + 1)
        }
        parts.add(rest)
        if (parts.size < 3) return false
        if ('.' in parts.last()) {
            val v4 = v4Int(parts.removeAt(parts.size - 1)) ?: return false
            parts.add("%x".format((v4 shr 16) and 0xFFFF))
            parts.add("%x".format(v4 and 0xFFFF))
        }
        if (parts.size > HEXTETS + 1) return false
        var skip: Int? = null
        for (i in 1 until parts.size - 1) {
            if (parts[i].isEmpty()) {
                if (skip != null) return false
                skip = i
            }
        }
        val hi: Int
        val lo: Int
        if (skip != null) {
            var partsHi = skip
            var partsLo = parts.size - skip - 1
            if (parts[0].isEmpty()) {
                partsHi -= 1
                if (partsHi != 0) return false
            }
            if (parts.last().isEmpty()) {
                partsLo -= 1
                if (partsLo != 0) return false
            }
            if (HEXTETS - (partsHi + partsLo) < 1) return false
            hi = partsHi
            lo = partsLo
        } else {
            if (parts.size != HEXTETS) return false
            if (parts[0].isEmpty() || parts.last().isEmpty()) return false
            hi = parts.size
            lo = 0
        }
        return (0 until hi).all { hextet(parts[it]) } && (parts.size - lo until parts.size).all { hextet(parts[it]) }
    }

    private fun hextet(text: String): Boolean =
        text.isNotEmpty() && text.length <= 4 && text.all { it in '0'..'9' || it in 'a'..'f' || it in 'A'..'F' }
}
