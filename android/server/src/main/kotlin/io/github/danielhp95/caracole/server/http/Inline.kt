package io.github.danielhp95.caracole.server.http

import io.github.danielhp95.caracole.core.json.PyJson
import kotlinx.serialization.json.JsonElement
import java.security.MessageDigest
import java.util.Base64

/** inline.py: what a page holds inline, a script or a style its Content-Security-Policy allows by its hash, and a
 * block of data for its script. */
object Inline {
    /** A CSP source allowing exactly this inline script or stylesheet: `'sha256-<base64>'` of its UTF-8. */
    fun sha256Source(text: String): String =
        "'sha256-" + Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-256").digest(text.toByteArray())) + "'"

    /**
     * [data] as a `<script type="application/json">` block with this id, and a line break. Every `<` in the JSON is
     * written `\u003c`, which JSON reads back as `<`: no text in it can end the block or open another element. The
     * JSON is `json.dumps(ensure_ascii=False)`'s, compact (PyJson): a float in [data] is Python's only when it came of
     * a text Python wrote or of PyJson.float, never of JsonPrimitive(Double).
     */
    fun jsonBlock(id: String, data: JsonElement): String =
        "<script type=\"application/json\" id=\"${PyText.escape(id)}\">" +
            PyJson.dumps(data, compact = true).replace("<", "\\u003c") + "</script>\n"
}
