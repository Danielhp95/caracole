package io.github.danielhp95.caracole.viewer.pages.internal

import io.github.danielhp95.caracole.core.py.PyHtml
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.web.Inline

/**
 * page.py's `_page` and `viewer_csp`: a whole page, sheet.html or songbook.html or a harmonica tab's, its head (the
 * title, the icon, the stylesheets and the policy that allows exactly them and the scripts), its body, then its
 * scripts; and the policy a server sends with a page caracole wrote, read back from the page's own `<meta>`.
 */
internal object PageFrame {
    /** _page: [title] marked as a name [names] convert, [styles] in the head, [scripts] after [body], each allowed
     * by its hash. */
    fun page(title: String, body: String, styles: List<String>, scripts: List<String>, names: Names? = null): String {
        val policy = "default-src 'none'; script-src ${scripts.joinToString(" ") { Inline.sha256Source(it) }}; " +
            "style-src ${styles.joinToString(" ") { Inline.sha256Source(it) }}; img-src data:; base-uri 'none'; " +
            "form-action 'none'"
        val size = body.length + styles.sumOf { it.length + 16 } + scripts.sumOf { it.length + 18 } + 2048
        return buildString(size) {
            append("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n")
            append("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n")
            append("<meta name=\"color-scheme\" content=\"light dark\">\n<meta name=\"referrer\" content=\"same-origin\">\n")
            append("<meta http-equiv=\"Content-Security-Policy\" content=\"").append(policy).append("\">\n")
            append(PageConstants.ICON)
            append("<title").append(PageHtml.zhAttr(title, names)).append('>').append(PyText.escape(title)).append("</title>\n")
            styles.forEach { append("<style>").append(it).append("</style>\n") }
            append("</head>\n<body>\n")
            append(body)
            scripts.forEach { append("<script>").append(it).append("</script>\n") }
            append("</body>\n</html>\n")
        }
    }

    /**
     * viewer_csp: the page's own policy, as its `<meta>` holds it, with a sandbox; a page whose policy can't be read
     * (none, not UTF-8, or more than a header's printable ASCII once its entities are read) gets one that runs and
     * loads nothing. Python's pattern is a bytes pattern: it runs here over the bytes read as Latin-1, a character a
     * byte, and the policy found is read back as UTF-8. An entity html.unescape can't read raises, as Python's does.
     */
    fun viewerCsp(page: ByteArray): String {
        val found = PyRe.search(PageConstants.META_POLICY, String(page, Charsets.ISO_8859_1))
        val policy = if (found == null) "" else {
            PyText.utf8(found.groupValues[1].toByteArray(Charsets.ISO_8859_1))?.let(PyHtml::unescape) ?: ""
        }
        return if (PyRe.fullmatch(PageConstants.HEADER_TEXT, policy) != null) {
            "sandbox allow-scripts allow-downloads; $policy"
        } else {
            PageConstants.NOTHING
        }
    }
}
