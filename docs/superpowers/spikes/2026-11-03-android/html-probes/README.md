# HTML probes (2026-11-03)

What caracole's HTML parser, selectolax 1.0.0's `LexborHTMLParser`, does with the markup where parsers part ways, and
what jsoup 1.15.3 does with the same: the evidence for [the HTML parsing spec](../../../specs/2026-11-03-html-parsing.md).
Kept as `.txt`, so nothing runs them.

- `lexbor_probe.py.txt`: `nix develop -c python3 -I lexbor_probe.py`. Its output, at caracole's selectolax:

  ```
  '<div id=t_body><pre>\nA\r\nB\rC</pre></div>' -> 'A\nB\nC'
  "<pre><script>var x='<b>';</script>T<br>U<!--c-->V</pre>" -> "var x='<b>';TUV"
  '<p>&amp頭 &ampx &notit; &#x80; &#0; a&nbsp;b</p>' -> '&頭 &x ¬it; € � a\xa0b'
  "<a title='&ampx &amp=y &amp頭'>x</a>" -> 'x'
  {'title': '&ampx &amp=y &頭'}
  ['one', 'two'] ['one', 'two']          # quirks mode: #b_main and #B_MAIN both match
  [] []                                  # standards mode: neither #b_main nor .foo matches B_MAIN, Foo
  [('a', None), ('-text', '  x '), ('b', None)]
  ```

- `Probe.java.txt`: the same cases through jsoup 1.15.3 (`javac -cp jsoup.jar Probe.java`), which differs from lexbor
  on CR, the legacy references in text, `<br>` (a newline in `wholeText`), script data and the doctypes that set quirks
  mode, and on id and class case: hence a parser of caracole's own, held to lexbor by vectors.
