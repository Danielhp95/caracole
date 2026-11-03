package io.github.danielhp95.caracole.core.db

/**
 * How many statements a text of SQL holds, as SQLite's own `sqlite3_complete` reads it (complete.c): its tokens
 * (whitespace and comments, `;`, a word, anything else, a quoted string or name being one), and its state machine,
 * where a statement ends at a `;`, except in `CREATE [TEMP|TEMPORARY] TRIGGER`, whose body's statements end it only
 * at `; END ;`. The bundled driver prepares a text's first statement and drops the rest without a word, where Python's
 * sqlite3 refuses a second, so [Db] refuses a text of more than one ([one]).
 *
 * ASCII arithmetic alone, no JDK text API.
 */
internal object Statements {
    private const val SEMI = 0
    private const val WS = 1
    private const val OTHER = 2
    private const val EXPLAIN = 3
    private const val CREATE = 4
    private const val TEMP = 5
    private const val TRIGGER = 6
    private const val END = 7

    // complete.c's trans[state][token]: 0 INVALID, 1 START, 2 NORMAL, 3 EXPLAIN, 4 CREATE, 5 TRIGGER, 6 SEMI, 7 END.
    private val TRANS = arrayOf(
        intArrayOf(1, 0, 2, 3, 4, 2, 2, 2),
        intArrayOf(1, 1, 2, 3, 4, 2, 2, 2),
        intArrayOf(1, 2, 2, 2, 2, 2, 2, 2),
        intArrayOf(1, 3, 3, 2, 4, 2, 2, 2),
        intArrayOf(1, 4, 2, 2, 2, 4, 5, 2),
        intArrayOf(6, 5, 5, 5, 5, 5, 5, 5),
        intArrayOf(6, 6, 5, 5, 5, 5, 5, 7),
        intArrayOf(1, 7, 5, 5, 5, 5, 5, 5),
    )

    /** [sql] holds one statement at most: a second, after the first's `;`, is an IllegalArgumentException. */
    fun one(sql: String) {
        require(count(sql) <= 1) {
            "one statement a call: the bundled SQLite would run the first and drop the rest of: $sql"
        }
    }

    /** The statements of [sql] that hold a token other than whitespace, a comment or `;`. */
    fun count(sql: String): Int {
        var state = 1
        var statements = 0
        var i = 0
        val n = sql.length
        while (i < n) {
            val c = sql[i]
            val token: Int
            when {
                isSpace(c) -> { token = WS; i++ }
                c == '-' && i + 1 < n && sql[i + 1] == '-' -> {
                    while (i < n && sql[i] != '\n') i++
                    token = WS
                }
                c == '/' && i + 1 < n && sql[i + 1] == '*' -> {
                    i += 2
                    while (i < n && !(sql[i] == '*' && i + 1 < n && sql[i + 1] == '/')) i++
                    i = minOf(n, i + 2)
                    token = WS
                }
                c == ';' -> { token = SEMI; i++ }
                c == '\'' || c == '"' || c == '`' -> {
                    // A quote doubled is one inside: the loop reads it as the end and a new start.
                    i++
                    while (i < n && sql[i] != c) i++
                    i++
                    token = OTHER
                }
                c == '[' -> {
                    while (i < n && sql[i] != ']') i++
                    i++
                    token = OTHER
                }
                isWord(c) -> {
                    val start = i
                    while (i < n && isWord(sql[i])) i++
                    token = keyword(sql, start, i)
                }
                else -> { token = OTHER; i++ }
            }
            val next = TRANS[state][token]
            if (next == 1 && token == SEMI && state != 0 && state != 1) statements++
            state = next
        }
        if (state != 0 && state != 1) statements++
        return statements
    }

    // sqlite3Isspace: the space and \t \n \v \f \r.
    private fun isSpace(c: Char): Boolean = c == ' ' || c in '\t'..'\r'

    // IdChar: a letter, a digit, '_', '$', or any character past ASCII.
    private fun isWord(c: Char): Boolean =
        c in 'a'..'z' || c in 'A'..'Z' || c in '0'..'9' || c == '_' || c == '$' || c.code >= 0x80

    private fun keyword(sql: String, start: Int, end: Int): Int = when {
        named(sql, start, end, "create") -> CREATE
        named(sql, start, end, "trigger") -> TRIGGER
        named(sql, start, end, "temp") || named(sql, start, end, "temporary") -> TEMP
        named(sql, start, end, "end") -> END
        named(sql, start, end, "explain") -> EXPLAIN
        else -> OTHER
    }

    /** `sql[start until end]` is [word] (lower-case ASCII), in any case. */
    private fun named(sql: String, start: Int, end: Int, word: String): Boolean {
        if (end - start != word.length) return false
        for (k in word.indices) {
            val c = sql[start + k]
            val lower = if (c in 'A'..'Z') c + ('a' - 'A') else c
            if (lower != word[k]) return false
        }
        return true
    }
}
