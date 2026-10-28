# A harmonica tab's notation, chosen by score

27 Oct 2026. Step 3 of the report "Better harmonica tab parsing" (`.superpowers/reports/`), and its section "Keep
every unread token in place, and say how the tab was read". Building it.

## Why

caracole reads every harmonica tab in harptabs.com's key, as regular expressions baked into harptab.py. The owner's
Spokey Dokey writes `3b` for blow 3, `3*d` for draw 3 bent and `-` between notes, and says so in a legend at its
foot. caracole read it as bent blows no harmonica plays, dropped what it couldn't read without a trace, drew the
legend as sung words, and still called the tab readable: its one test of a reading is how much text it explains, and
a wrong reading explained 86 % of a line. The page then told the reader "4 blow · −4 draw · −3′ bent", which the
tab's own legend contradicts.

## The notation is data

A `Symbol` is a mark as tabs write it, what it means and where it is written:

- `text`: `-`, `b`, `'`, `"`, `(w)`;
- `means`: a breath (`blow`, `draw`), `bend` (with `count`, the semitones: `"` is two), `over`, `slide`, `join`
  (notes run together), `together` (holes played at once), or an effect (`hold`, `wah`, `vibrato`, `shake`,
  `trill`…);
- `at`: `before` the hole, `after` it, `around` it (brackets), or `between` two holes.

A `Notation` is a name, its symbols, the breath of a hole written with no mark (`bare`: blow, draw, or none, when a
hole needs a letter), and whether its letters read in either case (`fold`). harptab.py compiles each notation into
its tokenizer (a hole is any run of its before-symbols, a number, any run of its after-symbols; brackets hold one
hole or several; between-symbols join two), cached by the notation, in place of the fixed `_HOLE`, `_INNER`,
`_GROUP`, `_COMMA_CHORD` and the `parens_draw` flag. What every notation shares stays a constant: holds (`----`,
`....`, `___`, `(hold)`), bars, repeat marks, a leading label.

The presets, in the order of how common they are on harptabs.com (the corpus of 146 tabs: signs 104, brackets 13,
letters 2, signs after 1, Barrett none):

| Preset | Blow | Draw | Bend | Besides | Who writes it |
|---|---|---|---|---|---|
| `signs` | `4`, `+4` | `-4` `−4` `–4` | `'` `’` `` ` `` `b` after, `"` `”` two, `b` before | `o` overblow, `<` `*` slide, `( )` chord, `{ }` shake, `[ ]` split | harptabs.com's key, harmonica.com |
| `brackets` | `4` | `(4)`, every hole inside `( )` | `'` `b` after, `"` two, after the brackets too | `-` joins | Spanish tabs (LaCuerda's "aspirar") |
| `letters` | `4b` `4B` | `4d` `4D` | `*` `'` after | `-` joins, `7,8B` together; a hole with no letter is unread | Harp-L, Harmonica Academy, Heart of Gold; Spokey Dokey |
| `signs after` | `4+`, `4` | `4-` | `'` `"` after | never a sign before a hole (`6-7`), a hold's (`6--`) or glued holes' (`456-`) | Wikibooks' two-sign system |
| `barrett` | `4+` | `4` | `'` `’` `"` after | | David Barrett, Mel Bay |

harp-spellings (steps 1 and 2, merged before this lane finished) dropped into these tables: `"` two bends a symbol of
every preset; `-b3` and `(3)b` fall out of the generic tokenizer (before-symbols in any order, after-symbols on a
lone hole's brackets); its signs after the hole are the `signs after` preset; a single dot a hold, `DOTS`, added to
every candidate in a tab that writes a dot before a hole; a time (`Time: 3/4`, `1:45`) never holes, in every
notation; the chip read as it reads it, Diatonic one more candidate, `signs` with `*` a bend (`STAR_BENDS`), ordered
before `signs` there.

## The score

Each tab is scanned under each candidate notation, and the best kept by **Q = P × T**, as CleverCSV picks a CSV
dialect:

- the lines scored are those any candidate reads as a line of holes (a row, or three holes and 40 % of it read), so
  every candidate is judged on the same text;
- **P**, the share of those lines' characters (spaces aside) the notation explains;
- **T**, the share of the holes it reads that a Richter harp plays (`harp.hole_note`: how deep each hole bends, the
  overblows). A slide counts as playable unless the page's chip says Diatonic. A soft score, never a filter: a
  tabber's own slip (`1**d`) costs a little and blocks nothing.

Ties go to the commonest notation. The margin is the winner's score over the best candidate that reads the tab
differently (two notations that read every hole alike are no rival: `signs` and `brackets` on a tab of bare numbers).
Two thresholds, set from the corpus so that no tab read fully today reads worse (`TAB_Q` 0.5: the lowest Q of a
diatonic tab of the 146 is 0.63; `MARGIN` 0.05; `ROW_TRUST` 0.5, under the weakest row of a tab read fully today,
0.6, a tabber's own `-5b` twice; `LEGEND_WEIGHT` 0.2):

- the tab is drawn when Q reaches `TAB_Q`, else it is its text as written, as an unreadable tab is today;
- a notation less common than another that reads the tab differently must beat it by `MARGIN`, else the evidence for
  the unusual reading is thin and the tab is its text as written. A common reading needs no margin: a tab of bare
  numbers is harptabs.com's blows, not Barrett's draws.

**Rows.** Each line read as holes is a `Row` with a confidence, its own P × T. A row at `ROW_TRUST` or more is drawn;
a row under it, and a line that holds holes but reads under 75 % (`missed` today, then prose or words), is its text
as written in place, its words line under it as written too. `Tab.readable` stays the whole tab's gate: drawn rows,
a confident reading, no chromatic harp.

## The legend

A legend block is two or more adjacent lines of `SYM = meaning`, `SYM: meaning`, `SYM - meaning` or `SYM   meaning`
(columns), wherever they sit, each meaning holding a word of a small dictionary, read case-insensitively with its
accents folded: blow, exhale, soplar…; draw, inhale, aspirar…; bend, bending; overblow; slide, button; hold, held,
extend; wah; vibrato, tremolo; shake, warble; trill, trino; chord, together; join, ligado; bar; rest. `Key: D` and
an address are no legend line. A placeholder stands for a hole: `x`, `X`, `#`, `N`, `numero`, or a hole number
(`(x) = aspirar` is brackets meaning draw; `x = soplar` the bare breath).

The legend is evidence, never an order:

- it makes one more candidate: the preset that agrees with most of its entries, changed as the legend says (its
  symbols' meanings; a letter the legend writes in one case and the tab in the other read in both; a symbol no
  preset places, `(w) = Wah effect`, an effect shown on its hole);
- each candidate's score is multiplied by `1 + LEGEND_WEIGHT × agreement`, its share of the legend's entries (those
  the tab's lines use) it reads as the legend says. The legend's own candidate agrees with all of them; a clearly
  better reading still wins, as a legend pasted from elsewhere would be.

Its lines are a `Legend` on the page, never words sung to the same tune.

## The page

- **Read as.** The header's fixed "4 blow · −4 draw · −3′ bent" becomes the notation used, its symbols as the tab
  writes them, those the tab uses: "Read as: b blow · d draw · * bend · (w) wah · (h) hold, from the tab's own
  legend", or "Read as: 4 blow · - draw · ' bend, guessed (0.99)", the number Q.
- **Nothing read is lost.** A row is its groups and its unread spans, each at its column: `$`, `(DV)`, the first
  hole of `3-4b` (a number with no letter, in a notation that needs one) are shown verbatim, muted, in place, never
  guessed. Effects are small labels on their hole ("wah"; a hold is the page's `…`); joins (`3*d-3d`) are kept, a mark
  between the two.
- **Per row.** A row read with low confidence is its text as written, in place; the rest of the tab is drawn.
- **The data.** A group is `[kind, holes]` as today, with a third entry where it has more: `{"fx": ["wah"],
  "join": 1}`; harptab.js's `drawGroup` draws the effects from it, so Notes and the harp's −/+ keep them. The data's
  `reading` says how the tab was read (`name`, `source`, `q`, `margin`, `said`). Unread spans are the page's text,
  never in the data, never tapped or played.
- The foot says caracole placed each hole over its syllable only where a row has words.

The page keeps its rules: its scripts and styles by hash, `createElement` alone, no music theory in harptab.js.

## The calls

- `letters` is one preset for `4B`/`4D` and `4b`/`4d`, its letters folded: Heart of Gold and Spokey Dokey read the
  same either way, and a tie between them goes to the commoner anyway. A hole with no letter in it is unread.
- Under `signs`, brackets round a lone unsigned hole (`(5)`) explain nothing: the score is what tells a Spanish tab
  (no `-` anywhere) from a signs tab that brackets a hole once, which today's count did.
- Under `brackets`, every unsigned hole in brackets is a draw, `(45)` too ("se aspiran el 4 y 5").
- `(w)` and `(h)` mean nothing until a legend says so: Spokey Dokey with its legend deleted shows them as written.
- A hold named by a legend (`(h) = Hold`) is drawn as the page's hold, `…`; other effects as a label.
- `3-4b`: the join is kept, the `3` unread; no breath is shared along a join.
- The page's chip goes in as `parse(…, harp=…)` (harp-spellings): Chromatic is a chromatic tab; Diatonic makes a
  slide unplayable in T.
- `parse(body, notation=…)` takes a notation given (a preset, or a preset changed by a small table, as the legend
  changes one): no score is kept for the others, its source "pinned". The owner's override builds on it.

## Not here

Layout tolerance (words over their holes, prose inside hole lines) and the owner's override page come in a later
lane, on this `Notation`.
